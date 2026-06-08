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
  self-contained conversation folder per chat, a synchronous turn-generation
  pipeline, and optional per-item voice + reveal timing. An in-chat config view,
  per-message edit/hide/delete, and a dev-tools trace viewer + pipeline node-graph.
  A hook-based plugin system (per-conversation enable + generic action dispatch +
  a `window.PtPlugins` frontend API) ships with **Summarizer**: a 📋 Summarize mode
  that map-reduces the history into one summary bubble (Keep or Purge).
- **[Tomeberry](tomeberry/index.md)** — a Cursor-like two-pane studio for tales of
  any length. A left pane swaps between a rich contenteditable **Content** editor
  (inline accept/reject proposal spans) and an **Organization** view (premise,
  structural tree, narrative constructs, story entities, relationships); a
  persistent right **Assistant** pane drives 10 co-author modes
  (Discover/Draft/Develop · Organize/Revise/Plan · Edit/Diagnose/Track · Publish)
  over the chain executor. Tale-scoped project folders, a propose→accept/reject/
  iterate diff loop on `app/textdiff`, a full per-request debug panel, starter
  templates, and tale export. Reads/writes workspace files through the standardized
  [MCP](../tools/mcp.md) gateway.

Blaboratory and Hoodat dogfood the cross-app [Prompt Pal](../tools/prompt-pal.md) registry and
the FieldControls hover affordance. The single bridge from the systems UI is one
`Apps` entry in `static/js/nav.js`; apps pages do not carry the systems nav.
