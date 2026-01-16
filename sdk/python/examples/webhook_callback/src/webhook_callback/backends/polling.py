"""
Polling Backend

Makes HTTP requests to check job status periodically.
Works with any REST API that provides job submission and status endpoints.
"""

import httpx
from typing import Dict, Any
from datetime import datetime
from .base import CallbackBackend, JobStatus


class PollingBackend(CallbackBackend):
    """
    Polling-based backend for long-running jobs.

    Submits jobs via HTTP POST and checks status via HTTP GET.
    The actual polling loop is handled by the state machine,
    this backend just does single submit/check operations.
    """

    def __init__(self, timeout: float = 30.0):
        """
        Initialize polling backend.

        Args:
            timeout: HTTP request timeout in seconds
        """
        self.timeout = timeout

    async def submit(self, endpoint: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Submit job to endpoint via HTTP POST.

        Expected response format:
        {
            "job_id": "abc123",
            "status_url": "https://api.example.com/jobs/abc123",
            "status": "pending"
        }

        Args:
            endpoint: Job submission URL
            data: Job data to submit

        Returns:
            Job submission response with job_id and status_url
        """
        async with httpx.AsyncClient() as client:
            response = await client.post(
                endpoint,
                json=data,
                timeout=self.timeout,
                headers={"Content-Type": "application/json"}
            )
            response.raise_for_status()
            result = response.json()

        # Add submission timestamp
        result["submitted_at"] = datetime.utcnow().isoformat()

        # Validate required fields
        if "job_id" not in result:
            raise ValueError("Response missing 'job_id' field")
        if "status_url" not in result:
            # Try to construct status URL from job_id
            if endpoint.endswith("/submit"):
                base_url = endpoint.rsplit("/", 1)[0]
                result["status_url"] = f"{base_url}/status/{result['job_id']}"
            else:
                raise ValueError("Response missing 'status_url' field")

        return result

    async def check_status(self, status_url: str, job_id: str) -> Dict[str, Any]:
        """
        Check job status via HTTP GET.

        Expected response format:
        {
            "status": "completed",  # or "pending", "running", "failed"
            "progress": 75,         # optional
            "result": {...},        # if completed
            "error": "...",         # if failed
        }

        Args:
            status_url: URL to check status
            job_id: Job identifier (used in error messages)

        Returns:
            Status response with current job state
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                status_url,
                timeout=self.timeout,
                headers={"Accept": "application/json"}
            )
            response.raise_for_status()
            result = response.json()

        # Add timestamp
        result["updated_at"] = datetime.utcnow().isoformat()

        # Validate status field
        if "status" not in result:
            raise ValueError("Response missing 'status' field")

        # Normalize status values
        status = result["status"].lower()
        if status not in [JobStatus.PENDING, JobStatus.RUNNING,
                          JobStatus.COMPLETED, JobStatus.FAILED]:
            # Try to map common variants
            status_mapping = {
                "queued": JobStatus.PENDING,
                "processing": JobStatus.RUNNING,
                "success": JobStatus.COMPLETED,
                "done": JobStatus.COMPLETED,
                "error": JobStatus.FAILED,
                "cancelled": JobStatus.FAILED,
            }
            result["status"] = status_mapping.get(status, JobStatus.RUNNING)
        else:
            result["status"] = status

        return result

    def get_backend_type(self) -> str:
        return f"PollingBackend(timeout={self.timeout}s)"
