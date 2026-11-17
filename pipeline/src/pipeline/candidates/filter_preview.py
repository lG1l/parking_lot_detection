"""5-나 확인용 영상: 5-가 확인용 영상 위에 구역 점선, 거리 선, 뺀 트랙의 X와 규칙 이름을 덧그린다 (D-332 가-4, 가-6).

YOLO·MOG2를 다시 돌리지 않는다. 5-가 영상을 한 프레임씩 읽어 그 위에 그리므로 앞 단계 표시가 그대로 남는다.
"""

import itertools
import math
from dataclasses import dataclass

import cv2
import numpy as np

from pipeline.candidates.crop import Point
from pipeline.candidates.floor_map import (
    CAR_END_M,
    CAR_OUT_M,
    PERSON_BEYOND_M,
    PERSON_END_M,
    PERSON_OUT_M,
    FloorMap,
    FloorPoint,
    distance_to_edge,
    edge_length,
    edge_point,
    nearest_on_edge,
    segment_points,
    to_floor,
    to_screen,
)
from pipeline.candidates.motion_preview import DARK, GRAY
from pipeline.candidates.preview import draw_labels
from pipeline.candidates.track_preview import _track_color
from pipeline.candidates.video import SAMPLING_FPS, select_by_time

PINK = (180, 105, 255)  # 사람 구역
TEAL = (170, 170, 0)  # 차 구역
BLACK = (0, 0, 0)  # 뺀 트랙의 X와 규칙 이름 바탕

_ZONE_STEP_M = 0.1  # 구역 테두리를 바닥에서 이 간격의 점으로 나눠 화면으로 옮긴다
_DASH_STEPS = 3  # 점선: 이 개수의 토막을 그리고 같은 개수를 건너뛴다
_ARC_STEPS = 16  # 내 차 너머 구역의 둥근 모퉁이 하나를 나누는 수
_ZONE_LINE = 2
_DIST_LINE = 1
_X_LINE = 3
_LINE_GAP = 34  # 글 한 줄의 높이 (px). preview의 글꼴 크기 22에 여백을 더한 값
_BELOW_GAP = 6  # 사각형 아래 변과 그 아래 첫 글 줄 사이
_HEADLINE_POS = (20, 80 + 6 * _LINE_GAP)  # 5-가의 왼쪽 위 글 줄(최대 6줄) 바로 아래

Label = tuple[str, tuple[int, int], tuple[int, int, int]]
Zone = tuple[list[Point | None], tuple[int, int, int]]  # (테두리의 화면 점들, 색)


class PreviewError(Exception):
    """확인용 영상을 만들 수 없다."""


@dataclass
class TrackMark:
    """트랙 하나를 그리는 데 필요한 판정 결과."""

    rules: list[str]  # 걸린 규칙 이름
    roi_touch: bool  # ROI 자격이 있는지. 없으면 X 없이 규칙 이름만 쓴다
    person_like: (
        bool | None
    )  # 사람·동물이면 True, 승용차·오토바이·자전거면 False, 거리를 재지 않는 종류면 None
    visible: set[float]  # 바닥점이 보이는 프레임의 시각


def analysis_times(video_path: str) -> list[float]:
    """원본 영상의 분석 프레임 시각 목록. 화면을 풀지 않고 시각만 읽는다."""
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise FileNotFoundError(f"영상을 열 수 없습니다: {video_path}")
    times: list[float] = []

    def grab_times():
        while cap.grab():
            times.append(cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0)
            yield times[-1]

    try:
        # select_by_time은 5-가가 분석 프레임을 고를 때 쓴 함수라 같은 프레임이 골라진다
        return [times[position] for position in select_by_time(grab_times())]
    finally:
        cap.release()


def _polyline(points: list[tuple[float, float]], step: float) -> list[tuple[float, float]]:
    """꼭짓점을 잇는 닫힌 선을 step 간격의 점으로 나눈다. 마지막 점은 첫 점과 같다."""
    out = []
    for a, b in zip(points, points[1:] + points[:1], strict=True):
        n = max(math.ceil(math.dist(a, b) / step), 1)
        out += [(a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n) for i in range(n)]
    return out + [points[0]]


def strip_outline(floor_map: FloorMap, edge: int, out_m: float, end_m: float) -> list[FloorPoint]:
    """변 edge의 띠(06장 "띠의 모양") 테두리를 바닥의 점들로."""
    far = edge_length(floor_map, edge) + end_m
    corners = [(-end_m, 0.0), (-end_m, out_m), (far, out_m), (far, 0.0)]
    return [edge_point(floor_map, edge, a, o) for a, o in _polyline(corners, _ZONE_STEP_M)]


