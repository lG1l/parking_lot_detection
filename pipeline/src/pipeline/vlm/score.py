"""후보 모두를 하나씩 불러 점수·근거·순위를 점수 파일(scores.jsonl)에 쓴다 (D-344). 명령의 진입점이다.

실행 (pipeline/ 폴더에서. --env-file이 .env의 LLM_API_KEY를 환경변수로 넣어 준다):
    uv run --env-file .env python -m pipeline.vlm.score <영상> <입력 JSON> <candidates.jsonl> <출력 폴더>

형식이 틀린 응답은 오류 글을 붙여 다시 부르고, 끝내 실패한 후보는 파싱 실패 목록으로 보낸다 (D-93).
API 오류가 나면 재시도 없이 멈추고 점수 파일을 쓰지 않는다 (D-344 다-4).
보내는 프레임은 비식별화하지 않은 원본 크롭이라 학교 대체 LLM API로만 보낸다 (불변 조건 3).
"""

import json
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass

import openai

from pipeline.candidates.s1_base.crop import CropError
from pipeline.candidates.s1_base.inputs import InputError, load_input
from pipeline.candidates.s1_base.preview import video_size
from pipeline.candidates.s1_base.roi import RoiError, build_roi
from pipeline.vlm.call import BASE_URL, KEY_ENV, CallError, FormatError, has_photo, parse_score
from pipeline.vlm.frames import iter_candidate_frames, load_clips
from pipeline.vlm.request import MODEL, build_request, with_format_error

# VLM 점수 형식 실패 시 최대 호출 수 (01장 1.6). 최초 호출을 포함한다
MAX_FORMAT_CALLS = 3

# 점수 파일의 이름 (04장 4.8)
SCORES_NAME = "scores.jsonl"

# list_kind의 값 (04장 candidates)
LIST_MAIN = "main"  # 점수가 나온 후보군 목록
LIST_PARSE_FAILED = "parse_failed"  # 끝내 형식이 틀린 파싱 실패 목록

# 요청(딕셔너리)을 보내 응답(딕셔너리)을 받는 함수. 테스트에서는 가짜를 넣는다
Send = Callable[[dict], dict]


@dataclass
class CandidateScore:
    score: int | None  # 끝내 실패하면 None. 0점을 주지 않는다 (D-93)
    reason: str | None
    calls: int  # 보낸 호출 수
    format_errors: int  # 그 가운데 형식 오류였던 수
    input_tokens: int = 0
    output_tokens: int = 0


def score_candidate(request: dict, send: Send, label: str = "") -> CandidateScore:
    """후보 1개를 최대 호출 수까지 부른다. 호출마다 한 줄을 출력한다."""
    result = CandidateScore(None, None, 0, 0)
    current = request
    for call_number in range(1, MAX_FORMAT_CALLS + 1):
        response = send(current)
        result.calls = call_number
        usage = response.get("usage") or {}
        result.input_tokens += usage.get("prompt_tokens") or 0
        result.output_tokens += usage.get("completion_tokens") or 0
        try:
            result.score, result.reason = parse_score(response)
        except FormatError as e:
            result.format_errors += 1
            print(f"{label} · 호출 {call_number} · 형식 오류: {e}")
            # 원래 요청에 붙인다. 가장 최근 오류 하나만 보내기 위해서다 (D-344 다-6)
            current = with_format_error(request, str(e))
            continue
        print(f"{label} · 호출 {call_number} · 점수 {result.score}")
        break
    return result


def rank_scores(
    clips: list[tuple[float, float]], scores: list[tuple[int | None, str | None]]
) -> list[dict]:
    """후보마다 점수 파일의 한 줄을 만든다. 돌려주는 순서는 후보 번호순 그대로다.

    후보군 목록은 점수 내림차순이고 동점은 임시로 start_sec 오름차순이다 (U-27 미정, D-344 다-3).
    파싱 실패 목록은 start_sec 오름차순이다 (D-177).
    """
    rows = []
    for (start, end), (score, reason) in zip(clips, scores):
        kind = LIST_PARSE_FAILED if score is None else LIST_MAIN
        rows.append(
            {
                "start_sec": start,
                "end_sec": end,
                "vlm_score": score,
                "list_kind": kind,
                "rank": 0,
                "reason": reason,
            }
        )
    main = [r for r in rows if r["list_kind"] == LIST_MAIN]
    failed = [r for r in rows if r["list_kind"] == LIST_PARSE_FAILED]
    main.sort(key=lambda r: (-r["vlm_score"], r["start_sec"]))
    failed.sort(key=lambda r: r["start_sec"])
    for ordered in (main, failed):
        for rank, row in enumerate(ordered, start=1):
            row["rank"] = rank
    return rows


