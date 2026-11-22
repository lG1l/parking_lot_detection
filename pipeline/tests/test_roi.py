import dataclasses

import numpy as np
import pytest

from pipeline.candidates.s1_base.crop import to_original, to_reduced
from pipeline.candidates.s1_base.inputs import AnalysisInput
from pipeline.candidates.s1_base.roi import (
    CAR_LENGTH_M,
    CAR_WIDTH_M,
    END_FLARE_DEG,
    LIFT_RATIO,
    STRIP_OUT_M,
    TWO_EDGE_KEEP_RATIO,
    RoiError,
    _floor_strip,
    _out_at,
    build_roi,
    camera_side_edges,
)

CORNERS = np.array([(728, 726), (962, 746), (1284, 636), (1032, 630)], dtype=float)
# 가장 먼 모서리 y 630 ~ bbox 위 변 448 = 화면 속 차체 높이 182
LIFT = round((630 - 448) * LIFT_RATIO)
# 바깥 끝이 변 방향으로 더 나가는 거리 (m)
FLARE_M = STRIP_OUT_M * np.tan(np.radians(END_FLARE_DEG))


def test_위가_좁고_아래가_넓은_사다리꼴은_아래_변만_카메라_쪽이다():
    # 변 0: 위, 변 1: 오른쪽, 변 2: 아래, 변 3: 왼쪽
    corners = [(200, 100), (400, 100), (500, 300), (100, 300)]
    assert camera_side_edges(corners) == [2]


def _input(damage_edges):
    return AnalysisInput(
        vehicle_bbox=(715, 448, 1261, 728),
        visible=False,
        damage_bbox=(732, 583, 850, 638),
        floor_corners=[(728, 726), (962, 746), (1284, 636), (1032, 630)],
        front_edge=0,
        damage_edges=damage_edges,
    )


def _roi(damage_edges):
    data = _input(damage_edges)
    frame = (1920, 1080)
    return build_roi(data, frame)


def _covered(roi, original):
    x, y = to_reduced(original, roi.crop)
    return roi.mask[round(y), round(x)] == 255


def test_건너편_변이_파손이면_지붕_위까지_덮지만_끝없이_높지는_않다():
    # 띠 바깥 선이 x=880에서 y≈639. 차체 높이 182 × 1.3 = 237만큼 올리면 위 경계 ≈ 402
    roi = _roi([3])
    assert _covered(roi, (880, 420))  # 지붕(448)보다 28px 위
    assert not _covered(roi, (880, 380))


def test_위_경계는_파손_변을_차체_높이의_1_3배만큼_그대로_올린_선이다():
    # 카메라 쪽 변 1이 파손이면 위 경계가 찍은 변 1과 화면에서 평행하다
    roi = _roi([1])
    a, b = CORNERS[1], CORNERS[2]
    for x in (1000, 1200):
        top = a[1] + (b[1] - a[1]) * (x - a[0]) / (b[0] - a[0]) - LIFT
        assert _covered(roi, (x, top + 10))
        assert not _covered(roi, (x, top - 10))


def test_띠_폭은_이웃_변을_자로_써서_잰다():
    # 변 1의 끝(모서리 2)에서 바깥은 뒤 변(3→2)을 이어 간 방향이고, 뒤 변 전체가 CAR_WIDTH_M이다
    out = _out_at(CORNERS, 1, 1.0, 0)
    assert np.allclose(out, (CORNERS[2] - CORNERS[3]) * STRIP_OUT_M / CAR_WIDTH_M)
    out = _out_at(CORNERS, 1, 0.0, 0)
    assert np.allclose(out, (CORNERS[1] - CORNERS[0]) * STRIP_OUT_M / CAR_WIDTH_M)


def test_모서리가_조금_어긋나도_띠_폭이_부풀지_않는다():
    # 중간_높 사진 입력: 앞 변 402px, 뒤 변 369px. 네 모서리로 바닥을 펴면 변 1 바깥이 250px까지 부풀었다
    corners = np.array([(1669, 1853), (2069, 1894), (2344, 1702), (1975, 1702)], dtype=float)
    longest = max(np.hypot(*(corners[1] - corners[0])), np.hypot(*(corners[2] - corners[3])))
    for t in (0.0, 0.5, 1.0):
        width = np.hypot(*_out_at(corners, 1, t, 0))
        assert width <= longest * STRIP_OUT_M / CAR_WIDTH_M + 1e-6


