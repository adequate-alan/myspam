"""Reversible editor (Alan, Oct 12): the same order, tiers, typed values and settings always give the same board, and an
edit sequence that's completely undone puts the board back exactly: every rank, position rank, tier, tier name,
Auto/Manual flag and calculated value, with nothing left unsaved and no "Revalued from tier" tag. Deliberate edits made
elsewhere (typed values, tier renames, a player dropped into another tier, a new tier) stay exactly as they were.

Drives the editor's own move functions in the page (SPM.edit: the same functions the arrows and drag-and-drop call), plus
real arrow clicks and a real mouse drag:
  1. 511 single moves undone (every 3rd player, 1/3/5/10 down, 3/5 up), All view, many crossing other positions
  2. the same in each position tab with the arrows, and with drops into another tier band and back (tier boundaries)
  3. 20 sessions of 40 random All-view moves undone in reverse, and 20 mixed sessions (All view, position-tab arrows,
     drops into tier bands; cross-position) undone in reverse
  4. typed values: moves of typed players and around them undone; clearing the values restores Auto players
  5. deliberate edits kept: a tier rename, a typed value, a tier drop and a new empty tier, then 40 moves undone
  6. the UI path: arrow clicks and a mouse drag, undone with the arrows

Run from the repo root:  python3 tests/reversal_check.py   (CHROMIUM=/path/to/chromium if needed)
"""
import functools, http.server, os, re, socketserver, sys, threading, time
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
h = functools.partial(http.server.SimpleHTTPRequestHandler, directory=ROOT); h.log_message = lambda *a: None
srv = socketserver.TCPServer(("127.0.0.1", 0), h); threading.Thread(target=srv.serve_forever, daemon=True).start()
failures = []
def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg, flush=True)
    if not cond: failures.append(msg)

# In-page helpers. ref = the state the session must come back to (CSV text + every player's rank, tier, value, source).
LIB = r"""
window.__R = (() => {
  const E = SPM.edit;
  const tags = () => [...document.querySelectorAll("#rank-body tr.player .rv-tag")].map(t => t.closest("tr").dataset.id).sort().join(",");
  const state = () => ({ csv: E.draft(), vals: JSON.stringify(E.values()), tags: tags() });
  const rows = () => E.values().map(([id, rank, pos, posNum, tier, value, source]) => ({ id, rank, pos, posNum, tier, value, source }));
  const byRank = () => rows().sort((a, b) => a.rank - b.rank);
  const head = csv => csv.split("\n")[0].split(",");
  function diff(ref) {   // what differs from ref (first few rows, per column), for the report
    const a = ref.csv.split("\n"), b = E.draft().split("\n"), h = head(ref.csv), out = [];
    for (let i = 1; i < Math.max(a.length, b.length) && out.length < 4; i++) if (a[i] !== b[i]) {
      const x = (a[i] || "").split(","), y = (b[i] || "").split(",");
      out.push(x[0] + ": " + h.map((c, k) => x[k] !== y[k] ? `${c} ${x[k]}→${y[k]}` : "").filter(Boolean).join(", "));
    }
    if (!out.length && ref.vals !== JSON.stringify(E.values())) out.push("calculated values differ");
    if (!out.length && ref.tags !== tags()) out.push(`"Revalued from tier" tags differ: ${ref.tags || "none"} → ${tags() || "none"}`);
    return out.join(" | ");
  }
  // the CSV (ranks, tiers, tier names, values, Auto/Manual), every calculated value, and the same "Revalued from tier" tags
  const same = ref => E.draft() === ref.csv && JSON.stringify(E.values()) === ref.vals && tags() === ref.tags;
  function rnd(seed) { let s = seed * 7919 % 2147483647; return () => (s = s * 16807 % 2147483647) / 2147483647; }
  const posGroup = (pos, rs = rows()) => rs.filter(r => r.posNum != null && r.pos === pos).sort((a, b) => a.posNum - b.posNum);
  return { E, state, rows, byRank, diff, same, rnd, posGroup };
})();
"""

