"""카메라 쪽 변 판정, 바닥 띠, ROI 마스크 (D-194, D-244, D-302).

ROI는 "파손 변 주변에서 접근하는 물체가 화면에 나타나는 자리"다.
파손 변 바깥 바닥 띠를 화면 위로 차체 높이만큼 그대로 옮겨 쓸고 지나간 자리에, 파손 사각형 주변을 더한다 (D-302).
파손 변이 파손 사각형의 가로 범위에 못 미치면 변을 늘려 띠도 함께 늘린다.

띠의 길이(m)는 찍은 변을 자로 써서 잰다: 앞·뒤 변은 CAR_WIDTH_M, 옆 변은 CAR_LENGTH_M이다.
네 모서리로 바닥 전체를 펴는 변환은 쓰지 않는다. 모서리가 조금만 어긋나도 사각형 바깥에서 크기가 크게 부풀기 때문이다.
"""

from dataclasses import dataclass

import cv2
import numpy as np

from pipeline.candidates.crop import Crop, display_crop, expand_to_contain
from pipeline.candidates.inputs import AnalysisInput, Point

# 찍은 변의 실제 길이로 가정하는 일반 승용차 크기 (m). D-194, D-244 한계
CAR_WIDTH_M = 1.8
CAR_LENGTH_M = 4.7

# D-302 (시작값)
STRIP_OUT_M = 0.8  # 파손 변 바깥 띠 폭 (m). 손이 닿는 구역과 같다
TWO_EDGE_KEEP_RATIO = 1 / 2  # 파손 변 2개: 각 변을 만나는 모서리에서 이 비율만큼만 쓴다
# 띠의 차에 붙지 않은 끝은 실제 바닥에서 파손 변과 직각(이웃 변 방향)이다. 그 끝을 이 각도만큼 더 바깥으로 벌린다
END_FLARE_DEG = 15
# 띠를 위로 옮기는 높이 = 화면 속 차체 높이 × 이 값. 사람이 차보다 큰 만큼(1.7m / 1.5m ≈ 1.13)에 여유를 더했다
LIFT_RATIO = 1.3
# 파손 사각형을 자기 폭의 이 배씩 좌우로 넓힌 자리는 꼭 ROI에 넣는다.
# 파손 변이 그 가로 범위에 못 미치면 변을 그 끝까지 늘려 띠·ROI도 함께 늘린다 (세로는 띠를 쓸어 올린 높이를 따른다)
DAMAGE_PAD_X_RATIO = 0.5 / 3
DISPLAY_MARGIN_RATIO = 0.15  # 보여줄 크롭: ROI를 담는 사각형에 폭·높이의 이 배씩 여백


class RoiError(Exception):
    """ROI를 만들 수 없을 때. 메시지는 사용자에게 그대로 보여 준다."""


@dataclass(frozen=True)
class Roi:
    crop: Crop  # 분석 크롭 (보여줄 크롭을 못 담으면 넓힌 것)
    mask: np.ndarray  # 분석 크롭을 줄인 프레임 크기로 만든 ROI (안쪽 255)
    strip: np.ndarray  # 파손 변 바깥 바닥 띠. 위로 옮기기 전의 다각형, 원본 픽셀 (N, 2) int32
    display: Crop  # 보여줄 크롭 (ROI 기준)


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


def _edge_length_m(edge: int, front_edge: int) -> float:
    """변 edge의 실제 길이 (m). 앞쪽 변과 그 맞은편이 폭, 나머지가 길이다 (D-194)."""
    return CAR_WIDTH_M if (edge - front_edge) % 2 == 0 else CAR_LENGTH_M


