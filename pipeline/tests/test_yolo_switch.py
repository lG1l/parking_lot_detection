import pytest

from pipeline.candidates.channel_b import MOG2_STABLE_SEC
from pipeline.candidates.video import SAMPLING_FPS
from pipeline.candidates.yolo_switch import YOLO_AFTER_SEC, YOLO_BEFORE_SEC, YoloSwitch

# 06장 예시 표의 시각을 상수로 만든다. 지금 값으로는 100초, 112초, 117초, 122초다.
# 첫 움직임은 안정 시각과 거슬러 올라갈 시간보다 충분히 뒤에 둔다
MOTION_START = MOG2_STABLE_SEC + YOLO_BEFORE_SEC + 60
MOTION_END = MOTION_START + 12
OFF_AT = MOTION_END + YOLO_AFTER_SEC
# 꺼진 뒤 "거슬러 올라가는 시간"이 지나기 전에 다시 움직인다 (규칙 4)
SECOND_MOTION = OFF_AT + YOLO_BEFORE_SEC / 2


def _run(until_sec, is_motion):
    """0초부터 until_sec까지 분석 프레임을 넣고 (판정기, 시각별 판정)을 돌려준다."""
    switch = YoloSwitch()
    decisions = {}
    for index in range(round(until_sec * SAMPLING_FPS) + 1):
        time_sec = index / SAMPLING_FPS
        decisions[time_sec] = switch.step(time_sec, is_motion(time_sec))
    return switch, decisions


def _spans(switch):
    return [(r.start_sec, r.end_sec) for r in switch.ranges]


def _first_motion(time_sec):
    return MOTION_START <= time_sec <= MOTION_END


def test_움직임이_생기면_앞_시간만큼_거슬러_돌리고_뒤_시간이_지나면_끈다():
    switch, decisions = _run(OFF_AT + 3, _first_motion)

    # 규칙 1: 켜는 프레임에서만 거슬러 돌릴 프레임이 나오고, 감지 직전까지다
    backfill = decisions[MOTION_START].backfill_times
    assert backfill[0] == pytest.approx(MOTION_START - YOLO_BEFORE_SEC)
    assert backfill[-1] < MOTION_START
    assert len(backfill) == YOLO_BEFORE_SEC * SAMPLING_FPS
    # 규칙 3: 끌 시각의 프레임까지 돌리고 그다음 프레임부터 안 돌린다
    assert decisions[OFF_AT].run
    assert not decisions[OFF_AT + 1 / SAMPLING_FPS].run
    # 영상 시작 구간(규칙 8) 다음에 [90, 117]
    assert _spans(switch) == [
        (0, MOG2_STABLE_SEC),
        pytest.approx((MOTION_START - YOLO_BEFORE_SEC, OFF_AT)),
    ]


def test_꺼진_지_얼마_안_돼_다시_켜지면_돌린_프레임은_건너뛰고_구간을_잇는다():
    switch, decisions = _run(
        SECOND_MOTION + YOLO_AFTER_SEC + 3,
        lambda t: _first_motion(t) or t == SECOND_MOTION,
    )

    # 규칙 4: 117초까지는 이미 돌렸으므로 그 뒤 프레임만 거슬러 돌린다
    backfill = decisions[SECOND_MOTION].backfill_times
    assert backfill[0] == pytest.approx(OFF_AT + 1 / SAMPLING_FPS)
    assert all(t > OFF_AT for t in backfill)
    # 새 구간이 생기지 않고 앞 구간이 두 번째 움직임 + 뒤 시간까지 늘어난다
    assert len(switch.ranges) == 2
    assert _spans(switch)[1] == pytest.approx(
        (MOTION_START - YOLO_BEFORE_SEC, SECOND_MOTION + YOLO_AFTER_SEC)
    )


@pytest.mark.parametrize(
    ("motion_sec", "expected_end"),
    [
        (None, MOG2_STABLE_SEC),  # 움직임이 없으면 안정 시각에 끈다
        (MOG2_STABLE_SEC - 2, MOG2_STABLE_SEC - 2 + YOLO_AFTER_SEC),  # 끌 시각이 안정 시각을 넘는다
    ],
)
def test_영상_시작부터_안정_시각까지는_움직임이_없어도_켠다(motion_sec, expected_end):
    switch, decisions = _run(MOG2_STABLE_SEC + YOLO_AFTER_SEC + 3, lambda t: t == motion_sec)

    assert decisions[0].run
    assert decisions[0].backfill_times == []
    assert _spans(switch) == [(0, pytest.approx(expected_end))]


def test_켜진_채_영상이_끝나면_마지막_프레임_시각에_구간이_닫힌다():
    last_sec = MOTION_START + 1
    switch, _ = _run(last_sec, lambda t: t == MOTION_START)

    assert _spans(switch)[-1] == pytest.approx((MOTION_START - YOLO_BEFORE_SEC, last_sec))
