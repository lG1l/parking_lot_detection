"""채널 B 덩어리를 채널 A 트랙에 붙일지 판정한다 (06장 6.5 채널 B (a), D-197, D-256, D-314).

ROI에 닿은 덩어리가 사람·움직이는 차의 일부(손 등)이면 그 트랙에 붙이고,
붙일 트랙이 없으면 (b)로 넘겨 클래스 없는 트랙을 만든다. 좌표는 모두 줄인 프레임 기준이다.
"""

import math

import numpy as np
import supervision as sv
from trackers import ByteTrackTracker

from pipeline.candidates.s1_base.crop import Crop, to_original
from pipeline.candidates.s1_base.video import SAMPLING_FPS
from pipeline.candidates.s2_motion.channel_b import Blob, Box
from pipeline.candidates.s3_tracks.channel_a import TRACK_CONFIRM_FRAMES, TRACK_START_CONF, TrackBox

# 01장 1.6 "0단계 필터 시작값"의 덩어리 붙이기 (D-256).
# 덩어리 픽셀 중 이 비율 이상이 트랙 bbox 안에 있으면 그 트랙의 일부로 본다
BLOB_ATTACH_RATIO = 0.5

# 01장 1.6 "덩어리 붙이기·확장 시작값"의 멈춘 차의 기준 (D-197).
# 최근 STOPPED_WINDOW_SEC 동안 bbox 중심 이동이 bbox 폭의 STOPPED_MOVE_RATIO 미만이면 멈춘 차다
STOPPED_WINDOW_SEC = 1.0
STOPPED_MOVE_RATIO = 0.05

# "차"로 보는 클래스 (D-197). 사람·동물은 멈춰도 붙인다
VEHICLE_CLASSES = ("car", "motorcycle", "bicycle", "truck", "bus")

# 채널 B 트랙 번호는 추적기 번호에 이 값을 더한다. 채널 A 번호와 겹치지 않게 한다 (D-312)
BLOB_TRACK_ID_OFFSET = 1_000_000
# 추적기에 넣는 신뢰도. 덩어리에는 신뢰도가 없어 늘 새 트랙을 시작할 수 있는 값으로 준다 (D-257)
BLOB_TRACK_CONF = 1.0

# 시각을 소수로 다루다 생기는 오차를 흡수하는 값 (초)
_TIME_EPS = 1e-6

# 트랙 번호 → 최근 STOPPED_WINDOW_SEC 동안의 (시각, 중심 x, 중심 y) 목록. 시간순이다
History = dict[int, list[tuple[float, float, float]]]


