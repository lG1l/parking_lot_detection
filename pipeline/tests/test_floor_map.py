import pytest

from pipeline.candidates.s4_filter.floor_map import (
    CAR_END_M,
    CAR_OUT_M,
    PERSON_END_M,
    PERSON_OUT_M,
    build_floor_map,
    distance_to_edge,
    in_strip,
    segment_in_strip,
    to_floor,
    to_screen,
)

# 바닥 1m가 화면 100px인 반듯한 직사각형. 변 0(위)이 앞쪽 변이라 가로가 폭 1.8m, 세로가 길이 4.7m다
PX_PER_M = 100
LEFT, TOP, RIGHT, BOTTOM = 100, 100, 280, 570
CORNERS = [(LEFT, TOP), (RIGHT, TOP), (RIGHT, BOTTOM), (LEFT, BOTTOM)]
SIDE_EDGE = 1  # 오른쪽 옆 변 (길이 4.7m). 바깥은 화면 오른쪽이다


def _floor(point):
    return to_floor(build_floor_map(CORNERS, 0), point)


def test_화면_가운데_점은_바닥_직사각형의_가운데다():
    assert _floor(((LEFT + RIGHT) / 2, (TOP + BOTTOM) / 2)) == pytest.approx((0.9, 2.35))


def test_옆_변에서_바깥으로_80px_떨어진_점의_거리는_0_8m다():
    floor_map = build_floor_map(CORNERS, 0)
    point = _floor((RIGHT + 80, (TOP + BOTTOM) / 2))
    assert distance_to_edge(floor_map, point, SIDE_EDGE) == pytest.approx(0.8)


def test_바닥_위치를_화면으로_되돌리면_원래_점이다():
    floor_map = build_floor_map(CORNERS, 0)
    assert to_screen(floor_map, to_floor(floor_map, (333, 444))) == pytest.approx((333, 444))


def test_사람_띠는_바깥_0_8m와_양_끝_0_3m까지다():
    floor_map = build_floor_map(CORNERS, 0)

    def inside(x_px, y_px):
        return in_strip(floor_map, _floor((x_px, y_px)), SIDE_EDGE, PERSON_OUT_M, PERSON_END_M)

    middle_y = (TOP + BOTTOM) / 2
    assert inside(RIGHT + 0.5 * PX_PER_M, middle_y)  # 바깥 0.5m
    assert not inside(RIGHT + 0.9 * PX_PER_M, middle_y)  # 바깥 0.9m
    assert inside(RIGHT + 0.5 * PX_PER_M, BOTTOM + 0.2 * PX_PER_M)  # 변 끝에서 0.2m 더 나간 곳
    assert not inside(RIGHT + 0.5 * PX_PER_M, BOTTOM + 0.4 * PX_PER_M)  # 변 끝에서 0.4m 더 나간 곳
    assert not inside((LEFT + RIGHT) / 2, middle_y)  # 내 차 바닥 위


def test_차_띠는_아래_변의_한쪽_끝만_걸쳐도_안이다():
    floor_map = build_floor_map(CORNERS, 0)
    middle_y = (TOP + BOTTOM) / 2
    inside_end = _floor((RIGHT + (CAR_OUT_M - 0.1) * PX_PER_M, middle_y))
    outside_end = _floor((RIGHT + (CAR_OUT_M + 3) * PX_PER_M, middle_y))
    far_end = _floor((RIGHT + (CAR_OUT_M + 1) * PX_PER_M, middle_y))

    assert segment_in_strip(floor_map, inside_end, outside_end, SIDE_EDGE, CAR_OUT_M, CAR_END_M)
    assert not segment_in_strip(floor_map, far_end, outside_end, SIDE_EDGE, CAR_OUT_M, CAR_END_M)
