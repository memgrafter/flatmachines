"""
Webhook Server Backend

Runs an embedded HTTP server to receive callbacks from long-running jobs.
Combines webhook receiving with polling fallback.
"""

import asyncio
import httpx
from typing import Dict, Any, Optional
from datetime import datetime
from aiohttp import web
from .base import CallbackBackend, JobStatus
from flatagents import get_logger

logger = get_logger(__name__)


class WebhookServerBackend(CallbackBackend):
    """
    Webhook-based backend with embedded HTTP server.

    Starts a local HTTP server to receive callbacks, combines with
    polling as a fallback. The state machine checks for received
    callbacks in its polling loop.
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 8765,
        timeout: float = 30.0,
        fallback_polling: bool = True
    ):
        """
        Initialize webhook server backend.

        Args:
            host: Host to bind the webhook server to
            port: Port to bind the webhook server to
            timeout: HTTP request timeout in seconds
            fallback_polling: If True, poll status if callback not received
        """
        self.host = host
        self.port = port
        self.timeout = timeout
        self.fallback_polling = fallback_polling

        self.server_started = False
        self.runner: Optional[web.AppRunner] = None
        self.site: Optional[web.TCPSite] = None
        self.callbacks: Dict[str, Dict[str, Any]] = {}

    async def start_callback_listener(self) -> str:
        """
        Start the webhook server.

        Idempotent - safe to call multiple times.

        Returns:
            Base URL where callbacks should be sent
        """
        if self.server_started:
            logger.info(f"Webhook server already running at http://{self.host}:{self.port}")
            return f"http://{self.host}:{self.port}/callback"

        # Create aiohttp application
        app = web.Application()
        app.router.add_post('/callback/{job_id}', self._handle_callback)
        app.router.add_get('/health', self._handle_health)

        # Start server
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, self.host, self.port)
        await self.site.start()

        self.server_started = True
        logger.info(f"✓ Webhook server started at http://{self.host}:{self.port}")

        return f"http://{self.host}:{self.port}/callback"

    async def _handle_callback(self, request: web.Request) -> web.Response:
        """Handle incoming webhook callback."""
        job_id = request.match_info['job_id']
        data = await request.json()

        logger.info(f"✓ Received callback for job {job_id}")

        # Store callback data
        self.callbacks[job_id] = {
            "job_id": job_id,
            "status": data.get("status", JobStatus.COMPLETED),
            "result": data.get("result"),
            "error": data.get("error"),
            "received_at": datetime.utcnow().isoformat(),
            **data
        }

        return web.json_response({"status": "received"})

    async def _handle_health(self, request: web.Request) -> web.Response:
        """Health check endpoint."""
        return web.json_response({"status": "healthy", "callbacks": len(self.callbacks)})

    async def submit(self, endpoint: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Submit job with callback URL.

        The callback URL is included in the submission so the
        external service knows where to send the completion notification.
        """
        # Ensure server is started
        callback_base = await self.start_callback_listener()

        # Submit job via HTTP POST
        async with httpx.AsyncClient() as client:
            # Include callback URL in submission
            submission_data = {
                **data,
                "callback_url": f"{callback_base}/{{job_id}}"  # Template with job_id
            }

            response = await client.post(
                endpoint,
                json=submission_data,
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

        # Construct callback URL with actual job_id
        job_id = result["job_id"]
        result["callback_url"] = f"{callback_base}/{job_id}"

        logger.info(f"Job {job_id} submitted with callback: {result['callback_url']}")

        return result

    async def check_callback_received(self, job_id: str) -> Optional[Dict[str, Any]]:
        """
        Check if a callback has been received (non-blocking).

        Returns callback data if received, None otherwise.
        """
        return self.callbacks.get(job_id)

    async def check_status(self, status_url: str, job_id: str) -> Dict[str, Any]:
        """
        Check job status - first check for callback, then poll if enabled.

        This implements the hybrid pattern: prefer callbacks, fall back to polling.
        """
        # First check if we received a callback
        callback = await self.check_callback_received(job_id)
        if callback:
            logger.info(f"Using callback data for job {job_id}")
            return {
                "status": callback.get("status", JobStatus.COMPLETED),
                "result": callback.get("result"),
                "error": callback.get("error"),
                "updated_at": callback.get("received_at"),
                "via_callback": True,
            }

        # If no callback and polling enabled, poll the status endpoint
        if self.fallback_polling and status_url:
            logger.info(f"No callback yet, polling status for job {job_id}")
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    status_url,
                    timeout=self.timeout,
                    headers={"Accept": "application/json"}
                )
                response.raise_for_status()
                result = response.json()

            result["updated_at"] = datetime.utcnow().isoformat()
            result["via_callback"] = False

            # Normalize status
            if "status" in result:
                result["status"] = result["status"].lower()

            return result
        else:
            # No callback received yet, return pending
            return {
                "status": JobStatus.PENDING,
                "updated_at": datetime.utcnow().isoformat(),
                "via_callback": False,
            }

    async def cleanup(self):
        """Stop the webhook server and clean up resources."""
        if self.site:
            await self.site.stop()
        if self.runner:
            await self.runner.cleanup()

        self.server_started = False
        self.callbacks.clear()
        logger.info("Webhook server stopped")

    def get_backend_type(self) -> str:
        return f"WebhookServerBackend({self.host}:{self.port})"
