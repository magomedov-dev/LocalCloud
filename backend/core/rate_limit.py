"""Лимитер частоты запросов со скользящим окном.

Используется для защиты чувствительных endpoint'ов (логин, заявки на
регистрацию, проверка доступа к публичным ссылкам) от перебора. Счётчики
хранятся в памяти процесса: при нескольких uvicorn-worker'ах суммарный лимит
кратен их числу, что остаётся жёстким ограничением по сравнению с отсутствием
лимита. Перебор пароля конкретной публичной ссылки дополнительно ограничен
блокировкой на уровне БД (см. ``PublicLinksService``), общей для всех
процессов.

Модуль не зависит от слоёв приложения и пригоден для unit-тестирования.
"""

from __future__ import annotations

import time
from collections import deque
from threading import Lock


class SlidingWindowRateLimiter:
    """Лимитер «не более N событий за последние W секунд» по ключу.

    Хранит таймстемпы событий в deque на каждый ключ. Очистка устаревших
    таймстемпов выполняется при обращении к ключу; полностью устаревшие ключи
    периодически выметаются, чтобы память не росла от разовых клиентов.

    Attributes:
        limit: Максимальное число событий в окне.
        window_seconds: Размер скользящего окна в секундах.
    """

    # Порог числа ключей, после которого при очередном обращении запускается
    # полная уборка устаревших ключей.
    _PRUNE_THRESHOLD = 10_000

    def __init__(self, *, limit: int, window_seconds: float) -> None:
        """Инициализирует лимитер.

        Args:
            limit: Максимальное число событий в окне (не меньше 1).
            window_seconds: Размер окна в секундах (больше 0).

        Raises:
            ValueError: Если параметры вне допустимых границ.
        """

        if limit < 1:
            raise ValueError("limit должен быть не меньше 1.")
        if window_seconds <= 0:
            raise ValueError("window_seconds должен быть больше нуля.")
        self.limit = limit
        self.window_seconds = float(window_seconds)
        self._events: dict[str, deque[float]] = {}
        self._lock = Lock()

    def acquire(self, key: str, *, now: float | None = None) -> float | None:
        """Регистрирует событие по ключу, если лимит не исчерпан.

        Args:
            key: Ключ лимита (например, ``"login:1.2.3.4"``).
            now: Текущий момент в секундах (по умолчанию ``time.monotonic()``).
                Параметр нужен для детерминированных тестов.

        Returns:
            ``None``, если событие разрешено и зарегистрировано. Иначе — число
            секунд до момента, когда лимит снова позволит событие
            (для заголовка ``Retry-After``).
        """

        moment = time.monotonic() if now is None else now
        threshold = moment - self.window_seconds

        with self._lock:
            if len(self._events) > self._PRUNE_THRESHOLD:
                self._prune(threshold)

            events = self._events.get(key)
            if events is None:
                events = deque()
                self._events[key] = events

            while events and events[0] <= threshold:
                events.popleft()

            if len(events) >= self.limit:
                return max(0.0, events[0] + self.window_seconds - moment)

            events.append(moment)
            return None

    def _prune(self, threshold: float) -> None:
        """Удаляет ключи, у которых не осталось событий в окне."""

        stale = [
            key
            for key, events in self._events.items()
            if not events or events[-1] <= threshold
        ]
        for key in stale:
            del self._events[key]
