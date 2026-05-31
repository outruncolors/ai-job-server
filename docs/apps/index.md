# Apps

Consumer experiences built on the job-server stack, walled off from the
"systems" navbar behind their own `/apps` landing. Apps reuse the shared backend
(chain engine, LLM client, MCP tools, store patterns) but keep game-specific
logic in their own package (`app/apps/<name>/`, `static/apps/<name>/`).

- **[Blaboratory](blaboratory/index.md)** — a virtual lab of AI residents. The
  MVP is the resident-creation loop: a 16-room grid where empty rooms can be
  filled with LLM-generated characters.
- **[Hoodat](hoodat/index.md)** — create and manage characters from a versioned
  template: generate from a prompt, regenerate any field, a Discord-style profile
  page, avatar generation/upload, and Targeted Exports.
- **[Prattletale](prattletale/index.md)** — an iMessage-style roleplay chat with a
  Hoodat character: typed bubble stacks (dialogue/action/narration), a
  self-contained conversation folder per chat, and a turn-generation pipeline. In
  planning; Phase 1 (text-first) is sequenced into self-contained build sessions.

Both Blaboratory and Hoodat dogfood the cross-app [Prompt Pal](../tools/prompt-pal.md) registry and
the FieldControls hover affordance. The single bridge from the systems UI is one
`Apps` entry in `static/js/nav.js`; apps pages do not carry the systems nav.
