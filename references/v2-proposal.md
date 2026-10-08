# Task ledger v2 — "stack + archive stack" (proposal, 2026-09-16)

Synthesis of five parallel research passes (CLI task-tool data models · AI-agent state across compaction · stack/WIP ops patterns · evidence critique of the current file · ergonomics). Nothing implemented yet.

## 1. Why v1 broke (evidence from the file, not opinion)

| # | Root cause | Evidence |
|---|---|---|
| 1 | OPEN is an append-only pile, not a stack | 33 open, median age 12d, oldest 20d. 22/33 `blocked:user` yet rendered on every read. 24/33 no LOG line in ≥9d. |
| 2 | `now:`/`next:` are hand-kept shadows of LOG | 7/33 `now:` are verbatim LOG copies; `T33.9 next: 4h watchdog running` is 14d stale; `T2` cron expiry 9d past. |
| 3 | `def:` grows unbounded | `T41` def = one 4,923-char line with 10 `| amended` segments. History stored inside the hot record. |
| 4 | Buckets masquerade as tasks | `T17` carries 14 open subtasks spanning a new service, a prod Bigtable schema blocker, a bug, a naming nit. All 14 render under NEEDS YOU. |
| 5 | Archiving breaks the DAG + ids | `closed_ids()` reads only the in-file CLOSED block → `⚠ T17.6 deps on unknown T17.5` (T17.5 is in the archive). `cmd_add` computes next id from in-file ids only → id reuse after archive. Legacy tail (lines 603–715, 19 `##` headers) is invisible to the CLI. |
| 6 | `verify:` is prose, not a contract | 6/33 are `-`; of 6 run, 5 fail (wrong cwd, English sentences, bash-isms under `/bin/sh`). |
| 7 | Line budget is upside down | LOG 44%, OPEN 37%, legacy tail 16%, CLOSED 2%. The hot view is the minority of the file the agent must re-read after every compaction. |

Field consensus (Anthropic context-engineering note, beads/`bd ready`, the "flat tickets + `tk ready`" backlash, Ralph-loop plan files, ESAA event-log→projection papers): the agent should re-hydrate from a **bounded derived view**, never from the whole store; done items must leave the hot file; history is an append-only log the hot view points to.

## 2. Storage: events in, views out

```
scratch/ledger/
  events.jsonl        append-only truth: every add/mutate/push/pop/close/log/answer is one event
  HOT.md              rendered, ≤40 lines, never hand-edited (regenerated on every write)
  ARCHIVE.md          rendered: closed + lapsed, newest first, one line each + link to events
  tasks/T41.md        rendered per task on demand (`ledger show`): def, full history, evidence
```

- Stable ids allocated from the event log (never reused; fixes root cause 5).
- `def` is immutable, one line. Amendments, `now`, notes are events; `now` is *derived* = last event on the task (kills root cause 2 and 3).
- Hand-edit safety: `HOT.md` says "generated — edit via `ledger`" at the top. If someone edits it anyway, the next write regenerates it; nothing is lost because the truth is the log. Free-hand notes go through `ledger log T41 "..."`.
- Lighter alternative if JSONL feels heavy: keep markdown but split into three files (OPEN / CLOSED append-only / LOG). It fixes 5 and 7 but not 2 and 3. Recommendation: events.

## 3. Stack semantics (the part the user asked for)

The stack is **not the ledger**. It is a thin pointer list over what you own right now.

| Bucket | What lives here | Cap | Shown in HOT |
|---|---|---|---|
| **NOW (stack)** | tasks you are actively working; top = `current` | depth 3 | always, top first |
| **NEXT** | ready to start (deps clear, not blocked) | 5 shown | yes |
| **WAITING** | `blocked:user`, `blocked:ext`, `delegated`, `watching` — each with a `poke_after` date | — | only pokes due today |
| **COLD** | parked / eventual | — | one line: `+N cold` |
| **ARCHIVE** | closed, lapsed | — | never (own file) |

Commands: `push T41` (T41 → current; previous current stays on the stack as *interrupted*), `pop` (= close current, resume the one beneath), `peek`, `park T41` (→ COLD), `promote T41` (COLD → NEXT), `wait T41 --until 2026-09-20 --on user` (→ WAITING with poke date), `resurrect T41` (ARCHIVE → NEXT).

