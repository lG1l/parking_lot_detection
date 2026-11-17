"""5-나 트랙 빼기: 5-가의 트랙 파일로 지나가기만 한 트랙을 뺀다 (06장 6.5, D-332).

YOLO를 다시 돌리지 않고 트랙 파일(tracks.jsonl)과 YOLO 구간 파일(yolo_ranges.json)만 읽는다.
"""

import json
import math
import shutil
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from pipeline.candidates.car_region import draw_region
from pipeline.candidates.crop import Crop, CropError, to_reduced
from pipeline.candidates.floor_map import (
    CAR_END_M,
    CAR_OUT_M,
    PERSON_BEYOND_M,
    PERSON_END_M,
    PERSON_OUT_M,
    FloorMap,
    build_floor_map,
    distance_to_edge,
    edge_coords,
    in_strip,
    is_trusted,
    segment_distance,
    segment_in_strip,
    to_floor,
    trust_range,
    trust_text,
)
from pipeline.candidates.inputs import InputError, load_input
from pipeline.candidates.preview import video_size
from pipeline.candidates.roi import Roi, RoiError, build_roi, camera_side_edges
from pipeline.candidates.track_preview import load_tracks
from pipeline.candidates.video import SAMPLING_FPS

# 06장 "물체 종류별 구역과 기준 거리": 어느 기준으로 재는지 (D-196, D-245)
PERSON_LIKE = (  # 바닥점 = bbox 아래 변의 가운데. 새를 뺀 동물은 사람과 같은 기준을 쓴다
    "person",
    "cat",
    "dog",
    "horse",
    "sheep",
    "cow",
    "elephant",
    "bear",
    "zebra",
    "giraffe",
)
CAR_LIKE = ("car", "motorcycle", "bicycle")  # bbox 아래 변 전체로 잰다. 자전거는 오토바이와 같다
# 트럭·버스·새·클래스 없는 트랙은 재지 않는다

# 트랙의 클래스가 동률일 때 이 클래스가 끼어 있으면 이쪽으로 정한다. 남기는 쪽이다 (D-269)
KEEP_ON_TIE = ("truck", "bus")

# 바닥점 닿음 여유: 분석 크롭 짧은 변의 이 비율 이하로 가까우면 닿은 것이다 (시작값, D-256)
TOUCH_RATIO = 0.01

# 가장 가까운 순간의 앞과 뒤로 이만큼을 "그 앞뒤"로 본다. 차 앞 트랙 빼기의 연속 시간과 같은 길이다 (D-332 나-1)
NEAR_WINDOW_SEC = 0.5

# 제외 기록에 쓰는 규칙 이름 (04장 4.8, D-331)
RULE_NO_ROI = "ROI 미접촉"
RULE_FLOOR = "바닥점 필터"
RULE_BEYOND = "차 너머 트랙 빼기"
RULE_FRONT = "차 앞 트랙 빼기"

# 차 너머 트랙 빼기를 쓰는 종류: 사람·승용차·오토바이 (06장 6.5, D-245)
BEYOND_CLASSES = ("person", "car", "motorcycle")
# 차 너머: 이 비율(분석 크롭 넓이 대비) 이상인 프레임이 하나라도 있으면 남긴다 (시작값, D-256, D-261)
BEYOND_CHANGE_RATIO = 0.01  # 차 영역 변화 (car_fg_px)
BEYOND_LOST_RATIO = 0.01  # 영역 줄어듦 (car_lost_px). 값은 같지만 따로 조정할 수 있게 상수를 나눈다

# 차 앞 트랙 빼기 (시작값, D-321, D-330)
FRONT_COVER_RATIO = 0.03  # "여러 프레임": car_front_fg가 이 값 이상
FRONT_OUT_RATIO = (
    0.05  # "전체가 함께": car_out_fg가 이 값 이상이면 가린 것이 아니라 차가 흔들린 것이다
)
FRONT_RUN_SEC = 0.5  # 가린 프레임이 이만큼 연속이어야 한다
CROSSED_RUN_SEC = 0.5  # 손이 닿는 구역 안에 이만큼 연속으로 있었으면 건너편으로 넘어간 것이다

