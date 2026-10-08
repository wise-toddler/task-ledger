# Task-tracking skill — operator-ergonomics lens (2026-08-27)

Design target: Shivansh's real flow — rapid Hinglish messages, mid-turn interjections, 5+ parallel subagents, hourly crons, PRs across 6 repos, tasks that mutate twice before landing ("9-c→9-a" → "b,c→luna" → "rahane do"), sessions that compact and must recover. Update cost per message must stay ~5s of model effort.

## 1. File format

P1. **Single MD, one block per task, stable short ids** (`T1`, `T2`… never reused).
   Tradeoff: no per-task history, but zero navigation cost and one Edit per update.
P2. Per-task files under `scratch/tasks/`.
   Tradeoff: clean history per task; too slow for rapid-fire updates, session must glob+read N files.
P3. JSON ledger + rendered MD.
   Tradeoff: machine-checkable; double-write burden, JSON edits are where models make quoting mistakes.

→ **P1.** Task block (max 4 lines):

```
### T7 gemini PT GSU ask [blocked:user] upd 08-27
now: someone bought ~175 GSU; formal 115-135 ask probably moot
next: user confirms → close
ev: scratch/routerbench-recon/rollout-verify-2026-08-27.md · cron fb6c6f62
```

Fields: id+title+`[state]`+upd date on line 1; `now:` (latest truth, rewritten in place); `next:` (who is blocked on what — this is the line status replies read); `ev:` (≤2 canonical pointers; full ids live in the report docs, not here).

**Mutation vs new:** same deliverable changing shape = same id, rewrite `now:`/title, append `(v2)` to title if the definition materially changed. Different deliverable = new id. Never fork a task silently — if unsure, mutate and say so in the reply.

## 2. Message classification

Rules in order, first match wins:
1. Close words — "close", "done", "rahane do", "ignore", "chhod do", "ho gaya", "band kar" → **close** (nearest matching open task).
2. Question form / "status", "kya hua", "?" alone, "kitna hua" → **status**.
3. Imperative naming an existing task/artifact ("harbour theek krdo", "sync krde") → **mutation** of that task (new sub-goal under same id) — not a new task.
4. Imperative with a new deliverable → **new task** (assign id immediately, write the block BEFORE starting work).
5. Ambiguous between two open tasks → status of the best match + one line "isko X maana; galat ho to bolo" — never a blocking question, never start irreversible work on a guess.

## 3. Status replies

- Named task: ≤4 lines — state word, `now`, `next`, one evidence pointer. Verify externally-mutable facts fresh (see §5) before replying.
- Bare "status": numbered one-liners for every OPEN task (`T3 A2A follow-ups [blocked:user] — guard#6 commit + un-draft pending`). No CLOSED items unless asked.
- Evidence in chat: 8-char ids + one link; anything longer stays in the task's report doc.

## 4. Lifecycle

States (one word in brackets): `active` (main session working) · `delegated:<agent>` · `watching` (cron/monitor, note cron id + expiry) · `blocked:user` (needs go) · `blocked:ext` (review/CI/other person).

Close: move block to `## CLOSED` as ONE line — `T7 closed 08-27: outcome + evidence link`. Keep evidence, drop prose.
Archive: when CLOSED exceeds ~15 lines or is older than 7 days, append to `scratch/PENDING_TASKS_ARCHIVE.md` and truncate. OPEN section must always fit in one screen.
Restart recovery: skill instructs a fresh session — read OPEN section first; treat every `now:` involving PR/deploy/sync state as STALE until re-verified; `delegated:` tasks whose agent died = re-check the deliverable file, not the agent.

## 5. Integration

- **Subagent spawn**: write `delegated:<name>` + expected deliverable path into the block in the SAME turn as the Agent call. On task-notification: update `now:` in the same turn, with the evidence path the agent returned — never mark done on the agent's claim without the file existing.
- **Crons**: `watching` + cron id + auto-expiry date; cron fires only update `now:` when a flag condition trips.
- **PR-state rule (fixes today's #1241/#3021 failures)**: any status reply or task update that mentions a PR MUST run `gh pr view --json state,mergedAt` fresh — the file is never the source of truth for merge state. If merged → suggest close in the same reply. Corollary: **before pushing more commits to a PR branch, check PR state; if merged, the commit goes to a new PR** (the b,c-missed-the-merge failure).
- **Memory boundary**: task file = live work state, dies with the task. Memory = preferences, protocols, durable facts. A closed task that taught something reusable → write the memory at close time, link it from the CLOSED line.

## 6. Predicted anti-patterns (each observed today)

1. Trusting the file/context for merge/deploy state → stale "still open" claims. (Fix: §5 PR-state rule.)
2. Pushing to a PR branch after it merged → commit silently orphaned. (Fix: pre-push state check.)
3. Recording tasks only at completion → spawn-time tasks vanish when the session compacts. (Fix: write block before work starts.)
4. Marking delegated tasks done from the agent's summary without opening the deliverable.
5. CLOSED/prepend bloat — three "updated" headers stacked in one file. (Fix: single OPEN section, archive policy.)
6. Treating a mutation as a fresh task → two blocks tracking one deliverable, statuses diverge.
7. Cron noise promoted into task updates — only flag-condition breaches touch the file.

## Recommended SKILL.md skeleton

```markdown
---
name: task-protocol
description: Track Shivansh's tasks in scratch/PENDING_TASKS.md — every user message is new-task, status, or close; open tasks live until explicitly closed. Load at session start and before answering any "status".
---

# Task protocol

File: `scratch/PENDING_TASKS.md` (repo-relative). Archive: `scratch/PENDING_TASKS_ARCHIVE.md`.

## On session start / after compaction
1. Read the OPEN section. 2. Treat every PR/deploy/sync fact in `now:` as stale. 3. Do not re-verify eagerly — verify per task when it is next touched.

## On every user message — classify, then act
- CLOSE ("close/done/rahane do/ignore/chhod do"): move the block to CLOSED as one line with outcome+evidence; confirm in ≤2 lines. If a reusable lesson, write a memory and link it.
- STATUS (question form / "status" / "kya hua"): named task → verify mutable facts fresh (gh pr view / kubectl / run list), reply ≤4 lines (state·now·next·evidence). Bare "status" → numbered one-liners of all OPEN.
- MUTATION (imperative naming an existing task): rewrite that block's `now:`+`next:`, keep the id, then do the work.
- NEW TASK (imperative, new deliverable): append a block (next free Tn, state, now, next, ev) BEFORE starting the work.
- Ambiguous: answer as status of best match + "isko X maana; galat ho to bolo".

## Task block format
### Tn <title> [active|delegated:<agent>|watching|blocked:user|blocked:ext] upd <date>
now: <one line, current truth>
next: <who is blocked on what>
ev: <≤2 pointers>

## Hard rules
- PR/merge/deploy state: NEVER from this file — always `gh pr view --json state,mergedAt` / cluster check at reply time; if merged, suggest close.
- Before pushing to any PR branch: check PR state; merged → new PR.
- Subagent spawn: record `delegated:` in the same turn; completion: update only after the deliverable file exists.
- Crons: record as `watching` with id+expiry; update `now:` only on flag breaches.
- Keep OPEN ≤ one screen; CLOSED >15 lines → archive file.
```

Adoption note: current PENDING_TASKS.md already has OPEN/CLOSED/ARCHIVE — migrate by assigning T1..Tn to the 7 open items and deleting the stacked historical headers.
