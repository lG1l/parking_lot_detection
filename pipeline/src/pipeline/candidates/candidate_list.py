"""6단계 명령: 남은 트랙으로 후보(클립)와 유력 시점을 계산해 후보 목록 파일에 쓴다 (D-333).

사용법: python -m pipeline.candidates.candidate_list <영상> <입력 JSON> <빼기 결과 폴더> <출력 폴더> [장면 파일] [--no-video]
트랙 파일만 읽어 한 번에 계산한다. 영상은 크기만 읽는다 (06장 6.5, D-333 가-4).
"""

import json
import sys
from dataclasses import dataclass
from pathlib import Path

from pipeline.candidates.candidate_clips import Clip, Range, make_clips, moving_times, track_ranges
from pipeline.candidates.candidate_preview import MomentMark, clock, make_candidate_preview
from pipeline.candidates.crop import CropError
from pipeline.candidates.filter_preview import PreviewError
from pipeline.candidates.floor_map import build_floor_map, is_trusted, trust_range
from pipeline.candidates.inputs import InputError, load_input
from pipeline.candidates.likely_moment import (
    METHOD_SCREEN,
    Damage,
    build_damage,
    measure,
    pick_closest,
    unit_of,
)
from pipeline.candidates.motion_preview import load_scenes
from pipeline.candidates.preview import video_size
from pipeline.candidates.roi import RoiError, build_roi, camera_side_edges
from pipeline.candidates.track_filter import (
    EXCLUDED_FILE,
    RANGES_FILE,
    TRACKS_FILE,
    VIDEO_FILE,
    Scene,
    _load_regions,
    _region_at,
    _write_jsonl,
    group_tracks,
    track_class,
)
from pipeline.candidates.track_preview import load_tracks
from pipeline.candidates.video import SAMPLING_FPS

CANDIDATES_FILE = "candidates.jsonl"
REPORT_FILE = "candidate_report.jsonl"

DIST_DIGITS = 2  # 확인용 기록의 거리 자릿수


@dataclass(frozen=True)
class Moment:
    """유력 시점 하나. 거리와 방법은 확인용 기록과 확인용 영상에만 쓴다."""

    track_id: int
    at_sec: float
    dist: float
    method: str


@dataclass(frozen=True)
class TrackReport:
    """클립 하나 안의 트랙 하나를 잰 결과."""

    track_id: int
    cls: str | None
    frames: int  # 거리를 잰 프레임 수
    moments: list[Moment]


def _in_ranges(t: float, ranges: list[Range]) -> bool:
    return any(start <= t <= end for start, end in ranges)


def measure_track(
    track_id: int,
    lines: list[dict],
    ranges: list[Range],
    clip: Clip,
    by_time: dict[float, list[dict]],
    scene: Scene,
    damage: Damage,
) -> TrackReport:
    """클립 안에서 트랙 하나의 유력 시점을 잡는다. 거리는 그 트랙의 후보 구간 안 프레임에서만 잰다."""
    cls = track_class([line.get("cls") for line in lines])
    measured = []
    for line in lines:
        t = line["t"]
        if not (clip.start_sec <= t <= clip.end_sec and _in_ranges(t, ranges)):
            continue
        others = [o["bbox"] for o in by_time[t] if o["track_id"] != track_id]
        result = measure(
            line["bbox"], cls, others, _region_at(scene, t), scene.roi.crop, scene.floor_map, damage
        )
        if result is not None:
            measured.append((t, *result))
    # 잴 프레임이 없는 트랙은 유력 시점을 만들지 않는다. 그래도 클립에는 남는다
    picked = pick_closest([dist for _, dist, _ in measured]) if measured else []
    moments = [Moment(track_id, *measured[i]) for i in picked]
    return TrackReport(track_id, cls, len(measured), moments)


def candidate_line(clip: Clip, reports: list[TrackReport]) -> dict:
    """후보 목록 파일의 한 줄 (04장 4.8). 키 이름은 candidates 칸과 같다."""
    return {
        "start_sec": clip.start_sec,
        "end_sec": clip.end_sec,
        "track_ids": clip.track_ids,
        "motion_ranges": [list(r) for r in clip.motion_ranges],
        "likely_moments": [
            {"track_id": m.track_id, "at_sec": m.at_sec}
            for report in reports
            for m in report.moments
        ],
    }


def report_line(number: int, report: TrackReport) -> dict:
    """확인용 기록의 한 줄. 다음 단계는 읽지 않는다."""
    closest = report.moments[0] if report.moments else None
    return {
        "clip": number,
        "track_id": report.track_id,
        "cls": report.cls,
        "method": closest.method if closest else None,
        "frames": report.frames,
        "min_dist": round(closest.dist, DIST_DIGITS) if closest else None,
        "unit": unit_of(closest.method) if closest else None,
        "at_sec": [m.at_sec for m in report.moments],
    }


