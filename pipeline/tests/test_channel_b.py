import numpy as np
import pytest

from pipeline.candidates.channel_b import (
    FrameRecord,
    MotionRange,
    clean_foreground,
    find_blobs,
    has_roi_motion,
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
