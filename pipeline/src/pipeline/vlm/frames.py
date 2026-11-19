"""후보 클립마다 VLM에 넣을 프레임을 1초에 1장씩 뽑아 분석 크롭으로 자른다 (D-342). 명령의 진입점이다.

실행 (pipeline/ 폴더에서):
    uv run python -m pipeline.vlm.frames <영상> <입력 JSON> <candidates.jsonl> <출력 폴더>

이미지로 저장하는 것은 눈 확인용이다. VLM 호출 쪽(7-나)은 저장한 이미지를 읽지 않고
iter_candidate_frames를 불러 받은 프레임을 바로 요청에 넣는다 (D-342 가-6).
저장하는 프레임은 비식별화하지 않은 원본 크롭이라 local_storage/ 밖으로 내보내지 않는다 (불변 조건 3).
"""

import json
import os
import sys
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field

import cv2
import numpy as np

from pipeline.candidates.s1_base.crop import CropError
from pipeline.candidates.s1_base.inputs import AnalysisInput, Bbox, InputError, Point, load_input
from pipeline.candidates.s1_base.preview import video_size
from pipeline.candidates.s1_base.roi import RoiError, build_roi
from pipeline.candidates.s1_base.video import iter_analysis_frames

# 프레임 간격 (초). 클립 처음부터 끝까지 통일한다. 임시이고 13-가에서 다시 정한다 (D-342 가-1)
FRAME_INTERVAL_SEC = 1.0

# 확인용 저장의 JPEG 품질 (D-342 가-4)
JPEG_QUALITY = 95

# 안내 프레임의 테두리 (BGR, D-342 가-5)
MAGENTA = (255, 0, 255)  # 파손 위치 사각형
LIME = (0, 255, 0)  # 바닥 네 모서리
_GUIDE_LINE = 2

# 시각을 소수로 다루다 생기는 오차를 흡수하는 값 (초)
_TIME_EPS = 1e-6

Rect = tuple[int, int, int, int]  # x1, y1, x2, y2 (원본 픽셀)


@dataclass
class VlmFrame:
    number: int  # 클립 안에서의 순번 (1부터)
    time_sec: float  # 프레임의 실제 시각 (원본 시간, 초)
    image: np.ndarray  # 분석 크롭으로 자른 BGR 화면 (줄이지 않는다)


@dataclass
class CandidateFrames:
    number: int  # 후보 번호 (candidates.jsonl의 줄 순서, 1부터)
    start_sec: float
    end_sec: float
    guide: np.ndarray | None = None  # 안내 프레임. 프레임이 한 장도 없으면 None
    frames: list[VlmFrame] = field(default_factory=list)


class ClipPicker:
    """클립 하나에서 다음에 고를 목표 시각을 기억한다.

    목표 시각은 start + 0초, 1초, 2초 … 이고 end보다 작은 동안이다 (D-342 가-2).
    """

    def __init__(self, start_sec: float, end_sec: float):
        self.start_sec = start_sec
        self.end_sec = end_sec
        self._k = 0  # 다음 목표 시각의 순서

    def done(self) -> bool:
        """더 고를 목표 시각이 없는지."""
        return self.start_sec + self._k * FRAME_INTERVAL_SEC >= self.end_sec - _TIME_EPS

    def take(self, time_sec: float) -> bool:
        """이 시각의 프레임을 골라야 하는지. 고르면 다음 목표로 넘어간다.

        목표 시각 이상인 첫 프레임을 고른다. 프레임 번호로 고르면
        프레임이 빠진 영상에서 시각이 밀리기 때문이다 (D-300과 같은 방식).
        """
        target = self.start_sec + self._k * FRAME_INTERVAL_SEC
        if self.done() or time_sec + _TIME_EPS < target:
            return False
        # 프레임 간격이 목표 간격보다 길어 목표를 건너뛰었으면 같이 넘긴다
        self._k = int((time_sec + _TIME_EPS - self.start_sec) / FRAME_INTERVAL_SEC) + 1
        return True


def pick_times(frame_times: Iterable[float], start_sec: float, end_sec: float) -> list[float]:
    """분석 프레임 시각 목록에서 클립 하나에 넣을 프레임의 시각을 고른다."""
    picker = ClipPicker(start_sec, end_sec)
    return [t for t in frame_times if picker.take(t)]


def to_crop_point(point: Point, crop_rect: Rect) -> Point:
    """원본 픽셀 좌표를 크롭 안 좌표로 바꾼다."""
    return (point[0] - crop_rect[0], point[1] - crop_rect[1])


def to_crop_bbox(bbox: Bbox, crop_rect: Rect) -> Bbox:
    x1, y1 = to_crop_point((bbox[0], bbox[1]), crop_rect)
    x2, y2 = to_crop_point((bbox[2], bbox[3]), crop_rect)
    return (x1, y1, x2, y2)


