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

TRACKS_FILE = "tracks.jsonl"
RANGES_FILE = "yolo_ranges.json"
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


@dataclass(frozen=True)
class Scene:
    """영상 하나에서 한 번만 만드는 것."""

    roi: Roi
    floor_map: FloorMap | None
    damage_edges: list[int]
    far_edges: list[int]  # 건너편 변 (카메라 쪽 변이 아닌 변)
    regions: list[tuple[float, float, np.ndarray | None]]  # YOLO 구간의 (시작, 끝, 기준 영역)


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
        shown = floor_point_visible(
            reduced_box(line["bbox"], crop), others, _region_at(scene, line["t"]), crop.reduced_size
        )
        # 바닥 지도 바깥이라 거리를 못 잰 프레임은 바닥점이 안 보인 것으로 친다 (06장 "바닥 지도 바깥")
        frames.append(Frame(line["t"], shown and dist is not None, dist, in_zone))
    return frames


def report_line(track_id: int, cls: str | None, roi_touch: bool, frames: list[Frame]) -> dict:
    """filter_report.jsonl의 한 줄 (D-332 가-3)."""
    dists = [f.dist_m for f in frames if f.dist_m is not None]
    return {
        "track_id": track_id,
        "cls": cls,
        "frames": len(frames),
        "start_sec": frames[0].t,
        "end_sec": frames[-1].t,
        "roi_touch": roi_touch,
        "min_dist_m": round(min(dists), 2) if dists else None,
        "zone_frames": sum(f.in_zone for f in frames),
        "rules": [],
        "kept_by": {},
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
    )

    by_time = load_tracks(str(Path(tracks_dir) / TRACKS_FILE))
    report = []
    for track_id, lines in sorted(group_tracks(by_time).items()):
        cls = track_class([line.get("cls") for line in lines])
        frames = track_frames(lines, cls, by_time, scene)
        report.append(report_line(track_id, cls, touches_roi(lines, roi), frames))

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    # 6단계가 이 폴더 하나만 읽도록 5-가의 두 파일을 그대로 복사해 둔다 (D-332 가-2)
    for name in (TRACKS_FILE, RANGES_FILE):
        shutil.copyfile(Path(tracks_dir) / name, out / name)
    _write_jsonl(out / REPORT_FILE, report)

    no_roi = sum(not line["roi_touch"] for line in report)
    print(f"트랙 {len(report)} · ROI 미접촉 {no_roi} · {trust_text(measured)}")


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
