"""Recent form: trend and availability are separate signals (Oct 10). A player ruled out, or who missed his team's
latest games, is never "Cooling" because of the weeks he missed: the trend reads his last three games played
(▲ Rising / ▼ Falling when they run one way, else ▲ Hot / → Steady / ▼ Cooling against his usual) and availability
is its own tag (this week's report status, or "Missed Wk N"). Also the Compare flow: My Team's Compare opens the
drawer on the Compare tab with the search, and the drawer's Compare tab picks a player from the board. And the
drawer itself (Oct 10): a season of only injury exits gives no Season trend, and Compare reads recent scoring from
completed games (a "Last 3 PPG in completed games" row) when a cut-short game is inside the last three.

Synthetic league and synthetic stat lines only (the real stats file is used as a template for its shape).
Run from the repo root:  CHROMIUM=/path/to/chromium python3 tests/form_trend_check.py   (SHOTS=/dir for screenshots)
"""
import os, re, sys, json, copy
HERE = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(HERE, "league_hub_check.py"), encoding="utf-8").read()
exec(src.split("failures = []")[0])   # make_league, L1, sleeper(), serve(), rows, sids, name_of

failures = []
def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond: failures.append(msg)
SHOTS = os.environ.get("SHOTS")

# --- a synthetic season: weeks 1–4 final, week 5 upcoming (Friday noon ET of week 5), report week 5 ---
WEEK = 5
FRIDAY5 = "2026-10-09T16:00:00Z"
DATES = {1: "2026-09-13", 2: "2026-09-20", 3: "2026-09-27", 4: "2026-10-04", 5: "2026-10-11"}
cur = json.load(open(os.path.join(ROOT, "data/stats/2026.json")))
prev = json.load(open(os.path.join(ROOT, "data/stats/2025.json")))
C = cur["cols"]
def line(w, tm, opp, rec, yd, td=0):
    r = [0] * len(C); r[C.index("w")] = w; r[C.index("tm")] = tm; r[C.index("opp")] = opp
    r[C.index("rec_tgt")] = rec + 2; r[C.index("rec")] = rec; r[C.index("rec_yd")] = yd; r[C.index("rec_td")] = td
    r[C.index("snap")] = 0.8; r[C.index("tgt_share")] = 0.2
    return r
info = {r["sleeper_id"]: r for r in rows}
mine = L1["rosters"][0]["players"]
# five of my players (RB/WR/TE/QB are all fine: the lines are receiving lines, Full PPR → rec + 0.1 yd + 6 td) and one free agent
CASES = {}
def case(key, sid, games, report=None, short=None):
    CASES[key] = {"sid": sid, "name": info[sid]["player"], "team": info[sid]["team"], "games": games, "report": report, "short": short}
P = [s for s in mine if info[s]["pos"] in ("RB", "WR", "TE", "QB")][:10]
FA = next(s for s in L1["free"][2:] if info[s]["pos"] in ("RB", "WR", "TE"))   # free[0] was claimed, free[1] added
# A: the Rashee Rice case: 2.9 → 12.3 → 15.8, then ruled out (missed week 4, Out on the week 5 report)
case("rice", P[0], {1: (2, 9), 2: (4, 83), 3: (7, 88)}, report=("Out", "DNP", "Hamstring"))
# B: a healthy player whose games run down: 24 → 18 → 12 → 6
case("falling", P[1], {1: (8, 160), 2: (6, 120), 3: (4, 80), 4: (2, 40)})
# C: Cooling for real: 10 / 12 / (missed) / 9 against a usual 17.5 (three games this season: last season is the baseline), back and playing
case("cooling", P[2], {1: (4, 60), 2: (4, 80), 4: (3, 60)})
# D: 20 → 25 (above his usual 17.5) then two missed weeks, not on this week's report
case("missed", P[3], {1: (8, 120), 2: (9, 160)})
# E: steady at his usual, Questionable this week
case("quest", P[4], {1: (7, 100), 2: (8, 100), 3: (7, 100), 4: (8, 100)}, report=("Questionable", "LP", "Ankle"))
# G: declining AND injured: 24 → 18 → 12, then out (a real decline is never hidden by the injury)
case("decl_inj", P[5], {1: (8, 160), 2: (6, 120), 3: (4, 80)}, report=("Out", "DNP", "Knee"))
# H: a game cut short by injury (3.0 in week 3, 20% of his snaps) between normal games: never a dip
case("short", P[6], {1: (7, 110), 2: (7, 100), 3: (1, 20), 4: (8, 100)}, short=[3, 0.2, 0.85, "Ankle", 12.0])
# I: one game, then out twice: not enough to call a trend
case("thin", P[7], {1: (6, 90)}, report=("IR", None, "Knee"))
# J: small one-way drift is noise: 19.0 → 17.0 → 16.5 against a usual 17.5 stays → Steady (a direction needs 25%)
case("noise", P[8], {1: (7, 120), 2: (7, 100), 3: (7, 95)})
# K: his only game this season was cut short by injury (3.0 in week 1, 20% of his snaps): no completed game, so no verdict
case("onlyshort", P[9], {1: (1, 20)}, short=[1, 0.2, 0.85, "Knee", 8.0], report=("Out", "DNP", "Knee"))
# F: the same Rice case on a free agent (Waiver Wire)
case("fa", FA, {1: (2, 9), 2: (4, 83), 3: (7, 88)}, report=("Out", "DNP", "Hamstring"))

