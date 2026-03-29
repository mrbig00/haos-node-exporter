"""
Renders a list of Metric objects into Prometheus text exposition format.

Reference: https://prometheus.io/docs/instrumenting/exposition_formats/
"""

from collections import defaultdict

from app.domain.metric import Metric, MetricType


def _label_str(labels: dict[str, str]) -> str:
    if not labels:
        return ""
    parts = []
    for k, v in sorted(labels.items()):
        escaped = v.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        parts.append(f'{k}="{escaped}"')
    return "{" + ",".join(parts) + "}"


def _format_value(v: float) -> str:
    if v != v:  # NaN
        return "NaN"
    if v == float("inf"):
        return "+Inf"
    if v == float("-inf"):
        return "-Inf"
    # Use integer representation when the value is a whole number
    if v == int(v) and abs(v) < 1e15:
        return str(int(v))
    return repr(v)


class RenderMetricsUseCase:
    def execute(self, metrics: list[Metric]) -> str:
        # Group by metric name to emit a single # HELP / # TYPE header per name
        by_name: dict[str, list[Metric]] = defaultdict(list)
        for m in metrics:
            by_name[m.name].append(m)

        lines: list[str] = []
        for name in sorted(by_name):
            group = by_name[name]
            first = group[0]

            if first.help_text:
                lines.append(f"# HELP {name} {first.help_text}")
            lines.append(f"# TYPE {name} {first.metric_type.value}")

            for metric in group:
                label_str = _label_str(metric.labels)
                lines.append(f"{name}{label_str} {_format_value(metric.value)}")

        lines.append("")  # trailing newline required by the spec
        return "\n".join(lines)
