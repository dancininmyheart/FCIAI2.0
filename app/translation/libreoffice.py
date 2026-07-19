from __future__ import annotations

import socket
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True, slots=True)
class LibreOfficeRequest:
    source_path: Path
    output_dir: Path
    output_format: str = "pdf"
    timeout_seconds: float = 120.0


@dataclass(frozen=True, slots=True)
class LibreOfficeResult:
    output_path: Path
    pid: int
    profile_path: Path
    port: int


@dataclass(frozen=True, slots=True)
class LibreOfficeError(Exception):
    code: str
    detail: str

    def __str__(self) -> str:
        return f"{self.code}: {self.detail}"


class OwnedProcess(Protocol):
    pid: int
    returncode: int | None

    def communicate(self, timeout: float | None = None) -> tuple[bytes | str | None, bytes | str | None]: ...
    def kill(self) -> None: ...
    def wait(self, timeout: float | None = None) -> int: ...


class ProcessLauncher(Protocol):
    def start(self, command: tuple[str, ...]) -> OwnedProcess: ...


class SubprocessLauncher:
    def start(self, command: tuple[str, ...]) -> OwnedProcess:
        return subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


class LibreOfficeProcessAdapter:
    def __init__(
        self,
        executable: Path,
        profile_root: Path,
        launcher: ProcessLauncher | None = None,
    ) -> None:
        self._executable = executable
        self._profile_root = profile_root
        self._launcher = launcher or SubprocessLauncher()
        self._port_lock = threading.Lock()
        self._owned_ports: set[int] = set()

    def convert(self, request: LibreOfficeRequest) -> LibreOfficeResult:
        source = request.source_path.resolve(strict=True)
        request.output_dir.mkdir(parents=True, exist_ok=True)
        self._profile_root.mkdir(parents=True, exist_ok=True)
        port = self._claim_port()
        try:
            with tempfile.TemporaryDirectory(prefix="lo-job-", dir=self._profile_root) as profile:
                profile_path = Path(profile).resolve()
                output = request.output_dir / f"{source.stem}.{request.output_format}"
                output.unlink(missing_ok=True)
                command = self._command(request, source, profile_path, port)
                try:
                    process = self._launcher.start(command)
                except OSError as exc:
                    raise LibreOfficeError("libreoffice_start_failed", "owned process could not start") from exc
                try:
                    process.communicate(timeout=request.timeout_seconds)
                except subprocess.TimeoutExpired as exc:
                    process.kill()
                    process.wait(timeout=10)
                    raise LibreOfficeError("libreoffice_timeout", "owned process exceeded its deadline") from exc
                if process.returncode not in (0, None):
                    raise LibreOfficeError("libreoffice_failed", f"owned process exited with {process.returncode}")
                if not output.is_file():
                    raise LibreOfficeError("libreoffice_missing_output", "conversion produced no output file")
                return LibreOfficeResult(output, process.pid, profile_path, port)
        finally:
            with self._port_lock:
                self._owned_ports.discard(port)

    def _command(
        self,
        request: LibreOfficeRequest,
        source: Path,
        profile: Path,
        port: int,
    ) -> tuple[str, ...]:
        profile_uri = profile.as_uri()
        return (
            str(self._executable),
            "--headless",
            "--nologo",
            "--nodefault",
            "--nofirststartwizard",
            f"-env:UserInstallation={profile_uri}",
            f"--accept=socket,host=127.0.0.1,port={port};urp;StarOffice.ComponentContext",
            "--convert-to",
            request.output_format,
            "--outdir",
            str(request.output_dir.resolve()),
            str(source),
        )

    def _claim_port(self) -> int:
        while True:
            port = _reserve_port()
            with self._port_lock:
                if port not in self._owned_ports:
                    self._owned_ports.add(port)
                    return port


def _reserve_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])
