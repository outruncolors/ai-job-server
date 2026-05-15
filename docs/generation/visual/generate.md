# Generate

The Generate tab submits a prompt against a ComfyUI workflow and shows the resulting images.

## What's on the page

- **Workflow** — dropdown populated from `GET /v1/comfyui/workflows`. Only workflows tagged "Ready" appear; invalid ones are listed but disabled.
- **Prompt** — the text injected into the workflow's `PROMPT` node.
- **Save / Load saved prompt** — small toolbar above the textarea. **Save** asks for a name and POSTs the current textarea + workflow selection to `/v1/image-prompts`. The **Load** dropdown lists previously saved prompts (with the workflow shown in parentheses); selecting one fills the textarea and, if the saved workflow still exists, also reselects it. See [Saved Image Prompts](prompts.md) for the full library and CRUD UI.
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
4. Export via Workflow → Export (API) and drop the JSON into `config/comfyui-workflows/`.

The Workflows view in the [Server → ComfyUI](../../management/server/comfyui.md) tab validates each file and reports the PROMPT node ID. See [ComfyUI Setup](comfyui-setup.md) for installation, model paths, and launch flags.
