"""바닥 지도: 화면 점 ↔ 바닥 위치(m), 파손 변까지 거리, 손이 닿는 구역(띠), 믿음 검사 (D-193, D-323, D-329, D-330).

바닥 지도는 네 모서리를 폭 1.8m × 길이 4.7m 직사각형에 짝지은 3×3 변환 행렬이다.
바닥 좌표는 모서리 0을 (0, 0)으로 두고 변 0을 x축, 변 1을 y축 방향으로 편 것이다.
ROI 바닥 띠(roi.py)는 이 지도를 쓰지 않는다. 바닥점 필터의 거리와 구역만 이 지도로 잰다 (D-323).
"""

import itertools
import math
from dataclasses import dataclass

import cv2
import numpy as np

from pipeline.candidates.s1_base.crop import Point
from pipeline.candidates.s1_base.roi import CAR_LENGTH_M, CAR_WIDTH_M, STRIP_OUT_M

# 06장 "물체 종류별 구역과 기준 거리" (시작값, D-244, D-324, D-330)
PERSON_OUT_M = STRIP_OUT_M  # 사람 띠: 파손 변 바깥쪽 깊이. ROI 바닥 띠 폭과 같은 값이다
PERSON_END_M = 0.3  # 사람 띠: 파손 변 양 끝에서 더 나가는 길이
PERSON_BEYOND_M = 2.0  # 내 차 너머의 사람: 파손 변까지의 가장 짧은 거리
CAR_OUT_M = 5.0  # 승용차·오토바이 띠: 파손 변 바깥쪽 깊이
CAR_END_M = 2.0  # 승용차·오토바이 띠: 파손 변 양 끝에서 더 나가는 길이

# 바닥 지도 믿음 검사 (시작값, D-329)
TRUST_SHIFT_PX = 3  # 네 모서리 좌표를 이만큼 줄이고 늘려 본다
TRUST_POINT_M = PERSON_OUT_M  # 파손 변 가운데에서 바깥으로 이만큼 떨어진 지점의 거리를 다시 잰다
TRUST_MAX_M = 1.2  # 다시 잰 값이 이보다 크면 믿지 않는다 (0.8m의 1.5배)
TRUST_MIN_M = 0.53  # 다시 잰 값이 이보다 작으면 믿지 않는다 (0.8m ÷ 1.5)

# 차의 bbox 아래 변을 이 개수의 점으로 나눠 띠 안인지 본다. 띠의 가장 짧은 변(0.8m)보다 점 간격이 훨씬 촘촘하다
SEGMENT_SAMPLES = 100

FloorPoint = tuple[float, float]  # 바닥 위치 (m)


@dataclass(frozen=True)
class FloorMap:
    matrix: np.ndarray  # 화면 점 → 바닥 위치
    inverse: np.ndarray  # 바닥 위치 → 화면 점
    corners: np.ndarray  # 바닥 좌표의 네 꼭짓점 (4, 2). 변 i = [i] → [(i + 1) % 4]
    behind: bool  # 화면 점을 바꿀 때 세 번째 값이 음수인 쪽이 바닥 지도 안인지


def _apply(matrix: np.ndarray, point: Point) -> tuple[float, float, float]:
    """행렬을 점에 곱한 세 값. 앞의 두 값을 세 번째 값으로 나누면 바뀐 좌표다."""
    x, y, w = matrix @ np.array([point[0], point[1], 1.0])
    return float(x), float(y), float(w)


def build_floor_map(corners: list[Point], front_edge: int) -> FloorMap | None:
    """네 모서리로 바닥 지도를 만든다. 만들 수 없는 모서리(한 줄로 놓임 등)면 None.

    앞쪽 변과 그 맞은편이 폭, 나머지 두 변이 길이다 (D-194).
    """
    side0 = CAR_WIDTH_M if front_edge % 2 == 0 else CAR_LENGTH_M  # 변 0과 변 2의 길이
    side1 = CAR_LENGTH_M if front_edge % 2 == 0 else CAR_WIDTH_M  # 변 1과 변 3의 길이
    floor = np.array([(0, 0), (side0, 0), (side0, side1), (0, side1)], dtype=np.float32)
    matrix = cv2.getPerspectiveTransform(np.array(corners, dtype=np.float32), floor)
    if not np.all(np.isfinite(matrix)) or abs(np.linalg.det(matrix)) < 1e-12:
        return None
    # 네 모서리는 모두 카메라 앞 바닥이므로 세 번째 값의 부호가 같아야 한다. 다르면 꼬인 사각형이다
    signs = {_apply(matrix, c)[2] > 0 for c in corners}
    if len(signs) != 1:
        return None
    return FloorMap(matrix, np.linalg.inv(matrix), floor.astype(np.float64), not signs.pop())