def write_scores(out_dir: str, rows: list[dict]) -> str:
    """점수 파일을 쓰고 경로를 돌려준다. 후보가 없어도 빈 파일을 쓴다."""
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, SCORES_NAME)
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
    return path


def check_no_empty(video_path: str, input_path: str, candidates_path: str) -> None:
    """프레임이 빈 후보가 있으면 CallError를 낸다 (D-344 다-8).

    호출을 시작하기 전에 영상을 한 번 더 읽는다. 중간에 멈추면 그때까지 쓴 호출이 버려지기 때문이다.
    """
    empty = [
        candidate.number
        for candidate in iter_candidate_frames(video_path, input_path, candidates_path)
        if not candidate.frames
    ]
    if empty:
        raise CallError(
            f"프레임이 없는 후보가 있다 (영상이 클립 시작보다 먼저 끝났다): 후보 {empty}"
        )


def print_lists(rows: list[dict]) -> None:
    """후보군 목록과 파싱 실패 목록을 순위순으로 출력한다."""
    numbered = list(enumerate(rows, start=1))  # (후보 번호, 줄)
    for title, kind in (("후보군 목록", LIST_MAIN), ("파싱 실패 목록", LIST_PARSE_FAILED)):
        picked = sorted(
            (p for p in numbered if p[1]["list_kind"] == kind), key=lambda p: p[1]["rank"]
        )
        print(f"\n[{title}] {len(picked)}개")
        for number, row in picked:
            line = f"  {row['rank']}위 · 후보 {number} · {row['start_sec']:g}~{row['end_sec']:g}초"
            if kind == LIST_MAIN:
                line += f" · 점수 {row['vlm_score']} · 근거: {row['reason']}"
            print(line)


def run_score(video_path: str, input_path: str, candidates_path: str, out_dir: str) -> None:
    # 후보 목록과 키는 영상을 읽기 전에 본다. 틀린 입력으로 API를 부르지 않기 위해서다
    clips = load_clips(candidates_path)
    if not clips:
        print(f"후보가 없다. 빈 점수 파일을 쓴다 → {write_scores(out_dir, [])}")
        return
    key = os.environ.get(KEY_ENV)
    if not key:
        raise CallError(
            f"{KEY_ENV}가 없다. pipeline/.env에 넣고 'uv run --env-file .env …'로 실행한다"
        )

    width, height = video_size(video_path)
    data = load_input(input_path, width, height)
    crop_rect = build_roi(data, (width, height)).crop.rect
    check_no_empty(video_path, input_path, candidates_path)
    if has_photo(input_path):
        print("파손 사진은 아직 넣지 않는다")

    # max_retries=0: SDK가 몰래 다시 보내지 않게 한다. 장애가 나면 그대로 멈춘다 (D-344 다-4)
    client = openai.OpenAI(api_key=key, base_url=BASE_URL, max_retries=0)

    def send(request: dict) -> dict:
        return client.chat.completions.create(**request).model_dump()

    print(f"모델: {MODEL} · 후보 {len(clips)}개")
    results = []
    # 번호순으로 하나씩 부른다. 동시 호출은 하지 않는다 (D-344 다-9)
    for candidate in iter_candidate_frames(video_path, input_path, candidates_path):
        label = (
            f"후보 {candidate.number}/{len(clips)}"
            f" · {candidate.start_sec:g}~{candidate.end_sec:g}초"
            f" · 판정 프레임 {len(candidate.frames)}장"
        )
        results.append(score_candidate(build_request(candidate, data, crop_rect), send, label))

    rows = rank_scores(clips, [(r.score, r.reason) for r in results])
    path = write_scores(out_dir, rows)
    print_lists(rows)
    print(
        f"\n호출 {sum(r.calls for r in results)}회"
        f" (형식 오류 {sum(r.format_errors for r in results)}회)"
        f" · 토큰: 입력 {sum(r.input_tokens for r in results)}"
        f" · 출력 {sum(r.output_tokens for r in results)}"
    )
    print(f"점수 파일 → {path}")


if __name__ == "__main__":
    if len(sys.argv) != 5:
        print(
            "사용법: python -m pipeline.vlm.score <영상> <입력 JSON> <candidates.jsonl> <출력 폴더>"
        )
        sys.exit(2)
    try:
        run_score(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4])
    except (CallError, InputError, CropError, RoiError, FileNotFoundError) as e:
        print(f"오류: {e}")
        sys.exit(1)
    except openai.APIError as e:
        # 인증 실패·요청 거절·한도·서버 장애·타임아웃이 모두 여기로 온다. 다시 보내지 않는다
        print(f"오류: API 호출 실패 — {type(e).__name__}: {e}")
        sys.exit(1)
