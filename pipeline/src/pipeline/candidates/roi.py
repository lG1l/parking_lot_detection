"""바닥 지도, 카메라 쪽 변 판정, ROI 마스크 (D-194, D-244).

ROI는 "파손 변 주변에서 접근하는 물체가 화면에 나타나는 자리"다.
지금은 파손 변이 모두 카메라 쪽 옆면일 때(D-244 결정 2)만 만든다.
"""

import cv2
import numpy as np

from pipeline.candidates.crop import Crop, expand_to_contain
from pipeline.candidates.inputs import AnalysisInput, Point

# 바닥 지도가 가정하는 일반 승용차 크기 (m). D-194, D-244 한계
CAR_WIDTH_M = 1.8
CAR_LENGTH_M = 4.7

# D-244 결정 2 (시작값)
STRIP_OUT_M = 1.0  # 파손 변 바깥 띠 폭 (m)
STRIP_END_M = 0.5  # 띠를 양 끝으로 늘리는 길이 (m)
ENTRY_BOX_RATIO = 0.12  # 양 끝 출입 상자: 차량 bbox 폭·높이의 ±이 배
DAMAGE_PAD_RATIO = 0.15  # 파손 사각형을 차량 bbox 폭·높이의 이 배씩 넓힘


class RoiNotImplementedError(Exception):
    """아직 만들지 않은 ROI 경우. 메시지는 사용자에게 그대로 보여 준다."""


class RoiError(Exception):
    """ROI를 만들 수 없을 때. 메시지는 사용자에게 그대로 보여 준다."""


def camera_side_edges(corners: list[Point]) -> list[int]:
    """네 모서리 사각형에서 바깥쪽이 화면 아래를 향한 변의 번호 (06장 바닥점 필터)."""
    cx = sum(p[0] for p in corners) / 4
    cy = sum(p[1] for p in corners) / 4
    result = []
    for i in range(4):
        a, b = corners[i], corners[(i + 1) % 4]
        # 변에 수직인 방향 둘 가운데, 사각형 가운데에서 멀어지는 쪽이 바깥이다
        normal = (b[1] - a[1], a[0] - b[0])
        away = (a[0] + b[0]) / 2 - cx, (a[1] + b[1]) / 2 - cy
        if normal[0] * away[0] + normal[1] * away[1] < 0:
            normal = (-normal[0], -normal[1])
        if normal[1] > 0:  # 화면 y는 아래로 늘어난다
            result.append(i)
    return result


def floor_points(front_edge: int) -> list[tuple[float, float]]:
    """바닥 지도 위 네 모서리의 위치 (m). 앞쪽 변이 폭 방향 끝 변이다 (D-194).

    모서리 front_edge → (0,0), 그다음 모서리부터 차례로 (폭,0), (폭,길이), (0,길이)다.
    인덱스는 corners 순서와 같다.
    """
    layout = [(0, 0), (CAR_WIDTH_M, 0), (CAR_WIDTH_M, CAR_LENGTH_M), (0, CAR_LENGTH_M)]
    return [layout[(j - front_edge) % 4] for j in range(4)]


def _strip_polygon(data: AnalysisInput, edge: int, to_screen: np.ndarray) -> np.ndarray:
    """파손 변 바깥 띠를 화면 좌표 다각형으로 만든다."""
    floor = np.array(floor_points(data.front_edge), dtype=np.float64)
    a, b = floor[edge], floor[(edge + 1) % 4]
    center = floor.mean(axis=0)
    u = (b - a) / np.linalg.norm(b - a)
    out = (a + b) / 2 - center
    out = out / np.linalg.norm(out)
    start = a - STRIP_END_M * u
    end = b + STRIP_END_M * u
    quad = np.array([start, end, end + STRIP_OUT_M * out, start + STRIP_OUT_M * out])
    screen = cv2.perspectiveTransform(quad.reshape(-1, 1, 2).astype(np.float32), to_screen)
    return screen.reshape(-1, 2)


