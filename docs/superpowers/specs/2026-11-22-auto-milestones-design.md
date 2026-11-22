# Automatic story milestones from RetroAchievements progression

Status: approved by the owner (2026-11-22). Branch: `feat/auto-milestones`.

## Intent

Today only Resident Evil 2 (GameCube, RA game 3176) has story milestones, because `ram_milestones.STORIES`
is hand-written: an achievement description prefix (`[Leon A]`), a list of ids to skip, and the RAM bits that
mean "a game is being played". The goal of Argos is a progress estimate across many games; a hand-written
entry per game does not scale. Any game linked to RetroAchievements should get milestones by itself, built from
what RA already says about it, and Argos should read them live from Dolphin's RAM during a session.

## Goals

- Milestones for any linked game come from the achievements typed `progression` and `win_condition`; no per-game table.
- The "a game is being played" gate comes from the game's own RA data, not from hand-picked bits.
- Games with several scenarios (RE2: Leon A, Leon B, Claire A, Claire B) get one milestone group per scenario.
- RE2 keeps working: the hand-written entry becomes the test oracle (the derived result must agree with it).

## Non-goals

- Progress percentage / fusion of signals (phase 5). This only produces the signal.
- Milestones for achievements whose rule is not a plain "flag becomes X" (counters, measured values). They are
  reported as not detectable (with the count), not guessed.
- Other emulators than Dolphin, and consoles other than GameCube.
- Verifying that flags survive a loaded save (issue #16). Still open, still UNVERIFIED.

## Anti-goals

- A wrong gate that stores empty or false signals (title screen read as "nothing reached"). When the gate
  cannot be derived for a game, the reader does not run for that game and the API says why. Failing closed
  beats a signal that looks real.
- Sending credentials anywhere new. `r=patch` keeps using the Dolphin login the app already uses.

## Constraints

- Keep the structure: `milestones.build/save/load/read`, `ra_flags.milestone_flag`, the `milestones` table, the
  `milestones` signal, the `/games/{id}/milestones` route.
- Rules are fetched with `r=patch` and the Dolphin RA token (the API key does not work there); no login means no
  milestones, as today (`PROBLEMS` shows why).
- Code and docs in English, UI text in Portuguese. Tests for new logic.

## Approaches considered

1. Minimal: type + `[tag]` grouping, keep the "common byte checks" gate guess and per-game overrides.
   Small, but the gate is a guess that fits RE2 only.
2. (Chosen by the owner) 1 plus a gate derived from the rich presence script in the `r=patch` response.
   Larger, no hand data; RE2 is a ground truth to check the parser against.
3. API only: milestones reached = progression achievements already unlocked. Cheapest and already useful for the
   estimate, but no live detection. Not replaced by this work; it stays available as a separate signal.

## Design

1. **Selection.** Join the patch achievements with the stored `ra_achievements.kind` (by achievement id) and
   keep `progression` and `win_condition`. `missable` and untyped ones fall out, which replaces `skip`.
2. **Scenario groups.** Group by the leading `[tag]` of the description; no tag means one group. Per group,
   the common byte checks of its rules still give the scenario gate (RE2: `0xH00163db6=0` Leon, `=1` Claire).
3. **Flags.** Unchanged: `milestone_flag`. Rules without a flag are counted as `undetectable` per group.
4. **In-game gate from rich presence.** The patch carries the rich presence script. Its display lines look
   like `?condition?text`. Proposal (the builder's call to validate against RE2): a display branch whose text
   has no dynamic part (no `@Lookup(...)` / `@Macro(...)`) describes a non-playing state ("On the Title Screen",
   "Watching a demo"); the in-game gate is the negation of those conditions. Only single-condition branches
   can be negated into the existing AND list of gates; if any branch has several conditions, or no static
   branch is found, the gate is unknown and the reader stays off for that game.
5. **Storage.** The derived in-game gates are stored with the rows (today they live only in memory, from
   `STORIES`), plus a `scenario` column (migration). `STORIES` is deleted.
6. **Reader.** `_poll` starts for any game with a RA link, stored milestones and a known gate (not for a
   `STORIES` membership). Everything else in `_poll` stays (attach, game code check, store on change).
7. **API.** `/games/{id}/milestones` returns groups, reached counts, `undetectable`, and a `problem` that says
   why a game is not supported (no login, no gate, no typed achievements).

## Verification

- Fixture: the real RE2 `r=patch` response, fetched once with the Dolphin login the app already holds and saved
  under `backend/tests/fixtures/` with the token and user stripped.
- Oracle test: for RE2 the derived in-game gate must be false on the title screen and during a demo and true in
  play, using the bits the hand-written entry used (`0x163DA4` bit S, `0x163DA6` bit R), and the derived Leon A
  milestones must include today's 12.
- Unit tests for typed selection, `[tag]` grouping, the display-branch parser, and the fail-closed paths.
- Real check, the owner's call: play RE2 on screen 1, muted, and watch `/games/{id}/milestones`.

## Left to the builder

- Exact grammar of the rich presence script and how much of it to parse; start with what RE2's script uses.
- Whether `scenario` is a column or part of the stored JSON.
- Migration wording and the group order shown by the API.

## Known limits (noted for later)

- Only RE2 has been looked at. Games whose RA set has no `progression` achievements, whose rules are counters
  instead of flags, or that have no rich presence script come out as "not supported" (with the reason). The
  owner agreed to leave it at that for now; a fallback for untyped sets (use every achievement with a simple
  flag) was discussed and deliberately not built, to avoid inventing milestones.
- The type is chosen by the set's volunteer authors and is optional; even in RE2 70 of 172 achievements are untyped.
  Coverage on a second game is unknown until one is linked and checked.
