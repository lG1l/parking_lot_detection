"""채널 A·B를 돌려 트랙 파일과 YOLO 구간 목록을 만든다 (3·4단계, D-310, D-316). 명령의 진입점이다.

영상을 한 번 읽으며 프레임마다 MOG2(채널 B) → 켜고 끄기 판정 → YOLO + ByteTrack(채널 A)
→ 덩어리 붙이기 → 채널 B 추적기를 돈다.
YOLO를 켜는 순간에는 링 버퍼에 들고 있던 지난 프레임부터 먼저 돌린다 (06장 6.5 규칙 1, D-247).
그리기는 탐지가 끝난 뒤 영상을 한 번 더 읽어 한다. MOG2와 YOLO는 다시 돌리지 않는다.

실행 (pipeline/ 폴더에서):
    uv run python -m pipeline.candidates.s3_tracks.track_preview \
        <영상> <입력 JSON> <모델 가중치> <출력 폴더> [장면 파일]
"""

import json
import os
import sys
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import TextIO

import cv2
import numpy as np
from trackers import ByteTrackTracker

from pipeline.candidates.s1_base.crop import Crop, CropError, crop_frame, to_original
from pipeline.candidates.s1_base.inputs import InputError, load_input
from pipeline.candidates.s1_base.preview import (
    GREEN,
    RED,
    WHITE,
    _draw_time,
    _format_time,
    draw_labels,
    roi_contours,
    video_size,
)
from pipeline.candidates.s1_base.roi import Roi, RoiError, build_roi
from pipeline.candidates.s1_base.video import SAMPLING_FPS, iter_analysis_frames
from pipeline.candidates.s2_motion.channel_b import (
    MOG2_STABLE_SEC,
    SHADOW,
    Blob,
    Box,
    FrameRecord,
    boxes_for_tracker,
    clean_foreground,
    create_mog2,
    find_blobs,
    group_blobs,
    has_oversized_blob,
    has_roi_motion,
    merge_motion_ranges,
)
from pipeline.candidates.s2_motion.motion_preview import (
    _BLOB_ALPHA,
    _LABEL_GAP,
    DARK,
    GRAY,
    SCENE_BLUE,
    YELLOW,
    Scene,
    _blob_to_original,
    _range_at,
    _scene_at,
    _zone_labels,
    attach_timeline,
    draw_zones,
    load_scenes,
    make_timeline,
)
from pipeline.candidates.s3_tracks.blob_tracks import (
    History,
    attach_target,
    blob_track_boxes,
    blob_track_lines,
    is_stopped_vehicle,
    open_blob_tracker,
    remember_positions,
    track_boxes,
)
from pipeline.candidates.s3_tracks.car_region import (
    BaseRegion,
    CarSpot,
    FramePixels,
    Polygon,
    base_region,
    build_car_spot,
    car_keys,
    pick_my_car,
    redraw,
    region_polygons,
)
from pipeline.candidates.s3_tracks.channel_a import (
    ChannelA,
    ModelError,
    TrackBox,
    open_channel_a,
    process_frame,
)
from pipeline.candidates.s3_tracks.motion_px import (
    blobs_moved_mask,
    changed_pixels,
    grow_bbox,
    moved_in_bbox,
    moved_in_blob,
    to_gray,
)
from pipeline.candidates.s3_tracks.yolo_switch import (
    YOLO_BEFORE_SEC,
    Decision,
    YoloRange,
    YoloSwitch,
)

# 링 버퍼에 담는 줄인 프레임 수. 지금 프레임을 빼고 "거슬러 올라가는 시간"만큼이다 (D-247)
RING_FRAMES = YOLO_BEFORE_SEC * SAMPLING_FPS

# (시각, 줄인 프레임)
TimedFrame = tuple[float, np.ndarray]

# 이름표 한 개: (글, 왼쪽 위 좌표, BGR 색). preview.draw_labels가 받는 모양이다
Label = tuple[str, tuple[int, int], tuple[int, int, int]]

# ROI에 닿은 덩어리 하나의 붙이기 결과 (D-314, D-315). 파일에는 쓰지 않는다 (D-316 결정 3)
ATTACHED = "붙음"  # 채널 A 트랙에 붙었다
PASSED = "넘김"  # 붙을 트랙이 없어 채널 B 추적기에 넣는 사각형이 됐다
SKIPPED = "건너뜀"  # MOG2 안정 전이거나 덩어리 상한에 걸려 넣지 않았다
BLOB_STATUSES = (ATTACHED, PASSED, SKIPPED)

# 트랙 색. 색상환(0~179)을 이 걸음으로 돌아 이웃 번호끼리 색이 멀어지게 한다
_HUE_STEP = 47
_TRACK_COLOR_VALUE = 190  # 흰 글씨가 읽히게 조금 어둡게 한다
_TRACK_LINE = 2

