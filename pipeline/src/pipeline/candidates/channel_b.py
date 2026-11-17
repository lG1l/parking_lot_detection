"""채널 B: MOG2 전경에서 덩어리를 골라 ROI 움직임을 판정한다 (D-192, D-195, D-201).

MOG2는 분석 크롭 전체(줄인 프레임)에 돌고, ROI는 "이 프레임에 ROI 움직임이 있는가"를 판정할 때만 쓴다.
ROI 움직임 = 노이즈 기준 이상인 전경 덩어리 중 하나라도 ROI와 한 픽셀 이상 겹친다 (06장 "ROI 움직임의 정의").
"""

from dataclasses import dataclass

import cv2
import numpy as np

# 01장 1.6 "채널 B 시작값" (D-195). 임계값과 학습 시간은 시연 영상으로 조정한 값이다 (D-309)
FOREGROUND_THRESHOLD = 100  # MOG2 varThreshold. 얼마나 달라져야 전경으로 볼지
BACKGROUND_LEARN_SEC = 30  # 배경 학습 시간. 프레임 수는 샘플링 fps로 환산한다
NOISE_AREA_RATIO = 0.0001  # 줄인 프레임 넓이의 0.01% 미만 덩어리는 노이즈로 버린다
# 덩어리 상한. 줄인 프레임 넓이의 30% 이상인 덩어리(조명 변화 등)로는 클래스 없는 트랙을 만들지 않는다
BLOB_MAX_AREA_RATIO = 0.3

# 01장 1.6 "덩어리 붙이기·확장 시작값"의 끊어진 덩어리 잇기 (D-197).
# 덩어리 사이 간격이 줄인 프레임 짧은 변의 1% 안쪽이면 같은 묶음이다 (D-315)
BLOB_JOIN_GAP_RATIO = 0.01

# 이 시각 전의 전경은 믿지 않는다. 01장 1.6 "MOG2 안정 시간" = 배경 학습 시간 (D-199)
MOG2_STABLE_SEC = BACKGROUND_LEARN_SEC

# 움직임 프레임 사이가 이 값(초) 이하면 같은 구간. 01장 1.6 "후보 구간 끊김 간격"을 빌려 쓴다 (D-317)
RANGE_GAP_SEC = 1.0

# 시각을 소수로 다루다 생기는 오차를 흡수하는 값 (초). 4.9 - 4.1이 0.8보다 조금 클 수 있다
_TIME_EPS = 1e-6

# MOG2 마스크 값. detectShadows를 켜면 그림자를 127로 따로 표시한다
FOREGROUND = 255

# 자잘한 점 지우기(열기)에 쓰는 3×3 사각형. 설계에 크기가 없어 가장 작은 값을 쓴다 (Task.md 가정 6)
_OPEN_KERNEL = np.ones((3, 3), np.uint8)


# 줄인 프레임 좌표의 사각형 (x1, y1, x2, y2). x2·y2는 포함하지 않는 끝이다
Box = tuple[int, int, int, int]


@dataclass(frozen=True)
class Blob:
    area: int  # 실제 전경 픽셀 수 (bbox 넓이가 아니다, D-195)
    contour: np.ndarray  # 줄인 프레임 좌표의 바깥 테두리. 확인용 영상에 칠할 때 쓴다
    touches_roi: bool
    bbox: Box  # 덩어리를 감싼 사각형
    # bbox 크기(높이×폭)의 참·거짓 그림. 참인 칸이 이 덩어리의 픽셀이다.
    # 프레임 전체 크기로 들고 있으면 프레임마다 메모리가 많이 들어 bbox만큼만 잘라 둔다
    mask: np.ndarray


@dataclass(frozen=True)
class FrameRecord:
    """탐지 중 분석 프레임 한 장마다 적는 사실. 구간 판정은 탐지가 끝난 뒤 이것만 보고 한다 (D-250)."""

    time_sec: float
    roi_motion: bool
    blobs: list[Blob]


@dataclass(frozen=True)
class MotionRange:
    start_sec: float  # 첫 움직임 프레임의 시각
    end_sec: float  # 마지막 움직임 프레임의 시각
    motion_frames: int  # 구간 안에서 ROI 움직임이 있던 프레임 수


def create_mog2(sampling_fps: float) -> cv2.BackgroundSubtractorMOG2:
    """01장 시작값으로 MOG2를 만든다. 학습 시간을 프레임 수로 바꿔 history에 넣는다."""
    history = round(BACKGROUND_LEARN_SEC * sampling_fps)
    return cv2.createBackgroundSubtractorMOG2(
        history=history, varThreshold=FOREGROUND_THRESHOLD, detectShadows=True
    )


def clean_foreground(fg_mask: np.ndarray) -> np.ndarray:
    """그림자(127)를 빼고 열기 연산으로 자잘한 점을 지운 0/255 마스크를 만든다."""
    binary = np.where(fg_mask == FOREGROUND, 255, 0).astype(np.uint8)
    return cv2.morphologyEx(binary, cv2.MORPH_OPEN, _OPEN_KERNEL)


def noise_min_area(shape: tuple[int, ...]) -> float:
    """노이즈 기준(픽셀 수). 해상도에 따라 뜻이 바뀌지 않게 줄인 프레임 넓이 대비 비율로 잰다."""
    return shape[0] * shape[1] * NOISE_AREA_RATIO


