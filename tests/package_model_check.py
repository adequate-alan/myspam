"""Trade Calculator package model and ownership check (Alan, Oct 21, Trade Calculator audit: P0 and P1).

P0, the rank-matched package adjustment (tradeModel): both sides sorted high to low, the shorter padded with empty spots;
at each rank the part of a piece the other side's piece doesn't match counts at (v / star) ^ (PACKAGE_POWER / depth).
Before, only the extras of an uneven trade were discounted, so a 0-value throw-in that evened the counts removed the
whole discount (Gibbs for K. Williams + C. Williams: Split -> "Team Beta is getting a steal").
  1. a 0-value player on either side changes nothing: scores, swing, the verdict read (valueRead)
  2. adding a positive-value player never lowers the receiving side's adjusted margin, and never raises it by more than
     his value (6,000+ random additions at depths 1.00 / 0.72 / 1.12, including new stars and tiny pieces)
  3. 1-for-1, 2-for-1 and 3-for-1 (any k-for-1) give exactly the old formula's scores
  4. the raw-vs-adjusted safeguards hold: a winner's gap is never larger than his raw edge, and never on the side raw
     calls behind; a raw about-even trade never reads as a clear win
  5. the live calculator: the audit's trades keep their verdict when 0-value players (Hurts, Dart: Out for season) are
     added; the Trade Finder's pre-filter uses the same model (tradeModel)
     (the receiving side's own adjusted value rises by 0 to his value; the margin can rise by more only when he becomes the
     deal's new best player, which re-measures the other side's package against a bigger star; the old rule did it in 5 of 866 sampled cases, by at most 97 points, the new one in
     81, by at most 0.39× his value, and the verdict never turns against his side)
P1, ownership: a player put on a card "from" a team that doesn't have him (a third team's player, a free agent) keeps the
hypothetical value comparison but turns off Roster Impact, Acceptance and the roster rationale (2-team and 3-team).
Synthetic 12-team Superflex league (Full PPR, TE+0.5), board values from RANKINGS_CSV.
Run from the repo root:  python3 tests/package_model_check.py   (CHROMIUM=/path/to/chromium if needed)
"""
import csv, functools, http.server, io, json, os, re, socketserver, sys, threading
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src = open(os.path.join(ROOT, "index.html"), encoding="utf-8").read()
rows = list(csv.DictReader(io.StringIO(re.search(r"RANKINGS_CSV\s*=\s*`(.*?)`", src, re.S).group(1).strip())))
sid = {r["player"]: r["sleeper_id"] for r in rows if r["sleeper_id"]}
POS = {r["player"]: r["pos"] for r in rows}
VAL = {r["player"]: float(r["value"] or 0) for r in rows}
fails = 0
def ok(cond, msg):
    global fails
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond: fails += 1

hd = functools.partial(http.server.SimpleHTTPRequestHandler, directory=ROOT); hd.log_message = lambda *a: None
srv = socketserver.TCPServer(("127.0.0.1", 0), hd); threading.Thread(target=srv.serve_forever, daemon=True).start()
PORT = srv.server_address[1]

# the board's own players by value: the trade examples follow whatever the live board says
by_val = sorted((r for r in rows if r["sleeper_id"] and VAL[r["player"]] > 0), key=lambda r: -VAL[r["player"]])
zeros = [r["player"] for r in rows if r["sleeper_id"] and VAL[r["player"]] == 0][:2]
def near(v, pos=None, skip=()):
    pool = [r["player"] for r in by_val if (pos is None or r["pos"] == pos) and r["player"] not in skip]
    return min(pool, key=lambda n: abs(VAL[n] - v))

