"""
Saga pattern for distributed VPP workflow coordination.

Manages multi-step processes (e.g., DR event dispatch, capacity auctions)
with compensating transactions to maintain eventual consistency.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional


class SagaStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    COMPENSATING = "compensating"
    COMPENSATED = "compensated"


@dataclass
class SagaStep:
    name: str
    action: Callable[[Dict[str, Any]], Dict[str, Any]]
    compensate: Callable[[Dict[str, Any]], None]


@dataclass
class SagaExecution:
    saga_id: str
    saga_type: str
    status: SagaStatus
    context: Dict[str, Any]
    completed_steps: List[str]
    failed_step: Optional[str]
    error: Optional[str]
    started_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None


class Saga:
    """
    Orchestration-based saga coordinator.

    Steps execute sequentially. On failure, completed steps run
    their compensating transactions in reverse order.
    """

    def __init__(self, saga_type: str) -> None:
        self.saga_type = saga_type
        self._steps: List[SagaStep] = []

    def step(
        self,
        name: str,
        action: Callable[[Dict[str, Any]], Dict[str, Any]],
        compensate: Callable[[Dict[str, Any]], None],
    ) -> "Saga":
        """Add a step to the saga (fluent builder)."""
        self._steps.append(SagaStep(name=name, action=action, compensate=compensate))
        return self

    def execute(self, initial_context: Dict[str, Any]) -> SagaExecution:
        """
        Execute all saga steps sequentially.

        On failure: triggers compensating transactions in reverse order.
        """
        import uuid
        saga_id = str(uuid.uuid4())[:8]
        context = dict(initial_context)
        completed_steps: List[str] = []

        execution = SagaExecution(
            saga_id=saga_id,
            saga_type=self.saga_type,
            status=SagaStatus.RUNNING,
            context=context,
            completed_steps=completed_steps,
            failed_step=None,
            error=None,
        )

        for step in self._steps:
            try:
                result = step.action(context)
                context.update(result or {})
                completed_steps.append(step.name)
            except Exception as exc:
                execution.status = SagaStatus.FAILED
                execution.failed_step = step.name
                execution.error = str(exc)
                # Compensate in reverse
                self._compensate(completed_steps, context)
                execution.status = SagaStatus.COMPENSATED
                execution.finished_at = time.time()
                return execution

        execution.status = SagaStatus.COMPLETED
        execution.finished_at = time.time()
        return execution

    def _compensate(self, completed: List[str], context: Dict[str, Any]) -> None:
        """Run compensating transactions in reverse order."""
        completed_set = set(completed)
        for step in reversed(self._steps):
            if step.name in completed_set:
                try:
                    step.compensate(context)
                except Exception:
                    pass   # Best-effort compensation
