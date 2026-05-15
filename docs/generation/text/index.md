# Text

The Text page (`/chain`) runs **chain jobs**: ordered lists of steps where each LLM step feeds its output into the next. Voice and context steps can sit anywhere in the chain to produce audio or save outputs for later use.

The page has two tabs:

- **[Chain](chain.md)** — build and run an ad-hoc chain
- **[Sequences](sequences.md)** — save, edit, and reuse chains

Chains are submitted to `POST /v1/jobs/chain`. Each step's intermediate files (prompt, output, audio, tool calls) are written to `steps/NNN_<name>/` inside the job folder and exposed through the Jobs page.
