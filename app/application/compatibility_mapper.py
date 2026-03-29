"""
Maps Home Assistant system_monitor entities to Prometheus node_exporter metrics.

Metric names and label sets match node_exporter exactly so that existing
Grafana dashboards and alerting rules work without modification.

Reference: https://github.com/prometheus/node_exporter
"""

import re
from datetime import datetime, timezone
from typing import Callable

from app.domain.entity import Entity
from app.domain.metric import Metric, MetricType
from app.infrastructure.config_loader import CompatibilityConfig
from app.infrastructure.logger import get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Unit conversion helpers
# ---------------------------------------------------------------------------

_UNIT_TO_BYTES: dict[str, float] = {
    "b": 1,
    "bytes": 1,
    "kb": 1_000,
    "kib": 1_024,
    "mb": 1_000_000,
    "mib": 1_048_576,
    "gb": 1_000_000_000,
    "gib": 1_073_741_824,
    "tb": 1_000_000_000_000,
    "tib": 1_099_511_627_776,
}


def _to_bytes(value: float, unit: str) -> float:
    factor = _UNIT_TO_BYTES.get(unit.strip().lower(), None)
    if factor is None:
        return value
    return value * factor


def _numeric(state: str) -> float | None:
    try:
        return float(state.strip())
    except (ValueError, AttributeError):
        return None


