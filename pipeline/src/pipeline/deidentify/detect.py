"""후보 클립의 모든 프레임에서 얼굴·번호판 박스를 찾아 탐지 파일로 쓴다 (D-346).

여기서는 가리지 않는다. 가리는 것은 8-다가 탐지 파일 deid_boxes.jsonl을 읽어서 한다.
확인용 영상(c03_boxes.mp4)은 가리기 전 화면이다. local_storage/ 밖으로 내보내지 않는다 (불변 조건 3).

실행 (pipeline/ 폴더에서):
    uv run python -m pipeline.deidentify.detect
        <영상> <입력 JSON> <candidates.jsonl> <모델 폴더> <출력 폴더> [후보 번호]

후보 번호는 3 또는 4,7 꼴이고, 없으면 모두 돌린다.
모델 폴더는 UrbanAnonymizer 저장소를 받은 곳이다. 저자 코드는 고치지 않고 부르기만 한다 (나-2).
"""

import json
import math
import os
import sys
import time

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
from pipeline.vlm.frames import load_clips

# 모델 입력 크기 (D-FINE-X 1408). 저자 코드가 화면을 이 크기의 정사각형으로 늘려 넣는다
MODEL_INPUT_SIZE = 1408
# 모델 폴더 안에서 꼭 있어야 하는 파일
_MODEL_SCRIPT = "scripts/anonymize.py"
_MODEL_CONFIG = "dfine_x_1408/config.yml"
_MODEL_WEIGHTS = "dfine_x_1408/model.pth"

# 모델이 주는 클래스 번호 → 탐지 파일에 쓰는 이름
CLASS_NAMES = {0: "face", 1: "plate"}
# 클래스별 임계값. 이 점수보다 낮은 박스는 버린다.
# 얼굴은 저자 기본값 0.1에서 0.2로 올렸다. 0.1~0.2의 박스는 거의 유리창·차 지붕 같은 오탐이었다.
# 시작값이고, 값은 측정(19번) 뒤 재검토에서 다시 정한다 (D-346 나-6)
THRESHOLDS = {"face": 0.2, "plate": 0.2}

# 확인용 영상에 그리는 색 (BGR)
_COLORS = {"face": (0, 0, 255), "plate": (0, 255, 255)}  # 얼굴 빨강, 번호판 노랑
_BORDER_COLOR = (255, 255, 255)  # 보여줄 크롭 경계선 (흰색)

Det = dict  # {"cls": "face" | "plate", "bbox": [x1, y1, x2, y2], "conf": 0.412}


class DetectError(Exception):
    """모델 폴더에 파일이 없거나 후보 번호가 틀렸을 때."""


def to_dets(raw: list[dict], crop: Rect) -> list[Det]:
    """모델이 준 박스(분석 크롭 안의 좌표, 실수)를 탐지 파일에 쓰는 박스(원본 픽셀, 정수)로 바꾼다.

    왼쪽·위는 내리고 오른쪽·아래는 올린다. 박스가 줄어들면 얼굴 가장자리가 가려지지 않기 때문이다.
    """
    cx1, cy1, cx2, cy2 = crop
    crop_w, crop_h = cx2 - cx1, cy2 - cy1
    dets = []
    for item in raw:
        cls = CLASS_NAMES[item["category_id"]]
        if item["score"] < THRESHOLDS[cls]:
            continue
        x1, y1, x2, y2 = item["box"]
        # 크롭 밖으로 나간 부분은 잘라 낸다. 탐지에 넣은 화면 밖은 본 적이 없는 곳이다
        x1 = math.floor(min(max(x1, 0), crop_w))
        y1 = math.floor(min(max(y1, 0), crop_h))
        x2 = math.ceil(min(max(x2, 0), crop_w))
        y2 = math.ceil(min(max(y2, 0), crop_h))
        if x2 <= x1 or y2 <= y1:
            continue  # 잘라 내고 나니 남은 것이 없다
        dets.append(
            {
                "cls": cls,
                "bbox": [x1 + cx1, y1 + cy1, x2 + cx1, y2 + cy1],
                "conf": round(float(item["score"]), 3),
            }
        )
    return merge_overlapping(dets)


def _overlaps(a: list[int], b: list[int]) -> bool:
    """두 박스가 넓이가 있게 겹치는가 (변만 맞닿은 것은 겹친 것이 아니다)."""
    return min(a[2], b[2]) > max(a[0], b[0]) and min(a[3], b[3]) > max(a[1], b[1])


