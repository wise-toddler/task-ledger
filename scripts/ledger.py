#!/usr/bin/env python3
"""Task ledger v2 — append-only events.jsonl, derived HOT.md/ARCHIVE.md, a 3-deep NOW stack over a task DAG."""
import argparse, datetime, json, os, re, subprocess, sys

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def _store_dir():
    """One store per repo, even from a linked worktree: resolve to the main checkout's skill dir."""
    if os.environ.get("LEDGER_HOME"):
        return os.environ["LEDGER_HOME"]
    try:
        common = subprocess.run(["git", "rev-parse", "--git-common-dir"], capture_output=True, text=True, cwd=SKILL_DIR).stdout.strip()
        if common:
            main_root = os.path.dirname(os.path.abspath(os.path.join(SKILL_DIR, common))) if not os.path.isabs(common) else os.path.dirname(common)
            cand = os.path.join(main_root, ".agents", "skills", "task-ledger", "out")
            if os.path.isdir(os.path.dirname(cand)):
                return cand
    except OSError:
        pass
    return os.path.join(SKILL_DIR, "out")

HOME = _store_dir()
EVENTS = os.path.join(HOME, "events.jsonl")
HOT = os.path.join(HOME, "HOT.md")
ARCHIVE = os.path.join(HOME, "ARCHIVE.md")
NOW_DEPTH = 3          # stack cap: 1 current + 2 interrupted
NEXT_SHOWN = 5
STALE_DAYS = 14        # waiting task untouched this long → poke
LAPSE_DAYS = 45        # cold task untouched this long → archive as lapsed (only via `sweep`)
BUCKETS = ("now", "next", "waiting", "cold")
PRIOS = ("P0", "P1", "P2", "")  # P0 = drop everything, P1 = this week, P2/blank = normal
PRIO_MARK = {"P0": "!! ", "P1": "!  ", "P2": "", "": ""}
ON = ("user", "ext")   # waiting reasons; also "delegated:<name>" and "watching[:<what>]"
ID = re.compile(r"^T\d+(?:\.\d+)*$")

def default_owner():
    """Who this session is: LEDGER_OWNER env, else <repo-basename>@<tty> mapped through out/owners.json aliases."""
    if os.environ.get("LEDGER_OWNER"):
        return os.environ["LEDGER_OWNER"]
    return _raw_owner()

def _owner_keys():
    """Candidate identity keys for this session, most stable first: sess:<id> (any Claude env var), then <repo>@<tty>."""
    keys = []
    sid = next((os.environ[k] for k in ("CLAUDE_CODE_BRIDGE_SESSION_ID", "CLAUDE_CODE_SESSION_ID", "CLAUDE_SESSION_ID") if os.environ.get(k)), "")
    if sid:
        keys.append("sess:" + sid[-8:])
    top = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True).stdout.strip() or os.getcwd()
    pid, tty = os.getpid(), ""
    for _ in range(8):  # walk up to the terminal that owns this session (Claude's tool shell has no tty of its own)
        r = subprocess.run(["ps", "-o", "ppid=,tty=", "-p", str(pid)], capture_output=True, text=True).stdout.split()
        if len(r) < 2:
            break
        pid, t = int(r[0]), r[1]
        if t not in ("??", "-", "?", ""):
            tty = t; break
        if pid <= 1:
            break
    keys.append(f"{os.path.basename(top)}@{tty or 'notty'}")
    return keys

def _aliases():
    try:
        return json.load(open(os.path.join(HOME, "owners.json")))
    except (OSError, ValueError):
        return {}

def _raw_owner():
    m = _aliases()
    keys = _owner_keys()
    for k in keys:
        if k in m:
            return m[k]
    return keys[0]

def ts():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M")

def today():
    return datetime.datetime.now(datetime.timezone.utc).date()

def sortkey(tid):
    return tuple(int(x) for x in tid[1:].split("."))

def parent_of(tid):
    return tid.rsplit(".", 1)[0] if "." in tid else None

# ---------- store ----------

def read_events():
    if not os.path.exists(EVENTS):
        return []
    out = []
    with open(EVENTS) as f:
        for n, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError as e:
                sys.exit(f"events.jsonl line {n} is not JSON ({e}); fix it by hand, nothing was written")
    return out

def append(events):
    os.makedirs(HOME, exist_ok=True)
    with open(EVENTS, "a") as f:
        for e in events:
            e.setdefault("ts", ts())
            e.setdefault("by", os.environ.get("LEDGER_BY", "main"))
            f.write(json.dumps(e, ensure_ascii=False) + "\n")

# ---------- replay ----------

def _evlist(v):
    """ev entries are one pointer each; split entries that were pasted with several URLs separated by spaces."""
    out = []
    for x in (v or []):
        out += [p for p in str(x).split() if p]
    return list(dict.fromkeys(out))

def new_task(tid, e):
    return {"id": tid, "title": e.get("title", ""), "def": e.get("def", ""), "deps": list(e.get("deps", [])),
            "repo": e.get("repo", ""), "verify": e.get("verify", ""), "ev": _evlist(e.get("ev", [])),
            "bucket": e.get("bucket", "next"), "on": e.get("on", ""), "until": e.get("until", ""), "owner": e.get("owner") or e.get("by", ""), "prio": e.get("prio", ""),
            "closed": None, "created": e["ts"], "last": e["ts"], "hist": [], "alias": e.get("alias", "")}

