#!/usr/bin/env python3
"""Task-ledger CLI for scratch/PENDING_TASKS.md — list/ready/show/add/mutate/close/log/verify, with a task DAG."""
import argparse, datetime, os, re, subprocess, sys

ROOT = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True).stdout.strip() or "."
FILE = os.environ.get("LEDGER_FILE", os.path.join(ROOT, "scratch", "PENDING_TASKS.md"))
ARCHIVE = FILE.replace(".md", "_ARCHIVE.md")
now = lambda: datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M")

ID = r"T\d+(?:\.\d+)*"
BLOCK = re.compile(rf"^### ({ID}) \[([^\]]+)\] (.+?)\n(.*?)(?=^### |^## |\Z)", re.M | re.S)
CLOSED_ROW = re.compile(rf"^- ({ID}) ", re.M)
LAYERS = (1, 2, 3)  # 1 = working it now · 2 = this cycle · 3 = parked/eventual
DEFAULT_LAYER = 2  # a block with no layer: line (legacy or hand-written) is near-term — the filter must never hide work
HEAD = ("def", "layer", "deps")  # structural lines, kept in this order directly under the title

def read():
    return open(FILE).read() if os.path.exists(FILE) else "## OPEN\n\n## CLOSED\n\n## LOG\n"

def write(s):
    open(FILE, "w").write(s)

def blocks(s):
    return [(m.group(1), m.group(2), m.group(3), m.group(4).rstrip("\n"), m.span()) for m in BLOCK.finditer(s)]

def closed_ids(s):
    sec = s.split("## CLOSED\n", 1)[1].split("\n## ", 1)[0] if "## CLOSED\n" in s else ""
    return set(CLOSED_ROW.findall(sec))

def field(body, key):
    m = re.search(rf"^{key}: (.*)$", body, re.M)
    return m.group(1) if m else ""

def set_field(body, key, val):
    if re.search(rf"^{key}:", body, re.M):
        return re.sub(rf"^{key}: .*$", f"{key}: {val}", body, flags=re.M)
    if key in HEAD:  # structural — sits under def:, in HEAD order
        prev = [k for k in HEAD[: HEAD.index(key)] if re.search(rf"^{k}:", body, re.M)]
        if not prev:
            return f"{key}: {val}\n" + body
        return re.sub(rf"^({prev[-1]}: .*)$", rf"\1\n{key}: {val}", body, count=1, flags=re.M)
    return body + f"\n{key}: {val}"

def deps_of(body):
    return [d for d in field(body, "deps").replace(",", " ").split() if d]

def layer_of(body):
    """1/2/3 — how near-term this task is; a block with no layer: line reads as DEFAULT_LAYER."""
    m = re.search(r"^layer: *(\d+)", body, re.M)
    n = int(m.group(1)) if m else DEFAULT_LAYER
    return n if n in LAYERS else DEFAULT_LAYER

def parent_of(tid):
    return tid.rsplit(".", 1)[0] if "." in tid else None

def sortkey(tid):
    return tuple(int(x) for x in tid[1:].split("."))

def log_line(s, tid, msg):
    if "## LOG" not in s:
        s += "\n## LOG\n"
    return s.replace("## LOG\n", f"## LOG\n{now()} {tid} {msg}\n", 1)

# ---------- graph ----------

def graph(bl):
    """dep edges + implicit child→parent edges (a parent is not done until its children are)."""
    g = {t: set(deps_of(b)) for t, _, _, b, _ in bl}
    for t in list(g):
        p = parent_of(t)
        if p:
            g.setdefault(p, set()).add(t)
    return g

def find_cycle(g):
    color, stack = {}, []
    def dfs(u):
        color[u] = 1
        stack.append(u)
        for v in sorted(g.get(u, ())):
            if color.get(v) == 1:
                return stack[stack.index(v):] + [v]
            if not color.get(v) and (c := dfs(v)):
                return c
        color[u] = 2; stack.pop(); return None
    for u in sorted(g):
        if not color.get(u) and (c := dfs(u)):
            return c
    return None

