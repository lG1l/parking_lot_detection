"""6단계 확인용 영상: 5-나 확인용 영상 위에 지금 후보, 유력 시점, 파손 지점을 덧그리고 아래에 시간 띠를 붙인다 (D-333 가-5).

5-나 영상을 한 프레임씩 읽어 그 위에 그리므로 앞 단계 표시가 그대로 남는다.
기존 시간 막대는 화면을 덮어쓴 그림이라 줄을 끼울 수 없다. 그래서 영상 아래에 새 띠를 덧붙여 높이를 늘린다.
"""

import math
from dataclasses import dataclass

import cv2
import numpy as np

from pipeline.candidates.candidate_clips import Clip
from pipeline.candidates.crop import Point
from pipeline.candidates.filter_preview import (
    _HEADLINE_POS,
    _LINE_GAP,
    Label,
    PreviewError,
    analysis_times,
)
from pipeline.candidates.motion_preview import (
    _BAR_MIN_W,
    _BAR_ROW_GAP,
    _BAR_ROW_H,
    DARK,
    YELLOW,
    _bar_x,
)
from pipeline.candidates.preview import GREEN, ORANGE, RED, WHITE, draw_labels
from pipeline.candidates.video import SAMPLING_FPS

_CLIP_POS = (_HEADLINE_POS[0], _HEADLINE_POS[1] + _LINE_GAP)  # 5-나 "바닥 지도 믿음" 줄 바로 아래
_MOMENT_LINE = 5  # 유력 시점 테두리 굵기
_DAMAGE_RADIUS = 6  # 파손 지점 원의 반지름
_DAMAGE_LINE = 2  # 파손 지점에서 트랙까지의 선
_LABEL_GAP = 6  # 사각형 오른쪽 변과 "유력 시점" 글 사이

_STRIP_PAD = 10  # 띠의 위아래 여백
_STRIP_ROWS = 3  # 후보 구간 한 줄, 클립 두 줄
_STRIP_ROW_BG = (70, 70, 70)
_TICK_W = 1  # 유력 시점 눈금 폭
_NOW_W = 3  # 지금 시각 세로선 폭


@dataclass(frozen=True)
class MomentMark:
    """유력 시점 프레임에 그릴 것."""

    text: str  # 거리와 단위. 예: "1.82m", "143px"
    to_damage: bool  # 파손 지점까지 선을 긋는지. 화면 거리로 잰 트랙은 긋지 않는다


def clock(sec: float) -> str:
    """초 → "분:초". 예: 65.2 → "1:05"."""
    return f"{int(sec // 60)}:{int(sec % 60):02d}"


def clip_text(t: float, clips: list[Clip]) -> str:
    """지금 시각이 든 후보를 한 줄로. 이웃 클립이 겹치는 5초 동안에는 둘 다 쓴다."""
    now = [
        f"후보 {i}/{len(clips)} · {clock(clip.start_sec)}~{clock(clip.end_sec)}"
        for i, clip in enumerate(clips, 1)
        if clip.start_sec <= t <= clip.end_sec
    ]
    return " / ".join(now) if now else "후보 없음"


def _row_y(row: int) -> int:
    return _STRIP_PAD + row * (_BAR_ROW_H + _BAR_ROW_GAP)


def _strip_height() -> int:
    return _row_y(_STRIP_ROWS - 1) + _BAR_ROW_H + _STRIP_PAD


def _fill(strip: np.ndarray, start: float, end: float, row: int, duration: float, color) -> None:
    x1 = _bar_x(start, duration, strip.shape[1])
    # 한 장짜리 구간도 보이게 최소 폭을 준다
    x2 = max(_bar_x(end, duration, strip.shape[1]), x1 + _BAR_MIN_W)
    cv2.rectangle(strip, (x1, _row_y(row)), (x2, _row_y(row) + _BAR_ROW_H), color, -1)