# 붙이기 결과별 덩어리 칠 색 (BGR)
_STATUS_COLORS = {ATTACHED: GREEN, PASSED: RED, SKIPPED: GRAY}
_FED_BOX_LINE = 1  # 채널 B 추적기에 넣은 사각형 (얇은 흰 선)
_BLOB_TRACK_LINE = 4  # 클래스 없는 트랙 (굵은 흰 선)

# 내 차 영역 표시 (BGR). 앞 단계의 색(주황·하늘·자홍·노랑·초록·빨강·회색·흰색·파랑)과 겹치지 않게 골랐다
BROWN = (40, 80, 140)  # 내 차 자리 (얇은 테두리)
PURPLE = (200, 50, 140)  # 구간의 기준 영역 (테두리), 그 프레임의 내 차 영역 (옅은 칠)
_CAR_SPOT_LINE = 1
_BASE_REGION_LINE = 2
_MY_CAR_ALPHA = 0.3  # 전경 칠(0.5)보다 옅게 해서 밑의 차와 전경 칠이 보이게 한다

# 트랙 이름표 뒤에 붙이는 움직인 픽셀 수·차 영역 키와 짧은 이름
_CAR_KEY_NAMES = (
    ("moved_px", "mv"),
    ("car_fg_px", "fg"),
    ("car_front_fg", "fr"),
    ("car_out_fg", "out"),
    ("car_lost_px", "lost"),
)


@dataclass(frozen=True)
class BlobFrame:
    """분석 프레임 한 장의 채널 B 결과. 확인용 영상에 그릴 때만 쓴다. 좌표는 원본 기준이다."""

    # ROI에 닿은 덩어리마다 (바깥 테두리, 붙이기 결과)
    blobs: list[tuple[np.ndarray, str]]
    boxes: list[Box]  # 채널 B 추적기에 넣은 사각형
    outside: list[np.ndarray]  # ROI에 닿지 않은 덩어리의 바깥 테두리 (판정하지 않은 MOG2 전경)


@dataclass
class DetectResult:
    """탐지를 끝까지 돌린 뒤 남는 것. 트랙 줄은 돌면서 파일에 바로 쓰므로 여기 없다."""

    ranges: list[YoloRange]  # YOLO를 돌린 구간 (시간순)
    yolo_frames: list[int] = field(default_factory=list)  # 구간마다 YOLO를 돌린 프레임 수
    # 구간마다의 기준 영역 다각형 목록. 내 차를 찾지 못한 구간은 빈 목록이다 (D-319)
    car_regions: list[list[Polygon]] = field(default_factory=list)
    track_ids: set[int] = field(default_factory=set)  # 트랙 파일에 나온 트랙 번호
    roi_motion: list[bool] = field(default_factory=list)  # 분석 프레임마다의 ROI 움직임 여부
    times: list[float] = field(
        default_factory=list
    )  # 분석 프레임마다의 시각 (roi_motion과 자리가 같다)
    duration_sec: float = 0.0  # 마지막 분석 프레임 시각
    # ROI에 닿은 덩어리 수 (붙이기 결과별). 영상 전체를 더한 값이다
    blob_counts: dict[str, int] = field(default_factory=lambda: dict.fromkeys(BLOB_STATUSES, 0))
    # 클래스 없는 트랙 번호 → [처음 시각, 마지막 시각, 줄 수]
    blob_tracks: dict[int, list] = field(default_factory=dict)
    blob_frames: list[BlobFrame] = field(default_factory=list)  # 분석 프레임마다의 채널 B 결과
    # YOLO를 돌린 프레임의 시각(소수 셋째 자리) → 그 프레임 내 차 영역의 테두리 (원본 좌표).
    # 내 차를 찾지 못한 프레임은 None이다. 확인용 영상과 터미널 요약에 쓴다
    my_car: dict[float, list[np.ndarray] | None] = field(default_factory=dict)

    @property
    def frame_count(self) -> int:
        """분석 프레임 수."""
        return len(self.roi_motion)


# ---------- ① 탐지 ----------


def _find_frame_blobs(
    mog2: cv2.BackgroundSubtractorMOG2, small: np.ndarray, roi: Roi
) -> tuple[list[Blob], FramePixels]:
    """줄인 프레임 한 장을 MOG2에 넣고 덩어리를 찾는다 (채널 B).

    차 영역 키를 잴 전경·그림자 그림도 함께 돌려준다. 덩어리를 만든 전경과 같은 그림이다 (D-319 결정 3).
    """
    raw = mog2.apply(small)
    binary = clean_foreground(raw)
    return find_blobs(binary, roi.mask), FramePixels(binary > 0, raw == SHADOW)