def check_deps(bl, tid, deps, known):
    """Reject dangling deps, self-deps and cycles before any write."""
    for d in deps:
        if d == tid:
            sys.exit(f"{tid} cannot depend on itself")
        if d not in known:
            sys.exit(f"unknown dep {d} — no such task in OPEN or CLOSED")
    g = graph(bl)
    g[tid] = set(deps) | {c for c in g if parent_of(c) == tid}
    if p := parent_of(tid):
        g.setdefault(p, set()).add(tid)
    if c := find_cycle(g):
        sys.exit("cycle: " + " → ".join(c))

def dep_forest(bl, open_ids):
    """open deps per task + the chain parent (its latest open dep = the one that unblocks it last)."""
    open_deps = {t: sorted([d for d in deps_of(b) if d in open_ids], key=sortkey) for t, _, _, b, _ in bl}
    chain = {}
    for t, ds in open_deps.items():
        if ds:
            chain.setdefault(ds[-1], []).append(t)
    return open_deps, {t: sorted(v, key=sortkey) for t, v in chain.items()}

def layer_warnings(idx, lay, open_ids):
    """A task cannot be nearer-term than what gates it: its open deps, or the parent thread it sits in."""
    out = []
    for t in sorted(open_ids, key=sortkey):
        for d in deps_of(idx[t]["body"]):
            if d in open_ids and lay[d] > lay[t]:
                out.append(f"layer inversion: {t} (L{lay[t]}) waits on {d} (L{lay[d]}) — promote {d} or park {t}")
        if (p := parent_of(t)) in open_ids and lay[p] > lay[t]:
            out.append(f"layer inversion: {t} (L{lay[t]}) sits under parked parent {p} (L{lay[p]})")
    return out

def buckets(bl, closed):
    """The one classification both consumers read — render() prints it, ledger_web.py serves it as JSON."""
    idx = {t: {"state": st, "title": ti, "body": b} for t, st, ti, b, _ in bl}
    open_ids, known = set(idx), set(idx) | closed
    kids = {t: sorted([c for c in open_ids if parent_of(c) == t], key=sortkey) for t in open_ids}
    open_deps, chain = dep_forest(bl, open_ids)
    tops = [t for t, *_ in bl if parent_of(t) not in open_ids]
    topset = set(tops)
    chain = {k: [c for c in v if c in topset] for k, v in chain.items() if k in topset}  # subtasks nest under their parent instead
    lay = {t: layer_of(idx[t]["body"]) for t in open_ids}

    b = {"needs": [], "ready": [], "flight": [], "waiting": [], "ext": []}
    for t in tops:
        st, body = idx[t]["state"], idx[t]["body"]
        if open_deps[t]:
            b["waiting"].append(t)
        elif st.startswith("blocked:user"):
            b["needs"].append(t)
        elif st.startswith("blocked:") and not deps_of(body):
            b["ext"].append(t)
        elif st.startswith("delegated") or st.startswith("watching"):
            b["flight"].append(t)
        else:
            b["ready"].append(t)
    for k in b:
        b[k].sort(key=lambda t: lay[t])  # stable — layer first, file order within a layer

    warn = [f"{t} deps on unknown {d}" for t, _, _, body, _ in bl for d in deps_of(body) if d not in known]
    if dup := sorted(open_ids & closed, key=sortkey):
        warn.append("ids present in both OPEN and CLOSED (OPEN wins): " + ", ".join(dup))
    if cyc := find_cycle(graph(bl)):
        warn.append("cycle: " + " → ".join(cyc))
    warn += layer_warnings(idx, lay, open_ids)
    return {"idx": idx, "kids": kids, "open_deps": open_deps, "chain": chain, "tops": tops, "layer": lay,
            "order": b, "roots": sorted([r for r in chain if not open_deps.get(r)], key=sortkey), "warnings": warn}

# ---------- rendering ----------

def trunc(s, n):
    return s if len(s) <= n else s[: n - 1] + "…"

def state_short(st):
    return trunc(st, 14)

def row(tid, state, lay, title, indent, mark=""):
    print(f"{' ' * indent}{tid:<8} {state_short(state):<14} L{lay} {trunc(title, 74 - len(mark))}{mark}")