d = copy.deepcopy(cur); d["through_week"] = WEEK - 1; d["updated"] = "2026-10-09T15:00:00Z"
di = d["schedule_cols"].index("date"); ti = d["schedule_cols"].index("time")
for t, rs in d["schedule"].items():   # every team: weeks 1–4 final (real scores or 20–17), week 5+ unplayed
    for r in rs:
        if r[0] >= WEEK: r[4] = r[5] = None
teams = {c["team"] for c in CASES.values()}
for t in teams:   # the test players' teams play every week 1–5 (no byes in the window)
    opp = next(x for x in d["schedule"] if x != t)
    d["schedule"][t] = [[w, opp, 1, DATES[w], 20 if w < WEEK else None, 17 if w < WEEK else None, "13:00", None, None, "outdoors", "Field"] + [None] * (len(d["schedule_cols"]) - 11) for w in range(1, WEEK + 1)]
for c in CASES.values():
    opp = d["schedule"][c["team"]][0][1]
    d["players"][c["sid"]] = {"n": c["name"], "p": info[c["sid"]]["pos"], "g": [line(w, c["team"], opp, *g) for w, g in sorted(c["games"].items())]}
    d["short"].pop(c["sid"], None)
    if c["short"]: d["short"][c["sid"]] = [c["short"]]
inj = d["injuries"]; inj["week"] = WEEK; ic = inj["cols"]
for t in teams: inj["teams"][t] = []
for c in CASES.values():
    if c["report"]:
        st, pr, what = c["report"]; row = [None] * len(ic)
        row[ic.index("name")] = c["name"]; row[ic.index("pos")] = info[c["sid"]]["pos"]; row[ic.index("sid")] = c["sid"]
        row[ic.index("status")] = st; row[ic.index("practice")] = pr; row[ic.index("injury")] = what; row[ic.index("fri")] = pr
        inj["teams"][c["team"]].append(row)
p25 = copy.deepcopy(prev); C25 = p25["cols"]
for c in CASES.values():   # last season: 8 games of exactly 17.5 (8 rec · 95 yd) = his usual
    g = []
    for w in range(1, 9):
        r = [0] * len(C25); r[C25.index("w")] = w; r[C25.index("tm")] = c["team"]; r[C25.index("opp")] = "X"
        r[C25.index("rec")] = 8; r[C25.index("rec_yd")] = 95; r[C25.index("rec_tgt")] = 10; g.append(r)
    p25["players"][c["sid"]] = {"n": c["name"], "p": info[c["sid"]]["pos"], "g": g}
    if "short" in p25: p25["short"].pop(c["sid"], None)

def freeze5(page):
    page.clock.install(time=FRIDAY5)
    page.route("**/data/stats/2026.json", lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps(d)))
    page.route("**/data/stats/2025.json", lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps(p25)))