def replay(events):
    """Fold the log into {id: task}, the NOW stack (bottom→top) and id aliases (detach)."""
    tasks, stack, alias = {}, [], {}
    for e in events:
        t = e.get("type")
        tid = e.get("id")
        if t == "add":
            tasks[tid] = new_task(tid, e)
            if tasks[tid]["bucket"] == "now":
                stack.append(tid)
            continue
        if t == "alias":
            alias[e["old"]] = e["new"]
            continue
        task = tasks.get(tid)
        if task is None:
            continue  # tolerate a stray event; never crash the replay
        task["last"] = e["ts"]
        task["hist"].append(e)
        if t in ("log", "amend", "note"):
            pass
        elif t == "set":
            for k in ("title", "def", "repo", "verify", "owner", "prio"):
                if k in e:
                    task[k] = e[k]
            if "ev" in e:
                task["ev"] = _evlist(e["ev"])
            if "deps" in e:
                task["deps"] = list(e["deps"])
        elif t == "bucket":
            if task["bucket"] == "now" and tid in stack:
                stack.remove(tid)
            task["bucket"] = e["bucket"]
            task["on"] = e.get("on", "") if e["bucket"] == "waiting" else ""
            task["until"] = e.get("until", "") if e["bucket"] == "waiting" else ""
            if e["bucket"] == "now":
                stack.append(tid)
        elif t == "ack":
            task["until"] = e.get("until", "")
        elif t == "close":
            task["closed"] = {"ts": e["ts"], "type": e.get("ctype", "done"), "evidence": e.get("evidence", "")}
            if tid in stack:
                stack.remove(tid)
        elif t == "reopen":
            task["closed"] = None
            task["bucket"] = "next"
    return tasks, stack, alias

def load():
    ev = read_events()
    tasks, stack, alias = replay(ev)
    return ev, tasks, stack, alias

def resolve(tasks, alias, tid):
    while tid in alias:
        tid = alias[tid]
    if tid not in tasks:
        sys.exit(f"unknown task {tid}")
    return tid

def open_tasks(tasks):
    return {k: v for k, v in tasks.items() if not v["closed"]}

def children(tasks, tid, only_open=True):
    return sorted([k for k, v in tasks.items() if parent_of(k) == tid and (not only_open or not v["closed"])], key=sortkey)

def open_deps(tasks, tid):
    return [d for d in tasks[tid]["deps"] if d in tasks and not tasks[d]["closed"]]

def days_since(stamp):
    d = datetime.datetime.strptime(stamp[:10], "%Y-%m-%d").date()
    return (today() - d).days

# ---------- graph ----------

def graph(tasks):
    """deps edges + implicit child→parent edges (a parent is not done until its children are)."""
    g = {t: set(v["deps"]) for t, v in tasks.items()}
    for t in list(g):
        p = parent_of(t)
        if p and p in tasks:
            g.setdefault(p, set()).add(t)
    return g

def find_cycle(g):
    color, path = {}, []
    def dfs(u):
        color[u] = 1; path.append(u)
        for v in sorted(g.get(u, ())):
            if color.get(v) == 1:
                return path[path.index(v):] + [v]
            if not color.get(v) and (c := dfs(v)):
                return c
        color[u] = 2; path.pop(); return None
    for u in sorted(g):
        if not color.get(u) and (c := dfs(u)):
            return c
    return None

def check_deps(tasks, tid, deps):
    for d in deps:
        if d == tid:
            sys.exit(f"{tid} cannot depend on itself")
        if d not in tasks:
            sys.exit(f"unknown dep {d}")
    g = graph(tasks)
    g[tid] = set(deps) | {c for c in g if parent_of(c) == tid}
    if (p := parent_of(tid)) and p in tasks:
        g.setdefault(p, set()).add(tid)
    if c := find_cycle(g):
        sys.exit("cycle: " + " → ".join(c))

# ---------- rules ----------

def check_verify(cmd):
    if not cmd:
        return
    r = subprocess.run(["bash", "-n"], input=cmd, capture_output=True, text=True)
    if r.returncode:
        sys.exit(f"verify is not valid bash: {r.stderr.strip()}")

def check_push(tasks, stack, tid):
    t = tasks[tid]
    if t["closed"]:
        sys.exit(f"{tid} is closed; reopen first")
    if t["bucket"] == "waiting":
        sys.exit(f"{tid} is WAITING on {t['on']}; `promote {tid}` when it is actually yours again")
    if (p := parent_of(tid)) in tasks and not tasks[p]["closed"] and tasks[p]["bucket"] == "cold":
        sys.exit(f"{tid} sits under parked parent {p}; promote {p} first")
    if tid not in stack and len(stack) >= NOW_DEPTH:
        sys.exit(f"NOW is full ({', '.join(reversed(stack))}); pop or park one first")

def snapshot(tasks, stack):
    """One classification for hot/list/web: buckets + derived flags."""
    op = open_tasks(tasks)
    out = {"now": list(reversed(stack)), "next": [], "waiting": [], "cold": [], "pokes": [], "held": {}}
    for t in sorted(op, key=lambda x: (PRIOS.index(op[x]["prio"]) if op[x]["prio"] in PRIOS else 3, x and -int(op[x]["last"].replace("-", "").replace("T", "").replace(":", "")))):
        v = op[t]
        if v["bucket"] == "now":
            continue
        held = open_deps(tasks, t)
        if held:
            out["held"][t] = held
        out[v["bucket"] if v["bucket"] in out else "next"].append(t)
        if v["bucket"] == "waiting":
            due = (v["until"] and datetime.datetime.strptime(v["until"], "%Y-%m-%d").date() <= today())
            stale = not v["until"] and days_since(v["last"]) >= STALE_DAYS
            if due or stale:
                out["pokes"].append(t)
    return out

