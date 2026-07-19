from __future__ import annotations

import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from app.translation.libreoffice import LibreOfficeError, LibreOfficeProcessAdapter, LibreOfficeRequest


@dataclass(slots=True)
class FakeProcess:
    command: tuple[str, ...]
    pid: int
    timeout: bool = False
    returncode: int | None = 0
    killed: bool = False
    waited: bool = False

    def communicate(self, timeout: float | None = None):
        if self.timeout:
            raise subprocess.TimeoutExpired(self.command, timeout)
        output_dir = Path(self.command[self.command.index("--outdir") + 1])
        source = Path(self.command[-1])
        output_format = self.command[self.command.index("--convert-to") + 1]
        (output_dir / f"{source.stem}.{output_format}").write_bytes(b"rendered")
        return b"", b""

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9

    def wait(self, timeout: float | None = None) -> int:
        self.waited = True
        return self.returncode or 0


@dataclass(slots=True)
class RecordingLauncher:
    timeout: bool = False
    commands: list[tuple[str, ...]] = field(default_factory=list)
    processes: list[FakeProcess] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def start(self, command: tuple[str, ...]) -> FakeProcess:
        with self.lock:
            process = FakeProcess(command, 1000 + len(self.processes), self.timeout)
            self.commands.append(command)
            self.processes.append(process)
            return process


def _request(tmp_path: Path, name: str) -> LibreOfficeRequest:
    source = tmp_path / f"{name}.pptx"
    source.write_bytes(b"pptx")
    return LibreOfficeRequest(source, tmp_path / f"out-{name}")


def test_concurrent_jobs_use_distinct_profiles_and_ports(tmp_path: Path) -> None:
    launcher = RecordingLauncher()
    adapter = LibreOfficeProcessAdapter(Path("soffice"), tmp_path / "profiles", launcher)
    results = []

    def run(name: str) -> None:
        results.append(adapter.convert(_request(tmp_path, name)))

    threads = [threading.Thread(target=run, args=(name,)) for name in ("one", "two")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(results) == 2
    assert len({result.profile_path for result in results}) == 2
    assert len({result.port for result in results}) == 2
    assert all(not result.profile_path.exists() for result in results)


def test_timeout_kills_reaps_owned_process_and_removes_profile(tmp_path: Path) -> None:
    launcher = RecordingLauncher(timeout=True)
    adapter = LibreOfficeProcessAdapter(Path("soffice"), tmp_path / "profiles", launcher)

    with pytest.raises(LibreOfficeError, match="libreoffice_timeout"):
        adapter.convert(_request(tmp_path, "hung"))

    process = launcher.processes[0]
    assert process.killed and process.waited
    assert list((tmp_path / "profiles").iterdir()) == []
