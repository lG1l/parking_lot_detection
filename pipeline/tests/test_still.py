"""정지 장면(9단계)의 중복 합치기·조각 잇기·탐지 목록 만들기. 영상·모델 없이 10×10 마스크로 본다."""

import numpy as np

from pipeline.still import build_detections, hull_polygon, merge_duplicates, sort_left_to_right


def _vehicle(conf, rows, cols, bbox, cls="car"):
    """rows·cols는 (시작, 끝+1)이다. 그 칸만 참인 10×10 마스크를 가진 탐지 하나."""
    mask = np.zeros((10, 10), dtype=bool)
    mask[rows[0] : rows[1], cols[0] : cols[1]] = True
    return {"mask": mask, "bbox": bbox, "conf": conf, "cls": cls}


def _abc():
    a = _vehicle(0.9, (0, 10), (0, 6), [0.0, 0.0, 6.0, 10.0])  # 열 0~5 전체 (60칸)
    b = _vehicle(0.5, (0, 10), (2, 8), [2.0, 0.0, 8.0, 10.0])  # 열 2~7 전체. A와 IoU 0.5
    c = _vehicle(0.7, (0, 2), (8, 10), [6.0, 0.0, 10.0, 2.0], "truck")  # 박스만 A·B와 겹친다
    return a, b, c


def test_overlapping_masks_become_one_vehicle():
    a, b, _ = _abc()
    groups = merge_duplicates([b, a])
    assert len(groups) == 1
    assert groups[0]["conf"] == 0.9
    assert groups[0]["bbox"] == [0.0, 0.0, 8.0, 10.0]


def test_box_overlap_alone_does_not_merge():
    assert len(merge_duplicates(list(_abc()))) == 2


def test_two_mask_pieces_become_one_hull():
    mask = np.zeros((10, 10), dtype=bool)
    mask[2:6, 0:3] = True
    mask[2:6, 6:9] = True
    assert sorted(hull_polygon(mask)) == [[0, 2], [0, 5], [8, 2], [8, 5]]


def test_det_id_goes_left_to_right_with_four_keys():
    a, b, c = _abc()
    detections = build_detections(sort_left_to_right(merge_duplicates([c, b, a])))
    assert [(d["det_id"], d["bbox"][0]) for d in detections] == [(1, 0), (2, 6)]
    assert all(set(d) == {"det_id", "bbox", "conf", "polygon"} for d in detections)


def test_no_detection_gives_empty_list():
    assert build_detections(sort_left_to_right(merge_duplicates([]))) == []
