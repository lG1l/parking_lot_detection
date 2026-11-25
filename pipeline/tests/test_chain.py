"""명령 잇기(10-가, D-359)의 상위 후보 고르기와 부르는 순서. 영상·모델·API 없이 돈다."""

import json
import os

import pytest

from pipeline import chain
from pipeline.vlm.call import CallError

# 4절 표의 순서대로 chain이 부르는 실행 함수 여덟 개
STEP_NAMES = [
    "run_still",
    "make_track_preview",
    "run_track_filter",
    "run_candidate_list",
    "run_score",
    "run_detect",
    "run_track",
    "run_mask",
]


def _row(list_kind, rank, score=None):
    return {"list_kind": list_kind, "rank": rank, "vlm_score": score}


# 후보 1~5 (줄 순서 = 후보 번호)
FIVE_ROWS = [
    _row("main", 2, 40),
    _row("parse_failed", 1),
    _row("main", 1, 85),
    _row("main", 3, 10),
    _row("parse_failed", 2),
]


def test_pick_top_two_of_each_list():
    # 후보군 목록의 3·1, 파싱 실패 목록의 2·5. 후보 4는 3위라 빠진다
    assert chain.pick_top_candidates(FIVE_ROWS, 2) == [1, 2, 3, 5]


def test_pick_top_one_of_each_list_and_empty():
    assert chain.pick_top_candidates(FIVE_ROWS, 1) == [2, 3]
    assert chain.pick_top_candidates([], 2) == []


@pytest.fixture
def fake_steps(monkeypatch):
    """여덟 실행 함수를 부른 이름과 인자만 적는 가짜로 바꾼다. 적은 목록을 준다."""
    calls = []
    for name in STEP_NAMES:

        def fake(*args, _name=name, **kwargs):
            calls.append((_name, args))

        monkeypatch.setattr(chain, name, fake)
    return calls


def _fake_score(monkeypatch, calls, rows=None, error=None):
    """run_score만 점수 파일을 쓰거나(rows) 오류를 내는(error) 가짜로 다시 바꾼다."""

    def fake(video_path, input_path, candidates_path, out_dir):
        calls.append(("run_score", (video_path, input_path, candidates_path, out_dir)))
        if error:
            raise error
        os.makedirs(out_dir)
        with open(os.path.join(out_dir, chain.SCORES_NAME), "w") as f:
            f.writelines(json.dumps(row) + "\n" for row in rows)

    monkeypatch.setattr(chain, "run_score", fake)


def _run(tmp_path):
    return chain.main(["v.mp4", "in.json", "yolo.pt", "models", str(tmp_path)])


def test_calls_eight_steps_in_order(tmp_path, monkeypatch, fake_steps):
    _fake_score(monkeypatch, fake_steps, rows=[_row("main", 2, 10), _row("main", 1, 30)])
    assert _run(tmp_path) == 0
    assert [name for name, _ in fake_steps] == STEP_NAMES
    args = dict(fake_steps)
    # 탐지와 가리기가 같은 후보 번호 글을 받는다
    assert args["run_detect"][-1] == "1,2"
    assert args["run_mask"][-1] == "1,2"


def test_no_candidates_ends_normally_without_masking(tmp_path, monkeypatch, fake_steps):
    _fake_score(monkeypatch, fake_steps, rows=[])
    assert _run(tmp_path) == 0
    assert [name for name, _ in fake_steps] == STEP_NAMES[:5]


def test_score_error_stops_chain(tmp_path, monkeypatch, fake_steps):
    _fake_score(monkeypatch, fake_steps, error=CallError("LLM_API_KEY가 없다"))
    assert _run(tmp_path) == 1
    assert [name for name, _ in fake_steps] == STEP_NAMES[:5]
