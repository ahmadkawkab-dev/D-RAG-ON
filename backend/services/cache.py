"""Small process-local TTL/LRU cache used by latency-sensitive services."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from time import monotonic
from typing import Callable, Generic, TypeVar


KeyT = TypeVar("KeyT")
ValueT = TypeVar("ValueT")


@dataclass(frozen=True)
class CacheInfo:
    hits: int
    misses: int
    size: int
    max_size: int


class TTLCache(Generic[KeyT, ValueT]):
    """Bounded LRU cache whose entries expire after a monotonic TTL."""

    def __init__(
        self,
        max_size: int,
        ttl_seconds: float,
        *,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self._clock = clock
        self._items: OrderedDict[KeyT, tuple[float, ValueT]] = OrderedDict()
        self._hits = 0
        self._misses = 0

    def get(self, key: KeyT) -> ValueT | None:
        if self.max_size == 0:
            self._misses += 1
            return None
        item = self._items.get(key)
        if item is None:
            self._misses += 1
            return None
        expires_at, value = item
        if expires_at <= self._clock():
            del self._items[key]
            self._misses += 1
            return None
        self._items.move_to_end(key)
        self._hits += 1
        return value

    def put(self, key: KeyT, value: ValueT) -> None:
        if self.max_size == 0:
            return
        self._items[key] = (self._clock() + self.ttl_seconds, value)
        self._items.move_to_end(key)
        while len(self._items) > self.max_size:
            self._items.popitem(last=False)

    def clear(self) -> None:
        self._items.clear()

    def info(self) -> CacheInfo:
        return CacheInfo(
            hits=self._hits,
            misses=self._misses,
            size=len(self._items),
            max_size=self.max_size,
        )
