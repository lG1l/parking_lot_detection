"""영상을 분석 프레임(샘플링 fps)만 골라 내준다 (D-198, D-282)."""

from collections.abc import Iterable, Iterator
from dataclasses import dataclass

import cv2
import numpy as np

# 샘플링 fps. 01장 1.6 "샘플링 fps" (시작값, 영상 전체 동일)
SAMPLING_FPS = 10

# 시각을 소수로 다루다 생기는 오차를 흡수하는 값 (초)
_TIME_EPS = 1e-6


@dataclass
class AnalysisFrame:
    index: int  # 분석 프레임 번호 (0부터)
    time_sec: float  # 그 프레임의 실제 영상 시각
    image: np.ndarray  # BGR 화면


def select_by_time(frame_times: Iterable[float], fps: float = SAMPLING_FPS) -> Iterator[int]:
    """프레임 시각 목록에서 분석 프레임의 위치(0부터)를 차례로 고른다.

    k번째 분석 프레임은 시각이 k / fps 이상인 첫 프레임이다 (D-282).
    프레임 번호로 고르면 가변 프레임 속도 영상에서 시각이 밀리기 때문이다.
    """
    next_k = 0
    for position, t in enumerate(frame_times):
        if t + _TIME_EPS >= next_k / fps:
            yield position
            # 프레임 간격이 목표 간격보다 길어 목표를 건너뛰었으면 같이 넘긴다
            next_k = int((t + _TIME_EPS) * fps) + 1


def _grab_times(cap: cv2.VideoCapture) -> Iterator[float]:
    """프레임을 하나씩 넘기며 그 시각(초)을 내준다."""
    # grab()은 프레임을 읽기만 하고 화면 변환은 하지 않는다. 고르지 않은 프레임은 변환을 아낀다.
    while cap.grab():
        yield cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0


def iter_analysis_frames(path: str, fps: float = SAMPLING_FPS) -> Iterator[AnalysisFrame]:
    """영상을 한 번 읽으면서 분석 프레임만 내준다."""
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise FileNotFoundError(f"영상을 열 수 없습니다: {path}")
    try:
        # select_by_time이 프레임을 고른 순간 cap은 그 프레임에 멈춰 있다
        for index, _ in enumerate(select_by_time(_grab_times(cap), fps)):
            ok, image = cap.retrieve()
            if not ok:
                break
            yield AnalysisFrame(index, cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0, image)
    finally:
        cap.release()


if __name__ == "__main__":
    import sys

    count = 0
    first = last = 0.0
    for frame in iter_analysis_frames(sys.argv[1]):
        if count == 0:
            first = frame.time_sec
        last = frame.time_sec
        count += 1
    print(f"분석 프레임 {count}장, 처음 {first:.3f}초, 마지막 {last:.3f}초")
