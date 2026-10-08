#!/usr/bin/env python3
"""Read-only live web view of the v2 ledger: kanban board (NOW/NEXT/WAITING/COLD), owner filter, detail drawer, DAG, archive. Never writes."""
import argparse, http.server, json, os, re, subprocess, sys, webbrowser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ledger as L  # noqa: E402

PAGE = r"""<!doctype html><html lang=en><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>ledger</title>
<style>
:root{
 --bg:#f5f6f8;--panel:#fff;--panel2:#fafbfc;--line:#e3e6eb;--line2:#edf0f3;
 --ink:#12161c;--ink2:#3c4655;--mute:#78828f;--sel:#2563eb;--selbg:#e8f0fe;
 --now:#b8690b;--next:#1d7a4c;--wait:#5257ce;--cold:#828a95;--poke:#b3291c;
 --code:#f1f3f6;--shadow:0 1px 2px rgba(16,24,40,.05),0 10px 28px rgba(16,24,40,.08);
 --tint-now:#fffaf2;--tint-next:#f4fbf7;--tint-waiting:#f7f7fd;--tint-cold:#f8f9fa;--tint-closed:#f8f9fa;
}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){
 --bg:#0e1116;--panel:#161a21;--panel2:#1a1f27;--line:#272e37;--line2:#20262e;
 --ink:#e6eaf1;--ink2:#b6c0cc;--mute:#7e8896;--sel:#63a1fb;--selbg:#1c2634;
 --now:#e0a44f;--next:#5dc08c;--wait:#9096f0;--cold:#78808c;--poke:#ef7d72;
 --code:#1e242c;--shadow:0 1px 2px rgba(0,0,0,.5),0 10px 30px rgba(0,0,0,.4);
 --tint-now:#1d1a13;--tint-next:#121d18;--tint-waiting:#171825;--tint-cold:#161a20;--tint-closed:#161a20;
}}
:root[data-theme=dark]{
 --bg:#0e1116;--panel:#161a21;--panel2:#1a1f27;--line:#272e37;--line2:#20262e;
 --ink:#e6eaf1;--ink2:#b6c0cc;--mute:#7e8896;--sel:#63a1fb;--selbg:#1c2634;
 --now:#e0a44f;--next:#5dc08c;--wait:#9096f0;--cold:#78808c;--poke:#ef7d72;
 --code:#1e242c;--shadow:0 1px 2px rgba(0,0,0,.5),0 10px 30px rgba(0,0,0,.4);
 --tint-now:#1d1a13;--tint-next:#121d18;--tint-waiting:#171825;--tint-cold:#161a20;--tint-closed:#161a20;
}
*{box-sizing:border-box}
[hidden]{display:none!important}
html,body{height:100%}
body{margin:0;background:var(--bg);color:var(--ink);font:13px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif;-webkit-font-smoothing:antialiased}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
a{color:var(--sel);text-decoration:none}a:hover{text-decoration:underline}
button{font:inherit;color:inherit;background:none;border:0;padding:0;cursor:pointer}

/* header */
header{position:sticky;top:0;z-index:20;background:var(--panel);border-bottom:1px solid var(--line)}
.hrow{display:flex;align-items:center;gap:16px;padding:8px 16px;flex-wrap:wrap}
.hrow+.hrow{border-top:1px solid var(--line2);padding-top:6px;padding-bottom:6px}
.brand{display:flex;align-items:center;gap:8px;font-weight:650;letter-spacing:-.01em;font-size:14px}
.dot{width:8px;height:8px;border-radius:50%;background:var(--next);box-shadow:0 0 0 3px rgba(29,122,76,.16);transition:background .2s}
.dot.bad{background:var(--poke);box-shadow:0 0 0 3px rgba(179,41,28,.16)}
.tabs{display:flex;gap:2px;background:var(--panel2);border:1px solid var(--line);border-radius:8px;padding:2px}
.tabs button{padding:3px 12px;border-radius:6px;color:var(--mute);font-size:12px;font-weight:550}
.tabs button.on{background:var(--panel);color:var(--ink);box-shadow:0 1px 2px rgba(16,24,40,.08)}
.pills{display:flex;gap:6px;flex-wrap:wrap}
.pill{display:inline-flex;align-items:center;gap:5px;font-size:11.5px;color:var(--ink2);padding:2px 9px;border:1px solid var(--line);border-radius:999px;background:var(--panel2)}
.pill i{width:6px;height:6px;border-radius:50%;background:currentColor;font-style:normal}
.pill.now{color:var(--now)}.pill.next{color:var(--next)}.pill.waiting{color:var(--wait)}.pill.cold{color:var(--cold)}.pill.poke{color:var(--poke);border-color:color-mix(in srgb,var(--poke) 35%,var(--line))}
.grow{flex:1}
.upd{font-size:11px;color:var(--mute);white-space:nowrap}
input[type=search]{-webkit-appearance:none;appearance:none;padding:5px 10px;border:1px solid var(--line);border-radius:8px;background:var(--panel2);color:var(--ink);min-width:240px;font-size:12.5px}
input[type=search]:focus{outline:none;border-color:var(--sel);background:var(--panel);box-shadow:0 0 0 3px var(--selbg)}
.chip{display:inline-flex;align-items:center;gap:5px;padding:2px 9px;border-radius:999px;border:1px solid var(--line);background:var(--panel2);font-size:11.5px;color:var(--ink2);cursor:pointer;user-select:none}
.chip:hover{border-color:var(--mute)}
.chip.on{background:var(--ink);border-color:var(--ink);color:var(--panel)}
.chipset{display:flex;gap:6px;align-items:center;flex-wrap:wrap}
.chipset .lbl{font-size:11px;color:var(--mute);text-transform:uppercase;letter-spacing:.06em}
.keys{font-size:11px;color:var(--mute)}
kbd{font:11px ui-monospace,monospace;border:1px solid var(--line);border-bottom-width:2px;border-radius:4px;padding:0 4px;background:var(--panel2)}

/* owner chips */
.own{font:600 10px/1.6 ui-monospace,monospace;padding:0 5px;border-radius:4px;background:hsl(var(--oh) 70% 92%);color:hsl(var(--oh) 60% 30%);letter-spacing:.04em;white-space:nowrap}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]) .own{background:hsl(var(--oh) 38% 22%);color:hsl(var(--oh) 75% 78%)}}
:root[data-theme=dark] .own{background:hsl(var(--oh) 38% 22%);color:hsl(var(--oh) 75% 78%)}

/* board */
main{padding:12px 16px 20px}
.board{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;align-items:stretch}
.col{background:var(--panel);border:1px solid var(--line);border-radius:12px;display:flex;flex-direction:column;height:calc(100vh - 132px);min-height:200px;overflow:hidden}
.col>h2{margin:0;padding:9px 12px;font-size:11px;font-weight:650;letter-spacing:.09em;text-transform:uppercase;color:var(--mute);display:flex;align-items:center;gap:8px;border-bottom:1px solid var(--line2)}
.col>h2 .n{margin-left:auto;font:11px ui-monospace,monospace;color:var(--ink2)}
.col>h2 .bar{width:3px;height:12px;border-radius:2px;background:var(--cold)}
.col[data-b=now]>h2 .bar{background:var(--now)}.col[data-b=next]>h2 .bar{background:var(--next)}.col[data-b=waiting]>h2 .bar{background:var(--wait)}
.list{overflow:auto;padding:8px;display:flex;flex-direction:column;gap:7px;scrollbar-width:thin}
.empty{color:var(--mute);font-size:12px;padding:10px 4px}

.card{border:1px solid var(--line);border-left:3px solid var(--cold);border-radius:9px;padding:7px 9px 8px;background:var(--panel2);cursor:pointer;transition:border-color .12s,box-shadow .12s,transform .12s}
.card:hover{border-color:var(--mute);box-shadow:0 1px 2px rgba(16,24,40,.06)}
.card.on{border-color:var(--sel);box-shadow:0 0 0 3px var(--selbg)}
.b-now{border-left-color:var(--now);background:var(--tint-now)}
.b-next{border-left-color:var(--next);background:var(--tint-next)}
.b-waiting{border-left-color:var(--wait);background:var(--tint-waiting)}
.b-cold{border-left-color:var(--cold);background:var(--tint-cold);opacity:.88}
.card .top{display:flex;align-items:baseline;gap:6px}
.card .cid{font:11px ui-monospace,monospace;color:var(--mute)}
.card .ttl{font-weight:600;color:var(--ink);letter-spacing:-.005em;line-height:1.35;overflow-wrap:anywhere}
.card .nx{color:var(--ink2);font-size:12px;margin-top:4px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.card .tags{display:flex;gap:4px;flex-wrap:wrap;margin-top:6px}
.tag{font:10.5px/1.6 ui-monospace,monospace;padding:0 5px;border-radius:4px;border:1px solid var(--line);background:var(--panel);color:var(--mute);white-space:nowrap}
.tag.poke{border-color:color-mix(in srgb,var(--poke) 40%,var(--line));color:var(--poke);font-weight:600}
.tag.hold{color:var(--wait)}.tag.blocks{color:var(--next)}
.tag.now{color:var(--now)}.tag.next{color:var(--next)}.tag.waiting{color:var(--wait)}.tag.cold{color:var(--cold)}
button:focus-visible,.chip:focus-visible{outline:2px solid var(--sel);outline-offset:1px}
.prio{font:700 9.5px/1.6 ui-monospace,monospace;padding:0 5px;border-radius:4px;letter-spacing:.06em;margin-right:6px}
.prio.P0{background:var(--poke);color:#fff}.prio.P1{background:var(--now);color:#fff}.prio.P2{background:var(--code);color:var(--mute)}
.card.p-P0{border-color:color-mix(in srgb,var(--poke) 55%,var(--line));box-shadow:inset 0 0 0 1px color-mix(in srgb,var(--poke) 35%,transparent)}
.card.p-P1{border-color:color-mix(in srgb,var(--now) 55%,var(--line))}
.pset{display:inline-flex;gap:2px;margin-left:8px;border:1px solid var(--line);border-radius:6px;padding:2px;background:var(--panel2)}
.pbtn{font:700 9.5px/1.6 ui-monospace,monospace;padding:0 6px;border-radius:4px;color:var(--mute)}
.pbtn.on.P0{background:var(--poke);color:#fff}.pbtn.on.P1{background:var(--now);color:#fff}.pbtn.on.P2{background:var(--code);color:var(--ink)}.pbtn.on.none{background:var(--code);color:var(--ink)}
.pbtn:hover{color:var(--ink)}
.toast{position:fixed;left:50%;bottom:18px;transform:translateX(-50%);background:var(--ink);color:var(--panel);padding:6px 12px;border-radius:8px;font-size:12px;opacity:0;transition:opacity .15s;pointer-events:none;z-index:50}
.toast.show{opacity:1}
.rank{font:9.5px/1.7 ui-monospace,monospace;letter-spacing:.08em;text-transform:uppercase;color:var(--now);font-weight:700}
.rank.dim{color:var(--mute);font-weight:600}

/* quick-add */
.qa{display:flex;gap:6px;padding:7px 8px;border-bottom:1px solid var(--line2);flex-wrap:wrap;align-items:center}
.qa .qin{flex:1 1 130px;min-width:0;padding:4px 8px;border:1px solid var(--line);border-radius:7px;background:var(--panel2);color:var(--ink);font-size:12.5px}
.qa .qin::placeholder{color:var(--mute)}
.qa .qin:focus{outline:none;border-color:var(--sel);background:var(--panel);box-shadow:0 0 0 3px var(--selbg)}
.qa select,.qa input[type=date]{font:11px ui-monospace,monospace;padding:3px 5px;border:1px solid var(--line);border-radius:6px;background:var(--panel2);color:var(--ink2);max-width:118px}
.qa .qrow{display:flex;gap:6px;width:100%}

/* subtasks on a card */
.tag.sub{cursor:pointer}
.tag.sub:hover{border-color:var(--mute);color:var(--ink2)}
.tag.ready{color:var(--mute)}
.tag.ready.un{color:var(--next);border-color:color-mix(in srgb,var(--next) 35%,var(--line))}
.kids{margin-top:6px;border-top:1px dashed var(--line);padding-top:5px;display:flex;flex-direction:column;gap:3px}
.kid{display:flex;gap:6px;align-items:baseline;font-size:11.5px;color:var(--ink2);padding:1px 2px;border-radius:5px}
.kid:hover{background:var(--code)}
.kid .cid{font:10.5px ui-monospace,monospace;color:var(--mute)}
.kid .kt{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.kid.done .kt{text-decoration:line-through;color:var(--mute)}

/* feed */
.frow{display:grid;grid-template-columns:96px 74px 58px 84px minmax(0,1fr);gap:10px;align-items:baseline;padding:6px 8px;border-top:1px solid var(--line2);cursor:pointer}
.frow:hover{background:var(--panel2)}
.frow .fts{font:10.5px ui-monospace,monospace;color:var(--mute)}
.frow .fid{font:11px ui-monospace,monospace;color:var(--ink2)}
.frow .ftx{color:var(--ink2);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.frow .ftl{color:var(--mute)}
@media (max-width:1000px){.frow{grid-template-columns:96px 74px minmax(0,1fr)}.frow .fby,.frow .fid{display:none}}

/* modal */
.modal{position:fixed;inset:0;z-index:40;display:flex;align-items:center;justify-content:center;background:rgba(10,14,20,.35)}
.modal .box{background:var(--panel);border:1px solid var(--line);border-radius:14px;box-shadow:var(--shadow);padding:16px 18px;width:min(460px,92vw);max-height:80vh;overflow:auto}
.modal h2{margin:0 0 10px;font-size:14px;letter-spacing:-.01em}
.modal dl{display:grid;grid-template-columns:auto minmax(0,1fr);gap:7px 14px;margin:0;font-size:12.5px}
.modal dt{text-align:right;white-space:nowrap}
.modal dd{margin:0;color:var(--ink2)}
.modal .foot{margin-top:14px;color:var(--mute);font-size:11.5px}

/* priority */
.plist{overflow:auto;max-height:calc(100vh - 148px)}
.pgroup{display:flex;align-items:center;gap:8px;padding:12px 2px 6px;font-size:11px;text-transform:uppercase;letter-spacing:.09em;color:var(--mute);font-weight:650;position:sticky;top:0;background:var(--panel);z-index:2}
.pgroup .hint,.pgroup .n{text-transform:none;letter-spacing:0;font-weight:500}
.pgroup .n{margin-left:auto;font:11px ui-monospace,monospace;color:var(--ink2)}
.prow{display:grid;grid-template-columns:54px 92px minmax(0,1fr) auto auto;gap:10px;align-items:center;padding:7px 10px;margin-bottom:5px;border:1px solid var(--line);border-left:3px solid var(--cold);border-radius:9px;background:var(--panel2);cursor:pointer;transition:border-color .12s}
.prow:hover{border-color:var(--mute)}
.prow.on{border-color:var(--sel);box-shadow:0 0 0 3px var(--selbg)}
.prow .cid{font:11px ui-monospace,monospace;color:var(--mute)}
.prow .own,.frow .own{justify-self:start;max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.prow .pt{min-width:0}
.prow .pt .ttl{font-weight:600;letter-spacing:-.005em;overflow-wrap:anywhere;line-height:1.35}
.prow .pt .nx{color:var(--ink2);font-size:12px;margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.prow .meta{display:flex;gap:4px;flex-wrap:wrap;justify-content:flex-end;max-width:300px}
.prow .pset{margin-left:0}
.pbanner{border:1px dashed var(--line);border-radius:9px;padding:11px 12px;color:var(--mute);font-size:12.5px;margin:4px 0 2px}
.pbanner b{color:var(--ink2)}
@media (max-width:1000px){.prow{grid-template-columns:54px minmax(0,1fr) auto;row-gap:6px}.prow .meta{grid-column:2/4;justify-content:flex-start;max-width:none}}

/* graph */
.panel{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:10px 12px}
.gwrap{overflow:auto;max-height:calc(100vh - 170px)}
svg{display:block}
.n rect{stroke:var(--line);stroke-width:1;fill:var(--panel2)}
.n:hover rect{stroke:var(--mute)}
.n.sel rect{stroke:var(--sel);stroke-width:2}
.n text{font:11px ui-monospace,monospace;fill:var(--ink)}
.n text.sub{font:10.5px -apple-system,system-ui,sans-serif;fill:var(--mute)}
.n .accent{stroke:none}
.n.now .accent{fill:var(--now)}.n.next .accent{fill:var(--next)}.n.waiting .accent{fill:var(--wait)}.n.cold .accent{fill:var(--cold)}
.n.now rect{fill:var(--tint-now)}.n.next rect{fill:var(--tint-next)}.n.waiting rect{fill:var(--tint-waiting)}.n.cold rect{fill:var(--tint-cold)}
.e{stroke:var(--mute);fill:none;opacity:.75}
.e.parent{stroke-dasharray:4 3;opacity:.5}
.legend{display:flex;gap:14px;flex-wrap:wrap;font-size:11.5px;color:var(--mute);margin-bottom:8px;align-items:center}
.legend b{font-weight:600;color:var(--ink2)}
.swatch{display:inline-block;width:9px;height:9px;border-radius:2px;margin-right:5px;vertical-align:-1px}

/* archive */
.arc{width:100%;border-collapse:collapse}
.arc tr{border-top:1px solid var(--line2);cursor:pointer}
.arc tr:hover{background:var(--panel2)}
.arc td{padding:7px 8px;vertical-align:top}
.arc td.d{font:11px ui-monospace,monospace;color:var(--mute);white-space:nowrap}
.arc td.i{font:11px ui-monospace,monospace;color:var(--mute);white-space:nowrap}
.arc .t{font-weight:600}
.arc .e{color:var(--mute);font-size:12px;margin-top:2px}
.badge{font:10px/1.7 ui-monospace,monospace;padding:0 6px;border-radius:999px;border:1px solid var(--line);color:var(--mute);white-space:nowrap}
.badge.done{color:var(--next);border-color:color-mix(in srgb,var(--next) 35%,var(--line))}
.badge.lapsed,.badge.abandoned{color:var(--cold)}
.badge.superseded{color:var(--wait)}

/* drawer */
.scrim{position:fixed;inset:0;background:rgba(10,14,20,.28);opacity:0;pointer-events:none;transition:opacity .16s;z-index:29}
.scrim.on{opacity:1;pointer-events:auto}
.drawer{position:fixed;top:0;right:0;height:100%;width:min(640px,96vw);background:var(--panel);border-left:1px solid var(--line);box-shadow:var(--shadow);transform:translateX(102%);transition:transform .18s cubic-bezier(.3,.8,.4,1);z-index:30;display:flex;flex-direction:column}
.drawer.on{transform:none}
.dhd{padding:12px 14px 10px;border-bottom:1px solid var(--line2)}
.dhd .l1{display:flex;align-items:center;gap:8px;margin-bottom:5px}
.dhd h1{margin:0;font-size:15.5px;line-height:1.35;letter-spacing:-.01em}
.dhd .x{margin-left:auto;color:var(--mute);font-size:15px;padding:2px 6px;border-radius:6px}
.dhd .x:hover{background:var(--code);color:var(--ink)}
.dbd{padding:12px 14px 40px;overflow:auto}
.kv{display:grid;grid-template-columns:82px minmax(0,1fr);gap:5px 12px;font-size:12.5px;margin-bottom:14px}
.kv .k{color:var(--mute);font-size:11.5px;padding-top:1px}
.kv .v{color:var(--ink2);overflow-wrap:anywhere}
code{font:11.5px ui-monospace,monospace;background:var(--code);padding:1px 5px;border-radius:5px;overflow-wrap:anywhere}
h3.sec{font-size:11px;text-transform:uppercase;letter-spacing:.09em;color:var(--mute);margin:16px 0 7px;font-weight:650}
.refs{display:flex;gap:5px;flex-wrap:wrap}
.ref{font:11px ui-monospace,monospace;padding:1px 7px;border-radius:6px;border:1px solid var(--line);background:var(--panel2);color:var(--ink2);cursor:pointer}
.ref:hover{border-color:var(--sel);color:var(--sel)}
.blk{background:var(--panel2);border:1px solid var(--line2);border-radius:8px;padding:8px 10px;color:var(--ink2);font-size:12.5px;overflow-wrap:anywhere}
.hist{list-style:none;padding:0;margin:0}
.hist li{padding:7px 0 7px 2px;border-top:1px solid var(--line2);font-size:12.5px;color:var(--ink2);overflow-wrap:anywhere}
.hist .ts{font:10.5px ui-monospace,monospace;color:var(--mute);margin-right:7px}
.hist .ty{font:10px/1.7 ui-monospace,monospace;padding:0 5px;border:1px solid var(--line);border-radius:999px;margin-right:6px;color:var(--mute)}
.hist .ty.close{color:var(--next)}.hist .ty.bucket{color:var(--wait)}.hist .ty.amend{color:var(--now)}
.hist .by{font:10px ui-monospace,monospace;color:var(--mute);opacity:.7;margin-left:6px}

@media (max-width:1000px){
 .board{grid-template-columns:repeat(4,300px);overflow-x:auto;padding-bottom:6px}
 .col{height:calc(100vh - 156px)}
 input[type=search]{min-width:160px}
}
</style>

<header>
 <div class=hrow>
  <div class=brand><span class=dot id=dot></span>ledger</div>
  <div class=tabs id=tabs><button data-v=board class=on>Board</button><button data-v=prio>Priority</button><button data-v=graph>Graph</button><button data-v=archive>Archive</button><button data-v=feed>Feed</button></div>
  <div class=pills id=pills></div>
  <div class=grow></div>
  <div class=tabs id=theme title="theme"><button data-t=light>Light</button><button data-t=dark>Dark</button><button data-t=auto>Auto</button></div>
  <div class=upd id=upd>connecting…</div>
 </div>
 <div class=hrow>
  <input type=search id=q placeholder="search id, title, #PR, text…" autocomplete=off spellcheck=false>
  <div class=chipset id=owners><span class=lbl>owner</span></div>
  <div class=chipset id=bks><span class=lbl>buckets</span></div>
  <div class=chipset id=flt><span class=chip id=readyonly title="only tasks with no open deps and not waiting">ready only</span></div>
  <div class=grow></div>
  <div class=keys><kbd>n</kbd> new <kbd>j</kbd><kbd>k</kbd> move <kbd>⏎</kbd> open <kbd>p</kbd> prio <kbd>/</kbd> search <kbd>?</kbd> keys</div>
 </div>
</header>
<script>
(function(){const k='ledgerTheme';const apply=t=>{if(t==='auto')delete document.documentElement.dataset.theme;else document.documentElement.dataset.theme=t;document.querySelectorAll('#theme button').forEach(b=>b.classList.toggle('on',b.dataset.t===t))};
 let t='light';try{t=localStorage.getItem(k)||'light'}catch(e){}
 const init=()=>{apply(t);document.querySelectorAll('#theme button').forEach(b=>b.onclick=()=>{t=b.dataset.t;try{localStorage.setItem(k,t)}catch(e){}apply(t)})};
 if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init);else init();})();
</script>

<main>
 <section id=board class=board>
  <div class=col data-b=now><h2><span class=bar></span>Now<span class=n></span></h2><form class=qa><input class=qin type=text placeholder="+ task" autocomplete=off spellcheck=false><select class=qowner title="owner"></select></form><div class=list></div></div>
  <div class=col data-b=next><h2><span class=bar></span>Next<span class=n></span></h2><form class=qa><input class=qin type=text placeholder="+ task" autocomplete=off spellcheck=false><select class=qowner title="owner"></select></form><div class=list></div></div>
  <div class=col data-b=waiting><h2><span class=bar></span>Waiting<span class=n></span></h2><form class=qa><input class=qin type=text placeholder="+ task" autocomplete=off spellcheck=false><select class=qowner title="owner"></select><div class=qrow><select class=qon title="waiting on"><option value=user>user</option><option value=ext>ext</option><option value="delegated:">delegated</option><option value=watching>watching</option></select><input class=quntil type=date title="until (optional)"></div></form><div class=list></div></div>
  <div class=col data-b=cold><h2><span class=bar></span>Cold<span class=n></span></h2><form class=qa><input class=qin type=text placeholder="+ task" autocomplete=off spellcheck=false><select class=qowner title="owner"></select></form><div class=list></div></div>
 </section>

 <section id=prio class=panel hidden><div class=plist id=plist></div></section>

 <section id=graph class=panel hidden>
  <div class=legend>
   <span><span class="swatch" style="background:var(--now)"></span>now</span>
   <span><span class="swatch" style="background:var(--next)"></span>next</span>
   <span><span class="swatch" style="background:var(--wait)"></span>waiting</span>
   <span><span class="swatch" style="background:var(--cold)"></span>cold</span>
   <span><b>—</b> dep</span><span><b>- -</b> parent</span>
   <div class=grow></div>
   <span class=chip id=gall>show unconnected</span>
  </div>
  <div class=gwrap><svg id=g xmlns="http://www.w3.org/2000/svg"><defs>
   <marker id=arrow viewBox="0 0 10 10" refX=9 refY=5 markerWidth=6 markerHeight=6 orient=auto-start-reverse><path d="M0 0L10 5L0 10z" fill="currentColor"/></marker>
  </defs></svg></div>
 </section>

 <section id=archive class=panel hidden><table class=arc><tbody id=arcb></tbody></table></section>

 <section id=feed class=panel hidden>
  <div class=legend><span class=lbl style="font-size:11px;color:var(--mute);text-transform:uppercase;letter-spacing:.06em">type</span>
   <span class=chipset id=ftypes></span><div class=grow></div><span id=fcount style="color:var(--mute);font-size:11.5px"></span></div>
  <div class=plist id=feedb></div>
 </section>
</main>

<div class=modal id=cheat hidden><div class=box>
 <h2>Keyboard</h2>
 <dl>
  <dt><kbd>j</kbd> <kbd>k</kbd></dt><dd>move the selection (also ↑ ↓)</dd>
  <dt><kbd>⏎</kbd></dt><dd>open the selected task</dd>
  <dt><kbd>esc</kbd></dt><dd>close the drawer, this box, or leave the search field</dd>
  <dt><kbd>/</kbd></dt><dd>jump to search</dd>
  <dt><kbd>n</kbd></dt><dd>new task — focuses the quick-add box of the Next column</dd>
  <dt><kbd>p</kbd></dt><dd>cycle the priority of the selected task: P0 → P1 → P2 → none</dd>
  <dt><kbd>1</kbd>…<kbd>5</kbd></dt><dd>Board, Priority, Graph, Archive, Feed</dd>
  <dt><kbd>?</kbd></dt><dd>this list</dd>
 </dl>
 <div class=foot>Quick-add writes through the ledger CLI, so its own rules still apply: Now refuses a fourth task, Waiting needs a reason.</div>
</div></div>
<div class=scrim id=scrim></div>
<aside class=drawer id=drawer aria-hidden=true><div class=dhd id=dhd></div><div class=dbd id=dbd></div></aside>

<script>
const $=s=>document.querySelector(s), E=(t,a)=>Object.assign(document.createElement(t),a||{});
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const GH='https://github.com/__GH_ORG__/';
const linkify=s=>esc(s)
  .replace(/(https?:\/\/[^\s<)\]]+)/g,'<a href="$1" target=_blank rel=noreferrer>$1</a>')
  .replace(/\b([a-z][a-z0-9-]{2,})#(\d{2,6})\b/g,'<a href="'+GH+'$1/pull/$2" target=_blank rel=noreferrer>$1#$2</a>');
const SVG=(t,a,...k)=>{const e=document.createElementNS('http://www.w3.org/2000/svg',t);for(const x in a)e.setAttribute(x,a[x]);k.forEach(c=>e.append(c));return e};
const hue=o=>{let h=0;for(const c of String(o))h=(h*31+c.charCodeAt(0))>>>0;return h%360};
const COLS=[['now','Now'],['next','Next'],['waiting','Waiting'],['cold','Cold']];
const nkey=i=>i.slice(1).split('.').map(Number);
const ncmp=(a,b)=>{const A=nkey(a),B=nkey(b);for(let i=0;i<Math.max(A.length,B.length);i++){const d=(A[i]??-1)-(B[i]??-1);if(d)return d}return 0};

const store={get(){try{return JSON.parse(localStorage.ledgerUI||'{}')}catch(e){return{}}},
 set(){try{localStorage.ledgerUI=JSON.stringify({view,owner,bkOn,gall,readyOnly,ftype})}catch(e){}}};
const P=store.get();
let D=null,raw='',sel=null,drawerOn=false,owner=P.owner||'all',q='',view=P.view||'board',gall=!!P.gall,navIdx=-1,nav=[];
const VIEWS=['board','prio','graph','archive','feed'];
const bkOn=Object.assign({now:true,next:true,waiting:true,cold:true},P.bkOn||{});
const cards=new Map();           // id -> {el,sig}
let lastSigs={pills:'',owners:'',graph:'',arc:'',drawer:'',prio:'',feed:'',qa:''};
const openKids=new Set();
let readyOnly=!!P.readyOnly,ftype=P.ftype||'all',routing=false;

/* ---------- helpers ---------- */
const shortTs=t=>t?t.slice(5,16).replace('T',' '):'';
function ago(t){if(!t)return'';const d=Math.floor((Date.now()-Date.parse(t+':00Z'))/86400000);return d<=0?'today':d===1?'1d ago':d+'d ago'}
function pokeOf(id){return D.snap.pokes.includes(id)}
function match(id){const t=D.tasks[id];if(!t)return false;
 if(owner!=='all'&&t.owner!==owner)return false;
 if(readyOnly&&!t.ready)return false;
 if(!q)return true;
 return (id+' '+t.title+' '+t.def+' '+t.next+' '+t.last_line+' '+(t.ev||[]).join(' ')+' '+(t.urls||[]).join(' ')).toLowerCase().includes(q)}

/* ---------- header ---------- */
function pills(){
 const s=D.snap,op=Object.values(D.tasks).filter(t=>!t.closed);
 const p0=op.filter(t=>t.prio==='P0').length,p1=op.filter(t=>t.prio==='P1').length;
 const p=[[p0?'poke':'',`P0 ${p0} · P1 ${p1}`],['now',`now ${s.now.length}/${D.depth}`],['next',`next ${s.next.length}`],['waiting',`waiting ${s.waiting.length}`],
  [s.pokes.length?'poke':'',`pokes ${s.pokes.length}`],['cold',`cold ${s.cold.length}`],['','closed '+s.closed.length]];
 const sig=JSON.stringify(p);if(sig===lastSigs.pills)return;lastSigs.pills=sig;
 $('#pills').innerHTML=p.map(([c,t])=>`<span class="pill ${c}"><i></i>${t}</span>`).join('');
}
function owners(){
 const list=['all',...[...new Set(Object.values(D.tasks).map(t=>t.owner))].sort()];
 const sig=list.join()+'|'+owner;if(sig===lastSigs.owners)return;lastSigs.owners=sig;
 const box=$('#owners');box.querySelectorAll('.chip').forEach(c=>c.remove());
 list.forEach(o=>{const c=E('span',{className:'chip'+(owner===o?' on':''),textContent:o==='all'?'all':o});
  c.onclick=()=>{owner=o;lastSigs.owners='';lastSigs.graph='';lastSigs.arc='';lastSigs.prio='';lastSigs.feed='';store.set();render()};box.append(c)});
}
function bucketChips(){
 const box=$('#bks');if(box.querySelector('.chip'))return;
 COLS.forEach(([k,l])=>{const c=E('span',{className:'chip'+(bkOn[k]?' on':''),textContent:l.toLowerCase()});
  c.onclick=()=>{bkOn[k]=!bkOn[k];c.classList.toggle('on',bkOn[k]);store.set();board()};box.append(c)});
}

/* ---------- board ---------- */
function tags(id){
 const t=D.tasks[id],out=[];
 if(t.bucket==='waiting'){const p=pokeOf(id);out.push(`<span class="tag${p?' poke':''}">${esc(t.on||'wait')}${t.until?' → '+t.until:''}</span>`);
  if(p)out.push('<span class="tag poke">POKE</span>')}
 const held=D.snap.held[id];if(held)out.push(`<span class="tag hold">⇠ ${held.join(' ')}</span>`);
 if(t.blocks.length)out.push(`<span class="tag blocks">⇢ ${t.blocks.join(' ')}</span>`);
 if(t.kids_all.length){const done=t.kids_all.filter(k=>D.tasks[k]&&D.tasks[k].closed).length;
  out.push(`<span class="tag sub" data-kids="${id}" title="subtasks">${done}/${t.kids_all.length} done</span>`)}
 if(t.ready)out.push(`<span class="tag ready${t.deps.length?' un':''}" title="${t.deps.length?'every dependency is closed':'no open dependency'}">ready</span>`);
 if(t.bucket==='cold')out.push(`<span class=tag>${ago(t.last)}</span>`);
 return out.join('');
}
function cardHTML(id,rank){
 const t=D.tasks[id];
 const r=rank===0?'<div class=rank>current</div>':rank>0?`<div class="rank dim">interrupted · ${rank}</div>`:'';
 return `${r}<div class=top><span class=cid>${id}</span>${t.prio?`<span class="prio ${t.prio}">${t.prio}</span>`:''}<span class=own style="--oh:${hue(t.owner)}">${esc(t.owner)}</span><span class=ttl>${esc(t.stitle)}</span></div>`+
   `<div class=nx>${esc(t.next||t.last_line||'')}</div><div class=tags>${tags(id)}</div>`+
   (openKids.has(id)?`<div class=kids>${t.kids_all.map(kidRow).join('')}</div>`:'');
}
function kidRow(k){
 const c=D.tasks[k];if(!c)return `<div class=kid><span class=cid>${k}</span><span class=kt>(not in this log)</span></div>`;
 return `<div class="kid${c.closed?' done':''}" data-go="${k}"><span class=cid>${k}</span><span class=kt>${esc(c.stitle)}</span>`+
  `<span class="tag ${c.closed?'':c.bucket}">${c.closed?c.closed.type:c.bucket}</span></div>`;
}
const EMPTY={now:'nothing pushed — ledger push T<n>',next:'next is clear',waiting:'nothing waiting',cold:'nothing parked'};
function emptyMsg(k){return (q||owner!=='all')?'no match':EMPTY[k]}
function board(){
 nav=[];
 for(const [key,label] of COLS){
  const col=$(`.col[data-b=${key}]`);col.hidden=!bkOn[key];
  const ids=D.snap[key].filter(match);
  if(bkOn[key])nav.push(...ids);
  col.querySelector('h2 .n').textContent=key==='now'?`${ids.length}/${D.depth}`:ids.length;
  const list=col.querySelector('.list');
  const want=new Set(ids);
  [...list.children].forEach(el=>{if(el.dataset.id&&!want.has(el.dataset.id))el.remove()});
  const ph=list.querySelector('.empty');
  if(!ids.length){if(!ph)list.append(E('div',{className:'empty',textContent:emptyMsg(key)}));else ph.textContent=emptyMsg(key);continue}
  if(ph)ph.remove();
  ids.forEach((id,i)=>{
   const rank=key==='now'?i:-1, sig=JSON.stringify([D.tasks[id],rank,D.snap.held[id],pokeOf(id),openKids.has(id)]);
   let c=cards.get(id);
   if(!c||!c.el.isConnected||c.el.parentNode!==list){const el=E('div',{className:'card'});el.dataset.id=id;el.onclick=e=>cardClick(e,id);c={el,sig:''};cards.set(id,c)}
   if(c.sig!==sig){c.sig=sig;c.el.innerHTML=cardHTML(id,rank);c.el.className='card b-'+D.tasks[id].bucket+(D.tasks[id].prio?' p-'+D.tasks[id].prio:'')}
   c.el.classList.toggle('on',sel===id);
   list.append(c.el);   // append moves an existing node → keeps order, no flicker
  });
 }
 if(navIdx>=nav.length)navIdx=nav.length-1;
}

function cardClick(e,id){
 const kb=e.target.closest('[data-kids]');
 if(kb){openKids.has(id)?openKids.delete(id):openKids.add(id);board();return}
 const kid=e.target.closest('.kid[data-go]');
 if(kid){openTask(kid.dataset.go);return}
 openTask(id);
}

/* ---------- quick add ---------- */
function quickAdd(){
 const sig=(D.owners||[]).join()+'|'+(D.me||'');
 if(sig!==lastSigs.qa){lastSigs.qa=sig;
  document.querySelectorAll('.qa .qowner').forEach(sl=>{const cur=sl.value;
   const me=D.me||'web';
   sl.innerHTML=[me,...(D.owners||[]).filter(o=>o!==me)].map(o=>`<option value="${esc(o)}">${esc(o)}</option>`).join('');
   sl.value=cur||me;});}
 document.querySelectorAll('.qa').forEach(f=>{
  if(f.dataset.wired)return;f.dataset.wired='1';
  const bucket=f.closest('.col').dataset.b;
  f.onsubmit=async ev=>{ev.preventDefault();
   const inp=f.querySelector('.qin'),title=inp.value.trim();if(!title)return;
   const fields={title,bucket,owner:f.querySelector('.qowner').value};
   if(bucket==='waiting'){let on=f.querySelector('.qon').value;
    if(on==='delegated:'){const who=prompt('delegated to whom?');if(!who)return;on='delegated:'+who.trim().replace(/\s+/g,'-')}
    fields.on=on;const u=f.querySelector('.quntil').value;if(u)fields.until=u}
   inp.disabled=true;
   const out=await op('add',null,fields);
   inp.disabled=false;
   if(/^T[\d.]+$/.test(out||'')){inp.value='';sel=out.trim();openKids.delete(sel)}
   inp.focus();
  };
 });
}

/* ---------- feed ---------- */
function sameText(txt,t){const a=String(txt||'').toLowerCase();return a&&(a.startsWith(t.stitle.toLowerCase().slice(0,30))||a.startsWith(t.title.toLowerCase().slice(0,30)))}
function feed(){
 const evs=(D.events||[]).filter(e=>{
  if(ftype!=='all'&&e.type!==ftype)return false;
  const t=D.tasks[e.id];
  if(owner!=='all'&&!(t&&t.owner===owner)&&e.by!==owner)return false;
  if(!q)return true;
  return (e.id+' '+e.type+' '+e.by+' '+e.text+' '+(t?t.title:'')).toLowerCase().includes(q)});
 const types=['all',...[...new Set((D.events||[]).map(e=>e.type))].sort()];
 const sig=JSON.stringify([evs.slice(0,200),types,ftype]);
 if(sig===lastSigs.feed)return;lastSigs.feed=sig;
 const tb=$('#ftypes');
 if(tb.dataset.sig!==types.join()+ftype){tb.dataset.sig=types.join()+ftype;
  tb.innerHTML='';types.forEach(ty=>{const c=E('span',{className:'chip'+(ftype===ty?' on':''),textContent:ty});
   c.onclick=()=>{ftype=ty;store.set();lastSigs.feed='';feed()};tb.append(c)})}
 $('#fcount').textContent=`${evs.length} of ${(D.events||[]).length} events`;
 const box=$('#feedb'),keep=box.scrollTop;
 box.innerHTML=evs.length?evs.slice(0,300).map(e=>{const t=D.tasks[e.id];
  return `<div class=frow data-id="${esc(e.id)}"><span class=fts>${shortTs(e.ts)}</span>`+
   `<span class="ty ${esc(e.type)}">${esc(e.type)}</span><span class=fid>${esc(e.id)}</span>`+
   `<span class=own style="--oh:${hue(e.by||'?')}">${esc(e.by||'?')}</span>`+
   `<span class=ftx>${e.text?esc(e.text):'<span class=ftl>(fields updated)</span>'}${t&&!sameText(e.text,t)?` <span class=ftl>· ${esc(t.stitle.slice(0,60))}</span>`:''}</span></div>`}).join('')
  :'<div class=empty>no event matches this filter</div>';
 box.scrollTop=keep;
 box.querySelectorAll('.frow').forEach(r=>r.onclick=()=>{if(D.tasks[r.dataset.id])openTask(r.dataset.id)});
}

/* ---------- drawer ---------- */
function refChips(ids){return ids.length?ids.map(i=>`<span class=ref data-go="${i}">${i}</span>`).join(''):'<span class=v style="color:var(--mute)">—</span>'}
function openTask(id,fromHash){
 if(!D.tasks[id])return;
 sel=id;drawerOn=true;navIdx=nav.indexOf(id);
 if(!fromHash)setHash('#/task/'+id);
 $('#drawer').classList.add('on');$('#drawer').setAttribute('aria-hidden','false');$('#scrim').classList.add('on');
 drawer();board();if(view==='graph')markGraph();
}
function closeDrawer(fromHash){drawerOn=false;if(!fromHash)setHash('#/'+view);$('#drawer').classList.remove('on');$('#drawer').setAttribute('aria-hidden','true');$('#scrim').classList.remove('on')}
function drawer(){
 if(!sel||!D.tasks[sel])return;
 const t=D.tasks[sel],sig=JSON.stringify([sel,t]);
 if(sig===lastSigs.drawer)return;lastSigs.drawer=sig;
 const state=t.closed?`closed · ${t.closed.type}`:t.bucket+(t.on?' · '+t.on:'')+(t.until?' · until '+t.until:'');
 $('#dhd').innerHTML=`<div class=l1><span class=own style="--oh:${hue(t.owner)}">${esc(t.owner)}</span><span class="cid mono" style="color:var(--mute)">${sel}</span><span class=pset title="priority (also: p cycles)">${pbtns(t.prio)}</span>`+
  `<span class="tag ${t.bucket}">${esc(state)}</span><button class=x id=dx title="close (esc)">✕</button></div><h1>${esc(t.stitle)}</h1>`;
 const rows=[
  ['next', t.next?linkify(t.next):'—'],
  ['def', linkify(t.def)],
  ['created', `${shortTs(t.created)} <span style="color:var(--mute)">· last ${shortTs(t.last)} (${ago(t.last)})</span>`],
  ['repo', t.repo?`<code>${esc(t.repo)}</code>`:'—'],
  ['verify', t.verify?`<code>${esc(t.verify)}</code>`:'—'],
 ];
 if(t.closed)rows.push(['evidence', linkify(t.closed.evidence||'—')]);
 let h=`<div class=kv>${rows.map(([k,v])=>`<div class=k>${k}</div><div class=v>${v}</div>`).join('')}</div>`;
 h+=`<h3 class=sec>graph</h3><div class=kv>`+
   `<div class=k>waits on</div><div class="v refs">${refChips(t.deps)}</div>`+
   `<div class=k>blocks</div><div class="v refs">${refChips(t.blocks)}</div>`+
   `<div class=k>parent</div><div class="v refs">${refChips(t.parent?[t.parent]:[])}</div>`+
   `<div class=k>subtasks</div><div class="v refs">${refChips(t.kids)}</div></div>`;
 const refs=[...(t.ev||[]),...(t.urls||[])].filter((v,i,a)=>a.indexOf(v)===i);
 if(refs.length)h+=`<h3 class=sec>evidence</h3><div class=blk>${refs.map(r=>/^https?:/.test(r)?`<a href="${esc(r)}" target=_blank rel=noreferrer>${esc(r)}</a>`:linkify(r)).join('<br>')}</div>`;
 h+=`<h3 class=sec>history · ${t.hist.length}</h3><ul class=hist>${t.hist.slice().reverse().map(e=>
   `<li><span class=ts>${shortTs(e.ts)}</span><span class="ty ${e.type}">${e.type}</span>${e.text?linkify(e.text):'<span style="color:var(--mute)">(fields updated)</span>'}${e.by?`<span class=by>${esc(e.by)}</span>`:''}</li>`).join('')}</ul>`;
 const bd=$('#dbd'),keep=bd.dataset.id===sel?bd.scrollTop:0;
 bd.innerHTML=h;bd.dataset.id=sel;bd.scrollTop=keep;
 $('#dx').onclick=closeDrawer;
 $('#dbd').querySelectorAll('.ref').forEach(r=>r.onclick=()=>openTask(r.dataset.go));
 $('#dhd').querySelectorAll('.ref').forEach(r=>r.onclick=()=>openTask(r.dataset.go));
}

/* ---------- priority ---------- */
const BORDER={now:0,next:1,waiting:2,cold:3};
function prioRow(id){
 const t=D.tasks[id],meta=[`<span class="tag ${t.bucket}">${t.bucket}${t.bucket==='waiting'&&t.on?' · '+esc(t.on):''}${t.until?' → '+t.until:''}</span>`];
 if(pokeOf(id))meta.push('<span class="tag poke">POKE</span>');
 if(D.snap.held[id])meta.push(`<span class="tag hold">⇠ ${D.snap.held[id].join(' ')}</span>`);
 if(t.blocks.length)meta.push(`<span class="tag blocks">⇢ ${t.blocks.join(' ')}</span>`);
 return `<div class="prow b-${t.bucket}${t.prio?' p-'+t.prio:''}${sel===id?' on':''}" data-id="${id}">`+
  `<span class=cid>${id}</span><span class=own style="--oh:${hue(t.owner)}">${esc(t.owner)}</span>`+
  `<div class=pt><div class=ttl>${esc(t.stitle)}</div><div class=nx>${esc(t.next||t.last_line||'')}</div></div>`+
  `<div class=meta>${meta.join('')}</div><span class=pset title="priority (p cycles)">${pbtns(t.prio)}</span></div>`;
}
function pbtns(cur){return ['P0','P1','P2',''].map(v=>`<button class="pbtn ${v||'none'} ${cur===v?'on':''}" data-p="${v||'none'}">${v||'none'}</button>`).join('')}
function prioView(){
 const ids=Object.keys(D.tasks).filter(i=>!D.tasks[i].closed&&match(i));
 const by={P0:[],P1:[],rest:[]};
 ids.forEach(i=>{const p=D.tasks[i].prio;(p==='P0'?by.P0:p==='P1'?by.P1:by.rest).push(i)});
 const ord=(a,b)=>(BORDER[D.tasks[a].bucket]-BORDER[D.tasks[b].bucket])||(D.tasks[a].last<D.tasks[b].last?1:-1);
 for(const k in by)by[k].sort(ord);
 const order=[...by.P0,...by.P1,...by.rest];
 if(view==='prio')nav=order;
 const sig=JSON.stringify([order,sel,order.map(i=>[D.tasks[i].prio,D.tasks[i].bucket,D.tasks[i].on,D.tasks[i].until,D.tasks[i].stitle,D.tasks[i].next,pokeOf(i)])]);
 if(sig===lastSigs.prio)return;lastSigs.prio=sig;
 const box=$('#plist'),keep=box.scrollTop;
 let h='';
 if(!ids.length)h=`<div class=pbanner>no open task matches this filter</div>`;
 else{
  if(!by.P0.length&&!by.P1.length)h+=`<div class=pbanner>No <b>P0</b> or <b>P1</b> right now — everything below is normal priority. Set one from the buttons on a row, or press <b>p</b> on a selected task.</div>`;
  for(const [p,list,hint] of [['P0',by.P0,'drop everything'],['P1',by.P1,'this week'],['P2',by.rest,'normal · P2 or unset']]){
   if(!list.length&&p!=='P2')continue;
   h+=`<div class=pgroup><span class="prio ${p}">${p}</span><span class=hint>${hint}</span><span class=n>${list.length}</span></div>`;
   h+=list.length?list.map(prioRow).join(''):'<div class=empty>none</div>';
  }
 }
 box.innerHTML=h;box.scrollTop=keep;
 box.querySelectorAll('.prow').forEach(r=>r.onclick=e=>{if(!e.target.closest('.pbtn'))openTask(r.dataset.id)});
}

/* ---------- graph ---------- */
function markGraph(){$('#g').querySelectorAll('.n').forEach(n=>n.classList.toggle('sel',n.dataset.id===sel))}
function graph(){
 const ids=Object.keys(D.tasks).filter(i=>!D.tasks[i].closed&&match(i));
 const edges=D.graph.edges.filter(e=>ids.includes(e.from)&&ids.includes(e.to));
 const linked=new Set(edges.flatMap(e=>[e.from,e.to]));
 const nodes=ids.filter(i=>gall||linked.has(i)||D.tasks[i].bucket==='now');
 const sig=JSON.stringify([nodes,edges,gall,nodes.map(i=>D.tasks[i].bucket)]);
 if(sig===lastSigs.graph){markGraph();return}lastSigs.graph=sig;
 const g=$('#g');[...g.querySelectorAll('.n,.e,.msg')].forEach(x=>x.remove());
 if(!nodes.length){g.setAttribute('viewBox','0 0 520 46');g.setAttribute('width',520);g.setAttribute('height',46);
  g.append(SVG('text',{x:10,y:28,class:'msg',fill:'currentColor','font-size':13},
   edges.length?'no tasks match the filter':'no dependency or parent edges among open tasks — try "show unconnected"'));return}
 const lvl={},inc={};nodes.forEach(i=>{lvl[i]=0;inc[i]=0});
 edges.forEach(e=>{if(nodes.includes(e.to))inc[e.to]++});
 let queue=nodes.filter(i=>!inc[i]),seen=new Set();
 while(queue.length){const u=queue.shift();if(seen.has(u))continue;seen.add(u);
  for(const e of edges)if(e.from===u&&nodes.includes(e.to)){lvl[e.to]=Math.max(lvl[e.to],lvl[u]+1);if(--inc[e.to]===0)queue.push(e.to)}}
 const cols={};nodes.slice().sort(ncmp).forEach(i=>(cols[lvl[i]]=cols[lvl[i]]||[]).push(i));
 const W=224,H=44,GX=80,GY=14,PAD=14,MAXROW=12,SUBGAP=16,pos={};
 let x=PAD;
 Object.keys(cols).map(Number).sort((a,b)=>a-b).forEach(l=>{           // wrap a tall layer into sub-columns
  const ids=cols[l],sub=Math.ceil(ids.length/MAXROW),rows=Math.ceil(ids.length/sub);
  ids.forEach((id,i)=>{pos[id]={x:x+Math.floor(i/rows)*(W+SUBGAP),y:PAD+(i%rows)*(H+GY)}});
  x+=sub*(W+SUBGAP)-SUBGAP+GX;});
 const xs=Object.values(pos),maxX=Math.max(...xs.map(p=>p.x))+W+PAD,maxY=Math.max(...xs.map(p=>p.y))+H+PAD;
 g.setAttribute('viewBox',`0 0 ${maxX} ${maxY}`);g.setAttribute('width',maxX);g.setAttribute('height',maxY);
 for(const e of edges){const a=pos[e.from],b=pos[e.to];if(!a||!b)continue;
  g.append(SVG('path',{class:'e '+e.kind,'marker-end':'url(#arrow)',
   d:`M${a.x+W} ${a.y+H/2} C${a.x+W+GX*0.5} ${a.y+H/2},${b.x-GX*0.5} ${b.y+H/2},${b.x-4} ${b.y+H/2}`}))}
 for(const id of nodes){const t=D.tasks[id],p=pos[id];
  const grp=SVG('g',{class:'n '+t.bucket,transform:`translate(${p.x},${p.y})`},
   SVG('rect',{width:W,height:H,rx:8}),SVG('rect',{class:'accent',width:3,height:H,rx:1.5}),
   SVG('text',{x:11,y:17},`${id} [${t.owner}]`),
   SVG('text',{x:11,y:32,class:'sub'},t.stitle.slice(0,30)+(t.stitle.length>30?'…':'')));
  grp.dataset.id=id;grp.style.cursor='pointer';grp.onclick=()=>openTask(id);g.append(grp)}
 markGraph();
}

/* ---------- archive ---------- */
function archive(){
 const ids=D.snap.closed.filter(match);
 const sig=JSON.stringify(ids);if(sig===lastSigs.arc)return;lastSigs.arc=sig;
 const b=$('#arcb');
 if(!ids.length){b.innerHTML='<tr><td class=empty>no closed tasks match</td></tr>';return}
 b.innerHTML=ids.slice(0,300).map(id=>{const t=D.tasks[id],c=t.closed;
  return `<tr data-id="${id}"><td class=d>${c.ts.slice(0,10)}</td><td class=i>${id}</td><td><span class=own style="--oh:${hue(t.owner)}">${esc(t.owner)}</span></td>`+
   `<td><span class="badge ${c.type}">${c.type}</span></td><td><div class=t>${esc(t.stitle)}</div>`+
   (c.evidence?`<div class=e>${linkify(c.evidence)}</div>`:'')+`</td></tr>`}).join('')
  +(ids.length>300?`<tr><td colspan=5 class=empty>+${ids.length-300} older</td></tr>`:'');
 b.querySelectorAll('tr[data-id]').forEach(r=>r.onclick=e=>{if(e.target.tagName!=='A')openTask(r.dataset.id)});
}

/* ---------- views + keys ---------- */
function setView(v,fromHash){view=v;$('#bks').hidden=v!=='board';$('#flt').hidden=!(v==='board'||v==='prio');$('#board').hidden=v!=='board';$('#prio').hidden=v!=='prio';$('#graph').hidden=v!=='graph';$('#archive').hidden=v!=='archive';$('#feed').hidden=v!=='feed';
 $('#tabs').querySelectorAll('button').forEach(b=>b.classList.toggle('on',b.dataset.v===v));store.set();
 if(!fromHash){if(drawerOn)closeDrawer(true);setHash('#/'+v)}   // a tab click means 'go to this view', so the drawer lets go of the URL
 render()}
function setHash(h){if(location.hash===h)return;routing=true;location.hash=h;setTimeout(()=>{routing=false},0)}
function applyHash(){
 if(routing||!D)return;
 const h=(location.hash||'').replace(/^#\/?/,'');
 if(!h){setHash('#/'+view);return}          // no route in the URL: keep the remembered view and publish it
 const m=/^task\/(T[\d.]+)$/.exec(h);
 if(m){if(D.tasks[m[1]])openTask(m[1],true);return}
 if(drawerOn)closeDrawer(true);
 const v=VIEWS.includes(h)?h:'board';
 if(v!==view)setView(v,true);
}
window.addEventListener('hashchange',applyHash);
function render(){if(!D)return;pills();owners();bucketChips();board();
 quickAdd();if(view==='prio')prioView();if(view==='graph')graph();if(view==='archive')archive();if(view==='feed')feed();if(drawerOn)drawer()}
function moveSel(d){
 if(view!=='board'&&view!=='prio')return;
 if(!nav.length)return;
 navIdx=Math.max(0,Math.min(nav.length-1,navIdx<0?0:navIdx+d));
 sel=nav[navIdx];
 if(view==='prio')prioView();else board();
 const el=view==='prio'?$(`#plist .prow[data-id="${sel}"]`):cards.get(sel)?.el;
 if(el)el.scrollIntoView({block:'nearest'});
 if(drawerOn){lastSigs.drawer='';drawer()}
}
async function op(cmd,args,fields){try{
 const r=await fetch('/op',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cmd,args,fields})});
 const j=await r.json();toast(j.ok?j.out:('error: '+j.out));
 if(j.ok){raw='';await tick()}
 return j.ok?j.out:''}catch(e){toast('op failed: '+e);return''}}
function toast(m){let t=document.getElementById('toast');if(!t){t=document.createElement('div');t.id='toast';t.className='toast';document.body.append(t)}t.textContent=m;t.classList.add('show');clearTimeout(toast._h);toast._h=setTimeout(()=>t.classList.remove('show'),1800)}
document.addEventListener('click',e=>{const b=e.target.closest('.pbtn');if(!b)return;e.stopPropagation();
 const id=b.closest('[data-id]')?.dataset.id||sel;if(id)op('prio',[id,b.dataset.p])});
const PCYCLE=['P0','P1','P2',''];
document.addEventListener('keydown',e=>{
 const typing=/^(INPUT|TEXTAREA)$/.test(e.target.tagName);
 if(e.key==='Escape'){if(!$('#cheat').hidden){$('#cheat').hidden=true;return}if(typing){e.target.blur();return}closeDrawer();return}
 if(typing)return;
 if(e.key==='?'){e.preventDefault();$('#cheat').hidden=!$('#cheat').hidden;return}
 if(e.key==='/'){e.preventDefault();$('#q').focus();return}
 if(e.key==='j'||e.key==='ArrowDown'){e.preventDefault();moveSel(1)}
 else if(e.key==='k'||e.key==='ArrowUp'){e.preventDefault();moveSel(-1)}
 else if(e.key==='Enter'){if(sel)openTask(sel)}
 else if(e.key==='p'&&sel&&D.tasks[sel]){const cur=D.tasks[sel].prio||'';const nx=PCYCLE[(PCYCLE.indexOf(cur)+1)%PCYCLE.length];op('prio',[sel,nx||'none'])}
 else if(e.key==='1')setView('board');else if(e.key==='2')setView('prio');else if(e.key==='3')setView('graph');else if(e.key==='4')setView('archive');else if(e.key==='5')setView('feed');
 else if(e.key==='n'){e.preventDefault();if(view!=='board')setView('board');const i=$('.col[data-b=next] .qin');if(i)i.focus()}
});
$('#q').oninput=e=>{q=e.target.value.trim().toLowerCase();lastSigs.graph='';lastSigs.arc='';lastSigs.prio='';lastSigs.feed='';render()};
$('#cheat').onclick=e=>{if(e.target.id==='cheat')$('#cheat').hidden=true};
$('#readyonly').classList.toggle('on',readyOnly);
$('#readyonly').onclick=()=>{readyOnly=!readyOnly;$('#readyonly').classList.toggle('on',readyOnly);store.set();
 lastSigs.graph='';lastSigs.arc='';lastSigs.prio='';lastSigs.feed='';render()};
$('#scrim').onclick=closeDrawer;
$('#tabs').querySelectorAll('button').forEach(b=>b.onclick=()=>setView(b.dataset.v));
$('#gall').onclick=()=>{gall=!gall;$('#gall').classList.toggle('on',gall);store.set();lastSigs.graph='';graph()};
$('#gall').classList.toggle('on',gall);setView(view,true);   // the URL, not the stored view, wins on load — see applyHash

/* ---------- poll ---------- */
async function tick(){
 try{
  const r=await fetch('/data',{cache:'no-store'});const txt=await r.text();
  $('#dot').classList.remove('bad');
  $('#upd').textContent='updated '+new Date().toLocaleTimeString();
  if(txt===raw)return;
  raw=txt;D=JSON.parse(txt);
  if(sel&&!D.tasks[sel]){sel=null;closeDrawer(true)}
  lastSigs.drawer='';render();
  if(!tick.first){tick.first=1;applyHash()}
 }catch(err){$('#dot').classList.add('bad');$('#upd').textContent='offline — '+err}
}
tick();setInterval(tick,1500);
</script></html>"""

