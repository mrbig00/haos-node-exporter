"""
Collects system-level metrics directly from /proc and /sys, producing
metric names, label keys, and semantics that exactly match Prometheus
node_exporter output.

These are real kernel counters — not approximations derived from HA entities.
"""

import os
import re
from pathlib import Path

from app.domain.metric import Metric, MetricType
from app.infrastructure.logger import get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Linux clock ticks per second (almost universally 100 on modern kernels).
try:
    _USER_HZ: int = os.sysconf("SC_CLK_TCK")  # type: ignore[assignment]
except (ValueError, OSError):
    _USER_HZ = 100

# Sector size assumed in /proc/diskstats (always 512 bytes on Linux).
_SECTOR_BYTES = 512

# Pseudo-filesystems that carry no meaningful storage stats.
_SKIP_FSTYPES = frozenset({
    "autofs", "binfmt_misc", "bpf", "cgroup", "cgroup2", "cgroup2fs",
    "cgroupfs", "configfs", "debugfs", "devpts", "devtmpfs", "ecryptfs",
    "efivarfs", "fuse.gvfsd-fuse", "fuse.portal", "fusectl",
    "hugetlbfs", "iso9660", "mqueue", "nsfs", "overlay", "proc",
    "pstore", "ramfs", "rootfs", "rpc_pipefs", "securityfs",
    "selinuxfs", "squashfs", "sysfs", "tmpfs", "tracefs", "nfsd",
})

# Disk device patterns that are not physical disks.
_SKIP_DISK_RE = re.compile(r"^(loop|ram|sr|fd)\d*$")

# Partition suffix pattern — skip sda1, sdb2, etc. but keep nvme0n1.
_PARTITION_RE = re.compile(r"^(?!nvme).+\d+$|^nvme\d+n\d+p\d+")

# CPU stat modes in /proc/stat field order.
_CPU_MODES = (
    "user", "nice", "system", "idle", "iowait",
    "irq", "softirq", "steal", "guest", "guest_nice",
)

