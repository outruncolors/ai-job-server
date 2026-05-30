# Generate

The Generate tab submits a prompt against a ComfyUI workflow and shows the resulting images.

## What's on the page

- **Workflow** — dropdown populated from `GET /v1/comfyui/workflows`. Only workflows tagged "Ready" appear; invalid ones are listed but disabled.
- **Prompt** — the text injected into the workflow's `PROMPT` node.
- **Save / Load saved prompt** — small toolbar above the textarea. **Save** asks for a name and POSTs the current textarea + workflow selection to `/v1/image-prompts`. The **Load** dropdown lists previously saved prompts (with the workflow shown in parentheses); selecting one fills the textarea and, if the saved workflow still exists, also reselects it. See [Saved Image Prompts](prompts.md) for the full library and CRUD UI.
- **Reference images** — file/paste pickers for each `REF_IMAGE_*` `LoadImage` node the workflow exposes. Optional; leaving one blank keeps the workflow default.
- **Denoise** — *(only shown when the workflow has a `DENOISE` node)* a float 0.00–1.00 (image-to-image strength). Blank leaves the workflow default.
- **Seed** — *(only shown when the workflow has a `SEED` node)* either a whole number or the **randomize** checkbox. Randomize is **on by default**; with it checked the server draws a fresh seed in `0 … 2^63-1` (ComfyUI's `PrimitiveInt` is a signed 64-bit int — larger values are rejected by `/prompt`, so both randomized and pasted seeds are capped at `2^63-1`). After the job finishes the **seed actually used** is shown beneath the field — click it to drop it back into the input (randomize auto-unchecks) so the result can be reproduced. Seeds travel as digit strings end-to-end to keep full 64-bit precision.
- **Generate** — submits the job.

## How it works

1. The page posts to `POST /v1/jobs/image` with the workflow name and prompt.
2. `execute_image_job()` loads `config/comfyui-workflows/<name>.json`, copies it, and replaces the `inputs.text` of the node titled `PROMPT` with the user's prompt. The resolved workflow is saved to `workflow.json` inside the job folder for audit.
3. The workflow is submitted to ComfyUI's `/prompt` endpoint. The runner polls `/history/<prompt_id>` every second (up to 10 minutes) until ComfyUI reports completion.
4. Each output image is fetched via `/view`, written into the job folder, and recorded in `artifacts.json`.

The page polls `/v1/jobs/<id>` until status is `done`, then loads images from `/v1/jobs/<id>/files/artifacts.json` and renders them in the output panel.

## Recreate

If you arrive at the Image page from the Jobs page via **Recreate**, the workflow and prompt are pre-filled from the original job's `request.json`. If that workflow no longer exists, a notice bar appears and the dropdown stays empty.

## Authoring workflows

Workflows are API-format JSON files. To author one:

1. Build the graph in the ComfyUI editor (`http://hostname:8188`).
2. Enable Settings → Dev Mode.
3. Title one node `PROMPT` and give it a `text` input — this is where the user's prompt will be injected.
4. *(optional)* Title `LoadImage` nodes `REF_IMAGE_1` / `REF_IMAGE_2` to expose reference-image uploads.
5. *(optional)* Title a `PrimitiveInt` node `SEED` and/or a `PrimitiveFloat` node `DENOISE` (each with a `value` input) to expose the seed and denoise controls. Each field is exposed only when its titled node is present and unambiguous (exactly one match).
6. Export via Workflow → Export (API) and drop the JSON into `config/comfyui-workflows/`.

The Workflows view in the [Server → ComfyUI](../../management/server/comfyui.md) tab validates each file and reports the PROMPT node ID. See [ComfyUI Setup](comfyui-setup.md) for installation, model paths, and launch flags.
