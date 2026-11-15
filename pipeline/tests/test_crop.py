import pytest

from pipeline.candidates.crop import (
    CropError,
    analysis_crop,
    expand_to_contain,
    to_original,
    to_reduced,
)

FRAME = (1920, 1080)


def test_가운데_차는_중심이_bbox_중심이고_16대9다():
    # bbox 폭 300 → 크롭 폭 600, 높이 337.5를 올려 338
    crop = analysis_crop((810, 440, 1110, 620), FRAME)
    assert (crop.width, crop.height) == (600, 338)
    assert crop.rect[0] + crop.width / 2 == 960  # bbox 중심 x
    assert crop.rect[1] + crop.height / 2 == 530  # bbox 중심 y


def test_구석의_차는_크기를_유지한_채_안쪽으로_밀린다():
    crop = analysis_crop((10, 10, 110, 90), FRAME)
    assert (crop.width, crop.height) == (200, 113)
    assert crop.rect[:2] == (0, 0)


def test_원본보다_큰_크롭은_멈춘다():
    # 폭 700짜리 차 → 크롭 1400은 1280 화면보다 크다
    with pytest.raises(CropError):
        analysis_crop((100, 100, 800, 500), (1280, 720))


def test_원본_점이_줄인_프레임을_거쳐_돌아온다():
    # 폭 640짜리 차 → 크롭 1280×720 → 640×360
    crop = analysis_crop((640, 300, 1280, 700), FRAME)
    assert (crop.width, crop.height) == (1280, 720)
    assert crop.reduced_size == (640, 360)
    p = (900.0, 500.0)
    back = to_original(to_reduced(p, crop), crop)
    assert abs(back[0] - p[0]) <= 1 and abs(back[1] - p[1]) <= 1


def test_roi가_크롭_밖으로_나가면_둘을_모두_담는_16대9로_넓힌다():
    crop = analysis_crop((810, 440, 1110, 620), FRAME)  # (660, 361, 1260, 699)
    region = (500, 500, 1000, 800)
    wide = expand_to_contain(crop, region, FRAME)
    x1, y1, x2, y2 = wide.rect
    assert x1 <= 500 and y1 <= 361 and x2 >= 1260 and y2 >= 800
    assert abs((x2 - x1) * 9 - (y2 - y1) * 16) <= 16  # 반올림 안의 16:9
