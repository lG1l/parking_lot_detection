import numpy as np

from pipeline.candidates.crop import analysis_crop, to_reduced
from pipeline.candidates.inputs import AnalysisInput
from pipeline.candidates.roi import build_roi, camera_side_edges


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


def test_건너편_변이_파손이면_차체와_지붕_위_여유까지_덮는다():
    data = _input([3])
    frame = (1920, 1080)
    roi = build_roi(data, frame, analysis_crop(data.vehicle_bbox, frame))
    crop, mask = roi.crop, roi.mask
    # 차체 한가운데와, bbox 높이(280)의 0.5배(140)만큼 위인 지붕 위 선 바로 아래
    for original in [(988, 588), (988, 448 - 138)]:
        x, y = to_reduced(original, crop)
        assert mask[round(y), round(x)] == 255


def test_카메라_쪽_옆면만_파손이면_지붕_위_여유는_덮지_않는다():
    data = _input([1])
    frame = (1920, 1080)
    roi = build_roi(data, frame, analysis_crop(data.vehicle_bbox, frame))
    crop, mask = roi.crop, roi.mask
    x, y = to_reduced((1100, 448 - 100), crop)  # 차량 bbox 위 변보다 100px 위
    assert mask[round(y), round(x)] == 0


def test_바닥띠는_파손_변마다_하나_기록되고_보여줄_크롭은_ROI를_담는다():
    frame = (1920, 1080)
    data = _input([0, 1])
    roi = build_roi(data, frame, analysis_crop(data.vehicle_bbox, frame))
    assert len(roi.strips) == 2
    ax1, ay1, ax2, ay2 = roi.crop.rect
    dx1, dy1, dx2, dy2 = roi.display.rect
    assert ax1 <= dx1 and ay1 <= dy1 and dx2 <= ax2 and dy2 <= ay2  # 보여줄 ⊂ 분석
    ys, xs = np.nonzero(roi.mask)
    # ROI(줄인 프레임)를 원본 좌표로 바꿔도 보여줄 크롭 안이어야 한다
    sx, sy = roi.crop.reduced_size[0] / roi.crop.width, roi.crop.reduced_size[1] / roi.crop.height
    assert dx1 <= ax1 + xs.min() / sx + 2 and ax1 + xs.max() / sx - 2 <= dx2
    assert dy1 <= ay1 + ys.min() / sy + 2 and ay1 + ys.max() / sy - 2 <= dy2
