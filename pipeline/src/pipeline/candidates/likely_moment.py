"""유력 시점: 파손 위치에 가장 가까웠던 프레임 (06장 6.5 "유력 시점", D-245).

프레임 하나의 거리를 재는 일과 가장 가까운 프레임을 고르는 일만 한다.
이 거리는 유력 시점에만 쓴다. 트랙을 빼는 조건에는 쓰지 않는다.
"""

import math
from dataclasses import dataclass

import numpy as np

from pipeline.candidates.crop import Crop, Point
from pipeline.candidates.floor_map import FloorMap, FloorPoint, to_floor
from pipeline.candidates.inputs import AnalysisInput
from pipeline.candidates.track_filter import (
    CAR_LIKE,
    KEEP_ON_TIE,
    TOUCH_RATIO,
    floor_point_visible,
    reduced_box,
    touches_box,
    touches_region,
)

TIE_RATIO = 1.01  # 01장 1.6 "유력 시점 동률 폭": 최솟값의 이 배수 이하인 프레임을 모두 잡는다

# 사람은 바닥점으로 잰다. 동물은 사람과 같은 빼는 조건을 쓰지만 유력 시점은 화면 거리다 (D-252)
POINT_CLASSES = ("person",)
# bbox 아래 변으로 잰다. 트럭·버스도 승용차와 같은 계산이다 (D-251)
EDGE_CLASSES = CAR_LIKE + KEEP_ON_TIE

METHOD_POINT = "바닥점"
METHOD_EDGE = "아래 변"
METHOD_RANGE = "발 범위"
METHOD_SCREEN = "화면 거리"

UNIT_FLOOR = "m"
UNIT_SCREEN = "px"

Bbox = list[float]  # [x1, y1, x2, y2] 원본 픽셀


@dataclass(frozen=True)
class Damage:
    """거리를 재는 상대. 영상 하나에서 한 번만 만든다."""

    bbox: Bbox  # 파손 사각형
    corners: list[Point]  # 내 차 바닥 네 모서리
    far_edges: list[int]  # 건너편 변
    screen_points: list[Point]  # 파손 변마다의 파손 지점 (화면). 확인용 영상에 그린다
    floor_points: list[FloorPoint]  # 위 점을 바닥 지도로 옮긴 것. 옮기지 못한 점은 없다


def pick_closest(dists: list[float]) -> list[int]:
    """가장 가까운 프레임들의 순번. 최솟값 × 동률 폭 이하를 모두 고른다. 최솟값이 0이면 0만 남는다."""
    limit = min(dists) * TIE_RATIO
    return [i for i, dist in enumerate(dists) if dist <= limit]


def _edge_y_at(a: Point, b: Point, x: float) -> float | None:
    """세로줄 x가 선분 a–b와 만나는 점의 y. 만나지 않으면 None."""
    if a[0] == b[0] or not min(a[0], b[0]) <= x <= max(a[0], b[0]):
        return None
    return a[1] + (b[1] - a[1]) * (x - a[0]) / (b[0] - a[0])


def damage_point(damage_bbox: Bbox, a: Point, b: Point) -> Point:
    """파손 지점: 파손 사각형의 가운데 세로줄이 파손 변 a–b와 만나는 점 (화면).

    만나지 않으면 변에서 그 세로줄에 가장 가까운 점, 곧 가까운 쪽 끝점을 쓴다 (D-333 나-7).
    """
    x = (damage_bbox[0] + damage_bbox[2]) / 2
    y = _edge_y_at(a, b, x)
    if y is not None:
        return (x, y)
    return min(a, b, key=lambda p: abs(p[0] - x))


def build_damage(data: AnalysisInput, floor_map: FloorMap | None, far_edges: list[int]) -> Damage:
    corners = data.floor_corners
    screen = [
        damage_point(data.damage_bbox, corners[e], corners[(e + 1) % 4]) for e in data.damage_edges
    ]
    floor = [to_floor(floor_map, p) for p in screen] if floor_map is not None else []
    return Damage(data.damage_bbox, corners, far_edges, screen, [p for p in floor if p is not None])


