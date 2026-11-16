"""채널 A 한 프레임 처리: YOLO11m-seg 탐지 → ByteTrack → 트랙 줄 (06장 6.5, D-196, D-200, D-260).

줄인 프레임 한 장을 받아 트랙 파일(04장 4.8)에 쓸 줄들을 만든다.
언제 돌릴지(켜고 끄기)는 yolo_switch가 정하고, 파일에 쓰는 일은 명령 쪽이 한다.
"""

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import supervision as sv
import torch
from trackers import ByteTrackTracker
from ultralytics import YOLO

from pipeline.candidates.crop import Crop, to_original
from pipeline.candidates.video import SAMPLING_FPS

# 01장 1.6 "채널 A YOLO 신뢰도 하한" (시작값, D-311). 추적기가 낮은 신뢰도 탐지로도
# 이미 있는 트랙을 이을 수 있게 새 트랙 시작 기준보다 낮게 둔다
YOLO_CONF = 0.1
# 01장 1.6 "채널 A·B 프레임 크기"의 YOLO 입력 (시작값, D-201)
YOLO_INPUT_SIZE = 640
# 01장 1.6 "ByteTrack 새 트랙 시작 기준" (시작값, D-200). 추적기의 기준 두 값에 같이 준다
TRACK_START_CONF = 0.5
# 이만큼 연속으로 잡혀야 트랙 번호가 확정된다 (D-255). 라이브러리 기본값은 2다
TRACK_CONFIRM_FRAMES = 3
# 채널 A 트랙 번호의 시작 (D-257). 추적기는 0부터 매기므로 쓸 때 더한다
TRACK_ID_START = 1

# 받는 클래스: 사람, 차량, COCO 동물 전체 (D-196). 번호는 모델의 이름 표에서 찾는다
CLASS_NAMES = (
    "person",
    "car",
    "motorcycle",
    "bicycle",
    "truck",
    "bus",
    "bird",
    "cat",
    "dog",
    "horse",
    "sheep",
    "cow",
    "elephant",
    "bear",
    "zebra",
    "giraffe",
)


class ModelError(Exception):
    """모델을 열 수 없을 때. 메시지는 사용자에게 그대로 보여 준다."""


@dataclass
class ChannelA:
    """영상 하나에 하나 만든다. 추적기는 껐다 켜도 끝까지 같은 것을 쓴다 (D-257)."""

    model: YOLO
    class_ids: list[int]  # CLASS_NAMES에 해당하는 모델의 클래스 번호
    device: str
    tracker: ByteTrackTracker


def open_channel_a(weights: Path) -> ChannelA:
    """가중치 파일로 모델을 열고 추적기를 만든다."""
    # 파일이 없으면 Ultralytics가 이름을 보고 스스로 내려받으므로 먼저 막는다
    if not weights.is_file():
        raise ModelError(f"모델 파일이 없습니다: {weights}")
    model = YOLO(str(weights))
    class_ids = [number for number, name in model.names.items() if name in CLASS_NAMES]
    if len(class_ids) != len(CLASS_NAMES):
        raise ModelError(f"모델에 필요한 클래스가 다 있지 않습니다: {weights}")
    tracker = ByteTrackTracker(
        frame_rate=SAMPLING_FPS,
        track_activation_threshold=TRACK_START_CONF,
        high_conf_det_threshold=TRACK_START_CONF,
        minimum_consecutive_frames=TRACK_CONFIRM_FRAMES,
    )
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    return ChannelA(model, class_ids, device, tracker)


def detect(channel: ChannelA, reduced: np.ndarray) -> sv.Detections:
    """줄인 프레임 한 장에서 사각형·신뢰도·클래스 번호를 얻는다. 좌표는 줄인 프레임 기준이다."""
    result = channel.model(
        reduced,
        conf=YOLO_CONF,
        imgsz=YOLO_INPUT_SIZE,
        classes=channel.class_ids,
        device=channel.device,
        verbose=False,
    )[0]
    boxes = result.boxes
    # 마스크는 이번에 쓰지 않으므로 옮기지 않는다 (4단계에서 내 차 것만 쓴다)
    return sv.Detections(
        xyxy=boxes.xyxy.cpu().numpy(),
        confidence=boxes.conf.cpu().numpy(),
        class_id=boxes.cls.cpu().numpy().astype(int),
    )


def track_lines(
    tracked: sv.Detections, names: dict[int, str], time_sec: float, crop: Crop
) -> list[dict]:
    """추적기가 돌려준 결과를 트랙 파일 줄로 바꾼다 (04장 4.8)."""
    lines = []
    for xyxy, conf, class_id, tracker_id in zip(
        tracked.xyxy, tracked.confidence, tracked.class_id, tracked.tracker_id
    ):
        if tracker_id < 0:
            # 아직 확정되지 않은 트랙이다 (D-200)
            continue
        x1, y1 = to_original((xyxy[0], xyxy[1]), crop)
        x2, y2 = to_original((xyxy[2], xyxy[3]), crop)
        lines.append(
            {
                "t": round(time_sec, 3),
                "track_id": int(tracker_id) + TRACK_ID_START,
                # 그 프레임에 YOLO가 낸 이름 그대로 쓴다. 트랙 안에서 바뀔 수 있다 (D-269)
                "cls": names[int(class_id)],
                "bbox": [round(x1), round(y1), round(x2), round(y2)],
                "conf": round(float(conf), 2),
            }
        )
    return lines


def process_frame(
    channel: ChannelA, reduced: np.ndarray, time_sec: float, crop: Crop
) -> list[dict]:
    """줄인 프레임 한 장을 탐지·추적해 그 프레임의 트랙 줄들을 돌려준다."""
    tracked = channel.tracker.update(detect(channel, reduced))
    return track_lines(tracked, channel.model.names, time_sec, crop)
