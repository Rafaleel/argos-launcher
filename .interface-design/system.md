# Argos Launcher — Interface Design System

Visual and structural reference for Argos Launcher UI screens. Preserves the warm editorial / print-shop aesthetic established by **Acervo** (`Library.tsx`) across dark and light themes.

## Direction & Feel

- **World:** Physical game archive, print-shop catalog, and emulator workbench.
- **Voice:** Calm, legible, structured — Portuguese (pt-BR) user-facing copy, zero emojis (strictly `lucide-react` SVG icons).
- **Focal rule:** Every page or tab opens with **one focal anchor panel** (`border-top: 3px solid var(--poster)`) that states the primary status/metric and primary action, followed by organized workspace columns or grouped cards below. Never stack raw unframed lists or walls of controls.

## Color Roles (Dark & Light Themes)

Tokens live in `frontend/src/style.css` (`:root` for dark, `:root[data-theme="light"]` for light).

| Role | Dark | Light | Usage |
|---|---|---|---|
| Canvas (`--paper`) | `#111110` | `#f7f1e4` | Page background |
| Primary surface (`--surface`) | `#1d1c1b` | `#fff9ed` | Panels and cards |
| Inset control/row (`--field`) | `#191816` | `#fffdf5` | Inputs, nested groups, timeline rows, folder rows |
| Raised/hover (`--raised`) | `#2e2a26` | `#eee4d4` | Secondary buttons, active segmented pills, row hover |
| Primary accent — Red (`--red`, `--poster`) | `#ff624b` / `#cb392e` | `#b72b1c` / `#b83226` | Section kickers + `.signal` stripes, `3px` hero top rules, active nav/tab underlines, total playtime figure, story progress, next-step markers, warning/missing states |
| Detail accent — Gold/Yellow (`--yellow`, `--gold-ink`, `--gold-fill`) | `#ffda65` / `#ffdc78` / `#ffdc78` | `#ffcf4a` / `#795600` / `#b57900` | Primary CTA buttons (`.btn.primary` with dark `#241b12` text), `<Eye gold />` ring, achievement & ranking meters, earned badges, "ready / connected" pills |
| Status pills (`--gold-pill-*`, `--red-pill-*`) | `#2f2818` / `#351d1a` | `#f4d888` / `#fae1d8` | Compact state badges; in light mode gold pill text uses `#49351b` for >7:1 contrast |

## Depth, Radius & Spacing

- **Depth strategy:** Borders-first (`1px solid var(--rule)`, `2px solid var(--outline)` on standard panels, `3px solid var(--poster)` on focal hero panels) combined with whisper-quiet surface shifts (`--paper` → `--surface` → `--raised`, `--field` for inset zones). No heavy drop shadows except floating dropdowns/toasts.
- **Border radius:** `4px` on buttons, inputs, pills, panels, and cards; `2px` on mini covers; `50%` on circular nodes/dots.
- **Spacing grid:** 4px base (`8px` micro, `12–16px` inside cards/groups, `20px` between workspace bands, `24px` below section mastheads).

## Typography

- **Display:** `Bricolage Grotesque Variable` (`--display`) — bold/extrabold (`700–800`), tight tracking (`-0.03em` to `-0.055em`), `line-height: 1.08–1.2`.
- **Body:** `IBM Plex Sans` (`--text`) — `15px` base, `13–14px` supporting copy, `12px` captions.
- **Technical / Eyebrows:** `ui-monospace` (`--mono`) — `11px` uppercase tracked (`0.09em`) for `.eyebrow` and `.kicker`; `12px` for paths, IDs, and rank indices.
- **Tabular numbers:** Always apply `.num` (`font-variant-numeric: tabular-nums`) to durations, counts, percentages, points, and dates.

## CSS Namespace Architecture

Keep **Acervo** (`.spotlight`, `.collection`, `.sleeve`, `.catalog-list`) and **Ficha header** (`.dossier`, `.tabs`, `.disc-picker`) untouched. Scope new UI work into dedicated namespaces:

- `.mast-*`: Section masthead for Atividade & Oficina (`App.tsx`).
- `.act-*`: Atividade pages (`Stats.tsx`, `Journal.tsx`, `Achievements.tsx`).
- `.ofc-*`: Oficina pages (`Emulators.tsx`, `Settings.tsx`, `Accounts.tsx`) and shared `.ofc-pill` / `.ofc-footnote` primitives.
- `.gm-*`: Ficha do Jogo tab panels (`GameSummary.tsx`, `GameAchievements.tsx`, `GameAchievementList.tsx`, `GameMilestones.tsx`, `GameDolphin.tsx`).

## Key Component Patterns

- **Hero Anchor Panel:** `.panel` with `border-top: 3px solid var(--poster)`, `.kicker` + `.signal`, primary heading/figure, status pills, and primary CTA on the right.
- **Segmented Control:** `.seg` (`role="group"`) with `<button type="button" aria-pressed={...}>`. Reserve `role="tablist"` strictly for complete tablist/tabpanel widgets (like `GamePage`'s `.tabs`).
- **Grouped Forms:** Wrap related form fields in `.ofc-field-group` (`--field` inset surface with `.eyebrow` header) and hide rarely changed options in `<details className="ofc-disclosure">` or controlled drawers.
- **Dirty-State Action:** Pair `"Alterações não salvas"` warning pill + primary save button when dirty, and `"Salvo"` with `<Check />` when clean (inside `.ofc-sub-bar` in Oficina or `.gm-panel-head` in Ficha do Jogo).
- **Path Truncation:** Always pair `display: grid; grid-template-columns: minmax(0, 1fr)` on containers with `min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap` on `<code>` paths.