TRACKS_FILE = "tracks.jsonl"
RANGES_FILE = "yolo_ranges.json"
EXCLUDED_FILE = "excluded.jsonl"
REPORT_FILE = "filter_report.jsonl"

_TIME_EPS = 1e-6

Box = tuple[float, float, float, float]  # (x1, y1, x2, y2)


@dataclass(frozen=True)
class Frame:
    """트랙 줄 하나에서 계산한 값."""

    t: float
    visible: bool  # 바닥점이 보였는지. 재지 않는 종류는 늘 False다
    dist_m: (
        float | None
    )  # 바닥점에서 파손 변까지의 거리. 재지 않는 종류이거나 바닥 지도 바깥이면 None
    in_zone: bool  # 손이 닿는 구역 안인지
    on_region: bool  # bbox 아래 변이 기준 영역에 닿았는지. 기준 영역이 없는 구간이면 True다
    crossed: bool  # 차 앞 트랙 빼기의 "건너편" 구역 안인지. 재지 않는 종류는 승용차 띠를 빌려 쓴다


@dataclass(frozen=True)
class Scene:
    """영상 하나에서 한 번만 만드는 것."""

    roi: Roi
    floor_map: FloorMap | None
    damage_edges: list[int]
    far_edges: list[int]  # 건너편 변 (카메라 쪽 변이 아닌 변)
    regions: list[tuple[float, float, np.ndarray | None]]  # YOLO 구간의 (시작, 끝, 기준 영역)
    trusted: bool  # 바닥 지도를 믿을 수 있는지 (D-329)


def group_tracks(by_time: dict[float, list[dict]]) -> dict[int, list[dict]]:
    """시각별 트랙 줄을 트랙 번호별로 다시 묶는다. 줄은 시각 순이다."""
    tracks: dict[int, list[dict]] = {}
    for t in sorted(by_time):
        for line in by_time[t]:
            tracks.setdefault(line["track_id"], []).append(line)
    return tracks


def track_class(classes: list[str | None]) -> str | None:
    """트랙의 클래스: 가장 많은 프레임에 나온 클래스 (D-269). classes는 시각 순이다.

    동률이면 남기는 쪽으로 본다. 트럭·버스가 끼어 있으면 트럭·버스, 그 밖은 먼저 나온 클래스다.
    """
    counts = Counter(classes)
    top = max(counts.values())
    tied = [c for c in counts if counts[c] == top]  # Counter는 처음 나온 순서를 지킨다
    for c in tied:
        if c in KEEP_ON_TIE:
            return c
    return tied[0]


def reduced_box(bbox: list[float], crop: Crop) -> Box:
    """원본 좌표의 bbox → 줄인 프레임 좌표. ROI와 기준 영역이 줄인 프레임 크기라 여기에 맞춘다."""
    x1, y1 = to_reduced((bbox[0], bbox[1]), crop)
    x2, y2 = to_reduced((bbox[2], bbox[3]), crop)
    return (x1, y1, x2, y2)


def _any_inside(mask: np.ndarray, box: Box) -> bool:
    """사각형 안에 0이 아닌 칸이 하나라도 있는지. 그림 밖으로 나간 부분은 잘라 낸다."""
    height, width = mask.shape[:2]
    x1, y1 = max(math.floor(box[0]), 0), max(math.floor(box[1]), 0)
    x2, y2 = min(math.ceil(box[2]), width), min(math.ceil(box[3]), height)
    return x1 < x2 and y1 < y2 and bool(mask[y1:y2, x1:x2].any())


