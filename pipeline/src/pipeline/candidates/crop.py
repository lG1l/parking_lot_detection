"""분석 크롭, 줄인 프레임 크기, 원본 ↔ 줄인 프레임 좌표 바꾸기 (D-201, D-244).

크롭은 원본 픽셀 좌표의 사각형 (x1, y1, x2, y2)이고, x2·y2는 포함하지 않는 끝이다.
"""

from dataclasses import dataclass

# 분석 크롭 폭 = 본인 차량 bbox 폭 × 이 값. 01장 1.6 "분석 크롭 크기" (시작값)
CROP_WIDTH_RATIO = 2

# 줄인 프레임. 긴 변이 REDUCED_LONG_SIDE보다 크면 REDUCED_SIZE로 줄인다. 01장 1.6 "채널 A·B 프레임 크기" (시작값)
REDUCED_LONG_SIDE = 640
REDUCED_SIZE = (640, 360)

Rect = tuple[int, int, int, int]
Point = tuple[float, float]


class CropError(Exception):
    """크롭이 원본 화면 안에 들어갈 수 없을 때. 메시지는 사용자에게 그대로 보여 준다."""


@dataclass(frozen=True)
class Crop:
    rect: Rect  # 원본 픽셀
    reduced_size: tuple[int, int]  # 줄인 프레임 (폭, 높이)

    @property
    def width(self) -> int:
        return self.rect[2] - self.rect[0]

    @property
    def height(self) -> int:
        return self.rect[3] - self.rect[1]


def _height_for(width: int) -> int:
    # 16:9. 반올림은 .5를 올린다 (600 → 337.5 → 338)
    return (width * 9 + 8) // 16


def _fit_16x9(width: int, height: int) -> tuple[int, int]:
    """폭×높이를 모두 담는 가장 작은 16:9 (폭, 높이)."""
    w = max(width, -(-height * 16 // 9))
    h = _height_for(w)
    # 반올림으로 높이가 모자라면 한 칸씩 키운다
    while h < height:
        w += 1
        h = _height_for(w)
    return w, h


def _place(
    center_x: float, center_y: float, width: int, height: int, frame: tuple[int, int]
) -> Rect:
    """중심에 맞춰 놓고, 원본 밖으로 나가면 크기를 유지한 채 안쪽으로 민다 (D-175 결정 3)."""
    frame_w, frame_h = frame
    if width > frame_w or height > frame_h:
        # 차가 화면 폭의 1/3보다 큰 경우다. 넓히는 규칙은 아직 없다 (Task.md 미룬 것 2)
        raise CropError(
            f"분석 크롭({width}×{height})이 원본({frame_w}×{frame_h})보다 큽니다. "
            "차가 화면에서 너무 큰 경우는 아직 만들지 않았습니다."
        )
    x1 = round(center_x - width / 2)
    y1 = round(center_y - height / 2)
    x1 = min(max(x1, 0), frame_w - width)
    y1 = min(max(y1, 0), frame_h - height)
    return (x1, y1, x1 + width, y1 + height)


def reduced_size_for(width: int, height: int) -> tuple[int, int]:
    """긴 변이 640보다 크면 640×360, 아니면 그대로 쓴다. 키우지 않는다 (D-201)."""
    if max(width, height) > REDUCED_LONG_SIDE:
        return REDUCED_SIZE
    return (width, height)


def analysis_crop(vehicle_bbox: Rect, frame: tuple[int, int]) -> Crop:
    """본인 차량 bbox로 분석 크롭을 계산한다. frame은 원본 (폭, 높이)."""
    x1, y1, x2, y2 = vehicle_bbox
    width = round((x2 - x1) * CROP_WIDTH_RATIO)
    height = _height_for(width)
    rect = _place((x1 + x2) / 2, (y1 + y2) / 2, width, height, frame)
    return Crop(rect, reduced_size_for(width, height))


def expand_to_contain(crop: Crop, region: Rect, frame: tuple[int, int]) -> Crop:
    """크롭과 region을 모두 담는 가장 작은 16:9 크롭으로 넓힌다 (D-201 포함 관계).

    이미 region을 담고 있으면 그대로 돌려준다.
    """
    cx1, cy1, cx2, cy2 = crop.rect
    rx1, ry1, rx2, ry2 = region
    if rx1 >= cx1 and ry1 >= cy1 and rx2 <= cx2 and ry2 <= cy2:
        return crop

    ux1, uy1, ux2, uy2 = min(cx1, rx1), min(cy1, ry1), max(cx2, rx2), max(cy2, ry2)
    width, height = _fit_16x9(ux2 - ux1, uy2 - uy1)
    rect = _place((ux1 + ux2) / 2, (uy1 + uy2) / 2, width, height, frame)
    return Crop(rect, reduced_size_for(width, height))


def display_crop(region: Rect, frame: tuple[int, int], margin_ratio: float) -> Crop:
    """region(ROI를 담는 사각형)에 폭·높이의 margin_ratio씩 여백을 더한 16:9 보여줄 크롭 (D-302).

    차량이 아니라 ROI가 기준이다. 화면 밖으로 나가면 크기를 유지한 채 안쪽으로 민다.
    """
    rx1, ry1, rx2, ry2 = region
    pad_x, pad_y = round((rx2 - rx1) * margin_ratio), round((ry2 - ry1) * margin_ratio)
    width, height = _fit_16x9(rx2 - rx1 + 2 * pad_x, ry2 - ry1 + 2 * pad_y)
    rect = _place((rx1 + rx2) / 2, (ry1 + ry2) / 2, width, height, frame)
    return Crop(rect, reduced_size_for(width, height))


def _scales(crop: Crop) -> tuple[float, float]:
    # 반올림 때문에 가로·세로 배율이 조금 다를 수 있어 따로 계산한다 (D-201 구현 주의)
    return crop.reduced_size[0] / crop.width, crop.reduced_size[1] / crop.height


def to_reduced(point: Point, crop: Crop) -> Point:
    """원본 좌표 → 줄인 프레임 좌표."""
    sx, sy = _scales(crop)
    return ((point[0] - crop.rect[0]) * sx, (point[1] - crop.rect[1]) * sy)


def to_original(point: Point, crop: Crop) -> Point:
    """줄인 프레임 좌표 → 원본 좌표."""
    sx, sy = _scales(crop)
    return (point[0] / sx + crop.rect[0], point[1] / sy + crop.rect[1])
