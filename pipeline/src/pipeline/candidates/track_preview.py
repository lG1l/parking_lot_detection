"""채널 A까지 돌려 트랙 파일과 YOLO 구간 목록을 만든다 (3단계, D-310). 명령의 진입점이다.

영상을 한 번 읽으며 프레임마다 MOG2(채널 B) → 켜고 끄기 판정 → YOLO + ByteTrack(채널 A)을 돈다.
YOLO를 켜는 순간에는 링 버퍼에 들고 있던 지난 프레임부터 먼저 돌린다 (06장 6.5 규칙 1, D-247).
그리기는 탐지가 끝난 뒤 영상을 한 번 더 읽어 한다. MOG2와 YOLO는 다시 돌리지 않는다.

실행 (pipeline/ 폴더에서):
    uv run python -m pipeline.candidates.track_preview \
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

from pipeline.candidates.channel_a import ChannelA, ModelError, open_channel_a, process_frame
from pipeline.candidates.channel_b import (
    MOG2_STABLE_SEC,
    clean_foreground,
    create_mog2,
    find_blobs,
    has_roi_motion,
)
from pipeline.candidates.crop import CropError, crop_frame
from pipeline.candidates.inputs import InputError, load_input
from pipeline.candidates.motion_preview import (
    _LABEL_GAP,
    GRAY,
    SCENE_BLUE,
    Scene,
    _range_at,
    _scene_at,
    _zone_labels,
    attach_timeline,
    draw_zones,
    load_scenes,
    make_timeline,
)
from pipeline.candidates.preview import (
    RED,
    _draw_time,
    _format_time,
    draw_labels,
    roi_contours,
    video_size,
)
from pipeline.candidates.roi import Roi, RoiError, build_roi
from pipeline.candidates.video import SAMPLING_FPS, iter_analysis_frames
from pipeline.candidates.yolo_switch import YOLO_BEFORE_SEC, Decision, YoloRange, YoloSwitch

# 링 버퍼에 담는 줄인 프레임 수. 지금 프레임을 빼고 "거슬러 올라가는 시간"만큼이다 (D-247)
RING_FRAMES = YOLO_BEFORE_SEC * SAMPLING_FPS

# (시각, 줄인 프레임)
TimedFrame = tuple[float, np.ndarray]

# 이름표 한 개: (글, 왼쪽 위 좌표, BGR 색). preview.draw_labels가 받는 모양이다
Label = tuple[str, tuple[int, int], tuple[int, int, int]]

# 트랙 색. 색상환(0~179)을 이 걸음으로 돌아 이웃 번호끼리 색이 멀어지게 한다
_HUE_STEP = 47
_TRACK_COLOR_VALUE = 190  # 흰 글씨가 읽히게 조금 어둡게 한다
_TRACK_LINE = 2


@dataclass
class DetectResult:
    """탐지를 끝까지 돌린 뒤 남는 것. 트랙 줄은 돌면서 파일에 바로 쓰므로 여기 없다."""

    ranges: list[YoloRange]  # YOLO를 돌린 구간 (시간순)
    yolo_frames: list[int] = field(default_factory=list)  # 구간마다 YOLO를 돌린 프레임 수
    track_ids: set[int] = field(default_factory=set)  # 트랙 파일에 나온 트랙 번호
    roi_motion: list[bool] = field(default_factory=list)  # 분석 프레임마다의 ROI 움직임 여부
    duration_sec: float = 0.0  # 마지막 분석 프레임 시각

    @property
    def frame_count(self) -> int:
        """분석 프레임 수."""
        return len(self.roi_motion)


# ---------- ① 탐지 ----------


def _roi_motion(mog2: cv2.BackgroundSubtractorMOG2, small: np.ndarray, roi: Roi) -> bool:
    """줄인 프레임 한 장을 MOG2에 넣고 ROI 움직임이 있는지 본다 (채널 B)."""
    binary = clean_foreground(mog2.apply(small))
    return has_roi_motion(find_blobs(binary, roi.mask))


def _backfill_frames(ring: deque[TimedFrame], decision: Decision) -> list[TimedFrame]:
    """링 버퍼에서 거슬러 돌릴 프레임을 시간순으로 꺼낸다 (규칙 1·4).

    어느 시각을 돌릴지는 켜고 끄기 판정이 이미 골랐다. 이미 돌린 프레임은 거기에 없다.
    """
    wanted = set(decision.backfill_times)
    return [(time_sec, image) for time_sec, image in ring if time_sec in wanted]


def _write_lines(tracks_file: TextIO, lines: list[dict]) -> None:
    """트랙 줄을 만든 순서대로 한 줄씩 쓴다 (04장 4.8, D-258)."""
    tracks_file.writelines(json.dumps(line, ensure_ascii=False) + "\n" for line in lines)


def detect(video_path: str, roi: Roi, channel: ChannelA, tracks_file: TextIO) -> DetectResult:
    """영상을 처음부터 끝까지 한 번 읽으며 YOLO가 켜진 프레임의 트랙 줄을 파일에 쓴다."""
    mog2 = create_mog2(SAMPLING_FPS)
    switch = YoloSwitch()
    ring: deque[TimedFrame] = deque(maxlen=RING_FRAMES)
    result = DetectResult(ranges=switch.ranges)
    for frame in iter_analysis_frames(video_path):
        small = crop_frame(frame.image, roi.crop)
        # MOG2는 켜고 끄기와 상관없이 모든 프레임을 한 번씩만 본다 (D-192)
        roi_motion = _roi_motion(mog2, small, roi)
        decision = switch.step(frame.time_sec, roi_motion)
        if decision.run:
            # 거슬러 돌릴 프레임을 먼저, 지금 프레임을 마지막에. 추적기에는 시간순으로 넣어야 한다 (D-313)
            to_run = [*_backfill_frames(ring, decision), (frame.time_sec, small)]
            for time_sec, image in to_run:
                lines = process_frame(channel, image, time_sec, roi.crop)
                _write_lines(tracks_file, lines)
                result.track_ids.update(line["track_id"] for line in lines)
            # 방금 돌린 프레임은 모두 마지막 구간의 것이다. 새 구간이 열렸으면 칸을 만든다
            if len(result.yolo_frames) < len(switch.ranges):
                result.yolo_frames.append(0)
            result.yolo_frames[-1] += len(to_run)
        ring.append((frame.time_sec, small))
        result.roi_motion.append(roi_motion)
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
            }
            for r, count in zip(result.ranges, result.yolo_frames, strict=True)
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


def draw_tracks(image: np.ndarray, lines: list[dict]) -> None:
    """트랙 사각형을 그린다 (image를 직접 고친다). bbox는 원본 좌표라 그대로 쓴다."""
    for line in lines:
        x1, y1, x2, y2 = line["bbox"]
        cv2.rectangle(image, (x1, y1), (x2, y2), _track_color(line["track_id"]), _TRACK_LINE)


def _track_labels(lines: list[dict]) -> list[Label]:
    """사각형 왼쪽 위에 붙이는 "번호 클래스 신뢰도" 이름표."""
    return [
        (
            f"{line['track_id']} {line['cls']} {line['conf']:.2f}",
            (line["bbox"][0], max(line["bbox"][1] - _LABEL_GAP, 0)),
            _track_color(line["track_id"]),
        )
        for line in lines
    ]


def _frame_labels(
    time_sec: float, roi_motion: bool, ranges: list[YoloRange], scenes: list[Scene]
) -> list[Label]:
    """왼쪽 위 시각 아래에 한 줄씩 쌓는 이름표."""
    texts = []
    if _range_at(ranges, time_sec) is not None:
        texts.append(("YOLO 켜짐", RED))
    if roi_motion:
        texts.append(("ROI 움직임", RED))
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
    result: DetectResult,
    tracks: dict[float, list[dict]],
    scenes: list[Scene],
    size: tuple[int, int],
) -> int:
    """영상을 다시 읽으며 트랙과 영역, 이름표, 시간 막대를 그린다. 쓴 프레임 수를 돌려준다."""
    width, height = size
    contours = roi_contours(roi.mask, roi.crop)
    zone_labels = _zone_labels(roi, contours)
    # 시간 막대 아랫줄의 빨간 칸이 YOLO 구간이다
    timeline = make_timeline(width, result.duration_sec, result.ranges, scenes)

    writer = cv2.VideoWriter(
        out_video, cv2.VideoWriter_fourcc(*"mp4v"), SAMPLING_FPS, (width, height)
    )
    count = 0
    # 같은 함수로 같은 영상을 읽으므로 프레임 순서가 탐지 때와 같다
    for frame, roi_motion in zip(iter_analysis_frames(video_path), result.roi_motion, strict=False):
        image = frame.image
        # 트랙 줄의 t는 소수 셋째 자리까지라 같은 자리로 맞춰 찾는다 (04장 4.8)
        lines = tracks.get(round(frame.time_sec, 3), [])
        draw_tracks(image, lines)
        draw_zones(image, roi, contours)
        frame_labels = _frame_labels(frame.time_sec, roi_motion, result.ranges, scenes)
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
    scenes = load_scenes(scenes_path) if scenes_path else []
    # 모델을 못 열면 영상을 읽기 전에 끝낸다
    channel = open_channel_a(Path(weights_path))

    os.makedirs(out_dir, exist_ok=True)
    tracks_path = os.path.join(out_dir, "tracks.jsonl")
    with open(tracks_path, "w", encoding="utf-8") as tracks_file:
        result = detect(video_path, roi, channel, tracks_file)

    ranges_path = os.path.join(out_dir, "yolo_ranges.json")
    write_ranges(ranges_path, video_path, result)
    print_summary(result)
    print(f"트랙 파일: {tracks_path}")
    print(f"YOLO 구간 목록: {ranges_path}")

    out_video = os.path.join(out_dir, "tracks.mp4")
    tracks = load_tracks(tracks_path)
    count = render(video_path, out_video, roi, result, tracks, scenes, (width, height))
    print(f"확인용 영상: {out_video} ({count}장, {SAMPLING_FPS}fps)")


if __name__ == "__main__":
    if len(sys.argv) not in (5, 6):
        print(
            "사용법: python -m pipeline.candidates.track_preview "
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