def touches_edge(box: Box, size: tuple[int, int], margin: float) -> bool:
    """bbox 아래 변이 분석 크롭 가장자리에 닿았는지. size는 줄인 프레임 (폭, 높이)다."""
    x1, _, x2, y2 = box
    return x1 <= margin or x2 >= size[0] - margin or y2 <= margin or y2 >= size[1] - margin


def cut_by_edge(box: Box, size: tuple[int, int], margin: float) -> bool:
    """bbox의 네 변 가운데 하나라도 분석 크롭 가장자리에 닿았는지. 화면에 들어오고 나가는 트랙을 가린다."""
    x1, y1, x2, y2 = box
    return x1 <= margin or y1 <= margin or x2 >= size[0] - margin or y2 >= size[1] - margin


def touches_box(box: Box, other: Box, margin: float) -> bool:
    """bbox 아래 변이 다른 트랙의 bbox(안쪽 포함)에 닿았는지.

    아래 변이 다른 bbox 안에 들어가 있어도 닿은 것이다. 가린 물체 위에 걸린 것일 수 있어 남기는 쪽으로 본다.
    """
    x1, _, x2, y2 = box
    gap_x = max(other[0] - x2, x1 - other[2], 0.0)
    gap_y = max(other[1] - y2, y2 - other[3], 0.0)
    return math.hypot(gap_x, gap_y) <= margin


def touches_region(box: Box, region: np.ndarray | None, margin: float) -> bool:
    """bbox 아래 변이 기준 영역에 닿았는지. 기준 영역이 없으면 판단할 수 없어 닿은 것으로 본다 (D-332 나-3)."""
    if region is None:
        return True
    x1, _, x2, y2 = box
    # 아래 변을 여유만큼 부풀린 사각형 안에 기준 영역의 칸이 있으면 닿은 것이다
    return _any_inside(region, (x1 - margin, y2 - margin, x2 + margin, y2 + margin + 1))


def floor_point_visible(
    box: Box, others: list[Box], region: np.ndarray | None, size: tuple[int, int]
) -> bool:
    """그 프레임의 바닥점이 보이는지 (06장 "바닥점이 보임의 판정"). 좌표는 모두 줄인 프레임이다.

    bbox 아래 변이 분석 크롭 가장자리, 다른 트랙 bbox, 기준 영역 가운데 하나에라도 닿으면 안 보인 것이다.
    """
    margin = min(size) * TOUCH_RATIO
    if touches_edge(box, size, margin) or touches_region(box, region, margin):
        return False
    return not any(touches_box(box, other, margin) for other in others)


def touches_roi(lines: list[dict], roi: Roi) -> bool:
    """ROI 자격: 한 프레임이라도 bbox가 ROI와 겹쳤는지 (D-202)."""
    return any(_any_inside(roi.mask, reduced_box(line["bbox"], roi.crop)) for line in lines)


def _measure_person(bbox: list[float], scene: Scene) -> tuple[float | None, bool]:
    """사람·동물: 바닥점(bbox 아래 변의 가운데)에서 파손 변까지의 거리와 구역 안인지."""
    point = to_floor(scene.floor_map, ((bbox[0] + bbox[2]) / 2, bbox[3]))
    if point is None:
        return None, False
    dist = min(distance_to_edge(scene.floor_map, point, e) for e in scene.damage_edges)
    in_person_strip = any(
        in_strip(scene.floor_map, point, e, PERSON_OUT_M, PERSON_END_M) for e in scene.damage_edges
    )
    # 내 차 너머의 사람: 바닥점이 건너편 변의 바깥쪽이면 띠 대신 거리로 본다 (D-332 나-4)
    beyond = any(edge_coords(scene.floor_map, point, e)[1] > 0 for e in scene.far_edges)
    return dist, in_person_strip or (beyond and dist <= PERSON_BEYOND_M)