def make_strip(
    width: int, duration: float, clips: list[Clip], moment_times: list[float]
) -> np.ndarray:
    """영상 아래에 붙일 시간 띠. 가로 위치는 기존 시간 막대와 같은 계산(_bar_x)이라 위아래로 맞는다.

    첫 줄 = 후보 구간(주황)과 유력 시점(흰 눈금), 둘째·셋째 줄 = 클립(초록).
    클립을 두 줄에 번갈아 그려 이웃 클립이 겹친 5초가 보이게 한다.
    """
    strip = np.full((_strip_height(), width, 3), DARK, dtype=np.uint8)
    for row in range(_STRIP_ROWS):
        _fill(strip, 0.0, duration, row, duration, _STRIP_ROW_BG)
    for i, clip in enumerate(clips):
        _fill(strip, clip.start_sec, clip.end_sec, 1 + i % 2, duration, GREEN)
        for start, end in clip.motion_ranges:
            _fill(strip, start, end, 0, duration, ORANGE)
    # 눈금은 주황 위에 그려야 보인다
    for t in moment_times:
        x = _bar_x(t, duration, width)
        cv2.line(strip, (x, _row_y(0)), (x, _row_y(0) + _BAR_ROW_H), WHITE, _TICK_W)
    return strip


def _with_now(strip: np.ndarray, t: float, duration: float) -> np.ndarray:
    """지금 시각의 흰 세로선을 그은 띠 (새 그림)."""
    out = strip.copy()
    x = _bar_x(t, duration, out.shape[1])
    cv2.line(out, (x, 0), (x, out.shape[0] - 1), WHITE, _NOW_W)
    return out


def _draw_moment(
    image: np.ndarray, bbox: list[float], mark: MomentMark, damage_points: list[Point]
) -> Label:
    """유력 시점 프레임의 트랙에 굵은 노란 테두리와 파손 지점까지의 선을 그리고, 쓸 글을 돌려준다."""
    x1, y1, x2, y2 = (int(v) for v in bbox)
    cv2.rectangle(image, (x1, y1), (x2, y2), YELLOW, _MOMENT_LINE)
    if mark.to_damage and damage_points:
        foot = ((x1 + x2) // 2, y2)
        near = min(damage_points, key=lambda p: math.dist(p, foot))
        cv2.line(image, (int(near[0]), int(near[1])), foot, RED, _DAMAGE_LINE)
    return (f"유력 시점 {mark.text}", (x2 + _LABEL_GAP, y1), YELLOW)


def make_candidate_preview(
    video_path: str,
    source_video: str,
    out_video: str,
    by_time: dict[float, list[dict]],
    clips: list[Clip],
    marks: dict[tuple[float, int], MomentMark],
    damage_points: list[Point],
    duration: float,
) -> int:
    """5-나 확인용 영상(source_video)에 6단계 표시를 더해 out_video로 쓴다. 쓴 프레임 수를 돌려준다.

    marks의 키는 (유력 시점의 시각, 트랙 번호)다. damage_points는 파손 지점(화면)이다.
    """
    times = analysis_times(video_path)
    cap = cv2.VideoCapture(source_video)
    if not cap.isOpened():
        raise FileNotFoundError(f"5-나 확인용 영상을 열 수 없습니다: {source_video}")
    try:
        count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        # 프레임 수가 다르면 프레임과 시각의 짝이 밀려 엉뚱한 프레임에 그리게 된다
        if count != len(times):
            raise PreviewError(
                f"5-나 확인용 영상의 프레임 수({count})가 원본 영상의 분석 프레임 수({len(times)})와 "
                f"다릅니다: {source_video}"
            )
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        strip = make_strip(width, duration, clips, [t for t, _ in marks])
        size = (width, height + strip.shape[0])
        writer = cv2.VideoWriter(out_video, cv2.VideoWriter_fourcc(*"mp4v"), SAMPLING_FPS, size)
        for time_sec in times:
            ok, image = cap.read()
            if not ok:
                raise PreviewError(f"5-나 확인용 영상을 끝까지 읽지 못했습니다: {source_video}")
            for x, y in damage_points:
                cv2.circle(image, (int(x), int(y)), _DAMAGE_RADIUS, RED, -1)
            labels: list[Label] = [(clip_text(time_sec, clips), _CLIP_POS, DARK)]
            # 트랙 줄의 t는 소수 셋째 자리까지라 같은 자리로 맞춰 찾는다 (04장 4.8)
            for line in by_time.get(round(time_sec, 3), []):
                mark = marks.get((line["t"], line["track_id"]))
                if mark is not None:
                    labels.append(_draw_moment(image, line["bbox"], mark, damage_points))
            image = draw_labels(image, labels)
            writer.write(np.vstack([image, _with_now(strip, time_sec, duration)]))
        writer.release()
    finally:
        cap.release()
    return len(times)