def _fill_upward(mask: np.ndarray, top_y: int) -> None:
    """mask의 각 열을, 가장 위 1인 칸부터 top_y 줄까지 위로 채운다."""
    filled = mask > 0
    has_any = filled.any(axis=0)
    first_row = filled.argmax(axis=0)
    rows = np.arange(mask.shape[0])[:, None]
    mask[(rows >= top_y) & (rows <= first_row[None, :]) & has_any[None, :]] = 255


def _roi_mask_original(data: AnalysisInput, frame: tuple[int, int]) -> np.ndarray:
    """원본 화면 크기의 ROI 마스크 (안쪽 255). 화면 밖으로 나간 부분은 버려진다."""
    width, height = frame
    bx1, by1, bx2, by2 = data.vehicle_bbox
    bw, bh = bx2 - bx1, by2 - by1

    src = np.array(data.floor_corners, dtype=np.float32)
    dst = np.array(floor_points(data.front_edge), dtype=np.float32)
    to_screen = cv2.getPerspectiveTransform(dst, src)

    strip = np.zeros((height, width), np.uint8)
    boxes = np.zeros((height, width), np.uint8)
    for edge in data.damage_edges:
        poly = _strip_polygon(data, edge, to_screen)
        cv2.fillPoly(strip, [np.round(poly).astype(np.int32)], 255)
        # 파손 변 양 끝점 중심 상자
        for p in (data.floor_corners[edge], data.floor_corners[(edge + 1) % 4]):
            x1, x2 = round(p[0] - ENTRY_BOX_RATIO * bw), round(p[0] + ENTRY_BOX_RATIO * bw)
            y1, y2 = round(p[1] - ENTRY_BOX_RATIO * bh), round(p[1] + ENTRY_BOX_RATIO * bh)
            cv2.rectangle(boxes, (x1, y1), (x2, y2), 255, -1)
    _fill_upward(strip, by1)

    dx1, dy1, dx2, dy2 = data.damage_bbox
    cv2.rectangle(
        boxes,
        (round(dx1 - DAMAGE_PAD_RATIO * bw), round(dy1 - DAMAGE_PAD_RATIO * bh)),
        (round(dx2 + DAMAGE_PAD_RATIO * bw), round(dy2 + DAMAGE_PAD_RATIO * bh)),
        255,
        -1,
    )
    return cv2.bitwise_or(strip, boxes)


def build_roi(data: AnalysisInput, frame: tuple[int, int], crop: Crop) -> tuple[Crop, np.ndarray]:
    """ROI 마스크를 만든다. 분석 크롭이 ROI를 담지 못하면 크롭을 넓혀 함께 돌려준다.

    마스크는 (넓힌) 분석 크롭을 줄인 프레임 크기로 만든 것이다 (안쪽 255, D-201).
    """
    camera = camera_side_edges(data.floor_corners)
    for edge in data.damage_edges:
        is_end_edge = (edge - data.front_edge) % 2 == 0  # 앞쪽 변이거나 그 맞은편 변
        if edge not in camera or is_end_edge:
            raise RoiNotImplementedError(
                "파손 변이 모두 카메라 쪽 옆면인 경우만 만들었습니다. "
                f"(파손 변 {data.damage_edges}, 앞쪽 변 {data.front_edge}, 카메라 쪽 변 {camera}) "
                "건너편·앞뒤 끝 변이 섞인 경우는 아직 만들지 않았습니다."
            )

    full = _roi_mask_original(data, frame)
    ys, xs = np.nonzero(full)
    if len(xs) == 0:
        raise RoiError("ROI가 화면 밖에 있어 비어 있습니다. 바닥 네 모서리를 확인해 주세요.")
    # 화면 안에 남은 ROI를 담는 가장 작은 사각형까지 크롭을 넓힌다 (D-201 포함 관계)
    roi_rect = (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)
    crop = expand_to_contain(crop, roi_rect, frame)

    x1, y1, x2, y2 = crop.rect
    small = cv2.resize(full[y1:y2, x1:x2], crop.reduced_size, interpolation=cv2.INTER_AREA)
    mask = np.where(small >= 128, 255, 0).astype(np.uint8)
    return crop, mask