# ---------- render ----------

def short(s, n=58):
    s = s.replace("\n", " ")
    return s if len(s) <= n else s[: n - 1] + "…"

def last_line(t):
    h = [e for e in t["hist"] if e["type"] in ("log", "amend", "close", "bucket", "verify", "note")]
    if not h:
        return f"added {t['created'][5:16]}"
    e = h[-1]
    txt = e.get("text") or e.get("evidence") or (f"→ {e.get('bucket')}" if e["type"] == "bucket" else e["type"])
    return f"{e['ts'][5:16]} {short(txt, 48)}"

def row(tasks, snap, t, mark="  "):
    v = tasks[t]
    hold = f"  ← waits {' '.join(snap['held'][t])}" if t in snap["held"] else ""
    on = f"  ({v['on']}{', until ' + v['until'] if v['until'] else ''})" if v["bucket"] == "waiting" else ""
    return f"{mark}{t:<8} {PRIO_MARK.get(v['prio'], '')}{short(v['title'], 58 - len(PRIO_MARK.get(v['prio'], ''))):<58}{on}{hold}\n           last: {last_line(v)}"

def render_hot(tasks, stack):
    snap = snapshot(tasks, stack)
    op = open_tasks(tasks)
    lines = [f"# HOT · {ts()}Z · now {len(snap['now'])}/{NOW_DEPTH} · next {len(snap['next'])} · waiting {len(snap['waiting'])} ({len(snap['pokes'])} pokes due) · cold {len(snap['cold'])} · open {len(op)}" + (f" · P0 {sum(1 for v in op.values() if v['prio']=='P0')}" if any(v['prio']=='P0' for v in op.values()) else ""),
             f"_generated by `ledger` — do not edit; truth is events.jsonl · this session = {default_owner()}_", ""]
    lines.append("NOW")
    if not snap["now"]:
        lines.append("  (empty — `ledger push T<n>`)")
    for i, t in enumerate(snap["now"]):
        lines.append(row(tasks, snap, t, "▶ " if i == 0 else "  "))
    if len(snap["now"]) > 1:
        lines.append(f"  debt: {len(snap['now']) - 1} interrupted")
    lines.append("NEXT")
    for t in snap["next"][:NEXT_SHOWN]:
        lines.append(row(tasks, snap, t))
    if len(snap["next"]) > NEXT_SHOWN:
        lines.append(f"  +{len(snap['next']) - NEXT_SHOWN} more → `ledger list --bucket next`")
    if snap["pokes"]:
        lines.append("POKES DUE")
        for t in snap["pokes"]:
            v = tasks[t]
            age = f"{days_since(v['until'])}d overdue" if v["until"] else f"untouched {days_since(v['last'])}d"
            lines.append(f"  {t:<8} {short(v['title'])}  ({v['on']}, {age})")
    lines.append(f"+{len(snap['cold'])} cold · +{len(snap['waiting'])} waiting → `ledger list --all`")
    return "\n".join(lines) + "\n"

def render_archive(tasks):
    closed = sorted([v for v in tasks.values() if v["closed"]], key=lambda v: v["closed"]["ts"], reverse=True)
    lines = ["# ARCHIVE (closed, newest first) — `ledger show T<n>` for history, `ledger reopen T<n>` to resurrect", ""]
    for v in closed:
        c = v["closed"]
        lines.append(f"- {v['id']} {c['ts'][:10]} {c['type']} — {short(v['title'], 70)} — {short(c['evidence'], 90)}")
    return "\n".join(lines) + "\n"

def render(tasks, stack):
    os.makedirs(HOME, exist_ok=True)
    for path, text in ((HOT, render_hot(tasks, stack)), (ARCHIVE, render_archive(tasks))):
        tmp = path + ".tmp"
        open(tmp, "w").write(text)
        os.replace(tmp, path)

def commit(events):
    """Append events, re-render, print the hot view header. Every mutating command ends here."""
    append(events)
    _, tasks, stack, _ = load()
    render(tasks, stack)
    return tasks, stack

# ---------- ids ----------

def next_id(tasks, parent=None):
    if parent:
        kids = [k for k in tasks if parent_of(k) == parent]
        n = max((sortkey(k)[-1] for k in kids), default=0) + 1
        return f"{parent}.{n}"
    tops = [sortkey(k)[0] for k in tasks if "." not in k]
    return f"T{max(tops, default=0) + 1}"

# ---------- commands ----------

def cmd_hot(a):
    _, tasks, stack, _ = load()
    render(tasks, stack)
    print(open(HOT).read(), end="")

def cmd_list(a):
    _, tasks, stack, _ = load()
    snap = snapshot(tasks, stack)
    want = [a.bucket] if a.bucket else (list(BUCKETS) if a.all else ["now", "next"])
    for b in want:
        ids = [t for t in snap[b] if not a.owner or tasks[t]["owner"] == a.owner]
        print(f"{b.upper()} ({len(ids)})")
        for t in ids:
            print(row(tasks, snap, t, "▶ " if (b == "now" and t == snap["now"][0]) else "  ") if not a.q else f"  {t:<8} {short(tasks[t]['title'])}")
    if not a.all and not a.bucket:
        print(f"+{len(snap['waiting'])} waiting · +{len(snap['cold'])} cold → --all")