def league_data(force):
    """force: {roster_index: [names]}; everyone else dealt by position in a snake so each team is realistic"""
    forced = {n for v in force.values() for n in v}
    teams = [list(force.get(i, [])) for i in range(12)]
    by = {pos: [r["player"] for r in sorted(rows, key=lambda r: int(r["pos_rank"])) if r["pos"] == pos and r["sleeper_id"] and r["player"] not in forced and VAL[r["player"]] > 0]
          for pos in ("QB", "RB", "WR", "TE")}
    for pos, k in {"QB": 3, "RB": 5, "WR": 6, "TE": 2}.items():
        i = 0
        for rnd in range(k):
            for t in (range(12) if rnd % 2 == 0 else range(11, -1, -1)):
                if sum(1 for n in teams[t] if POS[n] == pos) >= k: continue
                if i < len(by[pos]): teams[t].append(by[pos][i]); i += 1
    names = ["Team Alpha", "Team Beta"] + [f"Team {i}" for i in range(3, 13)]
    rosters = [{"roster_id": i + 1, "owner_id": f"u{i+1}", "co_owners": [], "players": [sid[n] for n in t], "starters": [], "reserve": [], "taxi": [],
                "settings": {"wins": 2, "losses": 2, "ties": 0, "fpts": 400}} for i, t in enumerate(teams)]
    users = [{"user_id": f"u{i+1}", "display_name": f"mgr{i+1}", "metadata": {"team_name": names[i]}, "avatar": ""} for i in range(12)]
    league = {"league_id": "L1", "name": "Synthetic League", "season": "2026", "status": "in_season", "total_rosters": 12,
              "roster_positions": ["QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX", "SUPER_FLEX"] + ["BN"] * 7,
              "scoring_settings": {"rec": 1, "bonus_rec_te": 0.5, "pass_td": 4, "pass_yd": 0.04, "rush_yd": 0.1, "rec_yd": 0.1, "rush_td": 6, "rec_td": 6, "pass_int": -2, "fum_lost": -2},
              "settings": {"num_teams": 12, "type": 0}}
    return league, users, rosters

def open_page(br, force):
    league, users, rosters = league_data(force)
    SL = {"source": "sleeper", "username": "mgr1", "userId": "u1", "displayName": "mgr1", "season": "2026",
          "leagues": [{"id": "L1", "name": "Synthetic League", "season": "2026", "status": "in_season", "format": ""}],
          "activeId": "L1", "data": {"L1": {"league": league, "users": users, "rosters": rosters}}, "view": "league"}
    def sleeper(route):
        path = route.request.url.split("/v1", 1)[-1].split("?")[0]
        body = {"/league/L1": league, "/league/L1/users": users, "/league/L1/rosters": rosters, "/state/nfl": {"season": "2026", "week": 7, "season_type": "regular"}}.get(path, [])
        route.fulfill(status=200, content_type="application/json", body=json.dumps(body))
    pg = br.new_page(viewport={"width": 1400, "height": 1100})
    pg.errs = []; pg.on("pageerror", lambda e: pg.errs.append(str(e)))
    pg.route("https://api.sleeper.app/**", sleeper)
    pg.route(re.compile(r"https://(sleepercdn\.com|a\.espncdn\.com|api\.sleeper\.com|api\.github\.com|fonts\..*|use\.typekit\.net)/.*"), lambda r: r.abort())
    pg.add_init_script(f"window.__SPM_TEST_HOOKS = true; if (!sessionStorage.getItem('t')) {{ sessionStorage.setItem('t', '1'); localStorage.clear(); localStorage.setItem('spm_sleeper', {json.dumps(json.dumps(SL))}); localStorage.setItem('spm_tc_mode', 'league'); }}")
    pg.goto(f"http://127.0.0.1:{PORT}/#trade"); pg.wait_for_function("typeof tradeModel === 'function'"); pg.wait_for_timeout(2500)
    setsel(pg, "tc-league", "L1"); pg.wait_for_timeout(800)
    setsel(pg, "team-A", "1"); setsel(pg, "team-B", "2"); pg.wait_for_timeout(400)
    return pg

def setsel(pg, id_, v):
    pg.evaluate("([id, v]) => { const s = document.getElementById(id); s.value = v; s.dispatchEvent(new Event('change', { bubbles: true })); }", [id_, v])
def add(pg, side, name):
    pg.fill(f"#search-{side}", name); pg.wait_for_timeout(250); pg.keyboard.press("Enter"); pg.wait_for_timeout(350)
def clear(pg):
    pg.evaluate("() => { const b = [...document.querySelectorAll('#panel-trade button')].find(x => x.textContent.trim() === 'Clear'); b && b.click(); }"); pg.wait_for_timeout(300)
