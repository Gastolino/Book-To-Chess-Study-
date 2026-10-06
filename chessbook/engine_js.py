"""Analysis with Stockfish in the chapter reader.

ENGINE_CSS styles the eval bar beside the board, the analysis section
between the board's controls and the line's title, and the settings;
ENGINE_JS is the part of the chapter page's script that loads the engine
(chessbook/engine_files.py: Stockfish.js 19, lite single-threaded build,
GPLv3) in a Web Worker the first time analysis is turned on, keeps its two
files in the browser's storage so that it runs offline afterwards, speaks
UCI with it, and shows what it finds. Both are joined into the chapter page
by chessbook/reader.py, where the board, the move tree and the board-move
chooser live that this script talks to (renderBoard, selectNode, moveSource,
boardMove).

The engine runs on the reader's device and sends nothing anywhere. It
analyses the position the board shows, whatever it is: a move of the book,
a variation the reader added, or the preview of a move just made. Stepping
through moves restarts the search after a short pause; leaving the chapter,
hiding the tab or turning analysis off stops it, so that it drains no phone.

What the engine finds is kept (the analysis cache): for each position (its
FEN without the move counters) and number of lines, the deepest result so
far, in the browser's IndexedDB "chessbook-analysis" (in memory only where
the browser keeps none), at most ANALYSIS_KEEP positions, the ones used
longest ago going first. A position shown again shows its kept result at
once, and the engine searches it only when the limit in the settings asks
for more than the kept result reached; "Deeper" always searches.
"""

ENGINE_CSS = r"""
.boardrow{display:flex;align-items:stretch;gap:8px;margin:0 auto;max-width:min(100%,calc(100vh - 140px))}
.boardrow > .boardwrap{flex:1 1 auto;min-width:0;margin:0;max-width:none}
.evalbar{flex:none;width:28px;position:relative}
.evalbar[hidden]{display:none}
.evalbar .ebar{position:absolute;left:0;top:0.27%;height:96%;width:7px;border:1px solid var(--line);
background:var(--board-dark);overflow:hidden}
.evalbar .ebar i{position:absolute;left:0;right:0;bottom:0;height:50%;background:var(--board-light);
transition:height .25s}
.evalbar.flip .ebar i{bottom:auto;top:0}
.evalbar .enum{position:absolute;left:0;bottom:0;font-family:"Geist Mono",ui-monospace,Menlo,Consolas,monospace;
font-size:10px;line-height:1.25;color:var(--muted);white-space:nowrap;font-variant-numeric:tabular-nums;
font-variant-ligatures:none}
#bcpu[aria-pressed="true"],#mcpu[aria-pressed="true"],#bgear[aria-pressed="true"]{color:var(--accent)}
.evhead{display:flex;align-items:baseline;justify-content:space-between;gap:8px 16px;flex-wrap:wrap}
.evstatus{font-variant-numeric:tabular-nums;min-width:0}
.evhead .tb{font-size:13px;flex:none}
.evlines{list-style:none;margin:6px 0 0;padding:0;display:grid;gap:0}
.evlines:empty{display:none}
.evlines li{min-width:0}
.evline{display:flex;align-items:baseline;gap:12px;width:100%;max-width:100%;min-width:0;background:none;border:0;border-radius:0;
padding:0;margin:0;text-align:left;cursor:pointer;color:var(--fg);font:inherit;
font-family:"Geist Mono",ui-monospace,Menlo,Consolas,monospace;font-size:15px;line-height:1.7;
font-variant-ligatures:none}
.evline .esc{flex:none;min-width:3.6em;font-weight:500;font-variant-numeric:tabular-nums}
.evline .epv{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--muted)}
.evline .epv .efirst{color:var(--fg);font-weight:500;text-underline-offset:3px;text-decoration-thickness:1px}
.evline:hover .efirst{text-decoration:underline}
.evline:hover .esc{color:var(--accent)}
.evline[aria-disabled="true"]{cursor:default}
.evline[aria-disabled="true"]:hover .efirst{text-decoration:none}
.evline[aria-disabled="true"]:hover .esc{color:var(--fg)}
.evset{display:grid;gap:8px}
.evset .row{display:grid;grid-template-columns:7em minmax(0,1fr);align-items:baseline;gap:4px 16px}
.evset .lab{color:var(--muted)}
.evset .opts{display:flex;flex-wrap:wrap;gap:4px 16px;min-width:0}
.evset .tb[aria-pressed="true"]{color:var(--accent);text-decoration:underline}
.evfoot{color:var(--muted);border-top:1px solid var(--line);padding-top:8px;margin-top:4px}
.meval{flex:none;font-family:"Geist Mono",ui-monospace,Menlo,Consolas,monospace;font-variant-ligatures:none;
font-variant-numeric:tabular-nums;color:var(--muted)}
.meval:empty{display:none}
svg.board .eva{fill:none;stroke:var(--accent);stroke-width:4px;stroke-linecap:round;opacity:.6}
svg.board .evh{fill:var(--accent);opacity:.6}
@media (max-width:700px){.boardrow{max-width:none}}
"""

