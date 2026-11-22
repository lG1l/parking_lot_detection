import numpy as np
import pytest

from pipeline.candidates.s4_filter.track_filter import floor_point_visible, longest_run, track_class

# 줄인 프레임 640×360. 닿음 여유는 짧은 변의 1%인 3.6px다
SIZE = (640, 360)
BOX = (300, 100, 340, 200)  # 화면 가운데의 bbox. 아래 변은 y=200, x=300~340


def _region(x1, y1, x2, y2):
    """(x1, y1)~(x2, y2) 사각형만 참인 기준 영역."""
    region = np.zeros((SIZE[1], SIZE[0]), bool)
    region[y1:y2, x1:x2] = True
    return region


FAR_REGION = _region(0, 0, 50, 50)  # 아래 변과 멀리 떨어진 기준 영역


@pytest.mark.parametrize(
    ("classes", "expected"),
    [
        (["car"] * 80 + ["truck"] * 20, "car"),
        (["truck"] * 70 + ["car"] * 30, "truck"),
        (["car"] * 50 + ["truck"] * 50, "truck"),  # 동률은 남기는 쪽
        (["motorcycle"] * 60 + ["bicycle"] * 40, "motorcycle"),
    ],
)
def test_트랙의_클래스는_가장_많은_프레임의_클래스다(classes, expected):
    assert track_class(classes) == expected


def test_아래_변이_분석_크롭_가장자리에_닿으면_바닥점이_안_보인다():
    at_bottom = (300, 100, 340, SIZE[1] - 2)
    assert not floor_point_visible(at_bottom, [], FAR_REGION, SIZE)


def test_아래_변이_다른_bbox에_닿으면_바닥점이_안_보인다():
    other = (342, 150, 400, 250)  # 아래 변의 오른쪽 끝에서 2px 떨어져 있다
    assert not floor_point_visible(BOX, [other], FAR_REGION, SIZE)


def test_아래_변이_기준_영역에_닿으면_바닥점이_안_보인다():
    assert not floor_point_visible(BOX, [], _region(310, 202, 330, 260), SIZE)


def test_아래_변이_모두와_떨어져_있으면_바닥점이_보인다():
    other = (360, 150, 400, 250)  # 아래 변의 오른쪽 끝에서 20px 떨어져 있다
    assert floor_point_visible(BOX, [other], FAR_REGION, SIZE)


def test_가장_긴_연속은_빠진_칸에서_끊긴다():
    # 10fps: 4개 연속 → 한 칸 빠짐 → 5개 연속
    times = [1.0, 1.1, 1.2, 1.3, 1.5, 1.6, 1.7, 1.8, 1.9]
    assert longest_run(times) == 5