def judge_blobs(
    blobs: list[Blob],
    shape: tuple[int, ...],
    time_sec: float,
    tracks: list[TrackBox],
    history: History,
) -> tuple[list[str | None], list[Box], list[int | None]]:
    """덩어리마다 붙이기 결과를 정하고, 채널 B 추적기에 넣을 사각형을 고른다.

    결과 목록은 blobs와 자리가 같다. ROI에 닿지 않은 덩어리는 판정하지 않아 None이다 (D-314 결정 1).
    마지막 목록은 덩어리마다 붙은 채널 A 트랙의 번호다 (붙지 않았으면 None).
    붙은 덩어리의 움직인 픽셀을 그 트랙에 세려면 번호가 필요하다 (D-333 나-1).
    """
    targets: list[int | None] = [None] * len(blobs)
    if time_sec < MOG2_STABLE_SEC:
        # 안정 전 전경은 믿을 수 없어 채널 B 추적기에 아무것도 넣지 않는다 (D-315 결정 4)
        return [SKIPPED if blob.touches_roi else None for blob in blobs], [], targets
    statuses: list[str | None] = [None] * len(blobs)
    attached: set[int] = set()
    groups = group_blobs(blobs, shape)
    for group in groups:
        oversized = has_oversized_blob(blobs, group, shape)
        for index in group:
            if not blobs[index].touches_roi:
                continue
            targets[index] = attach_target(blobs[index], tracks, history)
            if targets[index] is not None:
                statuses[index] = ATTACHED
                attached.add(index)
            else:
                # 상한에 걸린 묶음은 추적기에 넣지 않는다 (D-315 결정 3)
                statuses[index] = SKIPPED if oversized else PASSED
    return statuses, boxes_for_tracker(blobs, groups, attached, shape), targets


def _box_to_original(box: Box, crop: Crop) -> Box:
    x1, y1 = to_original((box[0], box[1]), crop)
    x2, y2 = to_original((box[2], box[3]), crop)
    return (round(x1), round(y1), round(x2), round(y2))


def _blob_frame(
    blobs: list[Blob], statuses: list[str | None], boxes: list[Box], crop: Crop
) -> BlobFrame:
    """그릴 때 쓸 것만 원본 좌표로 바꿔 남긴다. 덩어리 마스크는 들고 가지 않는다."""
    drawn = [
        (_blob_to_original(blob.contour, crop), status)
        for blob, status in zip(blobs, statuses, strict=True)
        if status is not None
    ]
    outside = [
        _blob_to_original(blob.contour, crop)
        for blob, status in zip(blobs, statuses, strict=True)
        if status is None
    ]
    return BlobFrame(drawn, [_box_to_original(box, crop) for box in boxes], outside)


def _count_blob_tracks(result: DetectResult, lines: list[dict]) -> None:
    """클래스 없는 트랙마다 처음·마지막 시각과 줄 수를 센다 (터미널 요약용)."""
    for line in lines:
        entry = result.blob_tracks.setdefault(line["track_id"], [line["t"], line["t"], 0])
        entry[1] = line["t"]
        entry[2] += 1


def _backfill_frames(ring: deque[TimedFrame], decision: Decision) -> list[TimedFrame]:
    """링 버퍼에서 거슬러 돌릴 프레임을 시간순으로 꺼낸다 (규칙 1·4).

    어느 시각을 돌릴지는 켜고 끄기 판정이 이미 골랐다. 이미 돌린 프레임은 거기에 없다.
    """
    wanted = set(decision.backfill_times)
    return [(time_sec, image) for time_sec, image in ring if time_sec in wanted]


def _write_lines(tracks_file: TextIO, lines: list[dict]) -> None:
    """트랙 줄을 만든 순서대로 한 줄씩 쓴다 (04장 4.8, D-258)."""
    tracks_file.writelines(json.dumps(line, ensure_ascii=False) + "\n" for line in lines)


def _my_car(vehicle_masks: np.ndarray, spot: CarSpot | None) -> np.ndarray | None:
    """그 프레임의 내 차 영역 (다시 그린 모양). 내 차를 찾지 못하면 None이다."""
    if spot is None:
        return None
    picked = pick_my_car(vehicle_masks, spot)
    return None if picked is None else redraw(picked)


def _add_car_keys(
    lines: list[dict],
    bboxes: list[tuple[float, float, float, float]],
    base: BaseRegion | None,
    my_car: np.ndarray | None,
    pixels: FramePixels | None,
    stable: bool,
) -> None:
    """트랙 줄마다 차 영역 키를 더한다 (lines를 직접 고친다). bboxes는 lines와 자리가 같은 줄인 좌표다."""
    for line, bbox in zip(lines, bboxes, strict=True):
        line.update(car_keys(bbox, base, my_car, pixels, stable))


