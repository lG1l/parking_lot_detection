"""8단계 틈 메우기 (D-350). 영상·모델·저자 코드 없이 돈다."""

from pipeline.deidentify.track import split_runs, to_det

FPS = 30.0


def test_runs_split_where_frames_are_missing():
    rows = [(0.0, []), (1 / FPS, []), (2 / FPS, []), (10.0, []), (10.0 + 1 / FPS, [])]

    runs = split_runs(rows, FPS)

    assert [len(run) for run in runs] == [3, 2]


def test_box_is_cut_to_frame_and_rounded():
    size = (1920, 1080)

    assert to_det("plate", [-5.4, 10.6, 30.2, 40.4], "interpolated", size) == {
        "cls": "plate",
        "bbox": [0, 11, 30, 40],
        "kind": "interpolated",
    }
    assert to_det("plate", [1930.0, 10.0, 1950.0, 40.0], "interpolated", size) is None
