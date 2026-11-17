"""채널 A까지 돌려 트랙 파일과 YOLO 구간 목록을 만든다 (3단계, D-310). 명령의 진입점이다.

영상을 한 번 읽으며 프레임마다 MOG2(채널 B) → 켜고 끄기 판정 → YOLO + ByteTrack(채널 A)을 돈다.
YOLO를 켜는 순간에는 링 버퍼에 들고 있던 지난 프레임부터 먼저 돌린다 (06장 6.5 규칙 1, D-247).

실행 (pipeline/ 폴더에서):
    uv run python -m pipeline.candidates.track_preview <영상> <입력 JSON> <모델 가중치> <출력 폴더>
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
from pipeline.candidates.preview import _format_time, video_size
from pipeline.candidates.roi import Roi, RoiError, build_roi
from pipeline.candidates.video import SAMPLING_FPS, iter_analysis_frames
from pipeline.candidates.yolo_switch import YOLO_BEFORE_SEC, Decision, YoloRange, YoloSwitch

# 링 버퍼에 담는 줄인 프레임 수. 지금 프레임을 빼고 "거슬러 올라가는 시간"만큼이다 (D-247)
RING_FRAMES = YOLO_BEFORE_SEC * SAMPLING_FPS

# (시각, 줄인 프레임)
TimedFrame = tuple[float, np.ndarray]


@dataclass
class DetectResult:
    """탐지를 끝까지 돌린 뒤 남는 것. 트랙 줄은 돌면서 파일에 바로 쓰므로 여기 없다."""

    ranges: list[YoloRange]  # YOLO를 돌린 구간 (시간순)
    yolo_frames: list[int] = field(default_factory=list)  # 구간마다 YOLO를 돌린 프레임 수
    track_ids: set[int] = field(default_factory=set)  # 트랙 파일에 나온 트랙 번호
    frame_count: int = 0  # 분석 프레임 수
    duration_sec: float = 0.0  # 마지막 분석 프레임 시각


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
        decision = switch.step(frame.time_sec, _roi_motion(mog2, small, roi))
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
        result.frame_count += 1
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


def make_track_preview(video_path: str, input_path: str, weights_path: str, out_dir: str) -> None:
    width, height = video_size(video_path)
    data = load_input(input_path, width, height)
    roi = build_roi(data, (width, height))
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


if __name__ == "__main__":
    if len(sys.argv) != 5:
        print(
            "사용법: python -m pipeline.candidates.track_preview "
            "<영상> <입력 JSON> <모델 가중치> <출력 폴더>"
        )
        sys.exit(2)
    try:
        make_track_preview(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4])
    except (InputError, CropError, RoiError, ModelError, FileNotFoundError) as e:
        print(f"오류: {e}")
        sys.exit(1)
