# UI Standards — AI Job Server

## Design Philosophy

Dark monospace terminal aesthetic. Sparse, functional, information-dense. Every pixel earns its place. No decorative elements. Color is used only for semantic meaning (status, accent, danger) — never for decoration.

---

## Responsive System

### Breakpoints

| Name    | Width     | Target                        |
|---------|-----------|-------------------------------|
| Mobile  | ≤ 768px   | Phones, small tablets         |
| Desktop | > 768px   | Laptops, external displays    |

**Priority target:** iPhone 14 Pro Max — 430px CSS width, 932px CSS height.

### Viewport Meta

Every page must include:
```html
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
```

`viewport-fit=cover` is required so content extends into the Dynamic Island safe area. Use `env(safe-area-inset-*)` to push interactive content away from the notch.

### Shared Files

Two files handle all responsive behavior and must be loaded in every HTML page:

```html
<!-- After the page's inline <style> block, so it wins on source-order ties -->
<link rel="stylesheet" href="/css/responsive.css">

<!-- Before </body> -->
<script src="/js/nav-mobile.js"></script>
```

`responsive.css` also defines all CSS custom properties (design tokens). `nav-mobile.js` injects the hamburger button and dropdown menu.

---

## Layout Patterns

### Desktop (> 768px): Two-Column Flex

```
┌──────────────────────────────────────────────┐
│  #topnav (44px fixed)                        │
├────────────────────┬─────────────────────────┤
│  #panel-left       │  #panel-right            │
│  (controls/list)   │  (output/detail)         │
│                    │                          │
│  overflow-y: auto  │  overflow-y: auto        │
└────────────────────┴─────────────────────────┘
```

- `#panels`: `display: flex; height: 100vh; padding-top: 44px;`
- `#panel-left`: either `flex: 1` (chain, voice, image) or fixed width (context: 340px, jobs: 480px)
- `#panel-right`: `flex: 1`
- `html, body`: `overflow: hidden` (panels scroll internally)

### Mobile (≤ 768px): Single-Column Stack

```
┌─────────────────────┐
│  #topnav (44px)     │
│  [AI Jobs]  [☰]     │
├─────────────────────┤
│  #panel-left        │
│  (full width)       │
├─────────────────────┤
│  #panel-right       │
│  (full width)       │
└─────────────────────┘
       ↕ page scrolls
```

`responsive.css` applies these overrides at `max-width: 768px`:

- `html, body`: `overflow: auto` (page scrolls, not panels)
- `#panels`: `flex-direction: column; height: auto`
- `#panel-left`: `width: 100%; border-right: none; border-bottom: 1px solid #1a1a1a`

**Exception:** The home page carousel uses `overflow: hidden` on `<body class="page-home">` and is excluded from the overflow override. Its slides already support touch swipe.

---

## Navigation

### Desktop

Horizontal link bar, 44px tall, fixed at top:
```
AI Jobs   Chain   Context   Voice   Image   Jobs   [page-specific btn]
```

- `.nav-home`: accent green `#2a6`, bold
- Inactive links: `#444`, hover `#888`
- Active link: `#ccc` (set via JS: `element.classList.add('active')`)

### Mobile

`nav-mobile.js` automatically:
1. Clones all nav links (and page-specific buttons) into a `div.nav-links-mobile` dropdown
2. Appends a `<button class="nav-hamburger">☰</button>` to `#topnav`
3. Wires the hamburger to toggle `.open` on the dropdown

On mobile, `responsive.css` hides `#topnav > a:not(.nav-home)` and `#topnav > button:not(.nav-hamburger)`. Only the home link and hamburger remain visible in the bar.

The dropdown closes on any item tap or outside click.

---

## Color Palette

All values available as CSS custom properties in `responsive.css`:

| Token                 | Value     | Usage                                    |
|-----------------------|-----------|------------------------------------------|
| `--color-bg`          | `#111`    | Page background                          |
| `--color-bg-panel`    | `#141414` | Hover states, slight elevation           |
| `--color-bg-raised`   | `#1a1a1a` | Cards, mobile nav dropdown               |
| `--color-bg-input`    | `#181818` | Input, textarea, select backgrounds      |
| `--color-border`      | `#1a1a1a` | Subtle dividers                          |
| `--color-border-mid`  | `#2e2e2e` | Input borders, card borders              |
| `--color-border-hi`   | `#383838` | Focused/elevated borders                 |
| `--color-text`        | `#ccc`    | Primary text                             |
| `--color-text-sub`    | `#aaa`    | Secondary text                           |
| `--color-text-muted`  | `#666`    | Muted / placeholder text                 |
| `--color-text-dim`    | `#444`    | Very dim text, inactive nav links        |
| `--color-accent`      | `#2a6`    | Primary accent: nav home, buttons, done  |
| `--color-accent-hover`| `#3b7`    | Primary button hover                     |
| `--color-warn`        | `#fa0`    | Running / in-progress states             |
| `--color-danger`      | `#e44`    | Errors, failed status                    |
| `--color-danger-bg`   | `#7a2222` | Danger button background                 |

### Status Colors

