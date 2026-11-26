"""평가 영상마다 첫 프레임의 차량 탐지 목록을 만들어 evaluation/kaggle_detections/에 쓴다.

입력 도구(evaluation/input_tool)가 차량을 고를 때 읽는 파일이다.
탐지는 9단계 정지 장면(pipeline.still, D-351)과 같은 함수로 하므로 서비스의 탐지 목록과 같다.

파일 이름 규칙
    영상 `<이름>.mp4` → 탐지 목록 `<이름>.json`. 입력 도구가 이 이름으로 영상과 맞춘다.
    영상 폴더는 하위 폴더까지 찾고, 탐지 목록은 폴더 구분 없이 한 곳에 쓴다.
    그래서 서로 다른 폴더에 같은 이름의 영상이 있으면 아무것도 쓰지 않고 멈춘다.
    이미 탐지 목록이 있는 영상은 건너뛴다. 다시 만들려면 그 json을 지우고 돌린다.

실행 (pipeline/ 폴더에서):
    uv run python ../evaluation/detect_first_frames.py <영상 폴더> <YOLO 가중치>
"""

import json
import sys
import unicodedata
from pathlib import Path

from pipeline.still import (
    StillError,
    build_detections,
    detect_vehicles,
    merge_duplicates,
    read_first_frame,
    sort_left_to_right,
)

OUT_DIR = Path(__file__).resolve().parent / "kaggle_detections"


def find_videos(video_dir: Path) -> dict[str, Path]:
    """하위 폴더까지 .mp4를 찾아 {이름: 경로}로 준다. 이름이 겹치면 멈춘다."""
    videos: dict[str, Path] = {}
    for path in sorted(video_dir.rglob("*")):
        if not path.is_file() or path.suffix.lower() != ".mp4":
            continue
        # macOS는 한글 파일 이름을 자모로 풀어 주기도 한다. 합친 꼴로 맞춰 쓴다
        name = unicodedata.normalize("NFC", path.name[:-4])
        if name in videos:
            sys.exit(f"오류: 같은 이름의 영상이 두 곳에 있습니다\n  {videos[name]}\n  {path}")
        videos[name] = path
    return videos


def main(video_dir: str, weights_path: str) -> None:
    videos = find_videos(Path(video_dir))
    if not videos:
        sys.exit(f"오류: 영상 폴더에 .mp4 파일이 없습니다: {video_dir}")

    skipped, empty, failed = 0, [], []
    for name, path in videos.items():
        out_path = OUT_DIR / f"{name}.json"
        if out_path.exists():
            skipped += 1
            continue
        try:
            image = read_first_frame(str(path))
        except StillError:
            failed.append(name)
            continue
        groups = sort_left_to_right(merge_duplicates(detect_vehicles(weights_path, image)))
        detections = build_detections(groups)
        out_path.write_text(json.dumps(detections))
        print(f"{name}: 차량 {len(detections)}대")
        if not detections:
            empty.append(name)

    made = len(videos) - skipped - len(failed)
    print(f"\n영상 {len(videos)}개 · 새로 만듦 {made}개 · 이미 있어 건너뜀 {skipped}개")
    if empty:
        print(f"차량이 하나도 잡히지 않은 영상 {len(empty)}개: " + ", ".join(empty))
    if failed:
        print(f"첫 프레임을 읽지 못한 영상 {len(failed)}개: " + ", ".join(failed))


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("사용법: python ../evaluation/detect_first_frames.py <영상 폴더> <YOLO 가중치>")
        sys.exit(2)
    try:
        main(sys.argv[1], sys.argv[2])
    except StillError as e:  # YOLO 가중치 파일이 없을 때
        sys.exit(f"오류: {e}")
