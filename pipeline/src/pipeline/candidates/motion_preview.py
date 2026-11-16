"""채널 B만 돌려 ROI 움직임 구간 목록과 확인용 영상을 만든다 (2단계, D-303). 명령의 진입점이다.

흐름은 탐지 → 구간 판정 → 그리기 순서다 (D-250). 탐지하는 동안에는 구간을 정하지 않는다.
그리기는 영상 전체의 구간이 정해진 뒤 영상을 한 번 더 읽어 한다. MOG2는 다시 돌리지 않는다.

실행 (pipeline/ 폴더에서):
    uv run python -m pipeline.candidates.motion_preview <영상> <입력 JSON> <출력 폴더> [장면 파일]
"""

import json
import os
import sys
from dataclasses import dataclass

import cv2
import numpy as np

from pipeline.candidates.channel_b import (
    MOG2_STABLE_SEC,
    FrameRecord,
    MotionRange,
    clean_foreground,
    create_mog2,
    find_blobs,
    has_roi_motion,
    merge_motion_ranges,
)
from pipeline.candidates.crop import Crop, CropError, analysis_crop, crop_frame, to_original
from pipeline.candidates.inputs import InputError, load_input
from pipeline.candidates.preview import (
    ORANGE,
    RED,
    WHITE,
    _draw_time,
    _format_time,
    draw_labels,
    draw_roi,
    roi_contours,
    video_size,
)
from pipeline.candidates.roi import Roi, RoiError, build_roi
from pipeline.candidates.video import SAMPLING_FPS, iter_analysis_frames

# 그림 색 (BGR)
YELLOW = (0, 220, 255)  # ROI에 닿지 않은 덩어리
SCENE_BLUE = (220, 120, 0)  # 시간 막대 윗줄: 기대 장면
GRAY = (130, 130, 130)  # 시간 막대 아랫줄: 안정 전
DARK = (40, 40, 40)  # 시간 막대 바탕

_BLOB_ALPHA = 0.5
_LABEL_GAP = 34  # 이름표 줄 간격 (px). preview의 글꼴 크기 22에 여백을 더한 값

# 시간 막대 모양 (px). 원본 크기 화면 맨 아래에 붙인다
_BAR_MARGIN_X = 40
_BAR_NAME_H = 34  # 장면 이름 줄
_BAR_ROW_H = 26  # 파란 줄·빨간 줄 높이
_BAR_ROW_GAP = 6
_BAR_TICK_H = 34  # 시각 글씨 줄
_BAR_MIN_W = 2  # 한 장짜리 구간도 보이게 하는 최소 폭


@dataclass(frozen=True)
class Scene:
    label: str
    start_sec: float
    end_sec: float


def load_scenes(path: str) -> list[Scene]:
    """장면 파일(JSON 배열, 개발 확인용, D-303)을 읽는다."""
    with open(path, encoding="utf-8") as f:
        return [Scene(s["label"], float(s["start_sec"]), float(s["end_sec"])) for s in json.load(f)]


# ---------- ① 탐지 ----------


def detect(video_path: str, roi: Roi) -> list[FrameRecord]:
    """영상을 처음부터 끝까지 한 번 읽으며 프레임마다 ROI 움직임과 덩어리를 적는다."""
    mog2 = create_mog2(SAMPLING_FPS)
    records = []
    for frame in iter_analysis_frames(video_path):
        small = crop_frame(frame.image, roi.crop)
        binary = clean_foreground(mog2.apply(small))
        blobs = find_blobs(binary, roi.mask)
        records.append(FrameRecord(frame.time_sec, has_roi_motion(blobs), blobs))
    return records


# ---------- ② 구간 판정 결과 쓰기 ----------


