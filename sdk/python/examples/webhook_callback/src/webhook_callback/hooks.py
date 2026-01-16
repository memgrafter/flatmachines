"""
Long-Running Job Hooks

Demonstrates checkpoint-safe hook actions for long-running jobs.

Key principle: Each hook action should complete quickly (< 30 seconds).
The polling loop happens in the state machine, with checkpoints between iterations.
"""

import asyncio
from typing import Any, Dict
from datetime import datetime
from flatagents import MachineHooks, get_logger
from .backends import CallbackBackend, JobStatus

logger = get_logger(__name__)


class LongRunningJobHooks(MachineHooks):
    """
    Hooks for long-running job management with pluggable backends.

    This demonstrates the correct pattern:
    - submit_job: Quick action to start job and get job_id
    - poll_once: Quick action to check status (single check)
    - State machine handles the polling loop with checkpoints

    NOT:
    - submit_and_wait: BAD - blocks for hours, can't checkpoint mid-execution
    """

    def __init__(self, backend: CallbackBackend):
        """
        Initialize hooks with a callback backend.

        Args:
            backend: Backend implementation (MockBackend, PollingBackend, etc)
        """
        self.backend = backend
        logger.info(f"Initialized LongRunningJobHooks with {self.backend.get_backend_type()}")

    async def on_action(self, action_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Handle custom actions."""
        if action_name == "submit_job":
            return await self._submit_job(context)
        elif action_name == "poll_once":
            return await self._poll_once(context)
        return context

    async def _submit_job(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Submit a long-running job (quick operation).

        This should complete in < 30 seconds. It just initiates the job
        and returns a job_id, it does NOT wait for completion.

        Updates context with:
        - job_id: Unique identifier for tracking
        - status_url: URL to check status
        - callback_url: (Optional) URL for callbacks
        - submitted_at: Timestamp
        """
        endpoint = context.get("job_endpoint")
        text = context.get("text", "")

        logger.info(f"Submitting job to: {endpoint}")
        logger.info(f"Job data: {text[:100]}...")

        try:
            # Start callback listener if backend supports it
            callback_url = await self.backend.start_callback_listener()
            if callback_url:
                logger.info(f"Callback listener started at: {callback_url}")

            # Submit the job
            result = await self.backend.submit(
                endpoint=endpoint,
                data={"text": text}
            )

            # Update context with job info
            context["job_id"] = result["job_id"]
            context["status_url"] = result.get("status_url")
            context["callback_url"] = result.get("callback_url", callback_url)
            context["submitted_at"] = result.get("submitted_at", datetime.utcnow().isoformat())

            logger.info(f"✓ Job submitted: {context['job_id']}")
            if context.get("callback_url"):
                logger.info(f"  Callback URL: {context['callback_url']}")
            if context.get("status_url"):
                logger.info(f"  Status URL: {context['status_url']}")

        except Exception as e:
            logger.error(f"✗ Job submission failed: {e}")
            context["submission_error"] = str(e)

        return context

    async def _poll_once(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Check job status once (quick operation).

        This should complete in < 30 seconds. It performs a single
        status check and returns immediately. The state machine will
        call this repeatedly in a loop with checkpoints between calls.

        Updates context with:
        - status: Current job status (pending/running/completed/failed)
        - progress: (Optional) Progress percentage
        - result: (Optional) Result data if completed
        - error: (Optional) Error message if failed
        - last_poll_error: Error message if polling failed
        - poll_error_type: Error classification (transient/client_error/server_error)
        """
        job_id = context.get("job_id")
        status_url = context.get("status_url")
        poll_count = context.get("poll_count", 0)

        if not job_id:
            logger.error("Cannot poll: no job_id in context")
            context["last_poll_error"] = "No job_id in context"
            context["poll_error_type"] = "client_error"
            return context

        logger.info(f"Polling job {job_id} (attempt #{poll_count + 1})")

        try:
            # Check status (single check, returns immediately)
            status_data = await self.backend.check_status(status_url, job_id)

            # Clear any previous polling errors (job status check succeeded)
            context["last_poll_error"] = None
            context["poll_error_type"] = None

            # Update context with current status
            context["status"] = status_data.get("status", JobStatus.PENDING)
            context["progress"] = status_data.get("progress", 0)

            # Add result if completed
            if status_data.get("status") == JobStatus.COMPLETED:
                context["result"] = status_data.get("result")
                context["end_time"] = datetime.utcnow().isoformat()
                logger.info(f"✓ Job {job_id} completed!")

            # Add error if failed (job-level failure, not polling error)
            elif status_data.get("status") == JobStatus.FAILED:
                context["error"] = status_data.get("error", "Unknown error")
                context["end_time"] = datetime.utcnow().isoformat()
                logger.error(f"✗ Job {job_id} failed: {context['error']}")

            # Log progress for running jobs
            else:
                progress = context.get("progress", 0)
                status = context.get("status", "unknown")
                logger.info(f"  Status: {status}, Progress: {progress}%")

        except Exception as e:
            # Classify the polling error
            error_type = self._classify_error(e)
            logger.error(f"✗ Status check failed ({error_type}): {e}")

            # Store error information in context for state machine to handle
            context["last_poll_error"] = str(e)
            context["poll_error_type"] = error_type

            # Don't update status on polling error
            # State machine will handle retries based on error_type

        return context

    def _classify_error(self, error: Exception) -> str:
        """
        Classify error type for retry/failure logic.

        Returns:
            - "rate_limit": 429, 408 - Needs backoff, retry automatically
            - "auth_required": 401, 402, 403 - Needs human intervention, checkpoint and pause
            - "permanent": 400, 404, 410 - Truly permanent, fail immediately
            - "server_error": 5xx - Likely transient, retry
            - "transient": Network/timeout - Temporary, retry
        """
        import httpx

        if isinstance(error, httpx.HTTPStatusError):
            status_code = error.response.status_code

            if 400 <= status_code < 500:
                # Classify 4xx errors more granularly

                # Rate limiting - should retry with backoff
                if status_code == 429:  # Too Many Requests
                    return "rate_limit"
                if status_code == 408:  # Request Timeout (client timeout)
                    return "rate_limit"

                # Authentication/authorization - needs human intervention
                if status_code == 401:  # Unauthorized (bad/missing credentials)
                    return "auth_required"
                if status_code == 402:  # Payment Required
                    return "auth_required"
                if status_code == 403:  # Forbidden (insufficient permissions)
                    return "auth_required"

                # Permanent errors - no point retrying
                if status_code == 400:  # Bad Request (malformed request)
                    return "permanent"
                if status_code == 404:  # Not Found (wrong job_id or URL)
                    return "permanent"
                if status_code == 410:  # Gone (resource deleted)
                    return "permanent"

                # Other 4xx - treat as permanent by default
                return "permanent"

            elif 500 <= status_code < 600:
                # 5xx server errors - usually transient
                return "server_error"
            else:
                # 3xx redirects shouldn't reach here (httpx follows them)
                # But if they do, treat as transient
                return "transient"

        elif isinstance(error, (httpx.TimeoutException, httpx.ConnectTimeout, httpx.ReadTimeout)):
            # Timeouts are transient
            return "transient"
        elif isinstance(error, (httpx.NetworkError, httpx.ConnectError)):
            # Network errors are transient
            return "transient"
        else:
            # Unknown errors - treat as transient to be safe
            return "transient"

    async def on_machine_end(self, context: Dict[str, Any], output: Any) -> Any:
        """Clean up backend resources when machine completes."""
        logger.info("Cleaning up backend resources...")
        try:
            await self.backend.cleanup()
        except Exception as e:
            logger.warning(f"Cleanup error (non-fatal): {e}")
        return output

    def on_state_enter(self, state: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Log state transitions for visibility."""
        job_id = context.get("job_id")
        if job_id:
            logger.info(f"→ [{job_id}] Entering state: {state}")
        else:
            logger.info(f"→ Entering state: {state}")
        return context

    def on_state_exit(self, state: str, context: Dict[str, Any], output: Any) -> Any:
        """Log state exits."""
        job_id = context.get("job_id")
        if state == "poll_status":
            status = context.get("status", "unknown")
            progress = context.get("progress", 0)
            if job_id:
                logger.info(f"← [{job_id}] Exiting {state}: {status} ({progress}%)")
            else:
                logger.info(f"← Exiting {state}: {status} ({progress}%)")
        else:
            if job_id:
                logger.info(f"← [{job_id}] Exiting state: {state}")
            else:
                logger.info(f"← Exiting state: {state}")
        return output