def beyond_outline(floor_map: FloorMap, edge: int, radius_m: float) -> list[FloorPoint]:
    """내 차 너머의 사람 구역 테두리: 변 edge의 바깥쪽에서 변(선분)까지의 거리가 radius_m 이하인 곳.

    변의 양 끝에서는 거리가 같은 점들이 원의 4분의 1 모양이 된다.
    """
    length = edge_length(floor_map, edge)
    quarter = [math.pi / 2 * i / _ARC_STEPS for i in range(_ARC_STEPS + 1)]
    corners = [(-radius_m * math.cos(a), radius_m * math.sin(a)) for a in quarter] + [
        (length + radius_m * math.sin(a), radius_m * math.cos(a)) for a in quarter
    ]
    return [edge_point(floor_map, edge, a, o) for a, o in _polyline(corners, _ZONE_STEP_M)]


def _on_screen(point: Point | None, size: tuple[int, int]) -> bool:
    return point is not None and 0 <= point[0] < size[0] and 0 <= point[1] < size[1]


def _zone(
    floor_map: FloorMap, outline: list[FloorPoint], color: tuple, text: str, size: tuple[int, int]
) -> tuple[Zone, list[Label]]:
    """바닥의 테두리를 화면 점으로 옮기고, 화면에 찍히는 첫 점에 이름표를 단다."""
    points = [to_screen(floor_map, p) for p in outline]
    # 화면 밖이거나 바닥 지도 바깥(카메라 뒤쪽)인 점은 건너뛴다
    points = [p if _on_screen(p, size) else None for p in points]
    shown = [p for p in points if p is not None]
    labels = [(text, (int(shown[0][0]), int(shown[0][1])), color)] if shown else []
    return (points, color), labels


def build_zones(
    floor_map: FloorMap | None, damage_edges: list[int], far_edges: list[int], size: tuple[int, int]
) -> tuple[list[Zone], list[Label]]:
    """파손 변마다 사람 구역과 차 구역, 파손 변이 건너편 변이면 내 차 너머 구역을 만든다."""
    zones: list[Zone] = []
    labels: list[Label] = []
    if floor_map is None:
        return zones, labels
    for edge in damage_edges:
        made = [
            (strip_outline(floor_map, edge, CAR_OUT_M, CAR_END_M), TEAL, "차 구역"),
            (strip_outline(floor_map, edge, PERSON_OUT_M, PERSON_END_M), PINK, "사람 구역"),
        ]
        if edge in far_edges:
            made.append((beyond_outline(floor_map, edge, PERSON_BEYOND_M), PINK, "사람 구역(너머)"))
        for outline, color, text in made:
            zone, zone_labels = _zone(floor_map, outline, color, text, size)
            zones.append(zone)
            labels += zone_labels
    return zones, labels


