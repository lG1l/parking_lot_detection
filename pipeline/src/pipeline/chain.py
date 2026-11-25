"""영상 하나와 입력 JSON 하나로 1~9단계의 명령을 차례로 돈다 (10-가, D-359). 명령의 진입점이다.

실행 (pipeline/ 폴더에서. --env-file이 .env의 LLM_API_KEY를 환경변수로 넣어 준다):
    uv run --env-file .env python -m pipeline.chain <영상> <입력 JSON> <YOLO 가중치> <비식별화 모델 폴더> <출력 폴더>

작업 셋을 차례로 돈다: 정지 장면 → 후보 탐지 + VLM → 상위 후보 가리기.
큐·DB 없이 출력 폴더 아래 단계별 폴더에 파일만 쓴다 (가-6).
어느 단계든 오류가 나면 그 자리에서 멈춘다. 이어서 하기는 없고 다시 돌리면 처음부터 한다 (가-5, 가-8).
"""

import json
import os
import sys

import openai

from pipeline.candidates.s1_base.crop import CropError
from pipeline.candidates.s1_base.inputs import InputError
from pipeline.candidates.s1_base.roi import RoiError
from pipeline.candidates.s3_tracks.channel_a import ModelError
from pipeline.candidates.s3_tracks.track_preview import make_track_preview
from pipeline.candidates.s4_filter.filter_preview import PreviewError
from pipeline.candidates.s4_filter.track_filter import run_track_filter
from pipeline.candidates.s5_clips.candidate_list import run_candidate_list
from pipeline.deidentify.clips import ClipError
from pipeline.deidentify.detect import DetectError, run_detect
from pipeline.deidentify.mask import MaskError, run_mask
from pipeline.deidentify.track import TrackError, run_track
from pipeline.still import StillError, run_still
from pipeline.vlm.call import CallError
from pipeline.vlm.score import SCORES_NAME, run_score

# 처음에 준비하는 후보 클립 수 (01장 1.6). 후보군 목록·파싱 실패 목록 각각이다 (D-68, D-93)
READY_CLIPS = 20

# 출력 폴더 아래의 단계별 폴더 (가-6). 가린 클립만 든 폴더와 가리기 전 화면이 든 폴더를 나눈다
DIR_STILL = "1_still"
DIR_TRACKS = "2_tracks"
DIR_FILTER = "3_filter"
DIR_CANDIDATES = "4_candidates"
DIR_SCORES = "5_scores"
DIR_DEID = "6_deid"
DIR_CLIPS = "7_clips"

# 앞 단계가 쓰고 뒤 단계가 읽는 파일의 이름 (04장 4.8)
CANDIDATES_NAME = "candidates.jsonl"
DEID_BOXES_NAME = "deid_boxes.jsonl"
MASK_BOXES_NAME = "mask_boxes.jsonl"

# 비식별화 모델을 여는 함수가 켜는 torch 환경 변수 (deidentify/detect.py의 load_detector)
WEIGHTS_ONLY_ENV = "TORCH_FORCE_WEIGHTS_ONLY_LOAD"

# 여덟 명령의 진입점이 각자 잡던 오류를 모았다. 이 밖의 오류는 버그라 잡지 않는다
CHAIN_ERRORS = (
    InputError,
    CropError,
    RoiError,
    ModelError,
    PreviewError,
    StillError,
    ClipError,
    DetectError,
    TrackError,
    MaskError,
    CallError,
    FileNotFoundError,
)


def _allow_yolo_load() -> None:
    """비식별화 모델을 연 뒤에 부른다. 다음에 여는 YOLO 가중치가 읽히게 한다.

    비식별화 모델을 여는 함수(load_detector)는 "텐서만 읽기" 환경 변수를 켜고 끄지 않는다.
    명령을 따로 돌릴 때는 프로세스가 끝나 문제가 없었지만, 한 프로세스에서 이으면
    그 뒤에 여는 YOLO 가중치(모델 구조가 함께 든 파일)가 읽히지 않는다.
    """
    os.environ.pop(WEIGHTS_ONLY_ENV, None)


def run_still_job(video_path: str, weights_path: str, model_dir: str, out_dir: str) -> None:
    """작업 1: 정지 장면. 입력 JSON 없이 돈다 (실제 서비스에서는 입력보다 먼저다)."""
    run_still(video_path, weights_path, model_dir, os.path.join(out_dir, DIR_STILL))
    _allow_yolo_load()


