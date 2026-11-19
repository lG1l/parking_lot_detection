import json

import numpy as np
import pytest

from pipeline.candidates.s1_base.inputs import AnalysisInput
from pipeline.vlm.call import FormatError, parse_score
from pipeline.vlm.frames import CandidateFrames, VlmFrame
from pipeline.vlm.request import SCORE_MAX, SCORE_MIN, TOOL_NAME, build_request, guide_text

CROP_RECT = (470, 232, 1765, 960)
BLACK = np.zeros((8, 8, 3), dtype=np.uint8)


def _data(visible: bool = True, description: str | None = None) -> AnalysisInput:
    return AnalysisInput(
        vehicle_bbox=(715, 452, 1259, 729),
        visible=visible,
        damage_bbox=(864, 592, 1027, 659),
        floor_corners=[(732, 723), (956, 743), (1273, 641), (1027, 638)],
        front_edge=0,
        damage_edges=[1],
        description=description,
    )


def _candidate() -> CandidateFrames:
    frames = [VlmFrame(1, 38.705, BLACK), VlmFrame(2, 39.705, BLACK)]
    return CandidateFrames(1, 38.7, 50.5, guide=BLACK, frames=frames)


def _kinds(request: dict) -> list[str]:
    """사용자 메시지의 조각을 순서대로 '글 내용' 또는 'image'로 바꾼다."""
    content = request["messages"][1]["content"]
    return [p["text"] if p["type"] == "text" else "image" for p in content]


def test_요청에_안내와_판정_프레임이_순서대로_들어간다():
    request = build_request(_candidate(), _data(), CROP_RECT)
    kinds = _kinds(request)
    assert kinds[0] == guide_text(_data(), CROP_RECT)
    assert kinds[1:] == [
        "image",
        "[프레임 1 / t=38.7s]",
        "image",
        "[프레임 2 / t=39.7s]",
        "image",
    ]
    assert request["messages"][0]["role"] == "system"
    assert "<user_description>" not in "".join(kinds)
    assert len(request["tools"]) == 1
    assert request["tools"][0]["function"]["name"] == TOOL_NAME
    assert request["tool_choice"]["function"]["name"] == TOOL_NAME
    url = request["messages"][1]["content"][1]["image_url"]["url"]
    assert url.startswith("data:image/jpeg;base64,")


def test_설명과_사진이_있으면_안내_프레임_뒤_판정_프레임_앞에_들어간다():
    data = _data(description="조수석 뒷문 아래가 긁혔어요")
    kinds = _kinds(build_request(_candidate(), data, CROP_RECT, photo=BLACK))
    assert kinds.count("image") == 4
    assert kinds[2] == "<user_description>조수석 뒷문 아래가 긁혔어요</user_description>"
    # 사진을 알리는 글과 사진이 안내 프레임(1) 뒤, 첫 캡션 앞이다
    assert kinds[4] == "image"
    assert kinds[5] == "[프레임 1 / t=38.7s]"


def test_안내_설명_글에_크롭_안_좌표와_보임_여부가_들어간다():
    seen = guide_text(_data(visible=True), CROP_RECT)
    unseen = guide_text(_data(visible=False), CROP_RECT)
    for text in (seen, unseen):
        assert "(394, 360, 557, 427)" in text
        assert "(262, 491)" in text
    assert seen != unseen


def _response(arguments: str | None, finish_reason: str = "tool_calls") -> dict:
    """가짜 응답. arguments가 None이면 도구 호출이 없는 응답이다."""
    calls = (
        None if arguments is None else [{"function": {"name": TOOL_NAME, "arguments": arguments}}]
    )
    message = {"role": "assistant", "content": None, "tool_calls": calls}
    return {"choices": [{"finish_reason": finish_reason, "message": message}]}


def test_정상_응답에서_점수와_근거를_읽는다():
    assert parse_score(_response('{"reason": "떨어져 지나갔다.", "score": 12}')) == (
        12,
        "떨어져 지나갔다.",
    )
    for score in (SCORE_MIN, SCORE_MAX):
        assert parse_score(_response(json.dumps({"reason": "근거", "score": score})))[0] == score


@pytest.mark.parametrize(
    "response",
    [
        _response(None),
        _response("점수는 12"),
        _response('{"reason": "근거"}'),
        _response(json.dumps({"reason": "근거", "score": SCORE_MAX + 1})),
        _response('{"reason": "근거", "score": "12"}'),
        _response('{"reason": "근거", "score": 12.5}'),
        _response('{"reason": "근거", "score": 12}', finish_reason="length"),
    ],
    ids=["도구_호출_없음", "JSON_아님", "score_없음", "범위_밖", "글자_점수", "소수_점수", "잘림"],
)
def test_형식이_틀린_응답은_형식_오류다(response):
    with pytest.raises(FormatError):
        parse_score(response)
