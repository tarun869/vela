"""
Job scheduler for VPP automated workflows.

Runs recurring tasks (forecast updates, settlement runs, telemetry
polls) with cron-like scheduling, retry logic, and execution history.
"""
from __future__ import annotations

import time
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class Job:
    job_id: str
    name: str
    func: Callable[[], Any]
    interval_s: float        # Run every N seconds
    max_retries: int = 3
    retry_delay_s: float = 30.0
    enabled: bool = True
    tags: List[str] = field(default_factory=list)


@dataclass
class JobExecution:
    job_id: str
    run_number: int
    status: JobStatus
    started_at: float
    finished_at: Optional[float] = None
    error: Optional[str] = None
    result: Any = None

    @property
    def duration_s(self) -> Optional[float]:
        if self.finished_at:
            return self.finished_at - self.started_at
        return None


class JobScheduler:
    """
    Simple cron-like job scheduler running in a background thread.

    Each job has an interval and is triggered when elapsed time >= interval.
    Failed jobs are retried up to max_retries times.
    """

    def __init__(self) -> None:
        self._jobs: Dict[str, Job] = {}
        self._last_run: Dict[str, float] = {}
        self._history: List[JobExecution] = []
        self._run_counter: Dict[str, int] = {}
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    def register(self, job: Job) -> None:
        with self._lock:
            self._jobs[job.job_id] = job
            self._last_run[job.job_id] = 0.0
            self._run_counter[job.job_id] = 0

    def unregister(self, job_id: str) -> None:
        with self._lock:
            self._jobs.pop(job_id, None)

    def _run_job(self, job: Job) -> None:
        """Execute a job with retry logic."""
        self._run_counter[job.job_id] = self._run_counter.get(job.job_id, 0) + 1
        exec_record = JobExecution(
            job_id=job.job_id,
            run_number=self._run_counter[job.job_id],
            status=JobStatus.RUNNING,
            started_at=time.time(),
        )

        last_error: Optional[str] = None
        for attempt in range(job.max_retries):
            try:
                result = job.func()
                exec_record.status = JobStatus.SUCCEEDED
                exec_record.result = result
                exec_record.finished_at = time.time()
                break
            except Exception as exc:
                last_error = str(exc)
                if attempt < job.max_retries - 1:
                    time.sleep(job.retry_delay_s * (attempt + 1))
        else:
            exec_record.status = JobStatus.FAILED
            exec_record.error = last_error
            exec_record.finished_at = time.time()

        with self._lock:
            self._history.append(exec_record)
            self._last_run[job.job_id] = time.time()
            if len(self._history) > 1000:
                self._history.pop(0)

    def tick(self) -> int:
        """Check and execute any overdue jobs. Returns number of jobs triggered."""
        now = time.time()
        triggered = 0
        with self._lock:
            jobs_to_run = []
            for jid, job in self._jobs.items():
                if not job.enabled:
                    continue
                if now - self._last_run.get(jid, 0.0) >= job.interval_s:
                    jobs_to_run.append(job)

        for job in jobs_to_run:
            t = threading.Thread(target=self._run_job, args=(job,), daemon=True)
            t.start()
            triggered += 1
        return triggered

    def history(self, job_id: Optional[str] = None, limit: int = 50) -> List[JobExecution]:
        with self._lock:
            hist = self._history if not job_id else [e for e in self._history if e.job_id == job_id]
            return list(reversed(hist[-limit:]))

    def job_stats(self) -> Dict[str, Dict]:
        stats: Dict[str, Dict] = {}
        with self._lock:
            for job_id in self._jobs:
                job_runs = [e for e in self._history if e.job_id == job_id]
                succeeded = sum(1 for e in job_runs if e.status == JobStatus.SUCCEEDED)
                failed = sum(1 for e in job_runs if e.status == JobStatus.FAILED)
                stats[job_id] = {
                    "total": len(job_runs),
                    "succeeded": succeeded,
                    "failed": failed,
                    "success_rate": succeeded / max(len(job_runs), 1),
                }
        return stats
