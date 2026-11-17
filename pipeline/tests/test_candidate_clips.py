import pytest

from pipeline.candidates.candidate_clips import (
    join_overlapping,
    make_clips,
    merge_near,
    split_clips,
    track_ranges,
    trim_clip,
)

# 06장 6.5 "클립으로 나누기"의 예시 표를 그대로 옮긴 것이다. 시각은 영상 처음으로 자르기 전의 값이다


def _approx(ranges):
    """예시 표의 숫자는 소수 첫째 자리까지라 0.05초 안이면 같은 것으로 본다."""
    return [pytest.approx(r, abs=0.05) for r in ranges]


def test_끊김_간격_이하는_잇고_넘으면_끊는다():
    assert track_ranges([1.0, 1.1, 1.2, 2.1, 5.0]) == [(1.0, 2.1), (5.0, 5.0)]


@pytest.mark.parametrize(
    ("length", "expected"),
    [
        (3, [(-5, 8)]),  # 여유 5초씩 → 13초
        (26, [(-2, 28)]),  # 여유를 2초씩으로 줄여 30초
        (35, [(-5, 20), (15, 40)]),
        (45, [(-5, 25), (20, 50)]),
        (50, [(-2.5, 27.5), (22.5, 52.5)]),
        (60, [(-5, 21.7), (16.7, 43.3), (38.3, 65)]),
        (95, [(-5, 25), (20, 50), (45, 75), (70, 100)]),
    ],
)
def test_후보_구간_하나를_클립으로_나눈다(length, expected):
    assert split_clips(0, length) == _approx(expected)


@pytest.mark.parametrize(
    ("ranges", "expected"),
    [
        ([(0, 5), (20, 25)], [(-5, 10), (15, 30)]),  # 사이 10초 초과: 각자 클립
        ([(0, 8), (14, 22)], [(-4, 26)]),  # 합친 0~22초에 여유 4초씩
        ([(0, 10), (19, 22), (24, 40)], [(-4, 26), (19, 45)]),  # [A+B], [C]
        ([(0, 15), (12, 40)], [(-5, 22.5), (17.5, 45)]),  # 겹친 것을 이은 0~40초를 둘로
        ([(0, 4), (10, 15), (22, 27)], [(-1.5, 28.5)]),  # 연쇄
        ([(0, 10), (15, 22), (20, 40)], [(-5, 15), (12.5, 42.5)]),  # 겹침을 먼저 잇는다
    ],
)
def test_여러_후보_구간을_합치고_나눈다(ranges, expected):
    clips = [
        clip
        for start, end in merge_near(join_overlapping(ranges))
        for clip in split_clips(start, end)
    ]
    assert clips == _approx(expected)


def test_클립_시각은_반올림하고_영상_안으로_자른다():
    assert trim_clip(-5.0, 8.04, 119.9) == (0.0, 8.0)
    assert trim_clip(100.0, 125.0, 119.9) == (100.0, 119.9)


def test_클립에는_여유_구간에_걸친_트랙도_넣는다():
    # 트랙 1의 구간 50~53초로 클립 45~58초가 생긴다. 트랙 2의 40~46초는 여유 구간에만 걸친다
    # (사이가 10초를 넘지 않지만 여기서는 트랙 2가 먼저라 합쳐진다. 그래서 60초 넘게 떨어진 트랙 3도 둔다)
    clips = make_clips({1: [(50.0, 53.0)], 2: [(40.0, 46.0)], 3: [(100.0, 101.0)]}, 200.0)
    assert [(c.start_sec, c.end_sec, c.track_ids) for c in clips] == [
        (35.0, 58.0, [1, 2]),
        (95.0, 106.0, [3]),
    ]
    assert clips[0].motion_ranges == [(40.0, 46.0), (50.0, 53.0)]
