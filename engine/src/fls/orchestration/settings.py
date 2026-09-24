"""Temporal connection settings — 12-factor, from the instance env (instance.env)."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class TemporalSettings:
    address: str = "127.0.0.1:7233"
    namespace: str = "default"
    task_queue: str = "fls-harness"

    @classmethod
    def from_env(cls) -> TemporalSettings:
        return cls(
            address=os.environ.get("TEMPORAL_ADDRESS", cls.address),
            namespace=os.environ.get("TEMPORAL_NAMESPACE", cls.namespace),
            task_queue=os.environ.get("TEMPORAL_TASK_QUEUE", cls.task_queue),
        )


def workflow_id(number: int) -> str:
    return f"exp-{int(number)}"