def cmd_show(a):
    _, tasks, _, alias = load()
    tid = resolve(tasks, alias, a.id)
    v = tasks[tid]
    # A closed task keeps its last bucket in the fold; the header must show the close, not that bucket.
    state = f"closed:{v['closed']['type']}" if v["closed"] else f"{v['bucket']}{':' + v['on'] if v['on'] else ''}"
    print(f"{tid} [{state}] {v['title']}")
    print(f"owner: {v['owner'] or '-'}" + (f"   prio: {v['prio']}" if v['prio'] else ""))
    print(f"def: {v['def']}")
    for k in ("deps", "repo", "verify", "ev", "until", "alias"):
        if v[k]:
            print(f"{k}: {' '.join(v[k]) if isinstance(v[k], list) else v[k]}")
    if v["closed"]:
        print(f"closed: {v['closed']['ts']} {v['closed']['type']} — {v['closed']['evidence']}")
    kids, blocks = children(tasks, tid), [k for k, w in tasks.items() if tid in w["deps"] and not w["closed"]]
    if kids:
        print(f"subtasks: {' '.join(kids)}")
    if blocks:
        print(f"blocks: {' '.join(blocks)}")
    print("history:")
    for e in v["hist"]:
        txt = e.get("text") or e.get("evidence") or json.dumps({k: x for k, x in e.items() if k not in ("ts", "id", "type", "by")}, ensure_ascii=False)
        print(f"  {e['ts']} {e['type']:<7} {txt}")

def cmd_add(a):
    _, tasks, stack, _ = load()
    parent = a.parent
    if parent and parent not in tasks:
        sys.exit(f"unknown parent {parent}")
    tid = next_id(tasks, parent)
    deps = a.after.split() if a.after else []
    check_deps(tasks | {tid: {"deps": deps, "closed": None}}, tid, deps)
    check_verify(a.verify)
    bucket = a.bucket or ("waiting" if a.on else "next")
    if bucket == "waiting" and not a.on:
        sys.exit("waiting needs --on user|ext|delegated:<name>|watching")
    if bucket == "now":
        check_push(tasks | {tid: {"closed": None, "bucket": "next"}}, stack, tid)
    e = {"type": "add", "id": tid, "title": a.title, "def": f"{a.desc or a.title} ({today()})", "deps": deps,
         "repo": a.repo or "", "verify": a.verify or "", "ev": a.ev or [], "bucket": bucket, "on": a.on or "", "until": a.until or "",
         "owner": a.owner or default_owner(), "prio": (a.prio or "").upper()}
    commit([e])
    print(tid)

def cmd_push(a):
    _, tasks, stack, alias = load()
    tid = resolve(tasks, alias, a.id)
    if tid == (stack[-1] if stack else None):
        print(f"{tid} already current"); return
    check_push(tasks, stack, tid)
    evs = []
    if tid in stack:  # bring an interrupted one back to top
        evs.append({"type": "bucket", "id": tid, "bucket": "next", "text": "re-top"})
    evs.append({"type": "bucket", "id": tid, "bucket": "now"})
    if (p := parent_of(tid)) in tasks and not tasks[p]["closed"] and tasks[p]["bucket"] == "cold":
        evs.insert(0, {"type": "bucket", "id": p, "bucket": "next", "text": f"pulled by push {tid}"})
    _, stack = commit(evs)
    print(f"current: {tid}" + (f"  (interrupted: {', '.join(reversed(stack[:-1]))})" if len(stack) > 1 else ""))

def do_close(tasks, stack, tid, ctype, evidence, cascade):
    kids = children(tasks, tid)
    if kids and not cascade:
        sys.exit(f"{tid} has open subtasks {' '.join(kids)}; close them or --cascade")
    evs = []
    for k in (kids if cascade else []):
        evs += do_close(tasks, stack, k, ctype, f"cascade from {tid}: {evidence}", True)
    evs.append({"type": "close", "id": tid, "ctype": ctype, "evidence": evidence})
    return evs

def unblocked_by(tasks, closed_ids):
    out = []
    for t, v in open_tasks(tasks).items():
        if t in closed_ids:
            continue
        if any(d in closed_ids for d in v["deps"]) and not open_deps(tasks, t):
            out.append(t)
    return out

def cmd_close(a):
    _, tasks, stack, alias = load()
    tid = resolve(tasks, alias, a.id)
    if tasks[tid]["closed"]:
        sys.exit(f"{tid} already closed")
    evs = do_close(tasks, stack, tid, a.type, a.evidence, a.cascade)
    closed_ids = {e["id"] for e in evs}
    tasks, stack = commit(evs)
    print(f"closed {' '.join(sorted(closed_ids, key=sortkey))}")
    if un := unblocked_by(tasks, closed_ids):
        print(f"unblocked: {' '.join(un)}")
    if stack:
        print(f"current: {stack[-1]}")

def cmd_pop(a):
    """Close the current task. The store is shared across sessions, so `pop T<n>` refuses if T<n> is not the top."""
    _, tasks, stack, alias = load()
    if not stack:
        sys.exit("NOW is empty")
    top = stack[-1]
    if a.id and resolve(tasks, alias, a.id) != top:
        sys.exit(f"current is {top} ({tasks[top]['title'][:50]}), not {a.id}; use `close {a.id}` or `pop {top}`")
    if not a.id:
        print(f"popping {top}: {tasks[top]['title'][:60]}")
    a.id = top
    cmd_close(a)

