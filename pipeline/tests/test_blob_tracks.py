import numpy as np
import pytest
import supervision as sv

from pipeline.candidates.blob_tracks import (
    BLOB_ATTACH_RATIO,
    BLOB_TRACK_ID_OFFSET,
    STOPPED_MOVE_RATIO,
    STOPPED_WINDOW_SEC,
    attach_target,
    blob_track_lines,
    is_stopped_vehicle,
    remember_positions,
)
from pipeline.candidates.channel_a import TrackBox
from pipeline.candidates.channel_b import find_blobs
from pipeline.candidates.crop import Crop

SHAPE = (360, 640)
BLOB_SIZE = 20
# 덩어리 폭 중 이만큼이 bbox 안에 들면 딱 붙이기 기준이다
ATTACH_COLUMNS = int(BLOB_SIZE * BLOB_ATTACH_RATIO)


def _hand_blob():
    """(100, 100)에서 시작하는 20×20 덩어리 (손)."""
    binary = np.zeros(SHAPE, np.uint8)
    binary[100 : 100 + BLOB_SIZE, 100 : 100 + BLOB_SIZE] = 255
    return find_blobs(binary, np.zeros(SHAPE, np.uint8))[0]


# D-314 예시 표. 사람 bbox의 왼쪽 끝만 옮겨 덩어리가 든 폭을 바꾼다. 멈춘 차는 늘 덩어리를 전부 덮는다
@pytest.mark.parametrize(
    ("person_left", "expected"),
    [
        (90, 7),  # 사람 bbox에 전부 든다 → 사람(7번)에 붙는다. 멈춘 차(3번)가 번호가 작아도 빠진다
        (120 - ATTACH_COLUMNS, 7),  # 딱 기준만큼 든다 → 붙는다
        (120 - ATTACH_COLUMNS + 1, None),  # 기준보다 한 줄 덜 든다 → 넘긴다
    ],
)
def test_멈춘_차를_빼고_기준_이상_겹치는_사람에_붙인다(person_left, expected):
    parked_car = TrackBox(3, "car", (50.0, 50.0, 300.0, 200.0))
    person = TrackBox(7, "person", (float(person_left), 60.0, 200.0, 160.0))
    history = {}
    # 위치가 한 번만 적힌 차는 멈춘 차다
    remember_positions(history, 10.0, [parked_car, person])

    assert attach_target(_hand_blob(), [parked_car, person], history) == expected


def _moved(cls, move_ratio):
    """폭 100인 트랙이 STOPPED_WINDOW_SEC 동안 폭의 move_ratio만큼 옆으로 간 뒤의 (트랙, 이력)."""
    history = {}
    remember_positions(history, 10.0, [TrackBox(1, cls, (100.0, 100.0, 200.0, 150.0))])
    moved = 100 * move_ratio
    now = TrackBox(1, cls, (100.0 + moved, 100.0, 200.0 + moved, 150.0))
    remember_positions(history, 10.0 + STOPPED_WINDOW_SEC, [now])
    return now, history


def test_멈춘_차만_붙일_대상에서_뺀다():
    assert is_stopped_vehicle(*_moved("car", STOPPED_MOVE_RATIO * 0.9))
    assert not is_stopped_vehicle(*_moved("car", STOPPED_MOVE_RATIO * 1.1))
    # 위치가 하나뿐인 차 (막 확정된 트랙)
    new_car = TrackBox(2, "car", (100.0, 100.0, 200.0, 150.0))
    history = {}
    remember_positions(history, 10.0, [new_car])
    assert is_stopped_vehicle(new_car, history)
    # 사람은 움직이지 않아도 붙일 대상이다
    assert not is_stopped_vehicle(*_moved("person", 0.0))


def test_확정된_클래스_없는_트랙만_원본_좌표_줄로_쓴다():
    # 줄인 좌표에 2를 곱하고 (400, 200)을 더하면 원본 좌표다
    crop = Crop((400, 200, 1680, 920), (640, 360))
    tracked = sv.Detections(
        xyxy=np.array([[10.0, 20.0, 30.0, 40.0], [100.0, 100.0, 120.0, 120.0]], dtype=np.float32),
        confidence=np.array([1.0, 1.0], dtype=np.float32),
        tracker_id=np.array([4, -1]),
    )

    lines = blob_track_lines(tracked, 12.3, crop)

    # 번호가 음수인 사각형은 아직 확정되지 않아 빠진다. 클래스·신뢰도 키는 없다
    assert lines == [
        {"t": 12.3, "track_id": 4 + BLOB_TRACK_ID_OFFSET, "bbox": [420, 240, 460, 280]}
    ]