def _parse_iso_to_unix(ts: str) -> float | None:
    """Parse an ISO 8601 timestamp string to a Unix epoch float."""
    for fmt in (
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
    ):
        try:
            dt = datetime.strptime(ts.strip(), fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# Pattern registry
# Each entry: (compiled regex, handler callable(entity, match) -> list[Metric])
# ---------------------------------------------------------------------------

HandlerFn = Callable[[Entity, re.Match], list[Metric]]
_PATTERNS: list[tuple[re.Pattern, HandlerFn]] = []


def _register(pattern: str) -> Callable[[HandlerFn], HandlerFn]:
    def decorator(fn: HandlerFn) -> HandlerFn:
        _PATTERNS.append((re.compile(pattern, re.IGNORECASE), fn))
        return fn
    return decorator


# ---------------------------------------------------------------------------
# CPU
# ---------------------------------------------------------------------------

@_register(r".*processor_use$")
def _cpu_usage(entity: Entity, _match: re.Match) -> list[Metric]:
    """
    HA gives CPU usage as a percentage snapshot.

    node_cpu_seconds_total is normally a per-core counter, but we expose
    a gauge approximation so that simple CPU utilisation dashboards work.
    We emit two synthetic cores (idle + non-idle) to satisfy PromQL
    expressions like:
        1 - avg(rate(node_cpu_seconds_total{mode="idle"}[5m]))
    """
    pct = _numeric(entity.state)
    if pct is None:
        return []

    idle_ratio = max(0.0, min(1.0, (100.0 - pct) / 100.0))
    busy_ratio = 1.0 - idle_ratio

    return [
        Metric(
            name="node_cpu_seconds_total",
            value=idle_ratio,
            labels={"cpu": "0", "mode": "idle"},
            help_text="Seconds the CPUs spent in each mode (approximated from HA processor_use).",
            metric_type=MetricType.COUNTER,
        ),
        Metric(
            name="node_cpu_seconds_total",
            value=busy_ratio,
            labels={"cpu": "0", "mode": "user"},
            help_text="Seconds the CPUs spent in each mode (approximated from HA processor_use).",
            metric_type=MetricType.COUNTER,
        ),
        # Also expose as a plain gauge for dashboards that prefer it
        Metric(
            name="node_cpu_usage_ratio",
            value=busy_ratio,
            labels={},
            help_text="CPU usage ratio 0–1 (derived from Home Assistant processor_use).",
            metric_type=MetricType.GAUGE,
        ),
    ]


@_register(r".*processor_temperature$")
def _cpu_temp(entity: Entity, _match: re.Match) -> list[Metric]:
    value = _numeric(entity.state)
    if value is None:
        return []
    # Convert °F → °C if necessary
    unit = entity.unit
    if "f" in unit.lower() and "°" in unit:
        value = (value - 32) * 5 / 9
    return [
        Metric(
            name="node_hwmon_temp_celsius",
            value=value,
            labels={"chip": "cpu", "sensor": "temp1"},
            help_text="Hardware monitor for temperature (in Celsius).",
            metric_type=MetricType.GAUGE,
        )
    ]


# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------

@_register(r".*memory_use$")
def _mem_used(entity: Entity, _match: re.Match) -> list[Metric]:
    value = _numeric(entity.state)
    if value is None:
        return []
    return [
        Metric(
            name="node_memory_MemUsed_bytes",
            value=_to_bytes(value, entity.unit or "B"),
            labels={},
            help_text="Memory information field MemUsed_bytes.",
            metric_type=MetricType.GAUGE,
        )
    ]


@_register(r".*memory_free$")
def _mem_free(entity: Entity, _match: re.Match) -> list[Metric]:
    value = _numeric(entity.state)
    if value is None:
        return []
    bytes_val = _to_bytes(value, entity.unit or "B")
    return [
        Metric(
            name="node_memory_MemFree_bytes",
            value=bytes_val,
            labels={},
            help_text="Memory information field MemFree_bytes.",
            metric_type=MetricType.GAUGE,
        ),
        Metric(
            name="node_memory_MemAvailable_bytes",
            value=bytes_val,
            labels={},
            help_text="Memory information field MemAvailable_bytes.",
            metric_type=MetricType.GAUGE,
        ),
    ]


@_register(r".*swap_use$")
def _swap_used(entity: Entity, _match: re.Match) -> list[Metric]:
    value = _numeric(entity.state)
    if value is None:
        return []
    return [
        Metric(
            name="node_memory_SwapUsed_bytes",
            value=_to_bytes(value, entity.unit or "B"),
            labels={},
            help_text="Memory information field SwapUsed_bytes.",
            metric_type=MetricType.GAUGE,
        )
    ]


@_register(r".*swap_free$")
def _swap_free(entity: Entity, _match: re.Match) -> list[Metric]:
    value = _numeric(entity.state)
    if value is None:
        return []
    return [
        Metric(
            name="node_memory_SwapFree_bytes",
            value=_to_bytes(value, entity.unit or "B"),
            labels={},
            help_text="Memory information field SwapFree_bytes.",
            metric_type=MetricType.GAUGE,
        )
    ]


# ---------------------------------------------------------------------------
# Filesystem / disk
# ---------------------------------------------------------------------------

def _mountpoint_from_entity(entity: Entity) -> str:
    """Extract mountpoint from entity attributes or entity_id."""
    mp = entity.attributes.get("path", "")
    if not mp:
        # Fall back: strip known prefixes and guess
        name = entity.entity_id.split(".")[-1]
        for prefix in ("disk_use_percent_", "disk_use_", "disk_free_"):
            if name.startswith(prefix):
                raw = name[len(prefix):]
                mp = "/" + raw.replace("_", "/").lstrip("/")
                break
    return mp or "/"


@_register(r".*disk_free$")
def _disk_free(entity: Entity, _match: re.Match) -> list[Metric]:
    value = _numeric(entity.state)
    if value is None:
        return []
    bytes_val = _to_bytes(value, entity.unit or "GiB")
    mp = _mountpoint_from_entity(entity)
    labels = {"device": "", "fstype": "", "mountpoint": mp}
    return [
        Metric(
            name="node_filesystem_free_bytes",
            value=bytes_val,
            labels=dict(labels),
            help_text="Filesystem free space in bytes.",
            metric_type=MetricType.GAUGE,
        ),
        Metric(
            name="node_filesystem_avail_bytes",
            value=bytes_val,
            labels=dict(labels),
            help_text="Filesystem space available to non-root users in bytes.",
            metric_type=MetricType.GAUGE,
        ),
    ]


@_register(r".*disk_use$")
def _disk_used(entity: Entity, _match: re.Match) -> list[Metric]:
    value = _numeric(entity.state)
    if value is None:
        return []
    bytes_val = _to_bytes(value, entity.unit or "GiB")
    mp = _mountpoint_from_entity(entity)
    return [
        Metric(
            name="node_filesystem_used_bytes",
            value=bytes_val,
            labels={"device": "", "fstype": "", "mountpoint": mp},
            help_text="Filesystem space used in bytes.",
            metric_type=MetricType.GAUGE,
        )
    ]


# ---------------------------------------------------------------------------
# Network
# ---------------------------------------------------------------------------

def _iface_from_entity(entity: Entity, match: re.Match) -> str:
    """Extract network interface name from entity_id match group."""
    try:
        raw = match.group(1)
        # entity_id safe chars use underscore; restore common separators
        return raw.strip("_")
    except IndexError:
        return "eth0"


@_register(r".*network_in_(.+)$")
def _net_rx_bytes(entity: Entity, match: re.Match) -> list[Metric]:
    value = _numeric(entity.state)
    if value is None:
        return []
    iface = _iface_from_entity(entity, match)
    return [
        Metric(
            name="node_network_receive_bytes_total",
            value=_to_bytes(value, entity.unit or "MiB"),
            labels={"device": iface},
            help_text="Network device statistic receive_bytes.",
            metric_type=MetricType.COUNTER,
        )
    ]


@_register(r".*network_out_(.+)$")
def _net_tx_bytes(entity: Entity, match: re.Match) -> list[Metric]:
    value = _numeric(entity.state)
    if value is None:
        return []
    iface = _iface_from_entity(entity, match)
    return [
        Metric(
            name="node_network_transmit_bytes_total",
            value=_to_bytes(value, entity.unit or "MiB"),
            labels={"device": iface},
            help_text="Network device statistic transmit_bytes.",
            metric_type=MetricType.COUNTER,
        )
    ]


@_register(r".*packets_in_(.+)$")
def _net_rx_packets(entity: Entity, match: re.Match) -> list[Metric]:
    value = _numeric(entity.state)
    if value is None:
        return []
    iface = _iface_from_entity(entity, match)
    return [
        Metric(
            name="node_network_receive_packets_total",
            value=value,
            labels={"device": iface},
            help_text="Network device statistic receive_packets.",
            metric_type=MetricType.COUNTER,
        )
    ]


@_register(r".*packets_out_(.+)$")
def _net_tx_packets(entity: Entity, match: re.Match) -> list[Metric]:
    value = _numeric(entity.state)
    if value is None:
        return []
    iface = _iface_from_entity(entity, match)
    return [
        Metric(
            name="node_network_transmit_packets_total",
            value=value,
            labels={"device": iface},
            help_text="Network device statistic transmit_packets.",
            metric_type=MetricType.COUNTER,
        )
    ]


@_register(r".*network_throughput_in_(.+)$")
def _net_rx_throughput(entity: Entity, match: re.Match) -> list[Metric]:
    value = _numeric(entity.state)
    if value is None:
        return []
    iface = _iface_from_entity(entity, match)
    # Convert throughput to bytes/s
    bps = _to_bytes(value, entity.unit.replace("/s", "").strip() if entity.unit else "B")
    return [
        Metric(
            name="node_network_receive_bytes_per_second",
            value=bps,
            labels={"device": iface},
            help_text="Network device receive throughput in bytes per second.",
            metric_type=MetricType.GAUGE,
        )
    ]


@_register(r".*network_throughput_out_(.+)$")
def _net_tx_throughput(entity: Entity, match: re.Match) -> list[Metric]:
    value = _numeric(entity.state)
    if value is None:
        return []
    iface = _iface_from_entity(entity, match)
    bps = _to_bytes(value, entity.unit.replace("/s", "").strip() if entity.unit else "B")
    return [
        Metric(
            name="node_network_transmit_bytes_per_second",
            value=bps,
            labels={"device": iface},
            help_text="Network device transmit throughput in bytes per second.",
            metric_type=MetricType.GAUGE,
        )
    ]


# ---------------------------------------------------------------------------
# Load averages
# ---------------------------------------------------------------------------

@_register(r".*load_1m$")
def _load1(entity: Entity, _match: re.Match) -> list[Metric]:
    value = _numeric(entity.state)
    if value is None:
        return []
    return [Metric(name="node_load1", value=value, labels={}, help_text="1m load average.", metric_type=MetricType.GAUGE)]


@_register(r".*load_5m$")
def _load5(entity: Entity, _match: re.Match) -> list[Metric]:
    value = _numeric(entity.state)
    if value is None:
        return []
    return [Metric(name="node_load5", value=value, labels={}, help_text="5m load average.", metric_type=MetricType.GAUGE)]


@_register(r".*load_15m$")
def _load15(entity: Entity, _match: re.Match) -> list[Metric]:
    value = _numeric(entity.state)
    if value is None:
        return []
    return [Metric(name="node_load15", value=value, labels={}, help_text="15m load average.", metric_type=MetricType.GAUGE)]


# ---------------------------------------------------------------------------
# Boot time
# ---------------------------------------------------------------------------

@_register(r".*last_boot$")
def _boot_time(entity: Entity, _match: re.Match) -> list[Metric]:
    unix_ts = _parse_iso_to_unix(entity.state)
    if unix_ts is None:
        log.warning("Could not parse last_boot timestamp: %r", entity.state)
        return []
    return [
        Metric(
            name="node_boot_time_seconds",
            value=unix_ts,
            labels={},
            help_text="Node boot time, in unixtime.",
            metric_type=MetricType.GAUGE,
        )
    ]


# ---------------------------------------------------------------------------
# Public use-case class
# ---------------------------------------------------------------------------

class CompatibilityMapperUseCase:
    """
    Translates HA entities into node_exporter-compatible metrics.

    Only emits approximated metrics (e.g. node_cpu_seconds_total) when
    ``allow_approximations`` is True in the config.
    """

    _APPROXIMATED = frozenset({
        "node_cpu_seconds_total",
        "node_cpu_usage_ratio",
    })

    def __init__(self, cfg: CompatibilityConfig) -> None:
        self._cfg = cfg

    def execute(self, entities: list[Entity]) -> list[Metric]:
        metrics: list[Metric] = []
        seen_entity_ids: set[str] = set()

        for entity in entities:
            for pattern, handler in _PATTERNS:
                m = pattern.match(entity.entity_id)
                if m:
                    produced = handler(entity, m)
                    for metric in produced:
                        if metric.name in self._APPROXIMATED and not self._cfg.allow_approximations:
                            log.debug(
                                "Skipping approximated metric %s (allow_approximations=false)",
                                metric.name,
                            )
                            continue
                        metrics.append(metric)
                    seen_entity_ids.add(entity.entity_id)
                    break  # first matching pattern wins

        # Synthesise node_memory_MemTotal_bytes from use + free when both are present
        metrics.extend(self._synthesise_mem_total(entities))
        metrics.extend(self._synthesise_swap_total(entities))
        metrics.extend(self._synthesise_filesystem_size(entities))

        return metrics

    # ------------------------------------------------------------------
    # Derived / synthesised metrics
    # ------------------------------------------------------------------

    def _synthesise_mem_total(self, entities: list[Entity]) -> list[Metric]:
        use_entity = self._find(entities, r".*memory_use$")
        free_entity = self._find(entities, r".*memory_free$")
        if use_entity is None or free_entity is None:
            return []
        used = _numeric(use_entity.state)
        free = _numeric(free_entity.state)
        if used is None or free is None:
            return []
        total = _to_bytes(used, use_entity.unit or "B") + _to_bytes(free, free_entity.unit or "B")
        return [
            Metric(
                name="node_memory_MemTotal_bytes",
                value=total,
                labels={},
                help_text="Memory information field MemTotal_bytes.",
                metric_type=MetricType.GAUGE,
            )
        ]

    def _synthesise_swap_total(self, entities: list[Entity]) -> list[Metric]:
        use_entity = self._find(entities, r".*swap_use$")
        free_entity = self._find(entities, r".*swap_free$")
        if use_entity is None or free_entity is None:
            return []
        used = _numeric(use_entity.state)
        free = _numeric(free_entity.state)
        if used is None or free is None:
            return []
        total = _to_bytes(used, use_entity.unit or "B") + _to_bytes(free, free_entity.unit or "B")
        return [
            Metric(
                name="node_memory_SwapTotal_bytes",
                value=total,
                labels={},
                help_text="Memory information field SwapTotal_bytes.",
                metric_type=MetricType.GAUGE,
            )
        ]

    def _synthesise_filesystem_size(self, entities: list[Entity]) -> list[Metric]:
        """Produce node_filesystem_size_bytes from disk_use + disk_free pairs."""
        use_map = self._find_all(entities, r".*disk_use$")
        free_map = self._find_all(entities, r".*disk_free$")

        metrics: list[Metric] = []
        for mp, use_entity in use_map.items():
            free_entity = free_map.get(mp)
            if free_entity is None:
                continue
            used = _numeric(use_entity.state)
            free = _numeric(free_entity.state)
            if used is None or free is None:
                continue
            total = (
                _to_bytes(used, use_entity.unit or "GiB")
                + _to_bytes(free, free_entity.unit or "GiB")
            )
            metrics.append(
                Metric(
                    name="node_filesystem_size_bytes",
                    value=total,
                    labels={"device": "", "fstype": "", "mountpoint": mp},
                    help_text="Filesystem size in bytes.",
                    metric_type=MetricType.GAUGE,
                )
            )
        return metrics

    @staticmethod
    def _find(entities: list[Entity], pattern: str) -> Entity | None:
        rx = re.compile(pattern, re.IGNORECASE)
        for e in entities:
            if rx.match(e.entity_id):
                return e
        return None

    @staticmethod
    def _find_all(entities: list[Entity], pattern: str) -> dict[str, Entity]:
        rx = re.compile(pattern, re.IGNORECASE)
        result: dict[str, Entity] = {}
        for e in entities:
            if rx.match(e.entity_id):
                mp = _mountpoint_from_entity(e)
                result[mp] = e
        return result