def write_ranges(
    path: str, video_path: str, records: list[FrameRecord], ranges: list[MotionRange]
) -> None:
    """구간 목록 파일 motion_ranges.json을 쓴다 (D-303 결정 3)."""
    data = {
        "video": os.path.basename(video_path),
        "sampling_fps": SAMPLING_FPS,
        "duration_sec": round(records[-1].time_sec, 3) if records else 0.0,
        "mog2_stable_sec": float(MOG2_STABLE_SEC),
        "ranges": [
            {
                "start_sec": round(r.start_sec, 3),
                "end_sec": round(r.end_sec, 3),
                "motion_frames": r.motion_frames,
            }
            for r in ranges
        ],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def print_ranges(ranges: list[MotionRange]) -> None:
    print(f"움직임 구간 {len(ranges)}개 (안정 전 = {_format_time(MOG2_STABLE_SEC)} 이전)")
    for n, r in enumerate(ranges, start=1):
        mark = "  안정 전" if r.start_sec < MOG2_STABLE_SEC else ""
        print(
            f"  {n:>3}  {_format_time(r.start_sec)} ~ {_format_time(r.end_sec)}"
            f"  프레임 {r.motion_frames}장{mark}"
        )


# ---------- ③ 그리기 ----------


def _blob_to_original(contour: np.ndarray, crop: Crop) -> np.ndarray:
    pts = [to_original((float(x), float(y)), crop) for x, y in contour.reshape(-1, 2)]
    return np.array(pts).round().astype(np.int32)


def draw_blobs(image: np.ndarray, record: FrameRecord, crop: Crop) -> np.ndarray:
    """ROI에 닿은 덩어리는 빨강, 닿지 않은 덩어리는 노랑 반투명으로 칠한 새 그림을 돌려준다."""
    if not record.blobs:
        return image
    layer = image.copy()
    for blob in record.blobs:
        color = RED if blob.touches_roi else YELLOW
        cv2.fillPoly(layer, [_blob_to_original(blob.contour, crop)], color)
    return cv2.addWeighted(layer, _BLOB_ALPHA, image, 1 - _BLOB_ALPHA, 0)


def _range_at(ranges: list[MotionRange], t: float) -> int | None:
    """t가 들어 있는 구간의 번호(1부터). 없으면 None."""
    for n, r in enumerate(ranges, start=1):
        if r.start_sec <= t <= r.end_sec:
            return n
    return None


def _scene_at(scenes: list[Scene], t: float) -> Scene | None:
    for scene in scenes:
        if scene.start_sec <= t <= scene.end_sec:
            return scene
    return None


def _frame_labels(
    record: FrameRecord, ranges: list[MotionRange], scenes: list[Scene]
) -> list[tuple[str, tuple[int, int], tuple[int, int, int]]]:
    """왼쪽 위 시각 아래에 한 줄씩 쌓는 이름표."""
    t = record.time_sec
    texts = []
    if record.roi_motion:
        texts.append(("ROI 움직임", RED))
    if t < MOG2_STABLE_SEC:
        texts.append(("안정 전", GRAY))
    n = _range_at(ranges, t)
    if n is not None:
        r = ranges[n - 1]
        texts.append((f"구간 {n} · {_format_time(r.start_sec)}~{_format_time(r.end_sec)}", RED))
    scene = _scene_at(scenes, t)
    if scene is not None:
        texts.append((f"장면 {scene.label}", SCENE_BLUE))
    return [(text, (20, 80 + i * _LABEL_GAP), color) for i, (text, color) in enumerate(texts)]


def _bar_x(t: float, duration: float, width: int) -> int:
    """시각 → 시간 막대 위 x 좌표."""
    usable = width - 2 * _BAR_MARGIN_X
    return _BAR_MARGIN_X + round(usable * t / duration) if duration > 0 else _BAR_MARGIN_X


def _bar_height() -> int:
    return _BAR_NAME_H + 2 * _BAR_ROW_H + _BAR_ROW_GAP + _BAR_TICK_H


def make_timeline(
    width: int, duration: float, ranges: list[MotionRange], scenes: list[Scene]
) -> np.ndarray:
    """두 줄 시간 막대를 한 번만 그려 둔다. 프레임마다 흰 세로선만 더한다.

    윗줄 = 장면 파일의 기대 장면(파랑), 아랫줄 = 잡힌 움직임 구간(빨강)과 안정 전(회색).
    파란 칸 바로 아래에 빨간 칸이 있으면 그 장면이 잡힌 것이다.
    """
    bar = np.full((_bar_height(), width, 3), DARK, np.uint8)
    top_y = _BAR_NAME_H
    low_y = top_y + _BAR_ROW_H + _BAR_ROW_GAP
    left, right = _bar_x(0, duration, width), _bar_x(duration, duration, width)
    for y in (top_y, low_y):
        cv2.rectangle(bar, (left, y), (right, y + _BAR_ROW_H), (70, 70, 70), -1)

    # 회색(안정 전)을 먼저 칠해야 그 위의 빨간 구간이 보인다
    stable_x = _bar_x(min(MOG2_STABLE_SEC, duration), duration, width)
    cv2.rectangle(bar, (left, low_y), (stable_x, low_y + _BAR_ROW_H), GRAY, -1)
    for r in ranges:
        x1 = _bar_x(r.start_sec, duration, width)
        x2 = max(_bar_x(r.end_sec, duration, width), x1 + _BAR_MIN_W)
        cv2.rectangle(bar, (x1, low_y), (x2, low_y + _BAR_ROW_H), RED, -1)

    names = []
    for scene in scenes:
        x1 = _bar_x(scene.start_sec, duration, width)
        x2 = max(_bar_x(scene.end_sec, duration, width), x1 + _BAR_MIN_W)
        cv2.rectangle(bar, (x1, top_y), (x2, top_y + _BAR_ROW_H), SCENE_BLUE, -1)
        names.append((scene.label, (x1, 4), SCENE_BLUE))

    # 양 끝과 가운데 시각 (분:초)
    tick_y = low_y + _BAR_ROW_H + 26
    for t in (0.0, duration / 2, duration):
        text = _format_time(t)
        x = _bar_x(t, duration, width)
        (tw, _), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)
        x = min(max(x - tw // 2, 0), width - tw)
        cv2.putText(bar, text, (x, tick_y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, WHITE, 2)
    return draw_labels(bar, names) if names else bar


def attach_timeline(image: np.ndarray, timeline: np.ndarray, t: float, duration: float) -> None:
    """화면 맨 아래에 시간 막대를 붙이고 지금 위치에 흰 세로선을 긋는다 (image를 직접 고친다)."""
    height, width = image.shape[:2]
    top = height - timeline.shape[0]
    image[top:] = timeline
    x = _bar_x(t, duration, width)
    cv2.line(
        image, (x, top + _BAR_NAME_H - 4), (x, top + _BAR_NAME_H + 2 * _BAR_ROW_H + 10), WHITE, 3
    )


def render(
    video_path: str,
    out_video: str,
    roi: Roi,
    records: list[FrameRecord],
    ranges: list[MotionRange],
    scenes: list[Scene],
    size: tuple[int, int],
) -> int:
    """영상을 다시 읽으며 프레임 기록대로 그린다. 쓴 프레임 수를 돌려준다."""
    width, height = size
    duration = records[-1].time_sec if records else 0.0
    contours = roi_contours(roi.mask, roi.crop)
    timeline = make_timeline(width, duration, ranges, scenes)
    x1, y1, x2, y2 = roi.crop.rect

    writer = cv2.VideoWriter(
        out_video, cv2.VideoWriter_fourcc(*"mp4v"), SAMPLING_FPS, (width, height)
    )
    count = 0
    # 같은 함수로 같은 영상을 읽으므로 프레임 순서가 탐지 때와 같다
    for frame, record in zip(iter_analysis_frames(video_path), records, strict=False):
        image = draw_roi(frame.image, contours)
        image = draw_blobs(image, record, roi.crop)
        cv2.rectangle(image, (x1, y1), (x2 - 1, y2 - 1), ORANGE, 2)
        labels = _frame_labels(record, ranges, scenes)
        if labels:
            image = draw_labels(image, labels)
        _draw_time(image, frame.index, frame.time_sec)
        attach_timeline(image, timeline, record.time_sec, duration)
        writer.write(image)
        count += 1
    writer.release()
    return count


def make_motion_preview(
    video_path: str, input_path: str, out_dir: str, scenes_path: str | None
) -> None:
    width, height = video_size(video_path)
    data = load_input(input_path, width, height)
    roi = build_roi(data, (width, height), analysis_crop(data.vehicle_bbox, (width, height)))
    scenes = load_scenes(scenes_path) if scenes_path else []

    records = detect(video_path, roi)
    ranges = merge_motion_ranges(records)

    os.makedirs(out_dir, exist_ok=True)
    ranges_path = os.path.join(out_dir, "motion_ranges.json")
    write_ranges(ranges_path, video_path, records, ranges)
    print_ranges(ranges)
    print(f"구간 목록: {ranges_path}")

    out_video = os.path.join(out_dir, "motion.mp4")
    count = render(video_path, out_video, roi, records, ranges, scenes, (width, height))
    print(f"확인용 영상: {out_video} ({count}장, {SAMPLING_FPS}fps)")


if __name__ == "__main__":
    if len(sys.argv) not in (4, 5):
        print(
            "사용법: python -m pipeline.candidates.motion_preview "
            "<영상> <입력 JSON> <출력 폴더> [장면 파일]"
        )
        sys.exit(2)
    try:
        make_motion_preview(
            sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4] if len(sys.argv) == 5 else None
        )
    except (InputError, CropError, RoiError, FileNotFoundError) as e:
        print(f"오류: {e}")
        sys.exit(1)