def read(pg):
    return pg.evaluate("""() => { const t = id => { const e = document.getElementById(id); return e && !e.hidden ? e.textContent.replace(/\\s+/g, ' ').trim() : ''; };
      return { title: t('verdict-title'), warn: t('tc-warn'), lens: !document.getElementById('tc-lens').hidden, why: t('tc-why-sum'),
               acc: [...document.querySelectorAll('#tc-why-body .rat h4 .tf-pill')].map(x => x.textContent.trim()),
               analysis: t('tc-analysis'), three: [...document.querySelectorAll('#three-verdicts .tv3-row')].map(r => r.textContent.replace(/\\s+/g, ' ').trim()) }; }""")

# ---------------------------------------------------------------- model properties, in the page (the real tradeModel)
PROPS = r"""
() => {
  const keep = LEAGUE_DEPTH, out = { zero: 0, zeroN: 0, worse: 0, direct: 0, over: 0, overStar: 0, addN: 0, k1: 0, k1N: 0, safe: 0, safeN: 0, evenWin: 0, worst: 0, exMax: 0, exRatio: 0, exPct: 0, exEx: null, starFlip: 0, starN: 0, exReal: 0, exRealEx: null, oldEx: 0, oldOver: 0, exList: [] };
  let seed = 7; const rnd = () => (seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648;
  const val = () => Math.round(rnd() < 0.15 ? rnd() * 300 : 300 + Math.pow(rnd(), 1.6) * 9700);
  const side = n => Array.from({ length: n }, () => ({ value: val() }));
  const margin = m => m.scoreA - m.scoreB;
  const old = (A, B) => {   // the Oct 5 rule: extras of an uneven trade only
    const rA = A.reduce((t, p) => t + p.value, 0), rB = B.reduce((t, p) => t + p.value, 0), n = A.length - B.length;
    if (!n) return [rA, rB];
    const star = Math.max(1, ...A.map(p => p.value), ...B.map(p => p.value)), d = LEAGUE_DEPTH;
    const big = (n > 0 ? A : B).map(p => Math.max(0, p.value)).sort((x, y) => y - x), ex = big.slice(big.length - Math.abs(n));
    const spot = ex.reduce((t, v) => t + v * (1 - Math.pow(Math.min(1, v / star), PACKAGE_POWER / d)), 0);
    return n > 0 ? [rA - spot, rB] : [rA, rB - spot];
  };
  const F = 3000;   // an average starter, for the verdict read
  try {
    for (const d of [1, 0.72, 1.12]) {
      LEAGUE_DEPTH = d;
      for (let i = 0; i < 1000; i++) {
        const A = side(1 + Math.floor(rnd() * 4)), B = side(1 + Math.floor(rnd() * 4)), m = tradeModel(A, B);
        // 1. zero-value player on either side
        for (const s of ["A", "B"]) {
          const A2 = s === "A" ? A.concat([{ value: 0 }]) : A, B2 = s === "B" ? B.concat([{ value: 0 }]) : B, z = tradeModel(A2, B2);
          const r1 = valueRead(m, F), r2 = valueRead(z, F);
          out.zeroN++;
          if (Math.abs(z.scoreA - m.scoreA) > 1e-6 || Math.abs(z.scoreB - m.scoreB) > 1e-6 || (z.adj ? z.adj.swing : 0) !== (m.adj ? m.adj.swing : 0)
              || r1.kind !== r2.kind || r1.side !== r2.side || Math.abs(r1.gap - r2.gap) > 1e-9) out.zero++;
        }
        // 2. a positive-value player to A: margin never down, never up by more than his value
        const x = rnd() < 0.2 ? Math.round(rnd() * 200) + 1 : rnd() < 0.2 ? 10000 + Math.round(rnd() * 3000) : val() || 1;
        const g = tradeModel(A.concat([{ value: x }]), B), dm = margin(g) - margin(m);
        out.addN++;
        if (dm < -1e-6) out.worse++;
        const dA = g.scoreA - m.scoreA, oldStar = Math.max(...A.map(p => p.value), ...B.map(p => p.value));
        if (dA < -1e-6 || dA > x + 1e-6) out.direct++;
        if (dm > x + 1e-6) { if (x > oldStar) out.overStar++; else out.over++; }
        if (x > oldStar) {
          // the new-best-player case: how far the margin moves beyond his own value, and whether the verdict leaves his side
          out.starN++;
          const ex = dm - x, tot = g.rawA + g.rawB, r1 = valueRead(m, F), r2 = valueRead(g, F);
          if (r2.side === "B" && r1.side !== "B") out.starFlip++;
          if (ex > out.exMax) { out.exMax = ex; out.exEx = { d, A: A.map(p => p.value), B: B.map(p => p.value), x, before: Math.round(margin(m)), after: Math.round(margin(g)),
            rawBefore: m.rawA - m.rawB, rawAfter: g.rawA + 0 - g.rawB, vBefore: r1.kind + ":" + (r1.side || "-") + ":" + r1.gap.toFixed(1), vAfter: r2.kind + ":" + (r2.side || "-") + ":" + r2.gap.toFixed(1) }; }
          out.exRatio = Math.max(out.exRatio, ex / x); out.exPct = Math.max(out.exPct, 100 * ex / tot);
          const [oA0, oB0] = old(A, B), [oA1, oB1] = old(A.concat([{ value: x }]), B), oex = (oA1 - oB1) - (oA0 - oB0) - x;
          out.oldEx = Math.max(out.oldEx, oex); if (oex > 1e-6) out.oldOver++;
          if (ex > 1e-6) out.exList.push(Math.round(ex));
          if (x <= 10000 && ex > out.exReal) { out.exReal = ex; out.exRealEx = { d, A: A.map(p => p.value), B: B.map(p => p.value), x, before: Math.round(margin(m)), after: Math.round(margin(g)),
            vBefore: r1.kind + ":" + (r1.side || "-") + ":" + r1.gap.toFixed(1), vAfter: r2.kind + ":" + (r2.side || "-") + ":" + r2.gap.toFixed(1), oldEx: Math.round(oex) }; }
        }
        out.worst = Math.min(out.worst, dm / x);
        // 3. k-for-1 = the old formula exactly
        if (A.length === 1 || B.length === 1) {
          const [oA, oB] = old(A, B); out.k1N++;
          if (Math.abs(oA - m.scoreA) > 1e-6 || Math.abs(oB - m.scoreB) > 1e-6) out.k1++;
        }
        // 4. safeguards: a winner's gap never exceeds his raw edge, never on the side raw calls behind
        const vr = valueRead(m, F);
        if (vr.side && vr.gap >= VALUE_FAIR && vr.kind !== "plain") {
          out.safeN++;
          const rawFor = vr.side === "A" ? vr.raw : -vr.raw;
          if (rawFor < vr.gap - 1e-9) out.safe++;
        }
        if (m.adj && Math.abs(vr.raw) < VALUE_FAIR && vr.gap >= VALUE_MAJOR && vr.kind !== "sensitive") out.evenWin++;
      }
    }
  } finally { LEAGUE_DEPTH = keep; }
  return out;
}"""

