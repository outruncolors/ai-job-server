# Visual

The Visual page (`/image`) generates images through **ComfyUI**, which runs as a long-lived HTTP server at `127.0.0.1:8188`. The Image page submits prompts; ComfyUI executes the workflow graph and produces image artifacts.

The page hosts:

- **[Generate](generate.md)** — pick a workflow, type a prompt, run a job
- **[Prompts](prompts.md)** — manage the library of saved prompts (name, prompt, workflow)

ComfyUI is also exposed through the **[Server → ComfyUI](../../management/server/comfyui.md)** tab for lifecycle controls (start / stop / restart) and through a Workflows / Config view for inspection. If you're setting this up for the first time, start with **[ComfyUI Setup](comfyui-setup.md)**.
