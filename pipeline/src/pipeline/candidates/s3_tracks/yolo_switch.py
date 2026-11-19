"""채널 A 켜고 끄기 판정 (06장 6.5 "채널 A 켜고 끄기" 규칙 1~4·7·8, D-97, D-199, D-247).

분석 프레임마다 (시각, ROI 움직임 여부)만 받아 "이 프레임에 YOLO를 돌릴지"와
"그 전에 링 버퍼에서 꺼내 먼저 돌릴 프레임 시각"을 알려 준다.
영상·모델·MOG2를 모른다. 숫자 계산뿐이라 영상 없이 테스트한다.
"""

from collections import deque
from dataclasses import dataclass, field

from pipeline.candidates.s2_motion.channel_b import MOG2_STABLE_SEC

# 01장 1.6 "채널 A 켜는 구간" (D-247). 초기값이다
YOLO_BEFORE_SEC = 10  # 켤 때 거슬러 올라가는 시간. 링 버퍼 길이와 같다
YOLO_AFTER_SEC = 5  # 마지막 ROI 움직임 뒤에 더 켜 두는 시간

# 시각을 소수로 다루다 생기는 오차를 흡수하는 값 (초)
_TIME_EPS = 1e-6


@dataclass
class YoloRange:
    """YOLO를 끊김 없이 돌린 구간 하나. 시각은 그 영상 처음부터 잰 초다."""

    start_sec: float  # 처음 돌린 프레임 시각 (거슬러 돌린 프레임 포함)
    end_sec: float  # 마지막으로 돌린 프레임 시각. 켜져 있는 동안 계속 늘어난다


@dataclass(frozen=True)
class Decision:
    """프레임 한 장에 대한 판정."""

    run: bool  # 이 프레임에 YOLO를 돌린다
    # 이 프레임보다 먼저 돌려야 하는 지난 프레임의 시각 (시간 오름차순). 켜는 순간에만 채워진다
    backfill_times: list[float] = field(default_factory=list)


class YoloSwitch:
    """영상 하나에 하나 만들고, 분석 프레임을 시간순으로 한 장씩 step()에 넣는다."""

    def __init__(self) -> None:
        # 규칙 8: 영상 시작부터 MOG2 안정 시각까지는 항상 켠다.
        # "끌 시각이 안정 시각인 켜진 상태"로 시작하면 규칙 2·3을 그대로 쓸 수 있다
        self._on = True
        self._off_at = float(MOG2_STABLE_SEC)
        self._last_run_sec: float | None = None
        # 꺼져 있는 동안 지나간 프레임 시각. 거슬러 돌릴 프레임을 고르는 데 쓴다
        self._recent_times: deque[float] = deque()
        self.ranges: list[YoloRange] = []

    def step(self, time_sec: float, roi_motion: bool) -> Decision:
        if self._on:
            decision = Decision(run=True)
        elif roi_motion:
            decision = Decision(run=True, backfill_times=self._turn_on(time_sec))
        else:
            self._remember(time_sec)
            return Decision(run=False)

        if roi_motion:
            # 규칙 2: 움직임이 있을 때마다 끌 시각을 뒤로 민다
            self._off_at = max(self._off_at, time_sec + YOLO_AFTER_SEC)
        self._record_run(time_sec)
        if time_sec >= self._off_at - _TIME_EPS:
            # 규칙 3: 끌 시각의 프레임까지 돌리고 끈다
            self._on = False
        return decision

    def _turn_on(self, time_sec: float) -> list[float]:
        """규칙 1·4: 켜면서 거슬러 돌릴 프레임 시각을 고른다."""
        from_sec = time_sec - YOLO_BEFORE_SEC
        backfill = [t for t in self._recent_times if t >= from_sec - _TIME_EPS]
        self._recent_times.clear()
        self._on = True
        self._off_at = time_sec  # 바로 뒤 규칙 2가 뒤 시간을 더해 다시 정한다

        # 규칙 4: 거슬러 올라갈 범위가 이미 돌린 프레임에 닿으면 새 구간을 열지 않는다.
        # _recent_times에는 꺼진 뒤의 프레임만 있어서 이미 돌린 프레임은 backfill에 없다
        overlaps = self._last_run_sec is not None and from_sec <= self._last_run_sec + _TIME_EPS
        if not overlaps:
            start = backfill[0] if backfill else time_sec
            self.ranges.append(YoloRange(start, start))
        return backfill

    def _record_run(self, time_sec: float) -> None:
        """YOLO를 돌린 프레임을 구간에 반영한다. 규칙 7(영상 끝)은 이것으로 지켜진다."""
        if not self.ranges:
            # 영상의 첫 프레임. 규칙 8의 구간은 영상 시작부터 하나다
            self.ranges.append(YoloRange(time_sec, time_sec))
        self.ranges[-1].end_sec = time_sec
        self._last_run_sec = time_sec

    def _remember(self, time_sec: float) -> None:
        """꺼진 동안의 프레임 시각을 거슬러 올라가는 시간만큼만 들고 있는다."""
        self._recent_times.append(time_sec)
        while self._recent_times[0] < time_sec - YOLO_BEFORE_SEC - _TIME_EPS:
            self._recent_times.popleft()
