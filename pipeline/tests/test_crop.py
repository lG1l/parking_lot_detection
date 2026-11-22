import numpy as np
import pytest

from pipeline.candidates.s1_base.crop import (
    Crop,
    CropError,
    analysis_crop,
    crop_frame,
    to_original,
    to_reduced,
)

FRAME = (1920, 1080)


def _display(rect):
    return Crop(rect, (rect[2] - rect[0], rect[3] - rect[1]))


def test_가운데_보여줄_크롭은_중심이_같고_1점4배_16대9다():
    # 보여줄 폭 800 → 분석 폭 1120, 높이 630
    crop = analysis_crop(_display((560, 315, 1360, 765)), FRAME)
    assert (crop.width, crop.height) == (1120, 630)
    assert crop.rect[0] + crop.width / 2 == 960
    assert crop.rect[1] + crop.height / 2 == 540


def test_구석의_보여줄_크롭은_분석_크롭이_안쪽으로_밀려도_담긴다():
    display = (0, 0, 400, 225)
    crop = analysis_crop(_display(display), FRAME)
    assert (crop.width, crop.height) == (560, 315)
    assert crop.rect[:2] == (0, 0)
    x1, y1, x2, y2 = crop.rect
    assert x1 <= display[0] and y1 <= display[1] and x2 >= display[2] and y2 >= display[3]


def test_원본보다_큰_크롭은_멈춘다():
    # 보여줄 폭 1000 → 분석 폭 1400은 1280 화면보다 크다
    with pytest.raises(CropError):
        analysis_crop(_display((140, 79, 1140, 641)), (1280, 720))


def test_원본_점이_줄인_프레임을_거쳐_돌아온다():
    # 분석 크롭 1280×720 → 640×360
    crop = Crop((320, 180, 1600, 900), (640, 360))
    assert crop.reduced_size == (640, 360)
    p = (900.0, 500.0)
    back = to_original(to_reduced(p, crop), crop)
    assert abs(back[0] - p[0]) <= 1 and abs(back[1] - p[1]) <= 1


def test_프레임을_잘라_줄이면_크롭의_줄인_크기가_된다():
    # 1280×720 크롭은 긴 변이 640보다 커서 640×360으로 줄인다
    image = np.zeros((1080, 1920, 3), np.uint8)
    crop = Crop((100, 50, 1380, 770), (640, 360))
    assert crop_frame(image, crop).shape == (360, 640, 3)