Rules the CLI enforces, not the prose:
- Pushing a 4th item onto NOW is refused until one is popped or parked. Depth > 1 is printed as a debt line in HOT.
- WAITING never enters NOW. A poke past due surfaces in HOT as "POKE T44 (user, 3d overdue)".
- `layer:` is dropped; the four buckets replace it (30/33 tasks were L1/L2 anyway, 1 was L3).
- `deps:` and dotted subtasks stay. A subtask cannot be in NOW if its parent is COLD. A parent with open children cannot be popped without `--cascade`.
- New captures land in NEXT by default, never on the stack (Linear triage rule).

## 4. Hot view (what the agent reads after compaction)

```
# HOT · 2026-09-16 09:40Z · now 2/3 · next 4 · waiting 11 (2 pokes due) · cold 6
NOW
  ▶ T43  llm-proxy prod release (#414+#415)          verify: gh pr view 415 …   last: 08:31 marked ready
    T48  YAML runbook runner spike                    last: 07:55 brainstorm doc
NEXT
    T41  stale knob billing bug                       verify: …
    T38  close superseded PRs #1361 #5938
POKES DUE
    T17.22 thalamus prod footprint (user, 9d)   T2 gemini monitor cron expired 09-07
+6 cold · +11 waiting → `ledger list --all`
```

One line per task: id, title, verify pointer, last event. Nothing else. Depth of detail is one hop away (`ledger show T43`).

## 5. Record contract

- `def` one line, immutable. `repo:` (cwd for verify). `verify:` must pass `bash -n` and a `--dry` execution at write time or `add`/`mutate` refuses it (kills root cause 6). `ev:` ≤2 pointers. `deps:`/`parent` as today.
- Everything else is an event: `{ts, id, type: add|log|amend|push|pop|park|promote|wait|close|answer|verify, text, by: main|subagent-name}`.

## 6. Rituals and auto-rules

- Re-hydrate = run `ledger hot` (bounded output, loud non-zero exit on parse failure). Never `cat` the store. Put it in the session-start / post-compaction step.
- Close prompts on triggers, not timers: at session start, and when a push would exceed the cap. ≤5 candidates, oldest untouched first.
- Auto: closed → ARCHIVE immediately. WAITING untouched 14d → poke + flagged `stale`. COLD untouched 45d → ARCHIVE as `lapsed` (recoverable with `resurrect`; logged).
- Verify-then-report, never self-close, subagents write only their artifact files: unchanged from v1.

## 7. Migration from the 715-line file

1. `ledger import PENDING_TASKS.md PENDING_TASKS_ARCHIVE.md` → one `imported` event per T-block (def, deps, ev kept; `now`/`next`/amendments become dated `log` events; CLOSED blocks → close events; the 603–715 legacy tail → one `note` event per `##` header, flagged `legacy`).
2. One forced re-state pass (Bullet-Journal migration): each of the 33 open tasks must be re-stated in one line into NOW / NEXT / WAITING(with poke date) / COLD, or it auto-closes as `lapsed`. T17 gets split into its real threads (service cutover, prod footprint, is_alloy_user, bugs) instead of one 14-child bucket.
3. Regenerate HOT.md; keep the old file read-only for a week, then delete.

Expected outcome: hot view ~25 lines instead of 715; the agent's post-compaction read drops from the whole file to one CLI call.

## 8. Decisions needed

1. Events JSONL + rendered views (recommended) vs. three markdown files.
2. NOW depth 3 and "refuse the 4th push" — or a softer warning.
3. Drop `layer:` in favour of the four buckets.
4. Migration auto-lapse for tasks not re-stated in the one-time pass (recoverable) — or manual only.
5. Name of the store dir (`scratch/ledger/`).

Sources gathered by the research passes: Taskwarrior 3 upgrade + terminology, todo.txt, org-mode archiving, Obsidian Tasks, beads (`bd ready`), Show HN "tk" flat-ticket replacement for beads, Ralph-loop prompt files, Anthropic effective-context-engineering, LangGraph persistence, ESAA/PROJECTMEM event-log→projection papers, Personal Kanban WIP limits, Google SRE "Dealing with Interrupts", GitLab on-call handover, Linear triage/auto-archive, Now/Next/Later, GTD weekly review, Bullet Journal migration.