def _measure_car(bbox: list[float], scene: Scene) -> tuple[float | None, bool]:
    """승용차·오토바이·자전거: bbox 아래 변에서 파손 변까지의 가장 짧은 거리와 구역 안인지 (D-325, D-330)."""
    a = to_floor(scene.floor_map, (bbox[0], bbox[3]))
    b = to_floor(scene.floor_map, (bbox[2], bbox[3]))
    if a is None or b is None:
        return None, False
    dist = min(segment_distance(scene.floor_map, a, b, e) for e in scene.damage_edges)
    in_car_strip = any(
        segment_in_strip(scene.floor_map, a, b, e, CAR_OUT_M, CAR_END_M) for e in scene.damage_edges
    )
    return dist, in_car_strip


def measure(bbox: list[float], cls: str | None, scene: Scene) -> tuple[float | None, bool]:
    """트랙의 클래스에 맞는 기준으로 (파손 변까지 거리 m, 구역 안인지)를 잰다. 잴 수 없으면 (None, False)."""
    if scene.floor_map is None:
        return None, False
    if cls in PERSON_LIKE:
        return _measure_person(bbox, scene)
    if cls in CAR_LIKE:
        return _measure_car(bbox, scene)
    return None, False


def in_crossed_zone(bbox: list[float], cls: str | None, scene: Scene) -> bool:
    """차 앞 트랙 빼기의 "건너편으로 넘어갔다"에 쓰는 구역 안인지 (D-330).

    사람·동물·승용차·오토바이·자전거는 바닥점 필터와 같은 구역이다.
    트럭·버스·새·클래스 없는 물체는 여기서만 승용차의 띠를 빌려 쓴다.
    """
    if scene.floor_map is None:
        return False
    if cls in PERSON_LIKE:
        return _measure_person(bbox, scene)[1]
    return _measure_car(bbox, scene)[1]


def _region_at(scene: Scene, t: float) -> np.ndarray | None:
    """시각 t가 속한 YOLO 구간의 기준 영역. 구간을 찾지 못하거나 영역이 비었으면 None."""
    for start, end, region in scene.regions:
        if start - _TIME_EPS <= t <= end + _TIME_EPS:
            return region
    return None


def track_frames(
    lines: list[dict], cls: str | None, by_time: dict[float, list[dict]], scene: Scene
) -> list[Frame]:
    """트랙의 줄마다 바닥점 보임·거리·구역 안을 계산한다."""
    crop = scene.roi.crop
    frames = []
    for line in lines:
        others = [
            reduced_box(other["bbox"], crop)
            for other in by_time[line["t"]]
            if other["track_id"] != line["track_id"]
        ]
        dist, in_zone = measure(line["bbox"], cls, scene)
        box = reduced_box(line["bbox"], crop)
        region = _region_at(scene, line["t"])
        shown = floor_point_visible(box, others, region, crop.reduced_size)
        on_region = touches_region(box, region, min(crop.reduced_size) * TOUCH_RATIO)
        # 바닥 지도 바깥이라 거리를 못 잰 프레임은 바닥점이 안 보인 것으로 친다 (06장 "바닥 지도 바깥")
        crossed = in_crossed_zone(line["bbox"], cls, scene)
        frames.append(
            Frame(line["t"], shown and dist is not None, dist, in_zone, on_region, crossed)
        )
    return frames


def seen_near_closest(frames: list[Frame]) -> bool | None:
    """조건 1: 가장 가까운 순간과 그 앞뒤로 바닥점이 보였는지 (D-332 나-1). 거리를 잰 프레임이 없으면 None.

    가장 가까운 순간은 가려졌는지와 상관없이 거리가 가장 작은 프레임이다.
    """
    measured = [f for f in frames if f.dist_m is not None]
    if not measured:
        return None
    closest = min(measured, key=lambda f: f.dist_m)
    near = [f for f in frames if abs(f.t - closest.t) <= NEAR_WINDOW_SEC + _TIME_EPS]
    return all(f.visible for f in near)


