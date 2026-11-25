"""탐지 파일의 얼굴·번호판 박스를 블러로 흐려 후보마다 가린 클립을 만든다 (D-347).

탐지는 다시 돌리지 않는다. 8-나가 쓴 탐지 파일 deid_boxes.jsonl을 읽기만 한다.
클립은 8-가(clips.py)와 똑같이 만들고, 프레임을 ffmpeg에 넘기기 전에 박스 자리만 흐린다.
추적·보간이 없어 탐지가 놓친 프레임은 얼굴·번호판이 그대로 보일 수 있다.
가린 클립도 local_storage/ 밖으로 내보내지 않는다.

실행 (pipeline/ 폴더에서):
    uv run python -m pipeline.deidentify.mask
        <영상> <입력 JSON> <candidates.jsonl> <deid_boxes.jsonl> <출력 폴더> [후보 번호]

후보 번호는 3 또는 4,7 꼴이다. 탐지를 돌린 후보의 번호를 준다 (다-4).
9단계(정지 장면)가 이 파일의 blur_box를 불러 쓴다.
"""

import json
import os
import sys

import cv2
import numpy as np

from pipeline.candidates.s1_base.crop import CropError
from pipeline.candidates.s1_base.inputs import InputError, load_input
from pipeline.candidates.s1_base.preview import video_size
from pipeline.candidates.s1_base.roi import RoiError, build_roi
from pipeline.deidentify.clips import (
    ClipError,
    H264Writer,
    Rect,
    even_rect,
    iter_clip_frames,
    video_fps,
)
from pipeline.deidentify.detect import Det, DetectError, parse_numbers
from pipeline.vlm.frames import load_clips

# 모자이크 블러 세기 (01장 1.6, D-347 다-2). 시그마 = 박스 짧은 변 × 이 값. 시작값이다.
# 박스가 9~379픽셀로 크게 달라 세기를 픽셀로 고정하지 않고 박스 크기에 맞춘다
MASK_BLUR_SIGMA_RATIO = 0.5

Box = list[int]  # [x1, y1, x2, y2]


class MaskError(Exception):
    """탐지 파일이 없을 때."""


def load_boxes(boxes_path: str) -> dict[float, list[Det]]:
    """탐지 파일을 모두 읽어 "프레임 시각(t) → 그 프레임의 박스 목록" 표로 만든다."""
    if not os.path.isfile(boxes_path):
        raise MaskError(f"탐지 파일이 없습니다: {boxes_path}")
    table = {}
    with open(boxes_path) as boxes_file:
        for line in boxes_file:
            row = json.loads(line)
            table[row["t"]] = row["dets"]
    return table


def boxes_at(table: dict[float, list[Det]], time_sec: float) -> list[Det]:
    """이 시각의 프레임에서 탐지한 박스 목록을 찾는다 (다-4).

    탐지 파일의 t가 프레임 시각을 소수 넷째 자리로 반올림한 값이라 같은 방법으로 반올림해 찾는다.
    탐지를 돌리지 않은 프레임이면 KeyError로 멈춘다. 조용히 "박스 없음"으로 넘기면
    가리지 않은 프레임이 클립에 들어가기 때문이다.
    """
    return table[round(time_sec, 4)]


def to_display_box(bbox: Box, display: Rect) -> Box | None:
    """원본 좌표 박스를 보여줄 크롭 안의 좌표로 옮기고 크롭 크기 안으로 자른다 (다-3).

    크롭 안에 남는 넓이가 없으면(크롭 밖이거나 변만 닿음) None을 돌려준다.
    """
    dx1, dy1, dx2, dy2 = display
    width, height = dx2 - dx1, dy2 - dy1
    x1 = min(max(bbox[0] - dx1, 0), width)
    y1 = min(max(bbox[1] - dy1, 0), height)
    x2 = min(max(bbox[2] - dx1, 0), width)
    y2 = min(max(bbox[3] - dy1, 0), height)
    if x2 <= x1 or y2 <= y1:
        return None
    return [x1, y1, x2, y2]


def blur_sigma(bbox: Box) -> float:
    """박스를 흐릴 세기(시그마)를 구한다. 크롭으로 자르기 전 박스를 넣는다 (다-2).

    잘린 박스로 재면 크롭 경계에 걸친 얼굴이 약하게 흐려진다.
    """
    return min(bbox[2] - bbox[0], bbox[3] - bbox[1]) * MASK_BLUR_SIGMA_RATIO


