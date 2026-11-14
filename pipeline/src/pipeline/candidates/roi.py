"""바닥 지도, 카메라 쪽 변 판정, ROI 마스크 (D-194, D-244, D-284).

ROI는 "파손 변 주변에서 접근하는 물체가 화면에 나타나는 자리"다.
파손 변 바깥 바닥 띠를 화면 위로 그대로 옮겨 쓸고 지나간 자리에, 파손 사각형 주변을 더한다 (D-284).
"""

from dataclasses import dataclass

import cv2
import numpy as np

from pipeline.candidates.crop import Crop, display_crop, expand_to_contain
from pipeline.candidates.inputs import AnalysisInput, Point

# 바닥 지도가 가정하는 일반 승용차 크기 (m). D-194, D-244 한계
CAR_WIDTH_M = 1.8
CAR_LENGTH_M = 4.7

# D-284 (시작값)
STRIP_OUT_M = 0.8  # 파손 변 바깥 띠 폭 (m). 손이 닿는 구역과 같다
TWO_EDGE_KEEP_RATIO = 2 / 3  # 파손 변 2개: 각 변을 만나는 모서리에서 이 비율만큼만 쓴다
# 띠를 위로 옮기는 높이: 띠에서 화면 가장 아래(카메라에 가장 가까운) 꼭짓점은 차량 bbox 세로 × 이 값.
# 다른 꼭짓점은 그 자리의 원근 배율만큼 줄이거나 늘린다
VISIBLE_HEIGHT_RATIO = 1.0  # 파손 변이 모두 카메라 쪽
HIDDEN_HEIGHT_RATIO = 1.1  # 그 밖: 차 너머 사람·물체가 지붕 위로 보이는 만큼 더 높인다
DAMAGE_PAD_RATIO = 0.5  # 파손 사각형을 자기 폭·높이의 이 배씩 넓힌 자리는 꼭 ROI에 넣는다
DISPLAY_MARGIN_RATIO = 0.15  # 보여줄 크롭: ROI를 담는 사각형에 폭·높이의 이 배씩 여백


class RoiError(Exception):
    """ROI를 만들 수 없을 때. 메시지는 사용자에게 그대로 보여 준다."""


@dataclass(frozen=True)
class FloorStrip:
    """파손 변 바깥 바닥 띠. 위로 옮기기 전의 모양이다."""

    polygon: np.ndarray  # 원본 픽셀 (N, 2) int32
    out_m: float  # 파손 변 바깥으로 얼마나 나가는 띠인가 (m)


@dataclass(frozen=True)
class Roi:
    crop: Crop  # 분석 크롭 (보여줄 크롭을 못 담으면 넓힌 것)
    mask: np.ndarray  # 분석 크롭을 줄인 프레임 크기로 만든 ROI (안쪽 255)
    strip: FloorStrip
    display: Crop  # 보여줄 크롭 (ROI 기준)


def camera_side_edges(corners: list[Point]) -> list[int]:
    """네 모서리 사각형에서 바깥쪽이 화면 아래를 향한 변의 번호 (06장 바닥점 필터)."""
    cx = sum(p[0] for p in corners) / 4
    cy = sum(p[1] for p in corners) / 4
    result = []
    for i in range(4):
        a, b = corners[i], corners[(i + 1) % 4]
        # 변에 수직인 방향 둘 가운데, 사각형 가운데에서 멀어지는 쪽이 바깥이다
        normal = (b[1] - a[1], a[0] - b[0])
        away = (a[0] + b[0]) / 2 - cx, (a[1] + b[1]) / 2 - cy
        if normal[0] * away[0] + normal[1] * away[1] < 0:
            normal = (-normal[0], -normal[1])
        if normal[1] > 0:  # 화면 y는 아래로 늘어난다
            result.append(i)
    return result