def _normal_end(line: dict, range_times: list[float], scene: Scene) -> bool:
    """트랙의 첫 줄이나 마지막 줄이 정상인지: bbox가 분석 크롭 가장자리에 닿았거나 YOLO 구간의 경계에 있다."""
    size = scene.roi.crop.reduced_size
    if cut_by_edge(reduced_box(line["bbox"], scene.roi.crop), size, min(size) * TOUCH_RATIO):
        return True
    # YOLO가 켜지거나 꺼진 순간이면 트랙이 끊긴 것이 아니다. 분석 프레임 한 칸까지는 같은 순간으로 본다
    one_frame = 1 / SAMPLING_FPS
    return any(abs(line["t"] - t) <= one_frame + _TIME_EPS for t in range_times)


def seen_whole(lines: list[dict], scene: Scene) -> bool:
    """조건 2: 처음부터 끝까지 한 물체로 봤는지 (D-332 나-2). 시작이나 끝이 정상이 아니면 끊긴 트랙이다."""
    starts = [start for start, _, _ in scene.regions]
    ends = [end for _, end, _ in scene.regions]
    return _normal_end(lines[0], starts, scene) and _normal_end(lines[-1], ends, scene)


def floor_filter_keeps(
    lines: list[dict], cls: str | None, frames: list[Frame], scene: Scene
) -> list[str]:
    """바닥점 필터에서 이 트랙을 남기는 이유들 (06장 "빼는 조건"). 비어 있으면 다섯 조건을 모두 만족해 뺀다."""
    if not scene.trusted:
        return ["조건 5: 바닥 지도 믿지 않음"]
    if cls not in PERSON_LIKE and cls not in CAR_LIKE:
        return ["거리를 재지 않는 종류"]
    seen = seen_near_closest(frames)
    if seen is None:
        return ["거리를 잰 프레임 없음"]
    keeps = []
    if not seen:
        keeps.append("조건 1: 가장 가까운 순간 앞뒤로 바닥점 안 보임")
    if not seen_whole(lines, scene):
        keeps.append("조건 2: 끊긴 트랙")
    if any(f.in_zone for f in frames):
        keeps.append("조건 3: 구역 안")
    if any(f.on_region for f in frames):
        keeps.append("조건 4: 내 차에 가려짐")
    return keeps


def longest_run(times: list[float]) -> int:
    """시각 목록에서 분석 프레임이 빠짐없이 이어진 가장 긴 줄의 프레임 수 (D-332 나-6). times는 시각 순이다."""
    step = 1 / SAMPLING_FPS
    best = run = 0
    previous = None
    for t in times:
        # 앞 프레임과의 간격이 분석 프레임 한 칸이면 이어진 것이다. 한 칸이라도 빠지면 새로 센다
        linked = previous is not None and t - previous <= step * 1.5
        run = run + 1 if linked else 1
        best = max(best, run)
        previous = t
    return best


def _unusable(lines: list[dict], keys: tuple[str, ...], scene: Scene) -> list[str]:
    """차 영역 키로 판정할 수 없는 이유. 비어 있으면 판정할 수 있다 (04장 4.8, D-259)."""
    if not scene.trusted:
        return ["바닥 지도 믿지 않음"]
    if any(_region_at(scene, line["t"]) is None for line in lines):
        return ["기준 영역이 없는 구간"]
    # 키가 있는데 값이 null이면 측정 불가다. 키가 없는 것은 "변화 없음"이라 여기에 들지 않는다
    if any(key in line and line[key] is None for line in lines for key in keys):
        return ["측정 불가 프레임 있음"]
    return []