def blur_box(image: np.ndarray, box: Box, sigma: float) -> None:
    """화면에서 박스 자리만 가우시안 블러로 흐린다. image를 그 자리에서 바꾼다 (다-1).

    박스 자리만 꺼내 흐린 뒤 제자리에 넣으므로 박스 안의 픽셀끼리만 섞이고 박스 밖은 그대로다.
    커널 크기 자리에 (0, 0)을 주면 OpenCV가 시그마에 맞는 크기를 고른다.
    """
    x1, y1, x2, y2 = box
    # copy()로 떼어 내야 OpenCV가 박스 밖 픽셀을 가장자리 계산에 끌어오지 않는다
    patch = image[y1:y2, x1:x2].copy()
    image[y1:y2, x1:x2] = cv2.GaussianBlur(patch, (0, 0), sigma)


def mask_frame(cropped: np.ndarray, dets: list[Det], display: Rect) -> tuple[int, int, int]:
    """보여줄 크롭으로 자른 화면에서 박스를 모두 흐린다.

    (흐린 얼굴 박스 수, 흐린 번호판 박스 수, 크롭 밖이라 버린 박스 수)를 돌려준다.
    """
    faces = plates = dropped = 0
    for det in dets:
        box = to_display_box(det["bbox"], display)
        if box is None:
            dropped += 1
            continue
        blur_box(cropped, box, blur_sigma(det["bbox"]))
        if det["cls"] == "face":
            faces += 1
        else:
            plates += 1
    return faces, plates, dropped


def run_mask(
    video_path: str,
    input_path: str,
    candidates_path: str,
    boxes_path: str,
    out_dir: str,
    numbers_text: str | None,
) -> None:
    """고른 후보마다 가린 클립 c03.mp4 … 를 쓴다. 뼈대는 clips.py의 run_clips와 같다 (다-5)."""
    width, height = video_size(video_path)
    data = load_input(input_path, width, height)
    display = even_rect(build_roi(data, (width, height)).display.rect)
    x1, y1, x2, y2 = display
    size = (x2 - x1, y2 - y1)
    fps = video_fps(video_path)

    all_clips = load_clips(candidates_path)
    if not all_clips:
        print("후보 0개")
        return
    numbers = parse_numbers(numbers_text, len(all_clips))
    clips = [all_clips[n - 1] for n in numbers]
    table = load_boxes(boxes_path)
    os.makedirs(out_dir, exist_ok=True)

    writers: dict[int, H264Writer] = {}  # 지금 쓰고 있는 클립 (후보 번호 → ffmpeg)
    # 후보 번호 → [프레임 수, 흐린 얼굴 박스 수, 흐린 번호판 박스 수, 버린 박스 수]
    stats = {n: [0, 0, 0, 0] for n in numbers}
    for frame in iter_clip_frames(video_path, clips):
        # iter_clip_frames는 넘겨준 목록 안의 순서(1부터)를 준다. 원래 후보 번호로 되돌린다
        frame_numbers = [numbers[i - 1] for i in frame.clip_numbers]
        cropped = frame.image[y1:y2, x1:x2]
        counts = mask_frame(cropped, boxes_at(table, frame.time_sec), display)

        for number in [n for n in writers if n not in frame_numbers]:
            writers.pop(number).close()  # 이 프레임이 안 들어가는 후보는 끝났다
        for number in frame_numbers:
            if number not in writers:
                out_path = os.path.join(out_dir, f"c{number:02d}.mp4")
                writers[number] = H264Writer(out_path, size, fps, video_path, all_clips[number - 1])
            writers[number].write(cropped)
            stat = stats[number]
            stat[0] += 1
            for i, count in enumerate(counts, start=1):
                stat[i] += count
    for writer in writers.values():
        writer.close()

    for number in numbers:
        start, end = all_clips[number - 1]
        frames, faces, plates, dropped = stats[number]
        print(
            f"후보 {number} · {start:g}~{end:g}초 · {frames}장 · 흐린 얼굴 박스 {faces} · "
            f"흐린 번호판 박스 {plates} · 크롭 밖이라 버린 박스 {dropped}"
            f" → {os.path.join(out_dir, f'c{number:02d}.mp4')}"
        )
    print(f"후보 {len(numbers)}개, 클립 크기 {size[0]}×{size[1]}, 초당 {fps:.3f}장")


if __name__ == "__main__":
    if len(sys.argv) not in (6, 7):
        print(
            "사용법: python -m pipeline.deidentify.mask"
            " <영상> <입력 JSON> <candidates.jsonl> <deid_boxes.jsonl> <출력 폴더> [후보 번호]"
        )
        sys.exit(2)
    try:
        run_mask(*sys.argv[1:6], sys.argv[6] if len(sys.argv) == 7 else None)
    except (
        InputError,
        CropError,
        RoiError,
        ClipError,
        DetectError,
        MaskError,
        FileNotFoundError,
    ) as e:
        print(f"오류: {e}")
        sys.exit(1)
