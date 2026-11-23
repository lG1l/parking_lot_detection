import pytest

from pipeline.deidentify.clips import clip_numbers_at, even_rect

# 프레임 시각이 1/30초 간격인 영상. 0~120초
TIMES = [k / 30 for k in range(3601)]


def test_폭이나_높이가_홀수이면_오른쪽_아래쪽에서_1픽셀_줄인다():
    # 925×520 → 924×520
    assert even_rect((655, 336, 1580, 856)) == (655, 336, 1579, 856)
    # 800×450은 이미 짝수라 그대로다
    assert even_rect((414, 334, 1214, 784)) == (414, 334, 1214, 784)
    # 925×521 → 924×520
    assert even_rect((0, 0, 925, 521)) == (0, 0, 924, 520)


def test_시작_시각_이상_끝_시각_미만인_프레임을_모두_넣는다():
    picked = [t for t in TIMES if clip_numbers_at(t, [(38.7, 50.5)])]
    # 38.7 = 1161/30부터 50.4667 = 1514/30까지 354장. 50.5 = 1515/30은 넣지 않는다
    assert picked[0] == pytest.approx(38.7)
    assert picked[-1] == pytest.approx(1514 / 30)
    assert len(picked) == 354


def test_겹친_클립은_둘_다에_넣고_영상이_먼저_끝나면_거기까지만_넣는다():
    overlapped = [(241.0, 271.0), (268.0, 281.0)]
    assert clip_numbers_at(269.0, overlapped) == [1, 2]
    assert clip_numbers_at(250.0, overlapped) == [1]
    assert clip_numbers_at(275.0, overlapped) == [2]

    # 영상은 120초에 끝난다. 클립 115~125에는 115.0~120.0초의 151장만 들어간다
    picked = [t for t in TIMES if clip_numbers_at(t, [(115.0, 125.0)])]
    assert picked[0] == pytest.approx(115.0)
    assert picked[-1] == pytest.approx(120.0)
    assert len(picked) == 151
