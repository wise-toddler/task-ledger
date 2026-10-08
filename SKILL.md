---
name: task-ledger
description: Maintain Shivansh's task ledger v2 — an append-only event log (out/events.jsonl) rendered into a bounded HOT view with a 3-deep NOW stack over a task DAG. Use at session start, after every context compaction, and on every user message in the "local main" session (each message = new task | status | close).
---

# Task Ledger v2

Truth: `out/events.jsonl` (append-only, one JSON event per line). Views: `out/HOT.md` (≤40 lines, regenerated on every write) and `out/ARCHIVE.md`. **Never hand-edit the views; never `cat` the event log.** Re-hydrate with one command:

```
python3 scripts/ledger.py hot        # or just: python3 scripts/ledger.py
```

`out/` is gitignored and personal. `LEDGER_HOME=<dir>` overrides it (per-repo ledgers, tests).

**Owner.** Every task carries `owner` = the session that added it. Set yours once per session: `export LEDGER_OWNER=<short-name>` (e.g. `main`, `alloy`, `bedrock`); without it the default is `sess:<last 8 of the Claude session id>` (falls back to `<repo>@<tty>` outside Claude); `ledger owner --alias <name>` maps this session to a friendly name once (out/owners.json). Do this at session start. `ledger owner` prints yours, `ledger owner --list` counts per owner, `ledger owner --rename OLD NEW` re-tags. Never encode the owner in the title.

## Buckets (the *when*), states (the *who*)

| Bucket | Meaning | Cap | In HOT |
|---|---|---|---|
| **NOW** | the stack — top is `current`, below it are interrupted tasks | depth 3 | always, top first |
| **NEXT** | ready to start: deps clear, yours | 5 shown | yes |
| **WAITING** | parked on someone/something: `--on user | ext | delegated:<name> | watching[:<what>]`, with a `--until` poke date | — | only pokes due |
| **COLD** | parked / eventual | — | `+N cold` |
| ARCHIVE | closed (done · user-word · superseded · abandoned · external · lapsed) | — | own file |

**Priority.** `prio T<n> P0|P1|P2|none` (or `add --prio`). P0 = drop everything (red, top of every column, `!!` in hot), P1 = this week (amber, `!`), P2/none = normal. Priority is orthogonal to bucket: a P0 can sit in WAITING when it is someone else's move.

`deps:` carries the DAG (`--after "T20 T21"`), dotted ids are subtasks (`T17.3`, any depth). Derived, never stored: `← waits T41` (open deps), pokes due, the NOW debt line.

Rules the CLI enforces (do not argue with them, fix the state):
- 4th `push` is refused → `pop` or `park` first. WAITING tasks cannot be pushed → `promote` first. A child cannot be pushed while its parent is COLD (push pulls the parent to NEXT).
- `close`/`pop` on a parent with open subtasks needs `--cascade`. Unknown deps and cycles are rejected at write.
- `verify:` must be valid bash (`bash -n`) and runs in `repo:` (cwd). `ledger verify T<n>` records the exit code as an event.
- A new capture lands in NEXT (or WAITING with `--on`), never on the stack.

## Per message type

**New task** → `add "<title>" [--desc] [--after "T20"] [--parent T17] [--repo] [--verify] [--ev] [--on user --until YYYY-MM-DD]` BEFORE starting work; print the id. Working on it now → `push T<n>`. A mutation of an existing deliverable = same id + `amend T<n> "<what changed>"`, never a fork.
**Status** (bare "status" = `hot`; named = `show T<n>`) → **verify-then-report**: run `verify T<n>` first; never report PR/merge/deploy state from the file or memory. Lead with NOW, then pokes due, then what is newly unblocked (`close` prints it).
**Close** → only on the user's word or verified evidence: `close T<n> --type done|user-word|… --evidence "<proof>"`, or `pop --evidence` for the current task. Never self-close: `wait T<n> --on user` and ask. Reusable lesson → memory, cite the id.
**Interrupt** → `push` the new thing; the old one stays on the stack as interrupted; `pop` returns to it. Depth > 1 is printed as debt — finish or `park`.
**Poke due** (WAITING past `--until`, or untouched 14d) → chase it, then `ack T<n> --until <next date>` or `promote`/`close`.
**Re-shape** → `detach T17.22` (subtask → top-level `T<new>`, alias kept, deps re-pointed) · `adopt T49 --parent T17` · `dep T<n> --add/--rm` · `set T<n> --title/--repo/--verify/--ev`.

## Commands

`hot` · `list [--all|--bucket B|--owner O] [-q]` · `owner [--list|--rename OLD NEW|--alias NAME]` · `prio T P0|P1|P2|none` · `show T` · `add` · `push T` · `pop [T] --evidence` · `peek` · `close T --evidence [--cascade]` · `park T` · `promote T` · `wait T --on X [--until D]` · `ack T --until D` · `reopen T` · `log T "<text>"` · `amend T "<text>"` · `set T …` · `dep T --add/--rm` · `detach T` · `adopt T --parent P` · `verify T` · `graph` (mermaid) · `sweep [--apply]` (COLD untouched ≥45d → lapsed, recoverable with `reopen`) · `import <v1 files>` · `restate <tsv>`

`scripts/ledger_web.py [--port 9099] [--open]` — read-only live view: bucket cards + DAG (solid = dep, dotted = parent), click a node for history. Polls every 1.5s, keeps the last good read through a mid-write tear.

`scripts/verify_recipes.sh <type> …` — canned verify one-liners: `pr <repo> <num> [sha]` · `deploy <ssh> <ctx> <ns> <name>` · `cloudrun <ssh> <project> <service> [ENV…]` · `flagsync <owner/repo> <workflow.yml> <substr>`. `ledger_web.py` links `repo#123` under `https://github.com/$LEDGER_GH_ORG/`.

## Write discipline

**The store is shared by every Claude session on this machine** (one `out/` per checkout), so the NOW stack can change under you. Never `pop` blind: use `pop T<n>` (refuses if T<n> is not the top) or `close T<n>`. A task you did not add is another session's — leave it alone unless the user says otherwise.

Single writer per event = the session that owns the task. Subagents write only their own artifact files and report back; main records with `log`. `LEDGER_BY=<name>` stamps events from another writer. Every reply that reports state MUST run `verify` (or a recipe) first.

## References

`references/v2-proposal.md` (why v2: evidence from the v1 file + the research behind buckets/stack/events), `references/dag-design.md` (deps as a field, dotted ids), `references/operator-lens.md`, `references/robustness-lens.md`. v1 CLI kept as `scripts/ledger_v1.py` for reading old markdown ledgers.
