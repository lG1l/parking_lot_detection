"""후보 1개로 학교 대체 LLM API를 한 번 불러 점수와 근거를 받아 출력한다 (D-343). 명령의 진입점이다.

실행 (pipeline/ 폴더에서. --env-file이 .env의 LLM_API_KEY를 환경변수로 넣어 준다):
    uv run --env-file .env python -m pipeline.vlm.call <영상> <입력 JSON> <candidates.jsonl> <후보 번호>

한 번만 보낸다. 재시도·재호출은 7-다 몫이다 (D-343 나-9). 파일은 만들지 않는다.
보내는 프레임은 비식별화하지 않은 원본 크롭이라 학교 대체 LLM API로만 보낸다 (불변 조건 3).
"""

import json
import os
import sys

import openai

from pipeline.candidates.s1_base.crop import CropError
from pipeline.candidates.s1_base.inputs import InputError, load_input
from pipeline.candidates.s1_base.preview import video_size
from pipeline.candidates.s1_base.roi import RoiError, build_roi
from pipeline.vlm.frames import CandidateFrames, iter_candidate_frames, load_clips
from pipeline.vlm.request import MODEL, SCORE_MAX, SCORE_MIN, build_request

# 학교 대체 LLM API의 주소. 비밀이 아니라 코드 상수로 둔다 (D-343 나-2)
BASE_URL = "https://bedrock.nxtcloud.kr/v1"

# 키를 읽는 환경변수 이름. 값은 팀장이 pipeline/.env에 직접 넣는다 (D-277)
KEY_ENV = "LLM_API_KEY"


class CallError(Exception):
    """호출을 시작할 수 없다 (키가 없다, 후보가 없다 등)."""


class FormatError(Exception):
    """응답이 점수 제출 도구의 형식을 따르지 않았다 (D-93)."""


def parse_score(response: dict) -> tuple[int, str]:
    """응답(딕셔너리)의 도구 호출 인자에서 (점수, 근거)를 꺼낸다. 형식이 틀리면 FormatError다."""
    choice = response["choices"][0]
    if choice.get("finish_reason") == "length":
        raise FormatError("응답이 길이 제한으로 잘렸다")
    tool_calls = choice["message"].get("tool_calls")
    if not tool_calls:
        raise FormatError("응답에 도구 호출이 없다")
    try:
        args = json.loads(tool_calls[0]["function"]["arguments"])
    except json.JSONDecodeError:
        raise FormatError("도구 호출의 인자가 JSON이 아니다") from None
    if not isinstance(args, dict) or "reason" not in args or "score" not in args:
        raise FormatError("도구 호출의 인자에 reason 또는 score가 없다")
    score, reason = args["score"], args["reason"]
    # type으로 보는 이유: isinstance는 True·False도 정수로 본다
    if type(score) is not int:
        raise FormatError(f"score가 정수가 아니다: {score!r}")
    if not SCORE_MIN <= score <= SCORE_MAX:
        raise FormatError(f"score가 {SCORE_MIN}~{SCORE_MAX} 밖이다: {score}")
    if not isinstance(reason, str):
        raise FormatError("reason이 글이 아니다")
    return score, reason


def find_candidate(
    video_path: str, input_path: str, candidates_path: str, number: int
) -> CandidateFrames:
    """그 번호의 후보가 나올 때까지만 영상을 읽는다."""
    for candidate in iter_candidate_frames(video_path, input_path, candidates_path):
        if candidate.number == number:
            if not candidate.frames:
                raise CallError(f"후보 {number}의 프레임이 없다 (영상이 클립 시작보다 먼저 끝났다)")
            return candidate
    raise CallError(f"후보 {number}가 없다")


def has_photo(input_path: str) -> bool:
    """입력에 파손 사진 키가 있는지만 본다. 사진 파일은 읽지 않는다 (D-343 나-10)."""
    with open(input_path, encoding="utf-8") as f:
        return bool(json.load(f).get("damage", {}).get("photo_key"))


def run_call(video_path: str, input_path: str, candidates_path: str, number: int) -> None:
    # 후보 번호와 키는 영상을 읽기 전에 본다. 틀린 입력으로 API를 부르지 않기 위해서다
    count = len(load_clips(candidates_path))
    if not 1 <= number <= count:
        raise CallError(f"후보 {number}가 없다 (후보는 1~{count}번이다)")
    key = os.environ.get(KEY_ENV)
    if not key:
        raise CallError(
            f"{KEY_ENV}가 없다. pipeline/.env에 넣고 'uv run --env-file .env …'로 실행한다"
        )

    width, height = video_size(video_path)
    data = load_input(input_path, width, height)
    crop_rect = build_roi(data, (width, height)).crop.rect
    candidate = find_candidate(video_path, input_path, candidates_path, number)
    if has_photo(input_path):
        print("파손 사진은 아직 넣지 않는다")
    request = build_request(candidate, data, crop_rect)

    # max_retries=0: SDK가 몰래 다시 보내지 않게 한다. 한 번만 보낸다 (D-343 나-9)
    client = openai.OpenAI(api_key=key, base_url=BASE_URL, max_retries=0)
    response = client.chat.completions.create(**request).model_dump()
    score, reason = parse_score(response)

    usage = response.get("usage") or {}
    print(
        f"후보 {candidate.number} · {candidate.start_sec:g}~{candidate.end_sec:g}초"
        f" · 판정 프레임 {len(candidate.frames)}장"
    )
    print(f"모델: {MODEL}")
    print(f"점수: {score}")
    print(f"근거: {reason}")
    print(f"토큰: 입력 {usage.get('prompt_tokens')} · 출력 {usage.get('completion_tokens')}")


if __name__ == "__main__":
    if len(sys.argv) != 5 or not sys.argv[4].isdigit():
        print(
            "사용법: python -m pipeline.vlm.call <영상> <입력 JSON> <candidates.jsonl> <후보 번호>"
        )
        sys.exit(2)
    try:
        run_call(sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4]))
    except (CallError, InputError, CropError, RoiError, FileNotFoundError) as e:
        print(f"오류: {e}")
        sys.exit(1)
    except FormatError as e:
        print(f"오류: 형식 오류 — {e}")
        sys.exit(1)
    except openai.APIError as e:
        # 인증 실패·요청 거절·한도·서버 장애·타임아웃이 모두 여기로 온다. 다시 보내지 않는다
        print(f"오류: API 호출 실패 — {type(e).__name__}: {e}")
        sys.exit(1)
