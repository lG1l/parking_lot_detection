from pipeline.candidates.s1_base.video import select_by_time


def test_고르지_않은_간격에서_목표_시각_이상인_첫_프레임을_고른다():
    # 약 30fps인데 간격이 들쭉날쭉하다
    times = [0.0, 0.030, 0.070, 0.101, 0.133, 0.170, 0.199, 0.205, 0.241, 0.300, 0.333]
    # 목표 0.0 → 0.0, 0.1 → 0.101, 0.2 → 0.205, 0.3 → 0.300
    assert list(select_by_time(times, fps=10)) == [0, 3, 7, 9]


def test_간격이_목표보다_길면_같은_프레임을_두_번_고르지_않는다():
    times = [0.0, 0.05, 0.35, 0.40]
    # 0.35가 목표 0.1·0.2·0.3을 한꺼번에 채운다. 다음 목표는 0.4
    assert list(select_by_time(times, fps=10)) == [0, 2, 3]
