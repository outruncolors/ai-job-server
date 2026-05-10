from __future__ import annotations

import asyncio
from pathlib import Path
from typing import List, Optional

from .config import OmniVoiceConfig


class OmniVoiceEphemeralRunner:
    def __init__(self, config: OmniVoiceConfig) -> None:
        self.config = config

    def build_command(
        self,
        text: str,
        output_path: Path,
        *,
        language: Optional[str] = None,
        instruct: Optional[str] = None,
        ref_audio_filename: Optional[str] = None,
        ref_text: Optional[str] = None,
        num_step: Optional[int] = None,
        guidance_scale: Optional[float] = None,
    ) -> List[str]:
        cmd: List[str] = list(self.config.infer_base_command or ["omnivoice-infer"])
        cmd += ["--model", self.config.model]
        cmd += ["--text", text]
        cmd += ["--output", str(output_path)]
        lang = language or self.config.language
        if lang:
            cmd += ["--language", lang]
        inst = instruct or self.config.instruct
        if inst:
            cmd += ["--instruct", inst]
        ref_fn = ref_audio_filename or self.config.ref_audio_filename
        ref_tx = ref_text or self.config.ref_text
        if ref_fn and ref_tx:
            cmd += ["--ref_audio", ref_fn, "--ref_text", ref_tx]
        if num_step is not None:
            cmd += ["--num_step", str(num_step)]
        if guidance_scale is not None:
            cmd += ["--guidance_scale", str(guidance_scale)]
        return cmd

    async def run(
        self,
        text: str,
        output_path: Path,
        job_dir: Path,
        *,
        language: Optional[str] = None,
        instruct: Optional[str] = None,
        ref_audio_filename: Optional[str] = None,
        ref_text: Optional[str] = None,
        num_step: Optional[int] = None,
        guidance_scale: Optional[float] = None,
    ) -> tuple[bytes, bytes]:
        cmd = self.build_command(
            text,
            output_path,
            language=language,
            instruct=instruct,
            ref_audio_filename=ref_audio_filename,
            ref_text=ref_text,
            num_step=num_step,
            guidance_scale=guidance_scale,
        )
        logs_path = job_dir / "logs.txt"
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(
                "OmniVoice is not installed or 'omnivoice-infer' is not on PATH"
            ) from exc

        stdout, stderr = await proc.communicate()
        with logs_path.open("a", encoding="utf-8") as f:
            if stdout:
                f.write(stdout.decode(errors="replace"))
            if stderr:
                f.write(stderr.decode(errors="replace"))
        if proc.returncode != 0:
            raise RuntimeError(
                f"omnivoice-infer exited with code {proc.returncode}. "
                f"stderr: {stderr.decode(errors='replace')[:500]}"
            )
        return stdout, stderr
