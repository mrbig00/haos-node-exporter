import asyncio
import os
import time
from typing import Any

import aiohttp

from app.domain.entity import Entity
from app.infrastructure.logger import get_logger

log = get_logger(__name__)

_HA_BASE_URL = os.environ.get("HA_BASE_URL", "http://supervisor/core")
_STATES_ENDPOINT = f"{_HA_BASE_URL}/api/states"


class HaClient:
    def __init__(self, timeout_seconds: int = 10, cache_seconds: int = 15) -> None:
        self._timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        self._cache_seconds = cache_seconds
        self._cache: list[Entity] | None = None
        self._cache_ts: float = 0.0
        self._lock = asyncio.Lock()

    @property
    def _token(self) -> str:
        token = os.environ.get("SUPERVISOR_TOKEN", "")
        if not token:
            log.warning("SUPERVISOR_TOKEN is not set")
        return token

    async def get_entities(self) -> list[Entity]:
        async with self._lock:
            now = time.monotonic()
            if self._cache is not None and (now - self._cache_ts) < self._cache_seconds:
                return self._cache

            entities = await self._fetch()
            self._cache = entities
            self._cache_ts = now
            return entities

    async def _fetch(self) -> list[Entity]:
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }
        try:
            async with aiohttp.ClientSession(timeout=self._timeout) as session:
                async with session.get(_STATES_ENDPOINT, headers=headers) as resp:
                    resp.raise_for_status()
                    data: list[dict[str, Any]] = await resp.json()
                    entities = [
                        Entity(
                            entity_id=item["entity_id"],
                            state=str(item.get("state", "")),
                            attributes=dict(item.get("attributes", {})),
                        )
                        for item in data
                    ]
                    log.info("Fetched %d entities from Home Assistant", len(entities))
                    return entities
        except aiohttp.ClientError as exc:
            log.error("Failed to fetch entities from HA: %s", exc)
            raise
        except Exception as exc:
            log.error("Unexpected error fetching entities: %s", exc)
            raise
