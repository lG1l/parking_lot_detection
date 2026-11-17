import dataclasses

import numpy as np

from pipeline.candidates.car_region import build_car_spot
from pipeline.candidates.crop import Crop
from pipeline.candidates.inputs import AnalysisInput

# D-264 예시 숫자. 줄이지 않는 크롭이라 원본 좌표 = 줄인 프레임 좌표다
FRAME = (640, 360)
CROP = Crop((0, 0, 640, 360), FRAME)
DATA = AnalysisInput(
    vehicle_bbox=(190, 120, 470, 270),  # 위 변 120, 폭 280, 높이 150
    visible=True,
    damage_bbox=(300, 200, 340, 230),
    floor_corners=[(200, 250), (420, 270), (460, 230), (250, 215)],
    front_edge=0,
    damage_edges=[0],
)


def test_내_차_자리는_아래_경계에서_bbox_위_변까지_채우고_좌우로_넓힌다():
    spot = build_car_spot(DATA, FRAME, CROP)
    columns = np.nonzero(spot.mask.any(axis=0))[0]
    # 사각형 가로 200~460에 좌우 여유 28(폭 280의 10%)을 더한다
    assert (columns.min(), columns.max()) == (172, 488)

    # x=300 줄: 위는 bbox 위 변 120, 아래는 변 (200,250)→(420,270) 위의 y≈259
    rows = np.nonzero(spot.mask[:, 300])[0]
    assert rows.min() == 120
    assert 258 <= rows.max() <= 260
    assert len(rows) == rows.max() - rows.min() + 1  # 사이에 빈 칸이 없다


def test_bbox_위_변이_네_모서리보다_아래면_내_차_자리를_만들지_않는다():
    data = dataclasses.replace(DATA, vehicle_bbox=(190, 300, 470, 350))
    assert build_car_spot(data, FRAME, CROP) is None
