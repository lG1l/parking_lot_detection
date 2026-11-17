"""후보 구간을 만드는 계산 (06장 6.5 "후보 구간의 규칙", D-245, D-333).

트랙 줄의 moved_px(움직인 픽셀 수)로 그 프레임이 움직인 프레임인지 정한다.
계산만 한다. 파일을 읽고 쓰는 일은 명령 쪽이 한다.
"""

# 01장 1.6 "움직임 판정 시작값" (D-254). 달라진 픽셀이 줄인 분석 프레임 넓이의 이 비율 이상이면 움직인 프레임이다
MOTION_AREA_RATIO = 0.0001


def is_moving_line(line: dict, crop_area: int) -> bool:
    """트랙 줄 하나가 움직인 프레임인지 (D-333 나-4).

    moved_px가 null(맨 첫 프레임)이거나 키가 없으면(거슬러 돈 프레임) 움직임이 아니다.
    """
    moved_px = line.get("moved_px")
    return moved_px is not None and moved_px >= crop_area * MOTION_AREA_RATIO


def has_moving_frame(lines: list[dict], crop_area: int) -> bool:
    """트랙에 움직인 프레임이 하나라도 있는지. 없으면 후보 구간이 생기지 않는다."""
    return any(is_moving_line(line, crop_area) for line in lines)
