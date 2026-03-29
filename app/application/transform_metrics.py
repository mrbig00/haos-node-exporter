import re

from app.domain.entity import Entity
from app.domain.metric import Metric, MetricType
from app.infrastructure.config_loader import Config
from app.infrastructure.logger import get_logger

log = get_logger(__name__)

_SAFE_LABEL = re.compile(r"[^a-zA-Z0-9_]")
_SAFE_NAME = re.compile(r"[^a-zA-Z0-9_:]")


def _safe_label_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _safe_metric_name(name: str) -> str:
    return _SAFE_NAME.sub("_", name)


def _to_numeric(state: str, mapping: dict[str, float]) -> float | None:
    lower = state.strip().lower()
    if lower in mapping:
        return mapping[lower]
    try:
        return float(lower)
    except ValueError:
        return None


class TransformToMetricsUseCase:
    """Converts filtered HA entities to native homeassistant_* Prometheus metrics."""

    def __init__(self, config: Config) -> None:
        self._config = config

    def execute(self, entities: list[Entity]) -> list[Metric]:
        filtered = self._filter(entities)
        metrics: list[Metric] = []
        for entity in filtered:
            metric = self._convert(entity)
            if metric is not None:
                metrics.append(metric)
        return metrics

    def _filter(self, entities: list[Entity]) -> list[Entity]:
        cfg = self._config
        result = []
        for e in entities:
            if cfg.include_entities and e.entity_id not in cfg.include_entities:
                continue
            if e.entity_id in cfg.exclude_entities:
                continue
            if cfg.include_domains and e.domain not in cfg.include_domains:
                continue
            result.append(e)
        return result

    def _convert(self, entity: Entity) -> Metric | None:
        value = _to_numeric(entity.state, self._config.state_mapping)
        if value is None:
            log.debug("Skipping non-numeric entity %s (state=%r)", entity.entity_id, entity.state)
            return None

        name = "homeassistant_" + _safe_metric_name(entity.entity_id.replace(".", "_"))
        labels: dict[str, str] = {"entity_id": entity.entity_id}

        if self._config.label_strategy.include_domain:
            labels["domain"] = entity.domain

        if self._config.label_strategy.include_friendly_name:
            labels["friendly_name"] = entity.friendly_name

        if entity.unit:
            labels["unit"] = entity.unit

        metric_type = MetricType.GAUGE
        if entity.state_class == "total_increasing":
            metric_type = MetricType.COUNTER

        help_text = f"Home Assistant entity {entity.entity_id}"
        if entity.device_class:
            help_text += f" ({entity.device_class})"

        return Metric(
            name=name,
            value=value,
            labels=labels,
            help_text=help_text,
            metric_type=metric_type,
        )
