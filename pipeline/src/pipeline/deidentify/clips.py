"""후보 클립을 보여줄 크롭으로 잘라 H.264 MP4로 만든다 (D-345).

여기서 만드는 클립은 가리기 전(비식별화하지 않은 원본 크롭)이다.
local_storage/ 밖으로 내보내지 않는다 (불변 조건 3).
8-나(얼굴·번호판 탐지)와 8-다(모자이크 클립)가 이 파일의 함수를 불러 쓴다.
"""

from collections.abc import Iterator
from dataclasses import dataclass

import cv2
import numpy as np

# 시각을 소수로 다루다 생기는 오차를 흡수하는 값 (초)
_TIME_EPS = 1e-6

Rect = tuple[int, int, int, int]  # x1, y1, x2, y2 (원본 픽셀)
Clip = tuple[float, float]  # 클립의 (시작, 끝) 시각 (초)


@dataclass
class ClipFrame:
    time_sec: float  # 프레임의 실제 시각 (원본 시간, 초)
    image: np.ndarray  # 원본 화면 전체 (BGR). 자르는 것은 받는 쪽이 한다
    clip_numbers: list[int]  # 이 프레임이 들어가는 클립의 번호 (1부터). 겹치면 여러 개다


def even_rect(rect: Rect) -> Rect:
    """사각형의 폭·높이가 홀수이면 오른쪽·아래쪽에서 1픽셀 줄여 짝수로 맞춘다 (D-345 가-2).

    H.264(yuv420p)는 짝수 크기만 받는다. 늘리지 않고 줄이는 이유는
    원본 경계에 붙은 크롭이 화면 밖으로 나가지 않게 하기 위해서다.
    """
    x1, y1, x2, y2 = rect
    return (x1, y1, x2 - (x2 - x1) % 2, y2 - (y2 - y1) % 2)


def clip_numbers_at(time_sec: float, clips: list[Clip]) -> list[int]:
    """이 시각의 프레임이 들어가는 클립의 번호(1부터)를 모두 돌려준다.

    시각이 start_sec 이상 end_sec 미만이면 들어간다 (D-345 가-3).
    끝 시각을 넣지 않아야 클립 길이가 end_sec − start_sec와 같아진다.
    """
    return [
        number
        for number, (start, end) in enumerate(clips, start=1)
        if start - _TIME_EPS <= time_sec < end - _TIME_EPS
    ]


def iter_clip_frames(video_path: str, clips: list[Clip]) -> Iterator[ClipFrame]:
    """영상을 한 번 읽으며 클립에 들어가는 원본 프레임을 모두 차례로 내준다.

    프레임을 번호가 아니라 영상이 알려 주는 시각으로 고른다. 프레임이 빠진 영상에서
    구간이 밀리지 않게 하기 위해서다 (D-300과 같은 방식).
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise FileNotFoundError(f"영상을 열 수 없습니다: {video_path}")
    last_end = max((end for _, end in clips), default=0.0)
    try:
        # grab()은 다음 프레임으로 넘어가기만 하고 화면을 풀지 않는다.
        # 어느 클립에도 안 들어가는 프레임은 화면을 풀지 않고 빨리 지나간다.
        while cap.grab():
            time_sec = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
            if time_sec >= last_end - _TIME_EPS:
                break  # 마지막 클립까지 끝났으면 영상을 더 읽지 않는다
            numbers = clip_numbers_at(time_sec, clips)
            if not numbers:
                continue
            ok, image = cap.retrieve()
            if not ok:
                break
            yield ClipFrame(time_sec, image, numbers)
    finally:
        cap.release()
