"""트랙마다 움직인 픽셀 수(moved_px)를 센다 (06장 6.5 "후보 구간의 규칙", D-254, D-262, D-333).

움직인 픽셀 = 직전 분석 프레임(0.1초 전)과 밝기가 기준 이상 달라진 픽셀이다.
어느 범위에서 세는지만 트랙 종류와 프레임 상황에 따라 다르다. 좌표는 모두 줄인 프레임 기준이다.
계산만 한다. 어느 방법을 쓸지 고르는 일과 파일에 쓰는 일은 명령 쪽이 한다.
"""

import cv2
import numpy as np

from pipeline.candidates.channel_b import Blob

# 01장 1.6 "움직임 판정 시작값" (D-254). 밝기(0~255) 차이가 이 값 이상이면 달라진 픽셀이다
MOTION_DIFF_MIN = 25

# MOG2 전경을 믿을 수 없는 프레임에서 채널 A 트랙의 bbox를 사방으로 넓히는 비율 (D-265, D-268, D-333).
# 가로는 bbox 폭, 세로는 bbox 높이의 이 배씩 넓힌다
BBOX_GROW_RATIO = 0.1

# 줄인 프레임 좌표의 사각형 (x1, y1, x2, y2). 추적기가 돌려준 값이라 소수다
FloatBox = tuple[float, float, float, float]


def to_gray(image: np.ndarray) -> np.ndarray:
    """줄인 프레임(BGR)을 밝기 그림(회색조)으로 바꾼다. 밝기 차이는 이 그림끼리 잰다."""
    return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)


def changed_pixels(prev_gray: np.ndarray, gray: np.ndarray) -> np.ndarray:
    """직전 분석 프레임과 밝기 차이가 기준 이상인 칸이 참인 그림.

    absdiff는 두 그림의 픽셀별 차이의 절댓값이다. 그냥 빼면 부호 없는 수라 음수가 큰 수로 돈다.
    """
    return cv2.absdiff(prev_gray, gray) >= MOTION_DIFF_MIN


def moved_in_blob(blob: Blob, changed: np.ndarray, roi_in: np.ndarray) -> int:
    """덩어리 픽셀이면서 ROI 안이면서 달라진 픽셀 수 (D-333 나-1)."""
    x1, y1, x2, y2 = blob.bbox
    # blob.mask는 덩어리 bbox만큼 잘린 그림이라 다른 두 그림도 같은 자리만 잘라 견준다
    moved = blob.mask & changed[y1:y2, x1:x2] & roi_in[y1:y2, x1:x2]
    # NumPy가 센 값은 NumPy 정수라 JSON으로 쓸 수 없다. 파이썬 정수로 바꾼다
    return int(np.count_nonzero(moved))


def blobs_moved_mask(blobs: list[Blob], changed: np.ndarray, roi_in: np.ndarray) -> np.ndarray:
    """덩어리들의 픽셀이면서 ROI 안이면서 달라진 칸이 참인 그림 (줄인 프레임 크기).

    클래스 없는 트랙은 어느 덩어리로 만들어졌는지 코드에 남지 않는다.
    넘긴 덩어리를 한 그림에 모아 두고 트랙 bbox로 잘라 센다 (D-333 나-2).
    """
    canvas = np.zeros(changed.shape, bool)
    for blob in blobs:
        x1, y1, x2, y2 = blob.bbox
        canvas[y1:y2, x1:x2] |= blob.mask
    return canvas & changed & roi_in


def grow_bbox(bbox: FloatBox) -> FloatBox:
    """bbox를 사방으로 BBOX_GROW_RATIO만큼 넓힌다. 팔처럼 bbox 밖으로 조금 나간 움직임도 세려는 것이다."""
    x1, y1, x2, y2 = bbox
    grow_x, grow_y = (x2 - x1) * BBOX_GROW_RATIO, (y2 - y1) * BBOX_GROW_RATIO
    return (x1 - grow_x, y1 - grow_y, x2 + grow_x, y2 + grow_y)


def moved_in_bbox(bbox: FloatBox, moved: np.ndarray) -> int:
    """bbox 안에서 참인 칸 수. bbox는 가장 가까운 픽셀 경계로 맞추고, 그림 밖으로 나간 부분은 버린다."""
    x1, y1, x2, y2 = (max(round(value), 0) for value in bbox)
    return int(np.count_nonzero(moved[y1:y2, x1:x2]))