def _out_at(corners: np.ndarray, edge: int, t: float, front_edge: int) -> np.ndarray:
    """변 edge 위 t(시작 0 ~ 끝 1) 자리에서 바깥 STRIP_OUT_M만큼의 화면 벡터.

    변의 끝에서 실제로 직각인 방향은 그 끝에서 만나는 이웃 변을 바깥으로 이어 간 방향이다.
    이웃 변의 화면 길이를 자로 써서 STRIP_OUT_M을 재고, 두 끝 사이는 고르게 섞는다.
    """
    prev, nxt, far = (edge - 1) % 4, (edge + 1) % 4, (edge + 2) % 4
    at_start = (corners[edge] - corners[prev]) * STRIP_OUT_M / _edge_length_m(prev, front_edge)
    at_end = (corners[nxt] - corners[far]) * STRIP_OUT_M / _edge_length_m(nxt, front_edge)
    return (1 - t) * at_start + t * at_end


def _extend_end(end: np.ndarray, direction: np.ndarray, x_range: tuple[float, float]) -> np.ndarray:
    """선의 끝 end를 화면에서 direction으로 늘려, x가 x_range의 끝에 닿게 한다. 이미 닿았으면 그대로 둔다."""
    if direction[0] == 0:
        return end
    target = x_range[1] if direction[0] > 0 else x_range[0]
    t = (target - end[0]) / direction[0]
    return end + max(t, 0.0) * direction


def _damage_x_range(data: AnalysisInput) -> tuple[float, float]:
    """파손 사각형을 좌우로 DAMAGE_PAD_X_RATIO만큼 넓힌 가로 범위 (원본 픽셀)."""
    dx1, _, dx2, _ = data.damage_bbox
    pad_x = DAMAGE_PAD_X_RATIO * (dx2 - dx1)
    return (dx1 - pad_x, dx2 + pad_x)


def _floor_strip(data: AnalysisInput) -> np.ndarray:
    """화면(원본 픽셀)의 띠 다각형. 앞쪽 꼭짓점들(변 1개 2개, 변 2개 3개)은 차에 붙은 파손 선 위의 점이다.

    변 1개: 선 = [시작, 끝]. 변 2개: 선 = [p, 만나는 모서리, q]. p·q는 모서리에서 각 변의 TWO_EDGE_KEEP_RATIO 지점이다.
    선의 두 끝을 파손 사각형(좌우 여백 포함)의 가로 범위까지 늘린 뒤, 바깥 STRIP_OUT_M로 띠를 만든다.
    차에 붙지 않은 두 끝은 바깥으로 갈수록 END_FLARE_DEG만큼 벌어진다.
    변 2개면 두 띠의 바깥 꼭짓점을 이어 L자 하나로 만든다 (만나는 모서리는 이어져 있어 벌릴 끝이 없다).
    """
    corners = np.array(data.floor_corners, dtype=np.float64)
    front = data.front_edge
    edges = data.damage_edges
    if len(edges) == 1:
        e1 = e2 = edges[0]
        line = [corners[e1], corners[(e1 + 1) % 4]]
        t_start, t_end = 0.0, 1.0
    else:
        # 이웃한 두 변 e1 → e2 (e2의 시작점 = e1의 끝점 = 만나는 모서리)
        e1, e2 = edges if (edges[0] + 1) % 4 == edges[1] else edges[::-1]
        corner = corners[e2]
        p = corner + (corners[e1] - corner) * TWO_EDGE_KEEP_RATIO
        q = corner + (corners[(e2 + 1) % 4] - corner) * TWO_EDGE_KEEP_RATIO
        line = [p, corner, q]
        t_start, t_end = 1 - TWO_EDGE_KEEP_RATIO, TWO_EDGE_KEEP_RATIO

    # 변을 따라 1m가 화면에서 얼마인가. 시작 쪽은 변을 거꾸로, 끝 쪽은 변 방향으로 나간다
    start_1m = (corners[e1] - corners[(e1 + 1) % 4]) / _edge_length_m(e1, front)
    end_1m = (corners[(e2 + 1) % 4] - corners[e2]) / _edge_length_m(e2, front)

    x_range = _damage_x_range(data)
    line[0] = _extend_end(line[0], start_1m, x_range)
    line[-1] = _extend_end(line[-1], end_1m, x_range)

    # 바깥 끝이 변 방향으로 더 나가는 거리 (m). 직각에서 END_FLARE_DEG 벌어진 선이 된다
    flare_m = STRIP_OUT_M * np.tan(np.radians(END_FLARE_DEG))
    outer = [line[-1] + _out_at(corners, e2, t_end, front) + flare_m * end_1m]
    if len(edges) == 2:
        outer.append(line[1] + _out_at(corners, e1, 1.0, front) + _out_at(corners, e2, 0.0, front))
    outer.append(line[0] + _out_at(corners, e1, t_start, front) + flare_m * start_1m)
    return np.vstack([line, outer])