def draw_zones(image: np.ndarray, zones: list[Zone]) -> None:
    """구역 테두리를 점선으로 그린다 (image를 직접 고친다). 토막을 몇 개 그리고 몇 개 건너뛴다."""
    for points, color in zones:
        for i, (a, b) in enumerate(itertools.pairwise(points)):
            if a is None or b is None or (i // _DASH_STEPS) % 2:
                continue
            cv2.line(image, (int(a[0]), int(a[1])), (int(b[0]), int(b[1])), color, _ZONE_LINE)


def closest_pair(
    floor_map: FloorMap, bbox: list[float], person_like: bool, damage_edges: list[int]
) -> tuple[float, Point, Point] | None:
    """(파손 변까지 거리 m, 바닥점의 화면 점, 파손 변 위 가장 가까운 점의 화면 점). 잴 수 없으면 None.

    사람·동물의 바닥점은 bbox 아래 변의 가운데, 차는 아래 변에서 파손 변에 가장 가까운 점이다 (D-325).
    """
    x1, _, x2, y2 = bbox
    if person_like:
        point = to_floor(floor_map, ((x1 + x2) / 2, y2))
        candidates = [] if point is None else [point]
    else:
        a, b = to_floor(floor_map, (x1, y2)), to_floor(floor_map, (x2, y2))
        candidates = [] if a is None or b is None else segment_points(a, b)
    pairs = [(distance_to_edge(floor_map, p, e), p, e) for p in candidates for e in damage_edges]
    if not pairs:
        return None
    dist, point, edge = min(pairs, key=lambda pair: pair[0])
    start = to_screen(floor_map, point)
    end = to_screen(floor_map, nearest_on_edge(floor_map, point, edge))
    if start is None or end is None:
        return None
    return dist, start, end


def _draw_x(image: np.ndarray, bbox: list[float]) -> None:
    x1, y1, x2, y2 = (int(v) for v in bbox)
    cv2.line(image, (x1, y1), (x2, y2), BLACK, _X_LINE)
    cv2.line(image, (x1, y2), (x2, y1), BLACK, _X_LINE)


def _draw_track(
    image: np.ndarray,
    line: dict,
    mark: TrackMark,
    floor_map: FloorMap | None,
    damage_edges: list[int],
) -> list[Label]:
    """트랙 줄 하나의 거리 선과 X를 그리고 (image를 직접 고친다), 써야 할 글을 돌려준다."""
    x1, _, _, y2 = (int(v) for v in line["bbox"])
    if not mark.roi_touch:
        # 멀리 주차한 차가 많아 X와 거리 선을 그리면 화면이 가려진다. 규칙 이름만 쓴다
        return [(", ".join(mark.rules), (x1, y2 + _BELOW_GAP), GRAY)]
    labels: list[Label] = []
    below: list[tuple[str, tuple[int, int, int]]] = []
    if mark.person_like is not None and floor_map is not None:
        color = _track_color(line["track_id"])
        pair = closest_pair(floor_map, line["bbox"], mark.person_like, damage_edges)
        if line["t"] in mark.visible and pair is not None:
            dist, start, end = pair
            a, b = (int(start[0]), int(start[1])), (int(end[0]), int(end[1]))
            cv2.line(image, a, b, color, _DIST_LINE)
            labels.append((f"{dist:.1f}m", ((a[0] + b[0]) // 2, (a[1] + b[1]) // 2), color))
        else:
            below.append(("바닥점 안 보임", color))
    if mark.rules:
        _draw_x(image, line["bbox"])
        below.append(("뺌: " + ", ".join(mark.rules), BLACK))
    return labels + [
        (text, (x1, y2 + _BELOW_GAP + i * _LINE_GAP), color)
        for i, (text, color) in enumerate(below)
    ]


def make_filter_preview(
    video_path: str,
    source_video: str,
    out_video: str,
    by_time: dict[float, list[dict]],
    marks: dict[int, TrackMark],
    floor_map: FloorMap | None,
    damage_edges: list[int],
    far_edges: list[int],
    headline: str,
) -> int:
    """5-가 확인용 영상(source_video)에 5-나 표시를 덧그려 out_video로 쓴다. 쓴 프레임 수를 돌려준다.

    floor_map이 None이면(바닥 지도를 믿지 않음) 구역과 거리 선을 그리지 않는다.
    """
    times = analysis_times(video_path)
    cap = cv2.VideoCapture(source_video)
    if not cap.isOpened():
        raise FileNotFoundError(f"5-가 확인용 영상을 열 수 없습니다: {source_video}")
    try:
        count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        # 프레임 수가 다르면 프레임과 시각의 짝이 밀려 엉뚱한 프레임에 그리게 된다
        if count != len(times):
            raise PreviewError(
                f"5-가 확인용 영상의 프레임 수({count})가 원본 영상의 분석 프레임 수({len(times)})와 "
                f"다릅니다: {source_video}"
            )
        size = (int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
        zones, zone_labels = build_zones(floor_map, damage_edges, far_edges, size)
        writer = cv2.VideoWriter(out_video, cv2.VideoWriter_fourcc(*"mp4v"), SAMPLING_FPS, size)
        for time_sec in times:
            ok, image = cap.read()
            if not ok:
                raise PreviewError(f"5-가 확인용 영상을 끝까지 읽지 못했습니다: {source_video}")
            draw_zones(image, zones)
            labels = zone_labels + [(headline, _HEADLINE_POS, DARK)]
            # 트랙 줄의 t는 소수 셋째 자리까지라 같은 자리로 맞춰 찾는다 (04장 4.8)
            for line in by_time.get(round(time_sec, 3), []):
                labels += _draw_track(image, line, marks[line["track_id"]], floor_map, damage_edges)
            writer.write(draw_labels(image, labels))
        writer.release()
    finally:
        cap.release()
    return len(times)