def layer_filter(bl, show):
    """Filter whole threads, never pieces: a thread survives iff its top-level layer is shown — or something
    shown still waits on it (a blocker you can't see is worse than a parked task you didn't ask for)."""
    body_of = {t: b for t, _, _, b, _ in bl}
    def root(t):
        while (p := parent_of(t)) in body_of:
            t = p
        return t
    tops = [t for t in body_of if parent_of(t) not in body_of]
    keep = {t for t in tops if layer_of(body_of[t]) in show}
    pend = [t for t in body_of if root(t) in keep]
    while pend:
        for d in deps_of(body_of[pend.pop()]):
            if d in body_of and root(d) not in keep:
                keep.add(root(d))
                pend += [t for t in body_of if root(t) == root(d)]
    return [x for x in bl if root(x[0]) in keep], len([t for t in tops if t not in keep])

def render(bl, closed, mode, hidden=0):
    B = buckets(bl, closed)
    idx, kids, open_deps, chain, lay = B["idx"], B["kids"], B["open_deps"], B["chain"], B["layer"]

    def kidrows(tid, indent):
        for c in kids[tid]:
            mark = " ← " + " ".join(open_deps[c]) if open_deps[c] else ""
            row(c, idx[c]["state"], lay[c], idx[c]["title"], indent, mark)
            kidrows(c, indent + 2)

    def emit(header, ids, shownow=False):
        if not ids:
            return
        print(f"\n{header} ({len(ids)})")
        for t in ids:
            st, ti, b = idx[t]["state"], idx[t]["title"], idx[t]["body"]
            stale = " ⚠ deps clear" if st.startswith("blocked:") and deps_of(b) and not open_deps[t] else ""
            row(t, st, lay[t], ti, 2, stale)
            if shownow and mode == "full" and (n := field(b, "now")):
                print(f"{' ' * 11}now: {trunc(n, 90)}")
            kidrows(t, 4)

    emit("NEEDS YOU", B["order"]["needs"])
    emit("READY", B["order"]["ready"], shownow=True)
    emit("IN FLIGHT", B["order"]["flight"], shownow=True)
    if B["order"]["waiting"]:
        print(f"\nWAITING ON A TASK ({len(B['order']['waiting'])})")
        def walk(t, indent):
            for c in chain.get(t, []):
                extra = [d for d in open_deps[c] if d != t]
                row(c, idx[c]["state"], lay[c], idx[c]["title"], indent, f"  (+{' '.join(extra)})" if extra else "")
                kidrows(c, indent + 2)
                walk(c, indent + 2)
        for t in B["roots"]:
            print(f"  ← {t} [{state_short(idx[t]['state'])}] L{lay[t]} {trunc(idx[t]['title'], 66)}")
            walk(t, 4)
    emit("WAITING ON EXTERNAL", B["order"]["ext"])

    if hidden:
        print(f"\n{hidden} top-level task(s) hidden by the layer filter — `ledger.py list --all`")
    for w in B["warnings"]:
        print(f"\n⚠ {w}")

def render_tree(bl):
    idx = {t: (st, ti) for t, st, ti, _, _ in bl}
    lay = {t: layer_of(b) for t, _, _, b, _ in bl}
    open_ids = set(idx)
    open_deps, chain = dep_forest(bl, open_ids)
    seen = set()

    def walk(t, indent, via=None):
        st, ti = idx[t]
        seen.add(t)
        rest = [d for d in open_deps[t] if d != via]  # deps other than the node it hangs from
        row(t, st, lay[t], ti, indent, f"  ← {' '.join(rest)}" if rest else "")
        for c in sorted([c for c in open_ids if parent_of(c) == t], key=sortkey):
            if c not in seen:
                walk(c, indent + 2)
        for d in chain.get(t, []):  # subtasks hang under their parent, never twice
            if d not in seen and parent_of(d) not in open_ids:
                walk(d, indent + 2, via=t)

    for t, *_ in bl:
        if t not in seen and not open_deps[t] and parent_of(t) not in open_ids:
            walk(t, 0)
    for t, *_ in bl:  # cycle survivors / orphans
        if t not in seen:
            walk(t, 0)

# ---------- commands ----------