def floor_points(front_edge: int) -> list[tuple[float, float]]:
    """바닥 지도 위 네 모서리의 위치 (m). 앞쪽 변이 폭 방향 끝 변이다 (D-194).

    모서리 front_edge → (0,0), 그다음 모서리부터 차례로 (폭,0), (폭,길이), (0,길이)다.
    인덱스는 corners 순서와 같다.
    """
    layout = [(0, 0), (CAR_WIDTH_M, 0), (CAR_WIDTH_M, CAR_LENGTH_M), (0, CAR_LENGTH_M)]
    return [layout[(j - front_edge) % 4] for j in range(4)]


def _is_visible_case(data: AnalysisInput) -> bool:
    """파손 변이 모두 카메라 쪽인가. 앞·뒤 끝 변이어도 카메라 쪽이면 파손이 보인다 (D-284)."""
    camera = camera_side_edges(data.floor_corners)
    return all(e in camera for e in data.damage_edges)


def _outward(floor: np.ndarray, edge: int) -> np.ndarray:
    """바닥 지도에서 변 edge의 바깥 방향 단위 벡터. 바닥 지도는 직사각형이라 변 가운데 → 바깥이다."""
    a, b = floor[edge], floor[(edge + 1) % 4]
    out = (a + b) / 2 - floor.mean(axis=0)
    return out / np.linalg.norm(out)


def _floor_strip(data: AnalysisInput) -> np.ndarray:
    """바닥 지도(m)의 띠 다각형.

    변 1개: 변 전체 × 바깥 STRIP_OUT_M. 양 옆으로는 늘리지 않는다.
    변 2개: 만나는 모서리에서 각 변의 2/3까지만 쓰고, 바깥 꼭짓점을 이어 L자 하나로 만든다.
    """
    floor = np.array(floor_points(data.front_edge), dtype=np.float64)
    edges = data.damage_edges
    if len(edges) == 1:
        e = edges[0]
        a, b = floor[e], floor[(e + 1) % 4]
        out = STRIP_OUT_M * _outward(floor, e)
        return np.array([a, b, b + out, a + out])

    # 이웃한 두 변 e1 → e2 (e2의 시작점 = e1의 끝점 = 만나는 모서리)
    e1, e2 = edges if (edges[0] + 1) % 4 == edges[1] else edges[::-1]
    corner = floor[e2]
    p = corner + (floor[e1] - corner) * TWO_EDGE_KEEP_RATIO
    q = corner + (floor[(e2 + 1) % 4] - corner) * TWO_EDGE_KEEP_RATIO
    out1 = STRIP_OUT_M * _outward(floor, e1)
    out2 = STRIP_OUT_M * _outward(floor, e2)
    polygon = np.array([p, corner, q, q + out2, corner + out1 + out2, p + out1])
    return polygon


def _to_screen(points: np.ndarray, to_screen: np.ndarray) -> np.ndarray:
    moved = cv2.perspectiveTransform(points.reshape(-1, 1, 2).astype(np.float32), to_screen)
    return moved.reshape(-1, 2)


def _local_scale(point: np.ndarray, to_screen: np.ndarray) -> float:
    """바닥 지도 point(m) 자리에서 바닥 1m가 화면에서 몇 px로 보이는가 (넓이 배율의 제곱근).

    방향에 따라 조금 다르므로 가로·세로 1m 사각형이 화면에서 차지하는 넓이로 평균을 낸다.
    """
    pts = np.array([point, point + [1.0, 0.0], point + [0.0, 1.0]])
    o, ex, ey = _to_screen(pts, to_screen)
    (ax, ay), (bx, by) = ex - o, ey - o
    return float(np.sqrt(abs(ax * by - ay * bx)))


def _lifts(
    floor_poly: np.ndarray, screen_poly: np.ndarray, to_screen: np.ndarray, base: float
) -> np.ndarray:
    """꼭짓점마다 위로 옮길 높이 (px). 멀리 있는 꼭짓점은 작게 보이므로 덜 올린다 (원근 반영)."""
    scales = np.array([_local_scale(p, to_screen) for p in floor_poly])
    nearest = int(np.argmax(screen_poly[:, 1]))  # 화면 가장 아래 = 카메라에 가장 가깝다
    return base * scales / scales[nearest]