| Status    | Class            | Color  |
|-----------|------------------|--------|
| queued    | `.status-queued` | `#777` |
| running   | `.status-running`| `#fa0` |
| done      | `.status-done`   | `#2a6` |
| failed    | `.status-failed` | `#e44` |
| error     | `.status-error`  | `#e44` |

---

## Typography

Font family: `monospace` throughout — no exceptions.

| Role             | Size      | Color   | Notes                               |
|------------------|-----------|---------|-------------------------------------|
| Section labels   | `0.66rem` | `#383838`| All-caps, `letter-spacing: 0.12em` |
| Nav links        | `0.72rem` | `#444`  |                                     |
| Table headers    | `0.74rem` | `#484848`|                                    |
| Table cells      | `0.74rem` | `#ccc`  |                                     |
| Form labels      | `0.76rem` | `#777`  |                                     |
| Inputs / buttons | `0.82rem` | `#ccc`  |                                     |
| Body text        | `0.82rem` | `#ccc`  |                                     |
| Slide labels     | `3rem`    | `#2a6`  | Home page only                      |
| Slide desc       | `1.25rem` | `#666`  | Home page only                      |

---

## Components

### Buttons

Three variants, consistent padding `7px 18px`:

| Variant   | Class       | Background | Hover      |
|-----------|-------------|------------|------------|
| Primary   | (default)   | `#2a6`     | `#3b7`     |
| Secondary | `.secondary`| `#333`     | `#424242`  |
| Danger    | `.danger`   | `#7a2222`  | `#992828`  |
| Disabled  | `[disabled]`| `#2a2a2a`  | (no hover), `opacity: 0.38` |

**Touch target rule:** Primary action buttons must be at least 36px tall (Apple HIG recommends 44px). The current `7px 18px` padding + default `line-height` meets this for `0.82rem` text. Do not reduce button padding below `6px 12px`.

### Inputs

```css
width: 100%; padding: 6px 8px;
background: #181818; border: 1px solid #2e2e2e;
color: #ccc; font-family: monospace; font-size: 0.82rem; border-radius: 3px;
```

Focus: `border-color: #4a4a4a; outline: none;`

Checkboxes use `accent-color: #2a6`. Range inputs use `accent-color: #2a6`.

### Textareas

- `resize: vertical` — always
- `min-height: 54px` baseline; increase for primary input areas (120–220px)

### Form Labels

```css
display: block; color: #777; font-size: 0.76rem;
margin-bottom: 3px; margin-top: 10px;
```

### Details / Summary (collapsible sections)

```css
summary::before { content: '▸ '; }
details[open] summary::before { content: '▾ '; }
```

Suppress the default disclosure triangle: `list-style: none` + `::-webkit-details-marker { display: none }`.

### `.row` (two-column field groups)

```css
.row { display: flex; gap: 10px; }
.row > * { flex: 1; min-width: 0; }
```

On mobile, add `.dims-row` to any `.row` that contains number inputs and should stack vertically. The responsive CSS flips `.dims-row` to `flex-direction: column`.

---

## Drawers

Right-side slide-in panel used for secondary content (sequences, settings):

```css
.drawer {
  position: fixed; top: 0; right: 0; height: 100vh;
  width: min(500px, 96vw);   /* responsive width already */
  transform: translateX(100%);
  transition: transform 0.36s cubic-bezier(0.4, 0, 0.2, 1);
  z-index: 200;
}
.drawer.open { transform: translateX(0); }
```

On mobile (`≤ 768px`), responsive.css overrides to `width: 100vw` so the drawer takes the full screen width. Always pair with `#drawer-overlay` (backdrop, `z-index: 150`).

---

## Z-Index Stack

| Layer               | Value | Element                         |
|---------------------|-------|---------------------------------|
| Nav bar             | 100   | `#topnav`                       |
| Mobile nav dropdown | 110   | `.nav-links-mobile`             |
| Drawer overlay      | 150   | `#drawer-overlay`               |
| Drawers             | 200   | `.drawer`                       |

---

## Safe Areas (iPhone notch / Dynamic Island)

Use `env()` values when placing interactive content near screen edges:

```css
/* Horizontal insets for Dynamic Island on iPhone 14 Pro Max */
padding-left:  max(16px, env(safe-area-inset-left));
padding-right: max(16px, env(safe-area-inset-right));

/* Bottom inset for home indicator */
padding-bottom: env(safe-area-inset-bottom);
```

The nav bar applies horizontal safe-area insets automatically via `responsive.css`. The home page carousel is `position: fixed` and inherits these constraints from the viewport.

---

## Adding a New Page

1. Copy the nav HTML from any existing page.
2. Use `#panels`, `#panel-left`, `#panel-right` for the two-column layout — the responsive system handles stacking automatically.
3. Add after your `</style>`:
   ```html
   <link rel="stylesheet" href="/css/responsive.css">
   ```
4. Add before `</body>`:
   ```html
   <script src="/js/nav-mobile.js"></script>
   ```
5. Add `viewport-fit=cover` to the viewport meta tag.
6. Set the active nav link in JS: `document.querySelector('#topnav [data-page="your-page"]').classList.add('active');`