URL = re.compile(r"https?://[^\s<)\"']+")
OWNER = re.compile(r"^\[([A-Za-z])\]\s*")
HIST_MAX = 120
FEED_MAX = 500


def owner_of(title):
    m = OWNER.match(title or "")
    return m.group(1).upper() if m else "M"


def data():
    ev, tasks, stack, _ = L.load()
    snap = L.snapshot(tasks, stack)
    op = L.open_tasks(tasks)
    blocks = {}
    for t, v in op.items():
        for d in v["deps"]:
            blocks.setdefault(d, []).append(t)
    out = {}
    for t, v in tasks.items():
        logs = [e for e in v["hist"] if e["type"] in ("log", "amend")]
        nxt = logs[-1].get("text", "") if logs else ""
        urls = list(dict.fromkeys(URL.findall(v["def"] + " " + " ".join(e.get("text", "") for e in v["hist"]))))
        p = L.parent_of(t)
        out[t] = {"title": v["title"], "stitle": OWNER.sub("", v["title"]), "owner": v.get("owner") or owner_of(v["title"]) or "-", "prio": v.get("prio",""),
                  "def": v["def"], "bucket": v["bucket"], "on": v["on"], "until": v["until"], "repo": v["repo"], "verify": v["verify"],
                  "deps": v["deps"], "ev": v["ev"], "urls": urls, "next": nxt, "last_line": L.last_line(v),
                  "blocks": blocks.get(t, []), "kids": L.children(tasks, t), "kids_all": L.children(tasks, t, only_open=False), "parent": p if p in tasks else "",
                  "ready": bool(not v["closed"] and v["bucket"] != "waiting" and not L.open_deps(tasks, t)),
                  "created": v["created"], "last": v["last"], "closed": v["closed"],
                  "hist": [{"ts": e["ts"], "type": e["type"], "by": e.get("by", ""),
                            "text": e.get("text") or e.get("evidence") or (e.get("bucket", "") + (" " + e.get("on", "") if e.get("on") else ""))}
                           for e in v["hist"][-HIST_MAX:]]}
    snap["closed"] = sorted((t for t, v in tasks.items() if v["closed"]), key=lambda t: tasks[t]["closed"]["ts"], reverse=True)
    feed = [{"ts": e["ts"], "id": e.get("id", ""), "type": e.get("type", ""), "by": e.get("by", ""),
             "text": e.get("text") or e.get("evidence") or e.get("title") or (e.get("bucket", "") + (" " + e.get("on", "") if e.get("on") else ""))}
            for e in ev if e.get("type") != "alias"][-FEED_MAX:][::-1]
    edges = []
    for t, v in op.items():
        edges += [{"from": d, "to": t, "kind": "dep"} for d in v["deps"] if d in op]
        if (p := L.parent_of(t)) in op:
            edges.append({"from": p, "to": t, "kind": "parent"})
    return {"header": f"now {len(snap['now'])}/{L.NOW_DEPTH} · next {len(snap['next'])} · waiting {len(snap['waiting'])} ({len(snap['pokes'])} pokes) · cold {len(snap['cold'])} · open {len(op)}",
            "depth": L.NOW_DEPTH, "gen": L.ts(), "snap": snap, "graph": {"edges": edges}, "tasks": out,
            "events": feed, "owners": sorted({v["owner"] for v in out.values() if v["owner"]}),
            "me": os.environ.get("LEDGER_OWNER", "web")}

