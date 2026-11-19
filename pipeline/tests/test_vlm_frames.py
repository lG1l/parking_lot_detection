import pytest

from pipeline.vlm.frames import pick_times, to_crop_bbox, to_crop_point

# 분석 프레임의 실제 시각은 k/10보다 조금 뒤다. 0~120초
TIMES = [k / 10 + 0.005 for k in range(1201)]


def test_클립_처음부터_끝_시각_전까지_1초에_1장을_고른다():
    picked = pick_times(TIMES, 38.7, 50.5)
    # 목표 38.7, 39.7 … 49.7 → 12장. 50.7은 끝 시각을 넘어 고르지 않는다
    assert picked == pytest.approx([38.705 + i for i in range(12)])
    assert len(pick_times(TIMES, 73.0, 83.8)) == 11
    # 길이 30.0초는 끝 시각을 포함하지 않아 30장이다
    assert len(pick_times(TIMES, 60.0, 90.0)) == 30


def test_프레임이_빠졌거나_영상이_먼저_끝나면_있는_프레임만_고른다():
    dropped = [t for t in TIMES if abs(t - 39.705) > 1e-6]
    # 39.705가 없으면 목표 39.7 이상인 첫 프레임은 39.805다
    assert pick_times(dropped, 38.7, 50.5)[1] == pytest.approx(39.805)

    short = [t for t in TIMES if t < 40.01]
    # 영상이 40.005에서 끝나면 목표 40.7부터는 고를 프레임이 없다
    assert pick_times(short, 38.7, 50.5) == pytest.approx([38.705, 39.705])


def test_원본_좌표를_크롭_안_좌표로_바꾼다():
    crop_rect = (470, 232, 1765, 960)
    assert to_crop_bbox((864, 592, 1027, 659), crop_rect) == (394, 360, 557, 427)
    assert to_crop_point((732, 723), crop_rect) == (262, 491)