def cmd_peek(a):
    _, tasks, stack, _ = load()
    if not stack:
        print("NOW is empty"); return
    snap = snapshot(tasks, stack)
    print(row(tasks, snap, stack[-1], "▶ "))

def move(a, bucket, extra=None, text=""):
    _, tasks, stack, alias = load()
    tid = resolve(tasks, alias, a.id)
    if tasks[tid]["closed"]:
        sys.exit(f"{tid} is closed; reopen first")
    e = {"type": "bucket", "id": tid, "bucket": bucket, "text": text}
    e.update(extra or {})
    evs = [e]
    if bucket == "cold":
        for k in children(tasks, tid):
            if tasks[k]["bucket"] in ("now", "next"):
                evs.append({"type": "bucket", "id": k, "bucket": "cold", "text": f"parked with parent {tid}"})
    tasks, stack = commit(evs)
    print(f"{tid} → {bucket}" + (f" ({e.get('on')}{', until ' + e['until'] if e.get('until') else ''})" if bucket == "waiting" else ""))

def cmd_park(a):
    move(a, "cold", text=a.note or "")

def cmd_promote(a):
    _, tasks, _, alias = load()
    tid = resolve(tasks, alias, a.id)
    if (p := parent_of(tid)) in tasks and not tasks[p]["closed"] and tasks[p]["bucket"] == "cold":
        a2 = argparse.Namespace(id=p, note=f"pulled by promote {tid}")
        move(a2, "next", text=a2.note)
    move(a, "next", text=a.note or "")

def cmd_wait(a):
    on = a.on
    if not (on in ON or on.startswith("delegated:") or on.startswith("watching")):
        sys.exit("--on must be user | ext | delegated:<name> | watching[:<what>]")
    if a.until:
        datetime.datetime.strptime(a.until, "%Y-%m-%d")
    move(a, "waiting", {"on": on, "until": a.until or ""}, text=a.note or "")

def cmd_ack(a):
    _, tasks, _, alias = load()
    tid = resolve(tasks, alias, a.id)
    datetime.datetime.strptime(a.until, "%Y-%m-%d")
    commit([{"type": "ack", "id": tid, "until": a.until, "text": a.note or ""}])
    print(f"{tid} poke moved to {a.until}")

def cmd_reopen(a):
    _, tasks, _, alias = load()
    tid = resolve(tasks, alias, a.id)
    if not tasks[tid]["closed"]:
        sys.exit(f"{tid} is open")
    commit([{"type": "reopen", "id": tid, "text": a.note or ""}])
    print(f"{tid} → next")

def cmd_log(a):
    _, tasks, _, alias = load()
    tid = resolve(tasks, alias, a.id)
    commit([{"type": "log", "id": tid, "text": a.text}])
    print("ok")

def cmd_amend(a):
    _, tasks, _, alias = load()
    tid = resolve(tasks, alias, a.id)
    commit([{"type": "amend", "id": tid, "text": a.text}])
    print("ok")

def cmd_set(a):
    _, tasks, _, alias = load()
    tid = resolve(tasks, alias, a.id)
    e = {"type": "set", "id": tid}
    for k in ("title", "repo", "verify", "ev", "owner", "prio"):
        if getattr(a, k) is not None:
            e[k] = getattr(a, k).upper() if k == "prio" else getattr(a, k)
    if len(e) == 2:
        sys.exit("nothing to set")
    if "verify" in e:
        check_verify(e["verify"])
    commit([e])
    print("ok")

def cmd_dep(a):
    _, tasks, _, alias = load()
    tid = resolve(tasks, alias, a.id)
    deps = list(tasks[tid]["deps"])
    for d in a.add or []:
        d = resolve(tasks, alias, d)
        if d not in deps:
            deps.append(d)
    for d in a.rm or []:
        deps = [x for x in deps if x != d]
    check_deps(tasks, tid, deps)
    commit([{"type": "set", "id": tid, "deps": deps}])
    print(f"{tid} deps: {' '.join(deps) or '-'}")

def cmd_detach(a):
    """Promote a subtask to a top-level task: new id, alias kept, deps/children re-pointed."""
    _, tasks, _, alias = load()
    old = resolve(tasks, alias, a.id)
    if "." not in old:
        sys.exit(f"{old} is already top-level")
    v = tasks[old]
    new = next_id(tasks)
    evs = [{"type": "add", "id": new, "title": v["title"], "def": v["def"] + f" | detached from {old} {today()}", "deps": v["deps"],
            "repo": v["repo"], "verify": v["verify"], "ev": v["ev"], "bucket": v["bucket"], "on": v["on"], "until": v["until"], "alias": old, "owner": v["owner"]},
           {"type": "close", "id": old, "ctype": "superseded", "evidence": f"detached → {new}"},
           {"type": "alias", "old": old, "new": new}]
    for t, w in tasks.items():
        if old in w["deps"] and not w["closed"]:
            evs.append({"type": "set", "id": t, "deps": [new if d == old else d for d in w["deps"]]})
    for k in children(tasks, old):
        evs.append({"type": "log", "id": k, "text": f"parent {old} detached as {new}; re-add under it with `adopt` if still a subtask"})
    commit(evs)
    print(f"{old} → {new}")

