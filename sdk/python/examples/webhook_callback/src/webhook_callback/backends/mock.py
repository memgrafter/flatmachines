"""
Mock Backend

Simulates a long-running job without external dependencies.
Useful for testing, demos, and development.
"""

import asyncio
from typing import Dict, Any
from datetime import datetime, timedelta
import uuid
from .base import CallbackBackend, JobStatus


class MockBackend(CallbackBackend):
    """
    Mock backend that simulates long-running jobs in-memory.

    Jobs "complete" after a configurable number of status checks,
    simulating a job that takes time to process.
    """

    def __init__(
        self,
        checks_until_complete: int = 3,
        simulate_progress: bool = True,
        failure_probability: float = 0.0
    ):
        """
        Initialize mock backend.

        Args:
            checks_until_complete: Number of status checks before job completes
            simulate_progress: Whether to report incremental progress
            failure_probability: Probability (0-1) that a job fails
        """
        self.checks_until_complete = checks_until_complete
        self.simulate_progress = simulate_progress
        self.failure_probability = failure_probability
        self.jobs: Dict[str, Dict[str, Any]] = {}

    async def submit(self, endpoint: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Simulate job submission."""
        job_id = str(uuid.uuid4())
        submitted_at = datetime.utcnow().isoformat()

        # Store job state
        self.jobs[job_id] = {
            "job_id": job_id,
            "endpoint": endpoint,
            "data": data,
            "status": JobStatus.PENDING,
            "check_count": 0,
            "submitted_at": submitted_at,
            "updated_at": submitted_at,
        }

        # Simulate network delay
        await asyncio.sleep(0.1)

        return {
            "job_id": job_id,
            "status_url": f"mock://status/{job_id}",
            "submitted_at": submitted_at,
        }

    async def check_status(self, status_url: str, job_id: str) -> Dict[str, Any]:
        """Simulate status check with incremental progress."""
        # Simulate network delay
        await asyncio.sleep(0.1)

        job = self.jobs.get(job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")

        # Increment check count
        job["check_count"] += 1
        check_count = job["check_count"]

        # Update timestamp
        job["updated_at"] = datetime.utcnow().isoformat()

        # Determine status based on checks
        if check_count == 1:
            status = JobStatus.PENDING
            progress = 0
        elif check_count < self.checks_until_complete:
            status = JobStatus.RUNNING
            if self.simulate_progress:
                progress = int((check_count / self.checks_until_complete) * 100)
            else:
                progress = 50
        else:
            # Job complete - check for failure
            import random
            if random.random() < self.failure_probability:
                status = JobStatus.FAILED
                progress = 100
                job["status"] = status
                return {
                    "status": status,
                    "progress": progress,
                    "error": "Simulated job failure",
                    "updated_at": job["updated_at"],
                }
            else:
                status = JobStatus.COMPLETED
                progress = 100

        job["status"] = status
        job["progress"] = progress

        response = {
            "status": status,
            "progress": progress,
            "updated_at": job["updated_at"],
        }

        # Add result if completed
        if status == JobStatus.COMPLETED:
            response["result"] = {
                "job_id": job_id,
                "input_data": job["data"],
                "processed_at": job["updated_at"],
                "processing_time": f"{check_count} checks",
                "output": f"Processed: {job['data'].get('text', 'N/A')}",
                "mock": True,
            }

        return response

    def get_backend_type(self) -> str:
        return f"MockBackend(checks={self.checks_until_complete})"
