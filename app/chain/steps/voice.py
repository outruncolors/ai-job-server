from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional

from .llm import _parse_gemma_tool_calls


async def run_voice_step(
    step_dir: Path,
    step: Any,
    text: str,
    client: Any = None,
    llm_config: Any = None,
) -> str:
    """Execute a voice step. Returns the output filename."""
    from ...omnivoice.config import get_config
    from ...omnivoice.manager import get_manager
    from ...voice_presets import get_preset, resolve_preset_wav

    if not step.voice_preset_id:
        raise RuntimeError("Voice step requires a voice_preset_id")

    preset = get_preset(step.voice_preset_id)
    if preset is None:
        raise RuntimeError(f"Voice preset {step.voice_preset_id!r} not found")

    config = get_config()
    manager = get_manager()
    output_path = step_dir / f"output.{config.response_format}"

    effective: dict = {
        "model": config.model,
        "voice_preset_id": step.voice_preset_id,
        "voice_preset_name": preset["name"],
        "response_format": config.response_format,
    }
    (step_dir / "request.json").write_text(
        json.dumps({**step.model_dump(), "effective": effective}, indent=2), encoding="utf-8"
    )

    wav_path = resolve_preset_wav(step.voice_preset_id)
    if wav_path is None:
        raise RuntimeError(
            f"Voice preset {preset['name']!r} wav file missing. Re-upload or remove the preset."
        )

    from ...omnivoice.runner import OmniVoiceEphemeralRunner
    runner = OmniVoiceEphemeralRunner(config)
    common_run_kwargs = dict(
        language=config.language,
        instruct=config.instruct,
        ref_audio_filename=str(wav_path),
        ref_text=preset["caption"],
        num_step=None,
        guidance_scale=None,
    )

    # Determine segments (auto-segment takes priority over preprocess)
    segments = None
    if step.voice_auto_segment and client and llm_config:
        from ...omnivoice.constants import DEFAULT_VOICE_AUTO_SEGMENT_PROMPT
        from ...mcp.registry import get_tool, to_openai_schema
        from ...models import VoiceSegment

        tool_def = get_tool("format_voice_segments")
        seg_prompt = config.voice_auto_segment_prompt or DEFAULT_VOICE_AUTO_SEGMENT_PROMPT
        prompt_content = f"{seg_prompt}\n\n{text}"
        (step_dir / "auto_segment_prompt.txt").write_text(prompt_content, encoding="utf-8")
        choice = await client.chat(
            messages=[{"role": "user", "content": prompt_content}],
            llm_config=llm_config,
            tools=[to_openai_schema(tool_def)],
        )
        message = choice.get("message", {})
        raw_content = message.get("content") or ""

        # Save raw LLM response for debugging
        (step_dir / "auto_segment_raw.txt").write_text(
            json.dumps(message, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        raw_tool_calls = message.get("tool_calls") or []
        if not raw_tool_calls and raw_content:
            raw_tool_calls = _parse_gemma_tool_calls(raw_content)

        seg_data: list[dict] = []
        if raw_tool_calls:
            tc = raw_tool_calls[0]
            args = json.loads(tc["function"]["arguments"])
            seg_data = args.get("segments", [])
        elif raw_content:
            # Fallback: model responded with a JSON array instead of calling the tool
            stripped = raw_content.strip()
            fence = re.match(r"^```(?:json)?\s*([\s\S]*?)```\s*$", stripped)
            if fence:
                stripped = fence.group(1).strip()
            try:
                parsed = json.loads(stripped)
                if isinstance(parsed, list):
                    seg_data = parsed
            except json.JSONDecodeError:
                pass

        if not seg_data:
            raise RuntimeError(
                "voice_auto_segment: LLM did not call format_voice_segments and "
                "returned no parseable JSON. See auto_segment_raw.txt for the raw response."
            )

        segments = [
            VoiceSegment(text=s["text"], delay_ms=int(s.get("delay_ms", 500)))
            for s in seg_data
            if str(s.get("text", "")).strip()
        ]
        if not segments:
            raise RuntimeError("voice_auto_segment: no non-empty segments returned")

    manager.active_voice_jobs += 1
    try:
        if segments:
            from ...audio_utils import merge_wav_files
            seg_paths = []
            delay_ms_list = []
            for idx, seg in enumerate(segments):
                seg_path = step_dir / f"segment_{idx:03d}.wav"
                await runner.run(seg.text, seg_path, step_dir, **common_run_kwargs)
                seg_paths.append(seg_path)
                delay_ms_list.append(seg.delay_ms)
            merge_wav_files(seg_paths, delay_ms_list, output_path)
        else:
            if step.voice_preprocess and client and llm_config:
                from ...omnivoice.constants import DEFAULT_VOICE_PREPROCESS_PROMPT
                preprocess_prompt = config.voice_preprocess_prompt or DEFAULT_VOICE_PREPROCESS_PROMPT
                text = await client.generate(f"{preprocess_prompt}\n\n{text}", llm_config)
            parts = [p for p in [step.voice_pre, text, step.voice_post] if p]
            tts_text = "\n\n".join(parts) if parts else text
            await runner.run(tts_text, output_path, step_dir, **common_run_kwargs)
    finally:
        manager.active_voice_jobs -= 1
    return output_path.name