def merge_overlapping(dets: list[Det]) -> list[Det]:
    """같은 클래스에서 겹치는 박스들을 모두 감싸는 박스 하나로 합친다 (D-346 나-9).

    모델이 얼굴 하나에 박스를 둘셋 내는 일이 있다. 감싸는 박스로 합치므로 가리는 범위는
    줄지 않는다. 점수는 그중 가장 높은 것을 쓴다.
    """
    merged: list[Det] = []
    for det in dets:
        box, conf = list(det["bbox"]), det["conf"]
        # 합쳐서 커진 박스가 다른 박스와 새로 겹칠 수 있다. 겹치는 것이 없을 때까지 되풀이한다
        while True:
            hit = next(
                (m for m in merged if m["cls"] == det["cls"] and _overlaps(m["bbox"], box)), None
            )
            if hit is None:
                break
            merged.remove(hit)
            other = hit["bbox"]
            box = [
                min(box[0], other[0]),
                min(box[1], other[1]),
                max(box[2], other[2]),
                max(box[3], other[3]),
            ]
            conf = max(conf, hit["conf"])
        merged.append({"cls": det["cls"], "bbox": box, "conf": conf})
    return merged


def make_line(time_sec: float, dets: list[Det]) -> str:
    """탐지 파일의 한 줄 (프레임 한 장). 박스가 없어도 빈 목록으로 쓴다 (나-5).

    8-다는 프레임 시각을 같은 방법(소수 넷째 자리)으로 반올림해 이 줄을 찾는다.
    """
    return json.dumps({"t": round(time_sec, 4), "dets": dets})


def check_model_dir(model_dir: str) -> None:
    """모델 폴더에 있어야 하는 파일이 모두 있는지 본다. 없으면 무엇이 없는지 알린다."""
    for name in (_MODEL_SCRIPT, _MODEL_CONFIG, _MODEL_WEIGHTS):
        if not os.path.isfile(os.path.join(model_dir, name)):
            raise DetectError(f"모델 폴더에 {name} 파일이 없습니다: {model_dir}")


def load_detector(model_dir: str):
    """저자 코드의 Detector를 만들어 (Detector, 장치 이름)을 돌려준다.

    저자 코드와 torch는 이 함수 안에서만 불러온다. 모델이 없는 곳(CI)에서도
    이 파일의 다른 함수를 불러 쓸 수 있어야 하기 때문이다. 9단계도 이 함수를 불러 쓴다.
    """
    # 저자 코드는 가중치 파일을 "안에 든 코드까지 실행하는" 방식으로 읽는다.
    # 이 환경 변수를 켜면 torch가 텐서만 읽는다 (나-2). torch를 불러오기 전에 켠다
    os.environ["TORCH_FORCE_WEIGHTS_ONLY_LOAD"] = "1"
    import torch

    sys.path.insert(0, os.path.join(model_dir, "scripts"))
    from anonymize import Detector

    # 워커(GPU EC2)와 Mac에서 같은 코드가 돌게 있는 것 중 빠른 장치를 고른다 (나-7)
    if torch.cuda.is_available():
        device = "cuda:0"
    elif torch.backends.mps.is_available():
        device = "mps"
    else:
        device = "cpu"
    detector = Detector(
        os.path.join(model_dir, _MODEL_CONFIG),
        os.path.join(model_dir, _MODEL_WEIGHTS),
        device,
        MODEL_INPUT_SIZE,
    )
    return detector, device


def detect_frame(detector, image: np.ndarray, crop: Rect) -> list[Det]:
    """원본 프레임 한 장을 분석 크롭으로 잘라 통째로 모델에 넣는다 (나-3)."""
    from PIL import Image

    x1, y1, x2, y2 = crop
    # OpenCV 프레임은 색 순서가 BGR이다. 저자 코드는 RGB 사진(PIL)을 받는다
    rgb = cv2.cvtColor(image[y1:y2, x1:x2], cv2.COLOR_BGR2RGB)
    # 모델에게는 가장 낮은 임계값으로 받고, 클래스별로 거르고 겹친 것을 합치는 것은 to_dets가 한다
    raw = detector.predict(Image.fromarray(rgb), score_threshold=min(THRESHOLDS.values()))
    return to_dets(raw, crop)