def cmd_adopt(a):
    """Move a top-level task under a parent: new dotted id, alias kept."""
    _, tasks, _, alias = load()
    old = resolve(tasks, alias, a.id)
    parent = resolve(tasks, alias, a.parent)
    v = tasks[old]
    new = next_id(tasks, parent)
    evs = [{"type": "add", "id": new, "title": v["title"], "def": v["def"] + f" | adopted from {old} {today()}", "deps": v["deps"],
            "repo": v["repo"], "verify": v["verify"], "ev": v["ev"], "bucket": v["bucket"], "on": v["on"], "until": v["until"], "alias": old, "owner": v["owner"]},
           {"type": "close", "id": old, "ctype": "superseded", "evidence": f"adopted → {new}"},
           {"type": "alias", "old": old, "new": new}]
    for t, w in tasks.items():
        if old in w["deps"] and not w["closed"]:
            evs.append({"type": "set", "id": t, "deps": [new if d == old else d for d in w["deps"]]})
    commit(evs)
    print(f"{old} → {new}")

def cmd_prio(a):
    _, tasks, _, alias = load()
    tid = resolve(tasks, alias, a.id)
    pr = (a.prio or "").upper()
    if pr == "NONE":   # `none` clears the field; "" is the stored value
        pr = ""
    if pr not in PRIOS:
        sys.exit("prio must be P0 | P1 | P2 | none")
    commit([{"type": "set", "id": tid, "prio": pr, "text": a.note or ""}])
    print(f"{tid} prio → {pr or 'none'}")

def cmd_owner(a):
    """`owner` → this session's default; `owner rename OLD NEW` → re-tag every task; `owner list` → counts."""
    _, tasks, _, _ = load()
    if a.rename:
        old, new = a.rename
        evs = [{"type": "set", "id": t, "owner": new} for t, v in tasks.items() if v["owner"] == old]
        if not evs:
            sys.exit(f"no tasks owned by {old}")
        commit(evs); print(f"{old} → {new}: {len(evs)} tasks"); return
    if a.alias:
        os.makedirs(HOME, exist_ok=True)
        path = os.path.join(HOME, "owners.json")
        m = _aliases()
        keys = _owner_keys()  # write every key this session can be seen as, so env/tty drift still resolves
        for k in keys:
            m[k] = a.alias
        json.dump(m, open(path, "w"), indent=1)
        print(f"{' + '.join(keys)} → {a.alias}"); return
    if a.list:
        from collections import Counter
        c = Counter(v["owner"] or "-" for v in open_tasks(tasks).values())
        for o, n in c.most_common(): print(f"{n:4}  {o}")
        return
    print(default_owner())

def cmd_verify(a):
    _, tasks, _, alias = load()
    tid = resolve(tasks, alias, a.id)
    v = tasks[tid]
    if not v["verify"]:
        sys.exit(f"{tid} has no verify: line")
    cwd = v["repo"] or os.getcwd()
    r = subprocess.run(["bash", "-c", v["verify"]], cwd=cwd, capture_output=True, text=True, timeout=180)
    out = (r.stdout + r.stderr).strip()
    print(out or f"(exit {r.returncode}, no output)")
    append([{"type": "verify", "id": tid, "text": short(out, 300), "exit": r.returncode}])
    sys.exit(r.returncode)

def cmd_graph(a):
    _, tasks, stack, _ = load()
    op = open_tasks(tasks)
    style = {"now": "fill:#ffd166", "next": "fill:#c7f9cc", "waiting": "fill:#e0e0e0", "cold": "fill:#f4f4f4,stroke-dasharray:3"}
    print("graph TD")
    for t, v in sorted(op.items(), key=lambda kv: sortkey(kv[0])):
        print(f'  {t.replace(".", "_")}["{t} {short(v["title"], 34)}"]')
        print(f"  style {t.replace('.', '_')} {style[v['bucket']]}")
    for t, v in op.items():
        for d in v["deps"]:
            if d in op:
                print(f"  {d.replace('.', '_')} --> {t.replace('.', '_')}")
        if (p := parent_of(t)) in op:
            print(f"  {p.replace('.', '_')} -.-> {t.replace('.', '_')}")

def cmd_sweep(a):
    """Time rules: cold untouched ≥ LAPSE_DAYS → lapsed (recoverable). Dry by default."""
    _, tasks, stack, _ = load()
    evs = []
    for t, v in open_tasks(tasks).items():
        if v["bucket"] == "cold" and days_since(v["last"]) >= LAPSE_DAYS and not children(tasks, t):
            evs.append({"type": "close", "id": t, "ctype": "lapsed", "evidence": f"cold untouched {days_since(v['last'])}d"})
    for e in evs:
        print(f"{'would lapse' if not a.apply else 'lapsed'} {e['id']}: {e['evidence']}")
    if a.apply and evs:
        commit(evs)
    if not evs:
        print("nothing to sweep")

# ---------- import from v1 markdown ----------

V1_BLOCK = re.compile(r"^### (T\d+(?:\.\d+)*) \[([^\]]+)\] (.+?)\n(.*?)(?=^### |^## |\Z)", re.M | re.S)
V1_LOG = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}) (T\d+(?:\.\d+)*) (.*)$", re.M)
V1_CLOSED = re.compile(r"^- (T\d+(?:\.\d+)*) (.*)$", re.M)

def v1_field(body, key):
    m = re.search(rf"^{key}: (.*)$", body, re.M)
    return m.group(1) if m else ""

def v1_bucket(state, layer):
    s = state.split("(")[0]
    if s.startswith("blocked:user"):
        return "waiting", "user", ""
    if s.startswith("blocked:ext"):
        return "waiting", "ext", ""
    if s.startswith("delegated"):
        return "waiting", s if ":" in s else "delegated:?", ""
    if s.startswith("watching"):
        return "waiting", "watching", ""
    if layer == "3":
        return "cold", "", ""
    return "next", "", ""