def make_guide(image: np.ndarray, data: AnalysisInput, crop_rect: Rect) -> np.ndarray:
    """크롭한 프레임을 복사해 파손 위치 사각형과 바닥 네 모서리를 그린 안내 프레임을 만든다.

    복사본에 그리는 이유: 판정 프레임은 테두리가 물체를 가리지 않게 깨끗하게 둔다 (D-342 가-5).
    """
    guide = image.copy()
    x1, y1, x2, y2 = to_crop_bbox(data.damage_bbox, crop_rect)
    cv2.rectangle(guide, (x1, y1), (x2, y2), MAGENTA, _GUIDE_LINE)
    corners = np.array([to_crop_point(p, crop_rect) for p in data.floor_corners], dtype=np.int32)
    cv2.polylines(guide, [corners], True, LIME, _GUIDE_LINE)
    return guide


def load_clips(candidates_path: str) -> list[tuple[float, float]]:
    """후보 목록 파일에서 클립의 (시작, 끝) 시각을 줄 순서대로 읽는다 (04장 4.8)."""
    clips = []
    with open(candidates_path, encoding="utf-8") as f:
        for text in f:
            if text.strip():
                line = json.loads(text)
                clips.append((line["start_sec"], line["end_sec"]))
    return clips


def iter_candidate_frames(
    video_path: str, input_path: str, candidates_path: str
) -> Iterator[CandidateFrames]:
    """영상을 한 번 읽으며 후보마다 안내 프레임과 판정 프레임을 후보 번호순으로 내준다.

    한꺼번에 돌려주지 않고 후보가 끝날 때마다 내준다. 줄이지 않은 프레임 수백 장을
    메모리에 다 쥐고 있지 않기 위해서다.
    """
    width, height = video_size(video_path)
    data = load_input(input_path, width, height)
    crop_rect = build_roi(data, (width, height)).crop.rect
    x1, y1, x2, y2 = crop_rect

    clips = load_clips(candidates_path)
    pickers = [ClipPicker(start, end) for start, end in clips]
    results = [CandidateFrames(i + 1, start, end) for i, (start, end) in enumerate(clips)]
    sent = 0  # 이미 내준 후보 수

    for frame in iter_analysis_frames(video_path):
        if sent == len(results):
            break  # 마지막 클립까지 끝났으면 영상을 더 읽지 않는다
        for picker, result in zip(pickers[sent:], results[sent:]):
            if not picker.take(frame.time_sec):
                continue
            # 복사하지 않으면 잘라낸 조각이 원본 화면 전체를 메모리에 붙잡아 둔다
            image = frame.image[y1:y2, x1:x2].copy()
            if not result.frames:
                result.guide = make_guide(image, data, crop_rect)
            result.frames.append(VlmFrame(len(result.frames) + 1, frame.time_sec, image))
        while sent < len(results) and pickers[sent].done():
            yield results[sent]
            sent += 1
    # 영상이 먼저 끝나면 거기까지 뽑은 것만 내준다
    yield from results[sent:]


def save_candidate(out_dir: str, candidate: CandidateFrames) -> str:
    """후보 하나의 안내 프레임과 판정 프레임을 눈 확인용 이미지로 저장하고 폴더 경로를 돌려준다."""
    folder = os.path.join(out_dir, f"c{candidate.number:02d}")
    os.makedirs(folder, exist_ok=True)
    quality = [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY]
    cv2.imwrite(os.path.join(folder, "guide.jpg"), candidate.guide, quality)
    for frame in candidate.frames:
        # 이름순 = 시간순이 되게 순번을 두 자리로 쓴다
        name = f"f{frame.number:02d}_t{frame.time_sec:.1f}.jpg"
        cv2.imwrite(os.path.join(folder, name), frame.image, quality)
    return folder


def run_frames(video_path: str, input_path: str, candidates_path: str, out_dir: str) -> None:
    count = total = 0
    for candidate in iter_candidate_frames(video_path, input_path, candidates_path):
        count += 1
        label = f"후보 {candidate.number} · {candidate.start_sec:g}~{candidate.end_sec:g}초"
        if not candidate.frames:
            print(f"{label} · 프레임 없음 (영상이 클립 시작보다 먼저 끝났다)")
            continue
        folder = save_candidate(out_dir, candidate)
        total += len(candidate.frames)
        print(f"{label} · {len(candidate.frames)}장 → {folder}")
    print(f"후보 {count}개, 판정 프레임 합계 {total}장")


if __name__ == "__main__":
    if len(sys.argv) != 5:
        print(
            "사용법: python -m pipeline.vlm.frames <영상> <입력 JSON> <candidates.jsonl> <출력 폴더>"
        )
        sys.exit(2)
    try:
        run_frames(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4])
    except (InputError, CropError, RoiError, FileNotFoundError) as e:
        print(f"오류: {e}")
        sys.exit(1)
