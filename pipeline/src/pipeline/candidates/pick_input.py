"""첫 화면에서 마우스로 좌표를 찍어 입력 JSON을 만드는 개발용 도구 (D-281).

입력 JSON은 원래 프론트에서 사용자가 찍어 만든다. 화면이 아직 없어서 영상마다 좌표를 손으로
재는 대신 이 도구로 만든다. 사용: python -m pipeline.candidates.pick_input <영상> <만들 JSON>
"""

import json
import sys

import cv2
import numpy as np

from pipeline.candidates.inputs import InputError, load_input
from pipeline.candidates.video import iter_analysis_frames

# 화면에 띄울 때 줄이는 배율. 클릭 좌표는 다시 원본 픽셀로 되돌려 저장한다
DISPLAY_SCALE = 0.6

# 찍는 순서: 차량 사각형 2점, 파손 사각형 2점, 바닥 네 모서리 4점
_STEPS = (
    ["vehicle box: top-left", "vehicle box: bottom-right"]
    + ["damage box: top-left", "damage box: bottom-right"]
    + [f"floor corner {i} (go around the car in order)" for i in range(4)]
)


def _draw(base: np.ndarray, points: list[tuple[int, int]]) -> np.ndarray:
    """찍은 점을 화면에 바로 그린다. points는 원본 픽셀 좌표다."""
    img = base.copy()
    scaled = [(int(x * DISPLAY_SCALE), int(y * DISPLAY_SCALE)) for x, y in points]
    if len(scaled) >= 2:
        cv2.rectangle(img, scaled[0], scaled[1], (255, 255, 255), 2)  # 차량: 흰색
    if len(scaled) >= 4:
        cv2.rectangle(img, scaled[2], scaled[3], (0, 0, 255), 2)  # 파손: 빨강
    corners = scaled[4:]
    if len(corners) >= 2:
        cv2.polylines(img, [np.array(corners)], len(corners) == 4, (255, 128, 0), 2)
    for i, p in enumerate(corners):
        cv2.circle(img, p, 5, (255, 128, 0), -1)
        cv2.putText(
            img, str(i), (p[0] + 8, p[1] - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 128, 0), 2
        )
    msg = _STEPS[len(points)] if len(points) < len(_STEPS) else "done"
    cv2.putText(
        img,
        msg + "  [u: undo, Esc: quit]",
        (10, 28),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        (0, 255, 255),
        2,
    )
    return img


def _click_points(first_frame: np.ndarray) -> list[tuple[int, int]] | None:
    h, w = first_frame.shape[:2]
    base = cv2.resize(first_frame, (int(w * DISPLAY_SCALE), int(h * DISPLAY_SCALE)))
    points: list[tuple[int, int]] = []
    window = "pick input"

    def on_mouse(event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN and len(points) < len(_STEPS):
            points.append((round(x / DISPLAY_SCALE), round(y / DISPLAY_SCALE)))

    cv2.namedWindow(window)
    cv2.setMouseCallback(window, on_mouse)
    while True:
        cv2.imshow(window, _draw(base, points))
        key = cv2.waitKey(30) & 0xFF
        if key == 27:
            cv2.destroyAllWindows()
            return None
        if key == ord("u") and points:
            points.pop()
        if len(points) == len(_STEPS):
            cv2.imshow(window, _draw(base, points))
            cv2.waitKey(500)  # 마지막 점이 그려진 것을 잠깐 보여 준다
            cv2.destroyAllWindows()
            return points


def _ask_edges() -> tuple[int, list[int], bool]:
    print("변 i는 i번 모서리에서 (i+1)번 모서리까지입니다 (3번 변은 3번→0번).")
    front = int(input("앞쪽 변 번호 (0~3): "))
    edges = [
        int(v)
        for v in input("파손 변 번호 (1개, 또는 이웃한 2개를 띄어 써서. 예: 0 또는 0 1): ").split()
    ]
    visible = input("파손이 CCTV에 보입니까? (y/n): ").strip().lower() == "y"
    return front, edges, visible


def main(video_path: str, out_path: str) -> None:
    frame = next(iter_analysis_frames(video_path), None)
    if frame is None:
        sys.exit(f"영상에서 프레임을 읽지 못했습니다: {video_path}")
    h, w = frame.image.shape[:2]

    points = _click_points(frame.image)
    if points is None:
        sys.exit("취소했습니다.")
    front, edges, visible = _ask_edges()

    x1, y1, x2, y2 = (*points[0], *points[1])
    dx1, dy1, dx2, dy2 = (*points[2], *points[3])
    data = {
        "vehicle": {"det_id": 1, "bbox": [min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)]},
        "damage": {
            "visible": visible,
            "damage_bbox": [min(dx1, dx2), min(dy1, dy2), max(dx1, dx2), max(dy1, dy2)],
            "floor_corners": [list(p) for p in points[4:]],
            "front_edge": front,
            "damage_edges": edges,
        },
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    try:
        load_input(out_path, w, h)  # 저장한 파일이 검사를 통과하는지 바로 확인한다
    except InputError as e:
        sys.exit(f"저장했지만 검사에서 걸렸습니다. 다시 찍어 주세요: {e}")
    print(f"저장했습니다: {out_path}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("사용: python -m pipeline.candidates.pick_input <영상> <만들 입력 JSON>")
    main(sys.argv[1], sys.argv[2])
