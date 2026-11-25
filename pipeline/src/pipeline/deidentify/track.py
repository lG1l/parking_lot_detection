"""탐지가 끊긴 프레임을 메워 "가릴 박스 파일" mask_boxes.jsonl을 쓴다 (D-350).

탐지 파일(deid_boxes.jsonl)은 프레임마다 따로 찾은 박스라, 얼굴·번호판이 한두 장씩 빠진다.
저자 코드(tracker/offline_tracker.py)의 track_video를 그대로 불러, 박스를 앞·뒤 두 방향으로
잇고 짧은 틈은 보간, 끝은 조금 연장한다. 저자 코드는 고치지 않는다.

박스를 더하기만 한다. 탐지 파일에 있던 박스는 하나도 빠지지 않는다.
출력 형식은 탐지 파일과 같아서 8-다(mask.py)에 탐지 파일 대신 이 파일을 주면 된다.
오래 안 잡힌 구간은 메우지 못한다 (차 박스를 따라가며 메우는 방법은 써 보고 뺐다, D-350).

실행 (pipeline/ 폴더에서):
    uv run python -m pipeline.deidentify.track <영상> <모델 폴더> <deid_boxes.jsonl> <출력 파일>
"""

import json
import os
import sys

from pipeline.candidates.s1_base.preview import video_size
from pipeline.deidentify.clips import ClipError, video_fps
from pipeline.deidentify.detect import THRESHOLDS, Det, DetectError

# 저자 코드의 클래스 번호 ↔ 탐지 파일의 이름
_CATEGORY = {"face": 0, "plate": 1}
_CLS_NAME = {0: "face", 1: "plate"}
_TRACKER_DIR = "tracker"
_TRACKER_SCRIPT = "offline_tracker.py"

Box = list[float]  # [x1, y1, x2, y2] 원본 좌표
Row = tuple[float, list[Det]]  # 탐지 파일의 한 줄 (프레임 시각, 박스 목록)


class TrackError(Exception):
    """입력 파일이 없을 때."""


def load_rows(boxes_path: str) -> list[Row]:
    """탐지 파일을 시각 순서의 (프레임 시각, 박스 목록) 목록으로 읽는다."""
    if not os.path.isfile(boxes_path):
        raise TrackError(f"탐지 파일이 없습니다: {boxes_path}")
    with open(boxes_path) as boxes_file:
        rows = [json.loads(line) for line in boxes_file]
    return sorted((row["t"], row["dets"]) for row in rows)


def split_runs(rows: list[Row], fps: float) -> list[list[Row]]:
    """프레임이 빠짐없이 이어지는 묶음으로 나눈다.

    탐지 파일에는 후보 여러 개의 프레임이 함께 들어 있다. 서로 떨어진 후보를 한 줄로 이으면
    추적기가 앞 후보의 박스를 뒤 후보까지 끌고 가므로, 프레임 간격이 벌어진 곳에서 끊는다.
    """
    runs: list[list[Row]] = []
    for row in rows:
        # 간격이 프레임 한 장 반보다 크면 사이에 빠진 프레임이 있다
        if runs and row[0] - runs[-1][-1][0] <= 1.5 / fps:
            runs[-1].append(row)
        else:
            runs.append([row])
    return runs


def to_det(cls: str, box: Box, kind: str, size: tuple[int, int]) -> Det | None:
    """박스를 화면 안으로 자르고 정수로 맞춰 파일에 쓸 모양으로 만든다. 넓이가 없으면 None."""
    width, height = size
    x1, y1 = max(round(box[0]), 0), max(round(box[1]), 0)
    x2, y2 = min(round(box[2]), width), min(round(box[3]), height)
    if x2 <= x1 or y2 <= y1:
        return None
    return {"cls": cls, "bbox": [x1, y1, x2, y2], "kind": kind}


def load_tracker(model_dir: str):
    """저자 추적 코드(offline_tracker 모듈)를 불러온다.

    모델이 없는 곳(CI)에서도 이 파일의 다른 함수를 쓸 수 있게 이 함수 안에서만 불러온다.
    """
    tracker_dir = os.path.join(model_dir, _TRACKER_DIR)
    if not os.path.isfile(os.path.join(tracker_dir, _TRACKER_SCRIPT)):
        raise TrackError(
            f"모델 폴더에 {_TRACKER_DIR}/{_TRACKER_SCRIPT} 파일이 없습니다: {model_dir}"
        )
    sys.path.insert(0, tracker_dir)
    import offline_tracker

    return offline_tracker


def tracker_inputs(run: list[Row], tracker):
    """묶음 한 개를 저자 추적기가 받는 모양으로 바꾼다: (상수 묶음, {프레임 순서: [(종류, 점수, 박스)]}).

    임계값은 우리 탐지 임계값(D-346)을 주고, 나머지 상수(틈 0.5초, 연장 0.25초 등)는 저자 기본값이다.
    """
    thresholds = {_CATEGORY[name]: value for name, value in THRESHOLDS.items()}
    params = tracker.TrackerParams(thresholds=thresholds, confirm=dict(thresholds))
    detections = {
        i: [(_CATEGORY[det["cls"]], det["conf"], det["bbox"]) for det in dets]
        for i, (_, dets) in enumerate(run)
    }
    return params, detections


def track_run(run: list[Row], size: tuple[int, int], fps: float, tracker) -> list[list[tuple]]:
    """이어진 프레임 한 묶음을 저자 추적기에 넣어 프레임마다 (종류, 박스, 어떻게 얻었나)를 받는다.

    "어떻게 얻었나"는 detected(그 프레임에서 탐지) · interpolated(틈 보간) · extrapolated(끝 연장)다.
    """
    params, detections = tracker_inputs(run, tracker)
    masks, _, _ = tracker.track_video(detections, len(run), size[0], size[1], fps, params)
    return [
        [
            (_CLS_NAME[category], [float(v) for v in box], kind)
            for category, box, kind, _ in masks[i]
        ]
        for i in range(len(run))
    ]


def run_track(video_path: str, model_dir: str, boxes_path: str, out_path: str) -> None:
    """탐지 파일의 모든 프레임에 대해 가릴 박스 파일을 쓴다."""
    size = video_size(video_path)
    fps = video_fps(video_path)
    rows = load_rows(boxes_path)
    tracker = load_tracker(model_dir)

    counts = {"detected": 0, "interpolated": 0, "extrapolated": 0}
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w") as out_file:
        for run in split_runs(rows, fps):
            tracked = track_run(run, size, fps, tracker)
            for (t, _), frame in zip(run, tracked, strict=True):
                dets = [det for cls, box, kind in frame if (det := to_det(cls, box, kind, size))]
                for det in dets:
                    counts[det["kind"]] += 1
                out_file.write(json.dumps({"t": t, "dets": dets}) + "\n")
            print(f"{run[0][0]:g}~{run[-1][0]:g}초 · {len(run)}장")
    print(
        f"그 프레임에서 탐지 {counts['detected']} · 틈 보간 {counts['interpolated']} · "
        f"끝 연장 {counts['extrapolated']} → {out_path}"
    )


if __name__ == "__main__":
    if len(sys.argv) != 5:
        print(
            "사용법: python -m pipeline.deidentify.track"
            " <영상> <모델 폴더> <deid_boxes.jsonl> <출력 파일>"
        )
        sys.exit(2)
    try:
        run_track(*sys.argv[1:5])
    except (ClipError, DetectError, TrackError, FileNotFoundError) as e:
        print(f"오류: {e}")
        sys.exit(1)