with sync_playwright() as p:
    kw = {"executable_path": os.environ["CHROMIUM"]} if os.environ.get("CHROMIUM") else {}
    br = p.chromium.launch(**kw); errs = []
    pg = br.new_page(viewport={"width": 1440, "height": 1000})
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.route("https://api.github.com/**", lambda r: r.abort())
    pg.route(re.compile(r"https://(sleepercdn\.com|a\.espncdn\.com|api\.sleeper\.(app|com)|use\.typekit\.net|fonts\.(googleapis|gstatic)\.com)/.*"), lambda r: r.abort())
    pg.add_init_script("window.__SPM_TEST_HOOKS = true;")   # the editor's move functions (SPM.edit), for this test only
    pg.goto(f"http://127.0.0.1:{srv.server_address[1]}/#rankings"); pg.wait_for_timeout(4000)
    pg.evaluate(LIB)
    n = pg.evaluate("() => __R.rows().length")
    ok(n > 250 and pg.evaluate("() => SPM.edit.unsaved()") == 0, f"Board loaded with nothing unsaved ({n} players)")

    # 1. single All-view moves undone
    r1 = pg.evaluate("""() => { const R = __R, E = R.E, ref = R.state(), B = R.byRank(), N = B.length, bad = []; let n = 0, tierX = 0, autoN = 0, autoOk = 0;
      for (let k = 0; k < N; k += 3) for (const d of [1, 3, 5, 10, -3, -5]) {
        const r = B[k], to = r.rank + d; if (to < 1 || to > N) continue; n++;
        E.overall(r.id, to);
        const mid = R.rows().find(x => x.id === r.id); if (mid.tier !== r.tier) tierX++;
        if (r.source === "auto") { autoN++; if (mid.source === "manual" && R.rows().filter(x => x.source !== B.find(y => y.id === x.id).source).length === 1) autoOk++; }
        E.overall(r.id, r.rank);
        if (!R.same(ref)) { bad.push(`#${r.rank} ${d > 0 ? "+" : ""}${d}: ${R.diff(ref)}`); E.reset(); }
      }
      return { n, bad, tierX, autoN, autoOk }; }""")
    ok(r1["autoN"] >= 50 and r1["autoOk"] == r1["autoN"], f"An Auto player is Manual while his own move stands, and nobody else's flag changes ({r1['autoOk']}/{r1['autoN']} moves of Auto players)")
    ok(r1["n"] == 511 and not r1["bad"], f"511 single moves undone in the All view restore the board exactly ({r1['n']} cases, {r1['tierX']} crossed a tier boundary on the way) {r1['bad'][:3]}")

    # 2. position tabs: arrows (derived tiers) and drops into another tier band (a deliberate tier) undone
    r2 = pg.evaluate("""() => { const R = __R, E = R.E, ref = R.state(), bad = []; let n = 0, m = 0;
      for (const pos of ["QB", "RB", "WR", "TE"]) {
        const G = R.posGroup(pos), L = G.length;
        for (let k = 0; k < L; k += 2) for (const d of [1, 2, 6, -1, -3]) {
          const r = G[k], to = r.posNum + d; if (to < 1 || to > L || Number(r.tier) >= 90) continue; n++;
          E.position(r.id, to); E.position(r.id, r.posNum);
          if (!R.same(ref)) { bad.push(`${pos}${r.posNum} ${d}: ${R.diff(ref)}`); E.reset(); }
        }
        // tier boundaries: the first and last player of every tier dropped into the next / previous tier's band and back
        for (let k = 0; k < L; k++) {
          const r = G[k], prev = G[k - 1], next = G[k + 1]; if (Number(r.tier) >= 90) continue;
          const tries = [];
          if (prev && prev.tier !== r.tier && Number(prev.tier) < 90) tries.push([r.posNum - 1, prev.tier], [Math.max(1, r.posNum - 3), G[Math.max(0, k - 3)].tier]);
          if (next && next.tier !== r.tier && Number(next.tier) < 90) tries.push([r.posNum + 1, next.tier], [Math.min(L, r.posNum + 4), G[Math.min(L - 1, k + 4)].tier]);
          for (const [to, t] of tries) { if (Number(t) >= 90) continue; m++;
            E.position(r.id, to, t); E.position(r.id, r.posNum, r.tier);
            if (!R.same(ref)) { bad.push(`${pos}${r.posNum} → ${to} (tier ${t}) and back: ${R.diff(ref)}`); E.reset(); }
          }
        }
      }
      return { n, m, bad }; }""")
    ok(not r2["bad"], f"Position tabs: {r2['n']} arrow moves and {r2['m']} drops across tier boundaries, each undone, restore the board exactly {r2['bad'][:3]}")

    # 3. sessions of 40 moves undone in reverse
    SESSION = """(seed, mixed) => { const R = __R, E = R.E, ref = R.state(), rnd = R.rnd(seed), log = []; let tierMoves = 0, cross = 0;
      for (let i = 0; i < 40; i++) {
        const B = R.byRank(), N = B.length, kind = mixed ? ["all", "arrow", "drop"][Math.floor(rnd() * 3)] : "all";
        if (kind === "all") {
          const r = B[Math.floor(rnd() * 180)], long = rnd() < 0.2, to = Math.max(1, Math.min(N, r.rank + Math.round((rnd() - 0.5) * (long ? 120 : 24))));
          if (to === r.rank) continue;
          log.push(["all", r.id, r.rank]); E.overall(r.id, to);
        } else {
          const pos = ["QB", "RB", "WR", "TE"][Math.floor(rnd() * 4)], G = R.posGroup(pos), L = G.length;
          const r = G[Math.floor(rnd() * (L - 2))]; if (Number(r.tier) >= 90) continue;
          const to = Math.max(1, Math.min(L, r.posNum + Math.round((rnd() - 0.5) * 16))); if (to === r.posNum) continue;
          if (kind === "arrow") { log.push(["arrow", r.id, r.posNum]); E.position(r.id, to); }
          else {   // a drop next to the player who'll be above or below him: his tier band
            const rest = G.filter(x => x.id !== r.id), nb = rest[Math.min(rest.length - 1, Math.max(0, to - 1 - (rnd() < 0.5 ? 1 : 0)))];
            if (Number(nb.tier) >= 90) continue;
            if (nb.tier !== r.tier) tierMoves++;
            log.push(["drop", r.id, r.posNum, r.tier]); E.position(r.id, to, nb.tier);
          }
        }
      }
      const moved = E.unsaved();
      for (const [kind, id, from, tier] of log.slice().reverse()) {
        if (kind === "all") E.overall(id, from); else if (kind === "arrow") E.position(id, from); else E.position(id, from, tier);
      }
      const res = { moves: log.length, moved, tierMoves, ok: R.same(ref), diff: R.same(ref) ? "" : R.diff(ref) };
      if (!res.ok) E.reset();
      return res; }"""
    for mixed in (False, True):
        out = [pg.evaluate(f"(a) => ({SESSION})(a[0], a[1])", [seed, mixed]) for seed in range(1, 21)]
        bad = [f"seed {i + 1}: {o['diff']}" for i, o in enumerate(out) if not o["ok"]]
        what = "mixed sessions (All view, position-tab arrows, drops into tier bands)" if mixed else "All-view sessions (20% long moves of up to 60 spots)"
        ok(not bad and all(o["moves"] >= 30 and o["moved"] > 0 for o in out),
           f"20 {what} of ~40 moves ({min(o['moves'] for o in out)}–{max(o['moves'] for o in out)} moves, up to {max(o['moved'] for o in out)} rows changed{', ' + str(sum(o['tierMoves'] for o in out)) + ' drops into another tier' if mixed else ''}) undone in reverse restore the board exactly {bad[:3]}")

    # 4. typed values
    r4 = pg.evaluate("""() => { const R = __R, E = R.E, ref0 = R.state(), B = R.byRank(), bad = [];
      const auto = B.filter(r => r.source === "auto"), pick = [B[20], B[64], B[120], auto[5], auto[30]];
      pick.forEach(r => E.value(r.id, Math.round(r.value * 1.04)));
      const ref1 = R.state(), typedSrc = pick.map(r => R.rows().find(x => x.id === r.id).source);
      for (const r of pick) for (const d of [1, 4, -2, 12]) {
        const cur = R.rows().find(x => x.id === r.id), to = cur.rank + d; if (to < 1 || to > B.length) continue;
        E.overall(r.id, to); E.overall(r.id, cur.rank);
        if (!R.same(ref1)) { bad.push(`typed ${cur.rank} ${d}: ${R.diff(ref1)}`); }
        // a neighbour moved past him and back
        const nb = R.byRank()[cur.rank]; if (nb) { E.overall(nb.id, cur.rank - 2 > 0 ? cur.rank - 2 : cur.rank + 3); E.overall(nb.id, nb.rank); if (!R.same(ref1)) bad.push(`past typed ${cur.rank}: ${R.diff(ref1)}`); }
      }
      pick.forEach(r => E.value(r.id, null));
      const back = R.same(ref0);
      return { bad, back, typedSrc, diff: back ? "" : R.diff(ref0) }; }""")
    ok(not r4["bad"], f"Moves of typed-value players and of players past them, undone, restore the board with the typed values exactly {r4['bad'][:3]}")
    ok(r4["typedSrc"][3:] == ["manual", "manual"] and r4["back"], f"Typing a value makes an Auto player Manual; clearing it restores Auto and the whole board {r4['diff']}")

    # 5. deliberate edits stay while everything else is undone
    r5 = pg.evaluate("""(SESSION) => { const R = __R, E = R.E, ref0 = R.state(), B = R.byRank();
      const wr = R.posGroup("WR"), t5 = wr.filter(r => r.tier === "5"), te = R.posGroup("TE");
      E.tier("rename", "WR", "5", "Renamed tier");                 // a tier rename
      E.value(B[40].id, Math.round(B[40].value * 1.03));            // a typed value
      const d = te.find((r, k) => k > 3 && te[k - 1].tier !== r.tier);   // first player of a TE tier dropped into the tier above
      E.position(d.id, d.posNum - 1, te[te.indexOf(d) - 1].tier);
      E.tier("below", "RB", "3");                                   // a new (empty) tier: renumbers the RB tiers below it
      const ref1 = R.state(), kept = E.unsaved();
      const s = (0, eval)("(" + SESSION + ")")(7, true);
      return { kept, ok: R.same(ref1), diff: R.same(ref1) ? "" : R.diff(ref1), renamed: E.draft().split("\\n").filter(l => l.includes("Renamed tier")).length, t5: t5.length, s }; }""", SESSION)
    ok(r5["ok"] and r5["kept"] > 0 and r5["renamed"] == r5["t5"],
       f"A tier rename, a typed value, a drop into another tier and a new tier stay exactly as made after a 40-move mixed session is undone ({r5['kept']} rows still edited, {r5['renamed']} rows carry the new name) {r5['diff']} {r5['s']['diff']}")
    pg.evaluate("() => SPM.edit.reset()")
    # earlier ordinary moves (across tiers, All view and arrows) stay exactly as made while a later session is undone
    r5b = []
    for seed in range(1, 11):
        r5b.append(pg.evaluate("""(a) => { const R = __R, E = R.E, rnd = R.rnd(1000 + a[1]);
          for (let i = 0; i < 8; i++) { const B = R.byRank(), r = B[Math.floor(rnd() * 150)]; E.overall(r.id, Math.max(1, r.rank + Math.round((rnd() - 0.5) * 20))); }
          for (const pos of ["WR", "RB"]) { const G = R.posGroup(pos), r = G[3 + Math.floor(rnd() * 20)]; E.position(r.id, Math.max(1, r.posNum - 2)); }
          const ref1 = R.state(), kept = E.unsaved();
          const s = (0, eval)("(" + a[0] + ")")(a[1], true);
          const res = { kept, ok: s.ok, diff: s.diff };
          E.reset(); return res; }""", [SESSION, seed]))
    bad = [f"seed {i + 1}: {o['diff']}" for i, o in enumerate(r5b) if not o["ok"]]
    ok(not bad and all(o["kept"] > 0 for o in r5b), f"10 boards with earlier moves across tiers kept: a 40-move mixed session on top, undone, leaves them exactly as they were {bad[:3]}")
    ok(pg.evaluate("() => SPM.edit.unsaved()") == 0, "Cancel brings back the saved board")

    # 6. the UI path: arrow clicks in the All view and a WR tab, and a real drag, each undone with the arrows
    ref = pg.evaluate("() => __R.state()")
    def arrows(pid, d, times):
        for _ in range(times):
            pg.locator(f'#rank-body tr.player[data-id="{pid}"] .arrow[data-dir="{d}"]').click(force=True); pg.wait_for_timeout(120)
    rows = pg.evaluate("() => __R.byRank()")
    b = next(r for i, r in enumerate(rows) if i > 20 and pg.evaluate(f"() => __R.posGroup('WR').some(x => x.id === {r['id']})"))
    arrows(b["id"], 1, 6); moved = pg.evaluate("() => SPM.edit.unsaved()"); arrows(b["id"], -1, 6)
    ok(moved > 0 and pg.evaluate("(ref) => __R.same(ref)", ref), f"All view: six ▼ clicks then six ▲ clicks restore the board exactly ({moved} rows changed on the way)")
    pg.click("#pos-chips button:has-text('WR')"); pg.wait_for_timeout(400)
    wr = pg.evaluate("() => __R.posGroup('WR')")
    w = next(r for k, r in enumerate(wr) if k > 4 and wr[k - 1]["tier"] != r["tier"])
    arrows(w["id"], -1, 3); t_mid = pg.evaluate(f"() => __R.rows().find(x => x.id === {w['id']}).tier"); arrows(w["id"], 1, 3)
    ok(t_mid != w["tier"] and pg.evaluate("(ref) => __R.same(ref)", ref), f"WR tab: WR{w['posNum']} moved up three spots into tier {t_mid} with the arrows and back restores tier {w['tier']} and the board exactly")
    pg.click("#pos-chips button:has-text('All')"); pg.wait_for_timeout(400)
    idx = 30; tr = pg.locator("#rank-body tr.player").nth(idx); pid = tr.get_attribute("data-id")
    tr.scroll_into_view_if_needed(); hb = tr.locator(".handle").bounding_box(); x, y = hb["x"] + hb["width"] / 2, hb["y"] + hb["height"] / 2
    rh = tr.bounding_box()["height"]
    pg.mouse.move(x, y); pg.mouse.down()
    for i in range(20): pg.mouse.move(x, y + 5 * rh * (i + 1) / 20); time.sleep(0.012)
    pg.mouse.up(); pg.wait_for_timeout(700)
    dist = pg.evaluate(f"() => __R.rows().find(x => x.id === {pid}).rank") - (idx + 1)
    arrows(pid, -1, dist)
    ok(dist > 0 and pg.evaluate("(ref) => __R.same(ref)", ref), f"A mouse drag of #{idx + 1} down {dist} rows, undone with {dist} ▲ clicks, restores the board exactly")
    ok(not errs, f"No page errors {errs[:3]}")
    br.close()
print(f"\n{len(failures)} check(s) failed." if failures else "\nAll reversal checks passed.")
sys.exit(1 if failures else 0)