ENGINE_JS = r"""
/* ---------------------------------------------------------------- analysis with Stockfish */
// The engine's files: the browser app names where they are (window.CHESSBOOK_ENGINE, an
// absolute address, since the reader runs from a blob address there); a reader built from the
// command line finds them in engine/ beside it when make_reader copied them.
const ENGINE_BASE = window.CHESSBOOK_APP ? (window.CHESSBOOK_ENGINE || null) : (D.engine ? "engine/" : null);
const ENGINE = {js: "stockfish-19-lite-single.js", wasm: "stockfish-19-lite-single.wasm", version: "19.0.0",
  db: "chessbook-engine", name: "Stockfish 19", build: "Stockfish.js by Nathan Rugg, lite single-threaded build"};
const EV_KEY = "chessbook-engine";
const EV_DEFAULT = {lines: 3, limit: "d18", auto: true, arrow: false, hash: 16};
const EV_LIMITS = [["d12", "depth 12"], ["d18", "depth 18"], ["d24", "depth 24"],
                   ["t1", "1 second"], ["t3", "3 seconds"], ["t10", "10 seconds"]];
const EV = {on: false, worker: null, ready: false, searching: false, stopping: false, fen: null, want: null,
  lines: [], depth: 0, nps: 0, done: false, deeper: 0, timer: 0, raf: 0, loading: false, failed: "", name: "",
  urls: [], settings: null, ran: null, hidden: false, from: null, loadMs: null, t0: 0, ended: "",
  cached: false, floor: 0, st: 0};

/* the analysis cache: the deepest result for each position and number of lines */
const ANALYSIS_KEEP = 5000;
const EVC = {mem: new Map(), db: null, puts: 0, hits: 0};
window.analysisCache = EVC;
function evKey(fen){ return fen.split(" ").slice(0, 4).join(" ") + "|" + EV.settings.lines; }
function evCacheDb(){
  if (!EVC.db) {
    EVC.db = new Promise((res, rej) => {
      if (!window.indexedDB) { rej(new Error("no storage")); return; }
      let r;
      try { r = indexedDB.open("chessbook-analysis", 1); } catch (e) { rej(e); return; }
      r.onupgradeneeded = () => {
        const st = r.result.createObjectStore("positions");
        st.createIndex("at", "at");
      };
      r.onsuccess = () => res(r.result);
      r.onerror = () => rej(r.error || new Error("no storage"));
      r.onblocked = () => rej(new Error("storage blocked"));
    });
    EVC.db.catch(() => {});
  }
  return EVC.db;
}
function evMem(key, rec){
  EVC.mem.delete(key);
  EVC.mem.set(key, rec);
  if (EVC.mem.size > 500) EVC.mem.delete(EVC.mem.keys().next().value);
}
async function evCacheGet(fen){
  const key = evKey(fen);
  if (EVC.mem.has(key)) { const r = EVC.mem.get(key); evMem(key, r); return r; }
  try {
    const db = await evCacheDb();
    const rec = await new Promise((res) => {
      const t = db.transaction("positions", "readwrite"), st = t.objectStore("positions"), q = st.get(key);
      q.onsuccess = () => {
        const r = q.result || null;
        if (r) { r.at = Date.now(); st.put(r, key); }      // used now: the last to go
        res(r);
      };
      q.onerror = () => res(null);
    });
    if (rec) evMem(key, rec);
    return rec;
  } catch (e) { return null; }
}
async function evCachePut(fen, rec){
  const key = evKey(fen), old = EVC.mem.get(key);
  if (old && old.depth >= rec.depth && old.ms >= rec.ms) return;
  rec.at = Date.now();
  evMem(key, rec);
  try {
    const db = await evCacheDb();
    const t = db.transaction("positions", "readwrite"), st = t.objectStore("positions");
    const q = st.get(key);
    q.onsuccess = () => { const o = q.result; if (!o || o.depth < rec.depth || (o.depth === rec.depth && o.ms < rec.ms)) st.put(rec, key); };
    EVC.puts++;
    if (EVC.puts % 50 === 1) {
      // more than ANALYSIS_KEEP positions: the ones used longest ago go
      const c = st.count();
      c.onsuccess = () => {
        let extra = c.result - ANALYSIS_KEEP;
        if (extra <= 0) return;
        st.index("at").openCursor().onsuccess = (e) => {
          const cur = e.target.result;
          if (!cur || extra-- <= 0) return;
          cur.delete();
          cur.continue();
        };
      };
    }
  } catch (e) { /* no storage: the memory keeps it while the page lives */ }
}
// a kept result is enough when it reached the limit the settings ask for
function evEnough(rec){
  const l = EV.settings.limit;
  if (l[0] === "d") return rec.depth >= parseInt(l.slice(1), 10);
  return rec.ms >= 0.95 * parseInt(l.slice(1), 10) * 1000 || rec.depth >= 40;
}
function evKeep(){
  // the search ends or stops: its deepest result is kept for the position
  if (!EV.fen || !EV.lines[0] || !EV.lines[0].pv.length || EV.ended) return;
  const lines = EV.lines.filter(Boolean).map(l => ({depth: l.depth, score: l.score, pv: l.pv.slice(0, 16)}));
  evCachePut(EV.fen, {depth: EV.lines[0].depth, lines, ms: Math.round(performance.now() - EV.st)});
}

function evLoadSettings(){
  let s = {};
  try { s = JSON.parse(localStorage.getItem(EV_KEY) || "{}") || {}; } catch (e) { s = {}; }
  const out = Object.assign({}, EV_DEFAULT);
  if (s.lines >= 1 && s.lines <= 5) out.lines = Math.round(s.lines);
  if (EV_LIMITS.some(l => l[0] === s.limit)) out.limit = s.limit;
  if (typeof s.auto === "boolean") out.auto = s.auto;
  if (typeof s.arrow === "boolean") out.arrow = s.arrow;
  if (s.hash === 16 || s.hash === 32) out.hash = s.hash;
  return out;
}
function evSaveSettings(){
  try { localStorage.setItem(EV_KEY, JSON.stringify(EV.settings)); } catch (e) { /* no storage */ }
}

/* the files: kept in the browser's storage after the first fetch, so that the engine loads offline */
function evDb(){
  return new Promise((res, rej) => {
    if (!window.indexedDB) { rej(new Error("no storage")); return; }
    const r = indexedDB.open(ENGINE.db, 1);
    r.onupgradeneeded = () => { if (!r.result.objectStoreNames.contains("files")) r.result.createObjectStore("files"); };
    r.onsuccess = () => res(r.result);
    r.onerror = () => rej(r.error || new Error("no storage"));
    r.onblocked = () => rej(new Error("storage blocked"));
  });
}
async function evStored(){
  try {
    const db = await evDb();
    return await new Promise((res, rej) => {
      const t = db.transaction("files", "readonly"), r = t.objectStore("files").get(ENGINE.version);
      r.onsuccess = () => { res(r.result || null); db.close(); };
      r.onerror = () => { rej(r.error); db.close(); };
    });
  } catch (e) { return null; }
}
async function evStore(files){
  try {
    const db = await evDb();
    await new Promise((res, rej) => {
      const t = db.transaction("files", "readwrite");
      t.objectStore("files").put(files, ENGINE.version);
      t.oncomplete = () => { res(); db.close(); };
      t.onerror = () => { rej(t.error); db.close(); };
      t.onabort = () => { rej(t.error); db.close(); };
    });
  } catch (e) { /* no storage: the files are fetched again next time */ }
}
async function evFiles(){
  const kept = await evStored();
  if (kept && kept.js && kept.wasm) { EV.from = "storage"; return kept; }
  if (!ENGINE_BASE) throw new Error("The engine is not installed.");
  const get = async (name) => {
    const r = await fetch(ENGINE_BASE + name);
    if (!r.ok) throw new Error("the server answered " + r.status + " for " + name);
    return r.arrayBuffer();
  };
  const [js, wasm] = await Promise.all([get(ENGINE.js), get(ENGINE.wasm)]);
  const files = {js, wasm};
  EV.from = "network";
  await evStore(files);
  return files;
}

/* the worker: Stockfish.js takes UCI commands as messages and answers one line a message */
function evSend(cmd){ if (EV.worker) EV.worker.postMessage(cmd); }
async function evStart(){
  if (EV.worker || EV.loading) return;
  EV.loading = true; EV.failed = "";
  evStatus();
  const t0 = performance.now();
  let files;
  try { files = await evFiles(); }
  catch (e) {
    EV.loading = false;
    EV.failed = ENGINE_BASE ? "The engine could not be loaded: " + (e && e.message ? e.message : e) + "." :
      "The engine is not installed beside this reader.";
    evStatus();
    return;
  }
  if (!EV.on) { EV.loading = false; return; }
  const jsUrl = URL.createObjectURL(new Blob([files.js], {type: "text/javascript"}));
  const wasmUrl = URL.createObjectURL(new Blob([files.wasm], {type: "application/wasm"}));
  EV.urls = [jsUrl, wasmUrl];
  // the loader reads the address of its .wasm from its own address's hash
  let w;
  try { w = new Worker(jsUrl + "#" + encodeURIComponent(wasmUrl)); }
  catch (e) {
    EV.loading = false; EV.failed = "The engine could not be started: " + (e && e.message ? e.message : e) + ".";
    evStatus(); return;
  }
  EV.worker = w;
  w.onmessage = (e) => evLine(String(e.data));
  w.onerror = (e) => {
    EV.failed = "The engine stopped: " + (e && e.message ? e.message : "it could not run in this browser") + ".";
    evStop(true); evStatus();
  };
  EV.t0 = t0;
  evSend("uci");
}
function evKill(){
  if (EV.worker) { try { EV.worker.terminate(); } catch (e) { /* gone */ } }
  EV.worker = null; EV.ready = false; EV.searching = false; EV.loading = false; EV.want = null;
  for (const u of EV.urls) { try { URL.revokeObjectURL(u); } catch (e) { /* gone */ } }
  EV.urls = [];
}
function evLine(line){
  if (line.indexOf("id name ") === 0) { EV.name = line.slice(8).trim(); return; }
  if (line === "uciok") {
    evSend("setoption name MultiPV value " + EV.settings.lines);
    evSend("setoption name Hash value " + EV.settings.hash);
    evSend("isready");
    return;
  }
  if (line === "readyok") {
    EV.ready = true; EV.loading = false;
    EV.loadMs = Math.round(performance.now() - EV.t0);
    window.engineLoaded = {ms: EV.loadMs, from: EV.from, name: EV.name};
    evStatus();
    evGo();
    return;
  }
  if (line.indexOf("bestmove") === 0) {
    evKeep();
    EV.searching = false; EV.stopping = false;
    if (EV.want) { const f = EV.want; EV.want = null; evSearch(f); }
    else { EV.done = true; evStatus(); }
    return;
  }
  if (line.indexOf("info ") === 0 && EV.searching) evInfo(line);
}
function evInfo(line){
  // "info depth 14 seldepth 20 multipv 2 score cp 31 nodes 123 nps 400000 ... pv e2e4 e7e5"
  const t = line.split(" ");
  if (t.indexOf("lowerbound") >= 0 || t.indexOf("upperbound") >= 0) return;
  const at = (k) => { const i = t.indexOf(k); return i >= 0 ? t[i + 1] : null; };
  const pvAt = t.indexOf("pv");
  if (pvAt < 0 || at("depth") == null || !EV.fen) return;
  const k = parseInt(at("multipv") || "1", 10) - 1;
  const depth = parseInt(at("depth"), 10);
  if (k === 0) EV.depth = Math.max(depth, EV.floor);
  // a kept result shows until the search goes deeper than it
  if (depth <= EV.floor) return;
  EV.cached = false;
  const si = t.indexOf("score");
  if (si < 0) return;
  // the score is from the side to move's view: it is turned to White's
  const black = (EV.fen.split(" ")[1] || "w") === "b", sign = black ? -1 : 1;
  const score = t[si + 1] === "mate" ? {mate: sign * parseInt(t[si + 2], 10)} : {cp: sign * parseInt(t[si + 2], 10)};
  EV.lines[k] = {depth, score, pv: t.slice(pvAt + 1)};
  const nps = parseInt(at("nps") || "0", 10);
  if (nps) EV.nps = nps;
  evRender();
}

/* what the board shows, and when to search */
function shownFen(){
  // the position the board shows (the board of a diagram, a preview, a move, the position
  // before a gap, the start of the line), or null when it shows no position
  if (S.diagram) { const [, d] = diagramInfo(S.diagram); return d && d.fen ? d.fen : null; }
  if (S.preview) return S.preview.fen;
  const n = S.node ? D.nodes[S.node] : null;
  if (n && n.fen) return n.fen;
  const known = n ? beforeGap(S.node) : null;
  if (known) return nodeFen(known);
  const L = S.line ? D.lines[S.line] : null;
  if (!n && L && nodeFen(L.root)) return nodeFen(L.root);
  return null;
}
function evLimit(){
  const l = EV.settings.limit, k = EV.deeper;
  if (l[0] === "d") return "depth " + (parseInt(l.slice(1), 10) + 8 * k);
  return "movetime " + (parseInt(l.slice(1), 10) * 1000 * Math.pow(4, k));
}
function evSearch(fen){
  // the position changes: the search in progress is stopped first, and the new one starts
  // when the engine has answered with its best move
  if (!EV.worker || !EV.ready) return;
  if (EV.searching) { EV.want = fen; if (!EV.stopping) { EV.stopping = true; evSend("stop"); } return; }
  EV.stopping = false;
  const kept = EV.fen === fen && EV.cached;
  EV.floor = kept && EV.lines[0] ? EV.lines[0].depth : 0;
  EV.st = performance.now();
  EV.fen = fen; EV.lines = kept ? EV.lines : []; EV.depth = EV.floor; EV.done = false; EV.searching = true;
  evSend("position fen " + fen);
  evSend("go " + evLimit());
  evRender(); evStatus();
}
function evGo(){
  // analyse the shown position (after a short pause while the reader steps through moves)
  clearTimeout(EV.timer);
  if (!EV.on || EV.hidden) return;
  const fen = shownFen();
  const halt = () => { if (EV.searching) { EV.want = null; if (!EV.stopping) { EV.stopping = true; evSend("stop"); } }
    EV.fen = null; EV.lines = []; evRender(); evStatus(); };
  if (!fen) { halt(); return; }
  if (fen === (EV.want || EV.fen) && (EV.searching || EV.done)) { evRender(); return; }
  if (!CJ.legalMoves(fen).length) {
    // checkmate or stalemate: nothing to search; the bar shows the result
    halt();
    const mated = CJ.inCheck(fen), white = (fen.split(" ")[1] || "w") === "w";
    EV.fen = fen; EV.done = true; EV.depth = 0;
    EV.lines = mated ? [{depth: 0, score: {mate: white ? -0 : 0, mated: white ? "w" : "b"}, pv: []}] : [{depth: 0, score: {cp: 0}, pv: []}];
    EV.ended = mated ? "Checkmate: " + (white ? "Black" : "White") + " has won." : "Stalemate: the game is drawn.";
    evRender(); evStatus(); return;
  }
  EV.ended = "";
  // set to analyse on demand, only the position shown when the icon was pressed is analysed
  if (!EV.settings.auto && fen !== EV.ran) { halt(); return; }
  EV.deeper = 0;
  const go = () => { EV.timer = setTimeout(() => { if (EV.on && !EV.hidden) evSearch(fen); }, 250); };
  if (EV.searching) { go(); return; }
  // what the engine found here before shows at once; the engine searches when it asks for more
  evCacheGet(fen).then((rec) => {
    if (!EV.on || EV.hidden || shownFen() !== fen || EV.searching) return;
    if (!rec) { EV.cached = false; go(); return; }
    EVC.hits++;
    EV.fen = fen; EV.cached = true; EV.depth = rec.depth;
    EV.lines = rec.lines.map(l => ({depth: l.depth, score: l.score, pv: l.pv.slice()}));
    EV.done = evEnough(rec);
    evRender(); evStatus();
    if (!EV.done) go();
  });
}
function evStop(dead){
  clearTimeout(EV.timer);
  if (EV.worker && EV.searching && !dead) evSend("stop");
  evKill();
}
function evShown(){
  // called by renderBoard: the eval bar follows the board, and the search follows the position
  const bar = $("evalbar");
  if (bar) bar.hidden = !EV.on;
  if (!EV.on) return;
  evGo();
  evArrow();
}
function setAnalysis(on){
  EV.on = on;
  for (const id of ["bcpu", "mcpu"]) { const b = $(id); if (b) b.setAttribute("aria-pressed", String(on)); }
  $("evalsec").hidden = !on;
  $("evalbar").hidden = !on;
  if (!on) {
    evStop();
    EV.fen = null; EV.lines = []; EV.ran = null; EV.failed = "";
    $("mevalnum").textContent = "";
    evArrow(); evRender(); evStatus();
    if (!$("evset").hidden) toggleSettings(false);
    layoutPanel(false);
    return;
  }
  EV.ran = shownFen();
  evStatus();
  if (!EV.worker) evStart(); else evGo();
  layoutPanel(false);
}
function pressCpu(){
  // the icon turns analysis on and off; set to analyse only on demand, a press while it is on
  // analyses the position now shown
  if (EV.on && !EV.settings.auto) {
    const fen = shownFen();
    if (fen && fen !== EV.ran) { EV.ran = fen; EV.deeper = 0; EV.fen = null; EV.done = false; evGo(); return; }
  }
  setAnalysis(!EV.on);
}

/* what the engine found, in words and on the bar */
function evScoreText(sc){
  if (!sc) return "";
  if (sc.mated) return sc.mated === "w" ? "−M0" : "M0";
  if (sc.mate != null) return (sc.mate < 0 ? "−" : "") + "M" + Math.abs(sc.mate);
  const v = sc.cp / 100;
  return (v < 0 ? "−" : "+") + Math.abs(v).toFixed(1);
}
function evWhiteShare(sc){
  // White's share of the bar, from 0 to 1: a sigmoid of the centipawns, as the common bars draw it
  if (!sc) return 0.5;
  if (sc.mated) return sc.mated === "w" ? 0 : 1;
  if (sc.mate != null) return sc.mate > 0 ? 1 : 0;
  return 1 / (1 + Math.exp(-0.004 * sc.cp));
}
function evSan(fen, pv){
  // the engine's moves as notation with move numbers from the shown position: [[san, uci], ...]
  const out = [];
  let f = fen;
  for (const uci of pv.slice(0, 16)) {
    const legal = CJ.legalMoves(f), m = legal.find(x => x[1] === uci);
    if (!m) break;
    const parts = f.split(" "), num = parts[5] || "1", black = parts[1] === "b";
    out.push([(black ? (out.length ? "" : num + "…") : num + ".") + m[0], uci, m[0]]);
    f = CJ.after(f, uci);
    if (!f) break;
  }
  return out;
}
function evRender(){
  // at most once a frame: the engine reports many times a second
  if (EV.raf) return;
  EV.raf = requestAnimationFrame(() => { EV.raf = 0; evRenderNow(); });
}
function evRenderNow(){
  const box = $("evlines");
  if (!box) return;
  const top = EV.lines[0] ? EV.lines[0].score : null;
  const bar = $("evalbar");
  bar.classList.toggle("flip", S.flip);
  bar.querySelector(".ebar i").style.height = (100 * evWhiteShare(top)).toFixed(1) + "%";
  bar.querySelector(".enum").textContent = EV.fen ? evScoreText(top) : "";
  $("mevalnum").textContent = EV.on && EV.fen ? evScoreText(top) : "";
  const src = EV.fen ? moveSource($("board")) : null;
  const canPlay = !!src && src.fen === EV.fen;
  let h = "";
  EV.lines.forEach((l, i) => {
    if (!l) return;
    const moves = evSan(EV.fen, l.pv);
    if (!moves.length) return;
    h += "<li><button class='evline' data-line='" + i + "' data-uci='" + esc(moves[0][1]) + "'" +
      (canPlay ? "" : " aria-disabled='true'") + " title='" + (canPlay ? "Play " + esc(moves[0][2]) + " on the board" :
      "The board takes no move here") + "'><span class='esc'>" + esc(evScoreText(l.score)) + "</span><span class='epv'>" +
      "<span class='efirst'>" + esc(moves[0][0]) + "</span> " + moves.slice(1).map(m => esc(m[0])).join(" ") + "</span></button></li>";
  });
  box.innerHTML = h;
  evArrow();
}
function evStatus(){
  const el = $("evstatus");
  if (!el) return;
  let t;
  if (EV.failed) t = EV.failed;
  else if (EV.loading) t = "Loading the engine (1.8 MB the first time)…";
  else if (!EV.fen) t = EV.on && !shownFen() ? "The board shows no position to analyse." :
    EV.on && !EV.settings.auto ? "A press on the processor icon analyses the position shown." : "";
  else if (EV.ended) t = EV.ended;
  else if (EV.searching) t = "Analysing… depth " + EV.depth + (EV.nps ? ", " + Math.round(EV.nps / 1000) + " thousand nodes a second" : "") + ".";
  else if (EV.done) t = "Depth " + EV.depth + (EV.cached ? ", kept from an earlier analysis." : " reached.");
  else t = "Stopped.";
  if (EV.hidden && EV.on) t = "Paused while the page is hidden.";
  el.textContent = t;
  $("evdeeper").hidden = !(EV.on && EV.fen && EV.ready && !EV.ended);
}
function deeper(){
  // the limit is lifted for this position: eight plies more, or four times the time
  if (!EV.on || !EV.fen || !EV.ready || EV.ended) return;
  EV.deeper += 1;
  EV.done = false;
  evSearch(EV.fen);
}
function evArrow(){
  // the top suggestion as an arrow on the board, when the settings ask for it
  for (const el of document.querySelectorAll("#board .eva, #board .evh")) el.remove();
  if (!EV.on || !EV.settings.arrow || !EV.lines[0] || !EV.fen) return;
  const svg = $("board").querySelector("svg.board");
  if (!svg) return;
  const uci = EV.lines[0].pv[0];
  if (!uci || uci.length < 4) return;
  const mid = (sq) => { const [x, y] = sqXY(svg, sq); return [x + SQ / 2, y + SQ / 2]; };
  const [x1, y1] = mid(uci.slice(0, 2)), [x2, y2] = mid(uci.slice(2, 4));
  const dx = x2 - x1, dy = y2 - y1, len = Math.hypot(dx, dy);
  if (!len) return;
  const ux = dx / len, uy = dy / len, head = 12, back = 9;
  // the shaft stops short of the head; the head is a small triangle at the target's middle
  const ex = x2 - ux * head, ey = y2 - uy * head;
  const NS = "http://www.w3.org/2000/svg";
  const line = document.createElementNS(NS, "line");
  line.setAttribute("class", "eva"); line.setAttribute("pointer-events", "none");
  line.setAttribute("x1", x1 + ux * 10); line.setAttribute("y1", y1 + uy * 10);
  line.setAttribute("x2", ex); line.setAttribute("y2", ey);
  const tri = document.createElementNS(NS, "polygon");
  tri.setAttribute("class", "evh"); tri.setAttribute("pointer-events", "none");
  tri.setAttribute("points", [x2, y2, ex - uy * back * 0.7, ey + ux * back * 0.7, ex + uy * back * 0.7, ey - ux * back * 0.7].join(","));
  svg.appendChild(line); svg.appendChild(tri);
}

/* the settings */
function toggleSettings(on){
  const box = $("evset");
  on = on === undefined ? box.hidden : on;
  box.hidden = !on;
  $("bgear").setAttribute("aria-pressed", String(on));
  if (on) renderSettings();
  layoutPanel(false);
}
function renderSettings(){
  const s = EV.settings;
  const opt = (key, value, label) => "<button class='tb' data-set='" + key + "' data-value='" + esc(String(value)) + "' aria-pressed='" +
    String(s[key] === value) + "'>" + esc(label) + "</button>";
  const row = (label, opts) => "<div class='row'><span class='lab'>" + label + "</span><span class='opts'>" + opts + "</span></div>";
  let h = row("Lines", [1, 2, 3, 4, 5].map(k => opt("lines", k, String(k))).join(""));
  h += row("Stop at", EV_LIMITS.map(l => opt("limit", l[0], l[1])).join(""));
  h += row("Analyse", opt("auto", true, "every position shown") + opt("auto", false, "only when the icon is pressed"));
  h += row("Arrow", opt("arrow", true, "best move on the board") + opt("arrow", false, "none"));
  h += row("Memory", opt("hash", 16, "16 MB") + opt("hash", 32, "32 MB"));
  h += "<p class='evfoot small'>" + esc((EV.name || ENGINE.name) + " (" + ENGINE.build + "), free software under the GNU General " +
    "Public License, version 3") + (ENGINE_BASE ? " (<a href='" + esc(ENGINE_BASE + "Copying.txt") + "' target='_blank' rel='noopener'>licence</a>)" : "") +
    ". The engine runs on this device and sends nothing anywhere.</p>";
  $("evset").innerHTML = "<div class='evset small'>" + h + "</div>";
}
function setOption(key, value){
  const s = EV.settings;
  if (key === "lines" || key === "hash") value = parseInt(value, 10);
  else if (key === "auto" || key === "arrow") value = value === "true";
  if (s[key] === value) return;
  s[key] = value;
  evSaveSettings();
  renderSettings();
  if (key === "arrow") { evArrow(); return; }
  if (key === "auto") { EV.ran = shownFen(); if (EV.on) evGo(); evStatus(); return; }
  if (!EV.worker) return;
  // the engine takes a new number of lines or memory between searches: the search in progress
  // is stopped, the option set, and the same position searched again
  const fen = EV.fen;
  if (EV.searching && !EV.stopping) { EV.stopping = true; evSend("stop"); }
  if (key === "lines") evSend("setoption name MultiPV value " + s.lines);
  if (key === "hash") evSend("setoption name Hash value " + s.hash);
  EV.lines = []; EV.done = false; EV.deeper = 0;
  if (EV.on && fen) { if (EV.searching) EV.want = fen; else evSearch(fen); }
}

function initEngine(){
  EV.settings = evLoadSettings();
  $("bcpu").addEventListener("click", pressCpu);
  if ($("mcpu")) $("mcpu").addEventListener("click", pressCpu);
  $("bgear").addEventListener("click", () => toggleSettings());
  $("evdeeper").addEventListener("click", deeper);
  $("evset").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-set]");
    if (b) setOption(b.dataset.set, b.dataset.value);
  });
  $("evlines").addEventListener("click", (e) => {
    // a tap on a line plays its first move on the board, through the board-move chooser
    const b = e.target.closest("button[data-uci]");
    if (!b || b.getAttribute("aria-disabled") === "true") return;
    const src = moveSource($("board"));
    if (!src || src.fen !== EV.fen) return;
    const m = CJ.legalMoves(src.fen).find(x => x[1] === b.dataset.uci);
    if (m) boardMove(src, m);
  });
  // nothing runs while the tab is hidden; the search starts again when it shows
  document.addEventListener("visibilitychange", () => {
    EV.hidden = document.hidden;
    if (!EV.on) return;
    if (EV.hidden) { clearTimeout(EV.timer); if (EV.searching) { EV.want = null; if (!EV.stopping) { EV.stopping = true; evSend("stop"); } } evStatus(); }
    else { EV.fen = null; EV.done = false; evGo(); }
  });
  // leaving the chapter ends the engine
  window.addEventListener("pagehide", () => { if (EV.worker) evKill(); });
  window.engineState = () => ({on: EV.on, ready: EV.ready, worker: !!EV.worker, searching: EV.searching, fen: EV.fen, depth: EV.depth,
    lines: EV.lines.map(l => l && {score: l.score, pv: l.pv.slice(0, 4), depth: l.depth}), done: EV.done,
    settings: Object.assign({}, EV.settings), failed: EV.failed, loading: EV.loading, name: EV.name, nps: EV.nps,
    from: EV.from || null, loadMs: EV.loadMs || null, deeper: EV.deeper, cached: EV.cached});
}
"""