def _sweep_up(mask: np.ndarray, polygon: np.ndarray, lift: int) -> None:
    """polygon을 화면 위로 lift만큼 옮기며 지나간 자리 전체를 mask에 채운다.

    다각형, 옮긴 다각형, 각 변이 지나간 평행사변형의 합집합이다.
    모든 꼭짓점을 같은 px로 옮기므로 위 경계는 띠의 변과 화면에서 평행하다.
    """
    up = polygon - [0, lift]
    parts = [polygon, up]
    for i in range(len(polygon)):
        j = (i + 1) % len(polygon)
        parts.append(np.array([polygon[i], polygon[j], up[j], up[i]]))
    for part in parts:
        cv2.fillPoly(mask, [part], 255)


def _roi_mask_original(
    data: AnalysisInput, frame: tuple[int, int]
) -> tuple[np.ndarray, np.ndarray]:
    """원본 화면 크기의 ROI 마스크 (안쪽 255)와 바닥 띠. 화면 밖으로 나간 부분은 버려진다."""
    width, height = frame
    polygon = np.round(_floor_strip(data)).astype(np.int32)
    # 화면 속 차체 높이 = 가장 먼(화면에서 가장 높은) 바닥 모서리 ~ bbox 위 변(먼 쪽 지붕).
    # bbox 세로는 바닥 사각형의 앞뒤 깊이까지 들어 있어, 카메라가 높을수록 차 높이보다 훨씬 커진다
    body_height = min(y for _, y in data.floor_corners) - data.vehicle_bbox[1]
    if body_height <= 0:
        # 음수면 띠가 아래로 쓸려 엉뚱한 ROI가 된다
        raise RoiError(
            "바닥 네 모서리가 차량 사각형의 위 변보다 위에 있습니다. 입력을 확인해 주세요."
        )
    lift = round(body_height * LIFT_RATIO)

    mask = np.zeros((height, width), np.uint8)
    _sweep_up(mask, polygon, lift)

    # 파손 사각형(좌우 여백 포함)이 빠져 있으면 그 자리를 더한다 (합집합이라 이미 덮인 곳은 그대로다)
    left, right = _damage_x_range(data)
    _, dy1, _, dy2 = data.damage_bbox
    cv2.rectangle(mask, (round(left), dy1), (round(right), dy2), 255, -1)
    return mask, polygon


def build_roi(data: AnalysisInput, frame: tuple[int, int], crop: Crop) -> Roi:
    """ROI, 바닥 띠, 보여줄 크롭을 만든다.

    보여줄 크롭은 ROI 기준이고, 분석 크롭이 보여줄 크롭을 못 담으면 분석 크롭을 넓힌다
    (D-95 ROI ⊂ 보여줄 ⊂ 분석). 마스크는 (넓힌) 분석 크롭을 줄인 프레임 크기다 (안쪽 255, D-201).
    """
    full, strip = _roi_mask_original(data, frame)
    ys, xs = np.nonzero(full)
    if len(xs) == 0:
        raise RoiError("ROI가 화면 밖에 있어 비어 있습니다. 바닥 네 모서리를 확인해 주세요.")
    roi_rect = (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)
    display = display_crop(roi_rect, frame, DISPLAY_MARGIN_RATIO)
    crop = expand_to_contain(crop, display.rect, frame)

    x1, y1, x2, y2 = crop.rect
    small = cv2.resize(full[y1:y2, x1:x2], crop.reduced_size, interpolation=cv2.INTER_AREA)
    mask = np.where(small >= 128, 255, 0).astype(np.uint8)
    return Roi(crop, mask, strip, display)
