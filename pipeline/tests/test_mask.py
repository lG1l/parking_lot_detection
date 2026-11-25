"""8-다 가리기 (D-347). 영상·모델 없이 돈다."""

import numpy as np

from pipeline.deidentify.mask import blur_box, blur_sigma, boxes_at, load_boxes, to_display_box

# 보여줄 크롭 (1차_보임_1변, 짝수로 맞춘 값). 크기 924×520
DISPLAY = (655, 336, 1579, 856)


def test_box_moves_to_display_coordinates():
    assert to_display_box([700, 400, 760, 430], DISPLAY) == [45, 64, 105, 94]


def test_box_is_cut_to_display_or_dropped():
    # 왼쪽 위에 걸친 박스는 크롭 안쪽만 남는다
    assert to_display_box([640, 330, 670, 350], DISPLAY) == [0, 0, 15, 14]
    # 크롭 밖에만 있는 박스
    assert to_display_box([600, 300, 650, 330], DISPLAY) is None
    # 경계에 닿기만 한 박스 (넓이가 없다)
    assert to_display_box([600, 400, 655, 430], DISPLAY) is None


def test_sigma_is_half_of_short_side_before_cut():
    assert blur_sigma([100, 100, 162, 120]) == 10.0  # 62×20
    assert blur_sigma([100, 100, 109, 110]) == 4.5  # 9×10
    # 걸친 박스도 자르기 전 높이 20으로 잰다
    assert blur_sigma([640, 330, 670, 350]) == 10.0


def test_blur_changes_only_inside_box():
    # 0과 255가 한 열씩 번갈아 나오는 줄무늬
    image = np.zeros((40, 40, 3), dtype=np.uint8)
    image[:, 1::2] = 255
    before = image.copy()

    blur_box(image, [10, 10, 30, 30], 10.0)

    inside = np.zeros((40, 40), dtype=bool)
    inside[10:30, 10:30] = True
    assert np.array_equal(image[~inside], before[~inside])
    assert image[inside].min() > 0
    assert image[inside].max() < 255


def test_boxes_are_found_by_rounded_time(tmp_path):
    path = tmp_path / "deid_boxes.jsonl"
    det = {"cls": "face", "bbox": [1012, 455, 1031, 478], "conf": 0.412}
    path.write_text(
        '{"t": 104.4083, "dets": [{"cls": "face", "bbox": [1012, 455, 1031, 478], "conf": 0.412}]}\n'
        '{"t": 104.4418, "dets": []}\n'
    )
    table = load_boxes(str(path))

    assert boxes_at(table, 104.40834) == [det]
    assert boxes_at(table, 104.44181) == []