def cmd_list(a):
    s = read(); bl = blocks(s)
    show = set(LAYERS) if getattr(a, "all", False) else ({a.layer} if getattr(a, "layer", None) else {1, 2})
    if getattr(a, "layer", None) and a.layer not in LAYERS:
        sys.exit(f"--layer must be one of {LAYERS}")
    bl, hidden = layer_filter(bl, show)
    if getattr(a, "tree", False):
        return render_tree(bl)
    if getattr(a, "ready", False):  # nothing in the graph holds it back, and no purely-external wait
        ids = {t for t, *_ in bl}
        st_of = {t: st for t, st, *_ in bl}
        body_of = {t: b for t, _, _, b, _ in bl}
        def held(t):  # a piece of a held thread is held too — never re-root a subtask as a top-level task
            while t in ids:
                if [d for d in deps_of(body_of[t]) if d in ids] or (
                        st_of[t].startswith("blocked:ext") and not deps_of(body_of[t])):
                    return True
                t = parent_of(t)
            return False
        bl = [x for x in bl if not held(x[0])]
    render(bl, closed_ids(s), "quiet" if a.q else "full", hidden)

def cmd_ready(a):
    a.tree, a.ready = False, True
    cmd_list(a)

def cmd_show(a):
    s = read(); bl = blocks(s)
    for tid, state, title, body, _ in bl:
        if tid == a.id:
            blocks_ = sorted([t for t, _, _, b, _ in bl if tid in deps_of(b)], key=sortkey)
            kids = sorted([t for t, *_ in bl if parent_of(t) == tid], key=sortkey)
            print(f"### {tid} [{state}] {title}\n{body}")
            if not re.search(r"^layer:", body, re.M): print(f"layer: {layer_of(body)} (default — no layer: line)")
            if blocks_: print(f"blocks: {' '.join(blocks_)}")
            if kids: print(f"subtasks: {' '.join(kids)}")
            return
    sys.exit(f"{a.id} not found")

def check_layer(n, flag):
    if n is not None and n not in LAYERS:
        sys.exit(f"{flag} must be one of {LAYERS} (1 = now, 3 = parked)")

def warn_layers(tid=None):
    s = read()
    for w in buckets(blocks(s), closed_ids(s))["warnings"]:
        if w.startswith("layer inversion") and (tid is None or tid in w):
            print("⚠ " + w)

def cmd_add(a):
    s = read(); bl = blocks(s); closed = closed_ids(s)
    ids = {t for t, *_ in bl} | closed
    deps = [d for x in (a.after or []) for d in x.replace(",", " ").split()]
    check_layer(a.layer, "--layer")
    lay = a.layer
    if a.parent:
        if a.parent not in {t for t, *_ in bl}:
            sys.exit(f"parent {a.parent} not found in OPEN")
        n = max([sortkey(t)[-1] for t in ids if parent_of(t) == a.parent] + [0]) + 1
        tid = f"{a.parent}.{n}"
        lay = lay or layer_of(next(b for t, _, _, b, _ in bl if t == a.parent))  # a piece starts as near-term as its thread
    lay = lay or DEFAULT_LAYER
    if not a.parent:
        tid = f"T{max([sortkey(t)[0] for t in ids] + [0]) + 1}"
    check_deps(bl, tid, deps, ids)
    blk = (f"### {tid} [{a.state}] {a.title}\ndef: {a.desc or a.title} ({now()})\nlayer: {lay}\n"
           + (f"deps: {' '.join(deps)}\n" if deps else "")
           + f"now: {a.now or 'started'}\nnext: {a.next or '-'}\nverify: {a.verify or '-'}\nev: {a.ev or '-'}\n\n")
    if a.parent:  # keep children next to their parent in the file
        span = [sp for t, _, _, _, sp in bl if t == a.parent][0]
        s = s[: span[1]] + blk + s[span[1]:]
    else:
        s = s.replace("## OPEN\n", "## OPEN\n" + blk, 1)
    write(log_line(s, tid, f"opened (L{lay}): {a.title}" + (f" (after {' '.join(deps)})" if deps else "")))
    print(tid)
    warn_layers(tid)

def _edit(a, fn, logmsg):
    s = read()
    for tid, state, title, body, span in blocks(s):
        if tid == a.id:
            nb = fn(state, title, body)
            s = s[: span[0]] + nb + s[span[1]:]
            write(log_line(s, tid, logmsg)); print("ok"); return
    sys.exit(f"{a.id} not found")

