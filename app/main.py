import asyncio
import signal

from app.application.collect_entities import CollectEntitiesUseCase
from app.application.compatibility_mapper import CompatibilityMapperUseCase
from app.application.render_metrics import RenderMetricsUseCase
from app.application.transform_metrics import TransformToMetricsUseCase
from app.infrastructure.config_loader import load_config
from app.infrastructure.ha_client import HaClient
from app.infrastructure.logger import configure_root, get_logger
from app.presentation.http_server import MetricsServer

log = get_logger(__name__)


async def main() -> None:
    configure_root("INFO")
    config = load_config()

    log.info(
        "Starting haos-node-exporter port=%d mode=%s",
        config.port,
        config.compatibility.mode,
    )

    client = HaClient(
        timeout_seconds=config.scrape.timeout_seconds,
        cache_seconds=config.scrape.cache_seconds,
    )

    server = MetricsServer(
        config=config,
        collect=CollectEntitiesUseCase(client),
        transform=TransformToMetricsUseCase(config),
        compat_mapper=CompatibilityMapperUseCase(config.compatibility),
        renderer=RenderMetricsUseCase(),
    )

    await server.run()

    # Keep running until SIGTERM / SIGINT
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    await stop.wait()
    log.info("Shutting down.")


if __name__ == "__main__":
    asyncio.run(main())