def track_moved_px(
    tracks: list[TrackBox],
    blobs: list[Blob],
    targets: list[int | None],
    changed: np.ndarray,
    roi_in: np.ndarray,
    history: History,
    by_bbox: bool,
) -> list[int]:
    """채널 A 트랙마다의 움직인 픽셀 수. tracks와 자리가 같다 (D-333 나-1·3).

    by_bbox가 거짓이면 그 트랙에 붙은 덩어리 안에서 센다. 붙은 덩어리가 없으면 0이다.
    by_bbox가 참이면(MOG2 전경을 믿을 수 없는 프레임) 넓힌 bbox와 ROI가 겹친 곳에서
    밝기 차이만으로 센다. 멈춘 차는 0이다. bbox 안의 변화가 그 차의 움직임으로 세어지는 것을 막는다 (D-265).
    """
    if by_bbox:
        moved = changed & roi_in
        return [
            0 if is_stopped_vehicle(track, history) else moved_in_bbox(grow_bbox(track.bbox), moved)
            for track in tracks
        ]
    counts = dict.fromkeys((track.track_id for track in tracks), 0)
    for blob, target in zip(blobs, targets, strict=True):
        if target is not None:
            counts[target] += moved_in_blob(blob, changed, roi_in)
    return [counts[track.track_id] for track in tracks]


def blob_track_moved_px(
    bboxes: list[tuple[float, float, float, float]],
    blobs: list[Blob],
    statuses: list[str | None],
    changed: np.ndarray,
    roi_in: np.ndarray,
) -> list[int]:
    """클래스 없는 트랙마다의 움직인 픽셀 수. bboxes와 자리가 같다 (D-333 나-2).

    넘긴 덩어리의 움직인 픽셀 가운데 그 트랙 bbox 안에 든 것을 센다.
    """
    passed = [blob for blob, status in zip(blobs, statuses, strict=True) if status == PASSED]
    moved = blobs_moved_mask(passed, changed, roi_in)
    return [moved_in_bbox(bbox, moved) for bbox in bboxes]


def _add_moved_px(lines: list[dict], counts: list[int] | None) -> None:
    """트랙 줄마다 moved_px를 더한다 (lines를 직접 고친다). counts가 None이면 모두 null이다."""
    for index, line in enumerate(lines):
        line["moved_px"] = None if counts is None else counts[index]