def to_floor(floor_map: FloorMap, point: Point) -> FloorPoint | None:
    """화면 점 → 바닥 위치 (m). 바닥 지도 바깥(지평선 위쪽·카메라 뒤쪽)이면 None.

    cv2.perspectiveTransform은 세 번째 값을 숨기고 나눠 버려서, 지평선 위쪽 점이
    멀쩡한 바닥 위치처럼 나온다. 그래서 행렬을 직접 곱해 부호를 본다 (06장 "바닥 지도 바깥").
    """
    x, y, w = _apply(floor_map.matrix, point)
    if w == 0 or (w < 0) != floor_map.behind:
        return None
    return (x / w, y / w)


def to_screen(floor_map: FloorMap, point: FloorPoint) -> Point | None:
    """바닥 위치 (m) → 화면 점. 카메라 뒤쪽이라 화면에 찍히지 않는 위치면 None."""
    x, y, w = _apply(floor_map.inverse, point)
    # 역행렬의 세 번째 값은 화면 → 바닥의 세 번째 값과 부호가 같은 쪽이 카메라 앞이다
    if w == 0 or (w < 0) != floor_map.behind:
        return None
    return (x / w, y / w)


def _edge_axes(floor_map: FloorMap, edge: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """변 edge의 (시작 모서리, 변을 따라가는 방향, 바깥 방향). 두 방향은 길이 1이다."""
    start = floor_map.corners[edge]
    end = floor_map.corners[(edge + 1) % 4]
    along = (end - start) / np.linalg.norm(end - start)
    # 변에 수직인 두 방향 가운데 직사각형 가운데에서 멀어지는 쪽이 바깥이다
    out = np.array([along[1], -along[0]])
    if np.dot(out, floor_map.corners.mean(axis=0) - start) > 0:
        out = -out
    return start, along, out


def edge_coords(floor_map: FloorMap, point: FloorPoint, edge: int) -> tuple[float, float]:
    """바닥 위치를 변 edge 기준으로 읽는다: (변을 따라 시작 모서리에서 간 거리, 변에서 바깥으로 나간 거리) m.

    바깥 거리가 음수면 변의 안쪽(내 차 바닥과 그 너머)이다.
    """
    start, along, out = _edge_axes(floor_map, edge)
    offset = np.array(point) - start
    return float(np.dot(offset, along)), float(np.dot(offset, out))


def edge_point(floor_map: FloorMap, edge: int, along_m: float, out_m: float) -> FloorPoint:
    """edge_coords의 반대: 변 edge 기준 (변을 따라 간 거리, 바깥으로 나간 거리)를 바닥 위치로 바꾼다."""
    start, along, out = _edge_axes(floor_map, edge)
    point = start + along * along_m + out * out_m
    return float(point[0]), float(point[1])


def nearest_on_edge(floor_map: FloorMap, point: FloorPoint, edge: int) -> FloorPoint:
    """변 edge(선분) 위에서 바닥 위치 point에 가장 가까운 점. 확인용 영상의 거리 선 끝점이다."""
    along, _ = edge_coords(floor_map, point, edge)
    return edge_point(floor_map, edge, min(max(along, 0.0), edge_length(floor_map, edge)), 0.0)


def edge_length(floor_map: FloorMap, edge: int) -> float:
    """변 edge의 길이 (m)."""
    return float(np.linalg.norm(floor_map.corners[(edge + 1) % 4] - floor_map.corners[edge]))


def distance_to_edge(floor_map: FloorMap, point: FloorPoint, edge: int) -> float:
    """바닥 위치에서 변 edge(선분)까지의 가장 짧은 거리 (m)."""
    along, out = edge_coords(floor_map, point, edge)
    # 선분의 끝을 벗어나면 가까운 끝점까지의 거리다
    over = max(-along, along - edge_length(floor_map, edge), 0.0)
    return math.hypot(over, out)


def in_strip(floor_map: FloorMap, point: FloorPoint, edge: int, out_m: float, end_m: float) -> bool:
    """바닥 위치가 변 edge의 띠 안인지 (06장 "띠의 모양", D-330).

    띠는 변을 한 변으로 하고 바깥으로 out_m 뻗은 직사각형이다. 변을 따라서는 양 끝에서 end_m씩 더 나간다.
    """
    along, out = edge_coords(floor_map, point, edge)
    return -end_m <= along <= edge_length(floor_map, edge) + end_m and 0 <= out <= out_m


def segment_points(a: FloorPoint, b: FloorPoint) -> list[FloorPoint]:
    """바닥의 선분 a–b를 촘촘한 점으로 나눈다. 화면의 직선은 바닥에서도 직선이라 양 끝점만 바꿔 오면 된다."""
    return [
        (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
        for t in np.linspace(0.0, 1.0, SEGMENT_SAMPLES)
    ]


def segment_in_strip(
    floor_map: FloorMap, a: FloorPoint, b: FloorPoint, edge: int, out_m: float, end_m: float
) -> bool:
    """바닥의 선분 a–b가 일부라도 변 edge의 띠 안에 있는지. 차의 bbox 아래 변에 쓴다 (D-330)."""
    return any(in_strip(floor_map, p, edge, out_m, end_m) for p in segment_points(a, b))


def segment_distance(floor_map: FloorMap, a: FloorPoint, b: FloorPoint, edge: int) -> float:
    """바닥의 선분 a–b에서 변 edge까지의 가장 짧은 거리 (m). 차의 bbox 아래 변에 쓴다 (D-325)."""
    return min(distance_to_edge(floor_map, p, edge) for p in segment_points(a, b))


def _trust_point(floor_map: FloorMap, edge: int) -> Point | None:
    """변 edge의 가운데에서 바깥으로 TRUST_POINT_M 떨어진 지점을 화면 점으로."""
    start = floor_map.corners[edge]
    end = floor_map.corners[(edge + 1) % 4]
    middle = (start + end) / 2
    # 바깥 방향은 직사각형 가운데에서 변의 가운데로 가는 방향이다
    out = middle - floor_map.corners.mean(axis=0)
    out = out / np.linalg.norm(out)
    target = middle + out * TRUST_POINT_M
    return to_screen(floor_map, (float(target[0]), float(target[1])))


def trust_range(
    corners: list[Point], front_edge: int, damage_edges: list[int]
) -> tuple[float, float] | None:
    """모서리를 조금씩 틀리게 했을 때 0.8m 지점이 읽히는 거리의 (가장 작은 값, 가장 큰 값) m (D-329).

    네 모서리 좌표 여덟 개를 각각 −3px, 그대로, +3px로 바꾼 모든 조합(3^8)으로 바닥 지도를 다시 만든다.
    거리를 계산할 수 없는 조합이 하나라도 있으면 None이다.
    """
    base = build_floor_map(corners, front_edge)
    if base is None:
        return None
    targets = [(edge, _trust_point(base, edge)) for edge in damage_edges]
    if any(point is None for _, point in targets):
        return None

    flat = [v for corner in corners for v in corner]
    distances = []
    for shifts in itertools.product((-TRUST_SHIFT_PX, 0, TRUST_SHIFT_PX), repeat=len(flat)):
        moved = [v + s for v, s in zip(flat, shifts, strict=True)]
        shaken = build_floor_map(list(zip(moved[0::2], moved[1::2], strict=True)), front_edge)
        if shaken is None:
            return None
        for edge, point in targets:
            on_floor = to_floor(shaken, point)
            if on_floor is None:
                return None
            distances.append(distance_to_edge(shaken, on_floor, edge))
    if not all(math.isfinite(d) for d in distances):
        return None
    return min(distances), max(distances)


def is_trusted(measured: tuple[float, float] | None) -> bool:
    """trust_range의 결과로 바닥 지도를 믿을지 정한다. 계산할 수 없었으면 믿지 않는다 (D-329)."""
    if measured is None:
        return False
    return measured[0] >= TRUST_MIN_M and measured[1] <= TRUST_MAX_M


def trust_text(measured: tuple[float, float] | None) -> str:
    """명령 출력과 확인용 영상에 쓰는 한 줄 (D-332 가-6)."""
    if not is_trusted(measured):
        return "바닥 지도 믿지 않음 (필터 끔)"
    return f"바닥 지도 믿음 {measured[0]:.2f}~{measured[1]:.2f}m"