with sync_playwright() as p:
    kw = {"executable_path": os.environ["CHROMIUM"]} if os.environ.get("CHROMIUM") else {}
    br = p.chromium.launch(**kw)
    star = by_val[0]["player"]
    # the audit's live trades, rebuilt from today's board: a star for two pieces that add up just under him, and for three
    two = [near(VAL[star] * 0.52, skip=(star,))]; two.append(near(VAL[star] - VAL[two[0]] - 300, skip=(star, two[0])))
    three = [near(VAL[star] * 0.42, skip=(star,))]; three.append(near(VAL[star] * 0.40, skip=(star, *three))); three.append(near(VAL[star] * 0.38, skip=(star, *three)))
    owner3 = near(VAL[star] * 0.75, pos="TE", skip=(star, *two, *three))
    p4 = near(VAL[star] * 0.6, pos="WR", skip=(star, *two, *three, owner3))
    force = {0: [star], 1: two + three, 2: [owner3] + zeros, 3: [p4]}
    pg = open_page(br, force)

    r = pg.evaluate(PROPS)
    ok(r["zero"] == 0, f"A 0-value player changes no score, package swing or verdict ({r['zeroN']} additions, {r['zero']} changed)")
    ok(r["worse"] == 0, f"Adding a player never makes the receiving side worse off ({r['addN']} additions at depths 1.00 / 0.72 / 1.12, {r['worse']} did; worst {r['worst']:.2f}× his value)")
    ok(r["direct"] == 0, f"The receiving side's own adjusted value rises by at least 0 and at most the value added ({r['direct']} of {r['addN']} broke it)")
    ok(r["over"] == 0, f"Adding a player raises the margin by more than his value only when he becomes the deal's new best player ({r['over']} other cases; {r['overStar']} new-best-player cases, where the other side's package is measured against a bigger star)")
    xs = sorted(r.pop("exList")); print("INFO new-best-player excess beyond his value: median", xs[len(xs)//2] if xs else 0, "· 90th percentile", xs[int(len(xs)*0.9)] if xs else 0)
    print("INFO new-best-player cases:", json.dumps({k: r[k] for k in ("starN", "overStar", "exMax", "exRatio", "exPct", "starFlip", "exEx", "exReal", "exRealEx", "oldEx", "oldOver")}))
    ok(r["starN"] > 0 and r["exRatio"] < 0.5, f"New best player: the margin moves at most 1.5× his value ({r['starN']} cases, {r['overStar']} beyond his value; largest excess {r['exMax']:.0f} points = {r['exRatio']:.2f}× his value, {r['exPct']:.1f}% of the deal)")
    ok(r["starFlip"] == 0, f"New best player: the verdict never turns against the side that receives him ({r['starFlip']} did)")
    nb = pg.evaluate("""() => { const keep = LEAGUE_DEPTH; LEAGUE_DEPTH = 0.72; try {
        const f = (a, b) => { const m = tradeModel(a.map(v => ({ value: v })), b.map(v => ({ value: v }))), r = valueRead(m, 3000); return [Math.round(m.scoreA - m.scoreB), r.kind, r.side || "-"]; };
        return { before: f([452], [5178, 4968, 1717]), after: f([452, 8112], [5178, 4968, 1717]) };
      } finally { LEAGUE_DEPTH = keep; } }""")
    ok(nb["before"] == [-9787, "tempered", "B"] and nb["after"] == [450, "split", "-"],
       f"New best player, fixed example (depth 0.72): 452 for 5,178 + 4,968 + 1,717 reads {nb['before']}; adding an 8,112 star to the 452 side reads {nb['after']}: the margin moves 10,237 for 8,112 added, and the result is a Split verdict, never a win the raw values don't support")
    ok(r["k1N"] > 0 and r["k1"] == 0, f"1-for-1, 2-for-1, 3-for-1 and 4-for-1 give exactly the old scores ({r['k1N']} trades, {r['k1']} differ)")
    ok(r["safeN"] > 0 and r["safe"] == 0, f"A winner's gap never exceeds his raw edge ({r['safeN']} adjusted verdicts, {r['safe']} broke it)")
    ok(r["evenWin"] == 0, f"A raw about-even trade never reads as a clear win from the package alone ({r['evenWin']} did)")

    # the same rule in fixed examples (values, not players): concentration counts even at equal counts
    ex = pg.evaluate("""() => { const keep = LEAGUE_DEPTH; LEAGUE_DEPTH = 1; try {
        const f = (a, b) => { const m = tradeModel(a.map(v => ({ value: v })), b.map(v => ({ value: v }))); return [Math.round(m.scoreA), Math.round(m.scoreB), m.adj ? m.adj.swing : 0]; };
        return { conc: f([8000, 1000], [5000, 4000]), even: f([5000, 5000], [5000, 5000]), one: f([9000], [6000, 3000]), z: f([9000, 0], [6000, 3000]) };
      } finally { LEAGUE_DEPTH = keep; } }""")
    ok(ex["conc"][0] > ex["conc"][1] and ex["conc"][2] > 0, f"8,000 + 1,000 reads ahead of 5,000 + 4,000 after the package adjustment ({ex['conc']})")
    ok(ex["even"][2] == 0, f"Two identical packages get no adjustment ({ex['even']})")
    ok(ex["one"] == ex["z"], f"9,000 for 6,000 + 3,000 and 9,000 + a 0 for the same read the same ({ex['one']} / {ex['z']})")

    # ---------------------------------------------------------------- the live calculator: 0-value throw-ins
    def verdict(A, B):
        clear(pg)
        for n in A: add(pg, "A", n)
        for n in B: add(pg, "B", n)
        return read(pg)["title"]
    if len(zeros) >= 2:
        base = verdict([star], two); plus = verdict([star] + zeros[:1], two)
        ok(base == plus and base, f"{star} for {' + '.join(two)}: '{base}' stays '{plus}' with {zeros[0]} (0) added")
        b3 = verdict([star], three); p3 = verdict([star] + zeros[:1], three); p3b = verdict([star] + zeros[:2], three)
        ok(b3 == p3 == p3b and b3, f"{star} for {' + '.join(three)}: '{b3}' stays '{p3}' / '{p3b}' with one and two 0-value players added")
    else:
        ok(False, "The board has two players at value 0 for the throw-in checks")

    # ---------------------------------------------------------------- P1: a player not on the sending team's roster
    clear(pg)
    add(pg, "A", two[0]); add(pg, "B", star)
    pg.evaluate("() => { const w = document.getElementById('tc-why'); if (w) w.open = true; }"); pg.wait_for_timeout(300)
    real = read(pg)
    ok(real["lens"] and real["acc"], f"A real 1-for-1 between the two picked teams has Roster Impact and Acceptance ({real['acc']})")
    add(pg, "A", owner3); pg.wait_for_timeout(300)
    hyp = read(pg)
    ok("isn't on Team Beta's roster" in hyp["warn"] and "Roster Impact, Acceptance and the roster rationale are off" in hyp["warn"],
       f"{owner3} (Team 3's) on Alpha's card: the warning says the roster reads are off ({hyp['warn'][:160]})")
    ok(not hyp["lens"] and not hyp["acc"] and hyp["why"] == "Why?", f"…and there's no Roster Impact lens, no Acceptance and no roster rationale (lens {hyp['lens']}, acc {hyp['acc']}, '{hyp['why']}')")
    ok(bool(hyp["title"]) and hyp["title"] != "Roster impact", f"…while the value verdict still counts him (hypothetical): '{hyp['title']}'")
    # 3-team: Alpha gets Team 3's player "from" Beta, Beta gets Team 4's, Team 4 gets Alpha's star (every team sends one)
    clear(pg)
    if pg.locator("#add-third").is_visible(): pg.click("#add-third"); pg.wait_for_timeout(300)
    setsel(pg, "team-C", "4"); pg.wait_for_timeout(300)
    add(pg, "A", owner3); add(pg, "A", two[0]); add(pg, "B", p4); add(pg, "C", star)   # Beta really sends two[0]
    for recv, frm in (("A", "B"), ("B", "C"), ("C", "A")):
        pg.evaluate("([r, f]) => document.querySelectorAll('select[data-from][data-recv=' + r + ']').forEach(s => { s.value = f; s.dispatchEvent(new Event('change', { bubbles: true })); })", [recv, frm])
    pg.wait_for_timeout(400)
    pg.evaluate("() => { const d = document.getElementById('tc-impact'); if (d) d.open = true; }"); pg.wait_for_timeout(300)
    t3 = read(pg)
    ok("Roster Impact, Acceptance and the roster rationale are off" in t3["warn"], f"3-team: the same warning ({t3['warn'][:140]})")
    ok(not re.search(r"[+−][\d.]+% roster impact|Starting-lineup|lineup score", t3["analysis"] or ""), f"3-team: no roster read for a player his sender doesn't have ({(t3['analysis'] or '')[:120]})")
    ok(len(t3["three"]) == 3, f"3-team: each team still gets its value read ({t3['three']})")

    ok(not pg.errs, f"No page errors ({pg.errs[:2]})")
    br.close()
print(f"\n{fails} failure(s)")
sys.exit(1 if fails else 0)