def detect(
    video_path: str,
    roi: Roi,
    spot: CarSpot | None,
    channel: ChannelA,
    blob_tracker: ByteTrackTracker,
    tracks_file: TextIO,
) -> DetectResult:
    """영상을 처음부터 끝까지 한 번 읽으며 채널 A·B의 트랙 줄을 파일에 쓴다."""
    mog2 = create_mog2(SAMPLING_FPS)
    history: History = {}
    switch = YoloSwitch()
    ring: deque[TimedFrame] = deque(maxlen=RING_FRAMES)
    result = DetectResult(ranges=switch.ranges)
    # 지금 구간의 기준 영역. 구간이 열릴 때마다 바뀐다. 내 차를 찾지 못한 구간은 None이다
    base: BaseRegion | None = None
    roi_in = roi.mask > 0
    # 직전 분석 프레임의 밝기 그림. 맨 첫 프레임에는 없다
    prev_gray: np.ndarray | None = None
    for frame in iter_analysis_frames(video_path):
        small = crop_frame(frame.image, roi.crop)
        gray = to_gray(small)
        # 직전 분석 프레임과 달라진 픽셀. 맨 첫 프레임은 견줄 프레임이 없어 None이다 (moved_px가 null)
        changed = None if prev_gray is None else changed_pixels(prev_gray, gray)
        # MOG2는 켜고 끄기와 상관없이 모든 프레임을 한 번씩만 본다 (D-192)
        blobs, pixels = _find_frame_blobs(mog2, small, roi)
        stable = frame.time_sec >= MOG2_STABLE_SEC
        roi_motion = has_roi_motion(blobs)
        decision = switch.step(frame.time_sec, roi_motion)
        # 이 프레임의 확정된 채널 A 트랙. YOLO가 꺼진 프레임에는 없다.
        # ROI 움직임이 있으면 YOLO를 반드시 돌리므로, 붙이기 판정에는 늘 이 프레임의 결과가 있다 (규칙 6)
        tracks: list[TrackBox] = []
        # 이 프레임의 내 차 영역. YOLO가 꺼진 프레임에는 없다
        my_car: np.ndarray | None = None
        # 이 프레임의 채널 A 줄. 덩어리 붙이기 뒤에 moved_px를 더해 쓴다 (D-333 나-1)
        current_lines: list[dict] = []
        if decision.run:
            # 거슬러 돌릴 프레임을 먼저, 지금 프레임을 마지막에. 추적기에는 시간순으로 넣어야 한다 (D-313)
            to_run = [*_backfill_frames(ring, decision), (frame.time_sec, small)]
            # 새 구간이 열렸으면 칸을 만든다. 규칙 4로 앞 구간에 이어 붙었으면 구간 수가 그대로다
            new_range = len(result.yolo_frames) < len(switch.ranges)
            if new_range:
                result.yolo_frames.append(0)
            for index, (time_sec, image) in enumerate(to_run):
                lines, tracks, vehicle_masks = process_frame(channel, image, time_sec, roi.crop)
                # 기준 영역은 구간의 첫 프레임에서 한 번만 만든다 (D-259). 이어 붙은 구간은 다시 만들지 않는다
                my_car = _my_car(vehicle_masks, spot)
                result.my_car[round(time_sec, 3)] = (
                    None if my_car is None else roi_contours(my_car.astype(np.uint8), roi.crop)
                )
                if new_range and index == 0:
                    polygons = [] if my_car is None else region_polygons(my_car)
                    result.car_regions.append(polygons)
                    base = base_region(polygons, small.shape[:2])
                # 거슬러 돌린 프레임의 위치도 적어야 켜자마자 멈춘 차를 알아본다 (D-314 결정 4)
                remember_positions(history, time_sec, tracks)
                result.track_ids.update(line["track_id"] for line in lines)
                # 마지막이 지금 프레임이다. 지금 프레임의 줄은 덩어리 붙이기 뒤에 쓴다
                if index == len(to_run) - 1:
                    current_lines = lines
                    continue
                # 거슬러 돈 프레임은 MOG2를 다시 돌리지 않아 전경이 없다. moved_px도 쓰지 않는다
                _add_car_keys(lines, [track.bbox for track in tracks], base, my_car, None, stable)
                _write_lines(tracks_file, lines)
            # 방금 돌린 프레임은 모두 마지막 구간의 것이다
            result.yolo_frames[-1] += len(to_run)
        # 채널 B는 지금 프레임에만 한다. 거슬러 돌린 프레임에는 채널 A만 돈다 (규칙 1)
        statuses, boxes, targets = judge_blobs(blobs, small.shape, frame.time_sec, tracks, history)
        # MOG2 전경을 믿을 수 없는 프레임: 안정 전이거나 덩어리 상한 이상인 덩어리가 있다 (D-265, D-268)
        by_bbox = not stable or has_oversized_blob(blobs, list(range(len(blobs))), small.shape)
        _add_moved_px(
            current_lines,
            None
            if changed is None
            else track_moved_px(tracks, blobs, targets, changed, roi_in, history, by_bbox),
        )
        _add_car_keys(current_lines, [track.bbox for track in tracks], base, my_car, pixels, stable)
        _write_lines(tracks_file, current_lines)
        for status in statuses:
            if status is not None:
                result.blob_counts[status] += 1
        result.blob_frames.append(_blob_frame(blobs, statuses, boxes, roi.crop))
        # 넣을 사각형이 없어도 매 프레임 불러야 사라진 트랙이 1초 뒤 끝난다 (D-315 결정 5)
        tracked = track_boxes(blob_tracker, boxes)
        blob_lines = blob_track_lines(tracked, frame.time_sec, roi.crop)
        blob_bboxes = blob_track_boxes(tracked)
        _add_moved_px(
            blob_lines,
            None
            if changed is None
            else blob_track_moved_px(blob_bboxes, blobs, statuses, changed, roi_in),
        )
        # 채널 B 줄에도 같은 규칙으로 쓴다 (D-319 결정 2)
        _add_car_keys(blob_lines, blob_bboxes, base, my_car, pixels, stable)
        _write_lines(tracks_file, blob_lines)
        _count_blob_tracks(result, blob_lines)
        ring.append((frame.time_sec, small))
        prev_gray = gray
        result.roi_motion.append(roi_motion)
        result.times.append(frame.time_sec)
        result.duration_sec = frame.time_sec
    return result


# ---------- ② 결과 쓰기 ----------


