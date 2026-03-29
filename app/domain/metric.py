from dataclasses import dataclass, field
from enum import Enum


class MetricType(str, Enum):
    GAUGE = "gauge"
    COUNTER = "counter"
    UNTYPED = "untyped"


@dataclass
class Metric:
    name: str
    value: float
    labels: dict[str, str] = field(default_factory=dict)
    help_text: str = ""
    metric_type: MetricType = MetricType.GAUGE
