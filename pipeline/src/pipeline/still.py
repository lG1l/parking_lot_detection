"""1단계 정지 장면: 영상의 첫 프레임에서 차량 탐지 목록과 가린 정지 장면 이미지를 만든다 (D-351).

출력 폴더에 파일 셋을 쓴다.
    detections.json  차량 탐지 목록 (04장 still_frames.detections 형식, 0건이면 [])
    0.jpg            얼굴·번호판을 흐린 첫 프레임
    0_check.jpg      확인용. 가리기 전 화면이다. local_storage/ 밖으로 내보내지 않는다 (불변 조건 3)

타일 방식(D-69)과 코덱 검사(D-43)는 미뤘다. 프레임을 통째로 모델에 한 번씩 넣는다.

실행 (pipeline/ 폴더에서):
    uv run python -m pipeline.still <영상> <YOLO 가중치> <비식별화 모델 폴더> <출력 폴더>
"""

import json
import os
import sys

import cv2
import numpy as np

from pipeline.deidentify.detect import (
    Det,
    DetectError,
    check_model_dir,
    detect_frame,
    load_detector,
)
from pipeline.deidentify.mask import mask_frame

# 정지 장면 차량 탐지 (01장 1.6, D-221, D-351). 모두 시작값이다
STILL_CLASS_NAMES = ("car", "motorcycle", "bus", "truck")
STILL_CONF = 0.25
STILL_YOLO_INPUT_SIZE = 640  # Ultralytics 기본값. 입력 JSON을 만든 도구와 같다 (9-2)
STILL_MERGE_IOU = 0.3  # 마스크 IoU가 이 이상이면 같은 차의 중복 탐지로 보고 합친다

# 확인용 이미지에 그리는 색 (BGR). 얼굴·번호판은 8-나 확인용 영상과 같다
_VEHICLE_COLOR = (0, 255, 0)  # 차량 다각형 초록
_BOX_COLORS = {"face": (0, 0, 255), "plate": (0, 255, 255)}  # 얼굴 빨강, 번호판 노랑
_FILL_ALPHA = 0.25  # 다각형을 칠하는 진하기. 차가 비쳐 보여야 한다

# 탐지 하나 또는 합친 묶음 하나.
# {"mask": 참·거짓 그림(높이, 폭), "bbox": [x1, y1, x2, y2], "conf": 0.9, "cls": "car"}
Vehicle = dict


class StillError(Exception):
    """영상을 못 열거나 YOLO 가중치 파일이 없을 때."""


def read_first_frame(video_path: str) -> np.ndarray:
    """영상의 첫 프레임 1장을 읽는다. 시크하지 않는다 (D-48)."""
    capture = cv2.VideoCapture(video_path)
    ok, image = capture.read()
    capture.release()
    if not ok:
        raise StillError(f"영상의 첫 프레임을 읽지 못했습니다: {video_path}")
    return image


def detect_vehicles(weights_path: str, image: np.ndarray) -> list[Vehicle]:
    """프레임 전체를 YOLO11m-seg에 한 번 넣어 차량 네 종류의 마스크·박스·신뢰도·종류를 얻는다."""
    # 파일이 없으면 Ultralytics가 이름을 보고 스스로 내려받으므로 먼저 막는다
    if not os.path.isfile(weights_path):
        raise StillError(f"YOLO 가중치 파일이 없습니다: {weights_path}")
    # 모델이 없는 곳(CI)에서도 이 파일의 다른 함수를 불러 쓸 수 있게 여기서 불러온다
    import torch
    from ultralytics import YOLO

    model = YOLO(weights_path)
    class_ids = [number for number, name in model.names.items() if name in STILL_CLASS_NAMES]
    if torch.cuda.is_available():
        device = "cuda:0"
    elif torch.backends.mps.is_available():
        device = "mps"
    else:
        device = "cpu"
    result = model(
        image,
        conf=STILL_CONF,
        imgsz=STILL_YOLO_INPUT_SIZE,
        classes=class_ids,
        device=device,
        verbose=False,
        # 켜야 마스크가 넣은 프레임 크기로 나와 프레임과 픽셀 자리가 맞는다
        retina_masks=True,
    )[0]
    if result.masks is None:
        return []  # 탐지가 하나도 없으면 마스크 자체가 없다
    # masks.xy는 가장 큰 조각만 주므로 masks.data(그림 전체)를 쓴다 (06장 6.3)
    masks = result.masks.data.cpu().numpy() > 0.5
    boxes = result.boxes.xyxy.cpu().numpy()
    confs = result.boxes.conf.cpu().numpy()
    classes = result.boxes.cls.cpu().numpy().astype(int)
    return [
        {
            "mask": masks[i],
            "bbox": [float(v) for v in boxes[i]],
            "conf": float(confs[i]),
            "cls": model.names[classes[i]],
        }
        for i in range(len(boxes))
    ]


def _mask_iou(a: np.ndarray, b: np.ndarray) -> float:
    """두 마스크가 겹친 칸 수 / 합친 칸 수."""
    union = (a | b).sum()
    return float((a & b).sum() / union) if union else 0.0


def merge_duplicates(vehicles: list[Vehicle]) -> list[Vehicle]:
    """같은 차의 중복 탐지를 한 대로 합친다 (06장 6.3 중복 합치기, D-351 9-3).

    신뢰도가 높은 탐지부터 보며, 이미 만든 묶음의 "합친 마스크"와 IoU를 잰다.
    기준 이상이면 그 묶음에 넣는다. 종류·conf는 신뢰도가 높은 쪽(묶음을 처음 만든 탐지),
    bbox는 합집합이다. 박스 IoU는 쓰지 않는다. 박스만 겹친 옆 차가 합쳐지기 때문이다.
    """
    groups: list[Vehicle] = []
    for vehicle in sorted(vehicles, key=lambda v: -v["conf"]):
        for group in groups:
            if _mask_iou(vehicle["mask"], group["mask"]) >= STILL_MERGE_IOU:
                group["mask"] |= vehicle["mask"]
                a, b = group["bbox"], vehicle["bbox"]
                group["bbox"] = [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]
                break
        else:
            groups.append({**vehicle, "mask": vehicle["mask"].copy()})
    return groups