def _center(bbox: tuple[float, float, float, float]) -> tuple[float, float]:
    return ((bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2)


def remember_positions(history: History, time_sec: float, tracks: list[TrackBox]) -> None:
    """이 프레임의 트랙 위치를 적고, 최근 STOPPED_WINDOW_SEC보다 오래된 위치를 지운다.

    프레임은 시간순으로 넣는다. 거슬러 돌린 프레임도 빠뜨리지 않고 넣어야 멈춘 차를 바로 알아본다.
    """
    for track in tracks:
        history.setdefault(track.track_id, []).append((time_sec, *_center(track.bbox)))
    oldest = time_sec - STOPPED_WINDOW_SEC - _TIME_EPS
    for track_id in list(history):
        history[track_id] = [entry for entry in history[track_id] if entry[0] >= oldest]
        if not history[track_id]:
            # 1초 넘게 안 보인 트랙이다. 추적기도 이때 트랙을 끝낸다
            del history[track_id]


def is_stopped_vehicle(track: TrackBox, history: History) -> bool:
    """멈춘 차인가. 멈춘 차에는 덩어리를 붙이지 않는다 (문 덩어리가 차에 묻히지 않게, D-197)."""
    if track.cls not in VEHICLE_CLASSES:
        return False
    positions = history.get(track.track_id, [])
    if len(positions) <= 1:
        # 막 확정된 트랙은 움직였는지 알 수 없다. 틀렸을 때 덜 위험한 멈춘 차로 본다 (D-314 결정 5)
        return True
    # 지금 중심과, 최근 1초 안에서 가장 오래된 위치의 중심 사이 거리 (D-314 결정 4)
    _, old_x, old_y = positions[0]
    now_x, now_y = _center(track.bbox)
    width = track.bbox[2] - track.bbox[0]
    return math.hypot(now_x - old_x, now_y - old_y) < width * STOPPED_MOVE_RATIO


def overlap_ratio(blob: Blob, bbox: tuple[float, float, float, float]) -> float:
    """덩어리 픽셀 중 bbox 안에 든 비율 (0~1). bbox는 가장 가까운 픽셀 경계로 맞춘다."""
    blob_x1, blob_y1, blob_x2, blob_y2 = blob.bbox
    # 덩어리 bbox와 트랙 bbox가 겹치는 사각형
    x1, y1 = max(blob_x1, round(bbox[0])), max(blob_y1, round(bbox[1]))
    x2, y2 = min(blob_x2, round(bbox[2])), min(blob_y2, round(bbox[3]))
    if x1 >= x2 or y1 >= y2:
        return 0.0
    # blob.mask는 덩어리 bbox만큼 잘린 그림이라 자리를 덩어리 bbox 기준으로 옮긴다
    inside = blob.mask[y1 - blob_y1 : y2 - blob_y1, x1 - blob_x1 : x2 - blob_x1].sum()
    return float(inside) / blob.area


def attach_target(blob: Blob, tracks: list[TrackBox], history: History) -> int | None:
    """덩어리를 붙일 채널 A 트랙의 번호. 붙일 트랙이 없으면 None이다 ((b)로 넘긴다).

    멈춘 차를 먼저 빼고, 남은 트랙 중 덩어리가 가장 많이 든 트랙을 고른다 (D-314 결정 3).
    먼저 고르고 나서 빼면 손 덩어리가 사람 대신 그 밑의 주차된 차에 걸린다.
    """
    best_id, best_ratio = None, 0.0
    # 번호 순으로 보고 더 클 때만 바꾸므로, 비율이 같으면 번호가 작은 트랙이 남는다
    for track in sorted(tracks, key=lambda track: track.track_id):
        if is_stopped_vehicle(track, history):
            continue
        ratio = overlap_ratio(blob, track.bbox)
        if ratio > best_ratio:
            best_id, best_ratio = track.track_id, ratio
    return best_id if best_ratio >= BLOB_ATTACH_RATIO else None


def open_blob_tracker() -> ByteTrackTracker:
    """채널 B용 추적기. 채널 A와 번호가 섞이지 않게 따로 만들고 설정은 같게 둔다 (D-257)."""
    return ByteTrackTracker(
        frame_rate=SAMPLING_FPS,
        track_activation_threshold=TRACK_START_CONF,
        high_conf_det_threshold=TRACK_START_CONF,
        minimum_consecutive_frames=TRACK_CONFIRM_FRAMES,
    )


def track_boxes(tracker: ByteTrackTracker, boxes: list[Box]) -> sv.Detections:
    """사각형들을 채널 B 추적기에 넣는다. 좌표는 줄인 프레임 기준이다.

    사각형이 없는 프레임에도 불러야 추적기가 "놓친 프레임"을 세어 트랙을 끝낸다 (06장 6.5 규칙 5).
    시각은 주지 않는다. 프레임 시각을 주는 것은 채널 A 추적기만의 규칙이다 (D-313).
    """
    detections = sv.Detections(
        xyxy=np.array(boxes, dtype=np.float32).reshape(-1, 4),
        confidence=np.full(len(boxes), BLOB_TRACK_CONF, dtype=np.float32),
    )
    return tracker.update(detections)


def blob_track_boxes(tracked: sv.Detections) -> list[tuple[float, float, float, float]]:
    """확정된 클래스 없는 트랙의 사각형을 줄인 프레임 좌표 그대로 꺼낸다. blob_track_lines와 순서가 같다.

    차 영역 키는 줄인 프레임에서 재므로 원본 좌표로 바꾸기 전의 사각형이 필요하다 (D-262).
    """
    return [
        tuple(float(v) for v in xyxy)
        for xyxy, tracker_id in zip(tracked.xyxy, tracked.tracker_id)
        if tracker_id >= 0
    ]


def blob_track_lines(tracked: sv.Detections, time_sec: float, crop: Crop) -> list[dict]:
    """채널 B 추적기가 돌려준 결과를 클래스 없는 트랙 줄로 바꾼다 (04장 4.8)."""
    lines = []
    for xyxy, tracker_id in zip(tracked.xyxy, tracked.tracker_id):
        if tracker_id < 0:
            # 아직 확정되지 않은 트랙이다 (D-255)
            continue
        x1, y1 = to_original((xyxy[0], xyxy[1]), crop)
        x2, y2 = to_original((xyxy[2], xyxy[3]), crop)
        lines.append(
            {
                "t": round(time_sec, 3),
                "track_id": int(tracker_id) + BLOB_TRACK_ID_OFFSET,
                # 클래스와 신뢰도는 쓰지 않는다. 이 둘이 없는 줄이 채널 B 줄이다 (D-257)
                "bbox": [round(x1), round(y1), round(x2), round(y2)],
            }
        )
    return lines
