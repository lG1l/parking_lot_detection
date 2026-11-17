"""후보 구간을 만드는 계산 (06장 6.5 "후보 구간의 규칙", D-245, D-333).

트랙 줄의 moved_px(움직인 픽셀 수)로 그 프레임이 움직인 프레임인지 정한다.
계산만 한다. 파일을 읽고 쓰는 일은 명령 쪽이 한다.
"""

import math
from dataclasses import dataclass

# 01장 1.6 "움직임 판정 시작값" (D-254). 달라진 픽셀이 줄인 분석 프레임 넓이의 이 비율 이상이면 움직인 프레임이다
MOTION_AREA_RATIO = 0.0001


def is_moving_line(line: dict, crop_area: int) -> bool:
    """트랙 줄 하나가 움직인 프레임인지 (D-333 나-4).

    moved_px가 null(맨 첫 프레임)이거나 키가 없으면(거슬러 돈 프레임) 움직임이 아니다.
    """
    moved_px = line.get("moved_px")
    return moved_px is not None and moved_px >= crop_area * MOTION_AREA_RATIO


def has_moving_frame(lines: list[dict], crop_area: int) -> bool:
    """트랙에 움직인 프레임이 하나라도 있는지. 없으면 후보 구간이 생기지 않는다."""
    return any(is_moving_line(line, crop_area) for line in lines)


# 01장 1.6 (D-245, 모두 시작값)
CLIP_MAX_SEC = 30.0  # "후보 클립 길이": 클립은 이 길이 이하다
RANGE_GAP_SEC = (
    1.0  # "후보 구간 끊김 간격": 한 트랙의 움직임이 이 시간 이하로 끊기면 같은 후보 구간이다
)
CLIP_MARGIN_SEC = 5.0  # "클립 앞뒤 여유": 후보 구간 앞과 뒤에 붙이는 시간
MERGE_GAP_SEC = 10.0  # "후보 구간 합치기 간격": 두 구간 사이가 이 시간 이하면 한 클립이다
SPLIT_OVERLAP_SEC = 5.0  # "30초 넘는 후보 구간 나누기": 이웃 클립이 겹치는 시간

CLIP_TIME_DIGITS = 1  # 클립의 시작·끝은 0.1초 단위다 (D-333 나-8)

_TIME_EPS = 1e-6

Range = tuple[float, float]  # (시작, 끝) 초


@dataclass(frozen=True)
class Clip:
    """후보(클립) 하나. 후보 목록 파일의 한 줄에서 유력 시점을 뺀 것이다 (04장 4.8)."""

    start_sec: float
    end_sec: float
    track_ids: list[int]
    motion_ranges: list[Range]


def moving_times(lines: list[dict], crop_area: int) -> list[float]:
    """트랙의 움직인 프레임 시각 목록. lines는 시각 순이다."""
    return [line["t"] for line in lines if is_moving_line(line, crop_area)]


def track_ranges(times: list[float]) -> list[Range]:
    """한 트랙의 움직인 프레임 시각을 후보 구간으로 잇는다 (D-333 나-4). times는 시각 순이다.

    끊김 간격 이하로 끊긴 프레임은 같은 구간이고, 끊긴 시간도 구간에 든다.
    움직인 프레임이 하나뿐이면 길이가 0인 구간이다.
    """
    ranges: list[Range] = []
    for t in times:
        if ranges and t - ranges[-1][1] <= RANGE_GAP_SEC + _TIME_EPS:
            ranges[-1] = (ranges[-1][0], t)
        else:
            ranges.append((t, t))
    return ranges


def join_overlapping(ranges: list[Range]) -> list[Range]:
    """서로 겹치는 구간을 하나로 잇는다. 트랙이 달라도 잇는다. 결과는 시작 순이다."""
    joined: list[Range] = []
    for start, end in sorted(ranges):
        if joined and start <= joined[-1][1]:
            joined[-1] = (joined[-1][0], max(joined[-1][1], end))
        else:
            joined.append((start, end))
    return joined


