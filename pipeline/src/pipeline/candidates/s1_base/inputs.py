"""입력 JSON을 읽고 검사한다 (D-299). 형식은 04장 payload 그대로다.

검사는 05장 5.7 가운데 손으로 쓴 JSON에서 틀리기 쉬운 것만 한다
(좌표 범위, 점 4개, 마주 보는 변이 만나지 않음, 파손 변 1개 또는 이웃 2개).
"""

import json
from dataclasses import dataclass

Point = tuple[int, int]
Bbox = tuple[int, int, int, int]  # x1, y1, x2, y2 (원본 픽셀)


class InputError(Exception):
    """입력 JSON이 틀렸을 때. 메시지는 사용자에게 그대로 보여 준다."""


@dataclass
class AnalysisInput:
    vehicle_bbox: Bbox
    visible: bool
    damage_bbox: Bbox
    floor_corners: list[Point]  # 찍은 순서. 변 i = [i] → [(i+1) % 4]
    front_edge: int
    damage_edges: list[int]
    description: str | None = None  # 사용자의 파손 설명 (선택). VLM에 참고 자료로만 넣는다


def load_input(path: str, width: int, height: int) -> AnalysisInput:
    """JSON 파일을 읽어 검사한 뒤 돌려준다. width, height는 영상 크기다."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        raise InputError(f"입력 JSON 파일이 없습니다: {path}") from None
    except json.JSONDecodeError as e:
        raise InputError(f"입력 JSON을 읽을 수 없습니다 ({e})") from None

    vehicle = _need(data, "vehicle", dict)
    damage = _need(data, "damage", dict)

    vehicle_bbox = _bbox(_need(vehicle, "bbox", list), "vehicle.bbox", width, height)
    damage_bbox = _bbox(_need(damage, "damage_bbox", list), "damage.damage_bbox", width, height)
    visible = _need(damage, "visible", bool)
    corners = _corners(_need(damage, "floor_corners", list), width, height)
    front_edge = _edge(_need(damage, "front_edge", int), "damage.front_edge")
    edges = _damage_edges(_need(damage, "damage_edges", list))
    description = damage.get("description")
    if description is not None and not isinstance(description, str):
        raise InputError("'description'의 형식이 틀렸습니다. 글이어야 합니다.")
    return AnalysisInput(
        vehicle_bbox, visible, damage_bbox, corners, front_edge, edges, description
    )


def _need(obj: dict, key: str, kind: type):
    if not isinstance(obj, dict) or key not in obj:
        raise InputError(f"'{key}' 항목이 없습니다.")
    value = obj[key]
    # bool은 int의 하위 타입이라 정수 자리에 true/false가 들어오는 것을 막는다
    if kind is int and isinstance(value, bool):
        raise InputError(f"'{key}'는 정수여야 합니다.")
    if not isinstance(value, kind):
        raise InputError(f"'{key}'의 형식이 틀렸습니다. {kind.__name__} 값이어야 합니다.")
    return value


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _bbox(values: list, name: str, width: int, height: int) -> Bbox:
    if len(values) != 4 or not all(_is_int(v) for v in values):
        raise InputError(f"{name}는 정수 4개 [x1, y1, x2, y2]여야 합니다.")
    x1, y1, x2, y2 = values
    if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
        raise InputError(
            f"{name} {values}가 영상 화면({width}x{height}) 밖이거나 x1<x2, y1<y2가 아닙니다."
        )
    return (x1, y1, x2, y2)


def _corners(values: list, width: int, height: int) -> list[Point]:
    if len(values) != 4:
        raise InputError("floor_corners는 점이 정확히 4개여야 합니다.")
    points: list[Point] = []
    for i, p in enumerate(values):
        if not (isinstance(p, list) and len(p) == 2 and all(_is_int(v) for v in p)):
            raise InputError(f"floor_corners[{i}]는 정수 [x, y]여야 합니다.")
        if not (0 <= p[0] <= width and 0 <= p[1] <= height):
            raise InputError(f"floor_corners[{i}] {p}가 영상 화면({width}x{height}) 밖입니다.")
        points.append((p[0], p[1]))
    if len(set(points)) != 4:
        raise InputError("floor_corners에 같은 점이 두 번 나옵니다.")
    # 마주 보는 변(0과 2, 1과 3)이 만나면 꼬인 사각형이라 차의 바닥으로 읽을 수 없다
    for a, b in ((0, 2), (1, 3)):
        if _segments_meet(points[a], points[(a + 1) % 4], points[b], points[(b + 1) % 4]):
            raise InputError(
                f"floor_corners가 꼬여 있습니다. 변 {a}, 변 {b}가 서로 만납니다. "
                "네 모서리를 사각형을 따라 한 방향으로 순서대로 찍어 주세요."
            )
    return points


def _edge(value: int, name: str) -> int:
    if not 0 <= value <= 3:
        raise InputError(f"{name}는 0~3 중 하나여야 합니다. (받은 값: {value})")
    return value


def _damage_edges(values: list) -> list[int]:
    if not all(_is_int(v) for v in values):
        raise InputError("damage_edges는 정수 목록이어야 합니다.")
    edges = [_edge(v, "damage_edges의 변 번호") for v in values]
    if len(edges) == 1:
        return edges
    # 2개는 모서리 파손일 때만이므로 이웃한 변(번호 차이 1 또는 3)이어야 한다
    if len(edges) == 2 and (edges[0] - edges[1]) % 4 in (1, 3):
        return edges
    raise InputError(f"damage_edges는 변 1개이거나 이웃한 변 2개여야 합니다. (받은 값: {values})")


def _cross(o: Point, a: Point, b: Point) -> int:
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def _on_segment(a: Point, b: Point, p: Point) -> bool:
    return min(a[0], b[0]) <= p[0] <= max(a[0], b[0]) and min(a[1], b[1]) <= p[1] <= max(a[1], b[1])


def _segments_meet(a: Point, b: Point, c: Point, d: Point) -> bool:
    """선분 ab와 cd가 만나는지 (끝점이 닿는 것도 만난 것으로 본다)."""
    d1, d2 = _cross(a, b, c), _cross(a, b, d)
    d3, d4 = _cross(c, d, a), _cross(c, d, b)
    if ((d1 > 0 and d2 < 0) or (d1 < 0 and d2 > 0)) and (
        (d3 > 0 and d4 < 0) or (d3 < 0 and d4 > 0)
    ):
        return True
    return (
        (d1 == 0 and _on_segment(a, b, c))
        or (d2 == 0 and _on_segment(a, b, d))
        or (d3 == 0 and _on_segment(c, d, a))
        or (d4 == 0 and _on_segment(c, d, b))
    )
