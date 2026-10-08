# Task-tracker skill — robustness/correctness lens (2026-08-27)

Grounding failures from this session: #1241 reported unmerged after it merged; d8d733cb pushed after squash-merge → silently absent from main; E2E monitor subagent died on credits, in-flight state lost; compaction dropped in-flight detail (PENDING_TASKS.md was the recovery anchor); `kubectl set image` "done" but eval pods read a configmap → Argo revert; GSUs bought externally mid-watch; multiple subagents editing the same docs.

## Proposals

### P1 — Verification-before-status (never trust the file for external state)
Every task entry carries a `verify:` line — ONE cheap command + expected output. Status = run it, diff, report, stamp `last_verified`.
- Tradeoff: cost/latency per status ping. Mitigate: only "state-bearing" tasks (external state) get verify; pure todo items skip; 5-min result reuse.
- Corollary rule (from d8d733cb): a "merged" check on a PR you pushed to late is TWO checks — PR state AND `git merge-base --is-ancestor <your-sha> origin/main`.
- Corollary rule (from configmap): a deploy verify must name EVERY consumer of the artifact (deployment image + configmap + Argo sync), not the one you touched.

### P2 — Single writer, two sections
Only the main session writes the tracker. Subagents return payloads; main records on notification. OPEN = mutable current-state snapshots; `## LOG` = append-only timestamped one-liners for every transition (opened/amended/verified/drift/closed). Post-mortems read LOG; status reads OPEN.
- Tradeoff: main session is a bottleneck; a dying subagent's last state is lost unless it returned early. Mitigate: subagent prompts must require incremental artifact writes (their own files), never tracker writes; tracker links the artifact.

### P3 — Self-contained entries (crash/compaction recovery)
Fields per task: `id` (T-NN-slug) · `opened` (UTC) · `def` (user's words, 1 line, immutable — amendments appended with ts, never rewritten) · `state` (open|blocked|awaiting-user|watching) · `owner` (main|subagent:<name>|external:<who>) · `verify:` · `expect:` (watch tasks) · `resume:` (worktree/branch/script/prompt pointer) · `artifacts:` (paths, PR URLs, run ids) · `last_verified` (ts + observation).
A fresh session reconstructs everything from OPEN alone; context is never canonical, the file is.

### P4 — Drift detection for watch-tasks
Watch tasks encode `expect:` as concrete observable state ("harness image v1.2.82 in deploy AND configmap AND Argo Synced", "gemini buckets 9,a only"). Status = verify output diffed against expect; mismatch = ⚠️ + LOG line. The rollout-verify run is the template (expected table vs observed, PASS/FAIL per row).
- Tradeoff: expects go stale when the user changes intent → amendments must update `expect:` in the same turn the user redefines the task.

### P5 — Close semantics
Close types: `done` (evidence) · `closed-on-user-word` (record "unverified" if no evidence) · `superseded` (link successor) · `abandoned` · `external` (someone else finished — record who/what).
User's word always ends the tracking obligation, but the close line MUST record: ts, type, evidence-or-"unverified", links. Never self-close on "looks done" — flip to `awaiting-user` with evidence and keep reporting status.

### P6 — Tracker survival
Canonical file lives in `mono/scratch/` (survives session + /tmp wipes). Commit to lowkey-main on meaningful transitions → git history = free event log; a second session's edits surface as merge conflicts instead of silent clobber. Corrupt file → recover from git. Archive closed entries beyond ~2 weeks into `TASKS_ARCHIVE.md` to keep OPEN scannable.
- Tradeoff: commit noise on lowkey-main. Mitigate: batch commits (end of turn-cluster), 1-line messages.

## Recommended design — SKILL.md skeleton

```markdown
---
name: task-tracker
description: Maintain the user's open-task ledger (new/status/close protocol) with verify-before-status
---
# Task Tracker

File: `mono/scratch/PENDING_TASKS.md` (canonical; context is never canonical). Sections: `## OPEN`, `## LOG` (append-only), archive file `TASKS_ARCHIVE.md`. Single writer: the main session only. UTC everywhere.

## On session start / after compaction
Read OPEN fully. Do not trust remembered state; entries are self-contained (def, verify, resume, artifacts).

## Classify every user message
new task | status(task?) | close(task). Ambiguous → status of the most relevant open task; NEVER start new work on an ambiguous message.

## New task
1. Assign `T-NN-slug`. Write entry: opened, def (user's words), state, owner, verify:, expect: (if watch), resume:, artifacts.
2. LOG "T-NN opened: <def>". 3. Execute. 4. On amendment: append `amended <ts>: <words>` + update expect/verify.

## Status
1. Generic "status" → one line per OPEN task; named task → detail.
2. For each state-bearing task run its `verify:` FIRST (table below). Report observed state, not remembered state. Stamp last_verified. Drift vs expect → ⚠️ + LOG.
3. Subagent-owned task: report only notified+artifact-backed results; a running agent = "running since <ts>", never predicted output.

## Close
1. Run verify if ≤30s; record close line in LOG: ts · type (done/user-word/superseded/abandoned/external) · evidence or "unverified" · links. 2. Move entry to archive. 3. Superseded → link successor id.

## Subagent completion/death
Notification → main writes results+artifacts into the entry. Death → keep entry open, state=blocked, resume: recipe intact; ask/decide respawn. Subagent prompts MUST require incremental writes to their own artifact file so death loses minutes, not the task.

## Verify-before-status table
| Task type | Recipe | Gotcha |
|---|---|---|
| PR | `gh pr view N --repo R --json state,mergeCommit,headRefOid` | late-pushed sha? ALSO `git merge-base --is-ancestor <sha> origin/main` |
| k8s deploy | deployment image + every consuming configmap + Argo app sync one-liner | verify ALL consumers, not the object you touched |
| Cloud Run eph | `gcloud run services describe` → latestReadyRevisionName + env vars | env-only revisions get replaced by next deploy |
| Flag sync | `gh run list --workflow sync-unleash.yml` (headSha!) + repo file grep | later sync can overwrite; check nothing synced after yours |
| Cron/monitor | last output + CronList alive | cron expires in 7d; subagent monitors die silently |
| Watch/drift | run verify, diff vs `expect:` | update expect when user changes intent |
| Doc/artifact | ls + mtime + grep the claimed content | subagents edit docs too — re-read before claiming |
```

Adjacent note (out of scope): the same `verify:` recipes double as the post-deploy checks memory already mandates (verify_deployed_image_sha).