def _sweep_up(mask: np.ndarray, polygon: np.ndarray, lifts: np.ndarray) -> None:
    """polygon의 꼭짓점을 각자 lifts만큼 화면 위로 옮기며 지나간 자리 전체를 mask에 채운다.

    다각형, 옮긴 다각형, 각 변이 지나간 사각형의 합집합이다.
    """
    up = polygon - np.stack([np.zeros(len(lifts)), lifts], axis=1).round().astype(np.int32)
    parts = [polygon, up]
    for i in range(len(polygon)):
        j = (i + 1) % len(polygon)
        parts.append(np.array([polygon[i], polygon[j], up[j], up[i]]))
    for part in parts:
        cv2.fillPoly(mask, [part], 255)


def _roi_mask_original(
    data: AnalysisInput, frame: tuple[int, int]
) -> tuple[np.ndarray, FloorStrip]:
    """원본 화면 크기의 ROI 마스크 (안쪽 255)와 바닥 띠. 화면 밖으로 나간 부분은 버려진다."""
    width, height = frame
    src = np.array(data.floor_corners, dtype=np.float32)
    dst = np.array(floor_points(data.front_edge), dtype=np.float32)
    to_screen = cv2.getPerspectiveTransform(dst, src)

    floor_poly = _floor_strip(data)
    screen_poly = _to_screen(floor_poly, to_screen)
    polygon = np.round(screen_poly).astype(np.int32)
    # 화면 속 차 높이(bbox 세로)를 기준으로 올린다. 차가 화면에서 크든 작든 같은 규칙이 된다
    ratio = VISIBLE_HEIGHT_RATIO if _is_visible_case(data) else HIDDEN_HEIGHT_RATIO
    base = (data.vehicle_bbox[3] - data.vehicle_bbox[1]) * ratio

    mask = np.zeros((height, width), np.uint8)
    _sweep_up(mask, polygon, _lifts(floor_poly, screen_poly, to_screen, base))

    # 파손 사각형 주변이 빠져 있으면 그 자리를 더한다 (합집합이라 이미 덮인 곳은 그대로다)
    dx1, dy1, dx2, dy2 = data.damage_bbox
    pad_x, pad_y = DAMAGE_PAD_RATIO * (dx2 - dx1), DAMAGE_PAD_RATIO * (dy2 - dy1)
    cv2.rectangle(
        mask,
        (round(dx1 - pad_x), round(dy1 - pad_y)),
        (round(dx2 + pad_x), round(dy2 + pad_y)),
        255,
        -1,
    )
    return mask, FloorStrip(polygon, STRIP_OUT_M)


def build_roi(data: AnalysisInput, frame: tuple[int, int], crop: Crop) -> Roi:
    """ROI, 바닥 띠, 보여줄 크롭을 만든다.

    보여줄 크롭은 ROI 기준이고, 분석 크롭이 보여줄 크롭을 못 담으면 분석 크롭을 넓힌다
    (D-95 ROI ⊂ 보여줄 ⊂ 분석). 마스크는 (넓힌) 분석 크롭을 줄인 프레임 크기다 (안쪽 255, D-201).
    """
    full, strip = _roi_mask_original(data, frame)
    ys, xs = np.nonzero(full)
    if len(xs) == 0:
        raise RoiError("ROI가 화면 밖에 있어 비어 있습니다. 바닥 네 모서리를 확인해 주세요.")
    roi_rect = (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)
    display = display_crop(roi_rect, frame, DISPLAY_MARGIN_RATIO)
    crop = expand_to_contain(crop, display.rect, frame)

    x1, y1, x2, y2 = crop.rect
    small = cv2.resize(full[y1:y2, x1:x2], crop.reduced_size, interpolation=cv2.INTER_AREA)
    mask = np.where(small >= 128, 255, 0).astype(np.uint8)
    return Roi(crop, mask, strip, display)
