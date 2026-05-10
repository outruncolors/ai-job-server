from __future__ import annotations


def render_template(
    template: str,
    *,
    input: str,
    previous: str,
    context: str,
    step_index: int,
    step_name: str,
) -> str:
    return (
        template
        .replace("{{input}}", input)
        .replace("{{previous}}", previous)
        .replace("{{context}}", context)
        .replace("{{step_index}}", str(step_index))
        .replace("{{step_name}}", step_name)
    )
