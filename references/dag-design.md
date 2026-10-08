# Task-ledger DAG + subtasks — design rationale (2026-08-31)

Trigger: the live ledger grew two multi-hop chains whose edges existed only as English prose inside `now:` — `T20 → T21 → T22` ("blocked on X3 + CA1") and `T23 → T24 → T25 → T26 → T27` ("blocked on skeleton", "blocked on write-path"), plus `T13 → T11 → T14 → T15`. 9 of 19 open tasks were waiting on another task, and `list` showed all 19 as one flat wall. The question the user actually asks many times a day — "pending tasks?" — was answerable only by reading prose.

## 1. Edges are a field, not a state

`deps: T20 T21` on the task block. Rejected alternatives:

- **`blocked:T23` as a state.** Loses information: state answers *who is blocked* (the user's go vs an external PR vs an agent), deps answer *what order things run in*. T24 is genuinely `blocked:user` AND downstream of T23 — one slot can't hold both. It also forces a state rewrite on every dep close, exactly the write that gets lost when a session compacts between the two events.
- **A separate edges block / JSON sidecar.** The file is hand-edited; a second place to edit is a second place to drift.

One space-separated line, omitted entirely when empty, so every pre-DAG block parses unchanged and migration is a no-op for tasks with no edges.

## 2. No auto-flip on close; readiness is derived on every read

When a dep closes, the dependent's state is **not** rewritten. `close` prints and LOGs `unblocked (T23 closed)`, and — the load-bearing part — `list` recomputes readiness from the file every time. Nothing depends on the session remembering. If a `blocked:*` task's deps are all closed, `list` renders `⚠ deps clear`: a self-healing nudge that survives compaction, session death, and a hand-edit that closed a dep without touching the dependent.

Auto-flipping to `active` would have been a lie in most real cases: T24 is `blocked:user` for its own reason (the user's go), not only because T23 was open.

## 3. Subtasks are dotted ids

`T23.1`, not a `parent:` field, and not both. The id IS the parent link, so a hand-edit cannot desync id from parent; it sorts naturally; and the existing regex needed one change (`T\d+` → `T\d+(?:\.\d+)*`). A `parent:` field can contradict the id and gives the parser two sources of truth.

- Parent is implicitly blocked by its children (children are added as parent deps for cycle detection), so a parent↔child cycle is caught.
- `close` on a parent with open children is **refused**, `--cascade` closes children first. Silent orphaning of children is the failure mode worth spending an error on.
- Bucketing classifies a parent by its *own* deps only, with children rendered indented beneath it. Counting children as blockers would sink every parent into WAITING and destroy the top-level structure.

## 4. Rendering: five buckets, ordered by who has to act

`NEEDS YOU` (blocked:user, deps clear) → `READY` → `IN FLIGHT` (delegated/watching) → `WAITING ON A TASK` → `WAITING ON EXTERNAL`. Empty buckets are skipped. Rationale: "pending tasks?" is really "what needs me", so the user's own decisions come first; work an agent or cron is already on is separated from work nobody is on, because the two need different replies.

WAITING is rendered as **nested chains**, not `← blocker` groups. The first attempt grouped each waiting task under its dep-set, which shredded the thalamus chain into four one-item groups — more lines than the flat list it replaced, and the chain shape (the actual information) was gone. A task hangs from its **latest** open dep (highest id — in practice the nearest hop), with any other blockers shown inline as `(+T11)`. Five thalamus tasks collapse into one 5-line chain under one anchor.

Line budget: 19 open tasks render in ~35 lines vs 57 before, and `now:` is shown only where it changes what you'd do next (READY / IN FLIGHT).

## 5. Integrity

Checked at write time (add/mutate): self-dep, dangling dep (an id in neither OPEN nor CLOSED), and cycles via DFS over explicit deps + implicit parent→child edges — the error prints the cycle path. Checked at read time (never fatal): a dep id that resolves to nothing renders as a `⚠` footer line rather than crashing `list`.

A dep pointing at a CLOSED id is *satisfied*, not dangling — that is the whole mechanism by which closing a dep frees its dependents.

Two integrity bugs the live file surfaced: `T8` existed simultaneously in OPEN and CLOSED (id reuse), and `T7` twice in CLOSED. `add` now maxes over closed ids too, so ids are never reused; resolution treats an OPEN block as authoritative over a CLOSED row of the same id, and `list` prints the collision as a warning instead of silently picking one.

## 6. Layers (2026-09-01)

`layer: 1|2|3` — 1 = being worked now, 2 = this cycle, 3 = parked/eventual. Same shape as `deps:`: one line, own field, omitted-line-parses-as-default, so every pre-layer block is untouched. It is a **third axis**, not a re-spelling of the other two: state = who is blocked, deps = what order, layer = when. Collapsing layer into state (`parked` as a state) would repeat §1's mistake — a task can be `blocked:user` *and* parked, and closing a dep must not have to rewrite it.

- **Default 2, for a missing line as well as a new task.** The filter's failure direction decides this: default 3 would let any legacy or hand-written block silently drop out of the default view — work disappearing is the one outcome this ledger exists to prevent. Default 1 fails the other way: if everything lands in "now", layer 1 stops meaning anything and the wall of 24 comes back. 2 shows in the default view *and* leaves 1 meaningful. Migration of the 24 pre-layer blocks was therefore a pure no-op for rendering.
- **Promotion is an operation; demotion is a field edit.** `promote` is the frequent, ratchet-like direction (a parked thing becomes relevant) and it has a consequence the user should not have to remember: whatever gates the task — its open deps, its parent thread — is dragged to the same layer, transitively, so the promote can't leave an inversion behind. Demotion is rarer and deliberate ("park this"), so it stays `mutate --layer 3` with no cascade: parking a task must never silently park the things waiting on it. Refusing demotion outright would be wrong — priorities genuinely recede (T16/T33.6 is P3 by the user's own words) — and a tool that refuses gets hand-edited around.
- **A subtask carries its own layer, seeded from its parent at creation.** Pure inheritance would make "this thread is active, this piece of it is eventual" unsayable — which is exactly the live shape (thalamus active, cortex cutover eventual). Two sources of truth is not a risk here the way `parent:` was in §3: the layer is *copied* once, not derived on every read.
- **Inversions are surfaced, never auto-fixed.** Two are computed on every read, alongside `⚠ deps clear`: a task nearer-term than something it waits on (`T17.5 (L1) waits on T17.4 (L2)`), and a subtask nearer-term than its parent. The first fired on the live ledger the moment layers landed and turned out to be real information — the read-path was being worked ahead of the write-path lift it nominally depends on, meaning either the dep or the plan is stale. Auto-promoting the blocker would have erased that finding. Parent→child edges are deliberately *excluded* from the first check: a parent is a container blocked by its children, so an L1 parent with an L3 child is normal, and only the reverse (parked thread, live piece) is a contradiction.
- **Filtering is per thread, and never hides a blocker.** `list` hides layer-3 *top-level* tasks (footer keeps the count) but always renders a whole thread once its parent is shown — hiding pieces of a thread you are reading is worse than showing a parked one — and pulls a hidden thread back in if something shown still waits on it. A blocker you cannot see is the worst possible omission; the inversion warning then explains why it is there.

## 7. One classifier, two consumers

`render()` used to be print-only, so `ledger_web.py` carried a transcribed copy of the bucket if/elif under a `# MIRROR:` comment — two places to edit, one of them silent when it drifted. The classification now lives in `ledger.py buckets(bl, closed)`, which returns idx / kids / open_deps / chain / roots / layers / the five ordered buckets / warnings; `render()` prints it and the viewer serializes it. Cycle detection came along for free (the viewer had it, `list` did not). `ledger_web.load_ledger()` asserts `buckets` and `layer_of` exist, so moving them fails loudly at startup instead of rendering a stale mirror.

## 8. Regrouping an existing task (id remap)

The id *is* the parent link (§3), so moving a task under a parent means changing its id — against the "stable id, never reused" rule. The compromise, applied when the 24-task flat list became two threads: renumber, and pay for it with a breadcrumb in three places — a `| amended <ts>: regrouped T20 → T33.3` on the `def` line (so the block itself says where it came from), one `REGROUP:` LOG line carrying the whole map (so a single grep resolves any old id in older LOG lines), and `deps:` rewritten to the new ids in the same pass. Old LOG/CLOSED lines are never rewritten — the LOG is append-only, and the map line is what makes them readable. Choosing the parent: the oldest task in the thread *if its `def` already scopes the whole thread* (T17 did — its amendment defined the service, not one deliverable), otherwise a fresh parent id (T33 — T11's def bounded itself to "design doc only, no impl" and could not honestly become the thread).

## 9. Known gap

`ledger.py` is read-modify-write with no locking, and the DAG makes multi-command edits more common. Two writers (main session + a subagent) can still lose an update. The single-writer rule in SKILL.md is the only thing holding this; if subagents ever need to write, this needs a lock file.
