"""Юнит-тесты для лимитера частоты запросов (core/rate_limit.py)."""
from __future__ import annotations

import pytest

from core.rate_limit import SlidingWindowRateLimiter


class TestSlidingWindowRateLimiter:
    def test_allows_up_to_limit(self) -> None:
        limiter = SlidingWindowRateLimiter(limit=3, window_seconds=60)
        assert limiter.acquire("k", now=0.0) is None
        assert limiter.acquire("k", now=1.0) is None
        assert limiter.acquire("k", now=2.0) is None

    def test_blocks_over_limit_and_reports_retry_after(self) -> None:
        limiter = SlidingWindowRateLimiter(limit=2, window_seconds=60)
        assert limiter.acquire("k", now=0.0) is None
        assert limiter.acquire("k", now=10.0) is None
        retry_after = limiter.acquire("k", now=20.0)
        # Первое событие (t=0) выйдет из окна в t=60 → ждать 40 секунд.
        assert retry_after == pytest.approx(40.0)

    def test_window_slides_and_allows_again(self) -> None:
        limiter = SlidingWindowRateLimiter(limit=1, window_seconds=30)
        assert limiter.acquire("k", now=0.0) is None
        assert limiter.acquire("k", now=10.0) is not None
        # Событие t=0 вышло из окна → лимит снова доступен.
        assert limiter.acquire("k", now=31.0) is None

    def test_keys_are_isolated(self) -> None:
        limiter = SlidingWindowRateLimiter(limit=1, window_seconds=60)
        assert limiter.acquire("a", now=0.0) is None
        assert limiter.acquire("a", now=1.0) is not None
        # Другой ключ имеет собственный счётчик.
        assert limiter.acquire("b", now=1.0) is None

    def test_blocked_attempt_not_counted(self) -> None:
        limiter = SlidingWindowRateLimiter(limit=1, window_seconds=30)
        assert limiter.acquire("k", now=0.0) is None
        # Отклонённые попытки не продлевают блокировку.
        assert limiter.acquire("k", now=10.0) is not None
        assert limiter.acquire("k", now=20.0) is not None
        assert limiter.acquire("k", now=31.0) is None

    def test_invalid_params_rejected(self) -> None:
        with pytest.raises(ValueError):
            SlidingWindowRateLimiter(limit=0, window_seconds=60)
        with pytest.raises(ValueError):
            SlidingWindowRateLimiter(limit=1, window_seconds=0)

    def test_prune_removes_stale_keys(self) -> None:
        limiter = SlidingWindowRateLimiter(limit=1, window_seconds=10)
        limiter.acquire("old", now=0.0)
        limiter.acquire("fresh", now=100.0)
        limiter._prune(threshold=90.0)
        assert "old" not in limiter._events
        assert "fresh" in limiter._events
