"""채널 B 덩어리를 채널 A 트랙에 붙일지 판정한다 (06장 6.5 채널 B (a), D-197, D-256, D-314).

ROI에 닿은 덩어리가 사람·움직이는 차의 일부(손 등)이면 그 트랙에 붙이고,
붙일 트랙이 없으면 (b)로 넘겨 클래스 없는 트랙을 만든다. 좌표는 모두 줄인 프레임 기준이다.
"""

import math

from pipeline.candidates.channel_a import TrackBox
from pipeline.candidates.channel_b import Blob

# 01장 1.6 "0단계 필터 시작값"의 덩어리 붙이기 (D-256).
# 덩어리 픽셀 중 이 비율 이상이 트랙 bbox 안에 있으면 그 트랙의 일부로 본다
BLOB_ATTACH_RATIO = 0.5

# 01장 1.6 "덩어리 붙이기·확장 시작값"의 멈춘 차의 기준 (D-197).
# 최근 STOPPED_WINDOW_SEC 동안 bbox 중심 이동이 bbox 폭의 STOPPED_MOVE_RATIO 미만이면 멈춘 차다
STOPPED_WINDOW_SEC = 1.0
STOPPED_MOVE_RATIO = 0.05

# "차"로 보는 클래스 (D-197). 사람·동물은 멈춰도 붙인다
VEHICLE_CLASSES = ("car", "motorcycle", "bicycle", "truck", "bus")

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
