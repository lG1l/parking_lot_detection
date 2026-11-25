"""deidentify/detect.py의 박스 바꾸기·한 줄 만들기 테스트 (D-346). 영상·모델 없이 돈다."""

from pipeline.deidentify.detect import make_line, to_dets

# 보임_1변 입력의 분석 크롭 (원본 픽셀)
CROP = (470, 232, 1765, 960)


def _raw(category_id, score, box):
    return {"category_id": category_id, "score": score, "box": box}


def test_box_becomes_original_pixels_rounded_outward():
    dets = to_dets([_raw(0, 0.5, [10.4, 20.6, 50.2, 60.1])], CROP)
    assert dets == [{"cls": "face", "bbox": [480, 252, 521, 293], "conf": 0.5}]


def test_threshold_differs_by_class():
    box = [10, 10, 30, 30]
    raw = [_raw(0, 0.19, box), _raw(0, 0.20, box), _raw(1, 0.09, box), _raw(1, 0.10, box)]
    dets = to_dets(raw, CROP)
    # 같은 자리여도 클래스가 다르면 합치지 않는다
    assert [(det["cls"], det["conf"]) for det in dets] == [("face", 0.2), ("plate", 0.1)]


def test_box_is_cut_at_crop_edge_and_dropped_when_outside():
    raw = [_raw(0, 0.5, [-5, -3, 2000, 900]), _raw(0, 0.5, [1300, 10, 1320, 30])]
    dets = to_dets(raw, CROP)
    assert [det["bbox"] for det in dets] == [[470, 232, 1765, 960]]


def test_line_without_boxes_has_empty_list():
    assert make_line(104.40834, []) == '{"t": 104.4083, "dets": []}'


def test_overlapping_boxes_of_same_class_become_one():
    # 첫째·둘째가 겹치고, 셋째는 둘째와만 겹친다 (이어서 하나가 된다). 넷째는 떨어져 있다
    raw = [
        _raw(0, 0.3, [10, 10, 30, 30]),
        _raw(0, 0.5, [25, 20, 45, 40]),
        _raw(0, 0.2, [40, 35, 60, 50]),
        _raw(0, 0.4, [200, 200, 220, 220]),
    ]
    dets = to_dets(raw, CROP)
    assert sorted((det["bbox"], det["conf"]) for det in dets) == [
        ([480, 242, 530, 282], 0.5),
        ([670, 432, 690, 452], 0.4),
    ]