def draw_preview(image: np.ndarray, dets: list[Det], view: Rect, display: Rect, label: str):
    """확인용 화면 한 장을 만든다: 분석 크롭 화면에 박스·점수·보여줄 크롭 경계선·글자 (나-8).

    view는 분석 크롭을 짝수 크기로 맞춘 사각형이다. 그 안의 좌표는 원본 좌표에서 왼쪽 위를 뺀 값이다.
    """
    vx, vy = view[0], view[1]
    frame = image[view[1] : view[3], view[0] : view[2]].copy()
    cv2.rectangle(
        frame, (display[0] - vx, display[1] - vy), (display[2] - vx, display[3] - vy), _BORDER_COLOR
    )
    for det in dets:
        x1, y1, x2, y2 = det["bbox"]
        color = _COLORS[det["cls"]]
        cv2.rectangle(frame, (x1 - vx, y1 - vy), (x2 - vx, y2 - vy), color, 1)
        cv2.putText(
            frame,
            f"{det['conf']:.2f}",
            (x1 - vx, y1 - vy - 3),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.4,
            color,
            1,
        )
    # 글자 뒤에 검은 띠를 먼저 깔아 밝은 천장 위에서도 읽히게 한다
    (text_w, text_h), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 1)
    cv2.rectangle(frame, (0, 0), (text_w + 16, text_h + 16), (0, 0, 0), -1)
    cv2.putText(frame, label, (8, text_h + 8), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
    return frame


def parse_numbers(text: str | None, total: int) -> list[int]:
    """명령에 준 후보 번호("3" 또는 "4,7")를 읽는다. 주지 않았으면 후보 모두다."""
    if text is None:
        return list(range(1, total + 1))
    try:
        numbers = sorted({int(part) for part in text.split(",")})
    except ValueError:
        raise DetectError(f"후보 번호는 3 또는 4,7 꼴이어야 합니다: {text}") from None
    for number in numbers:
        if not 1 <= number <= total:
            raise DetectError(f"후보 번호 {number}이(가) 범위(1~{total}) 밖입니다")
    return numbers


def run_detect(
    video_path: str,
    input_path: str,
    candidates_path: str,
    model_dir: str,
    out_dir: str,
    numbers_text: str | None,
) -> None:
    """고른 후보의 모든 프레임을 탐지해 deid_boxes.jsonl과 후보별 확인용 영상을 쓴다."""
    width, height = video_size(video_path)
    data = load_input(input_path, width, height)
    roi = build_roi(data, (width, height))
    crop, display = roi.crop.rect, roi.display.rect
    view = even_rect(crop)  # 확인용 영상 크기. H.264는 짝수 크기만 받는다
    size = (view[2] - view[0], view[3] - view[1])
    fps = video_fps(video_path)

    all_clips = load_clips(candidates_path)
    if not all_clips:
        print("후보 0개")
        return
    numbers = parse_numbers(numbers_text, len(all_clips))
    clips = [
        all_clips[n - 1] for n in numbers
    ]  # 고른 후보만. 겹치는 프레임은 한 번만 나온다 (나-4)
    check_model_dir(model_dir)
    detector, device = load_detector(model_dir)
    print(f"장치 {device}, 후보 {len(clips)}개 탐지 시작")
    os.makedirs(out_dir, exist_ok=True)

    writers: dict[int, H264Writer] = {}  # 지금 쓰고 있는 확인용 영상 (후보 번호 → ffmpeg)
    # 후보 번호 → [프레임 수, 얼굴 박스 수, 번호판 박스 수, 박스 없는 프레임 수]
    stats = {n: [0, 0, 0, 0] for n in numbers}
    frame_count, model_seconds = 0, 0.0
    with open(os.path.join(out_dir, "deid_boxes.jsonl"), "w") as boxes_file:
        for frame in iter_clip_frames(video_path, clips):
            # iter_clip_frames는 넘겨준 목록 안의 순서(1부터)를 준다. 원래 후보 번호로 되돌린다
            frame_numbers = [numbers[i - 1] for i in frame.clip_numbers]
            started = time.perf_counter()
            dets = detect_frame(detector, frame.image, crop)
            model_seconds += time.perf_counter() - started
            frame_count += 1
            boxes_file.write(make_line(frame.time_sec, dets) + "\n")

            faces = sum(det["cls"] == "face" for det in dets)
            plates = len(dets) - faces
            for number in [n for n in writers if n not in frame_numbers]:
                writers.pop(number).close()  # 이 프레임이 안 들어가는 후보는 끝났다
            for number in frame_numbers:
                if number not in writers:
                    out_path = os.path.join(out_dir, f"c{number:02d}_boxes.mp4")
                    writers[number] = H264Writer(
                        out_path, size, fps, video_path, all_clips[number - 1]
                    )
                label = f"c{number:02d} {frame.time_sec:.2f}s face {faces} plate {plates}"
                writers[number].write(draw_preview(frame.image, dets, view, display, label))
                stat = stats[number]
                stat[0] += 1
                stat[1] += faces
                stat[2] += plates
                stat[3] += not dets
    for writer in writers.values():
        writer.close()

    for number in numbers:
        start, end = all_clips[number - 1]
        frames, faces, plates, empty = stats[number]
        print(
            f"후보 {number} · {start:g}~{end:g}초 · {frames}장 · 얼굴 박스 {faces} · "
            f"번호판 박스 {plates} · 박스 없는 프레임 {empty}"
        )
    if frame_count:
        # 참고값이다. 모델에 넣고 받는 시간만 잰 것이고 영상 읽기·쓰기는 들어 있지 않다
        print(f"탐지한 프레임 {frame_count}장, 프레임당 평균 {model_seconds / frame_count:.3f}초")


if __name__ == "__main__":
    if len(sys.argv) not in (6, 7):
        print(
            "사용법: python -m pipeline.deidentify.detect"
            " <영상> <입력 JSON> <candidates.jsonl> <모델 폴더> <출력 폴더> [후보 번호]"
        )
        sys.exit(2)
    try:
        run_detect(*sys.argv[1:6], sys.argv[6] if len(sys.argv) == 7 else None)
    except (InputError, CropError, RoiError, ClipError, DetectError, FileNotFoundError) as e:
        print(f"오류: {e}")
        sys.exit(1)
