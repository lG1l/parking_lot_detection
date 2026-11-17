import dataclasses

import numpy as np

from pipeline.candidates.car_region import (
    build_car_spot,
    draw_region,
    pick_my_car,
    region_polygons,
)
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


def _rect_mask(x1, y1, x2, y2):
    mask = np.zeros((FRAME[1], FRAME[0]), bool)
    mask[y1:y2, x1:x2] = True
    return mask


# D-264 예시 표의 마스크 넷. 내 차 자리는 가로 172~488, 위 120, 아래 경계 약 250~270, 아래 여유 15픽셀이다
LEFT_PIECE = _rect_mask(200, 130, 260, 260)  # 자리 안 약 94%, 아래 경계보다 10픽셀쯤 내려감
RIGHT_PIECE = _rect_mask(300, 130, 440, 225)  # 자리 안 100%, 내려가지 않음
FRONT_CAR = _rect_mask(250, 200, 450, 310)  # 자리 안 약 55%, 40픽셀 넘게 내려감
NEXT_CAR = _rect_mask(470, 130, 640, 230)  # 자리 안 약 11%, 내려가지 않음


def test_내_차_자리에_선_마스크만_뽑아_하나로_합친다():
    spot = build_car_spot(DATA, FRAME, CROP)
    masks = np.stack([LEFT_PIECE, RIGHT_PIECE, FRONT_CAR, NEXT_CAR])

    picked = pick_my_car(masks, spot)

    assert np.array_equal(picked, LEFT_PIECE | RIGHT_PIECE)


def test_내_차_자리에_선_마스크가_없으면_찾지_못함이다():
    spot = build_car_spot(DATA, FRAME, CROP)
    assert pick_my_car(np.stack([FRONT_CAR, NEXT_CAR]), spot) is None
    assert pick_my_car(np.zeros((0, FRAME[1], FRAME[0]), bool), spot) is None


def test_자리_안_비율이_높아도_아래_여유보다_더_내려가면_내_차가_아니다():
    spot = build_car_spot(DATA, FRAME, CROP)
    # x=300~400의 아래 경계는 약 259~268. 자리 안 약 85%지만 아래로 20픽셀 넘게 내려간다
    tall = _rect_mask(300, 120, 400, 290)
    assert np.count_nonzero(tall & spot.mask) / np.count_nonzero(tall) >= 0.8
    assert pick_my_car(tall[None], spot) is None


def test_기준_영역은_조각마다_바깥_윤곽_다각형이고_다시_그리면_구멍이_채워진다():
    shape = (FRAME[1], FRAME[0])
    left = _rect_mask(200, 130, 260, 220)
    right = _rect_mask(300, 130, 440, 225)
    hole = _rect_mask(350, 160, 380, 190)
    region = (left | right) & ~hole

    polygons = region_polygons(region)
    redrawn = draw_region(polygons, shape)

    assert len(polygons) == 2
    assert all(
        isinstance(value, int) for polygon in polygons for point in polygon for value in point
    )
    assert np.array_equal(redrawn, left | right)
    # 한 번 더 바꿔도 같은 모양이다 (파일로 적었다 다시 그려도 달라지지 않는다)
    assert np.array_equal(draw_region(region_polygons(redrawn), shape), redrawn)


def test_빈_다각형_목록을_그리면_빈_그림이다():
    assert not draw_region([], (FRAME[1], FRAME[0])).any()
