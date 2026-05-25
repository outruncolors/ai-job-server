"""Consumer apps built on the ai-job-server stack.

Apps are user-facing experiences (e.g. Blaboratory) that live behind the
separate `/apps` landing, walled off from the systems nav. They reuse the
shared backend (chain engine, LLM client, MCP tools, store patterns) but keep
game-specific logic in their own package.
"""