def cmd_mutate(a):
    s = read(); bl = blocks(s)
    cur = next((b for t, _, _, b, _ in bl if t == a.id), None)
    if cur is None:
        sys.exit(f"{a.id} not found")
    deps = deps_of(cur)
    if a.deps is not None:
        deps = a.deps.replace(",", " ").split()
    for x in a.add_dep or []:
        deps += [d for d in x.replace(",", " ").split() if d not in deps]
    for x in a.rm_dep or []:
        deps = [d for d in deps if d not in x.replace(",", " ").split()]
    if deps != deps_of(cur):
        check_deps([b for b in bl if b[0] != a.id], a.id, deps, {t for t, *_ in bl} | closed_ids(s))

    check_layer(a.layer, "--layer")

    def fn(state, title, body):
        st = a.state or state
        for k, v in (("layer", a.layer), ("now", a.now), ("next", a.next), ("verify", a.verify), ("ev", a.ev)):
            if v is not None:
                body = set_field(body, k, v)
        if deps != deps_of(body):
            body = set_field(body, "deps", " ".join(deps)) if deps else re.sub(r"^deps: .*\n?", "", body, flags=re.M).rstrip("\n")
        if a.amend:
            body = re.sub(r"^(def: .*)$", rf"\1 | amended {now()}: {a.amend}", body, count=1, flags=re.M)
        return f"### {a.id} [{st}] {a.title or title}\n{body}\n\n"

    _edit(a, fn, a.amend or (f"layer → L{a.layer}" if a.layer else None) or a.now
          or (f"deps → {' '.join(deps) or 'none'}" if deps != deps_of(cur) else "mutated"))
    warn_layers(a.id)

def _set_layer(s, tid, n):
    for t, st, ti, body, span in blocks(s):
        if t == tid:
            return s[: span[0]] + f"### {t} [{st}] {ti}\n{set_field(body, 'layer', n)}\n\n" + s[span[1]:]
    return s

def cmd_promote(a):
    """Pull a task nearer-term (3→2→1) — and with it whatever gates it, so no inversion is left behind."""
    s = read(); body = {t: b for t, _, _, b, _ in blocks(s)}
    if a.id not in body:
        sys.exit(f"{a.id} not found in OPEN")
    cur = layer_of(body[a.id])
    if a.to is None and cur == min(LAYERS):
        print(f"{a.id} already L{cur}")
        return
    target = a.to if a.to is not None else cur - 1
    check_layer(target, "--to")
    if target > cur:
        sys.exit(f"{a.id} is L{cur}; promote only moves toward L1 — park it with `mutate {a.id} --layer {target}`")
    if target == cur:
        print(f"{a.id} already L{cur}")
        return
    moves = {a.id: target}
    if not a.no_cascade:  # what a promoted task waits on (deps, parent thread) can't stay further out than it
        pend = [a.id]
        while pend:
            t = pend.pop()
            for d in deps_of(body[t]) + [parent_of(t)]:
                if d in body and layer_of(body[d]) > moves[t] and moves.get(d, 9) > moves[t]:
                    moves[d] = moves[t]
                    pend.append(d)
    for t in sorted(moves, key=sortkey):
        s = _set_layer(s, t, moves[t])
        s = log_line(s, t, f"promoted L{layer_of(body[t])} → L{moves[t]}" + ("" if t == a.id else f" (gates {a.id})"))
    write(s)
    print("\n".join(f"{t} L{layer_of(body[t])} → L{moves[t]}" + ("" if t == a.id else "  (blocker/parent)")
                    for t in sorted(moves, key=sortkey)))
    warn_layers()