def test_파손_변_1개는_양_끝이_바깥으로_벌어진다():
    polygon = _floor_strip(_input([1]))
    along_1m = (CORNERS[2] - CORNERS[1]) / CAR_LENGTH_M
    # 차에 붙은 선의 먼 끝은 그대로, 바깥 끝은 변 방향으로 0.8 × tan15° 더 나간다
    assert np.allclose(polygon[1], CORNERS[2])
    assert np.allclose(polygon[2], CORNERS[2] + _out_at(CORNERS, 1, 1.0, 0) + FLARE_M * along_1m)
    assert np.allclose(polygon[3], polygon[0] + _out_at(CORNERS, 1, 0.0, 0) - FLARE_M * along_1m)


def test_파손_변이_파손_사각형에_못_미치면_변을_그만큼_늘린다():
    polygon = _floor_strip(_input([1]))
    # 파손 사각형 왼쪽 732 - 폭 118 × 1/6 = 712.3. 변 1의 가까운 끝(962,746)을 변 방향으로 늘린다
    assert np.isclose(polygon[0][0], 712.3, atol=0.1)
    (ax, ay), (bx, by) = polygon[0] - CORNERS[1], CORNERS[2] - CORNERS[1]
    assert abs(ax * by - ay * bx) < 1e-6  # 변 1 직선 위


def test_파손_변_2개는_만나는_모서리에서_절반까지만_쓰고_바깥_꼭짓점을_잇는다():
    polygon = _floor_strip(_input([0, 1]))
    corner = CORNERS[1]  # 변 0의 끝 = 변 1의 시작
    assert np.allclose(polygon[1], corner)
    assert np.allclose(polygon[2], corner + (CORNERS[2] - corner) * TWO_EDGE_KEEP_RATIO)
    # 바깥 꼭짓점은 모서리에서 두 변을 각각 이어 간 방향으로 0.8m씩
    out = (corner - CORNERS[0]) / CAR_WIDTH_M + (corner - CORNERS[2]) / CAR_LENGTH_M
    assert np.allclose(polygon[4], corner + STRIP_OUT_M * out)
    # 만나지 않는 끝은 벌어진다: 변 1의 절반 끝 바깥은 변 방향으로 더 나간다
    along_1m = (CORNERS[2] - corner) / CAR_LENGTH_M
    assert np.allclose(
        polygon[3], polygon[2] + _out_at(CORNERS, 1, TWO_EDGE_KEEP_RATIO, 0) + FLARE_M * along_1m
    )


def test_파손_사각형_좌우_여백은_자기_폭의_6분의_1이다():
    roi = _roi([1])
    # 왼쪽 끝 732 - 118/6 ≈ 712
    assert _covered(roi, (716, 610))
    assert not _covered(roi, (700, 610))


def test_보여줄_크롭은_ROI를_담고_분석_크롭은_보여줄_크롭을_담는다():
    roi = _roi([0, 1])
    ax1, ay1, ax2, ay2 = roi.crop.rect
    dx1, dy1, dx2, dy2 = roi.display.rect
    assert ax1 <= dx1 and ay1 <= dy1 and dx2 <= ax2 and dy2 <= ay2
    ys, xs = np.nonzero(roi.mask)
    left, top = to_original((float(xs.min()), float(ys.min())), roi.crop)
    right, bottom = to_original((float(xs.max()), float(ys.max())), roi.crop)
    assert dx1 <= left and dy1 <= top and right <= dx2 and bottom <= dy2


def test_바닥_모서리가_차량_사각형_위_변보다_위면_멈춘다():
    # 가장 먼 모서리 y 630보다 bbox 위 변이 아래(650)면 차체 높이가 음수가 된다
    data = dataclasses.replace(_input([1]), vehicle_bbox=(715, 650, 1261, 728))
    with pytest.raises(RoiError):
        build_roi(data, (1920, 1080))
