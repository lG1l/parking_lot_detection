"""5-나 트랙 빼기: 5-가의 트랙 파일로 지나가기만 한 트랙을 뺀다 (06장 6.5, D-332).

YOLO를 다시 돌리지 않고 트랙 파일(tracks.jsonl)과 YOLO 구간 파일(yolo_ranges.json)만 읽는다.
"""

import sys

from pipeline.candidates.crop import CropError
from pipeline.candidates.floor_map import trust_range, trust_text
from pipeline.candidates.inputs import InputError, load_input
from pipeline.candidates.preview import video_size
from pipeline.candidates.roi import RoiError


def run_track_filter(
    video_path: str, input_path: str, tracks_dir: str, out_dir: str, make_video: bool
) -> None:
    """트랙 빼기를 한 번 돌린다. tracks_dir은 5-가 결과 폴더, out_dir은 5-나 결과 폴더다."""
    width, height = video_size(video_path)
    data = load_input(input_path, width, height)
    measured = trust_range(data.floor_corners, data.front_edge, data.damage_edges)
    print(trust_text(measured))


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--no-video"]
    if len(args) != 4:
        print(
            "사용법: python -m pipeline.candidates.track_filter "
            "<영상> <입력 JSON> <5-가 결과 폴더> <출력 폴더> [--no-video]"
        )
        sys.exit(2)
    try:
        run_track_filter(*args, make_video="--no-video" not in sys.argv)
    except (InputError, CropError, RoiError, FileNotFoundError) as e:
        print(f"오류: {e}")
        sys.exit(1)
