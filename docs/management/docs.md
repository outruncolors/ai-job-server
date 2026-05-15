# Docs

The page you're reading now.

The viewer renders Markdown files from the `docs/` directory on the server. Its structure mirrors the navbar so a doc's location matches where its subject lives in the site.

## How it works

- `GET /v1/docs` walks `docs/` recursively and returns a tree. Each directory becomes a collapsible group; each `.md` file becomes a leaf. Titles come from the file's first `# H1` heading (falling back to a title-cased filename); directory titles come from the folder name.
- `GET /v1/docs/{path:path}` returns a file as plain text. The resolved path is checked with `Path.is_relative_to(DOCS_DIR)` to reject `..` traversal.
- The frontend renders Markdown with `marked.js`, rewrites internal `.md` links to in-app hash navigation, and persists the active doc in the URL hash (`#generation/text/chain.md`). Refreshing on a deep link expands its ancestors and reloads the same doc.

## Adding a doc

1. Drop a Markdown file under `docs/` in the directory that matches where it belongs in the navbar (or under `docs/reference/` for cross-cutting engineering material).
2. Start with a single `# Heading` line — it becomes the title in the tree.
3. Link to siblings with relative paths: `[Sequences](sequences.md)` from inside `generation/text/`. The viewer rewrites these into hash links automatically, so they work both in the rendered viewer and when reading the raw file in an editor.

No restart needed — the next page load picks up new files.