def find_blobs(binary: np.ndarray, roi_mask: np.ndarray) -> list[Blob]:
    """깨끗한 전경 마스크에서 노이즈 기준 이상인 덩어리를 골라 ROI에 닿는지 표시한다.

    덩어리는 대각선까지 이어진 픽셀 묶음(8방향)이다 (Task.md 가정 7).
    """
    count, labels, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
    min_area = noise_min_area(binary.shape)
    blobs = []
    # 0번은 배경이라 건너뛴다
    for label in range(1, count):
        area = int(stats[label, cv2.CC_STAT_AREA])
        if area < min_area:
            continue
        pixels = labels == label
        touches = bool(np.any(roi_mask[pixels]))
        contours, _ = cv2.findContours(
            pixels.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        # stats에는 넓이 말고 bbox(왼쪽, 위, 폭, 높이)도 들어 있다
        x, y = int(stats[label, cv2.CC_STAT_LEFT]), int(stats[label, cv2.CC_STAT_TOP])
        w, h = int(stats[label, cv2.CC_STAT_WIDTH]), int(stats[label, cv2.CC_STAT_HEIGHT])
        bbox = (x, y, x + w, y + h)
        blobs.append(Blob(area, contours[0], touches, bbox, pixels[y : y + h, x : x + w].copy()))
    return blobs


def has_roi_motion(blobs: list[Blob]) -> bool:
    """덩어리 중 하나라도 ROI에 닿으면 이 프레임에 ROI 움직임이 있다."""
    return any(blob.touches_roi for blob in blobs)


def join_gap_px(shape: tuple[int, ...]) -> int:
    """끊어진 덩어리 잇기 간격(픽셀). 덩어리 사이의 빈 픽셀이 이 수 이하면 같은 묶음이다."""
    return int(min(shape[0], shape[1]) * BLOB_JOIN_GAP_RATIO)


def group_blobs(blobs: list[Blob], shape: tuple[int, ...]) -> list[list[int]]:
    """가까운 덩어리끼리 묶는다 (D-315). 묶음 하나는 blobs의 자리 번호 목록이다.

    전경을 부풀리면(팽창) 가까운 덩어리끼리 붙는다. 부풀린 그림에서 연결 요소를 다시 구해
    "어느 덩어리가 같은 묶음인지"만 알아낸다. 노이즈로 버린 점은 그리지 않으므로 다리가 되지 않는다.
    """
    canvas = np.zeros(shape[:2], np.uint8)
    for blob in blobs:
        x1, y1, x2, y2 = blob.bbox
        canvas[y1:y2, x1:x2][blob.mask] = 255
    # 한 변이 (간격 + 1)인 사각형으로 부풀리면, 사이의 빈 픽셀이 간격 이하인 두 픽셀이 맞닿는다
    size = join_gap_px(shape) + 1
    grown = cv2.dilate(canvas, np.ones((size, size), np.uint8))
    _, labels = cv2.connectedComponents(grown, connectivity=8)
    groups: dict[int, list[int]] = {}
    for index, blob in enumerate(blobs):
        x1, y1, _, _ = blob.bbox
        # 덩어리의 픽셀 하나만 보면 된다. 부풀려도 한 덩어리는 한 연결 요소 안에 있다
        row, col = np.argwhere(blob.mask)[0]
        groups.setdefault(int(labels[y1 + row, x1 + col]), []).append(index)
    return list(groups.values())


def has_oversized_blob(blobs: list[Blob], group: list[int], shape: tuple[int, ...]) -> bool:
    """묶음 안에 덩어리 상한 이상인 덩어리가 있는가. 있으면 그 묶음은 추적기에 넣지 않는다."""
    max_area = shape[0] * shape[1] * BLOB_MAX_AREA_RATIO
    return any(blobs[index].area >= max_area for index in group)


def group_bbox(blobs: list[Blob], group: list[int]) -> Box:
    """묶음 전체를 감싼 사각형. 부풀리기 전의 덩어리 bbox로 계산한다."""
    boxes = [blobs[index].bbox for index in group]
    return (
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    )


def boxes_for_tracker(
    blobs: list[Blob], groups: list[list[int]], attached: set[int], shape: tuple[int, ...]
) -> list[Box]:
    """채널 B 추적기에 넣을 사각형을 고른다 (D-315). attached는 채널 A 트랙에 붙은 덩어리의 자리 번호다.

    묶음 안에 "ROI에 닿았고 붙지 않은 덩어리"가 하나라도 있으면 묶음 전체의 사각형 하나를 넣는다.
    """
    boxes = []
    for group in groups:
        if has_oversized_blob(blobs, group, shape):
            continue
        if any(blobs[index].touches_roi and index not in attached for index in group):
            boxes.append(group_bbox(blobs, group))
    return boxes


def merge_motion_ranges(records: list[FrameRecord]) -> list[MotionRange]:
    """ROI 움직임이 있던 프레임을 시간순으로 이어 붙여 움직임 구간을 만든다 (D-317).

    앞 움직임 프레임과의 사이가 RANGE_GAP_SEC 이하면 같은 구간에 넣고, 넘으면 새 구간을 연다.
    전경이 한두 프레임 깜빡여 한 장면이 여러 조각으로 나뉘지 않게 하려는 것이다.
    """
    ranges: list[MotionRange] = []
    for record in records:
        if not record.roi_motion:
            continue
        last = ranges[-1] if ranges else None
        if last and record.time_sec - last.end_sec <= RANGE_GAP_SEC + _TIME_EPS:
            ranges[-1] = MotionRange(last.start_sec, record.time_sec, last.motion_frames + 1)
        else:
            ranges.append(MotionRange(record.time_sec, record.time_sec, 1))
    return ranges