def write_ranges(path: str, video_path: str, result: DetectResult) -> None:
    """YOLO 구간 목록 파일 yolo_ranges.json을 쓴다 (D-310 결정 2, 개발 확인용)."""
    data = {
        "video": os.path.basename(video_path),
        "sampling_fps": SAMPLING_FPS,
        "duration_sec": round(result.duration_sec, 3),
        "mog2_stable_sec": float(MOG2_STABLE_SEC),
        "ranges": [
            {
                "start_sec": round(r.start_sec, 3),
                "end_sec": round(r.end_sec, 3),
                "yolo_frames": count,
                "car_region": car_region,
            }
            for r, count, car_region in zip(
                result.ranges, result.yolo_frames, result.car_regions, strict=True
            )
        ],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def print_summary(result: DetectResult) -> None:
    yolo_total = sum(result.yolo_frames)
    ratio = yolo_total / result.frame_count if result.frame_count else 0.0
    print(
        f"YOLO 구간 {len(result.ranges)}개 "
        f"(YOLO 프레임 {yolo_total} / 분석 프레임 {result.frame_count}장, {ratio:.0%})"
        f" / 트랙 {len(result.track_ids)}개"
    )
    for n, (r, count) in enumerate(zip(result.ranges, result.yolo_frames, strict=True), start=1):
        print(
            f"  {n:>3}  {_format_time(r.start_sec)} ~ {_format_time(r.end_sec)}  프레임 {count}장"
        )
    print_blob_summary(result)
    print_car_summary(result)


def print_car_summary(result: DetectResult) -> None:
    """내 차를 찾지 못한 프레임 수와 기준 영역이 빈 구간 수를 한 줄로 찍는다."""
    not_found = sum(contours is None for contours in result.my_car.values())
    empty = sum(not polygons for polygons in result.car_regions)
    print(
        f"내 차 영역: YOLO 프레임 {len(result.my_car)}장 가운데 찾지 못함 {not_found}장"
        f" / 기준 영역이 빈 구간 {empty}개 (구간 {len(result.car_regions)}개)"
    )


def print_blob_summary(result: DetectResult) -> None:
    """ROI 덩어리의 붙이기 결과와 클래스 없는 트랙 목록을 찍는다 (D-316 결정 3)."""
    counts = result.blob_counts
    line_total = sum(entry[2] for entry in result.blob_tracks.values())
    print(
        f"ROI 덩어리 {sum(counts.values())}개 "
        f"({ATTACHED} {counts[ATTACHED]} · {PASSED} {counts[PASSED]} · {SKIPPED} {counts[SKIPPED]})"
        f" / 클래스 없는 트랙 {len(result.blob_tracks)}개 (줄 {line_total}개)"
    )
    for track_id, (start_sec, end_sec, lines) in sorted(result.blob_tracks.items()):
        print(f"  {track_id}  {_format_time(start_sec)} ~ {_format_time(end_sec)}  줄 {lines}개")


# ---------- ③ 그리기 ----------


def load_tracks(path: str) -> dict[float, list[dict]]:
    """트랙 파일을 읽어 시각(t)별로 묶는다. 줄 순서를 믿지 않는다 (D-258)."""
    tracks: dict[float, list[dict]] = {}
    with open(path, encoding="utf-8") as f:
        for text in f:
            line = json.loads(text)
            tracks.setdefault(line["t"], []).append(line)
    return tracks


def _track_color(track_id: int) -> tuple[int, int, int]:
    """트랙 번호마다 다른 색 (BGR). 같은 번호는 영상 내내 같은 색이다."""
    hsv = np.uint8([[[track_id * _HUE_STEP % 180, 255, _TRACK_COLOR_VALUE]]])
    b, g, r = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)[0, 0]
    return int(b), int(g), int(r)


def _is_blob_track(line: dict) -> bool:
    """클래스 없는 트랙 줄인가. 클래스가 없는 줄이 채널 B 줄이다 (D-257)."""
    return "cls" not in line


def draw_tracks(image: np.ndarray, lines: list[dict]) -> None:
    """트랙 사각형을 그린다 (image를 직접 고친다). bbox는 원본 좌표라 그대로 쓴다.

    채널 A 트랙은 번호마다 다른 색 선, 클래스 없는 트랙은 굵은 흰 선이다.
    """
    for line in lines:
        x1, y1, x2, y2 = line["bbox"]
        if _is_blob_track(line):
            cv2.rectangle(image, (x1, y1), (x2, y2), WHITE, _BLOB_TRACK_LINE)
        else:
            cv2.rectangle(image, (x1, y1), (x2, y2), _track_color(line["track_id"]), _TRACK_LINE)


