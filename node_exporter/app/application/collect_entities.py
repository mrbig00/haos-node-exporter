from app.domain.entity import Entity
from app.infrastructure.ha_client import HaClient
from app.infrastructure.logger import get_logger

log = get_logger(__name__)


class CollectEntitiesUseCase:
    def __init__(self, client: HaClient) -> None:
        self._client = client

    async def execute(self) -> list[Entity]:
        return await self._client.get_entities()
