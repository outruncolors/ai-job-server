# Apps

Consumer experiences built on the job-server stack, walled off from the
"systems" navbar behind their own `/apps` landing. Apps reuse the shared backend
(chain engine, LLM client, MCP tools, store patterns) but keep game-specific
logic in their own package (`app/apps/<name>/`, `static/apps/<name>/`).

- **[Blaboratory](blaboratory/index.md)** — a virtual lab of AI residents. The
  MVP is the resident-creation loop: a 16-room grid where empty rooms can be
  filled with LLM-generated characters.

The single bridge from the systems UI is one `Apps` entry in
`static/js/nav.js`; apps pages do not carry the systems nav.
