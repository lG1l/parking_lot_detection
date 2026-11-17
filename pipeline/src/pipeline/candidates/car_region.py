"""내 차 영역: 내 차 자리, 내 차 마스크 고르기, 기준 영역 (D-259, D-263, D-264, D-319, D-320).

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
    floor: np.ndarray  # 네 모서리 사각형. 줄인 프레임 크기, 안쪽 True (D-320)


def _floor_original(data: AnalysisInput, frame: tuple[int, int]) -> np.ndarray:
    """원본 화면 크기의 네 모서리 사각형 (안쪽 255). 화면 밖으로 나간 부분은 버려진다."""
    width, height = frame
    quad = np.zeros((height, width), np.uint8)
    cv2.fillPoly(quad, [np.array(data.floor_corners, np.int32)], 255)
    return quad


def _spot_original(data: AnalysisInput, quad: np.ndarray) -> np.ndarray:
    """원본 화면 크기의 내 차 자리 (안쪽 255). quad는 원본 화면 크기의 네 모서리 사각형이다."""
    height, width = quad.shape
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
    quad = _floor_original(data, frame)
    mask = _to_reduced(_spot_original(data, quad), crop)
    # 아래 여유 픽셀 수도 줄인 배율로 바꾼다
    scale_y = crop.reduced_size[1] / crop.height
    margin = (data.vehicle_bbox[3] - data.vehicle_bbox[1]) * CAR_SPOT_BELOW_RATIO * scale_y
    return CarSpot(mask, _too_low(mask, margin), _to_reduced(quad, crop))


def _to_reduced(full: np.ndarray, crop: Crop) -> np.ndarray:
    """원본 화면 크기의 그림(안쪽 255)을 분석 크롭으로 자르고 줄여 참·거짓 그림으로 만든다."""
    x1, y1, x2, y2 = crop.rect
    small = cv2.resize(full[y1:y2, x1:x2], crop.reduced_size, interpolation=cv2.INTER_AREA)
    return small >= 128


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
    """차량 마스크들 가운데 내 차 자리에 선 것을 전부 합쳐 그 프레임의 내 차 영역을 만든다 (D-264 결정 3, D-320).

    masks는 (차량 탐지 수, 높이, 폭)의 참·거짓 그림이다. 세 조건을 모두 만족하는 마스크가 없으면
    "찾지 못함"으로 None을 돌려준다. 프레임마다 처음부터 다시 고르고 앞 프레임 결과를 이어받지 않는다.
    """
    picked = np.zeros(spot.mask.shape, bool)
    for mask in masks:
        area = np.count_nonzero(mask)
        if area == 0:
            continue
        inside = np.count_nonzero(mask & spot.mask) / area
        not_too_low = not (mask & spot.too_low).any()
        # 네 모서리 사각형 안의 픽셀에는 내 차나 더 가까운 물체만 보인다. 내 차 너머의 차는 닿지 못한다 (D-320)
        on_floor = (mask & spot.floor).any()
        if inside >= CAR_SPOT_INSIDE_RATIO and not_too_low and on_floor:
            picked |= mask
    return picked if picked.any() else None


# 다각형 하나 = 꼭짓점 [x, y]의 목록. 줄인 분석 프레임 좌표의 정수다 (D-263)
Polygon = list[list[int]]


def region_polygons(region: np.ndarray) -> list[Polygon]:
    """내 차 영역(참·거짓 그림)을 다각형 목록으로 바꾼다 (D-263). 다각형 하나 = 조각 하나의 바깥 윤곽이다.

    바깥 윤곽만 따므로 안쪽 구멍은 적히지 않는다. 꼭짓점을 줄이는 근사는 하지 않는다.
    CHAIN_APPROX_SIMPLE은 곧은 줄의 가운데 점만 빼므로 다시 그리면 같은 모양이 나온다.
    """
    contours, _ = cv2.findContours(
        region.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    return [contour.reshape(-1, 2).tolist() for contour in contours]


def draw_region(polygons: list[Polygon], shape: tuple[int, int]) -> np.ndarray:
    """다각형 목록을 (높이, 폭) 크기의 참·거짓 그림으로 다시 그린다. 안쪽 구멍은 채워진다.

    기준 영역은 이렇게 다시 그린 모양이다. 파일에 적힌 다각형으로 누구나 같은 모양을 얻는다 (D-263).
    """
    canvas = np.zeros(shape, np.uint8)
    cv2.fillPoly(canvas, [np.array(polygon, np.int32) for polygon in polygons], 1)
    return canvas > 0


@dataclass(frozen=True)
class BaseRegion:
    """YOLO 구간 하나의 기준 영역 (D-259). 트랙 줄의 차 영역 키는 이것과 견줘 잰다."""

    mask: np.ndarray  # 기준 영역. 줄인 프레임 크기, 안쪽 True
    lower: np.ndarray  # 기준 영역의 아래쪽 1/2 (D-219)


@dataclass(frozen=True)
class FramePixels:
    """분석 프레임 한 장의 MOG2 결과. 줄인 프레임 크기의 참·거짓 그림이다 (D-319 결정 3)."""

    foreground: np.ndarray  # 전경. 채널 B가 덩어리를 찾는 그림과 같다 (그림자 제외, 열기 연산 뒤)
    shadow: np.ndarray  # 그림자. MOG2 원본 값이 127인 칸


def _lower_half(region: np.ndarray) -> np.ndarray:
    """영역의 아래쪽 1/2. 세로줄마다 영역의 위 끝과 아래 끝의 가운데보다 아래쪽이다 (D-219).

    영역 전체의 세로 가운데로 자르지 않는다. 차를 비스듬히 보면 가까운 쪽 끝에서 유리까지 들어온다.
    """
    height = region.shape[0]
    top = np.argmax(region, axis=0)
    bottom = height - 1 - np.argmax(region[::-1], axis=0)
    rows = np.arange(height)[:, None]
    # 영역이 없는 세로줄은 region이 모두 False라 결과도 False다
    return region & (rows > (top + bottom) / 2)


def base_region(polygons: list[Polygon], shape: tuple[int, int]) -> BaseRegion | None:
    """다각형 목록을 다시 그려 구간의 기준 영역을 만든다. 빈 목록(내 차를 찾지 못함)이면 None이다."""
    if not polygons:
        return None
    mask = draw_region(polygons, shape)
    return BaseRegion(mask, _lower_half(mask))


def redraw(region: np.ndarray) -> np.ndarray:
    """그 프레임의 내 차 영역을 기준 영역과 같은 방법(바깥 윤곽 → 다시 그리기)으로 만든 모양으로 바꾼다.

    기준 영역은 구멍이 채워진 모양이다. 마스크를 그대로 견주면 구멍 때문에
    가린 것이 없어도 영역 줄어듦이 생긴다 (D-319 결정 4).
    """
    return draw_region(region_polygons(region), region.shape)


def _inside_bbox(bbox: tuple[float, float, float, float], shape: tuple[int, int]) -> np.ndarray:
    """줄인 프레임 좌표의 bbox 안쪽을 True로 칠한 그림. bbox는 가장 가까운 픽셀 경계로 맞춘다."""
    x1, y1, x2, y2 = (max(round(value), 0) for value in bbox)
    inside = np.zeros(shape, bool)
    inside[y1:y2, x1:x2] = True
    return inside


def _ratio(count: int, total: int) -> float:
    """비율을 소수 둘째 자리로 반올림한다 (04장 4.8 예시와 같은 자리)."""
    return round(count / total, 2)


def car_keys(
    bbox: tuple[float, float, float, float],
    base: BaseRegion | None,
    my_car: np.ndarray | None,
    pixels: FramePixels | None,
    stable: bool,
) -> dict:
    """트랙 줄 하나에 쓸 차 영역 키를 잰다 (04장 4.8, D-262, D-319, D-321).

    bbox는 줄인 프레임 좌표다. base는 그 프레임이 속한 구간의 기준 영역(없으면 None),
    my_car는 그 프레임의 내 차 영역(다시 그린 모양, 찾지 못했으면 None),
    pixels는 그 프레임의 MOG2 결과(거슬러 돈 프레임은 MOG2를 다시 돌리지 않아 None),
    stable은 MOG2가 안정된 뒤인지다.
    값이 0인 키는 넣지 않는다(키가 없으면 변화 없음). 잴 수 없는 키는 None(파일에서는 null)이다.
    """
    if base is None:
        # 기준 영역이 없는 구간에서는 잴 것이 없다
        return {}
    inside = _inside_bbox(bbox, base.mask.shape)
    overlap = base.mask & inside
    if not overlap.any():
        return {}

    keys: dict = {}
    if pixels is not None and not stable:
        # 안정 전 전경은 믿을 수 없어 전경을 쓰는 키 셋은 측정 불가다 (06장 6.5 구현 주의사항)
        keys.update(car_fg_px=None, car_front_fg=None, car_out_fg=None)
    elif pixels is not None:
        # NumPy가 센 값은 NumPy 정수라 JSON으로 쓸 수 없다. 파이썬 정수로 바꾼다
        fg_px = int(np.count_nonzero(overlap & (pixels.foreground | pixels.shadow)))
        if fg_px:
            keys["car_fg_px"] = fg_px
        # 분모는 기준 영역 전체 넓이다. bbox가 조금만 걸친 물체는 값이 작게 나온다 (D-321)
        front = _ratio(
            np.count_nonzero(base.lower & inside & pixels.foreground),
            np.count_nonzero(base.mask),
        )
        if front:
            keys["car_front_fg"] = front
        outside = base.mask & ~inside
        out_area = np.count_nonzero(outside)
        if out_area == 0:
            # bbox가 기준 영역을 다 덮으면 "차 전체가 함께 변했는지"를 알 수 없다 (D-319 결정 5)
            keys["car_out_fg"] = None
        else:
            out = _ratio(np.count_nonzero(outside & pixels.foreground), out_area)
            if out:
                keys["car_out_fg"] = out

    if my_car is None:
        # 그 프레임의 내 차 영역이 없으면 영역 줄어듦을 잴 수 없다
        keys["car_lost_px"] = None
    else:
        lost_px = int(np.count_nonzero(overlap & ~my_car))
        if lost_px:
            keys["car_lost_px"] = lost_px
    return keys
