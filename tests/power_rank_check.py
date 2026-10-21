"""Overall Power Rankings as AM-implied expected lineup points (Alan, Oct 21). Synthetic leagues only; no real league
data belongs in the repo.

Run from the repo root:  python3 tests/power_rank_check.py   (CHROMIUM=/path/to/chromium if needed; SHOTS=/dir for screenshots)

Checks:
1. Reproducible: the same numbers twice on one page and after a reload (hashed draws, no Math.random).
2. Each position's value -> points curve never falls as value rises, in a Superflex TE premium league and a 10-team
   1QB Half PPR league.
3. Backup QBs: a QB with under a 50% chance to start gets at most that chance x the curve, never starter-level points;
   out-for-season players count 0.
4. Ranks run 1..n in roster-value order (Alan, Oct 21, later: the team score leads, expected PPG beside it); ppg = lineup + depth; the ideal lineup is never below the expected one.
5. Injured reserve counts as healthy for Power rank (moving team 5's IR players to its bench changes no team's PPG),
   while Starter strength uses the healthy roster only.
6. Close: a team is marked Close exactly when the team above or below is within 2% of its roster value; the gap line says
   how far ahead of #2 (for #1) or behind the team above.
7. 1,600 draws agree with the page's 400 within 0.4 PPG per team.
8. The 7% generic absence costs no team more than 7% of its ideal lineup (the same rate for every player, so injury
   risk AM already priced isn't charged again); deeper benches lose less.
9. A league with kickers and defenses says they aren't valued; a league without says nothing about them.
10. Position lenses still rank by AM value rooms (unchanged); My Team shows Power rank and Starter strength in PPG.
11. No page errors; the list fits a 390px phone.
"""
import os, re, sys, json, statistics
HERE = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(HERE, "league_hub_check.py"), encoding="utf-8").read()
exec(src.split("failures = []")[0])   # make_league, L1, L2, LEAGUES, sleeper(), serve(), freeze()

failures = []
def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond: failures.append(msg)
SHOTS = os.environ.get("SHOTS")

# the 10-team league also starts a kicker and a defense
L2["league"]["roster_positions"] = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF"] + ["BN"] * 6
IR5 = list(L1["rosters"][4]["reserve"])

def open_league(br, lid, theme="dark", width=1440):
    errs = []
    pg = br.new_page(viewport={"width": width, "height": 1000})
    freeze(pg, FRIDAY)
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.route("https://api.sleeper.app/**", sleeper)
    pg.route(re.compile(r"https://(sleepercdn\.com|a\.espncdn\.com|fonts\.(googleapis|gstatic)\.com|use\.typekit\.net)/.*"), lambda r: r.abort())
    pg.add_init_script(f"window.__SPM_TEST_HOOKS = true; try {{ localStorage.setItem('spm_theme', '{theme}'); }} catch (e) {{}}")
    pg.goto(f"http://127.0.0.1:{port}/#rankings"); pg.wait_for_timeout(4500)
    pg.evaluate("() => { const b = document.createElement('button'); b.dataset.act = 'account'; document.getElementById('league-menu').append(b); b.click(); b.remove(); }")
    pg.wait_for_timeout(400)
    pg.fill("#sd-username", "tester"); pg.press("#sd-username", "Enter"); pg.wait_for_timeout(800)
    pg.locator(f"#sd-leagues [data-league='{lid}']").click(); pg.wait_for_timeout(1800)
    pg.click("#tab-league"); pg.wait_for_timeout(600)
    pg.click("[data-lsub=power]"); pg.wait_for_timeout(600)
    return pg, errs

def ppgs(P): return {t["team"]: round(t["ppg"], 6) for t in P["teams"]}
def fnum(s):
    m = re.search(r"-?\d[\d,]*\.?\d*", s); return float(m.group(0).replace(",", "")) if m else None

