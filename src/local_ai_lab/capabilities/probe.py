from __future__ import annotations

import csv
import ctypes
import os
import platform
import shutil
import socket
import subprocess
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from local_ai_lab.capabilities.model import (
    CapabilityFact,
    NodeCapabilityReport,
    ProbeObservation,
    isoformat_utc,
    utc_now,
)

Clock = Callable[[], datetime]


@dataclass(frozen=True, slots=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


class CommandNotAllowedError(ValueError):
    pass


class ReadOnlyCommandRunner:
    """Runs a deliberately small allowlist of inspection-only commands."""

    ALLOWED_EXECUTABLES = frozenset(
        {"cargo", "node", "nvidia-smi", "pnpm", "python", "rocminfo", "rustc", "wsl"}
    )

    def __call__(self, command: Sequence[str], timeout_seconds: float = 10.0) -> CommandResult:
        if not command:
            raise CommandNotAllowedError("empty command")
        requested = command[0]
        if Path(requested).name != requested:
            raise CommandNotAllowedError("executable paths are not accepted")
        executable = requested.casefold()
        for suffix in (".exe", ".cmd", ".bat"):
            if executable.endswith(suffix):
                executable = executable[: -len(suffix)]
                break
        if executable not in self.ALLOWED_EXECUTABLES:
            raise CommandNotAllowedError(f"command is not in the read-only allowlist: {requested}")
        resolved = shutil.which(requested)
        if resolved is None:
            return CommandResult(127, "", "command not found")
        try:
            completed = subprocess.run(
                [resolved, *command[1:]],
                check=False,
                capture_output=True,
                timeout=timeout_seconds,
                shell=False,
            )
        except subprocess.TimeoutExpired as error:
            stdout = self._decode_output(error.stdout if isinstance(error.stdout, bytes) else b"")
            stderr = self._decode_output(error.stderr if isinstance(error.stderr, bytes) else b"")
            return CommandResult(124, stdout, stderr or "probe timed out")
        return CommandResult(
            completed.returncode,
            self._decode_output(completed.stdout),
            self._decode_output(completed.stderr),
        )

    @staticmethod
    def _decode_output(value: bytes) -> str:
        if not value:
            return ""
        if b"\x00" in value:
            for encoding in ("utf-16-le", "utf-16-be"):
                try:
                    return value.decode(encoding).lstrip("\ufeff")
                except UnicodeDecodeError:
                    continue
        return value.decode("utf-8", errors="replace")


class _MemoryStatusEx(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


class NodeProbe:
    NVIDIA_QUERY = (
        "nvidia-smi",
        "--query-gpu=index,name,uuid,memory.total,driver_version,temperature.gpu,pstate",
        "--format=csv,noheader,nounits",
    )

    VERSION_COMMANDS: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("runtime.python", ("python", "--version")),
        ("runtime.node", ("node", "--version")),
        ("runtime.pnpm", ("pnpm", "--version")),
        ("runtime.rustc", ("rustc", "--version")),
        ("runtime.cargo", ("cargo", "--version")),
    )

    def __init__(
        self,
        *,
        runner: Callable[[Sequence[str], float], CommandResult] | None = None,
        clock: Clock = utc_now,
    ) -> None:
        self._runner = runner or ReadOnlyCommandRunner()
        self._clock = clock

    def collect(self, *, data_root: Path) -> NodeCapabilityReport:
        now = isoformat_utc(self._clock())
        hostname = socket.gethostname()
        provisional_id = uuid.uuid5(
            uuid.NAMESPACE_URL, f"local-ai-lab:provisional-node:{hostname.casefold()}"
        )
        report = NodeCapabilityReport(
            schema_version="1.0",
            report_id=str(uuid.uuid7()),
            node_id=str(provisional_id),
            node_id_kind="provisional_hostname_uuid5",
            observed_at=now,
        )

        self._collect_platform(report, now)
        self._collect_memory(report, now)
        self._collect_disk(report, now, data_root)
        self._collect_versions(report, now)
        self._collect_nvidia(report, now)
        self._collect_rocm(report, now)
        self._collect_wsl(report, now)

        report.limitations.extend(
            [
                "No ML workload was executed; inference and training remain untested.",
                "No dtype, backward, LoRA, checkpoint, throughput or stability test was executed.",
                "The node id is provisional until authenticated pairing persists a UUIDv7 identity.",
            ]
        )
        report.seal()
        return report

    @staticmethod
    def _fact(
        report: NodeCapabilityReport,
        now: str,
        key: str,
        value: object,
        source: str,
        *,
        unit: str | None = None,
        detail: str | None = None,
    ) -> None:
        report.facts.append(
            CapabilityFact(
                key=key,
                value=value,
                status="detected",
                source=source,
                observed_at=now,
                unit=unit,
                detail=detail,
            )
        )

    def _collect_platform(self, report: NodeCapabilityReport, now: str) -> None:
        values = {
            "node.hostname": socket.gethostname(),
            "os.system": platform.system(),
            "os.release": platform.release(),
            "os.version": platform.version(),
            "os.machine": platform.machine(),
            "cpu.processor": platform.processor() or os.environ.get("PROCESSOR_IDENTIFIER", "unknown"),
            "cpu.logical_processors": os.cpu_count(),
        }
        for key, value in values.items():
            self._fact(report, now, key, value, "python.platform")
        report.probes.append(ProbeObservation("platform", "completed", now))

    def _collect_memory(self, report: NodeCapabilityReport, now: str) -> None:
        if platform.system() != "Windows":
            report.probes.append(
                ProbeObservation("memory", "unavailable", now, "only Windows is implemented in phase 0")
            )
            return
        status = _MemoryStatusEx()
        status.dwLength = ctypes.sizeof(_MemoryStatusEx)
        try:
            success = ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
        except (AttributeError, OSError) as error:
            report.probes.append(ProbeObservation("memory", "error", now, str(error)))
            return
        if not success:
            report.probes.append(ProbeObservation("memory", "error", now, "GlobalMemoryStatusEx failed"))
            return
        self._fact(report, now, "memory.physical_total_bytes", status.ullTotalPhys, "Win32 API", unit="bytes")
        self._fact(report, now, "memory.physical_available_bytes", status.ullAvailPhys, "Win32 API", unit="bytes")
        report.probes.append(ProbeObservation("memory", "completed", now))

    def _collect_disk(self, report: NodeCapabilityReport, now: str, data_root: Path) -> None:
        try:
            usage = shutil.disk_usage(data_root.resolve())
        except OSError as error:
            report.probes.append(ProbeObservation("disk", "error", now, str(error)))
            return
        self._fact(report, now, "storage.data_root", str(data_root.resolve()), "shutil.disk_usage")
        self._fact(report, now, "storage.total_bytes", usage.total, "shutil.disk_usage", unit="bytes")
        self._fact(report, now, "storage.free_bytes", usage.free, "shutil.disk_usage", unit="bytes")
        report.probes.append(ProbeObservation("disk", "completed", now))

    def _collect_versions(self, report: NodeCapabilityReport, now: str) -> None:
        for key, command in self.VERSION_COMMANDS:
            result = self._runner(command, 10.0)
            if result.returncode == 0:
                value = (result.stdout or result.stderr).strip().splitlines()[0]
                self._fact(report, now, key, value, "command", detail=" ".join(command))
                report.probes.append(ProbeObservation(key, "completed", now))
            else:
                detail = (result.stderr or result.stdout).strip() or f"exit {result.returncode}"
                status = "unavailable" if result.returncode == 127 else "error"
                report.probes.append(ProbeObservation(key, status, now, detail))

    def _collect_nvidia(self, report: NodeCapabilityReport, now: str) -> None:
        result = self._runner(self.NVIDIA_QUERY, 15.0)
        if result.returncode != 0:
            status = "unavailable" if result.returncode == 127 else "error"
            report.probes.append(
                ProbeObservation("nvidia-smi", status, now, (result.stderr or result.stdout).strip())
            )
            return
        rows = list(csv.reader(result.stdout.splitlines(), skipinitialspace=True))
        for ordinal, row in enumerate(rows):
            if len(row) != 7:
                report.probes.append(
                    ProbeObservation("nvidia-smi", "error", now, f"unexpected CSV row {ordinal}")
                )
                continue
            index, name, gpu_uuid, memory_mib, driver, temperature_c, pstate = (
                item.strip() for item in row
            )
            prefix = f"gpu.{index}"
            self._fact(report, now, f"{prefix}.vendor", "NVIDIA", "nvidia-smi")
            self._fact(report, now, f"{prefix}.name", name, "nvidia-smi")
            self._fact(report, now, f"{prefix}.uuid", gpu_uuid, "nvidia-smi")
            self._fact(report, now, f"{prefix}.memory_total_mib", int(memory_mib), "nvidia-smi", unit="MiB")
            self._fact(report, now, f"{prefix}.driver_version", driver, "nvidia-smi")
            self._fact(report, now, f"{prefix}.temperature_c", int(temperature_c), "nvidia-smi", unit="°C")
            self._fact(report, now, f"{prefix}.performance_state", pstate, "nvidia-smi")
        report.probes.append(ProbeObservation("nvidia-smi", "completed", now))

    def _collect_rocm(self, report: NodeCapabilityReport, now: str) -> None:
        result = self._runner(("rocminfo",), 15.0)
        if result.returncode == 0:
            self._fact(report, now, "runtime.rocm.command_available", True, "rocminfo")
            report.probes.append(ProbeObservation("rocminfo", "completed", now))
            return
        status = "unavailable" if result.returncode == 127 else "error"
        report.probes.append(
            ProbeObservation("rocminfo", status, now, (result.stderr or result.stdout).strip())
        )

    def _collect_wsl(self, report: NodeCapabilityReport, now: str) -> None:
        result = self._runner(("wsl", "--status"), 15.0)
        if result.returncode == 0:
            self._fact(report, now, "runtime.wsl.status_available", True, "wsl --status")
            report.probes.append(ProbeObservation("wsl", "completed", now))
            return
        status = "unavailable" if result.returncode == 127 else "error"
        detail = (result.stderr or result.stdout).strip() or f"exit {result.returncode}"
        report.probes.append(ProbeObservation("wsl", status, now, detail))
