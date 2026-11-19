from pipeline.candidates.s5_clips.likely_moment import pick_closest


def test_최솟값의_동률_폭_안인_프레임을_모두_고른다():
    # 2.00 × 1.01 = 2.02 이하만 남는다
    assert pick_closest([2.00, 2.01, 2.03, 5.0]) == [0, 1]


def test_최솟값이_0이면_0인_프레임만_고른다():
    assert pick_closest([0, 0, 0.5]) == [0, 1]