port = serve()
with sync_playwright() as p:
    br = p.chromium.launch(**({"executable_path": os.environ["CHROMIUM"]} if os.environ.get("CHROMIUM") else {}))
    allerrs = []

    # ---------- Superflex TE premium league ----------
    pg, errs = open_league(br, "L1"); allerrs += errs
    P = pg.evaluate("() => SPM.power()")
    P2 = pg.evaluate("() => SPM.power()")
    ok(len(P["teams"]) == 12 and ppgs(P) == ppgs(P2), "1. The same expected PPG twice on one page")
    ok(len(P["weeks"]) >= 5 and P["haz"] == 0.07 and P["draws"] == 400 and P["closePct"] == 0.02, f"Simulates weeks {P['weeks'][0]}–{P['weeks'][-1]} with a 7% absence rate and 400 draws")

    for pos, pts in P["curves"].items():
        ys = [y for _, y in pts]
        ok(all(b >= a - 1e-9 for a, b in zip(ys, ys[1:])) and ys[-1] > 0, f"2. [SF TE+] {pos} curve never falls as value rises (0 -> {ys[-1]:.1f} PPG at 10,000)")

    curve = lambda pos, v: P["curves"][pos][min(400, max(0, round(v / 25)))][1]
    qbs = [x for x in P["players"] if x["pos"] == "QB" and not x["out"]]
    back = [x for x in qbs if x["start"] is not None and x["start"] < 0.5]
    starters = sorted([x["pts"] for x in qbs if x["start"] is not None and x["start"] >= 0.5 and x["pts"] > 0])
    worst_back = max((x["pts"] / max(curve("QB", x["value"]), 1e-9) - x["start"] for x in back if curve("QB", x["value"]) > 0.5), default=0)
    ok(back and worst_back <= 0.05, f"3. {len(back)} backup QBs (under 50% to start) get at most start chance x curve (worst excess {worst_back:.3f})")
    hi_back = max((x["pts"] for x in back), default=0)
    ok(hi_back <= 0.5 * max(starters[-12:] or [0]) + 1e-9, f"3. No backup QB reaches starter-level points (best backup {hi_back:.1f} vs top starters {starters[-1] if starters else 0:.1f})")
    outs = [x for x in P["players"] if x["out"]]
    ok(all(x["pts"] == 0 for x in outs), f"3. Out-for-season players count 0 ({len(outs)})")

    T = sorted(P["teams"], key=lambda t: t["power"])
    ok([t["power"] for t in T] == list(range(1, 13)) and all(T[i]["score"] >= T[i + 1]["score"] - 1e-9 for i in range(11)), "4. Power ranks run 1..12 in roster-value order")
    ok(all(abs(t["ppg"] - (t["lineup"] + t["depth"])) < 1e-6 and t["ideal"] >= t["ppg"] - 1e-6 and t["depth"] >= -1e-6 for t in T), "4. PPG = starting lineup + depth; the ideal lineup is never below it")
    ok(sorted(t["start"] for t in T) == list(range(1, 13)) and all(
        (a["startPpg"] >= b["startPpg"] - 1e-9) for a in T for b in T if a["start"] < b["start"]), "4. Starter strength ranks follow the healthy lineup's PPG")

    # 6. the list on screen: roster value, PPG under it, Close and the gap line
    items = pg.evaluate("""() => [...document.querySelectorAll('.pr-item')].map(it => ({ rid: Number(it.dataset.rid),
      rank: Number(it.querySelector('.pr-rank').textContent), score: it.querySelector('.pr-score').textContent,
      close: !!it.querySelector('.pr-close'), gap: (it.querySelector('.pr-gap') || {}).textContent || '' }))""")
    byrid = {t["rid"]: t for t in P["teams"]}
    ok([i["rank"] for i in items] == list(range(1, 13)) and all(abs(fnum(i["score"]) - byrid[i["rid"]]["score"]) <= 0.51 for i in items) and "PPG" not in "".join(i["score"] for i in items),
       "6. The main number is each team's roster value, in rank order")
    ok(all(abs(fnum(i["gap"]) - byrid[i["rid"]]["ppg"]) <= 0.051 and "expected PPG" in i["gap"] for i in items), "6. Expected PPG sits under it, secondary")
    near = lambda hi, lo: hi - lo <= 0.02 * max(1, hi)
    want = [(i > 0 and near(T[i - 1]["score"], T[i]["score"])) or (i < 11 and near(T[i]["score"], T[i + 1]["score"])) for i in range(12)]
    ok([i["close"] for i in items] == want, f"6. Close marks exactly the teams within 2% of a neighbour's roster value ({sum(want)} of 12)")
    dnum = lambda g: fnum(g.split("·", 1)[1]) if "·" in g else None
    gaps_ok = "ahead of #2" in items[0]["gap"] and abs(dnum(items[0]["gap"]) - (T[0]["score"] - T[1]["score"])) <= 1 and all(
        f"behind #{k}" in items[k]["gap"] and abs(dnum(items[k]["gap"]) - (T[k - 1]["score"] - T[k]["score"])) <= 1 for k in range(1, 12))
    ok(gaps_ok, f"6. Gap lines in roster value: '{items[0]['gap']}', '{items[1]['gap']}' …")
    ok("ROSTER VALUE" in pg.inner_text(".pr-head").upper(), "6. The column reads Roster value")
    note = pg.inner_text(".method-note")
    ok("Injured reserve counts as if healthy" in note and "Close" in note and "kicker" not in note.lower() and "defense" not in note.lower(),
       "9. The note explains the method and Close, and says nothing about kickers in a league without them")
    if SHOTS: pg.screenshot(path=f"{SHOTS}/power_overall.png")
    # hover card
    pg.locator(".pr-item .pr-strength").first.hover(); pg.wait_for_timeout(700)
    hc = pg.inner_text("#hc") if pg.locator("#hc").is_visible() else ""
    ok("roster value" in hc and "Bench share" in hc and "Expected PPG" in hc and "Depth adds" in hc, f"The strength card explains roster value, then lineup and depth in PPG ({hc[:80]!r})")
    if SHOTS: pg.screenshot(path=f"{SHOTS}/power_card.png")
    pg.mouse.move(5, 5); pg.wait_for_timeout(300)

    # 10. lenses stay on AM value rooms
    rooms = pg.evaluate("() => SPM.powerRooms()")
    pg.click("[data-pb-pos=RB]"); pg.wait_for_timeout(400)
    lens = pg.evaluate("() => [...document.querySelectorAll('.pr-item')].map(it => [Number(it.dataset.rid), Number(it.querySelector('.pr-score').textContent.replace(/\\D/g, ''))])")
    rb = {r["rid"]: r["room"]["RB"] for r in rooms}
    ok(all(abs(v - rb[n]) <= 1 for n, v in lens) and [v for _, v in lens] == sorted([v for _, v in lens], reverse=True), "10. The RB lens still ranks AM value rooms")
    pg.click("[data-pb-pos=OVERALL]"); pg.wait_for_timeout(300)

    # 7. more draws, 8. absence rate
    P16 = pg.evaluate("() => SPM.power({ draws: 1600 })")
    d16 = max(abs(a["ppg"] - b["ppg"]) for a, b in zip(sorted(P["teams"], key=lambda t: t["rid"]), sorted(P16["teams"], key=lambda t: t["rid"])))
    ok(d16 <= 0.4, f"7. 1,600 draws agree with 400 within 0.4 PPG (largest {d16:.2f})")
    P0 = pg.evaluate("() => SPM.power({ haz: 0 })")
    by0 = {t["rid"]: t["ppg"] for t in P0["teams"]}
    drops = [(by0[t["rid"]] - t["ppg"], t["ideal"]) for t in P["teams"]]
    worst = max(d / i for d, i in drops)
    ok(min(d for d, _ in drops) > 0 and worst <= 0.07 + 0.005, f"8. The 7% absence rate costs no team more than 7% of its ideal lineup: the same rate for every player, never extra for injury risk AM already priced (drops {min(d for d, _ in drops):.2f}–{max(d for d, _ in drops):.2f} PPG, at most {100 * worst:.1f}%)")
    P3 = pg.evaluate("() => SPM.power()")
    ok(ppgs(P3) == ppgs(P), "Test re-runs leave the page's own numbers as they were")

    # My Team strip
    pg.click("#tab-myteam"); pg.wait_for_timeout(800)
    mine = next(t for t in P["teams"] if t["rid"] == 1)
    pr_t, st_t = pg.inner_text(".mt-pr"), pg.inner_text(".mt-st")
    ok(f"#{mine['power']}" in pr_t and f"{round(mine['score']):,}" in pr_t, f"10. My Team's Power rank shows roster value ({' '.join(pr_t.split())})")
    ok(f"#{mine['start']}" in st_t and "PPG" in st_t and f"{mine['startPpg']:.1f}" in st_t, f"10. Starter strength shows the healthy lineup's PPG ({' '.join(st_t.split())})")
    if SHOTS: pg.screenshot(path=f"{SHOTS}/power_myteam.png")

    # 1. after a reload
    pg.reload(); pg.wait_for_timeout(5000)
    pg.click("#tab-league"); pg.wait_for_timeout(600)
    ok(ppgs(pg.evaluate("() => SPM.power()")) == ppgs(P), "1. The same expected PPG after a reload")
    pg.close()

    # 5. IR counts as healthy: the same league with team 5's IR players on its bench
    L1["rosters"][4]["reserve"] = []
    pg, errs = open_league(br, "L1"); allerrs += errs
    Q = pg.evaluate("() => SPM.power()")
    t5 = lambda X: next(t for t in X["teams"] if t["rid"] == 5)
    ok(ppgs(Q) == ppgs(P), "5. Moving IR players to the bench changes no team's expected PPG (IR counts as healthy)")
    ok(t5(Q)["startPpg"] >= t5(P)["startPpg"] - 1e-9 and t5(Q)["ideal"] == t5(P)["ideal"], f"5. Starter strength leaves IR out ({t5(P)['startPpg']:.1f} with 2 on IR, {t5(Q)['startPpg']:.1f} without)")
    L1["rosters"][4]["reserve"] = IR5
    pg.close()

    # ---------- 10-team 1QB Half PPR league with K and DEF ----------
    pg, errs = open_league(br, "L2", theme="light"); allerrs += errs
    R = pg.evaluate("() => SPM.power()")
    for pos, pts in R["curves"].items():
        ys = [y for _, y in pts]
        ok(all(b >= a - 1e-9 for a, b in zip(ys, ys[1:])), f"2. [10-team 1QB Half] {pos} curve never falls as value rises")
    ok(R["curves"]["WR"][200][1] != P["curves"]["WR"][200][1], "2. Curves are fitted per league scoring (WR at 5,000 differs between the two leagues)")
    note = pg.inner_text(".method-note")
    ok("Kickers, defenses aren't valued by AM" in note, f"9. A league with K and DEF says they aren't counted")
    T2 = sorted(R["teams"], key=lambda t: t["power"])
    ok([t["power"] for t in T2] == list(range(1, 11)) and all(T2[i]["score"] >= T2[i + 1]["score"] - 1e-9 for i in range(9)), "4. [10-team] ranks follow roster value")
    if SHOTS: pg.screenshot(path=f"{SHOTS}/power_light.png")
    pg.set_viewport_size({"width": 390, "height": 900}); pg.wait_for_timeout(500)
    over = pg.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
    ok(over <= 0, f"11. The Power Rankings fit a 390px phone (overflow {over}px)")
    if SHOTS: pg.screenshot(path=f"{SHOTS}/power_phone.png", full_page=False)
    pg.close()

    ok(not allerrs, f"11. No page errors {allerrs[:3]}")
    br.close()

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