# /proc/meminfo keys → node_exporter metric name suffix.
_MEMINFO_MAP: dict[str, str] = {
    "MemTotal":        "MemTotal_bytes",
    "MemFree":         "MemFree_bytes",
    "MemAvailable":    "MemAvailable_bytes",
    "Buffers":         "Buffers_bytes",
    "Cached":          "Cached_bytes",
    "SwapCached":      "SwapCached_bytes",
    "Active":          "Active_bytes",
    "Inactive":        "Inactive_bytes",
    "Active(anon)":    "Active_anon_bytes",
    "Inactive(anon)":  "Inactive_anon_bytes",
    "Active(file)":    "Active_file_bytes",
    "Inactive(file)":  "Inactive_file_bytes",
    "Unevictable":     "Unevictable_bytes",
    "Mlocked":         "Mlocked_bytes",
    "SwapTotal":       "SwapTotal_bytes",
    "SwapFree":        "SwapFree_bytes",
    "Dirty":           "Dirty_bytes",
    "Writeback":       "Writeback_bytes",
    "AnonPages":       "AnonPages_bytes",
    "Mapped":          "Mapped_bytes",
    "Shmem":           "Shmem_bytes",
    "KReclaimable":    "KReclaimable_bytes",
    "Slab":            "Slab_bytes",
    "SReclaimable":    "SReclaimable_bytes",
    "SUnreclaim":      "SUnreclaim_bytes",
    "KernelStack":     "KernelStack_bytes",
    "PageTables":      "PageTables_bytes",
    "Bounce":          "Bounce_bytes",
    "WritebackTmp":    "WritebackTmp_bytes",
    "CommitLimit":     "CommitLimit_bytes",
    "Committed_AS":    "Committed_AS_bytes",
    "VmallocTotal":    "VmallocTotal_bytes",
    "VmallocUsed":     "VmallocUsed_bytes",
    "VmallocChunk":    "VmallocChunk_bytes",
    "HardwareCorrupted": "HardwareCorrupted_bytes",
    "AnonHugePages":   "AnonHugePages_bytes",
    "ShmemHugePages":  "ShmemHugePages_bytes",
    "ShmemPmdMapped":  "ShmemPmdMapped_bytes",
    "CmaTotal":        "CmaTotal_bytes",
    "CmaFree":         "CmaFree_bytes",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read(path: str) -> str | None:
    """Read a text file, returning None on any error."""
    try:
        return Path(path).read_text()
    except Exception:
        return None


def _g(name: str, value: float, labels: dict, help_text: str) -> Metric:
    return Metric(name=name, value=value, labels=labels,
                  help_text=help_text, metric_type=MetricType.GAUGE)


def _c(name: str, value: float, labels: dict, help_text: str) -> Metric:
    return Metric(name=name, value=value, labels=labels,
                  help_text=help_text, metric_type=MetricType.COUNTER)


# ---------------------------------------------------------------------------
# Collector
# ---------------------------------------------------------------------------

class SystemCollector:
    """
    Reads /proc and /sys to produce exact node_exporter metric output.
    Each sub-collector is isolated; a failure in one never blocks others.
    """

    def __init__(self, node_name: str = "") -> None:
        # When node_name is set it overrides the nodename label in node_uname_info,
        # making it easy to identify this host in multi-node Grafana dashboards.
        self._node_name = node_name.strip()

    def collect(self) -> list[Metric]:
        metrics: list[Metric] = []
        for fn in (
            self._cpu,
            self._memory,
            self._load,
            self._boot_time,
            self._network,
            self._diskstats,
            self._filesystem,
            self._hwmon_temperature,
            self._thermal_zone_temperature,
            self._uname,
        ):
            try:
                metrics.extend(fn())
            except Exception as exc:
                log.warning("system_collector.%s failed: %s", fn.__name__, exc)
        return metrics

    # ------------------------------------------------------------------
    # CPU  —  /proc/stat
    # node_cpu_seconds_total{cpu,mode}
    # ------------------------------------------------------------------

    def _cpu(self) -> list[Metric]:
        raw = _read("/proc/stat")
        if not raw:
            return []

        metrics: list[Metric] = []
        for line in raw.splitlines():
            if not line.startswith("cpu") or line.startswith("cpu "):
                # Skip the aggregate "cpu " line; use per-core "cpu0", "cpu1", …
                continue
            parts = line.split()
            core = parts[0][3:]  # "cpu0" → "0"
            for i, mode in enumerate(_CPU_MODES):
                if i + 1 >= len(parts):
                    break
                seconds = int(parts[i + 1]) / _USER_HZ
                metrics.append(_c(
                    "node_cpu_seconds_total",
                    seconds,
                    {"cpu": core, "mode": mode},
                    "Seconds the CPUs spent in each mode.",
                ))
        return metrics

    # ------------------------------------------------------------------
    # Memory  —  /proc/meminfo
    # node_memory_<Field>_bytes
    # ------------------------------------------------------------------

    def _memory(self) -> list[Metric]:
        raw = _read("/proc/meminfo")
        if not raw:
            return []

        parsed: dict[str, int] = {}
        for line in raw.splitlines():
            parts = line.split()
            if len(parts) < 2:
                continue
            key = parts[0].rstrip(":")
            try:
                parsed[key] = int(parts[1]) * 1024   # kB → bytes
            except ValueError:
                continue

        return [
            _g(f"node_memory_{suffix}", float(parsed[key]), {},
               f"Memory information field {suffix}.")
            for key, suffix in _MEMINFO_MAP.items()
            if key in parsed
        ]

    # ------------------------------------------------------------------
    # Load averages  —  /proc/loadavg
    # node_load1, node_load5, node_load15
    # ------------------------------------------------------------------

    def _load(self) -> list[Metric]:
        raw = _read("/proc/loadavg")
        if not raw:
            return []
        parts = raw.split()
        if len(parts) < 3:
            return []
        return [
            _g("node_load1",  float(parts[0]), {}, "1m load average."),
            _g("node_load5",  float(parts[1]), {}, "5m load average."),
            _g("node_load15", float(parts[2]), {}, "15m load average."),
        ]

    # ------------------------------------------------------------------
    # Boot time  —  /proc/stat  btime line
    # node_boot_time_seconds
    # ------------------------------------------------------------------

    def _boot_time(self) -> list[Metric]:
        raw = _read("/proc/stat")
        if not raw:
            return []
        for line in raw.splitlines():
            if line.startswith("btime"):
                return [_g("node_boot_time_seconds", float(line.split()[1]),
                           {}, "Node boot time, in unixtime.")]
        return []

    # ------------------------------------------------------------------
    # Network  —  /proc/net/dev
    # node_network_{receive,transmit}_{bytes,packets,errors,dropped}_total
    # ------------------------------------------------------------------

    def _network(self) -> list[Metric]:
        raw = _read("/proc/net/dev")
        if not raw:
            return []

        metrics: list[Metric] = []
        for line in raw.splitlines()[2:]:   # skip two header lines
            if ":" not in line:
                continue
            iface, rest = line.split(":", 1)
            iface = iface.strip()
            if iface == "lo":
                continue

            f = rest.split()
            if len(f) < 16:
                continue

            # /proc/net/dev column layout (0-indexed after the colon):
            # RX: bytes packets errs drop fifo frame compressed multicast
            # TX: bytes packets errs drop fifo colls  carrier  compressed
            lbl = {"device": iface}
            metrics += [
                _c("node_network_receive_bytes_total",    float(f[0]),  lbl, "Network device statistic receive_bytes."),
                _c("node_network_receive_packets_total",  float(f[1]),  lbl, "Network device statistic receive_packets."),
                _c("node_network_receive_errors_total",   float(f[2]),  lbl, "Network device statistic receive_errs."),
                _c("node_network_receive_dropped_total",  float(f[3]),  lbl, "Network device statistic receive_drop."),
                _c("node_network_transmit_bytes_total",   float(f[8]),  lbl, "Network device statistic transmit_bytes."),
                _c("node_network_transmit_packets_total", float(f[9]),  lbl, "Network device statistic transmit_packets."),
                _c("node_network_transmit_errors_total",  float(f[10]), lbl, "Network device statistic transmit_errs."),
                _c("node_network_transmit_dropped_total", float(f[11]), lbl, "Network device statistic transmit_drop."),
            ]
        return metrics

    # ------------------------------------------------------------------
    # Disk I/O  —  /proc/diskstats
    # node_disk_*
    # ------------------------------------------------------------------

    def _diskstats(self) -> list[Metric]:
        raw = _read("/proc/diskstats")
        if not raw:
            return []

        metrics: list[Metric] = []
        for line in raw.splitlines():
            parts = line.split()
            if len(parts) < 14:
                continue

            dev = parts[2]
            if _SKIP_DISK_RE.match(dev) or _PARTITION_RE.match(dev):
                continue

            lbl = {"device": dev}
            rc  = int(parts[3])   # reads completed
            rm  = int(parts[4])   # reads merged
            rs  = int(parts[5])   # sectors read
            rms = int(parts[6])   # time reading (ms)
            wc  = int(parts[7])   # writes completed
            wm  = int(parts[8])   # writes merged
            ws  = int(parts[9])   # sectors written
            wms = int(parts[10])  # time writing (ms)
            io  = int(parts[11])  # I/Os in progress
            iot = int(parts[12])  # time doing I/O (ms)
            iow = int(parts[13])  # weighted time (ms)

            metrics += [
                _c("node_disk_reads_completed_total",          float(rc),                      lbl, "The total number of reads completed successfully."),
                _c("node_disk_reads_merged_total",             float(rm),                      lbl, "The total number of reads merged."),
                _c("node_disk_read_bytes_total",               float(rs  * _SECTOR_BYTES),     lbl, "The total number of bytes read successfully."),
                _c("node_disk_read_time_seconds_total",        float(rms) / 1000,              lbl, "The total number of seconds spent by all reads."),
                _c("node_disk_writes_completed_total",         float(wc),                      lbl, "The total number of writes completed successfully."),
                _c("node_disk_writes_merged_total",            float(wm),                      lbl, "The total number of writes merged."),
                _c("node_disk_written_bytes_total",            float(ws  * _SECTOR_BYTES),     lbl, "The total number of bytes written successfully."),
                _c("node_disk_write_time_seconds_total",       float(wms) / 1000,              lbl, "The total number of seconds spent by all writes."),
                _g("node_disk_io_now",                         float(io),                      lbl, "The number of I/Os currently in progress."),
                _c("node_disk_io_time_seconds_total",          float(iot) / 1000,              lbl, "Total seconds spent doing I/Os."),
                _c("node_disk_io_time_weighted_seconds_total", float(iow) / 1000,              lbl, "The weighted number of seconds spent doing I/Os."),
            ]
        return metrics

    # ------------------------------------------------------------------
    # Filesystem  —  /proc/mounts + os.statvfs
    # node_filesystem_{size,free,avail,files,files_free,readonly}_bytes
    # ------------------------------------------------------------------

    def _filesystem(self) -> list[Metric]:
        raw = _read("/proc/mounts")
        if not raw:
            return []

        seen_mountpoints: set[str] = set()
        metrics: list[Metric] = []

        for line in raw.splitlines():
            parts = line.split()
            if len(parts) < 4:
                continue
            device, mountpoint, fstype, options = parts[0], parts[1], parts[2], parts[3]

            if fstype in _SKIP_FSTYPES:
                continue
            if mountpoint in seen_mountpoints:
                continue
            seen_mountpoints.add(mountpoint)

            try:
                st = os.statvfs(mountpoint)
            except OSError:
                continue

            bsize = st.f_frsize or st.f_bsize
            lbl = {"device": device, "fstype": fstype, "mountpoint": mountpoint}

            metrics += [
                _g("node_filesystem_size_bytes",  float(st.f_blocks * bsize), lbl, "Filesystem size in bytes."),
                _g("node_filesystem_free_bytes",  float(st.f_bfree  * bsize), lbl, "Filesystem free space in bytes."),
                _g("node_filesystem_avail_bytes", float(st.f_bavail * bsize), lbl, "Filesystem space available to non-root users in bytes."),
                _g("node_filesystem_files",       float(st.f_files),          lbl, "Filesystem total file nodes."),
                _g("node_filesystem_files_free",  float(st.f_ffree),          lbl, "Filesystem total free file nodes."),
                _g("node_filesystem_readonly",    float(1 if "ro" in options.split(",") else 0), lbl, "Filesystem read-only status."),
            ]
        return metrics

    # ------------------------------------------------------------------
    # hwmon temperature  —  /sys/class/hwmon
    # node_hwmon_temp_celsius{chip, sensor}
    # ------------------------------------------------------------------

    def _hwmon_temperature(self) -> list[Metric]:
        hwmon_root = Path("/sys/class/hwmon")
        if not hwmon_root.exists():
            return []

        metrics: list[Metric] = []
        for hwmon_dir in sorted(hwmon_root.iterdir()):
            name_file = hwmon_dir / "name"
            chip = name_file.read_text().strip() if name_file.exists() else hwmon_dir.name

            for temp_input in sorted(hwmon_dir.glob("temp*_input")):
                sensor = temp_input.stem.replace("_input", "")   # "temp1_input" → "temp1"
                try:
                    temp_c = int(temp_input.read_text().strip()) / 1000.0
                    metrics.append(_g(
                        "node_hwmon_temp_celsius",
                        temp_c,
                        {"chip": chip, "sensor": sensor},
                        "Hardware monitor for temperature (in Celsius).",
                    ))
                except Exception:
                    continue

                # Critical threshold (optional)
                crit_file = hwmon_dir / f"{sensor}_crit"
                if crit_file.exists():
                    try:
                        crit_c = int(crit_file.read_text().strip()) / 1000.0
                        metrics.append(_g(
                            "node_hwmon_temp_crit_celsius",
                            crit_c,
                            {"chip": chip, "sensor": sensor},
                            "Hardware monitor for temperature critical threshold (in Celsius).",
                        ))
                    except Exception:
                        pass

        return metrics

    # ------------------------------------------------------------------
    # Thermal zone temperature  —  /sys/class/thermal
    # node_thermal_zone_temp{zone, type}
    # ------------------------------------------------------------------

    def _thermal_zone_temperature(self) -> list[Metric]:
        thermal_root = Path("/sys/class/thermal")
        if not thermal_root.exists():
            return []

        metrics: list[Metric] = []
        for zone_dir in sorted(thermal_root.iterdir()):
            if not zone_dir.name.startswith("thermal_zone"):
                continue
            try:
                temp_c = int((zone_dir / "temp").read_text().strip()) / 1000.0
                zone_type = (zone_dir / "type").read_text().strip() if (zone_dir / "type").exists() else zone_dir.name
                metrics.append(_g(
                    "node_thermal_zone_temp",
                    temp_c,
                    {"zone": zone_dir.name, "type": zone_type},
                    "Zone temperature in Celsius.",
                ))
            except Exception:
                continue
        return metrics

    # ------------------------------------------------------------------
    # System info  —  os.uname()
    # node_uname_info
    # ------------------------------------------------------------------

    def _uname(self) -> list[Metric]:
        try:
            u = os.uname()
            nodename = self._node_name if self._node_name else u.nodename
            return [_g(
                "node_uname_info",
                1.0,
                {
                    "sysname":    u.sysname,
                    "nodename":   nodename,
                    "release":    u.release,
                    "version":    u.version,
                    "machine":    u.machine,
                    "domainname": getattr(u, "domainname", ""),
                },
                "Labeled system information as provided by the uname system call.",
            )]
        except Exception:
            return []
