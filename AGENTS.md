# Argos Launcher: agent instructions

Local game library and launcher for Linux with a progress estimate per game.
Backend: Python 3.12 + FastAPI + SQLite (`backend/`). Frontend: React + TypeScript
(Vite) inside a Tauri 2 shell (`frontend/`). Design notes live in `PROJETO.md`
(local only, gitignored; read it if present).

## Run and check

- Backend: `cd backend && uv run uvicorn app.main:app --host 127.0.0.1 --port 8765`
- Frontend: `cd frontend && pnpm dev` (http://127.0.0.1:5173), or `pnpm tauri dev` for the desktop app
- Backend tests: `cd backend && uv run pytest`
- Frontend check: `cd frontend && pnpm build` (runs `tsc --noEmit` then `vite build`)

Run both checks before calling work done.

## Language

- Code, comments, commits, PR text and docs: English.
- User-facing UI text: Portuguese (pt-BR).

## Git

- Never commit to `main`. One branch per piece of work (`feat/...`, `fix/...`, `docs/...`, `chore/...`), English slugs. Follow-up requests on the same piece reuse the branch.
- Small local commits. Push, PR and merge only with the owner's explicit approval.

## Rules

- Everything runs locally; no mandatory cloud service. External APIs (RetroAchievements) are optional.
- The app never downloads or distributes ROMs/ISOs. `ISOs/` is gitignored; never commit game images, texture packs, `*.db`, `.env`, API keys or tokens.
- Secrets (RetroAchievements key, Dolphin token) are write-only: no route returns them, and error messages must never include them or the request URL.
- UI: no emojis anywhere (use SVG icons, lucide-react); style selects and spacing like the existing pages.
- Real emulator test launches go to the built-in display (screen 1) with sound muted.
- Build phases are ordered (see `PROJETO.md`, section 5); do not start a later phase before the previous one works. Keep the `signals` table and the `Collector` interface.
- Tests are required for the scanner (hash, matching) and the signal fusion (synthetic signals).
