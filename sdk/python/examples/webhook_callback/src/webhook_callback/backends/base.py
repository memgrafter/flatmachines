"""
Callback Backend Interface

Defines the abstract interface for handling long-running jobs with callbacks.
Implementations can use polling, webhook servers, or external services.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from datetime import datetime


class JobStatus:
    """Standard job status values."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"


class CallbackBackend(ABC):
    """
    Abstract interface for long-running job callback mechanisms.

    This interface supports two patterns:
    1. Polling: Submit job, then poll status until complete
    2. Callback: Submit job with callback URL, wait for webhook

    All methods should be idempotent and safe to retry.
    """

    @abstractmethod
    async def submit(self, endpoint: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Submit a long-running job.

        This should be a fast operation (< 30 seconds) that just initiates
        the job and returns immediately with a job ID.

        Args:
            endpoint: The job submission endpoint URL
            data: Job parameters/data to submit

        Returns:
            Dict containing:
                - job_id: Unique identifier for the job
                - status_url: URL to check job status
                - callback_url: (Optional) URL where callback will be sent
                - submitted_at: ISO timestamp of submission

        Raises:
            Exception: If submission fails
        """
        pass

    @abstractmethod
    async def check_status(self, status_url: str, job_id: str) -> Dict[str, Any]:
        """
        Check the current status of a job (single check, non-blocking).

        This should be fast (< 30 seconds) and return immediately.
        It's called repeatedly in a state loop with checkpoints between calls.

        Args:
            status_url: URL to check job status
            job_id: The job identifier

        Returns:
            Dict containing:
                - status: One of JobStatus values (pending/running/completed/failed)
                - progress: (Optional) Progress percentage (0-100)
                - result: (Optional) Result data if completed
                - error: (Optional) Error message if failed
                - updated_at: ISO timestamp of last update

        Raises:
            Exception: If status check fails
        """
        pass

    async def start_callback_listener(self) -> Optional[str]:
        """
        Start a callback listener (for webhook-based backends).

        Optional method for backends that use webhooks instead of polling.
        Should be idempotent - safe to call multiple times.

        Returns:
            Callback URL where webhooks should be sent, or None if not applicable
        """
        return None

    async def check_callback_received(self, job_id: str) -> Optional[Dict[str, Any]]:
        """
        Check if a callback has been received for this job (non-blocking).

        Optional method for webhook-based backends. Returns immediately
        with callback data if received, None otherwise.

        Args:
            job_id: The job identifier

        Returns:
            Callback data if received, None otherwise
        """
        return None

    async def cleanup(self):
        """
        Clean up resources (stop servers, close connections, etc).

        Called when the job is complete or the machine is shutting down.
        Should be idempotent.
        """
        pass

    def get_backend_type(self) -> str:
        """Return a string identifying the backend type (for logging)."""
        return self.__class__.__name__
