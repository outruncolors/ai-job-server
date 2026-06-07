"""The OOC reply pipeline — a lean, single-step LLM job.

Mirrors :func:`app.apps.prattletale.generator.run_director`'s one-step
on-disk-job pattern (reuse the full LLM plumbing: endpoint resolution, model
swap, on-disk trace), but with its own ``ooc.reply`` prompt and **no** memory /
director / feel — an out-of-character chat with the author is meta, so it stays
lean.

The OOC reply sees both channels: the in-character conversation (via
:func:`generator.build_context`) and the full out-of-character history so far
(via :func:`generator.render_ooc_history`). The in-character pipeline, by
contrast, never sees OOC content (the ``ooc`` item type is filtered out of
``generator._flatten_transcript``).

On **any** failure it appends an ``ooc`` model turn whose text is an inline
``(OOC generation failed: …)`` note (the same inline-error philosophy as the
in-character pipeline) rather than raising — so the parallel chat stays
consistent and the failure is visible and debuggable.
"""

from __future__ import annotations

from app.apps.hoodat.characters_store import get_character
from app.apps.prattletale import generator, store
from app.apps.prattletale.models import Author, ItemType
from app.chain.executor import execute_chain_job
from app.chain.models import ChainJobRequest
from app.jobs import create_job, find_job_dir
from app.prompt_pal.service import get_text

# Its own job type so OOC replies are filterable in the on-disk job log (beside
# JOB_TYPE / JOB_TYPE_DIRECTOR in the generator).
JOB_TYPE_OOC = "prattletale_ooc"


async def generate_ooc_reply(conversation_id: str) -> tuple[dict, str]:
    """Generate the author's out-of-character reply and persist it as an ``ooc``
    model turn. Returns ``(ooc_model_turn, job_id)``. Assumes the caller has
    already appended the user's OOC turn (so it appears at the tail of
    ``ooc_history``). Never raises — a failure becomes an inline-error OOC turn."""
    conversation = store.get_conversation(conversation_id)
    transcript = store.get_transcript(conversation_id)
    if conversation is None or transcript is None:
        raise generator.GenerationError(f"conversation not found: {conversation_id}")

    job_id: str | None = None
    context_vars: dict | None = None
    raw = ""
    try:
        character = get_character(conversation["counterpart_character_id"])
        if character is None:
            raise generator.GenerationError(
                f"counterpart character not found: {conversation['counterpart_character_id']}"
            )
        resolved = generator._resolve_llm(None)
        context_vars = generator.build_context(conversation, character, transcript)
        context_vars = {
            **context_vars,
            "ooc_history": generator.render_ooc_history(transcript.get("turns") or []),
        }
        # Strip internal underscore carriers (lists/dicts) before {{var.*}} substitution.
        prompt = get_text(
            "prattletale", "ooc.reply",
            variables=generator.renderable_vars(context_vars),
        )
        request = ChainJobRequest(
            title="Prattletale OOC reply",
            input=context_vars.get("ooc_history", ""),
            llm=resolved,
            steps=[generator._llm_step(1, "ooc", "OOC", prompt, thinking=False)],
        )
        status = create_job(JOB_TYPE_OOC, request.model_dump(), request.input)
        job_id = status["job_id"]
        job_dir = find_job_dir(job_id)
        if job_dir is None:  # pragma: no cover — create_job just made it
            raise generator.GenerationError("job directory disappeared after creation")

        await execute_chain_job(job_id, job_dir, request)
        raw = generator._read_final_output(job_dir).strip()
        if not raw:
            raise generator.GenerationError("OOC model produced no output")

        turn = store.append_ooc_turn(conversation_id, Author.model, raw, job_id=job_id)
        if turn is None:  # pragma: no cover — conversation checked above
            raise generator.GenerationError("transcript disappeared while persisting OOC turn")

        store.write_trace(conversation_id, turn["id"], {
            "job_id": job_id,
            "context_input": context_vars,
            "raw_final_output": raw,
            "parsed_items": [{"type": ItemType.ooc.value, "text": raw}],
            "steps": generator._collect_steps(job_dir, request),
            "error": None,
        })
        return turn, job_id
    except Exception as exc:  # noqa: BLE001 — any failure becomes an inline-error OOC turn
        error_turn = store.append_ooc_turn(
            conversation_id, Author.model, f"(OOC generation failed: {exc})", job_id=job_id
        )
        if error_turn is not None:
            store.write_trace(conversation_id, error_turn["id"], {
                "job_id": job_id,
                "context_input": context_vars,
                "raw_final_output": raw,
                "parsed_items": [],
                "error": str(exc),
            })
        return error_turn or {}, job_id or ""
