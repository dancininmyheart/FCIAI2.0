from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.utils.enhanced_task_queue import _thread_task_outcome
from app.utils.thread_pool_executor import TaskStatus


@pytest.mark.parametrize(
    ("status", "result", "expected"),
    (
        (TaskStatus.COMPLETED, True, "completed"),
        (TaskStatus.COMPLETED, False, "failed"),
        (TaskStatus.COMPLETED, None, "failed"),
        (TaskStatus.FAILED, None, "failed"),
        (TaskStatus.CANCELED, None, "canceled"),
    ),
)
def test_thread_task_outcome_requires_explicit_success(
    status: TaskStatus,
    result: bool | None,
    expected: str,
) -> None:
    thread_task = SimpleNamespace(status=status, result=result)

    assert _thread_task_outcome(thread_task) == expected
