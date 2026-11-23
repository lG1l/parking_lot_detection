import json

import numpy as np

from pipeline.candidates.s1_base.inputs import AnalysisInput
from pipeline.vlm.frames import CandidateFrames, VlmFrame
from pipeline.vlm.request import SCORE_MAX, TOOL_NAME, build_request
from pipeline.vlm.score import (
    LIST_MAIN,
    LIST_PARSE_FAILED,
    MAX_FORMAT_CALLS,
    rank_scores,
    score_candidate,
)

CROP_RECT = (470, 232, 1765, 960)
BLACK = np.zeros((8, 8, 3), dtype=np.uint8)


def _request() -> dict:
    data = AnalysisInput(
        vehicle_bbox=(715, 452, 1259, 729),
        visible=True,
        damage_bbox=(864, 592, 1027, 659),
        floor_corners=[(732, 723), (956, 743), (1273, 641), (1027, 638)],
        front_edge=0,
        damage_edges=[1],
        description=None,
    )
    candidate = CandidateFrames(1, 38.7, 50.5, guide=BLACK, frames=[VlmFrame(1, 38.705, BLACK)])
    return build_request(candidate, data, CROP_RECT)


def _response(arguments: str | None) -> dict:
    """가짜 응답. arguments가 None이면 도구 호출이 없는 응답이다."""
    calls = (
        None if arguments is None else [{"function": {"name": TOOL_NAME, "arguments": arguments}}]
    )
    message = {"role": "assistant", "content": None, "tool_calls": calls}
    return {"choices": [{"finish_reason": "tool_calls", "message": message}]}


class FakeSend:
    """받은 요청을 기억하고 가짜 응답을 차례로 내준다. 응답이 하나면 그것을 계속 내준다."""

    def __init__(self, responses: list[dict]):
        self.responses = responses
        self.requests: list[dict] = []

    def __call__(self, request: dict) -> dict:
        self.requests.append(request)
        return self.responses[min(len(self.requests), len(self.responses)) - 1]


def _last_text(request: dict) -> str:
    """사용자 내용의 맨 끝 조각의 글. 이미지면 빈 글이다."""
    return request["messages"][1]["content"][-1].get("text", "")


def test_순위는_점수_내림차순이고_동점은_먼저_일어난_순이다():
    clips = [(10.0, 15.0), (20.0, 25.0), (30.0, 35.0), (40.0, 45.0), (50.0, 55.0)]
    scores = [(40, "가"), (None, None), (70, "다"), (40, "라"), (None, None)]
    rows = rank_scores(clips, scores)
    # 결과의 순서는 후보 번호순 그대로다
    assert [r["start_sec"] for r in rows] == [10.0, 20.0, 30.0, 40.0, 50.0]
    assert [r["list_kind"] for r in rows] == [
        LIST_MAIN,
        LIST_PARSE_FAILED,
        LIST_MAIN,
        LIST_MAIN,
        LIST_PARSE_FAILED,
    ]
    assert [r["rank"] for r in rows] == [2, 1, 1, 3, 2]
    assert list(rows[0]) == ["start_sec", "end_sec", "vlm_score", "list_kind", "rank", "reason"]


def test_후보가_없거나_모두_끝내_실패한_경우():
    assert rank_scores([], []) == []
    rows = rank_scores([(10.0, 15.0), (20.0, 25.0)], [(None, None), (None, None)])
    assert [r["list_kind"] for r in rows] == [LIST_PARSE_FAILED, LIST_PARSE_FAILED]
    assert [r["rank"] for r in rows] == [1, 2]
    assert all(r["vlm_score"] is None and r["reason"] is None for r in rows)


def test_형식_오류면_오류_글을_붙여_다시_부른다():
    request = _request()
    send = FakeSend([_response(None), _response(json.dumps({"reason": "근거", "score": 35}))])
    result = score_candidate(request, send)
    assert len(send.requests) == 2
    assert (result.score, result.reason, result.calls, result.format_errors) == (35, "근거", 2, 1)
    assert "응답에 도구 호출이 없다" in _last_text(send.requests[1])
    assert "형식에 맞지 않았다" not in _last_text(send.requests[0])
    assert "형식에 맞지 않았다" not in _last_text(request)


def test_계속_형식_오류면_최대_호출_수에서_멈추고_점수가_없다():
    send = FakeSend([_response(json.dumps({"reason": "근거", "score": SCORE_MAX + 1}))])
    result = score_candidate(_request(), send)
    assert len(send.requests) == MAX_FORMAT_CALLS
    assert result.score is None and result.reason is None
    assert result.format_errors == MAX_FORMAT_CALLS
