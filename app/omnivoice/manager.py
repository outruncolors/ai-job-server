from __future__ import annotations

import shutil
from typing import Optional


class OmniVoiceManager:
    def __init__(self) -> None:
        self.active_voice_jobs: int = 0

    def ephemeral_available(self) -> bool:
        return shutil.which("omnivoice-infer") is not None


_manager: Optional[OmniVoiceManager] = None


def get_manager() -> OmniVoiceManager:
    global _manager
    if _manager is None:
        _manager = OmniVoiceManager()
    return _manager