def hull_polygon(mask: np.ndarray) -> list[list[int]]:
    """조각 잇기: 마스크의 조각을 모두 감싸는 볼록 껍질의 꼭짓점을 구한다 (06장 6.3).

    기둥에 끊겨 마스크가 두 조각이어도 다각형 하나가 된다.
    """
    # findContours는 덩어리마다 바깥 윤곽의 점들을 준다
    contours, _ = cv2.findContours(
        mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    # convexHull은 점들을 모두 감싸는 가장 작은 볼록 다각형을 준다
    hull = cv2.convexHull(np.vstack(contours)).reshape(-1, 2)
    return [[int(x), int(y)] for x, y in hull]


def sort_left_to_right(groups: list[Vehicle]) -> list[Vehicle]:
    """bbox 왼쪽 변(x1, 소수 버림)이 작은 순서로 늘어놓는다. det_id를 매기는 순서다 (9-4)."""
    return sorted(groups, key=lambda group: int(group["bbox"][0]))


def build_detections(groups: list[Vehicle]) -> list[dict]:
    """늘어놓은 묶음 목록을 04장 still_frames.detections 형식의 탐지 목록으로 바꾼다 (9-5).

    det_id는 받은 순서대로 1부터 매긴다. 키는 네 개뿐이고 차량 종류는 넣지 않는다.
    """
    return [
        {
            "det_id": number,
            "bbox": [int(v) for v in group["bbox"]],
            "conf": round(group["conf"], 2),
            "polygon": hull_polygon(group["mask"]),
        }
        for number, group in enumerate(groups, start=1)
    ]


def draw_check(
    image: np.ndarray, detections: list[dict], class_names: list[str], boxes: list[Det]
) -> np.ndarray:
    """확인용 이미지를 만든다: 가리기 전 화면 + 차량 다각형·번호·종류·conf + 얼굴·번호판 박스."""
    canvas = image.copy()
    polygons = [np.array(det["polygon"], dtype=np.int32) for det in detections]
    if polygons:
        # 다각형을 칠한 그림과 원래 그림을 섞어 옅게 칠한다
        filled = canvas.copy()
        cv2.fillPoly(filled, polygons, _VEHICLE_COLOR)
        canvas = cv2.addWeighted(filled, _FILL_ALPHA, canvas, 1 - _FILL_ALPHA, 0)
        cv2.polylines(canvas, polygons, True, _VEHICLE_COLOR, 2)
    for det, class_name in zip(detections, class_names, strict=True):
        x1, y1 = det["bbox"][:2]
        label = f"{det['det_id']} {class_name} {det['conf']:.2f}"
        # 글자 뒤에 검은 띠를 먼저 깔아 밝은 차 위에서도 읽히게 한다
        (text_w, text_h), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)
        cv2.rectangle(canvas, (x1, y1), (x1 + text_w + 8, y1 + text_h + 10), (0, 0, 0), -1)
        cv2.putText(
            canvas, label, (x1 + 4, y1 + text_h + 4), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255,) * 3, 2
        )
    for box in boxes:
        x1, y1, x2, y2 = box["bbox"]
        cv2.rectangle(canvas, (x1, y1), (x2, y2), _BOX_COLORS[box["cls"]], 2)
    return canvas


def run_still(video_path: str, weights_path: str, model_dir: str, out_dir: str) -> None:
    """첫 프레임 1장으로 detections.json·0.jpg·0_check.jpg를 쓴다."""
    image = read_first_frame(video_path)
    height, width = image.shape[:2]
    whole = (0, 0, width, height)  # 프레임 전체. 타일로 나누지 않는다 (9-1)

    # 차량은 가리기 전 프레임에서 탐지한다. 흐린 뒤에 탐지하면 차 경계가 흐려진다 (D-65)
    groups = sort_left_to_right(merge_duplicates(detect_vehicles(weights_path, image)))
    detections = build_detections(groups)

    check_model_dir(model_dir)
    detector, _ = load_detector(model_dir)
    boxes = detect_frame(detector, image, whole)

    masked = image.copy()  # 확인용 이미지는 가리기 전 화면이어야 해서 복사본을 흐린다
    faces, plates, _ = mask_frame(masked, boxes, whole)
    check = draw_check(image, detections, [group["cls"] for group in groups], boxes)

    os.makedirs(out_dir, exist_ok=True)
    list_path = os.path.join(out_dir, "detections.json")
    still_path = os.path.join(out_dir, "0.jpg")
    check_path = os.path.join(out_dir, "0_check.jpg")
    with open(list_path, "w") as list_file:
        json.dump(detections, list_file)
    cv2.imwrite(still_path, masked)
    cv2.imwrite(check_path, check)

    print(f"차량 {len(detections)}대 · 얼굴 박스 {faces} · 번호판 박스 {plates}")
    for path in (list_path, still_path, check_path):
        print(path)


if __name__ == "__main__":
    if len(sys.argv) != 5:
        print(
            "사용법: python -m pipeline.still <영상> <YOLO 가중치> <비식별화 모델 폴더> <출력 폴더>"
        )
        sys.exit(2)
    try:
        run_still(*sys.argv[1:5])
    except (StillError, DetectError) as e:
        print(f"오류: {e}")
        sys.exit(1)