def beyond_keeps(
    lines: list[dict], cls: str | None, frames: list[Frame], scene: Scene
) -> list[str]:
    """차 너머 트랙 빼기에서 이 트랙을 남기는 이유들 (06장 "차 너머 트랙 빼기"). 비어 있으면 뺀다."""
    if cls not in BEYOND_CLASSES:
        return ["쓰지 않는 종류"]
    if any(e in scene.far_edges for e in scene.damage_edges):
        return ["파손 변이 카메라 쪽 변만이 아님"]
    unusable = _unusable(lines, ("car_fg_px", "car_lost_px"), scene)
    if unusable:
        return unusable
    width, height = scene.roi.crop.reduced_size
    crop_area = width * height  # _px 키는 줄인 분석 프레임의 픽셀 수다
    keeps = []
    if any(f.visible for f in frames):
        keeps.append("바닥점이 보임")
    if any(line.get("car_fg_px", 0) >= crop_area * BEYOND_CHANGE_RATIO for line in lines):
        keeps.append("차 영역 변화 있음")
    if any(line.get("car_lost_px", 0) >= crop_area * BEYOND_LOST_RATIO for line in lines):
        keeps.append("영역 줄어듦 있음")
    return keeps


def _covers_front(line: dict) -> bool:
    """그 프레임에서 트랙이 내 차 앞을 가렸는지: 아래쪽 1/2이 충분히 변했고 차 전체가 함께 변하지는 않았다.

    car_out_fg가 null(bbox 바깥의 차 영역이 없음)이면 함께 변했는지 알 수 없어 가린 프레임으로 세지 않는다.
    """
    out = line.get("car_out_fg", 0)
    return (
        line.get("car_front_fg", 0) >= FRONT_COVER_RATIO
        and out is not None
        and out < FRONT_OUT_RATIO
    )


def front_keeps(lines: list[dict], frames: list[Frame], scene: Scene) -> list[str]:
    """차 앞 트랙 빼기에서 이 트랙을 남기는 이유들 (06장 "차 앞 트랙 빼기"). 비어 있으면 뺀다."""
    if not all(e in scene.far_edges for e in scene.damage_edges):
        return ["파손 변이 건너편 변만이 아님"]
    # car_out_fg의 null은 프레임 단위로 다룬다 (_covers_front). MOG2가 안정되기 전이면 car_front_fg도 null이다
    unusable = _unusable(lines, ("car_front_fg",), scene)
    if unusable:
        return unusable
    keeps = []
    covered = longest_run([line["t"] for line in lines if _covers_front(line)])
    if covered < round(FRONT_RUN_SEC * SAMPLING_FPS):
        keeps.append("차 앞을 가리지 않음")
    crossed = longest_run([f.t for f in frames if f.crossed])
    if crossed >= round(CROSSED_RUN_SEC * SAMPLING_FPS):
        keeps.append("건너편으로 넘어갔다")
    return keeps


def judge(lines: list[dict], cls: str | None, frames: list[Frame], scene: Scene) -> tuple:
    """트랙에 걸린 규칙 이름 목록과, 규칙마다 남긴 이유를 낸다.

    ROI 자격이 없는 트랙에는 다른 규칙을 적용하지 않는다.
    그 밖에는 한 규칙에 걸려도 나머지 규칙을 모두 판정한다 (D-331).
    """
    if not touches_roi(lines, scene.roi):
        return [RULE_NO_ROI], {}
    keeps_by_rule = {
        RULE_FLOOR: floor_filter_keeps(lines, cls, frames, scene),
        RULE_BEYOND: beyond_keeps(lines, cls, frames, scene),
        RULE_FRONT: front_keeps(lines, frames, scene),
    }
    rules = [rule for rule, keeps in keeps_by_rule.items() if not keeps]
    kept_by = {rule: ", ".join(keeps) for rule, keeps in keeps_by_rule.items() if keeps}
    return rules, kept_by


def report_line(
    track_id: int, cls: str | None, frames: list[Frame], rules: list[str], kept_by: dict[str, str]
) -> dict:
    """filter_report.jsonl의 한 줄 (D-332 가-3)."""
    dists = [f.dist_m for f in frames if f.dist_m is not None]
    return {
        "track_id": track_id,
        "cls": cls,
        "frames": len(frames),
        "start_sec": frames[0].t,
        "end_sec": frames[-1].t,
        "roi_touch": RULE_NO_ROI not in rules,
        "min_dist_m": round(min(dists), 2) if dists else None,
        "zone_frames": sum(f.in_zone for f in frames),
        "rules": rules,
        "kept_by": kept_by,
    }


