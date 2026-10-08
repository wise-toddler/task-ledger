# task-ledger

A Claude Code skill: an append-only task ledger (`events.jsonl`) with a NOW stack, NEXT / WAITING / COLD buckets, deps, subtasks and a read-only web view. Protocol and commands are in `SKILL.md`.

## Install

Clone into the skills dir of any checkout (or `~/.claude/skills` for every project):

```bash
git clone git@github.com:wise-toddler/task-ledger.git .claude/skills/task-ledger
python3 .claude/skills/task-ledger/scripts/ledger.py hot
```

`out/` (the store) is gitignored and lives inside the skill dir. Back it up separately; a checkout operation that replaces the dir (branch switch, dir to symlink) deletes it.

## Layout

- `SKILL.md`: protocol, buckets, commands
- `scripts/ledger.py`: the CLI (`hot`, `add`, `push`, `pop`, `close`, `wait`, `verify`, ...)
- `scripts/ledger_web.py`: live read-only view (`--port 9099 --open`)
- `scripts/verify_recipes.sh`: canned verify one-liners
- `scripts/ledger_v1.py`: reader for the old markdown ledger
- `references/`: design notes (v2 proposal, DAG design, operator and robustness lenses)
