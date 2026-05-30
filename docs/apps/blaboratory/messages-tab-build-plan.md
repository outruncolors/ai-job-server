# Blaboratory — Messages tab build plan

Status: **built.** Discord-style chat-feed view + deep-linkable messages +
tabbed resident modal.

## Overview

The Messages tab renders the shared computer-channel `chat` feed (the messages
residents post via `use_computer`) as a Discord-style speech-bubble timeline —
avatar + name + timestamp per author run — alongside Rooms and Config. It is
architected for **deep-linking to a single message**: a resident's event-log
entry for a chat post is clickable and jumps to that exact message in the feed
(`?tab=messages&message_id=<id>`), scrolling it into view and flash-highlighting
it.

## Design decisions

- **Routing**: tabs stay hash-routed (`#rooms`/`#messages`/`#config`); the
  deep-link layers query params — `?tab=` and `?message_id=` are honored on load
  (query wins over hash) and reflected via `history.replaceState` on in-app
  clicks (no reload).
- **Playhead scope**: the feed respects the timeline playhead (`until_tick=`),
  consistent with the Rooms grid and event log. A deep-link jumps the playhead to
  latest so the target is always in scope.
- **Bubble style**: Discord-style — all messages left-aligned, grouped by
  consecutive author, avatar (initials, color hashed from resident id; a clear
  seam left to swap in real avatar `<img>` later) + name + time once per run.

## What landed

### Backend
- `chat_store.py`: playhead-scoped, oldest-first feed paging helpers
  `chat_latest` / `chat_before` / `chat_newer` / `get_chat` (shared `_scope`
  appends `tick <= until_tick`). Left the cursor-driven `chat_after`/`chat_upto`
  untouched.
- `router.py`: `GET /v1/apps/blaboratory/chat` with `until_tick`/`before`/`after`/
  `around`/`limit` (clamped ≤200), author-name enrichment from
  `residents_store.list_residents()`, and `has_more_before`/`has_more_after`/
  `target_id` in the response.
- `context_pipeline.write_phase`: injects the new chat row's id into the event
  payload (`payload.chat_id`) so the event log can deep-link. Backward compatible.

### Frontend (`static/apps/blaboratory/`)
- `index.html`: Messages tab button + `#tab-messages` pane (`#msg-scroll` /
  `#msg-list` / `#msg-jump` pill); resident detail dialog restructured into a
  sub-tab strip (Profile / Event log / Context) with three panes.
- `blaboratory.js`: messages module — `loadMessages` (initial/playhead-changed),
  `loadOlder` (infinite scroll up, scroll-preserving), `loadNewer` (after a
  deep-link), `pollMessages` (live append while following, "↓ new messages" pill
  when scrolled up), `scrollToMessage`/`goToMessage` (deep-link), Discord grouping
  + avatar/time helpers. Resident modal: `switchModalTab`, reformatted
  `renderEventLog` (action icon + verb + summary + tick/time; chat-post rows are
  clickable `a.ev-quote` links into Messages).
- `styles.css`: bubble/avatar/group styles, `msgflash` highlight keyframes, jump
  pill, modal sub-tabs, reformatted event-log rows; mobile tweaks at ≤560px.

### Tests
- `test_db_stores.py`: `chat_*` paging ordering + `until_tick` scoping.
- `test_router_part2.py`: `GET /chat` author enrichment, `around` target echo,
  `until_tick` truncation.
- `test_context_pipeline.py`: `write_phase` stores `payload.chat_id`.

## Deferred
- Real resident avatar images (the avatar is an initials circle for now; the
  render seam is isolated in `renderMsgList`).