def run_analysis_job(video_path: str, input_path: str, weights_path: str, out_dir: str) -> None:
    """작업 2: 후보 탐지(트랙 → 트랙 빼기 → 후보 목록) 뒤에 VLM 점수를 매긴다."""
    tracks_dir = os.path.join(out_dir, DIR_TRACKS)
    filter_dir = os.path.join(out_dir, DIR_FILTER)
    candidates_dir = os.path.join(out_dir, DIR_CANDIDATES)
    make_track_preview(video_path, input_path, weights_path, tracks_dir, None)
    # 3·4의 확인용 영상은 6단계에서 본 것과 같아 만들지 않는다 (가-2)
    run_track_filter(video_path, input_path, tracks_dir, filter_dir, make_video=False)
    run_candidate_list(
        video_path, input_path, filter_dir, candidates_dir, scenes_path=None, make_video=False
    )
    run_score(
        video_path,
        input_path,
        os.path.join(candidates_dir, CANDIDATES_NAME),
        os.path.join(out_dir, DIR_SCORES),
    )


def read_scores(out_dir: str) -> list[dict]:
    """점수 파일의 줄 목록. 줄 순서가 후보 번호순이다 (첫 줄 = 후보 1)."""
    with open(os.path.join(out_dir, DIR_SCORES, SCORES_NAME)) as f:
        return [json.loads(line) for line in f if line.strip()]


def pick_top_candidates(score_rows: list[dict], top_n: int) -> list[int]:
    """가린 클립을 만들 후보 번호를 오름차순으로 준다 (가-3).

    rank는 목록(후보군·파싱 실패)마다 1부터라, rank만 보면 두 목록 각각의 상위 top_n개가 된다.
    """
    return [number for number, row in enumerate(score_rows, start=1) if row["rank"] <= top_n]


def run_masking_job(
    video_path: str, input_path: str, model_dir: str, out_dir: str, numbers: list[int]
) -> None:
    """작업 3: 고른 후보의 얼굴·번호판 탐지 → 추적 → 가린 클립."""
    candidates_path = os.path.join(out_dir, DIR_CANDIDATES, CANDIDATES_NAME)
    deid_dir = os.path.join(out_dir, DIR_DEID)
    boxes_path = os.path.join(deid_dir, DEID_BOXES_NAME)
    mask_boxes_path = os.path.join(deid_dir, MASK_BOXES_NAME)
    # 기존 명령은 후보 번호를 "1,2,3" 꼴의 글로 받는다
    numbers_text = ",".join(str(n) for n in numbers)
    run_detect(video_path, input_path, candidates_path, model_dir, deid_dir, numbers_text)
    _allow_yolo_load()
    run_track(video_path, model_dir, boxes_path, mask_boxes_path)
    run_mask(
        video_path,
        input_path,
        candidates_path,
        mask_boxes_path,
        os.path.join(out_dir, DIR_CLIPS),
        numbers_text,
    )


def run_chain(
    video_path: str, input_path: str, weights_path: str, model_dir: str, out_dir: str
) -> None:
    """작업 셋을 차례로 돈다. 오류는 잡지 않고 그대로 올린다."""
    print("[1/3] 정지 장면")
    run_still_job(video_path, weights_path, model_dir, out_dir)
    print("[2/3] 후보 탐지 + VLM")
    run_analysis_job(video_path, input_path, weights_path, out_dir)
    numbers = pick_top_candidates(read_scores(out_dir), READY_CLIPS)
    if not numbers:
        # 탐지 명령은 후보가 없으면 파일을 쓰지 않아 추적 명령이 죽는다. 후보 0개는 오류가 아니다 (가-4)
        print("후보 없음. 가린 클립을 만들지 않고 끝낸다")
        return
    print(f"[3/3] 상위 후보 가리기: 후보 {numbers}")
    run_masking_job(video_path, input_path, model_dir, out_dir, numbers)


def main(args: list[str]) -> int:
    """명령 인자 5개를 받아 돌리고 종료 코드를 준다."""
    if len(args) != 5:
        print(
            "사용법: python -m pipeline.chain"
            " <영상> <입력 JSON> <YOLO 가중치> <비식별화 모델 폴더> <출력 폴더>"
        )
        return 2
    try:
        run_chain(*args)
    except CHAIN_ERRORS as e:
        # 뒤 단계를 부르지 않고 멈춘다. 이미 쓴 파일은 지우지 않는다 (가-5)
        print(f"오류: {e}")
        return 1
    except openai.APIError as e:
        # 인증 실패·한도·서버 장애·타임아웃. VLM이 실패하면 가린 클립은 없다 (06장 6.12)
        print(f"오류: API 호출 실패 — {type(e).__name__}: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
