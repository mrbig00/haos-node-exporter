import traceback

from aiohttp import web

from app.application.collect_entities import CollectEntitiesUseCase
from app.application.compatibility_mapper import CompatibilityMapperUseCase
from app.application.render_metrics import RenderMetricsUseCase
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


class MetricsServer:
    def __init__(
        self,
        config: Config,
        collect: CollectEntitiesUseCase,
        transform: TransformToMetricsUseCase,
        compat_mapper: CompatibilityMapperUseCase,
        renderer: RenderMetricsUseCase,
    ) -> None:
        self._config = config
        self._collect = collect
        self._transform = transform
        self._compat_mapper = compat_mapper
        self._renderer = renderer

    async def handle_metrics(self, request: web.Request) -> web.Response:
        try:
            entities = await self._collect.execute()
        except Exception as exc:
            log.error("Failed to collect entities from HA API: %s\n%s", exc, traceback.format_exc())
            output = self._renderer.execute([_DOWN_METRIC])
            return web.Response(text=output, content_type="text/plain", charset="utf-8", status=500)

        metrics: list[Metric] = [_UP_METRIC]
        mode = self._config.compatibility.mode

        if mode in ("native", "dual"):
            metrics.extend(self._transform.execute(entities))

        if mode in ("node_exporter", "dual"):
            metrics.extend(self._compat_mapper.execute(entities))

        output = self._renderer.execute(metrics)
        return web.Response(
            text=output,
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
