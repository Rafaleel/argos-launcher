# Automatic Story Milestones Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (native, no subagents: owner's rule) to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Any RA-linked game gets story milestones built from its `progression`/`win_condition` achievements, with the "a game is being played" gate derived from its rich presence script, read live from Dolphin's RAM.

**Architecture:** `milestones.build` selects typed achievements (types come from the stored catalog `ra_achievements.kind`), groups them by the leading `[tag]` of the description, and keeps the existing flag extraction. A new `collectors/rich_presence.py` derives the in-game gate from the patch's rich presence script; the gate is stored in each row's `gates`. `STORIES` is deleted; a game that cannot be built fails closed ("not supported" + reason in `PROBLEMS`).

**Tech Stack:** Python 3.12, FastAPI, SQLite, pytest (`cd backend && uv run pytest -q`).

**Spec:** `docs/superpowers/specs/2026-11-22-auto-milestones-design.md`

## Global Constraints

- Work only in this worktree (`../argos-claude`, branch `feat/auto-milestones`); never check out branches in the main folder. A new worktree needs `cd backend && uv sync` first.
- Code, comments, commits, docs in English; UI-facing strings (`PROBLEMS` messages) in Portuguese (pt-BR). No emojis.
- Keep: `milestones.build/save/load/read`, `ra_flags.milestone_flag`, the `milestones` table and signal, the `/games/{id}/milestones` route, the existing top-level keys of that route (`supported`, `total`, `reached`, `items`, `read_at`, `problem`).
- Fail closed: if the gate, the types or the catalog are missing, store no rows and set `PROBLEMS[game_id]`; never store a signal from an ungated read.
- Secrets: `r=patch` keeps using the Dolphin login; no token or user name in fixtures, logs or errors.
- Commits: small, local, with the trailer `Claude-Session: https://claude.ai/code/session_01QDUSqQhc3zQBbsseP84bcT`. No push without the owner's OK.

## Review Focus

- Game linked but achievements never synced (empty catalog): "not supported" with a "sincronize" message, no crash.
- Rich presence missing, empty, or with no static branch: gate unknown, no rows stored.
- Title screen or demo (zeroed RAM) with a derived gate: `read` returns `None`, no signal stored.
- Between scenarios no group's gates hold (menu): `read` returns `None`.
- Rows built by the old version (no scenario, no in-game gate): ignored until rebuilt, never read without the gate.
- Patch achievement with a non-string `MemAddr` or an id missing from the catalog: skipped, no crash.

---

### Task 1: Capture the real RE2 patch as a fixture (needs the owner's OK)

**Files:**
- Create: `backend/tests/fixtures/re2_patch.json`, `backend/tests/fixtures/re2_leon_a_ids.json`

**Interfaces:**
- Produces: the real `r=patch` JSON for RA game 3176 and the achievement ids of the 12 rows the old hand-built `build()` stored for Leon A.

- [ ] **Step 1: Ask the owner's OK** to fetch the patch once with the Dolphin login the app already holds (this sends that token to retroachievements.org, exactly as a play session does). Do not continue without it.
- [ ] **Step 2: Fetch and save.** In a throwaway script under `$CLAUDE_JOB_DIR/tmp`, build `install` as `api.py:286` does, call `dolphin.ra_login(install)` then `retroachievements.fetch_patch(3176, *login)`, and write the JSON to the fixture path. Write `[row.ra_achievement_id for row in milestones]` from `~/.local/share/argos/argos.db` (read-only `SELECT ra_achievement_id FROM milestones WHERE game_id = <RE2 game id> ORDER BY position`) to the second fixture.
- [ ] **Step 3: Inspect the fixture** (never print the whole file): name of the rich presence key (expected `RichPresencePatch`), its line format (expected `Display:` section with `?cond?text` lines and `@Macro(...)` dynamic parts), the `Type` key per achievement. Note any difference from these expectations at the top of Task 2's work.
- [ ] **Step 4: Confirm no token or user name is in the fixture** (`grep -i` for the user name and for `token`). Commit: `test: add the real RE2 patch as a fixture`.

### Task 2: Derive the in-game gate from rich presence

**Files:**
- Create: `backend/app/collectors/rich_presence.py`
- Test: `backend/tests/test_rich_presence.py`

**Interfaces:**
- Produces: `in_game_gates(script: str | None) -> list[tuple[int, str, int]] | None`. Each tuple is `(address, size_letter, required_value)`, the same shape as the stored `gates`. `None` means the gate cannot be derived.

