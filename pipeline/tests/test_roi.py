import cv2
import numpy as np

from pipeline.candidates.crop import analysis_crop, to_original, to_reduced
from pipeline.candidates.inputs import AnalysisInput
from pipeline.candidates.roi import (
    END_FLARE_DEG,
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


def _to_screen_matrix(data):
    return cv2.getPerspectiveTransform(np.float32(floor_points(0)), np.float32(data.floor_corners))


def _covered(roi, original):
    x, y = to_reduced(original, roi.crop)
    return roi.mask[round(y), round(x)] == 255


def test_건너편_변이_파손이면_지붕_위까지_덮지만_끝없이_높지는_않다():
    # bbox 세로 280 × 1.1 = 308을 가장 낮은 꼭짓점에서 올리고, 먼 꼭짓점은 덜 올린다. x=880 위 경계 ≈ 359
    roi = _roi([3])
    assert _covered(roi, (880, 400))  # 지붕(448)보다 48px 위
    assert not _covered(roi, (880, 250))


def test_카메라_쪽_옆면만_파손이면_차_높이만큼_올린다():
    # 띠의 가장 낮은 꼭짓점 (789,864)을 bbox 세로 280만큼 올린다. 위 경계: x=962 ≈ 502, x=1123 ≈ 458
    roi = _roi([1])
    assert _covered(roi, (962, 510))
    assert not _covered(roi, (962, 495))
    assert _covered(roi, (1123, 465))
    assert not _covered(roi, (1123, 450))


def test_가장_낮은_꼭짓점은_정확히_bbox_세로만큼_올린다():
    data = _input([1])
    to_screen = _to_screen_matrix(data)
    floor_poly = _floor_strip(data, to_screen)
    lowest = int(np.argmax(_to_screen(floor_poly, to_screen)[:, 1]))
    lifts = _lifts(floor_poly, to_screen, floor_poly[lowest], 280)
    assert np.isclose(lifts[lowest], 280)
    assert lifts.max() <= 280 + 1e-6  # 가장 낮은 꼭짓점이 카메라에 가장 가깝다


def test_먼_꼭짓점은_덜_올려_위_경계가_실제로_바닥_변과_평행하다():
    data = _input([1])
    to_screen = _to_screen_matrix(data)
    near, far = np.array(floor_points(0)[1]), np.array(floor_points(0)[2])
    on_edge = np.array([near, (near + far) / 2, far])
    lifts = _lifts(on_edge, to_screen, near, 280)
    assert lifts[2] < lifts[1] < lifts[0]
    # 실제로 같은 높이로 올린 직선 위 세 점은 화면에서도 한 직선 위에 있다
    tops = _to_screen(on_edge, to_screen) - np.c_[np.zeros(3), lifts]
    (ax, ay), (bx, by) = tops[1] - tops[0], tops[2] - tops[0]
    assert abs(ax * by - ay * bx) < 1e-3 * np.hypot(bx, by) ** 2


def test_파손_변_1개는_양_끝이_바깥으로_벌어진다():
    data = _input([1])
    polygon = _floor_strip(data, _to_screen_matrix(data))
    b = np.array(floor_points(0)[2])
    # 차에 붙은 선의 먼 끝은 그대로, 바깥 끝은 변 방향으로 0.8 × tan30° 더 나간다
    flare = STRIP_OUT_M * np.tan(np.radians(END_FLARE_DEG))
    assert np.allclose(polygon[1], b)
    assert np.allclose(polygon[2], b + [STRIP_OUT_M, flare])
    assert np.allclose(polygon[3], polygon[0] + [STRIP_OUT_M, -flare])


def test_파손_변이_파손_사각형에_못_미치면_변을_그만큼_늘린다():
    data = _input([1])
    to_screen = _to_screen_matrix(data)
    polygon = _floor_strip(data, to_screen)
    # 파손 사각형 왼쪽 732 - 폭 118 × 1/6 = 712.3. 변 1의 가까운 끝(962,746)을 변 방향으로 늘린다
    assert np.isclose(polygon[0][0], floor_points(0)[1][0])  # 변 1 직선 위
    assert np.isclose(_to_screen(polygon[:1], to_screen)[0][0], 712.3, atol=0.1)


def test_파손_변_2개는_만나는_모서리에서_2_3까지만_쓰고_바깥_꼭짓점을_잇는다():
    data = _input([0, 1])
    polygon = _floor_strip(data, _to_screen_matrix(data))
    floor = np.array(floor_points(0))
    corner = floor[1]  # 변 0의 끝 = 변 1의 시작
    assert np.allclose(polygon[1], corner)
    assert np.allclose(polygon[2], corner + (floor[2] - corner) * 2 / 3)
    # 바깥 꼭짓점은 모서리에서 두 바깥 방향으로 0.8m씩
    assert any(np.allclose(p, corner + [STRIP_OUT_M, -STRIP_OUT_M]) for p in polygon)
    # 만나지 않는 끝은 벌어진다: 변 1의 2/3 끝 바깥은 변 방향(+y)으로 더 나간다
    flare = STRIP_OUT_M * np.tan(np.radians(END_FLARE_DEG))
    assert np.allclose(polygon[3], polygon[2] + [STRIP_OUT_M, flare])


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
