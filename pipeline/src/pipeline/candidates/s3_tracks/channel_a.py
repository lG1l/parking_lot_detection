"""채널 A 한 프레임 처리: YOLO11m-seg 탐지 → ByteTrack → 트랙 줄 (06장 6.5, D-196, D-200, D-260).

줄인 프레임 한 장을 받아 트랙 파일(04장 4.8)에 쓸 줄들과 차량 클래스 마스크를 만든다.
언제 돌릴지(켜고 끄기)는 yolo_switch가 정하고, 파일에 쓰는 일은 명령 쪽이 한다.
"""

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import supervision as sv
import torch
from trackers import ByteTrackTracker
from ultralytics import YOLO

from pipeline.candidates.s1_base.crop import Crop, to_original
from pipeline.candidates.s1_base.video import SAMPLING_FPS

# 01장 1.6 "채널 A YOLO 신뢰도 하한" (시작값, D-311). 추적기가 낮은 신뢰도 탐지로도
# 이미 있는 트랙을 이을 수 있게 새 트랙 시작 기준보다 낮게 둔다
YOLO_CONF = 0.1
# 01장 1.6 "채널 A·B 프레임 크기"의 YOLO 입력 (시작값, D-201)
YOLO_INPUT_SIZE = 640
# 01장 1.6 "ByteTrack 새 트랙 시작 기준" (시작값, D-200). 추적기의 기준 두 값에 같이 준다
TRACK_START_CONF = 0.5
# 이만큼 연속으로 잡혀야 트랙 번호가 확정된다 (D-255). 라이브러리 기본값은 2다
TRACK_CONFIRM_FRAMES = 3

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


# 내 차 영역을 고를 때 보는 차량 클래스 (06장 6.5 "내 차 찾기", D-264). 내 차가 다른 차량 클래스로 잡혀도 된다
MASK_CLASS_NAMES = ("car", "motorcycle", "bus", "truck")


class ModelError(Exception):
    """모델을 열 수 없을 때. 메시지는 사용자에게 그대로 보여 준다."""


@dataclass(frozen=True)
class TrackBox:
    """한 프레임의 확정된 채널 A 트랙 하나. 채널 B 덩어리를 붙일 때 본다 (D-314)."""

    track_id: int
    cls: str  # 그 프레임에 YOLO가 낸 클래스 이름
    bbox: tuple[float, float, float, float]  # 줄인 프레임 좌표 (x1, y1, x2, y2)


@dataclass
class ChannelA:
    """영상 하나에 하나 만든다. 추적기는 껐다 켜도 끝까지 같은 것을 쓴다 (D-257)."""

    model: YOLO
    class_ids: list[int]  # CLASS_NAMES에 해당하는 모델의 클래스 번호
    mask_class_ids: list[int]  # MASK_CLASS_NAMES에 해당하는 모델의 클래스 번호
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
    mask_class_ids = [number for number, name in model.names.items() if name in MASK_CLASS_NAMES]
    return ChannelA(model, class_ids, mask_class_ids, device, tracker)


def detect(channel: ChannelA, reduced: np.ndarray) -> tuple[sv.Detections, np.ndarray]:
    """줄인 프레임 한 장에서 사각형·신뢰도·클래스 번호와 차량 클래스 마스크를 얻는다.

    좌표는 줄인 프레임 기준이다. 마스크는 (차량 탐지 수, 높이, 폭)의 참·거짓 그림이고,
    추적기를 거치기 전의 탐지 전부에서 꺼낸다. 내 차를 고르는 데는 트랙 번호가 필요 없다 (D-264).
    """
    result = channel.model(
        reduced,
        conf=YOLO_CONF,
        imgsz=YOLO_INPUT_SIZE,
        classes=channel.class_ids,
        device=channel.device,
        verbose=False,
        # 기본 설정이면 마스크가 모델 입력 크기(패딩 포함 640×384)로 나온다.
        # 켜면 넣은 이미지 크기(640×360)로 나와 줄인 프레임과 픽셀 자리가 맞는다
        retina_masks=True,
    )[0]
    boxes = result.boxes
    class_id = boxes.cls.cpu().numpy().astype(int)
    detections = sv.Detections(
        xyxy=boxes.xyxy.cpu().numpy(),
        confidence=boxes.conf.cpu().numpy(),
        class_id=class_id,
    )
    if result.masks is None:
        # 탐지가 하나도 없으면 마스크 자체가 없다
        return detections, np.zeros((0, *reduced.shape[:2]), bool)
    is_vehicle = np.isin(class_id, channel.mask_class_ids)
    return detections, result.masks.data.cpu().numpy()[is_vehicle] > 0


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
                # 추적기가 매긴 번호 그대로 쓴다. 0번부터다 (D-312)
                "track_id": int(tracker_id),
                # 그 프레임에 YOLO가 낸 이름 그대로 쓴다. 트랙 안에서 바뀔 수 있다 (D-269)
                "cls": names[int(class_id)],
                "bbox": [round(x1), round(y1), round(x2), round(y2)],
                "conf": round(float(conf), 2),
            }
        )
    return lines


def track_boxes(tracked: sv.Detections, names: dict[int, str]) -> list[TrackBox]:
    """추적기가 돌려준 결과에서 확정된 트랙을 줄인 프레임 좌표 그대로 꺼낸다 (D-314 결정 2)."""
    return [
        TrackBox(int(tracker_id), names[int(class_id)], tuple(float(v) for v in xyxy))
        for xyxy, class_id, tracker_id in zip(tracked.xyxy, tracked.class_id, tracked.tracker_id)
        if tracker_id >= 0
    ]


def process_frame(
    channel: ChannelA, reduced: np.ndarray, time_sec: float, crop: Crop
) -> tuple[list[dict], list[TrackBox], np.ndarray]:
    """줄인 프레임 한 장을 탐지·추적해 트랙 줄들, 확정 트랙들, 차량 클래스 마스크들을 돌려준다.

    트랙 줄은 파일에 쓸 원본 좌표이고, 확정 트랙과 마스크는 줄인 좌표다.
    프레임은 시간순으로 넣는다. 앞선 시각을 넣으면 추적기가 그 프레임을 건너뛴다.
    """
    detections, vehicle_masks = detect(channel, reduced)
    # 시각을 줘서 YOLO가 꺼져 있던 시간만큼 추적기도 시간이 흐르게 한다 (D-313).
    # 주지 않으면 호출 1번을 1프레임으로 세어, 공백 뒤 같은 자리에 온 다른 물체가 앞 번호를 이어받는다
    tracked = channel.tracker.update(detections, timestamp=time_sec)
    names = channel.model.names
    return track_lines(tracked, names, time_sec, crop), track_boxes(tracked, names), vehicle_masks
