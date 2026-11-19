"""후보 하나의 프레임을 한 장에 줄여 붙인 확인용 묶음 이미지를 만든다 (D-342 가-8).

눈으로 볼 때만 쓴다. VLM에 넣는 프레임은 줄이지 않는다.
"""

import cv2
import numpy as np

from pipeline.candidates.s1_base.preview import draw_labels

# 한 줄의 칸 수와 칸 폭 (픽셀). 확인용이라 줄여서 붙인다
COLUMNS = 4
CELL_WIDTH = 480

_TITLE_HEIGHT = 44
_LABEL_COLOR = (40, 40, 40)  # 글 배경 (BGR)


def _cell(image: np.ndarray, label: str) -> np.ndarray:
    """그림을 칸 폭으로 줄이고 왼쪽 위에 글을 쓴다."""
    height = round(image.shape[0] * CELL_WIDTH / image.shape[1])
    small = cv2.resize(image, (CELL_WIDTH, height), interpolation=cv2.INTER_AREA)
    return draw_labels(small, [(label, (8, 6), _LABEL_COLOR)])


def make_sheet(title: str, cells: list[tuple[str, np.ndarray]]) -> np.ndarray:
    """(칸 글, 그림) 목록을 한 줄에 COLUMNS칸씩 붙이고 맨 위에 제목을 쓴 그림을 돌려준다.

    그림은 모두 같은 크기여야 한다 (한 후보의 프레임은 같은 분석 크롭이다).
    """
    images = [_cell(image, label) for label, image in cells]
    # 마지막 줄의 빈 칸은 검은 그림으로 채워야 줄끼리 폭이 맞아 이어 붙일 수 있다
    while len(images) % COLUMNS:
        images.append(np.zeros_like(images[0]))
    rows = [np.hstack(images[i : i + COLUMNS]) for i in range(0, len(images), COLUMNS)]
    body = np.vstack(rows)
    bar = np.zeros((_TITLE_HEIGHT, body.shape[1], 3), dtype=np.uint8)
    return np.vstack([draw_labels(bar, [(title, (8, 8), _LABEL_COLOR)]), body])