def cmd_import(a):
    if os.path.exists(EVENTS) and not a.force:
        sys.exit(f"{EVENTS} exists; --force to append an import anyway")
    text = "\n".join(open(p).read() for p in a.files)
    evs, seen = [], set()
    for m in V1_BLOCK.finditer(text):
        tid, state, title, body = m.group(1), m.group(2), m.group(3).strip(), m.group(4)
        if tid in seen:
            continue
        seen.add(tid)
        d = v1_field(body, "def")
        parts = [p.strip() for p in re.split(r"\s*\|\s*amended\s*", d)]
        head, amends = parts[0], parts[1:]
        created = (re.search(r"\((\d{4}-\d{2}-\d{2})\)", head) or [None, "2026-08-27"])[1]
        bucket, on, until = v1_bucket(state, v1_field(body, "layer"))
        deps = [x for x in v1_field(body, "deps").replace(",", " ").split() if x]
        ev = [x for x in v1_field(body, "ev").split() if x][:2]
        evs.append({"ts": created + "T00:00", "type": "add", "id": tid, "title": title, "def": head, "deps": deps, "repo": "",
                    "verify": v1_field(body, "verify") if v1_field(body, "verify") not in ("", "-") else "", "ev": ev,
                    "bucket": bucket, "on": on, "until": until, "by": "import"})
        for am in amends:
            evs.append({"ts": created + "T00:01", "type": "amend", "id": tid, "text": am, "by": "import"})
        for k in ("now", "next", "expect"):
            if val := v1_field(body, k):
                evs.append({"ts": created + "T00:02", "type": "log", "id": tid, "text": f"{k}: {val}", "by": "import"})
    open_ids = set(seen)
    for m in V1_CLOSED.finditer(text):
        tid, rest = m.group(1), m.group(2)
        if tid in seen:
            evs.append({"ts": "2026-08-27T00:00", "type": "close", "id": tid, "ctype": "done", "evidence": short(rest, 200), "by": "import"})
            continue
        seen.add(tid)
        evs.append({"ts": "2026-08-27T00:00", "type": "add", "id": tid, "title": short(rest, 80), "def": rest, "deps": [], "bucket": "next", "by": "import"})
        evs.append({"ts": "2026-08-27T00:00", "type": "close", "id": tid, "ctype": "done", "evidence": short(rest, 200), "by": "import"})
    for m in V1_LOG.finditer(text):
        stamp, tid, msg = m.groups()
        if tid in seen:
            evs.append({"ts": stamp, "type": "log", "id": tid, "text": msg, "by": "import"})
    # dangling deps (closed in an archive we did not get) → drop with a log line
    known = {e["id"] for e in evs if e["type"] == "add"}
    for e in evs:
        if e["type"] == "add" and (bad := [d for d in e["deps"] if d not in known]):
            e["deps"] = [d for d in e["deps"] if d in known]
            evs.append({"ts": e["ts"], "type": "log", "id": e["id"], "text": f"import dropped unknown deps {' '.join(bad)}", "by": "import"})
    evs.sort(key=lambda e: (e["ts"], 0 if e["type"] == "add" else 1))
    for e in evs:
        if e["type"] == "close":  # a close must come after the task's other events
            e["ts"] = max(e["ts"], max((x["ts"] for x in evs if x["id"] == e["id"] and x["type"] != "close"), default=e["ts"]))
    evs.sort(key=lambda e: (e["ts"], 0 if e["type"] == "add" else 1))
    tasks, stack = commit(evs)
    op = open_tasks(tasks)
    print(f"imported {len(known)} tasks ({len(op)} open, {len(known) - len(op)} closed), {len(evs)} events")
    tsv = os.path.join(HOME, "migration_restate.tsv")
    with open(tsv, "w") as f:
        f.write("id\ttitle\tbucket_now\tbucket_new\ton\tuntil\tnote\n")
        for t in sorted(op, key=sortkey):
            v = op[t]
            f.write(f"{t}\t{v['title']}\t{v['bucket']}\t{v['bucket']}\t{v['on']}\t\t\n")
    print(f"re-state sheet: {tsv} (edit bucket_new/on/until; `lapse` in bucket_new closes as lapsed; then `ledger restate {tsv}`)")

def cmd_restate(a):
    _, tasks, _, alias = load()
    evs = []
    for line in open(a.file).read().splitlines()[1:]:
        if not line.strip():
            continue
        cols = (line.split("\t") + [""] * 7)[:7]
        tid, _, cur, new, on, until, note = cols
        tid = resolve(tasks, alias, tid)
        if new == "lapse":
            evs.append({"type": "close", "id": tid, "ctype": "lapsed", "evidence": note or "migration re-state"})
        elif new and new != cur:
            if new not in BUCKETS:
                sys.exit(f"{tid}: bad bucket {new}")
            if new == "waiting" and not on:
                sys.exit(f"{tid}: waiting needs on")
            evs.append({"type": "bucket", "id": tid, "bucket": new, "on": on, "until": until, "text": note or "migration re-state"})
        elif new == "waiting" and (on or until):
            evs.append({"type": "bucket", "id": tid, "bucket": "waiting", "on": on, "until": until, "text": note or "migration re-state"})
    if not evs:
        print("no changes"); return
    tasks, stack = commit(evs)
    print(f"applied {len(evs)} changes; now {len(stack)}/{NOW_DEPTH}")

