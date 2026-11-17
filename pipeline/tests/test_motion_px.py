import numpy as np
import pytest

from pipeline.candidates.channel_b import Blob
from pipeline.candidates.motion_px import (
    BBOX_GROW_RATIO,
    MOTION_DIFF_MIN,
    blobs_moved_mask,
    changed_pixels,
    grow_bbox,
    moved_in_bbox,
    moved_in_blob,
)

SIZE = 8


def _left_half_blob() -> Blob:
    """8×8 그림의 왼쪽 반(4열)을 다 채운 덩어리."""
    mask = np.ones((SIZE, SIZE // 2), bool)
    return Blob(int(mask.sum()), np.zeros((0, 1, 2), np.int32), True, (0, 0, SIZE // 2, SIZE), mask)


def _changed(diff: int) -> np.ndarray:
    """가운데 4×4만 밝기를 diff만큼 바꾼 두 프레임의 달라진 픽셀 그림."""
    prev_gray = np.full((SIZE, SIZE), 100, np.uint8)
    gray = prev_gray.copy()
    gray[2:6, 2:6] += diff
    return changed_pixels(prev_gray, gray)


def _top_six_rows() -> np.ndarray:
    roi_in = np.zeros((SIZE, SIZE), bool)
    roi_in[:6] = True
    return roi_in


# 덩어리(왼쪽 4열) ∩ 달라진 칸(2~5행, 2~5열) ∩ ROI(위 6줄) = 2~5행의 2~3열 = 4 × 2 = 8칸
@pytest.mark.parametrize(
    ("diff", "expected"),
    [
        (MOTION_DIFF_MIN, 8),  # 딱 기준만큼 달라졌다 → 센다
        (MOTION_DIFF_MIN - 1, 0),  # 기준보다 1 작다 → 세지 않는다
    ],
)
def test_moved_in_blob(diff, expected):
    assert moved_in_blob(_left_half_blob(), _changed(diff), _top_six_rows()) == expected


def test_moved_in_bbox_of_blobs():
    """넘긴 덩어리의 움직인 픽셀을 트랙 bbox로 잘라 센다. bbox 밖(2열)은 빠진다."""
    moved = blobs_moved_mask([_left_half_blob()], _changed(MOTION_DIFF_MIN), _top_six_rows())
    assert moved_in_bbox((3.0, 0.0, 8.0, 8.0), moved) == 4


def test_grow_bbox():
    """폭 20·높이 10인 bbox는 좌우로 2, 위아래로 1씩 넓어진다."""
    assert BBOX_GROW_RATIO == 0.1
    assert grow_bbox((10.0, 10.0, 30.0, 20.0)) == (8.0, 9.0, 32.0, 21.0)