def merge_near(ranges: list[Range]) -> list[Range]:
    """가까운 구간을 한 클립으로 묶는다. ranges는 겹침을 이은 뒤의 시작 순 목록이다.

    사이가 합치기 간격 이하이고 합친 길이가 클립 길이 이하일 때만 합친다.
    넘게 만드는 구간부터 새로 시작하므로 움직임이 없는 빈 시간에서 잘린다.
    """
    merged: list[Range] = []
    for start, end in ranges:
        if merged:
            first, last = merged[-1]
            near = start - last <= MERGE_GAP_SEC + _TIME_EPS
            if near and end - first <= CLIP_MAX_SEC + _TIME_EPS:
                merged[-1] = (first, end)
                continue
        merged.append((start, end))
    return merged


def split_clips(start: float, end: float) -> list[Range]:
    """묶은 구간 하나를 앞뒤 여유를 붙인 클립들로 나눈다 (06장 "30초를 넘는 후보 구간 나누기").

    영상 처음·끝으로 자르기 전의 값이라 시작이 음수일 수 있다.
    30초 이하 구간을 넣으면 클립 하나가 나온다.
    """
    length = end - start
    step = CLIP_MAX_SEC - SPLIT_OVERLAP_SEC  # 클립 하나가 새로 덮는 길이
    # 클립 수는 가장 적게: 여유 없이 30초 클립을 5초씩 겹쳐 구간을 덮는 데 필요한 수
    count = max(math.ceil((length - SPLIT_OVERLAP_SEC) / step - _TIME_EPS), 1)
    # 클립을 모두 30초로 잡았을 때 덮는 길이에서 구간을 빼고 남는 것이 양끝 여유다. 여유는 5초를 넘지 않는다
    covered = count * step + SPLIT_OVERLAP_SEC
    margin = min(CLIP_MARGIN_SEC, (covered - length) / 2)
    # 여유가 5초로 막히면 30초를 다 채우지 못하므로 모든 클립 길이를 똑같이 줄인다
    clip_length = (length + 2 * margin + SPLIT_OVERLAP_SEC * (count - 1)) / count
    first = start - margin
    return [
        (
            first + i * (clip_length - SPLIT_OVERLAP_SEC),
            first + i * (clip_length - SPLIT_OVERLAP_SEC) + clip_length,
        )
        for i in range(count)
    ]


def trim_clip(start: float, end: float, duration: float) -> Range:
    """클립 시각을 0.1초 단위로 반올림하고 영상 안으로 자른다 (D-333 나-8)."""
    start = max(round(start, CLIP_TIME_DIGITS), 0.0)
    end = min(round(end, CLIP_TIME_DIGITS), duration)
    # 반올림 때문에 클립 길이를 넘으면 끝을 줄인다
    if end - start > CLIP_MAX_SEC:
        end = round(start + CLIP_MAX_SEC, CLIP_TIME_DIGITS)
    return start, end


def _overlaps(a: Range, b: Range) -> bool:
    return a[0] <= b[1] and b[0] <= a[1]


def make_clips(ranges_by_track: dict[int, list[Range]], duration: float) -> list[Clip]:
    """트랙별 후보 구간으로 클립 목록을 만든다 (06장 "클립으로 나누기"). 결과는 시작 순이다."""
    all_ranges = [r for ranges in ranges_by_track.values() for r in ranges]
    clips = []
    for start, end in merge_near(join_overlapping(all_ranges)):
        for raw_start, raw_end in split_clips(start, end):
            clip = trim_clip(raw_start, raw_end, duration)
            # 여유 구간에만 걸친 후보 구간도 이 클립에 넣는다 (D-333 나-9)
            inside = {
                track_id: [r for r in ranges if _overlaps(r, clip)]
                for track_id, ranges in ranges_by_track.items()
            }
            track_ids = sorted(track_id for track_id, ranges in inside.items() if ranges)
            joined = join_overlapping([r for ranges in inside.values() for r in ranges])
            # 후보 구간 목록은 클립 안 부분만 남긴다
            motion = [(max(s, clip[0]), min(e, clip[1])) for s, e in joined]
            clips.append(Clip(clip[0], clip[1], track_ids, motion))
    return clips
