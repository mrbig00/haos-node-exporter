import traceback

from aiohttp import web

from app.application.collect_entities import CollectEntitiesUseCase
from app.application.compatibility_mapper import CompatibilityMapperUseCase
from app.application.render_metrics import RenderMetricsUseCase
from app.application.system_collector import SystemCollector
from app.application.transform_metrics import TransformToMetricsUseCase
from app.domain.metric import Metric, MetricType
from app.infrastructure.config_loader import Config
from app.infrastructure.logger import get_logger

log = get_logger(__name__)

_CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"

_UP_METRIC = Metric(
    name="homeassistant_exporter_up",
    value=1.0,
    labels={},
    help_text="1 if the exporter successfully reached Home Assistant, 0 otherwise.",
    metric_type=MetricType.GAUGE,
)
_DOWN_METRIC = Metric(
    name="homeassistant_exporter_up",
    value=0.0,
    labels={},
    help_text="1 if the exporter successfully reached Home Assistant, 0 otherwise.",
    metric_type=MetricType.GAUGE,
)


def _deduplicate(metrics: list[Metric]) -> list[Metric]:
    """
    Remove duplicate (name, labels) pairs, keeping the first occurrence.
    System collector metrics are prepended so they always win over
    compatibility_mapper approximations when both produce the same key.
    """
    seen: set[tuple] = set()
    result: list[Metric] = []
    for m in metrics:
        key = (m.name, tuple(sorted(m.labels.items())))
        if key not in seen:
            seen.add(key)
            result.append(m)
    return result


class MetricsServer:
    def __init__(
        self,
        config: Config,
        collect: CollectEntitiesUseCase,
        transform: TransformToMetricsUseCase,
        compat_mapper: CompatibilityMapperUseCase,
        renderer: RenderMetricsUseCase,
        system_collector: SystemCollector,
    ) -> None:
        self._config = config
        self._collect = collect
        self._transform = transform
        self._compat_mapper = compat_mapper
        self._renderer = renderer
        self._system_collector = system_collector

    async def handle_metrics(self, request: web.Request) -> web.Response:
        # --- 1. System metrics (always, independent of HA) ---
        system_metrics = self._system_collector.collect()

        # --- 2. HA entity metrics ---
        try:
            entities = await self._collect.execute()
            up = _UP_METRIC
        except Exception as exc:
            log.error("Failed to collect entities from HA API: %s\n%s", exc, traceback.format_exc())
            entities = []
            up = _DOWN_METRIC

        # --- 3. Assemble in priority order: system → HA ---
        metrics: list[Metric] = list(system_metrics)
        metrics.append(up)

        mode = self._config.compatibility.mode

        if mode == "native" and entities:
            # Only homeassistant_* metrics, no system metrics (clear system list).
            metrics = [up]
            metrics.extend(self._transform.execute(entities))

        elif mode == "dual" and entities:
            # homeassistant_* + node_* from HA entities (system already included above).
            metrics.extend(self._transform.execute(entities))
            metrics.extend(self._compat_mapper.execute(entities))

        # mode == "node_exporter": system_collector output only — no HA entity metrics.

        # Deduplicate: system_collector values take precedence over
        # compatibility_mapper approximations for the same (name, labels).
        metrics = _deduplicate(metrics)

        output = self._renderer.execute(metrics)
        status = 200 if up.value == 1.0 else 500
        return web.Response(
            text=output,
            status=status,
            headers={"Content-Type": _CONTENT_TYPE},
        )

    async def handle_health(self, request: web.Request) -> web.Response:
        return web.Response(text="OK")

    def build_app(self) -> web.Application:
        app = web.Application()
        app.router.add_get("/metrics", self.handle_metrics)
        app.router.add_get("/healthz", self.handle_health)
        return app

    async def run(self) -> None:
        app = self.build_app()
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", self._config.port)
        await site.start()
        log.info("Metrics server listening on port %d", self._config.port)
