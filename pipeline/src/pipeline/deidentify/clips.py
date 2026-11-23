"""후보 클립을 보여줄 크롭으로 잘라 H.264 MP4로 만든다 (D-345).

여기서 만드는 클립은 가리기 전(비식별화하지 않은 원본 크롭)이다.
local_storage/ 밖으로 내보내지 않는다 (불변 조건 3).

실행 (pipeline/ 폴더에서):
    uv run python -m pipeline.deidentify.clips <영상> <입력 JSON> <candidates.jsonl> <출력 폴더>

8-나(얼굴·번호판 탐지)와 8-다(모자이크 클립)가 이 파일의 함수를 불러 쓴다.
"""

import os
import shutil
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import dataclass

import cv2
import numpy as np

from pipeline.candidates.s1_base.crop import CropError
from pipeline.candidates.s1_base.inputs import InputError, load_input
from pipeline.candidates.s1_base.preview import video_size
from pipeline.candidates.s1_base.roi import RoiError, build_roi
from pipeline.vlm.frames import load_clips

# 시각을 소수로 다루다 생기는 오차를 흡수하는 값 (초)
_TIME_EPS = 1e-6

Rect = tuple[int, int, int, int]  # x1, y1, x2, y2 (원본 픽셀)
Clip = tuple[float, float]  # 클립의 (시작, 끝) 시각 (초)


class ClipError(Exception):
    """ffmpeg가 없거나 인코딩에 실패했을 때."""


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


def video_fps(video_path: str) -> float:
    """영상의 평균 프레임 속도 (초당 장 수)."""
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise FileNotFoundError(f"영상을 열 수 없습니다: {video_path}")
    fps = cap.get(cv2.CAP_PROP_FPS)
    cap.release()
    return fps


class H264Writer:
    """ffmpeg를 따로 띄워 프레임을 하나씩 넘겨 H.264 MP4 파일 하나를 쓴다 (D-345 가-5).

    프레임이 Python을 거쳐 가므로 8-다는 넘기기 전에 모자이크만 씌우면 된다.
    소리는 ffmpeg가 원본 영상에서 같은 구간을 직접 읽어 붙인다 (가-6).
    """

    def __init__(
        self, out_path: str, size: tuple[int, int], fps: float, video_path: str, clip: Clip
    ):
        if shutil.which("ffmpeg") is None:
            raise ClipError("ffmpeg 명령을 찾을 수 없습니다. ffmpeg를 설치해야 합니다")
        start_sec, end_sec = clip
        command = [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            # 첫 번째 입력: 가공하지 않은 BGR 프레임이 이 크기·이 속도로 표준 입력에 들어온다
            "-f",
            "rawvideo",
            "-pix_fmt",
            "bgr24",
            "-s",
            f"{size[0]}x{size[1]}",
            "-r",
            f"{fps}",
            "-i",
            "-",
            # 두 번째 입력: 원본 영상의 start_sec부터 클립 길이만큼. 여기서는 소리만 가져온다
            "-ss",
            f"{start_sec}",
            "-t",
            f"{end_sec - start_sec}",
            "-i",
            video_path,
            "-map",
            "0:v",
            # 끝의 ?는 "있으면"이다. 원본에 소리가 없으면 화면만 있는 클립이 된다
            "-map",
            "1:a?",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            # 재생 정보를 파일 앞에 둔다. 웹에서 파일을 다 받기 전에 재생이 시작된다
            "-movflags",
            "+faststart",
            out_path,
        ]
        self._process = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=subprocess.PIPE)

    def write(self, image: np.ndarray) -> None:
        """프레임 한 장을 ffmpeg에 넘긴다. image의 크기는 만들 때 준 size와 같아야 한다."""
        try:
            self._process.stdin.write(image.tobytes())
        except BrokenPipeError:
            self.close()  # ffmpeg가 먼저 죽었다. close가 ffmpeg의 오류 글을 담아 알린다
            raise

    def close(self) -> None:
        """입력을 닫아 ffmpeg가 파일을 마무리하게 하고 끝나기를 기다린다."""
        _, error_text = self._process.communicate()
        if self._process.returncode != 0:
            raise ClipError(f"ffmpeg 실패 — {error_text.decode(errors='replace').strip()}")


def run_clips(video_path: str, input_path: str, candidates_path: str, out_dir: str) -> None:
    """후보마다 가리기 전 클립 c01.mp4, c02.mp4 … 를 쓴다 (D-345 가-7)."""
    width, height = video_size(video_path)
    data = load_input(input_path, width, height)
    x1, y1, x2, y2 = even_rect(build_roi(data, (width, height)).display.rect)
    size = (x2 - x1, y2 - y1)
    fps = video_fps(video_path)

    clips = load_clips(candidates_path)
    if not clips:
        print("후보 0개")
        return
    os.makedirs(out_dir, exist_ok=True)

    writers: dict[int, H264Writer] = {}  # 지금 쓰고 있는 클립 (번호 → ffmpeg)
    counts = [0] * len(clips)  # 클립마다 넣은 프레임 수
    for frame in iter_clip_frames(video_path, clips):
        # 이 프레임이 들어가지 않는 클립은 끝난 것이다. 닫아서 파일을 마무리한다
        for number in [n for n in writers if n not in frame.clip_numbers]:
            writers.pop(number).close()
        cropped = frame.image[y1:y2, x1:x2]
        for number in frame.clip_numbers:
            if number not in writers:
                out_path = os.path.join(out_dir, f"c{number:02d}.mp4")
                writers[number] = H264Writer(out_path, size, fps, video_path, clips[number - 1])
            writers[number].write(cropped)
            counts[number - 1] += 1
    for writer in writers.values():
        writer.close()

    for number, ((start, end), count) in enumerate(zip(clips, counts), start=1):
        label = f"후보 {number} · {start:g}~{end:g}초"
        if count == 0:
            print(f"{label} · 프레임 없음 (영상이 클립 시작보다 먼저 끝났다)")
        else:
            print(f"{label} · {count}장 → {os.path.join(out_dir, f'c{number:02d}.mp4')}")
    print(f"후보 {len(clips)}개, 클립 크기 {size[0]}×{size[1]}, 초당 {fps:.3f}장")


if __name__ == "__main__":
    if len(sys.argv) != 5:
        print(
            "사용법: python -m pipeline.deidentify.clips"
            " <영상> <입력 JSON> <candidates.jsonl> <출력 폴더>"
        )
        sys.exit(2)
    try:
        run_clips(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4])
    except (InputError, CropError, RoiError, ClipError, FileNotFoundError) as e:
        print(f"오류: {e}")
        sys.exit(1)