- [ ] **Step 1: Write failing tests** with a synthetic script modeled on the fixture's format: a script with two static single-condition branches `?0xS00163da4=0?On the Title Screen` and `?0xR00163da6=1?Watching a demo` plus a dynamic default line returns `[(0x163DA4, "S", 1), (0x163DA6, "R", 0)]`. Also assert `None` for: `None`/empty script; no static branch; a static branch with two conditions (`_`); a static branch on a byte operand (`0xH...=0`, its negation is not expressible); an unparseable condition.
- [ ] **Step 2: Run** `cd backend && uv run pytest tests/test_rich_presence.py -q`. Expected: FAIL (module missing).
- [ ] **Step 3: Implement `in_game_gates`.** Take the `Display:` section; a branch is `?<conditions>?<text>`; static means the text has no `@`. Parse each condition with `ra_flags.parse_operand` (`=` only); only bit sizes (`M`..`T`) can be negated (`=0` becomes required 1, `=1` becomes required 0). Any other case returns `None`. Return the gates sorted by address, no duplicates. Adjust the parsing to the real format found in Task 1 step 3.
- [ ] **Step 4: Add the oracle test** against `re2_patch.json`: `in_game_gates(patch[<rich presence key>])` equals `[(0x163DA4, "S", 1), (0x163DA6, "R", 0)]` (today's hand-written bits). If the real script differs, stop and report to the owner what the script shows; do not bend the test.
- [ ] **Step 5: Run the new tests: PASS. Commit** `feat: derive the in-game gate from the rich presence script`.

### Task 3: Build milestones by type and scenario

**Files:**
- Modify: `backend/app/milestones.py`, `backend/app/db/__init__.py` (migration + `milestone_groups` table)
- Test: `backend/tests/test_milestones.py`

**Interfaces:**
- Produces: `build(patch: dict, kinds: dict[int, str]) -> tuple[list[dict], dict[str, int]]`: items (same keys as today plus `"scenario": str`, `"" ` when there is no tag) and `undetectable` counts per scenario. Selected: achievement ids whose `kinds` value is `progression` or `win_condition`. Scenario: the text inside a leading `[...]` of `Description`. Common byte-check gates are computed per scenario group (existing logic).
- Produces: `save(conn, game_id, items, undetectable: dict[str, int])` (also fills `milestone_groups(game_id, scenario, position, undetectable)`, replacing the game's rows in both tables); `load(conn, game_id) -> list[dict]` returns only rows whose `scenario IS NOT NULL` (old rows are ignored), including `scenario`; `groups(conn, game_id) -> list[dict]` with `scenario`, `undetectable` in position order.
- Produces: `read(items: list[dict], mem_read) -> tuple[str, list[bool]] | None`: the first scenario whose items' gates all hold and its reached flags in item order; `None` if no scenario's gates hold.
- Schema: `milestones` gains `scenario TEXT` via the existing `ALTER` loop; `milestone_groups` is a new `CREATE TABLE IF NOT EXISTS` in `SCHEMA` (primary key `(game_id, scenario)`).

- [ ] **Step 1: Rewrite the tests** in `test_milestones.py` for the new `build` signature using the existing mini `PATCH` and a `KINDS` dict: only `progression`/`win_condition` ids are kept; `[Leon A]` and `[Claire A]` come out as two scenarios with their own gates; an untyped id is dropped; `Fell` (no plain flag) is counted in `undetectable["Leon A"]`; `End` and `Fast` still share one flag; no tag gives scenario `""`; a non-string `MemAddr` is skipped.
- [ ] **Step 2: Add tests** for `save`/`load`/`groups` round trip, for old rows (inserted with `scenario NULL`) being ignored by `load`, and for `read`: returns `("Leon A", [...])` when its gates hold, `None` when none hold (title screen zeroed RAM).
- [ ] **Step 3: Run** `uv run pytest tests/test_milestones.py -q`. Expected: FAIL.
- [ ] **Step 4: Implement** the signatures above; reuse the current gate/flag/dedupe code per group. In-game gates are appended later (Task 4), not here.
- [ ] **Step 5: Run `test_milestones.py` and `test_ra_flags.py`: PASS. Commit** `feat: build milestones from typed achievements, one group per scenario`.

### Task 4: Drop STORIES and derive everything in `ensure`

**Files:**
- Modify: `backend/app/collectors/ram_milestones.py`
- Test: `backend/tests/test_ram_milestones.py`

**Interfaces:**
- Consumes: Task 2 `in_game_gates`, Task 3 `build/save/load/read`, `ra_store.get_catalog(conn, ra_id)`.
- Produces: `ensure(conn, game_id, ra_id, install) -> list[dict]` (same signature; stored rows first, else fetch and build). `start(...)` runs for any game with a `ra_id` and a game code (no `STORIES`). The `milestones` signal payload becomes `{"ra_id", "scenario", "reached": [names], "total"}` for the active scenario only.

- [ ] **Step 1: Update the tests:** drop the `STORIES` monkeypatch; `PATCH` gains a rich presence script (reuse the Task 2 synthetic one under the real key) and the catalog is inserted into `ra_achievements`. Cases: builds and stores rows with the in-game gates appended; empty catalog gives `[]` and a `PROBLEMS` message mentioning syncing; no typed achievement gives `[]` and a reason; gate `None` gives `[]` and a reason and **no rows stored**; title-screen RAM stores no signal; a Leon A session stores a signal with `scenario == "Leon A"`; old rows (scenario NULL) cause a rebuild.
- [ ] **Step 2: Run** `uv run pytest tests/test_ram_milestones.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.** In `ensure`: `load` first; else login, `fetch_patch`, `kinds` from the catalog, then in order: empty catalog, no typed ids, gate `None`, no items, each setting a Portuguese `PROBLEMS[game_id]` and returning `[]`; otherwise append the gate to every item's `gates`, `save`, `load`. Delete `STORIES` and the `in_game` line in `_poll`; `_poll` uses the `(scenario, flags)` result of `read` and stores a signal only when it changes. `# shortcut: a game that fails to build refetches the patch every session; add a retry limit if it becomes noisy`.
- [ ] **Step 4: Run the whole backend suite** (`uv run pytest -q`). Expected: PASS except `test_milestones_api.py` (next task). Commit `feat: build milestones for any linked game, no hand-written story`.

### Task 5: The milestones route

**Files:**
- Modify: `backend/app/api_ra.py:81-96`
- Test: `backend/tests/test_milestones_api.py`

**Interfaces:**
- Consumes: `milestones.load`, `milestones.groups`, `latest_signal(conn, game_id, "milestones")`.
- Produces: `GET /games/{id}/milestones` → `{"supported": bool, "groups": [{"scenario", "total", "reached", "undetectable", "items": [{"name","reached"}]}], "active": str | None, "total", "reached", "items", "read_at", "problem"}`. `supported` is true when the game has rows. The top-level `total/reached/items` describe the active scenario (from the latest signal) or the first group, so the current frontend keeps working. Unsupported: `{"supported": False, "problem": PROBLEMS.get(game_id)}`.

- [ ] **Step 1: Update the tests:** a game with two groups and a signal for one returns both groups, `active` set and the top-level keys of the active one; a game without rows is `supported: false` with its `problem`; a signal of another `ra_id` is ignored (existing case).
- [ ] **Step 2: Run** `uv run pytest tests/test_milestones_api.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** the route as described.
- [ ] **Step 4: Run the full suite and `cd frontend && pnpm build`** (the frontend still reads the top-level keys). Expected: both PASS. Commit `feat: expose milestone groups and the active scenario`.

### Task 6: RE2 oracle end to end

**Files:**
- Test: `backend/tests/test_milestones_re2.py`

**Interfaces:**
- Consumes: both fixtures, `ensure`, `read`, `FakeMem`/`ram` helpers from `test_ram_milestones.py`.

- [ ] **Step 1: Write the test** that loads `re2_patch.json`, fills the catalog from its achievements and `kinds`, runs `ensure`, and asserts: the `Leon A` group contains every id in `re2_leon_a_ids.json`; gates include `(0x163DA4,"S",1)` and `(0x163DA6,"R",0)`; `read` is `None` on a title-screen RAM image and a `("Leon A", ...)` result on an in-game one.
- [ ] **Step 2: Run it.** If it fails because the derived Leon A set misses some of the 12 old ids, report which and why to the owner instead of loosening the assertion.
- [ ] **Step 3: Full suite + frontend build: PASS. Commit** `test: RE2 oracle for automatic milestones`.

### Task 7: Real check (the owner's call)

- [ ] **Step 1: Ask the owner** before launching RE2 (screen 1, muted). Then run the backend from this worktree with its own `ARGOS_DB` copy, start a session, and read `/games/<id>/milestones` on the title screen (no signal) and in play (Leon A reached count changes). Report the result, including anything unverified (loaded-save behavior stays UNVERIFIED, issue #16). Do not push or open a PR without the owner's OK.
