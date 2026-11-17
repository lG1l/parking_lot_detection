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
CAR_SPOT_INSIDE_RATIO = 0.8  # 안쪽: 마스크 픽셀의 이 비율 이상이 내 차 자리 안에 있어야 한다
CAR_SPOT_BELOW_RATIO = (
    0.1  # 아래 여유: 내 차 자리 아래 경계보다 차량 bbox 높이의 이 배까지는 내려가도 된다
)


@dataclass(frozen=True)
class CarSpot:
    mask: np.ndarray  # 내 차 자리. 줄인 프레임 크기, 안쪽 True
    too_low: np.ndarray  # 내 차 자리의 세로줄에서 아래 경계 + 아래 여유보다 더 아래인 칸 (True)


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
    mask = small >= 128
    # 아래 여유 픽셀 수도 줄인 배율로 바꾼다
    scale_y = crop.reduced_size[1] / crop.height
    margin = (data.vehicle_bbox[3] - data.vehicle_bbox[1]) * CAR_SPOT_BELOW_RATIO * scale_y
    return CarSpot(mask, _too_low(mask, margin))


def _too_low(spot: np.ndarray, margin: float) -> np.ndarray:
    """내 차 자리의 세로줄마다 아래 경계에서 margin 넘게 내려간 칸을 True로 칠한다.

    내 차를 가리는 차는 카메라에 더 가까워 화면에서 더 아래에 닿는다. 이 칸에 닿은 마스크는 내 차가 아니다 (D-264 원리).
    """
    height = spot.shape[0]
    has_spot = spot.any(axis=0)
    bottom = height - 1 - np.argmax(spot[::-1], axis=0)
    rows = np.arange(height)[:, None]
    return has_spot & (rows > bottom + margin)


def pick_my_car(masks: np.ndarray, spot: CarSpot) -> np.ndarray | None:
    """차량 마스크들 가운데 내 차 자리에 선 것을 전부 합쳐 그 프레임의 내 차 영역을 만든다 (D-264 결정 3).

    masks는 (차량 탐지 수, 높이, 폭)의 참·거짓 그림이다. 두 조건을 모두 만족하는 마스크가 없으면
    "찾지 못함"으로 None을 돌려준다. 프레임마다 처음부터 다시 고르고 앞 프레임 결과를 이어받지 않는다.
    """
    picked = np.zeros(spot.mask.shape, bool)
    for mask in masks:
        area = np.count_nonzero(mask)
        if area == 0:
            continue
        inside = np.count_nonzero(mask & spot.mask) / area
        if inside >= CAR_SPOT_INSIDE_RATIO and not (mask & spot.too_low).any():
            picked |= mask
    return picked if picked.any() else None