def moment_marks(reports: list[list[TrackReport]]) -> dict[tuple[float, int], MomentMark]:
    """확인용 영상에 그릴 유력 시점. 키는 (시각, 트랙 번호)다."""
    return {
        (m.at_sec, m.track_id): MomentMark(
            f"{m.dist:.{DIST_DIGITS}f}{unit_of(m.method)}", m.method != METHOD_SCREEN
        )
        for group in reports
        for report in group
        for m in report.moments
    }


def scene_text(label: str, start: float, end: float, clips: list[Clip]) -> str:
    """장면 하나와 겹치는 후보 번호를 한 줄로. 예: "2번 1:10~1:30 → 후보 2, 3"."""
    numbers = [
        str(i) for i, clip in enumerate(clips, 1) if clip.start_sec <= end and start <= clip.end_sec
    ]
    found = "후보 " + ", ".join(numbers) if numbers else "후보 없음"
    return f"{label} {clock(start)}~{clock(end)} → {found}"


def run_candidate_list(
    video_path: str,
    input_path: str,
    filter_dir: str,
    out_dir: str,
    scenes_path: str | None,
    make_video: bool,
) -> None:
    """후보 목록을 한 번 계산한다. filter_dir은 track_filter의 결과 폴더다."""
    frame = video_size(video_path)
    data = load_input(input_path, *frame)
    roi = build_roi(data, frame)
    near_edges = camera_side_edges(data.floor_corners)
    scene = Scene(
        roi,
        build_floor_map(data.floor_corners, data.front_edge),
        data.damage_edges,
        [e for e in range(len(data.floor_corners)) if e not in near_edges],
        _load_regions(Path(filter_dir) / RANGES_FILE, roi.crop),
        is_trusted(trust_range(data.floor_corners, data.front_edge, data.damage_edges)),
    )
    damage = build_damage(data, scene.floor_map, scene.far_edges)

    by_time = load_tracks(str(Path(filter_dir) / TRACKS_FILE))
    with open(Path(filter_dir) / EXCLUDED_FILE, encoding="utf-8") as f:
        excluded = {json.loads(text)["track_id"] for text in f}
    with open(Path(filter_dir) / RANGES_FILE, encoding="utf-8") as f:
        duration = json.load(f)["duration_sec"]

    tracks = {i: lines for i, lines in group_tracks(by_time).items() if i not in excluded}
    width, height = roi.crop.reduced_size
    crop_area = width * height  # moved_px는 줄인 분석 프레임의 픽셀 수다
    ranges_by_track = {
        i: track_ranges(moving_times(lines, crop_area)) for i, lines in tracks.items()
    }
    ranges_by_track = {i: ranges for i, ranges in ranges_by_track.items() if ranges}
    clips = make_clips(ranges_by_track, duration)

    if not scene.trusted:
        # 바닥 지도를 믿지 않는 입력의 유력 시점은 아직 정해지지 않았다 (Task 5절 #2). 그때까지는 만들지 않는다
        print("알림: 바닥 지도를 믿지 않는 입력이라 유력 시점을 만들지 않습니다")
    reports = [
        [
            measure_track(i, tracks[i], ranges_by_track[i], clip, by_time, scene, damage)
            for i in clip.track_ids
        ]
        if scene.trusted
        else []
        for clip in clips
    ]

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    # 후보가 없어도 빈 파일을 쓴다. 다음 단계가 "후보 없음"과 "아직 안 돌림"을 가를 수 있다
    _write_jsonl(out / CANDIDATES_FILE, [candidate_line(c, r) for c, r in zip(clips, reports)])
    _write_jsonl(
        out / REPORT_FILE,
        [report_line(n, report) for n, group in enumerate(reports, 1) for report in group],
    )

    moments = sum(len(report.moments) for group in reports for report in group)
    longest = max((clip.end_sec - clip.start_sec for clip in clips), default=0.0)
    print(
        f"후보 {len(clips)}개 · 남은 트랙 {len(tracks)}개 중 후보 구간 있는 트랙 {len(ranges_by_track)}개"
        f" · 유력 시점 {moments}개 · 가장 긴 클립 {longest:.1f}초"
    )
    if scenes_path is not None:
        for s in load_scenes(scenes_path):
            print(scene_text(s.label, s.start_sec, s.end_sec, clips))

    if make_video:
        out_video = out / VIDEO_FILE
        count = make_candidate_preview(
            video_path,
            str(Path(filter_dir) / VIDEO_FILE),
            str(out_video),
            by_time,
            clips,
            moment_marks(reports),
            damage.screen_points,
            duration,
        )
        print(f"확인용 영상: {out_video} ({count}장, {SAMPLING_FPS}fps)")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--no-video"]
    if len(args) not in (4, 5):
        print(
            "사용법: python -m pipeline.candidates.candidate_list "
            "<영상> <입력 JSON> <빼기 결과 폴더> <출력 폴더> [장면 파일] [--no-video]"
        )
        sys.exit(2)
    try:
        run_candidate_list(
            *args[:4],
            scenes_path=args[4] if len(args) == 5 else None,
            make_video="--no-video" not in sys.argv,
        )
    except (InputError, CropError, RoiError, PreviewError, FileNotFoundError) as e:
        print(f"오류: {e}")
        sys.exit(1)
