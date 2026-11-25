"""IP 기준 횟수 제한 (D-356 6번).

API 프로세스 메모리에 둔다. uvicorn 워커가 하나라 따로 저장소를 두지 않는다.
서버를 다시 켜면 0이 된다.
"""

import math
import threading
import time

_lock = threading.Lock()
_hits: dict[tuple, list[float]] = {}  # key → 창 안의 시각들
_blocked: dict[tuple, float] = {}  # key → 막힘이 풀리는 시각
_PRUNE_OVER = 10000  # 키가 이보다 많으면 지난 것을 지운다
_LONGEST_WINDOW = 3600  # 쓰는 창 중 가장 긴 것 (가입 시작 1시간)


def _now() -> float:
    return time.monotonic()


def _prune(now: float) -> None:
    for key in [k for k, t in _hits.items() if not t or t[-1] <= now - _LONGEST_WINDOW]:
        del _hits[key]
    for key in [k for k, t in _blocked.items() if t <= now]:
        del _blocked[key]


def blocked_for(*keys: tuple) -> int | None:
    """keys 중 막힌 것이 있으면 남은 초, 없으면 None."""
    now = _now()
    with _lock:
        left = max((_blocked.get(k, 0) - now for k in keys), default=0)
    return math.ceil(left) if left > 0 else None


def record_failure(key: tuple, limit: int, window: float) -> None:
    """실패를 하나 센다. window 안에 limit회가 되면 window 동안 막는다."""
    now = _now()
    with _lock:
        if len(_hits) > _PRUNE_OVER:
            _prune(now)
        hits = [t for t in _hits.get(key, []) if t > now - window]
        hits.append(now)
        if len(hits) >= limit:
            _blocked[key] = now + window
            hits = []
        _hits[key] = hits


def take(key: tuple, limit: int, window: float) -> int | None:
    """시도를 하나 센다. window 안에 이미 limit회면 세지 않고 풀릴 때까지 남은 초를 준다."""
    now = _now()
    with _lock:
        if len(_hits) > _PRUNE_OVER:
            _prune(now)
        hits = [t for t in _hits.get(key, []) if t > now - window]
        if len(hits) >= limit:
            _hits[key] = hits
            return max(1, math.ceil(hits[0] + window - now))
        hits.append(now)
        _hits[key] = hits
    return None


def clear(key: tuple) -> None:
    with _lock:
        _hits.pop(key, None)
        _blocked.pop(key, None)


def reset() -> None:
    """테스트용."""
    with _lock:
        _hits.clear()
        _blocked.clear()