def draw_blob_frame(image: np.ndarray, blob_frame: BlobFrame) -> np.ndarray:
    """MOG2 전경을 반투명하게 칠하고, 추적기에 넣은 사각형을 얇은 흰 선으로 그린다.

    ROI 덩어리는 붙이기 결과 색, ROI에 닿지 않은 덩어리는 노랑이다 (2단계 영상과 같은 색).
    """
    if blob_frame.blobs or blob_frame.outside:
        layer = image.copy()
        for contour in blob_frame.outside:
            cv2.fillPoly(layer, [contour], YELLOW)
        for contour, status in blob_frame.blobs:
            cv2.fillPoly(layer, [contour], _STATUS_COLORS[status])
        image = cv2.addWeighted(layer, _BLOB_ALPHA, image, 1 - _BLOB_ALPHA, 0)
    for x1, y1, x2, y2 in blob_frame.boxes:
        cv2.rectangle(image, (x1, y1), (x2, y2), WHITE, _FED_BOX_LINE)
    return image


def draw_my_car(image: np.ndarray, contours: list[np.ndarray] | None) -> np.ndarray:
    """그 프레임의 내 차 영역을 보라로 옅게 칠한 새 그림을 돌려준다. 없으면 그대로 돌려준다."""
    if not contours:
        return image
    layer = image.copy()
    cv2.fillPoly(layer, contours, PURPLE)
    return cv2.addWeighted(layer, _MY_CAR_ALPHA, image, 1 - _MY_CAR_ALPHA, 0)


def _base_contours(result: DetectResult, crop: Crop) -> list[list[np.ndarray]]:
    """구간마다의 기준 영역 테두리 (원본 좌표). 파일에 쓴 다각형을 그대로 옮긴다."""
    return [
        [_blob_to_original(np.array(polygon), crop) for polygon in polygons]
        for polygons in result.car_regions
    ]


def _car_key_text(line: dict) -> str:
    """트랙 줄의 움직인 픽셀 수와 차 영역 키를 "mv95 fg2650 fr0.05 lost2410"처럼 쓴다.

    없는 키는 빼고 null은 "-"다.
    """
    return "".join(
        f" {name}{'-' if line[key] is None else line[key]}"
        for key, name in _CAR_KEY_NAMES
        if key in line
    )


def _track_labels(lines: list[dict]) -> list[Label]:
    """사각형 왼쪽 위에 붙이는 "번호 클래스 신뢰도" 이름표. 채널 B 줄은 번호뿐이다 (D-258).

    차 영역 키가 있으면 뒤에 붙인다.
    """
    return [
        (
            (
                str(line["track_id"])
                if _is_blob_track(line)
                else f"{line['track_id']} {line['cls']} {line['conf']:.2f}"
            )
            + _car_key_text(line),
            (line["bbox"][0], max(line["bbox"][1] - _LABEL_GAP, 0)),
            # 이름표 글씨가 흰색이라 클래스 없는 트랙은 어두운 바탕에 쓴다
            DARK if _is_blob_track(line) else _track_color(line["track_id"]),
        )
        for line in lines
    ]


def _blob_count_text(blob_frame: BlobFrame) -> str:
    """이 프레임 ROI 덩어리의 붙이기 결과 수. 예: "붙음 2 · 넘김 1 · 건너뜀 0"."""
    statuses = [status for _, status in blob_frame.blobs]
    return " · ".join(f"{status} {statuses.count(status)}" for status in BLOB_STATUSES)


def _frame_labels(
    time_sec: float,
    roi_motion: bool,
    blob_frame: BlobFrame,
    ranges: list[YoloRange],
    scenes: list[Scene],
    my_car: dict[float, list[np.ndarray] | None],
) -> list[Label]:
    """왼쪽 위 시각 아래에 한 줄씩 쌓는 이름표."""
    texts = []
    if _range_at(ranges, time_sec) is not None:
        texts.append(("YOLO 켜짐", GREEN))
    # YOLO를 돌린 프레임에만 쓴다. 꺼진 프레임에는 내 차를 찾아보지 않았다
    if round(time_sec, 3) in my_car:
        found = my_car[round(time_sec, 3)] is not None
        texts.append(("내 차 찾음" if found else "내 차 찾지 못함", PURPLE))
    if roi_motion:
        texts.append(("ROI 움직임", RED))
        texts.append((_blob_count_text(blob_frame), DARK))
    if time_sec < MOG2_STABLE_SEC:
        texts.append(("안정 전", GRAY))
    scene = _scene_at(scenes, time_sec)
    if scene is not None:
        texts.append((f"장면 {scene.label}", SCENE_BLUE))
    return [(text, (20, 80 + i * _LABEL_GAP), color) for i, (text, color) in enumerate(texts)]


