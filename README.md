# Home Assistant Node Exporter

A Home Assistant add-on that exposes entity states and system metrics as Prometheus-compatible metrics, using the same metric names and label conventions as the official [Prometheus Node Exporter](https://github.com/prometheus/node_exporter).

Existing Grafana dashboards, Prometheus alerting rules, and PromQL queries built for Node Exporter work without modification.

---

## Use case

Home Assistant runs on a host machine (Raspberry Pi, NUC, VM, etc.) that also runs your smart home. You already have Prometheus and Grafana set up to monitor your infrastructure with Node Exporter. This add-on lets you:

- **Monitor the HA host machine** — CPU usage, memory, disk, network, load averages, and boot time — using the exact same metric names as Node Exporter, so your existing dashboards just work.
- **Monitor smart home entities** — temperature sensors, binary sensors, power meters, presence sensors — as native `homeassistant_*` Prometheus metrics.
- **Unify observability** — a single Prometheus scrape job covers both system health and smart home state. No separate Node Exporter process needed on the HA host.

### Example: what you get in Prometheus

```
# System metrics (same names as node_exporter)
node_cpu_seconds_total{cpu="0",mode="idle"} 0.97
node_cpu_seconds_total{cpu="0",mode="user"} 0.03
node_memory_MemTotal_bytes 8388608000
node_memory_MemFree_bytes 2147483648
node_memory_MemAvailable_bytes 2147483648
node_filesystem_size_bytes{mountpoint="/"} 128849018880
node_filesystem_free_bytes{mountpoint="/"} 53687091200
node_network_receive_bytes_total{device="eth0"} 1073741824
node_network_transmit_bytes_total{device="eth0"} 536870912
node_load1 0.42
node_load5 0.38
node_load15 0.35
node_boot_time_seconds 1711660800
node_hwmon_temp_celsius{chip="cpu",sensor="temp1"} 52.3

# Smart home entity metrics
homeassistant_sensor_living_room_temperature{entity_id="sensor.living_room_temperature",domain="sensor",friendly_name="Living Room Temperature"} 21.5
homeassistant_binary_sensor_front_door{entity_id="binary_sensor.front_door",domain="binary_sensor",friendly_name="Front Door"} 0
homeassistant_sensor_solar_power{entity_id="sensor.solar_power",domain="sensor",friendly_name="Solar Power"} 1847.0

# Exporter health
homeassistant_exporter_up 1
```

---

## How it works

The add-on runs a lightweight Python HTTP server inside the Home Assistant supervisor environment. On each Prometheus scrape:

1. Fetches all entity states from the HA REST API (`/api/states`) using the Supervisor token — no separate credentials needed.
2. Filters entities by domain and entity ID according to your configuration.
3. Maps [system_monitor](https://www.home-assistant.io/integrations/systemmonitor/) entities to Node Exporter metric names (see mapping table below).
4. Converts all other numeric entities to `homeassistant_*` metrics.
5. Renders and serves the combined output at `/metrics` in Prometheus text format.

Responses from HA are cached (default: 15 seconds) to avoid hammering the API on every scrape.

---

## Node Exporter metric mapping

The following Home Assistant [System Monitor](https://www.home-assistant.io/integrations/systemmonitor/) entities are automatically translated to their Node Exporter equivalents:

| HA Entity (pattern) | Node Exporter Metric | Notes |
|---|---|---|
| `*processor_use` | `node_cpu_seconds_total{mode="idle/user"}` | Approximated from % snapshot; requires `allow_approximations: true` |
| `*processor_temperature` | `node_hwmon_temp_celsius{chip="cpu",sensor="temp1"}` | °F auto-converted to °C |
| `*memory_use` | `node_memory_MemUsed_bytes` | |
| `*memory_free` | `node_memory_MemFree_bytes`, `node_memory_MemAvailable_bytes` | |
| `*memory_use` + `*memory_free` | `node_memory_MemTotal_bytes` | Synthesised by adding both values |
| `*swap_use` | `node_memory_SwapUsed_bytes` | |
| `*swap_free` | `node_memory_SwapFree_bytes` | |
| `*swap_use` + `*swap_free` | `node_memory_SwapTotal_bytes` | Synthesised |
| `*disk_use` | `node_filesystem_used_bytes{mountpoint="..."}` | |
| `*disk_free` | `node_filesystem_free_bytes`, `node_filesystem_avail_bytes` | |
| `*disk_use` + `*disk_free` | `node_filesystem_size_bytes` | Synthesised |
| `*network_in_<iface>` | `node_network_receive_bytes_total{device="<iface>"}` | |
| `*network_out_<iface>` | `node_network_transmit_bytes_total{device="<iface>"}` | |
| `*packets_in_<iface>` | `node_network_receive_packets_total{device="<iface>"}` | |
| `*packets_out_<iface>` | `node_network_transmit_packets_total{device="<iface>"}` | |
| `*load_1m` | `node_load1` | |
| `*load_5m` | `node_load5` | |
| `*load_15m` | `node_load15` | |
| `*last_boot` | `node_boot_time_seconds` | Parses ISO 8601 timestamp to Unix epoch |

Units are converted automatically. HA reports memory in `MiB`, disk in `GiB` — all values are normalised to bytes before export.

---

## Prerequisites

- Home Assistant OS or Home Assistant Supervised
- The [System Monitor](https://www.home-assistant.io/integrations/systemmonitor/) integration enabled in HA (for system-level metrics)
- A running Prometheus instance that can reach your HA host on the configured port (default: `9100`)

### Enable System Monitor entities

System Monitor entities are disabled by default. Enable the ones you want via **Settings → Devices & Services → System Monitor → Entities**, or add them to your `configuration.yaml`:

```yaml
# configuration.yaml
sensor:
  - platform: systemmonitor
    resources:
      - type: processor_use
      - type: processor_temperature
      - type: memory_use
      - type: memory_free
      - type: swap_use
      - type: swap_free
      - type: disk_use
        arg: /
      - type: disk_free
        arg: /
      - type: network_in
        arg: eth0
      - type: network_out
        arg: eth0
      - type: load_1m
      - type: load_5m
      - type: load_15m
      - type: last_boot
```

---

## Installation

### 1. Add the repository

In Home Assistant, go to **Settings → Add-ons → Add-on Store** and click the menu (⋮) in the top right. Select **Repositories** and add:

```
https://github.com/mrbig00/haos-node-exporter
```

### 2. Install the add-on

Find **Node Exporter for Home Assistant** in the add-on store and click **Install**.

### 3. Configure

Go to the **Configuration** tab of the add-on and adjust options as needed (see [Configuration](#configuration) below), then click **Save**.

### 4. Start

Go to the **Info** tab and click **Start**. Check the **Log** tab to confirm the server started:

```json
{"ts":"...","level":"INFO","msg":"Metrics server listening on port 9100"}
```

### 5. Configure Prometheus

Add a scrape job to your `prometheus.yml`:

```yaml
scrape_configs:
  - job_name: home_assistant
    static_configs:
      - targets: ["<your-ha-ip>:9100"]
    scrape_interval: 30s
```

Reload Prometheus and verify the target is `UP` at `http://<prometheus>:9090/targets`.

---

## Configuration

All options are set via the add-on configuration UI or directly in `options.json`.

```yaml
# Port the /metrics endpoint listens on.
# Default: 9100 (same as node_exporter — change if both run simultaneously)
port: 9100

# HA entity domains to include. All others are ignored.
include_domains:
  - sensor
  - binary_sensor

# Allowlist: only these entity IDs are exported (empty = all domains above)
include_entities: []

# Denylist: these entity IDs are always excluded
exclude_entities:
  - sensor.some_noisy_entity

# Labels attached to every homeassistant_* metric
label_strategy:
  include_friendly_name: true   # adds friendly_name="..." label
  include_domain: true          # adds domain="..." label

# How non-numeric states are converted to numbers
state_mapping:
  "on": 1
  "off": 0
  open: 1
  closed: 0
  home: 1
  away: 0
  unlocked: 1
  locked: 0

scrape:
  timeout_seconds: 10   # HA API request timeout
  cache_seconds: 15     # How long to cache HA responses

compatibility:
  # native        — only homeassistant_* metrics
  # node_exporter — only node_* metrics (system_monitor entities only)
  # dual          — both sets (default, recommended)
  mode: dual

  # Allow metrics that must be approximated (e.g. node_cpu_seconds_total
  # derived from a CPU % snapshot rather than actual kernel counters).
  # Set to false for strict semantic correctness.
  allow_approximations: true
```

### Compatibility modes

| Mode | homeassistant_* metrics | node_* metrics |
|---|---|---|
| `native` | Yes | No |
| `node_exporter` | No | Yes |
| `dual` (default) | Yes | Yes |

Use `node_exporter` mode if you are replacing an existing Node Exporter scrape job and want a clean drop-in. Use `dual` if you want both system metrics and smart home entity metrics in one endpoint.

---

## Endpoints

| Endpoint | Description |
|---|---|
| `GET /metrics` | Prometheus text format metrics |
| `GET /healthz` | Returns `200 OK` — use for liveness probes |

---

## Grafana dashboards

Because system metrics use exact Node Exporter metric names and label conventions, the following dashboards work without any changes:

- [Node Exporter Full](https://grafana.com/grafana/dashboards/1860) (Dashboard ID 1860)
- [Node Exporter for Prometheus](https://grafana.com/grafana/dashboards/11074) (Dashboard ID 11074)

Import the dashboard and point it at the Prometheus data source that scrapes this add-on.

---

## Architecture

```
┌──────────────────────────────────────────────┐
│  Presentation  │  GET /metrics (aiohttp)      │
├──────────────────────────────────────────────┤
│  Application   │  CollectEntities             │
│                │  TransformToMetrics          │
│                │  CompatibilityMapper         │
│                │  RenderMetrics               │
├──────────────────────────────────────────────┤
│  Domain        │  Entity  Metric              │
├──────────────────────────────────────────────┤
│  Infrastructure│  HaClient  ConfigLoader      │
│                │  Logger                      │
└──────────────────────────────────────────────┘
```

```
app/
├── main.py
├── domain/
│   ├── entity.py          # HA entity model
│   └── metric.py          # Prometheus metric model
├── application/
│   ├── collect_entities.py      # Fetches states from HA API
│   ├── transform_metrics.py     # → homeassistant_* metrics
│   ├── compatibility_mapper.py  # → node_* metrics
│   └── render_metrics.py        # → Prometheus text format
├── infrastructure/
│   ├── ha_client.py       # Async HA REST client with caching
│   ├── config_loader.py   # Reads /data/options.json
│   └── logger.py          # Structured JSON logging
└── presentation/
    └── http_server.py     # aiohttp server, /metrics + /healthz
```

---

## Limitations

- **`node_cpu_seconds_total` is approximated.** Node Exporter reads kernel counters per CPU core and mode. Home Assistant's System Monitor only exposes a single CPU usage percentage. The exported value is a synthetic ratio, not a real counter. Dashboards using `rate(node_cpu_seconds_total[5m])` will show correct relative load but not per-core or per-mode breakdowns. Disable with `allow_approximations: false` if you need strict correctness.
- **No disk I/O counters.** HA does not expose `node_disk_reads_completed_total` or similar I/O counters.
- **No network error/drop counters.** HA only exposes byte totals, not error or drop counts.
- **Filesystem labels are partial.** HA does not provide the `device` or `fstype` for mounts, so those labels are empty strings in filesystem metrics.

---

## License

MIT