FORM = """name => { const tr = [...document.querySelectorAll('%s')].find(r => (r.querySelector('.pl-name') || {}).textContent === name);
  if (!tr) return null; const rf = tr.querySelector('.rf'); if (!rf) return { text: tr.textContent };
  const t = rf.querySelector('.rf-trend'), a = rf.querySelector('.rf-avail');
  return { cells: [...rf.querySelectorAll('.rf-col')].map(c => c.textContent.trim()), sub: (rf.querySelector('.rf-sub') || {}).textContent || '',
    trend: t ? t.textContent : '', trendCls: t ? t.className : '', trendTip: t ? t.title : '', avail: a ? a.textContent : '', availCls: a ? a.className : '', availTip: a ? a.title : '' }; }"""

port = serve()
with sync_playwright() as p:
    br = p.chromium.launch(**({"executable_path": os.environ["CHROMIUM"]} if os.environ.get("CHROMIUM") else {}))
    errs = []
    pg = br.new_page(viewport={"width": 1440, "height": 1000})
    freeze5(pg)
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.route("https://api.sleeper.app/**", sleeper)
    pg.route(re.compile(r"https://(sleepercdn\.com|a\.espncdn\.com|api\.github\.com)/.*"), lambda r: r.abort())
    pg.goto(f"http://127.0.0.1:{port}/#rankings"); pg.wait_for_timeout(4500)
    pg.evaluate("() => { const b = document.createElement('button'); b.dataset.act = 'account'; document.getElementById('league-menu').append(b); b.click(); b.remove(); }")
    pg.wait_for_timeout(400)
    pg.fill("#sd-username", "tester"); pg.press("#sd-username", "Enter"); pg.wait_for_timeout(800)
    pg.locator("#sd-leagues [data-league='L1']").click(); pg.wait_for_timeout(1500)
    ok(pg.evaluate("() => SPM && typeof currentWeek === 'function' ? currentWeek() : null") in (WEEK, None), "synthetic season loaded")
    wk = pg.evaluate("() => (document.querySelector('#rank-body') ? 1 : 0)")

    pg.click("#tab-myteam"); pg.wait_for_timeout(1500)
    if SHOTS: pg.screenshot(path=f"{SHOTS}/form_myteam.png", full_page=True)
    def form(key, sel=".mt-table tr.mt-row"): return pg.evaluate(FORM % sel, CASES[key]["name"])
    f = form("rice")
    ok(f and f["cells"] == ["12.3Wk 2", "15.8Wk 3", "OUTWk 4"] and "Avg 14.1" in f["sub"], f"Rice case: last three team weeks 12.3 · 15.8 · OUT, Avg 14.1 ({f and f['cells']}, {f and f['sub']})")
    ok(f and f["trend"] == "▲ Rising" and "rising" in f["trendCls"] and "2.9 → 15.8" in f["trendTip"] and "Wk 1, 2, 3" in f["trendTip"], f"Rice case: trend reads his games played, ▲ Rising ({f and f['trend']} · {f and f['trendTip']})")
    ok(f and "Cooling" not in f["sub"] and "Falling" not in f["sub"], "Rice case: never Cooling or Falling because of the week he missed")
    ok(f and f["avail"] == "Out" and "out" in f["availCls"] and "Week 5 injury report: Out (Hamstring)" in f["availTip"] and "missed Wk 4" in f["availTip"], f"Rice case: availability is its own tag, Out, from this week's report ({f and f['avail']} · {f and f['availTip']})")
    f = form("falling")
    ok(f and f["cells"] == ["18.0Wk 2", "12.0Wk 3", "6.0Wk 4"] and f["trend"] == "▼ Falling" and "falling" in f["trendCls"] and not f["avail"], f"Falling case: 24 → 18 → 12 → 6 reads ▼ Falling with no availability tag ({f and f['trend']} / '{f and f['avail']}')")
    f = form("cooling")
    ok(f and f["cells"] == ["12.0Wk 2", "OUTWk 3", "9.0Wk 4"] and f["trend"] == "▼ Cooling" and "cool" in f["trendCls"] and "usual 17.5" in f["trendTip"] and f["avail"] == "Back" and "back" in f["availCls"] and "missing Wk 3" in f["availTip"], f"Cooling case: 10 · 12 · 9 against a usual 17.5 still reads ▼ Cooling, with a 'Back' tag for the week he missed ({f and f['trend']} · {f and f['trendTip']})")
    f = form("missed")
    ok(f and f["cells"] == ["25.0Wk 2", "OUTWk 3", "OUTWk 4"] and f["trend"] == "▲ Hot" and "usual 17.5" in f["trendTip"] and f["avail"] == "Missed Wk 3–4" and "out" in f["availCls"], f"Missed case: 20 → 25 (two games: a level, not a direction) then two missed weeks: ▲ Hot + 'Missed Wk 3–4' ({f and f['trend']} / {f and f['avail']})")
    f = form("quest")
    ok(f and f["trend"] == "→ Steady" and f["avail"] == "Questionable" and "q" in f["availCls"].split() and "Week 5 injury report: Questionable (Ankle)" in f["availTip"] and "limited practice" in f["availTip"], f"Questionable case: → Steady with a Questionable tag from the report ({f and f['trend']} / {f and f['avail']} · {f and f['availTip']})")
    f = form("decl_inj")
    ok(f and f["cells"] == ["18.0Wk 2", "12.0Wk 3", "OUTWk 4"] and f["trend"] == "▼ Falling" and f["avail"] == "Out", f"Declining and injured: 24 → 18 → 12 then out still reads ▼ Falling beside Out, the injury hides no real decline ({f and f['trend']} / {f and f['avail']})")
    f = form("short")
    ok(f and f["cells"][1].startswith("3.0") and "*" in f["cells"][1] and f["trend"] == "→ Steady" and "Wk 1, 2, 4" in f["trendTip"] and "Wk 3 cut short by injury, not counted" in f["trendTip"] and not f["avail"], f"Cut-short game: 3.0* in week 3 is skipped, 18 · 17 · 18 reads → Steady, never Cooling ({f and f['trend']} · {f and f['trendTip']})")
    f = form("thin")
    ok(f and f["trend"] == "No trend" and "none" in f["trendCls"] and "Only 1 completed game" in f["trendTip"] and f["avail"] == "IR" and "ir" in f["availCls"].split(), f"Thin data: one game then IR reads 'No trend' + IR, no guess ({f and f['trend']} / {f and f['avail']})")
    f = form("noise")
    ok(f and f["trend"] == "→ Steady" and "within 15%" in f["trendTip"], f"Noise case: 19.0 → 17.0 → 16.5 is not a Falling trend, → Steady against his usual ({f and f['trend']} · {f and f['trendTip']})")
    # the trend never says out and the availability tag never says cooling: two signals, two elements
    allf = [form(k) for k in ("rice", "falling", "cooling", "missed", "quest", "decl_inj", "short", "thin")]
    ok(all(x and not re.search(r"out|missed|back|ir\b", x["trend"], re.I) and not re.search(r"hot|cool|rising|falling|steady|trend", x["avail"], re.I) for x in allf), "Trend labels never carry availability and availability tags never carry form")

    # Waiver Wire shows the same two signals for a free agent
    pg.click("#tab-league"); pg.wait_for_timeout(800)
    pg.click("[data-lsub=waivers]"); pg.wait_for_timeout(1200)
    pg.fill("#fa-search", CASES["fa"]["name"]); pg.wait_for_timeout(600)
    f = form("fa", "#fa-wrap tr")
    ok(f and f.get("trend") == "▲ Rising" and f.get("avail") == "Out", f"Waiver Wire: the same free-agent case reads ▲ Rising + Out ({f})")
    if SHOTS: pg.screenshot(path=f"{SHOTS}/form_waivers.png", full_page=True)

    # --- the player drawer: injury exits never make a verdict on their own (folded in from the weekly check, Oct 10) ---
    pg.click("#tab-myteam"); pg.wait_for_timeout(800)
    f = form("onlyshort")
    ok(f and f["trend"] == "No trend" and f["avail"] == "Out" and "cut short" in f["trendTip"], f"Only a cut-short game: Recent form reads No trend + Out ({f and f['trend']} · {f and f['trendTip']})")
    pg.evaluate("sid => document.querySelector(`#myteam-body .pl-link[data-player='${sid}']`).click()", CASES["onlyshort"]["sid"]); pg.wait_for_timeout(1200)
    tr = pg.evaluate("""() => { const c = [...document.querySelectorAll('.ov-cell')].find(x => (x.querySelector('.ov-label') || {}).textContent === 'Season trend');
      return c ? { val: c.querySelector('.ov-val').textContent.trim(), sub: (c.querySelector('.ov-sub') || {}).textContent || '' } : null; }""")
    ok(tr and tr["val"] == "–" and tr["sub"].startswith("No completed game this season yet") and "injury-shortened" in tr["sub"], f"Drawer: Season trend with only an injury exit is '–' with 'No completed game this season yet', never Down ({tr})")
    pg.keyboard.press("Escape"); pg.wait_for_timeout(400)
    # Compare: a cut-short game inside the last three adds a "completed games" row, and the summary reads recent scoring from it
    pg.evaluate("sid => document.querySelector(`#myteam-body .pl-link[data-player='${sid}']`).click()", CASES["short"]["sid"]); pg.wait_for_timeout(1200)
    pg.click("[data-pp-tab=compare]"); pg.wait_for_timeout(600)
    pg.fill("#pm-pick", CASES["noise"]["name"].split()[-1]); pg.wait_for_timeout(500)
    pg.locator(f".pm-pick-list button:has-text('{CASES['noise']['name']}')").first.click(); pg.wait_for_timeout(1000)
    cm = pg.evaluate("""() => { const rows = [...document.querySelectorAll('.cmp-table tr')].map(r => [...r.children].map(c => c.textContent.trim()));
      const find = l => rows.find(r => r.some(c => c === l)); return { l3: find('Last 3 PPG'), l3full: find('Last 3 PPG in completed games'),
      sum: (document.querySelector('.cmp-sum') || {}).textContent || '', names: [...document.querySelectorAll('.cmp-head .cmp-name')].map(e => e.textContent.trim()) }; }""")
    ok(cm["names"] == [CASES["short"]["name"], CASES["noise"]["name"]], f"Compare opened on {cm['names']}")
    ok(cm["l3"] and cm["l3"][0].startswith("12.7") and "*" in cm["l3"][0] and cm["l3"][2].startswith("17.5"), f"Compare: Last 3 PPG keeps the official 12.7* vs 17.5 ({cm['l3']})")
    ok(cm["l3full"] and cm["l3full"][0] == "17.5" and cm["l3full"][2] == "17.5", f"Compare: a 'Last 3 PPG in completed games' row appears, 17.5 vs 17.5 ({cm['l3full']})")
    ok("recent scoring" not in cm["sum"], f"Compare summary reads recent scoring from completed games, so the cut-short game gives nobody the lead ('{cm['sum'][:90]}')")
    pg.click("[data-pm-uncompare]"); pg.wait_for_timeout(400); pg.keyboard.press("Escape"); pg.wait_for_timeout(400)

    # --- Compare flow ---
    pg.click("#tab-myteam"); pg.wait_for_timeout(800)
    r0 = pg.locator(".mt-table tr.mt-row:has(.mt-act)").first; nm = r0.locator(".pl-name").text_content()
    r0.locator("td.pos-col").hover(); r0.locator("[data-mt-cmp]").click(); pg.wait_for_timeout(1200)
    st = pg.evaluate("""() => { const m = document.getElementById('player-modal'); return { open: m.open, drawer: m.classList.contains('drawer'),
      name: (document.getElementById('pm-name') || {}).textContent, tab: (document.querySelector('.pp-tabs [aria-pressed=true]') || {}).dataset?.ppTab,
      pick: !!document.querySelector('#pm-pick'), focused: document.activeElement && document.activeElement.id === 'pm-pick',
      note: (document.querySelector('.pm-body .empty-note') || {}).textContent || '', banner: !document.getElementById('cmp-banner').hidden }; }""")
    ok(st["open"] and st["drawer"] and st["name"] == nm, f"My Team → Compare opens {nm} in the drawer")
    ok(st["tab"] == "compare" and st["pick"] and st["focused"] and st["note"].startswith("Pick a player to compare with"), f"My Team → Compare lands on the Compare tab with the search focused (tab {st['tab']}, note '{st['note'][:40]}')")
    ok(not st["banner"], "No board pick mode from My Team (the board isn't on screen)")
    other = CASES["falling"]["name"] if nm != CASES["falling"]["name"] else CASES["cooling"]["name"]
    pg.fill("#pm-pick", other.split()[-1]); pg.wait_for_timeout(500)
    pg.locator(f".pm-pick-list button:has-text('{other}')").first.click(); pg.wait_for_timeout(1000)
    cm = pg.evaluate("""() => ({ rows: document.querySelectorAll('.cmp-table tr').length, names: [...document.querySelectorAll('.cmp-head .cmp-name')].map(e => e.textContent.trim()),
      sum: (document.querySelector('.cmp-sum') || {}).textContent || '', tab: (document.querySelector('.pp-tabs [aria-pressed=true]') || {}).dataset?.ppTab })""")
    ok(cm["tab"] == "compare" and cm["rows"] > 8 and cm["names"] == [nm, other] and cm["sum"], f"Picking {other} shows the Compare table ({cm['rows']} rows, {cm['names']})")
    pg.click("[data-pm-swap]"); pg.wait_for_timeout(600)
    cm2 = pg.evaluate("() => [...document.querySelectorAll('.cmp-head .cmp-name')].map(e => e.textContent.trim())")
    ok(cm2 == [other, nm], f"Swap exchanges the two players ({cm2})")
    pg.click("[data-pm-uncompare]"); pg.wait_for_timeout(600)
    ok(pg.evaluate("() => (document.querySelector('.pp-tabs [aria-pressed=true]') || {}).dataset?.ppTab") == "overview" and not pg.evaluate("() => !!document.querySelector('.cmp-table')"), "Stop comparing returns to the Overview")
    pg.keyboard.press("Escape"); pg.wait_for_timeout(400)

    # From the Rankings board: the Compare tab with no Player B opens the search and board pick mode; a board click picks B
    pg.click("#tab-rankings"); pg.wait_for_timeout(800)
    pg.evaluate("i => document.querySelectorAll('#rank-body [data-player]')[i].click()", 5); pg.wait_for_timeout(1200)
    a_name = pg.evaluate("() => document.getElementById('pm-name').textContent")
    pg.click("[data-pp-tab=compare]"); pg.wait_for_timeout(600)
    st = pg.evaluate("() => ({ banner: !document.getElementById('cmp-banner').hidden, pick: !!document.querySelector('#pm-pick'), circles: document.querySelectorAll('#rank-body .cmp-pick, #rank-body [data-cmp-pick]').length })")
    ok(st["banner"] and st["pick"], f"Board drawer: the Compare tab opens the search and board pick mode (banner {st['banner']}, picks {st['circles']})")
    b_name = pg.evaluate("i => document.querySelectorAll('#rank-body [data-player]')[i].closest('tr').querySelector('.pl-name').textContent", 9)
    pg.evaluate("i => document.querySelectorAll('#rank-body [data-player]')[i].click()", 9); pg.wait_for_timeout(1200)
    cm = pg.evaluate("""() => ({ names: [...document.querySelectorAll('.cmp-head .cmp-name')].map(e => e.textContent.trim()), banner: !document.getElementById('cmp-banner').hidden,
      tab: (document.querySelector('.pp-tabs [aria-pressed=true]') || {}).dataset?.ppTab })""")
    ok(cm["tab"] == "compare" and cm["names"] == [a_name, b_name] and not cm["banner"], f"Clicking {b_name} on the board makes him Player B and leaves pick mode ({cm})")
    if SHOTS: pg.screenshot(path=f"{SHOTS}/form_compare.png", full_page=False)
    ok(not errs, f"No page errors ({errs[:3]})")
    br.close()
print(f"\n{len(failures)} failure(s)"); sys.exit(1 if failures else 0)
