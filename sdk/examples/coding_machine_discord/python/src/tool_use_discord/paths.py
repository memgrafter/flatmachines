from __future__ import annotations

import os
from pathlib import Path


def mk42_home() -> Path:
    return Path(os.environ.get("MK42_HOME", "~/.agents/mk42")).expanduser().resolve()


def default_history_dir() -> str:
    return str(
        Path(
            os.environ.get(
                "TOOL_USE_DISCORD_HISTORY_DIR",
                str(mk42_home() / "history"),
            )
        ).expanduser().resolve()
    )
