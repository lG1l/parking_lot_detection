"""분석 크롭·입력을 원본 영상 위에 그린 확인용 영상을 만든다. 명령의 진입점이다.

실행 (pipeline/ 폴더에서):
    uv run python -m pipeline.candidates.preview <영상> <입력 JSON> <출력 폴더>
"""

import os
import sys

import cv2
import numpy as np

from pipeline.candidates.crop import Crop, CropError, analysis_crop, to_original
from pipeline.candidates.inputs import AnalysisInput, InputError, load_input
from pipeline.candidates.roi import RoiError, build_roi, camera_side_edges
from pipeline.candidates.video import SAMPLING_FPS, iter_analysis_frames

# 그림 색 (BGR)
YELLOW = (0, 255, 255)
WHITE = (255, 255, 255)
BLUE = (255, 128, 0)
RED = (0, 0, 255)
GREEN = (0, 200, 0)

_LINE = 2
_BOLD = 5


def video_size(path: str) -> tuple[int, int]:
    """영상의 (폭, 높이)."""
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise FileNotFoundError(f"영상을 열 수 없습니다: {path}")
    size = (int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
    cap.release()
    return size


def _format_time(sec: float) -> str:
    return f"{int(sec // 60)}:{sec % 60:04.1f}"


def draw_inputs(image: np.ndarray, crop: Crop, data: AnalysisInput) -> None:
    """분석 크롭과 사용자 입력을 image 위에 그린다 (image를 직접 고친다)."""
    x1, y1, x2, y2 = crop.rect
    cv2.rectangle(image, (x1, y1), (x2 - 1, y2 - 1), YELLOW, _LINE)

    vx1, vy1, vx2, vy2 = data.vehicle_bbox
    cv2.rectangle(image, (vx1, vy1), (vx2, vy2), WHITE, _LINE)

    corners = data.floor_corners
    for i in range(4):
        a, b = corners[i], corners[(i + 1) % 4]
        if i in data.damage_edges:
            color, thick = RED, _BOLD
        elif i == data.front_edge:
            color, thick = BLUE, _BOLD
        else:
            color, thick = BLUE, _LINE
        cv2.line(image, a, b, color, thick)
        # 변 번호는 변의 가운데에 쓴다
        mid = ((a[0] + b[0]) // 2, (a[1] + b[1]) // 2)
        cv2.putText(image, str(i), mid, cv2.FONT_HERSHEY_SIMPLEX, 1.0, color, 2)

    dx1, dy1, dx2, dy2 = data.damage_bbox
    cv2.rectangle(image, (dx1, dy1), (dx2, dy2), RED, _LINE)


def roi_contours(mask: np.ndarray, crop: Crop) -> list[np.ndarray]:
    """줄인 프레임 크기 ROI 마스크의 테두리를 원본 픽셀 좌표로 돌려준다."""
    found, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    return [
        np.array([to_original((float(x), float(y)), crop) for x, y in c.reshape(-1, 2)])
        .round()
        .astype(np.int32)
        for c in found
    ]


def draw_roi(image: np.ndarray, contours: list[np.ndarray]) -> np.ndarray:
    """ROI를 초록 반투명 + 테두리로 그린 새 그림을 돌려준다."""
    layer = image.copy()
    cv2.fillPoly(layer, contours, GREEN)
    out = cv2.addWeighted(layer, 0.3, image, 0.7, 0)
    cv2.polylines(out, contours, True, GREEN, _LINE)
    return out


def _draw_label(image: np.ndarray, index: int, time_sec: float) -> None:
    text = f"{_format_time(time_sec)}  #{index}"
    # 어두운 영상에서도 읽히게 검은 테두리를 먼저 쓴다
    cv2.putText(image, text, (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (0, 0, 0), 6)
    cv2.putText(image, text, (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.4, WHITE, 2)


def make_preview(video_path: str, input_path: str, out_dir: str) -> None:
    width, height = video_size(video_path)
    data = load_input(input_path, width, height)
    crop = analysis_crop(data.vehicle_bbox, (width, height))
    crop, roi_mask = build_roi(data, (width, height), crop)
    contours = roi_contours(roi_mask, crop)

    print(f"분석 크롭 (원본 픽셀): {crop.rect}  크기 {crop.width}×{crop.height}")
    print(f"줄인 프레임 크기: {crop.reduced_size[0]}×{crop.reduced_size[1]}")
    print(f"카메라 쪽 변: {camera_side_edges(data.floor_corners)}  파손 변: {data.damage_edges}")
    print(f"ROI 넓이 비율 (분석 크롭 대비): {np.count_nonzero(roi_mask) / roi_mask.size:.1%}")

    os.makedirs(out_dir, exist_ok=True)
    out_video = os.path.join(out_dir, "preview.mp4")
    writer = cv2.VideoWriter(
        out_video, cv2.VideoWriter_fourcc(*"mp4v"), SAMPLING_FPS, (width, height)
    )
    count = 0
    for frame in iter_analysis_frames(video_path):
        image = draw_roi(frame.image, contours)
        draw_inputs(image, crop, data)
        _draw_label(image, frame.index, frame.time_sec)
        if frame.index == 0:
            cv2.imwrite(os.path.join(out_dir, "preview_first.png"), image)
        writer.write(image)
        count += 1
    writer.release()
    print(f"확인용 영상: {out_video} ({count}장, {SAMPLING_FPS}fps)")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("사용법: python -m pipeline.candidates.preview <영상> <입력 JSON> <출력 폴더>")
        sys.exit(2)
    try:
        make_preview(sys.argv[1], sys.argv[2], sys.argv[3])
    except (InputError, CropError, RoiError, FileNotFoundError) as e:
        print(f"오류: {e}")
        sys.exit(1)
