import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from app.infrastructure.logger import get_logger

log = get_logger(__name__)

_OPTIONS_PATH = Path("/data/options.json")

_DEFAULTS: dict = {
    "port": 9100,
    "include_domains": ["sensor", "binary_sensor"],
    "include_entities": [],
    "exclude_entities": [],
    "label_strategy": {
        "include_friendly_name": True,
        "include_domain": True,
    },
    "state_mapping": {
        "on": 1,
        "off": 0,
        "open": 1,
        "closed": 0,
        "home": 1,
        "away": 0,
        "true": 1,
        "false": 0,
        "unlocked": 1,
        "locked": 0,
    },
    "scrape": {
        "timeout_seconds": 10,
        "cache_seconds": 15,
    },
    "compatibility": {
        "mode": "dual",
        "allow_approximations": True,
    },
}


@dataclass
class LabelStrategy:
    include_friendly_name: bool = True
    include_domain: bool = True


@dataclass
class ScrapeConfig:
    timeout_seconds: int = 10
    cache_seconds: int = 15


@dataclass
class CompatibilityConfig:
    mode: str = "dual"          # native | node_exporter | dual
    allow_approximations: bool = True


@dataclass
class Config:
    port: int = 9100
    include_domains: list[str] = field(default_factory=lambda: ["sensor", "binary_sensor"])
    include_entities: list[str] = field(default_factory=list)
    exclude_entities: list[str] = field(default_factory=list)
    label_strategy: LabelStrategy = field(default_factory=LabelStrategy)
    state_mapping: dict[str, float] = field(default_factory=dict)
    scrape: ScrapeConfig = field(default_factory=ScrapeConfig)
    compatibility: CompatibilityConfig = field(default_factory=CompatibilityConfig)


def _deep_merge(base: dict, override: dict) -> dict:
    result = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(result.get(k), dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def load_config() -> Config:
    raw: dict = dict(_DEFAULTS)

    if _OPTIONS_PATH.exists():
        try:
            with _OPTIONS_PATH.open() as f:
                user = json.load(f)
            raw = _deep_merge(raw, user)
            log.info("Loaded options from %s", _OPTIONS_PATH)
        except Exception as exc:
            log.warning("Failed to read options.json, using defaults: %s", exc)

    state_mapping = {str(k).lower(): float(v) for k, v in raw.get("state_mapping", {}).items()}

    return Config(
        port=int(raw["port"]),
        include_domains=list(raw["include_domains"]),
        include_entities=list(raw["include_entities"]),
        exclude_entities=list(raw["exclude_entities"]),
        label_strategy=LabelStrategy(
            include_friendly_name=bool(raw["label_strategy"]["include_friendly_name"]),
            include_domain=bool(raw["label_strategy"]["include_domain"]),
        ),
        state_mapping=state_mapping,
        scrape=ScrapeConfig(
            timeout_seconds=int(raw["scrape"]["timeout_seconds"]),
            cache_seconds=int(raw["scrape"]["cache_seconds"]),
        ),
        compatibility=CompatibilityConfig(
            mode=str(raw["compatibility"]["mode"]),
            allow_approximations=bool(raw["compatibility"]["allow_approximations"]),
        ),
    )
