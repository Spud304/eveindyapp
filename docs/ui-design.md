# UI design brief

Frontend style for the redesign. It copies the style of my AT Tool project. Adapted from that project's brief; AT-specific details (team name, ban tokens, fit wording) are replaced with this app's equivalents.

## Character
- Desktop-first working tool, not a marketing site. Dense, fast, quiet.
- Looks like a cleaned-up spreadsheet or admin console: flat panels, thin borders, small text, no imagery, no illustrations, no gradients, almost no shadows (only toasts and menus).
- **Light theme by default**; dark theme uses the same tokens. A header button toggles it and the choice is stored in localStorage.
- Numbers are monospace with tabular figures and right-aligned in tables.
- **Every derived value shows its reason** (e.g. "ME 10 from corp BPO", "buying: rule T2 components", a red badge that names the broken rule). The planning engine's output must carry these reasons; see `docs/redesign.md`.

## Stack
- React + TypeScript + Vite, Tailwind CSS v4 (tokens in `@theme`), `clsx`. No component library (shadcn etc. deliberately not used).
- TanStack Router + TanStack Query. Mutations show a toast through `meta: { toast: 'Plan saved' }`.
- Fonts: Inter (sans), JetBrains Mono (mono).

## Structure
- `src/index.css`: all colour and font-size tokens. The only place they are defined.
- `src/components/ui/index.tsx`: the only place visual styling lives. Pages compose primitives; a restyle edits this one file.
- `src/features/<area>/`: one folder per feature (page components plus a `format.ts` of display helpers). Areas: `plans`, `library`, `dashboard`, `setup`.
- `src/hooks/`: small generic hooks (sort, debounce, copy, page title, "/" focuses search).
- Every interactive element gets a `data-testid` like `plans.search` or `plans.row.<id>` (for Playwright).

## Tokens (semantic names; never raw hex in components)

| token | dark | light (Google Sheets palette) |
|---|---|---|
| bg | #0f1216 | #f8f9fa |
| panel | #171b21 | #ffffff |
| panel-2 (hover, sub-headers, default buttons) | #1f242c | #f1f3f4 |
| line (all borders) | #2a3139 | #c0c4c8 |
| fg | #e7eaee | #202124 |
| muted (labels, secondary text) | #8f9aa8 | #5f6368 |
| accent (links, primary, focus) | #6ea8fe | #1a73e8 |
| accent-fg | #0b1220 | #ffffff |
| ok / warn / bad / info | #4fc38a / #e8b647 / #ef6b6b / #62c4d9 | #188038 / #e37400 / #d93025 / #007b83 |

- Mechanism: `:root` holds dark values, `[data-theme="light"]` overrides them, and `@theme` maps `--color-x: var(--x)` so Tailwind classes like `bg-panel`, `border-line`, `text-muted`, `bg-bad/15` work.
- **Default theme must be light.** Because `:root` holds the dark values, copying the CSS alone opens in dark. Port the `readTheme()` logic too: read localStorage, fall back to `light`, set `data-theme` on `<html>` before first paint.
- Status tints use 15% alpha backgrounds with full-strength text (`bg-ok/15 text-ok`).
- Domain-specific fills get their own tokens (e.g. job states: planned / running / ready / delivered).

## Type and spacing
- **Font sizes are tokens** (the AT Tool used inline `text-[11px]`/`text-[12px]`; don't copy that). Define in `@theme`:
  - `--text-label` 11px: labels, table headers, badges
  - `--text-ui` 12px: working surfaces
  - `--text-body` 13px: body, line-height 1.4
  - page title 14px semibold. Nothing larger than 16px.
- Section and table headers: label size, semibold, UPPERCASE, `tracking-wide`, muted colour.
- Controls are 28px tall (`h-7`), compact buttons 24px (`h-6`). Radius is the small Tailwind `rounded` everywhere.
- Spacing: `p-3` inside panels, `gap-4` between panels, `p-4` around the main area, table cells `px-2 py-1`.

## Layout
- App shell: 40px header (app name, horizontal text nav with active item as `bg-panel-2`, theme toggle, character + role badge, logout on the right), scrolling `main` with `p-4`, 24px footer with version in label-size muted text.
- Nav items are hidden when the user lacks the capability, not disabled (e.g. a plan viewer doesn't see edit actions).
- Each page: a `PageHeader` row (title, monospace count, muted context, actions pushed right with `ml-auto`, bottom border).
- Body: a CSS grid, main content + side panel, e.g. `grid gap-4 xl:grid-cols-[2fr_1fr]` or `[1fr_380px]`; it stacks below xl/lg.
- Complex screens use a named-area CSS grid with fixed side columns (e.g. 230 / 210 / fluid / 290); they scroll sideways below ~1180px rather than reflow.

## Primitives (build these first, keep them small)
- **Panel**: bordered `bg-panel` box, optional header strip (uppercase muted title left, actions right, bottom border), `p-3` body.
- **Button**: variants `default` (panel-2 + border, hover border goes muted), `primary` (accent fill, hover `brightness-110`), `danger` (bad/15 tint, red text), `ghost` (no border, muted until hover). Disabled = 50% opacity + not-allowed cursor.
- **Input / Select / Textarea**: `bg-bg`, line border, border turns accent on focus, no outline; `invalid` turns the border warn. Textareas are monospace (used for pasted data). Number inputs hide spinner arrows.
- **Badge**: label-size uppercase tinted pill; tones muted/ok/warn/bad/info/accent. Used for status, flags, roles.
- **Table**: semantic `<table>` in an `overflow-x-auto` wrapper; rows separated by top borders only; uppercase muted label-size headers; optional `hover` row tint. Collapsible group rows use ▸/▾ and a count.
- **Field**: muted label stacked above its control.
- **Empty**: centred muted message + one hint line + the action that fixes it (e.g. "Clear filters"), shown only if the viewer may act.
- **ErrorText**: red inline text. **Mono**: span with the mono class.
- **Toasts**: bottom-right, at most 3, 4 s, click to dismiss, one line each, tone shown by border colour.
- **Context menu**: right-click and a hover "⋯" button open the same menu; Esc / outside click / scroll close it.

## Interaction rules
- Global `:focus-visible` = 2px accent outline. Keyboard where it matters: "/" focuses the page search, Enter/arrows move across grid-like inputs.
- Search inputs are debounced; filters sit in the PageHeader actions.
- Destructive actions use `window.confirm` with a sentence naming what is lost ("Delete plan dreadbatch 1? Its lines and job links go with it.").
- Notes and edits happen inline with autosave, never in modal popups.
- Native `<select>` only for short lists; long lists get a text filter (tall native popups paint blank in Chromium).
- Browser tab title is "Page · EVE Indy".
- UI text is plain, literal and short: lowercase placeholders ("search item"), sentence-case buttons, `title` tooltips that say what a control does.
