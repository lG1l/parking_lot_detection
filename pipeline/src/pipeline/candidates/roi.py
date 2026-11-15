"""바닥 지도, 카메라 쪽 변 판정, ROI 마스크 (D-194, D-244, D-284).

ROI는 "파손 변 주변에서 접근하는 물체가 화면에 나타나는 자리"다.
파손 변 바깥 바닥 띠를 화면 위로 그대로 옮겨 쓸고 지나간 자리에, 파손 사각형 주변을 더한다 (D-284).
파손 변이 파손 사각형의 가로 범위에 못 미치면 변을 늘려 띠도 함께 늘린다.
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
END_FLARE_DEG = 30  # 띠의 차에 붙지 않은 끝을 변의 수직선에서 바깥으로 이 각도만큼 벌린다
# 띠를 위로 옮기는 높이: 띠의 화면에서 가장 낮은 꼭짓점은 차량 bbox 세로 × 이 값.
# 다른 꼭짓점은 카메라 깊이에 반비례해 줄이거나 늘린다 (실제로 같은 높이)
VISIBLE_HEIGHT_RATIO = 1.0  # 파손 변이 모두 카메라 쪽
HIDDEN_HEIGHT_RATIO = 1.1  # 그 밖: 차 너머 사람·물체가 지붕 위로 보이는 만큼 더 높인다
# 파손 사각형을 자기 폭의 이 배씩 좌우로 넓힌 자리는 꼭 ROI에 넣는다.
# 파손 변이 그 가로 범위에 못 미치면 변을 그 끝까지 늘려 띠·ROI도 함께 늘린다 (세로는 띠를 쓸어 올린 높이를 따른다)
DAMAGE_PAD_X_RATIO = 0.5 / 3
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


def _unit(v: np.ndarray) -> np.ndarray:
    return v / np.linalg.norm(v)


def _damage_line(data: AnalysisInput) -> tuple[np.ndarray, list[int]]:
    """차에 붙은 파손 선의 점들 (바닥 지도 m)과 그 순서대로의 파손 변 번호.

    변 1개: [시작, 끝]. 변 2개: [p, 만나는 모서리, q]. p·q는 모서리에서 각 변의 2/3 지점이다.
    """
    floor = np.array(floor_points(data.front_edge), dtype=np.float64)
    edges = data.damage_edges
    if len(edges) == 1:
        e = edges[0]
        return np.array([floor[e], floor[(e + 1) % 4]]), [e]
    # 이웃한 두 변 e1 → e2 (e2의 시작점 = e1의 끝점 = 만나는 모서리)
    e1, e2 = edges if (edges[0] + 1) % 4 == edges[1] else edges[::-1]
    corner = floor[e2]
    p = corner + (floor[e1] - corner) * TWO_EDGE_KEEP_RATIO
    q = corner + (floor[(e2 + 1) % 4] - corner) * TWO_EDGE_KEEP_RATIO
    return np.array([p, corner, q]), [e1, e2]


def _extend_end(
    end: np.ndarray, direction: np.ndarray, to_screen: np.ndarray, x_range: tuple[float, float]
) -> np.ndarray:
    """선의 끝 end를 바닥 지도에서 direction(단위 벡터)으로 늘려, 화면 x가 x_range의 끝에 닿게 한다.

    이미 닿았거나 그 방향으로는 닿을 수 없으면 그대로 둔다.
    """
    h = to_screen
    a, c = h[0] @ [*end, 1.0], h[2] @ [*end, 1.0]
    b, e = h[0, :2] @ direction, h[2, :2] @ direction
    # t m 늘린 점의 화면 x = (a + b·t) / (c + e·t). 왼쪽·오른쪽 중 움직이는 쪽 끝을 목표로 한다
    target = x_range[1] if b * c - a * e > 0 else x_range[0]
    denom = b - target * e
    if denom == 0:
        return end
    t = (target * c - a) / denom
    # t ≤ 0: 이미 닿았다. 분모 부호가 바뀜: 카메라 뒤로 넘어가야 닿는다
    if t <= 0 or (c + e * t) * c <= 0:
        return end
    return end + t * direction


def _floor_strip(data: AnalysisInput, to_screen: np.ndarray) -> np.ndarray:
    """바닥 지도(m)의 띠 다각형. 앞쪽 꼭짓점들(파손 선의 점 수만큼)은 차에 붙은 파손 선 위의 점이다.

    파손 선의 두 끝을 파손 사각형(좌우 여백 포함)의 가로 범위까지 늘린 뒤, 바깥 STRIP_OUT_M로 띠를 만든다.
    차에 붙지 않은 두 끝은 바깥으로 갈수록 END_FLARE_DEG만큼 벌어진다.
    변 2개면 두 띠의 바깥 꼭짓점을 이어 L자 하나로 만든다 (만나는 모서리는 이어져 있어 벌릴 끝이 없다).
    """
    floor = np.array(floor_points(data.front_edge), dtype=np.float64)
    line, edges = _damage_line(data)
    start_dir, end_dir = _unit(line[0] - line[1]), _unit(line[-1] - line[-2])

    dx1, _, dx2, _ = data.damage_bbox
    pad_x = DAMAGE_PAD_X_RATIO * (dx2 - dx1)
    x_range = (dx1 - pad_x, dx2 + pad_x)
    line[0] = _extend_end(line[0], start_dir, to_screen, x_range)
    line[-1] = _extend_end(line[-1], end_dir, to_screen, x_range)

    # 바깥 끝이 변 방향으로 더 나가는 거리. 비스듬히 다가오는 사람도 띠 끝에서 잡는다
    flare = STRIP_OUT_M * np.tan(np.radians(END_FLARE_DEG))
    outs = [STRIP_OUT_M * _outward(floor, e) for e in edges]
    outer = [line[-1] + outs[-1] + flare * end_dir]
    if len(edges) == 2:
        outer.append(line[1] + outs[0] + outs[1])
    outer.append(line[0] + outs[0] + flare * start_dir)
    return np.vstack([line, outer])


def _to_screen(points: np.ndarray, to_screen: np.ndarray) -> np.ndarray:
    moved = cv2.perspectiveTransform(points.reshape(-1, 1, 2).astype(np.float32), to_screen)
    return moved.reshape(-1, 2)


def _depth(points: np.ndarray, to_screen: np.ndarray) -> np.ndarray:
    """바닥 지도 점(m)들의 카메라 깊이에 비례하는 값 (바닥 → 화면 변환의 셋째 행 w)."""
    return np.c_[points, np.ones(len(points))] @ to_screen[2]


def _lifts(
    floor_poly: np.ndarray, to_screen: np.ndarray, ref: np.ndarray, base: float
) -> np.ndarray:
    """꼭짓점마다 위로 옮길 높이 (px). 바닥 지도 점 ref에서 base만큼이 되게 원근 배율로 맞춘다.

    같은 실제 높이는 화면에서 깊이에 반비례해 보인다. 그래서 위로 옮긴 경계는 실제로 같은 높이의 선이 되어
    바닥 변과 실제 세계에서 평행하다 (화면에서는 같은 소실점으로 모인다).
    """
    return base * _depth(ref[None], to_screen)[0] / _depth(floor_poly, to_screen)


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

    floor_poly = _floor_strip(data, to_screen)
    polygon = np.round(_to_screen(floor_poly, to_screen)).astype(np.int32)
    # 띠의 화면에서 가장 낮은 꼭짓점(ROI의 낮은 쪽 세로 변)을 화면 속 차 높이(bbox 세로)만큼 올린다.
    # 차가 화면에서 크든 작든 같은 규칙이 된다
    ref = floor_poly[int(np.argmax(polygon[:, 1]))]
    ratio = VISIBLE_HEIGHT_RATIO if _is_visible_case(data) else HIDDEN_HEIGHT_RATIO
    base = (data.vehicle_bbox[3] - data.vehicle_bbox[1]) * ratio

    mask = np.zeros((height, width), np.uint8)
    _sweep_up(mask, polygon, _lifts(floor_poly, to_screen, ref, base))

    # 파손 사각형(좌우 여백 포함)이 빠져 있으면 그 자리를 더한다 (합집합이라 이미 덮인 곳은 그대로다)
    dx1, dy1, dx2, dy2 = data.damage_bbox
    pad_x = DAMAGE_PAD_X_RATIO * (dx2 - dx1)
    cv2.rectangle(mask, (round(dx1 - pad_x), dy1), (round(dx2 + pad_x), dy2), 255, -1)
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