def render(
    video_path: str,
    out_video: str,
    roi: Roi,
    spot: CarSpot | None,
    result: DetectResult,
    tracks: dict[float, list[dict]],
    scenes: list[Scene],
    size: tuple[int, int],
) -> int:
    """영상을 다시 읽으며 덩어리·트랙·영역, 이름표, 시간 막대를 그린다. 쓴 프레임 수를 돌려준다."""
    width, height = size
    contours = roi_contours(roi.mask, roi.crop)
    zone_labels = _zone_labels(roi, contours)
    spot_contours = [] if spot is None else roi_contours(spot.mask.astype(np.uint8), roi.crop)
    base_contours = _base_contours(result, roi.crop)
    # 시간 막대 둘째 줄의 빨간 칸이 ROI 움직임 구간, 셋째 줄의 초록 칸이 YOLO 구간이다
    records = [
        FrameRecord(time_sec, roi_motion, [])
        for time_sec, roi_motion in zip(result.times, result.roi_motion, strict=True)
    ]
    timeline = make_timeline(
        width, result.duration_sec, merge_motion_ranges(records), scenes, result.ranges
    )

    writer = cv2.VideoWriter(
        out_video, cv2.VideoWriter_fourcc(*"mp4v"), SAMPLING_FPS, (width, height)
    )
    count = 0
    # 같은 함수로 같은 영상을 읽으므로 프레임 순서가 탐지 때와 같다
    for frame, roi_motion, blob_frame in zip(
        iter_analysis_frames(video_path), result.roi_motion, result.blob_frames, strict=False
    ):
        # 덩어리 칠을 먼저 해야 그 위의 트랙 사각형과 영역 선이 흐려지지 않는다
        image = draw_blob_frame(frame.image, blob_frame)
        # 트랙 줄의 t는 소수 셋째 자리까지라 같은 자리로 맞춰 찾는다 (04장 4.8)
        time_key = round(frame.time_sec, 3)
        image = draw_my_car(image, result.my_car.get(time_key))
        lines = tracks.get(time_key, [])
        draw_tracks(image, lines)
        draw_zones(image, roi, contours)
        cv2.polylines(image, spot_contours, True, BROWN, _CAR_SPOT_LINE)
        # 기준 영역은 그 프레임이 속한 YOLO 구간의 것을 그린다. 구간 밖 프레임에는 없다
        range_number = _range_at(result.ranges, frame.time_sec)
        if range_number is not None:
            cv2.polylines(image, base_contours[range_number - 1], True, PURPLE, _BASE_REGION_LINE)
        frame_labels = _frame_labels(
            frame.time_sec, roi_motion, blob_frame, result.ranges, scenes, result.my_car
        )
        image = draw_labels(image, zone_labels + _track_labels(lines) + frame_labels)
        _draw_time(image, frame.index, frame.time_sec)
        attach_timeline(image, timeline, frame.time_sec, result.duration_sec)
        writer.write(image)
        count += 1
    writer.release()
    return count


def make_track_preview(
    video_path: str, input_path: str, weights_path: str, out_dir: str, scenes_path: str | None
) -> None:
    width, height = video_size(video_path)
    data = load_input(input_path, width, height)
    roi = build_roi(data, (width, height))
    spot = build_car_spot(data, (width, height), roi.crop)
    scenes = load_scenes(scenes_path) if scenes_path else []
    # 모델을 못 열면 영상을 읽기 전에 끝낸다
    channel = open_channel_a(Path(weights_path))
    blob_tracker = open_blob_tracker()

    os.makedirs(out_dir, exist_ok=True)
    tracks_path = os.path.join(out_dir, "tracks.jsonl")
    with open(tracks_path, "w", encoding="utf-8") as tracks_file:
        result = detect(video_path, roi, spot, channel, blob_tracker, tracks_file)

    ranges_path = os.path.join(out_dir, "yolo_ranges.json")
    write_ranges(ranges_path, video_path, result)
    print_summary(result)
    print(f"트랙 파일: {tracks_path}")
    print(f"YOLO 구간 목록: {ranges_path}")

    out_video = os.path.join(out_dir, "tracks.mp4")
    tracks = load_tracks(tracks_path)
    count = render(video_path, out_video, roi, spot, result, tracks, scenes, (width, height))
    print(f"확인용 영상: {out_video} ({count}장, {SAMPLING_FPS}fps)")


if __name__ == "__main__":
    if len(sys.argv) not in (5, 6):
        print(
            "사용법: python -m pipeline.candidates.s3_tracks.track_preview "
            "<영상> <입력 JSON> <모델 가중치> <출력 폴더> [장면 파일]"
        )
        sys.exit(2)
    try:
        make_track_preview(
            sys.argv[1],
            sys.argv[2],
            sys.argv[3],
            sys.argv[4],
            sys.argv[5] if len(sys.argv) == 6 else None,
        )
    except (InputError, CropError, RoiError, ModelError, FileNotFoundError) as e:
        print(f"오류: {e}")
        sys.exit(1)
