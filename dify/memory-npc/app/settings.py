"""Environment-backed configuration for the npc-memory service."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class ServiceSettings:
    listen_host: str = "0.0.0.0"
    listen_port: int = 8877
    powercontext_url: str = "http://127.0.0.1:8878"
    history_window_turns: int = 12
    max_action_chars: int = 2000
    max_reply_chars: int = 8000
    request_timeout_seconds: float = 30.0

    @classmethod
    def from_env(cls) -> "ServiceSettings":
        return cls(
            listen_host=os.environ.get("NPC_MEMORY_HOST", "0.0.0.0"),
            listen_port=int(os.environ.get("NPC_MEMORY_PORT", "8877")),
            powercontext_url=os.environ.get(
                "POWERCONTEXT_SERVER_URL", "http://127.0.0.1:8878"
            ).rstrip("/"),
            history_window_turns=int(os.environ.get("NPC_MEMORY_HISTORY_WINDOW", "12")),
            max_action_chars=int(os.environ.get("NPC_MEMORY_MAX_ACTION_CHARS", "2000")),
            max_reply_chars=int(os.environ.get("NPC_MEMORY_MAX_REPLY_CHARS", "8000")),
            request_timeout_seconds=float(
                os.environ.get("NPC_MEMORY_TIMEOUT_SECONDS", "30")
            ),
        )
