"""The legal moves of a position, in the browser.

CHESS_JS gives legalMoves(fen) -> [[SAN, UCI], ...] sorted by SAN, as
reader.legal_moves() does in Python, so that the chapter reader can offer
the legal moves of any position (the pencil corrects any move, not only the
moves the program was unsure of) without the build listing them for every
move. Squares are numbered 0..63 from a8 to h1, row by row.
"""

CHESS_JS = r"""
const CJ = (function(){
  const FILES = "abcdefgh";
  const N = [[-2,-1],[-2,1],[-1,-2],[-1,2],[1,-2],[1,2],[2,-1],[2,1]];
  const K = [[-1,-1],[-1,0],[-1,1],[0,-1],[0,1],[1,-1],[1,0],[1,1]];
  const B = [[-1,-1],[-1,1],[1,-1],[1,1]], R = [[-1,0],[1,0],[0,-1],[0,1]];
  function parse(fen){
    const f = fen.split(" "), b = new Array(64).fill("");
    f[0].split("/").forEach((row, r) => { let c = 0; for (const ch of row) { if (/\d/.test(ch)) c += +ch; else b[r * 8 + c++] = ch; } });
    return {b, turn: f[1] || "w", castle: f[2] || "-", ep: f[3] || "-", half: +(f[4] || 0), full: +(f[5] || 1)};
  }
  function fen(p){
    const rows = [];
    for (let r = 0; r < 8; r++) {
      let s = "", e = 0;
      for (let c = 0; c < 8; c++) { const x = p.b[r * 8 + c]; if (!x) { e++; continue; } if (e) { s += e; e = 0; } s += x; }
      rows.push(s + (e || ""));
    }
    return rows.join("/") + " " + p.turn + " " + (p.castle || "-") + " " + p.ep + " " + p.half + " " + p.full;
  }
  const white = (x) => x && x === x.toUpperCase();
  const mine = (p, x) => x && (p.turn === "w") === white(x);
  const sq = (r, c) => FILES[c] + (8 - r);
  function attacked(b, s, byWhite){
    const r = s >> 3, c = s & 7;
    const at = (rr, cc) => rr >= 0 && rr < 8 && cc >= 0 && cc < 8 ? b[rr * 8 + cc] : null;
    const is = (x, t) => x && white(x) === byWhite && x.toLowerCase() === t;
    const pr = byWhite ? r + 1 : r - 1;
    if (is(at(pr, c - 1), "p") || is(at(pr, c + 1), "p")) return true;
    for (const [dr, dc] of N) if (is(at(r + dr, c + dc), "n")) return true;
    for (const [dr, dc] of K) if (is(at(r + dr, c + dc), "k")) return true;
    for (const [dirs, kinds] of [[B, "bq"], [R, "rq"]]) for (const [dr, dc] of dirs) {
      let rr = r + dr, cc = c + dc;
      while (rr >= 0 && rr < 8 && cc >= 0 && cc < 8) {
        const x = b[rr * 8 + cc];
        if (x) { if (white(x) === byWhite && kinds.indexOf(x.toLowerCase()) >= 0) return true; break; }
        rr += dr; cc += dc;
      }
    }
    return false;
  }
  function inCheck(p, w){
    const k = p.b.indexOf(w ? "K" : "k");
    return k >= 0 && attacked(p.b, k, !w);
  }
  function pseudo(p){
    const out = [], b = p.b, w = p.turn === "w";
    for (let s = 0; s < 64; s++) {
      const x = b[s];
      if (!mine(p, x)) continue;
      const r = s >> 3, c = s & 7, t = x.toLowerCase();
      const add = (rr, cc, promo) => out.push({from: s, to: rr * 8 + cc, promo: promo || ""});
      if (t === "p") {
        const d = w ? -1 : 1, last = w ? 0 : 7, start = w ? 6 : 1;
        const push = (rr, cc) => { if (rr === last) for (const q of "qrbn") add(rr, cc, q); else add(rr, cc); };
        if (r + d >= 0 && r + d < 8 && !b[(r + d) * 8 + c]) {
          push(r + d, c);
          if (r === start && !b[(r + 2 * d) * 8 + c]) add(r + 2 * d, c);
        }
        for (const dc of [-1, 1]) {
          const cc = c + dc, rr = r + d;
          if (cc < 0 || cc > 7 || rr < 0 || rr > 7) continue;
          const y = b[rr * 8 + cc];
          if ((y && !mine(p, y)) || p.ep === sq(rr, cc)) push(rr, cc);
        }
        continue;
      }
      const steps = t === "n" ? N : t === "k" ? K : t === "b" ? B : t === "r" ? R : B.concat(R);
      const slide = "brq".indexOf(t) >= 0;
      for (const [dr, dc] of steps) {
        let rr = r + dr, cc = c + dc;
        while (rr >= 0 && rr < 8 && cc >= 0 && cc < 8) {
          const y = b[rr * 8 + cc];
          if (y && mine(p, y)) break;
          add(rr, cc);
          if (y || !slide) break;
          rr += dr; cc += dc;
        }
      }
      if (t === "k") {
        const home = w ? 60 : 4, rights = w ? "KQ" : "kq";
        if (s === home && !inCheck(p, w)) {
          if (p.castle.indexOf(rights[0]) >= 0 && !b[s + 1] && !b[s + 2] && b[s + 3] === (w ? "R" : "r") &&
              !attacked(b, s + 1, !w) && !attacked(b, s + 2, !w)) out.push({from: s, to: s + 2, promo: "", castle: "O-O"});
          if (p.castle.indexOf(rights[1]) >= 0 && !b[s - 1] && !b[s - 2] && !b[s - 3] && b[s - 4] === (w ? "R" : "r") &&
              !attacked(b, s - 1, !w) && !attacked(b, s - 2, !w)) out.push({from: s, to: s - 2, promo: "", castle: "O-O-O"});
        }
      }
    }
    return out;
  }
  function play(p, m){
    const q = {b: p.b.slice(), turn: p.turn === "w" ? "b" : "w", castle: p.castle, ep: "-", half: p.half + 1,
               full: p.full + (p.turn === "b" ? 1 : 0)};
    const x = q.b[m.from], t = x.toLowerCase(), w = p.turn === "w";
    if (t === "p" && sq(m.to >> 3, m.to & 7) === p.ep) q.b[m.to + (w ? 8 : -8)] = "";
    if (t === "p" || q.b[m.to]) q.half = 0;
    if (t === "p" && Math.abs(m.to - m.from) === 16) q.ep = sq((m.from + m.to) >> 4, m.from & 7);
    q.b[m.to] = m.promo ? (w ? m.promo.toUpperCase() : m.promo) : x;
    q.b[m.from] = "";
    if (m.castle) {
      const rf = m.to > m.from ? m.from + 3 : m.from - 4, rt = m.to > m.from ? m.from + 1 : m.from - 1;
      q.b[rt] = q.b[rf]; q.b[rf] = "";
    }
    let cr = q.castle === "-" ? "" : q.castle;
    const drop = (s, letters) => { if (m.from === s || m.to === s) for (const l of letters) cr = cr.replace(l, ""); };
    drop(60, "KQ"); drop(4, "kq"); drop(63, "K"); drop(56, "Q"); drop(7, "k"); drop(0, "q");
    q.castle = cr || "-";
    return q;
  }
  function legal(p){ return pseudo(p).filter(m => !inCheck(play(p, m), p.turn === "w")); }
  function san(p, m, all){
    const x = p.b[m.from], t = x.toLowerCase();
    let s;
    if (m.castle) s = m.castle;
    else {
      const to = sq(m.to >> 3, m.to & 7), cap = !!p.b[m.to] || (t === "p" && to === p.ep);
      if (t === "p") s = (cap ? FILES[m.from & 7] + "x" : "") + to + (m.promo ? "=" + m.promo.toUpperCase() : "");
      else {
        const rivals = all.filter(o => o.to === m.to && o.from !== m.from && p.b[o.from] === x);
        let dis = "";
        if (rivals.length) {
          const f = m.from & 7, r = m.from >> 3;
          if (!rivals.some(o => (o.from & 7) === f)) dis = FILES[f];
          else if (!rivals.some(o => (o.from >> 3) === r)) dis = String(8 - r);
          else dis = FILES[f] + (8 - r);
        }
        s = t.toUpperCase() + dis + (cap ? "x" : "") + to;
      }
    }
    const q = play(p, m);
    if (inCheck(q, q.turn === "w")) s += legal(q).length ? "+" : "#";
    return s;
  }
  function legalMoves(f){
    let p;
    try { p = parse(f); } catch (e) { return []; }
    const all = legal(p);
    return all.map(m => [san(p, m, all), sq(m.from >> 3, m.from & 7) + sq(m.to >> 3, m.to & 7) + m.promo])
      .sort((a, b) => a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0);
  }
  function after(f, uci){
    const p = parse(f), m = legal(p).find(o => sq(o.from >> 3, o.from & 7) + sq(o.to >> 3, o.to & 7) + o.promo === uci);
    return m ? fen(play(p, m)) : null;
  }
  return {legalMoves, after};
})();
"""