def screen_distance(bbox: Bbox, damage_bbox: Bbox) -> float:
    """화면에서 bbox와 파손 사각형 사이의 가장 짧은 거리 (원본 픽셀). 겹치면 0."""
    gap_x = max(damage_bbox[0] - bbox[2], bbox[0] - damage_bbox[2], 0.0)
    gap_y = max(damage_bbox[1] - bbox[3], bbox[1] - damage_bbox[3], 0.0)
    return math.hypot(gap_x, gap_y)


def _segment_distance(a: FloorPoint, b: FloorPoint, p: FloorPoint) -> float:
    """바닥의 선분 a–b에서 점 p까지의 가장 짧은 거리 (m). a와 b가 같으면 점과 점의 거리다."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    length2 = dx * dx + dy * dy
    along = 0.0 if length2 == 0 else ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / length2
    along = min(max(along, 0.0), 1.0)
    return math.dist((a[0] + dx * along, a[1] + dy * along), p)


def covered_end(
    bbox: Bbox, others: list[Bbox], region: np.ndarray | None, crop: Crop, damage: Damage
) -> Point:
    """발을 가린 물체의 바닥 쪽 끝 (화면). "발이 있을 수 있는 범위"의 아래 끝이다 (D-333 나-5).

    세로줄은 bbox 아래 변 가운데의 x다. 가린 물체가 여럿이면 가장 아래 끝을 쓴다.
    아래로 더 내려갈 곳이 없으면 "몸이 보이는 아래 끝"(bbox 아래 변 가운데) 그대로다.
    """
    x, bottom = (bbox[0] + bbox[2]) / 2, bbox[3]
    box = reduced_box(bbox, crop)
    margin = min(crop.reduced_size) * TOUCH_RATIO
    ends = [bottom]
    # 내 차에 가림: 차에 붙어 서 있다고 보고 바닥 사각형의 건너편 변까지 내린다
    if touches_region(box, region, margin):
        corners = damage.corners
        crossings = [_edge_y_at(corners[e], corners[(e + 1) % 4], x) for e in damage.far_edges]
        ends += [y for y in crossings if y is not None]
    # 다른 트랙에 가림: 그 bbox의 아래 변까지 내린다
    ends += [other[3] for other in others if touches_box(box, reduced_box(other, crop), margin)]
    # 분석 크롭 가장자리에 잘림: 가장자리 점은 bbox 아래 변과 같은 자리라 더할 것이 없다
    return (x, max(ends))


def measure(
    bbox: Bbox,
    cls: str | None,
    others: list[Bbox],
    region: np.ndarray | None,
    crop: Crop,
    floor_map: FloorMap | None,
    damage: Damage,
) -> tuple[float, str] | None:
    """프레임 하나에서 (파손 위치까지의 거리, 잰 방법). 잴 수 없는 프레임이면 None (D-333 나-6).

    others는 같은 프레임의 다른 트랙 bbox, region은 그 시각의 기준 영역(내 차)이다.
    """
    if cls not in POINT_CLASSES + EDGE_CLASSES:
        return screen_distance(bbox, damage.bbox), METHOD_SCREEN
    if floor_map is None or not damage.floor_points:
        return None

    center = ((bbox[0] + bbox[2]) / 2, bbox[3])
    other_boxes = [reduced_box(other, crop) for other in others]
    if not floor_point_visible(reduced_box(bbox, crop), other_boxes, region, crop.reduced_size):
        ends, method = (center, covered_end(bbox, others, region, crop, damage)), METHOD_RANGE
    elif cls in POINT_CLASSES:
        ends, method = (center, center), METHOD_POINT
    else:
        ends, method = ((bbox[0], bbox[3]), (bbox[2], bbox[3])), METHOD_EDGE

    a, b = to_floor(floor_map, ends[0]), to_floor(floor_map, ends[1])
    if a is None or b is None:
        return None
    return min(_segment_distance(a, b, p) for p in damage.floor_points), method


def unit_of(method: str) -> str:
    return UNIT_SCREEN if method == METHOD_SCREEN else UNIT_FLOOR
