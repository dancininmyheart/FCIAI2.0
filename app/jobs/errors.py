from __future__ import annotations

from dataclasses import dataclass

from app.jobs.types import JobStatus, TaskId


@dataclass(frozen=True, slots=True)
class JobNotFound(Exception):
    public_id: TaskId

    def __str__(self) -> str:
        return f"job {self.public_id} not found"


@dataclass(frozen=True, slots=True)
class StaleJobState(Exception):
    public_id: TaskId
    expected_version: int
    actual_version: int

    def __str__(self) -> str:
        return f"job {self.public_id} version {self.actual_version} != {self.expected_version}"


@dataclass(frozen=True, slots=True)
class IllegalJobTransition(Exception):
    public_id: TaskId
    status: JobStatus
    action: str

    def __str__(self) -> str:
        return f"cannot {self.action} job {self.public_id} from {self.status.value}"


@dataclass(frozen=True, slots=True)
class InvalidProgress(Exception):
    progress: int

    def __str__(self) -> str:
        return f"invalid progress: {self.progress}"