# ---------- main ----------

def main():
    ap = argparse.ArgumentParser(prog="ledger", description=__doc__)
    sp = ap.add_subparsers(dest="cmd")
    sp.add_parser("hot", help="the bounded hot view (default)").set_defaults(f=cmd_hot)
    p = sp.add_parser("list"); p.add_argument("--all", action="store_true"); p.add_argument("--bucket", choices=BUCKETS); p.add_argument("--owner"); p.add_argument("-q", action="store_true"); p.set_defaults(f=cmd_list)
    p = sp.add_parser("show"); p.add_argument("id"); p.set_defaults(f=cmd_show)
    p = sp.add_parser("add"); p.add_argument("title"); p.add_argument("--desc"); p.add_argument("--owner", help="default: $LEDGER_OWNER or <repo>@<tty>"); p.add_argument("--prio", choices=["P0", "P1", "P2", "p0", "p1", "p2"]); p.add_argument("--after", help="space-separated dep ids"); p.add_argument("--parent")
    p.add_argument("--repo"); p.add_argument("--verify"); p.add_argument("--ev", action="append"); p.add_argument("--bucket", choices=BUCKETS); p.add_argument("--on"); p.add_argument("--until"); p.set_defaults(f=cmd_add)
    p = sp.add_parser("push"); p.add_argument("id"); p.set_defaults(f=cmd_push)
    p = sp.add_parser("pop", help="close the current task (pass its id to guard against another session's push)"); p.add_argument("id", nargs="?"); p.add_argument("--type", default="done", choices=["done", "user-word", "superseded", "abandoned", "external"]); p.add_argument("--evidence", required=True); p.add_argument("--cascade", action="store_true"); p.set_defaults(f=cmd_pop)
    sp.add_parser("peek").set_defaults(f=cmd_peek)
    p = sp.add_parser("close"); p.add_argument("id"); p.add_argument("--type", default="done", choices=["done", "user-word", "superseded", "abandoned", "external", "lapsed"]); p.add_argument("--evidence", required=True); p.add_argument("--cascade", action="store_true"); p.set_defaults(f=cmd_close)
    p = sp.add_parser("park"); p.add_argument("id"); p.add_argument("--note"); p.set_defaults(f=cmd_park)
    p = sp.add_parser("promote", help="cold/waiting → next"); p.add_argument("id"); p.add_argument("--note"); p.set_defaults(f=cmd_promote)
    p = sp.add_parser("wait"); p.add_argument("id"); p.add_argument("--on", required=True); p.add_argument("--until"); p.add_argument("--note"); p.set_defaults(f=cmd_wait)
    p = sp.add_parser("ack", help="poke seen; next poke date"); p.add_argument("id"); p.add_argument("--until", required=True); p.add_argument("--note"); p.set_defaults(f=cmd_ack)
    p = sp.add_parser("reopen"); p.add_argument("id"); p.add_argument("--note"); p.set_defaults(f=cmd_reopen)
    p = sp.add_parser("log"); p.add_argument("id"); p.add_argument("text"); p.set_defaults(f=cmd_log)
    p = sp.add_parser("amend"); p.add_argument("id"); p.add_argument("text"); p.set_defaults(f=cmd_amend)
    p = sp.add_parser("set"); p.add_argument("id"); p.add_argument("--title"); p.add_argument("--repo"); p.add_argument("--verify"); p.add_argument("--ev", action="append"); p.add_argument("--owner"); p.add_argument("--prio"); p.set_defaults(f=cmd_set)
    p = sp.add_parser("dep"); p.add_argument("id"); p.add_argument("--add", nargs="+"); p.add_argument("--rm", nargs="+"); p.set_defaults(f=cmd_dep)
    p = sp.add_parser("detach", help="subtask → top-level task"); p.add_argument("id"); p.set_defaults(f=cmd_detach)
    p = sp.add_parser("adopt", help="top-level task → subtask of --parent"); p.add_argument("id"); p.add_argument("--parent", required=True); p.set_defaults(f=cmd_adopt)
    p = sp.add_parser("prio", help="P0 (drop everything) | P1 (this week) | P2/none"); p.add_argument("id"); p.add_argument("prio"); p.add_argument("--note"); p.set_defaults(f=cmd_prio)
    p = sp.add_parser("owner", help="show this session's owner; --rename OLD NEW; --list"); p.add_argument("--rename", nargs=2, metavar=("OLD", "NEW")); p.add_argument("--list", action="store_true"); p.add_argument("--alias", metavar="NAME", help="name this terminal session (stored in out/owners.json)"); p.set_defaults(f=cmd_owner)
    p = sp.add_parser("verify"); p.add_argument("id"); p.set_defaults(f=cmd_verify)
    sp.add_parser("graph", help="mermaid DAG of open tasks").set_defaults(f=cmd_graph)
    p = sp.add_parser("sweep", help="apply time rules"); p.add_argument("--apply", action="store_true"); p.set_defaults(f=cmd_sweep)
    p = sp.add_parser("import", help="v1 PENDING_TASKS.md (+archive) → events"); p.add_argument("files", nargs="+"); p.add_argument("--force", action="store_true"); p.set_defaults(f=cmd_import)
    p = sp.add_parser("restate"); p.add_argument("file"); p.set_defaults(f=cmd_restate)
    a = ap.parse_args()
    if not a.cmd:
        a.f = cmd_hot
    a.f(a)

if __name__ == "__main__":
    main()