class H(http.server.BaseHTTPRequestHandler):
    good = b"{}"
    def log_message(self, *a):
        pass
    def do_GET(self):
        if self.path.startswith("/data"):
            try:
                H.good = json.dumps(data(), ensure_ascii=False).encode()
            except Exception:
                pass  # mid-write tear: serve the last good read
            body, ctype = H.good, "application/json"
        else:
            body, ctype = PAGE.replace("__GH_ORG__", os.environ.get("LEDGER_GH_ORG", "")).encode(), "text/html; charset=utf-8"
        self.send_response(200); self.send_header("Content-Type", ctype); self.send_header("Cache-Control", "no-store"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

SAFE = re.compile(r"[\w.-]{1,40}")                                        # ids, priorities, owner names
ON_RE = re.compile(r"user|ext|delegated:[\w.-]{1,30}|watching(?::[\w.-]{1,30})?")
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")

def argv_prio(req):
    args = [str(x) for x in req.get("args", [])]
    if len(args) != 2 or not all(SAFE.fullmatch(x) for x in args):
        raise ValueError("prio takes <id> <P0|P1|P2|none>")
    return ["prio", *args, "--note", "via web"]

def argv_add(req):
    f = req.get("fields") or {}
    title = " ".join(str(f.get("title", "")).split())
    if not 1 <= len(title) <= 200:
        raise ValueError("title must be 1-200 characters")
    bucket = str(f.get("bucket", "next"))
    if bucket not in L.BUCKETS:
        raise ValueError(f"bucket must be one of {', '.join(L.BUCKETS)}")
    out = ["add", title, "--bucket", bucket]
    if owner := str(f.get("owner", "") or ""):
        if not SAFE.fullmatch(owner):
            raise ValueError("bad owner")
        out += ["--owner", owner]
    if bucket == "waiting":                                                # the CLI enforces this too; fail early with a better message
        on = str(f.get("on", "") or "")
        if not ON_RE.fullmatch(on):
            raise ValueError("waiting needs on = user | ext | delegated:<name> | watching[:<what>]")
        out += ["--on", on]
        if until := str(f.get("until", "") or ""):
            if not DATE_RE.fullmatch(until):
                raise ValueError("until must be YYYY-MM-DD")
            out += ["--until", until]
    return out

OPS = {"prio": argv_prio, "add": argv_add}  # every write still goes through the CLI, so its own rules apply

class H(H):
    def do_POST(self):
        if self.path != "/op":
            self.send_response(404); self.end_headers(); return
        n = int(self.headers.get("Content-Length", "0"))
        try:
            req = json.loads(self.rfile.read(n) or b"{}")
            cmd = req.get("cmd")
            if cmd not in OPS:
                raise ValueError("bad op")
            argv = OPS[cmd](req)
            env = dict(os.environ, LEDGER_BY="web", LEDGER_OWNER=os.environ.get("LEDGER_OWNER", "web"))
            r = subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "ledger.py"), *argv], capture_output=True, text=True, env=env, timeout=30)
            body = json.dumps({"ok": r.returncode == 0, "out": (r.stdout + r.stderr).strip()[-300:]}).encode()
        except Exception as e:
            body = json.dumps({"ok": False, "out": str(e)}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--port", type=int, default=9099); ap.add_argument("--open", action="store_true"); ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    if a.check:
        d = data(); print(f"ok: {len(d['tasks'])} tasks ({len(d['snap']['closed'])} closed), {len(d['graph']['edges'])} edges"); sys.exit(0)
    if a.open:
        webbrowser.open(f"http://127.0.0.1:{a.port}/")
    print(f"http://127.0.0.1:{a.port}/  ({L.HOME})")
    http.server.ThreadingHTTPServer(("127.0.0.1", a.port), H).serve_forever()
