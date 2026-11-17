import numpy as np
import pytest

from pipeline.candidates.channel_b import (
    BLOB_MAX_AREA_RATIO,
    FrameRecord,
    MotionRange,
    boxes_for_tracker,
    clean_foreground,
    find_blobs,
    group_blobs,
    has_roi_motion,
    join_gap_px,
    merge_motion_ranges,
)

# 줄인 프레임 640×360. 노이즈 기준은 640×360×0.0001 ≈ 23픽셀
SHAPE = (360, 640)
EMPTY_ROI = np.zeros(SHAPE, np.uint8)


def _mask_with(*squares, value=255):
    """(x, y, 한 변) 정사각형들을 value로 칠한 MOG2 마스크."""
    mask = np.zeros(SHAPE, np.uint8)
    for x, y, size in squares:
        mask[y : y + size, x : x + size] = value
    return mask


def test_노이즈_기준보다_작은_덩어리는_버린다():
    # 20×20=400픽셀은 남고, 4×4=16픽셀은 열기(3×3)는 견디지만 23픽셀 미만이라 버린다
    binary = clean_foreground(_mask_with((100, 100, 20), (300, 200, 4)))
    blobs = find_blobs(binary, EMPTY_ROI)
    assert [b.area for b in blobs] == [400]


def test_그림자만_있으면_덩어리가_없다():
    binary = clean_foreground(_mask_with((100, 100, 50), value=127))
    assert find_blobs(binary, EMPTY_ROI) == []


def test_ROI와_겹치는_덩어리가_있으면_움직임이_있다():
    binary = clean_foreground(_mask_with((100, 100, 20), (400, 200, 20)))
    roi = np.zeros(SHAPE, np.uint8)
    roi[210:260, 410:460] = 255  # 두 번째 덩어리와만 겹친다
    blobs = find_blobs(binary, roi)
    assert [b.touches_roi for b in blobs] == [False, True]
    assert has_roi_motion(blobs)


def test_아무것도_ROI와_겹치지_않으면_움직임이_없다():
    binary = clean_foreground(_mask_with((100, 100, 20), (400, 200, 20)))
    roi = np.zeros(SHAPE, np.uint8)
    roi[300:350, 550:600] = 255
    assert not has_roi_motion(find_blobs(binary, roi))


def _records(motion_times, all_times):
    """all_times 중 motion_times에만 ROI 움직임이 있는 프레임 기록."""
    return [FrameRecord(t, t in motion_times, []) for t in all_times]


# Task.md 7장 "이어 붙이기 예시" (끊김 간격 1초). 움직임 없는 프레임도 섞어 넣는다
@pytest.mark.parametrize(
    ("motion", "expected"),
    [
        ([4.0, 4.1, 4.2], [MotionRange(4.0, 4.2, 3)]),
        ([4.0, 4.1, 4.9, 5.0], [MotionRange(4.0, 5.0, 4)]),
        ([4.0, 4.1, 5.5, 5.6], [MotionRange(4.0, 4.1, 2), MotionRange(5.5, 5.6, 2)]),
        ([8.0], [MotionRange(8.0, 8.0, 1)]),
        ([], []),
    ],
)
def test_움직임_프레임을_끊김_간격으로_이어_붙인다(motion, expected):
    all_times = sorted({round(t / 10, 1) for t in range(30, 95)} | set(motion))
    assert merge_motion_ranges(_records(motion, all_times)) == expected


def _roi_over(x, y, size):
    """(x, y)에서 시작하는 정사각형만 덮는 ROI 마스크."""
    roi = np.zeros(SHAPE, np.uint8)
    roi[y : y + size, x : x + size] = 255
    return roi


# D-315 예시 표. 왼쪽 정사각형만 ROI에 닿고, 오른쪽 정사각형까지의 간격만 바꾼다
@pytest.mark.parametrize(
    ("gap", "expected_groups", "right_edge"),
    [
        (
            join_gap_px(SHAPE),
            1,
            120 + join_gap_px(SHAPE) + 20,
        ),  # 가깝다: 묶음 하나, 둘을 감싼 사각형
        (join_gap_px(SHAPE) * 10, 2, 120),  # 멀다: 묶음 둘, ROI에 닿은 쪽 사각형만
    ],
)
def test_가까운_덩어리는_한_묶음이고_먼_덩어리는_따로다(gap, expected_groups, right_edge):
    binary = clean_foreground(_mask_with((100, 100, 20), (120 + gap, 100, 20)))
    blobs = find_blobs(binary, _roi_over(100, 100, 20))

    groups = group_blobs(blobs, SHAPE)

    assert len(groups) == expected_groups
    assert boxes_for_tracker(blobs, groups, set(), SHAPE) == [(100, 100, right_edge, 120)]


def test_상한_이상인_덩어리가_든_묶음은_넣지_않는다():
    # 큰 덩어리는 상한(줄인 프레임 넓이의 30%)을 넘는 정사각형, 작은 덩어리는 멀리 떨어진 20×20
    big = int((SHAPE[0] * SHAPE[1] * BLOB_MAX_AREA_RATIO) ** 0.5) + 1
    binary = clean_foreground(_mask_with((0, 0, big), (600, 300, 20)))
    roi = _roi_over(0, 0, 10) | _roi_over(600, 300, 20)
    blobs = find_blobs(binary, roi)
    assert [b.touches_roi for b in blobs] == [True, True]

    boxes = boxes_for_tracker(blobs, group_blobs(blobs, SHAPE), set(), SHAPE)

    assert boxes == [(600, 300, 620, 320)]
