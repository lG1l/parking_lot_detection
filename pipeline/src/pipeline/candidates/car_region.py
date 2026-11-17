"""내 차 영역: 내 차 자리, 내 차 마스크 고르기, 기준 영역 (D-259, D-263, D-264, D-319).

내 차 자리는 영역으로 쓰지 않는다. YOLO가 낸 차량 마스크 가운데 내 차의 것을 고르는 틀이다 (D-264 결정 8).
계산은 모두 줄인 분석 프레임 좌표에서 한다 (D-262, D-263).
"""

from dataclasses import dataclass

import cv2
import numpy as np

from pipeline.candidates.crop import Crop
from pipeline.candidates.inputs import AnalysisInput

# 01장 1.6 "0단계 필터 시작값"의 내 차 고르기 값 (시작값, D-264)
CAR_SPOT_SIDE_RATIO = 0.1  # 좌우 여유: 내 차 자리를 차량 bbox 폭의 이 배씩 좌우로 넓힌다


@dataclass(frozen=True)
class CarSpot:
    mask: np.ndarray  # 내 차 자리. 줄인 프레임 크기, 안쪽 True


def _spot_original(data: AnalysisInput, frame: tuple[int, int]) -> np.ndarray:
    """원본 화면 크기의 내 차 자리 (안쪽 255). 화면 밖으로 나간 부분은 버려진다."""
    width, height = frame
    quad = np.zeros((height, width), np.uint8)
    cv2.fillPoly(quad, [np.array(data.floor_corners, np.int32)], 255)
    filled = quad > 0

    # 세로줄마다 사각형의 아래 경계(가장 아래 픽셀)를 찾는다. 뒤집어서 처음 나오는 칸이 가장 아래 칸이다
    columns = np.nonzero(filled.any(axis=0))[0]
    left, right = int(columns.min()), int(columns.max())
    bottom = height - 1 - np.argmax(filled[::-1], axis=0)

    # 좌우로 넓힌다. 넓힌 세로줄은 사각형 양 끝 세로줄의 아래 경계를 그대로 쓴다.
    # (전체를 가로로 부풀리면 사각형 안쪽 세로줄의 아래 경계까지 옆줄을 따라 내려가 아래 여유 판정이 느슨해진다)
    pad = round((data.vehicle_bbox[2] - data.vehicle_bbox[0]) * CAR_SPOT_SIDE_RATIO)
    xs = np.arange(max(left - pad, 0), min(right + pad, width - 1) + 1)
    spot_bottom = bottom[np.clip(xs, left, right)]

    # 차체는 바닥 사각형의 바로 위에 있다. 위 끝(지붕)은 차량 bbox의 위 변이다 (D-264 원리)
    rows = np.arange(height)[:, None]
    spot = np.zeros((height, width), np.uint8)
    spot[:, xs] = ((rows >= data.vehicle_bbox[1]) & (rows <= spot_bottom)) * 255
    return spot


def build_car_spot(data: AnalysisInput, frame: tuple[int, int], crop: Crop) -> CarSpot | None:
    """내 차 자리를 만든다 (영상마다 한 번). frame은 원본 (폭, 높이).

    네 모서리 사각형이 걸친 세로줄마다 사각형의 아래 경계에서 차량 bbox 위 변까지 채우고 좌우로 넓힌다.
    원본 좌표에서 만든 뒤 ROI와 같은 방법(분석 크롭으로 자르고 줄이기)으로 줄인 프레임에 옮긴다.
    bbox 위 변이 네 모서리보다 아래면 채울 자리가 없으므로 None을 돌려준다.
    """
    if min(y for _, y in data.floor_corners) <= data.vehicle_bbox[1]:
        return None
    full = _spot_original(data, frame)
    x1, y1, x2, y2 = crop.rect
    small = cv2.resize(full[y1:y2, x1:x2], crop.reduced_size, interpolation=cv2.INTER_AREA)
    return CarSpot(small >= 128)
