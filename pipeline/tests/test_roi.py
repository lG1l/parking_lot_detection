import cv2
import numpy as np

from pipeline.candidates.crop import analysis_crop, to_original, to_reduced
from pipeline.candidates.inputs import AnalysisInput
from pipeline.candidates.roi import (
    STRIP_OUT_M,
    _floor_strip,
    _lifts,
    _to_screen,
    build_roi,
    camera_side_edges,
    floor_points,
)


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
    return build_roi(data, frame, analysis_crop(data.vehicle_bbox, frame))


def _covered(roi, original):
    x, y = to_reduced(original, roi.crop)
    return roi.mask[round(y), round(x)] == 255


def test_건너편_변이_파손이면_지붕_위까지_덮지만_끝없이_높지는_않다():
    # bbox 세로 280 × 1.1 = 308을 가장 가까운 꼭짓점에서 올리고, 먼 꼭짓점은 덜 올린다. x=880 위 경계 ≈ 387
    roi = _roi([3])
    assert _covered(roi, (880, 400))  # 지붕(448)보다 48px 위
    assert not _covered(roi, (880, 250))


def test_카메라_쪽_옆면만_파손이면_차_높이만큼_올린다():
    # bbox 세로 280 × 1.0을 가장 가까운 꼭짓점에서 올린다. x=1123 위 경계 ≈ 454
    roi = _roi([1])
    assert _covered(roi, (1123, 470))
    assert not _covered(roi, (1123, 435))


def test_먼_꼭짓점은_원근만큼_덜_올린다():
    data = _input([1])
    floor_poly = _floor_strip(data)
    to_screen = cv2.getPerspectiveTransform(
        np.float32(floor_points(0)), np.float32(data.floor_corners)
    )
    screen_poly = _to_screen(floor_poly, to_screen)
    lifts = _lifts(floor_poly, screen_poly, to_screen, 280)
    # 꼭짓점 3 (1088,757)이 화면 가장 아래라 bbox 세로 그대로, 먼 끝 꼭짓점 1 (1284,636)은 덜 올린다
    assert np.isclose(lifts[3], 280)
    assert lifts[1] < lifts[3] * 0.85


def test_파손_변_1개는_양_옆으로_늘리지_않는다():
    data = _input([1])
    polygon = _floor_strip(data)
    a, b = floor_points(0)[1], floor_points(0)[2]
    assert np.allclose(polygon[0], a) and np.allclose(polygon[1], b)
    assert np.isclose(np.linalg.norm(polygon[3] - polygon[0]), STRIP_OUT_M)


def test_파손_변_2개는_만나는_모서리에서_2_3까지만_쓰고_바깥_꼭짓점을_잇는다():
    data = _input([0, 1])
    polygon = _floor_strip(data)
    floor = np.array(floor_points(0))
    corner = floor[1]  # 변 0의 끝 = 변 1의 시작
    assert np.allclose(polygon[1], corner)
    assert np.allclose(polygon[0], corner + (floor[0] - corner) * 2 / 3)
    assert np.allclose(polygon[2], corner + (floor[2] - corner) * 2 / 3)
    # 바깥 꼭짓점은 모서리에서 두 바깥 방향으로 0.8m씩
    assert any(np.allclose(p, corner + [STRIP_OUT_M, -STRIP_OUT_M]) for p in polygon)


def test_파손_사각형_주변은_ROI에_들어간다():
    roi = _roi([1])
    # 파손 사각형 (732,583)-(850,638)을 자기 폭 118의 0.5배 넓힌 왼쪽 끝 근처
    assert _covered(roi, (680, 610))


def test_보여줄_크롭은_ROI를_담고_분석_크롭은_보여줄_크롭을_담는다():
    roi = _roi([0, 1])
    ax1, ay1, ax2, ay2 = roi.crop.rect
    dx1, dy1, dx2, dy2 = roi.display.rect
    assert ax1 <= dx1 and ay1 <= dy1 and dx2 <= ax2 and dy2 <= ay2
    ys, xs = np.nonzero(roi.mask)
    left, top = to_original((float(xs.min()), float(ys.min())), roi.crop)
    right, bottom = to_original((float(xs.max()), float(ys.max())), roi.crop)
    assert dx1 <= left and dy1 <= top and right <= dx2 and bottom <= dy2
