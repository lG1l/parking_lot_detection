import numpy as np
import supervision as sv

from pipeline.candidates.channel_a import track_lines
from pipeline.candidates.crop import Crop

# 원본 1280×720 영역을 640×360으로 줄인 분석 크롭. 줄인 좌표 × 2 + (400, 200) = 원본 좌표
CROP = Crop((400, 200, 1680, 920), (640, 360))
NAMES = {0: "person", 2: "car"}


def test_확정된_트랙만_원본_좌표_정수_bbox로_줄이_된다():
    tracked = sv.Detections(
        xyxy=np.array([[100.0, 50.0, 200.0, 150.0], [300.2, 100.4, 400.6, 160.8]]),
        confidence=np.array([0.9, 0.774]),
        class_id=np.array([2, 0]),
        # 첫 사각형은 아직 확정되지 않았다. 둘째는 추적기 번호 6이다
        tracker_id=np.array([-1, 6]),
    )

    lines = track_lines(tracked, NAMES, 43.70949, CROP)

    assert lines == [
        {
            "t": 43.709,
            "track_id": 6,
            "cls": "person",
            # (300.2, 100.4, 400.6, 160.8) × 2 + (400, 200) = (1000.4, 400.8, 1201.2, 521.6)
            "bbox": [1000, 401, 1201, 522],
            "conf": 0.77,
        }
    ]
    assert all(type(v) is int for v in lines[0]["bbox"])
    assert type(lines[0]["track_id"]) is int