def _load_regions(path: Path, crop: Crop) -> list[tuple[float, float, np.ndarray | None]]:
    """YOLO 구간 파일에서 구간마다 (시작, 끝, 기준 영역)을 읽는다. 내 차를 찾지 못한 구간은 None이다."""
    with open(path, encoding="utf-8") as f:
        ranges = json.load(f)["ranges"]
    shape = (crop.reduced_size[1], crop.reduced_size[0])
    return [
        (
            r["start_sec"],
            r["end_sec"],
            draw_region(r["car_region"], shape) if r["car_region"] else None,
        )
        for r in ranges
    ]


def _write_jsonl(path: Path, lines: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(json.dumps(line, ensure_ascii=False) + "\n" for line in lines)


def run_track_filter(
    video_path: str, input_path: str, tracks_dir: str, out_dir: str, make_video: bool
) -> None:
    """트랙 빼기를 한 번 돌린다. tracks_dir은 5-가 결과 폴더, out_dir은 5-나 결과 폴더다."""
    frame = video_size(video_path)
    data = load_input(input_path, *frame)
    roi = build_roi(data, frame)
    measured = trust_range(data.floor_corners, data.front_edge, data.damage_edges)
    near_edges = camera_side_edges(data.floor_corners)
    scene = Scene(
        roi,
        build_floor_map(data.floor_corners, data.front_edge),
        data.damage_edges,
        [e for e in range(len(data.floor_corners)) if e not in near_edges],
        _load_regions(Path(tracks_dir) / RANGES_FILE, roi.crop),
        is_trusted(measured),
    )

    by_time = load_tracks(str(Path(tracks_dir) / TRACKS_FILE))
    report = []
    for track_id, lines in sorted(group_tracks(by_time).items()):
        cls = track_class([line.get("cls") for line in lines])
        frames = track_frames(lines, cls, by_time, scene)
        report.append(report_line(track_id, cls, frames, *judge(lines, cls, frames, scene)))

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    # 6단계가 이 폴더 하나만 읽도록 5-가의 두 파일을 그대로 복사해 둔다 (D-332 가-2)
    for name in (TRACKS_FILE, RANGES_FILE):
        shutil.copyfile(Path(tracks_dir) / name, out / name)
    _write_jsonl(out / REPORT_FILE, report)
    # 제외 기록은 매번 전체를 새로 쓴다. 뺀 트랙이 없어도 빈 파일을 쓴다 (D-331)
    excluded = [
        {"track_id": line["track_id"], "rules": line["rules"]} for line in report if line["rules"]
    ]
    _write_jsonl(out / EXCLUDED_FILE, excluded)

    counts = Counter(rule for line in excluded for rule in line["rules"])
    print(
        f"트랙 {len(report)} · {RULE_NO_ROI} {counts[RULE_NO_ROI]} · {RULE_FLOOR} {counts[RULE_FLOOR]}"
        f" · 차 너머 {counts[RULE_BEYOND]} · 차 앞 {counts[RULE_FRONT]}"
        f" · 남음 {len(report) - len(excluded)} · {trust_text(measured)}"
    )


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--no-video"]
    if len(args) != 4:
        print(
            "사용법: python -m pipeline.candidates.track_filter "
            "<영상> <입력 JSON> <5-가 결과 폴더> <출력 폴더> [--no-video]"
        )
        sys.exit(2)
    try:
        run_track_filter(*args, make_video="--no-video" not in sys.argv)
    except (InputError, CropError, RoiError, FileNotFoundError) as e:
        print(f"오류: {e}")
        sys.exit(1)
