from __future__ import annotations

import time
from typing import Any, Optional

import requests


class DiscordAPI:
    BASE_URL = "https://discord.com/api/v10"

    def __init__(self, *, bot_token: str, channel_id: str, timeout_seconds: float = 30.0):
        self.bot_token = bot_token
        self.channel_id = str(channel_id)
        self.timeout_seconds = timeout_seconds
        self._session = requests.Session()

    def get_current_user(self) -> dict[str, Any]:
        return self._request("GET", "/users/@me")

    def list_channel_messages(self, *, limit: int = 50) -> list[dict[str, Any]]:
        limit = max(1, min(100, int(limit)))
        data = self._request(
            "GET",
            f"/channels/{self.channel_id}/messages",
            params={"limit": limit},
        )
        if not isinstance(data, list):
            raise RuntimeError(f"Unexpected Discord response type for messages: {type(data)}")
        return data

    def post_channel_message(self, content: str, reply_to_message_id: Optional[str] = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"content": content}
        if reply_to_message_id:
            payload["message_reference"] = {"message_id": str(reply_to_message_id)}

        data = self._request(
            "POST",
            f"/channels/{self.channel_id}/messages",
            json=payload,
        )
        if not isinstance(data, dict):
            raise RuntimeError(f"Unexpected Discord response type for post: {type(data)}")
        return data

    def _request(self, method: str, path: str, **kwargs) -> Any:
        headers = kwargs.pop("headers", {})
        headers = {
            **headers,
            "Authorization": f"Bot {self.bot_token}",
            "Content-Type": "application/json",
        }

        while True:
            response = self._session.request(
                method=method,
                url=f"{self.BASE_URL}{path}",
                headers=headers,
                timeout=self.timeout_seconds,
                **kwargs,
            )

            if 200 <= response.status_code < 300:
                if not response.text:
                    return {}
                return response.json()

            if response.status_code == 429:
                payload = response.json()
                retry_after = float(payload.get("retry_after", 1.0))
                time.sleep(max(0.0, retry_after))
                continue

            raise RuntimeError(
                f"Discord API request failed: {method} {path} status={response.status_code} body={response.text}"
            )