def cmd_close(a):
    s = read(); bl = blocks(s)
    kids = sorted([t for t, *_ in bl if parent_of(t) == a.id], key=sortkey)
    if kids and not a.cascade:
        sys.exit(f"{a.id} has open subtasks: {' '.join(kids)} — close them first or pass --cascade")
    # every descendant, not just direct kids — deepest first, so --cascade can never orphan a grandchild
    subs = sorted([t for t, *_ in bl if t.startswith(a.id + ".")], key=sortkey, reverse=True) if a.cascade else []
    for tid in subs + [a.id]:
        s = _close_one(s, tid, a)
    write(s)
    bl = blocks(s)
    freed = [t for t, st, ti, b, _ in bl if a.id in deps_of(b) and not [d for d in deps_of(b) if d in {x for x, *_ in bl}]]
    for t in freed:
        s = log_line(s, t, f"unblocked ({a.id} closed)")
    if freed:
        write(s)
        print("unblocked: " + ", ".join(f"{t} {next(ti for x, _, ti, _, _ in bl if x == t)}" for t in freed))
    closed = s.split("## CLOSED\n", 1)[1].split("\n## ", 1)[0] if "## CLOSED\n" in s else ""
    if closed.count("\n- ") > 15:
        print("note: CLOSED >15 lines — archive to", ARCHIVE)
    print("closed")

def _close_one(s, tid, a):
    for t, state, title, body, span in blocks(s):
        if t == tid:
            s = s[: span[0]] + s[span[1]:]
            line = f"- {tid} {title} — {a.type} {now()}: {a.evidence or 'unverified'}\n"
            s = s.replace("## CLOSED\n", "## CLOSED\n" + line, 1) if "## CLOSED" in s else s + "\n## CLOSED\n" + line
            return log_line(s, tid, f"closed({a.type}): {a.evidence or 'unverified'}")
    sys.exit(f"{tid} not found")

def cmd_log(a):
    write(log_line(read(), a.id or "-", a.msg)); print("ok")

def cmd_verify(a):
    for tid, state, title, body, _ in blocks(read()):
        if tid == a.id:
            v = field(body, "verify")
            if v in ("", "-"):
                sys.exit(f"{tid}: no verify recipe")
            print(f"$ {v}", flush=True)
            sys.exit(subprocess.run(v, shell=True).returncode)
    sys.exit(f"{a.id} not found")

p = argparse.ArgumentParser()
sub = p.add_subparsers(dest="cmd", required=True)
lsp = sub.add_parser("list"); lsp.add_argument("-q", action="store_true")
lsp.add_argument("--ready", action="store_true"); lsp.add_argument("--tree", action="store_true")
for x in (lsp, rp := sub.add_parser("ready")):
    x.add_argument("--layer", type=int, help="show only this layer (default: 1+2)")
    x.add_argument("--all", action="store_true", help="include parked (layer 3) threads")
rp.add_argument("-q", action="store_true")
sub.add_parser("show").add_argument("id")
ap = sub.add_parser("add"); ap.add_argument("title")
for x in ("--desc", "--now", "--next", "--verify", "--ev", "--parent"): ap.add_argument(x)
ap.add_argument("--after", action="append", help="dep id(s) this task waits on; repeatable")
ap.add_argument("--layer", type=int, help=f"1 now / 2 this cycle / 3 parked (default: parent's, else {DEFAULT_LAYER})")
ap.add_argument("--state", default="active")
mp = sub.add_parser("mutate"); mp.add_argument("id")
for x in ("--state", "--title", "--now", "--next", "--verify", "--ev", "--amend", "--deps"): mp.add_argument(x)
mp.add_argument("--add-dep", action="append"); mp.add_argument("--rm-dep", action="append")
mp.add_argument("--layer", type=int, help="set layer 1/2/3 — the only way to demote (park) a task")
pp = sub.add_parser("promote"); pp.add_argument("id")
pp.add_argument("--to", type=int, help="target layer (default: one step nearer, 3→2→1)")
pp.add_argument("--no-cascade", action="store_true", help="leave blockers/parent parked (prints the inversions)")
cp = sub.add_parser("close"); cp.add_argument("id")
cp.add_argument("--type", default="done", choices=["done", "user-word", "superseded", "abandoned", "external"])
cp.add_argument("--evidence"); cp.add_argument("--cascade", action="store_true")
lp = sub.add_parser("log"); lp.add_argument("msg"); lp.add_argument("--id")
sub.add_parser("verify").add_argument("id")
a = p.parse_args()
{"list": cmd_list, "ready": cmd_ready, "show": cmd_show, "add": cmd_add, "mutate": cmd_mutate,
 "promote": cmd_promote, "close": cmd_close, "log": cmd_log, "verify": cmd_verify}[a.cmd](a)
