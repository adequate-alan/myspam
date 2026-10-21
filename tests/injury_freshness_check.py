"""Injury report freshness (Alan, Oct 21): a practice report speaks for one game only.

Found by Alan: Breece Hall's Week 7 matchup card read "Out · quadricep · did not practice", which was NYJ's Week 6
report. The stats file keeps the latest week's report (data/stats/<season>.json `injuries`), and on Monday and Tuesday
that's still last week's, so every view that read it without checking the week showed last week's practice and game
status as this week's. Rules checked here:

  * DNP / LP / FP and Questionable / Doubtful / Out are shown as current only from the report for the team's next game.
  * Before that report is out, no practice or game status is shown; an injury from last week's report is a dated,
    neutral note ("Quadricep · Out in Week 6"); the Practice Report tab labels last week's report as last week's.
  * The weekly projection: a designation from last week is a prior labelled "last week" (roles.py CARRY, calibrated in
    the Oct 21 projection audit), and a practice-only report (Wednesday / Thursday, no game designations yet) never
    resets an injured player to a full 100% (Kyle Monangai, Oct 21: DNP, Questionable on Sleeper, projected 1.0).
  * Week transitions: Monday / Tuesday (last week's report), Wednesday before his team's report, a practice-only
    report, the final report, a player Out last week who's off this week's report, and a Thursday game whose report
    is for a game already played.

A. roles.py on synthetic reports (no browser). B. the page on the frozen test board, a frozen Week 7 schedule and
clock (Wednesday Oct 21 2026, noon ET), synthetic injury reports and roles computed by roles.py.

    python3 tests/injury_freshness_check.py            (CHROMIUM=/path for a non-Playwright Chromium)
"""
import copy, functools, http.server, json, os, re, socketserver, sys, threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "pipeline")); sys.path.insert(0, os.path.join(ROOT, "tests"))
import roles

failures = []
def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond: failures.append(msg)
near = lambda a, b, tol=0.011: a is not None and b is not None and abs(a - b) <= tol

BREECE, ALLEN, SWIFT, MONANGAI = "8155", "11576", "6790", "12534"
INJ_COLS = ["name", "pos", "sid", "status", "practice", "injury", "wed", "thu", "fri"]
WEEK = 7

# ---------------------------------------------------------------- frozen Week 7 schedule (all Week 6 games played)
def stats_fixture():
    d = json.load(open(os.path.join(ROOT, "data/stats/2026.json")))
    for rows in d["schedule"].values():
        for r in rows:
            if r[0] >= WEEK: r[4] = r[5] = None
    for pl in d["players"].values():
        pl["g"] = [g for g in pl["g"] if g[0] < WEEK]
    d["short"] = {k: [x for x in v if x[0] < WEEK] for k, v in d["short"].items()}
    d["through_week"] = WEEK - 1
    d["injuries"] = {"week": WEEK - 1, "cols": INJ_COLS, "teams": {}}
    return d
STATS = stats_fixture()
PRIOR = json.load(open(os.path.join(ROOT, "data/stats/2025.json")))
DEPTH = json.load(open(os.path.join(ROOT, "data/depth_charts.json")))

def row(name, pos, sid, status, practice, injury, day="fri"):
    return [name, pos, sid, status, practice, injury, practice if day == "wed" else None, practice if day == "thu" else None, practice if day == "fri" else None]

def scenario(week, teams, sleeper=None, played=None):
    """Stats + depth chart for one moment: the report (`week`, `teams`), Sleeper's designations ({sid: status}),
    and teams whose Week 7 game is already final (`played`, e.g. a Thursday game)."""
    st = copy.deepcopy(STATS); st["injuries"] = {"week": week, "cols": INJ_COLS, "teams": teams}
    for tm in played or []:
        for r in st["schedule"].get(tm, []):
            if r[0] == WEEK: r[4], r[5] = 24, 17
    dc = copy.deepcopy(DEPTH)
    for chart in dc["teams"].values():
        for lst in chart.values():
            for x in lst:
                if x[0] in (sleeper or {}): x[3] = sleeper[x[0]]
                elif x[0] in (BREECE, ALLEN, SWIFT, MONANGAI): x[3] = None
    return st, dc

def roles_of(st, dc):
    R = roles.team_roles(st, dc, PRIOR)
    return R, {sid: [r["n"], r["l"], r["s"], r["sl"], r["depth"], r["status"], r["team"], r["week"], int(r["fresh"])] for sid, r in R.items()}

HALL6 = row("Breece Hall", "RB", BREECE, "Out", "DNP", "Quadricep")
SCEN = {
    # Monday / Tuesday: only last week's report; Sleeper still lists last week's Out
    "tue": scenario(WEEK - 1, {"NYJ": [HALL6]}, {BREECE: "Out"}),
    # Wednesday, NYJ hasn't reported yet (CHI has: a Thursday game); last week's report is gone from the file
    "wed_none": scenario(WEEK, {"CHI": [row("Kyle Monangai", "RB", MONANGAI, None, "DNP", "Thumb", "wed")]}, {BREECE: "Out", MONANGAI: "Questionable"}),
    # Wednesday's practice-only report: DNP, no game designation yet
    "wed": scenario(WEEK, {"NYJ": [row("Breece Hall", "RB", BREECE, None, "DNP", "Quadricep", "wed")]}, {BREECE: "Out"}),
    # Friday's final report: Questionable after a limited practice
    "fri": scenario(WEEK, {"NYJ": [row("Breece Hall", "RB", BREECE, "Questionable", "LP", "Quadricep"), row("Braelon Allen", "RB", ALLEN, "Out", "DNP", "Ankle")]}, {BREECE: "Questionable", ALLEN: "Out"}),
    # Out last week, back this week: NYJ's report doesn't list him, Sleeper has cleared him
    "back": scenario(WEEK, {"NYJ": [row("Braelon Allen", "RB", ALLEN, None, "LP", "Ankle", "wed")]}, {}),
    # Thursday game: CHI's Week 7 game is final, its Week 7 report says nothing about Week 8
    "thu": scenario(WEEK, {"CHI": [row("D'Andre Swift", "RB", SWIFT, "Out", "DNP", "Hamstring")]}, {SWIFT: "Out"}, played=["CHI"]),
}
ROLES = {k: roles_of(*v) for k, v in SCEN.items()}

# ---------------------------------------------------------------- A. roles.py
R = ROLES["tue"][0][BREECE]
ok(not R["fresh"] and R["status"] == "Out" and near(R["n"], roles.CARRY["Out"]), f"Tuesday, last week's report: Breece is a 30% prior labelled last week's (n={R['n']}, fresh={R['fresh']})")
R = ROLES["wed"][0][BREECE]
ok(not R["fresh"] and near(R["n"], roles.CARRY["Out"]), f"Wednesday practice-only report (DNP, no designation): Breece keeps the pre-report prior, not 1.0 (n={R['n']})")
R = ROLES["wed_none"][0]
ok(near(R[BREECE]["n"], roles.CARRY["Out"]) and not R[BREECE]["fresh"], "Wednesday before NYJ's report: Breece keeps last week's prior")
ok(near(R[MONANGAI]["n"], roles.CARRY["Questionable"]) and not R[MONANGAI]["fresh"], f"Wednesday practice-only report for a Thursday game: Monangai (DNP, Questionable on Sleeper) {R[MONANGAI]['n']}, not 1.0")
R = ROLES["fri"][0]
ok(R[BREECE]["fresh"] and near(R[BREECE]["n"], roles.AVAIL_Q["LP"]), f"Friday final report: Questionable after a limited practice = {roles.AVAIL_Q['LP']} (n={R[BREECE]['n']})")
ok(R[ALLEN]["n"] == 0 and R[ALLEN]["status"] == "Out", "Friday final report: ruled Out = 0")
R = ROLES["back"][0]
ok(R[BREECE]["n"] == 1 and R[BREECE]["status"] is None, f"Out last week, not on this week's report: Breece back to 1.0 (n={R[BREECE]['n']})")
ok(R[ALLEN]["n"] == 1 and not R[ALLEN]["fresh"], "On this week's practice-only report with no Sleeper designation: 1.0")
R = ROLES["thu"][0][SWIFT]
ok(not R["fresh"] and R["week"] == WEEK + 1 and near(R["n"], roles.CARRY["Out"]), f"Thursday game played: CHI's Week 7 report doesn't decide Week 8 (fresh={R['fresh']}, week={R['week']}, n={R['n']})")
# the final report still decides once any game designation is in (a team listing one player Questionable)
st, dc = scenario(WEEK, {"NYJ": [row("Breece Hall", "RB", BREECE, None, "FP", "Quadricep"), row("Braelon Allen", "RB", ALLEN, "Questionable", "LP", "Ankle")]}, {BREECE: "Out"})
R = roles_of(st, dc)[0]
ok(R[BREECE]["fresh"] and R[BREECE]["n"] == 1, "Final report with designations: a listed player without one plays (1.0)")

# ---------------------------------------------------------------- B. the page
from playwright.sync_api import sync_playwright
import fixture_board as FB

class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a): pass
srv = socketserver.TCPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=ROOT))
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{srv.server_address[1]}"
WEDNESDAY = "2026-10-21T16:00:00Z"
CUR = {"stats": None, "roles": None}

CARD = """sid => { const c = document.querySelector('#player-body .tw-card'); if (!c) return null;
  const chip = c.querySelector('.tw-game .st-badge'), sub = [...c.querySelectorAll('.tw-stat')].find(t => /proj/.test(t.textContent));
  return { chip: chip ? chip.textContent : '', chipCls: chip ? chip.className : '', chipTip: chip ? (chip.title || chip.parentElement.title || chip.getAttribute('data-hc-t') || '') : '',
    notes: [...document.querySelectorAll('#player-body .tw-line')].filter(l => /Practice notes/.test(l.textContent)).map(l => l.textContent).join(' | '),
    proj: sub ? sub.querySelector('.tw-val').textContent : '', projSub: sub && sub.querySelector('.tw-sub') ? sub.querySelector('.tw-sub').textContent : '', text: c.textContent }; }"""

with sync_playwright() as p:
    kw = {"executable_path": os.environ["CHROMIUM"]} if os.environ.get("CHROMIUM") else {}
    br = p.chromium.launch(**kw)
    errs = []

    def page_for(key, width=1440):
        st, dc = SCEN[key]
        pg = br.new_page(viewport={"width": width, "height": 1000})
        pg.on("pageerror", lambda e: errs.append(f"{key}: {e}"))
        pg.clock.install(time=WEDNESDAY)
        FB.route(pg, BASE)
        pg.route("**/data/stats/2026.json", lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps(st)))
        pg.route("**/data/depth_charts.json*", lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps(dc)))
        pg.route("**/data/roles.json*", lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps({"updated": "2026-10-21T15:00Z", "players": ROLES[key][1]})))
        pg.route(re.compile(r"https://(sleepercdn\.com|a\.espncdn\.com|api\.sleeper\.(app|com)|use\.typekit\.net)/.*"), lambda r: r.abort())
        pg.goto(BASE + "/#rankings"); pg.wait_for_timeout(2500)
        return pg

    def open_card(pg, sid, tab=None):
        pg.evaluate("sid => document.querySelector(`#rank-body [data-player=\"${sid}\"]`).click()", sid); pg.wait_for_timeout(1200)
        if tab:
            pg.evaluate("t => document.querySelector(`#player-body [data-pp-tab=\"${t}\"], #player-modal [data-pp-tab=\"${t}\"]`).click()", tab); pg.wait_for_timeout(500)
        return pg.evaluate(CARD, sid) if not tab else pg.inner_text("#player-body")

    def outlook(pg, sid):
        return pg.evaluate("([s, w]) => SPM.weekOutlookOf ? SPM.weekOutlookOf(s, w) : null", [sid, WEEK])

    # Monday / Tuesday: last week's report
    pg = page_for("tue")
    c = open_card(pg, BREECE)
    ok(c is not None and "did not practice" not in c["text"] and "DNP" not in c["chip"], f"Tuesday: Week 7 card shows no practice participation from Week 6 (chip: {c and c['chip']!r})")
    ok("prior" in c["chipCls"] and "Out in Week 6" in c["chip"] and "Quadricep" in c["chip"], f"Tuesday: the injury stays as a dated, neutral note ({c['chip']!r})")
    ok("Week 6" in c["chipTip"] and "No Week 7 practice report" in c["chipTip"], f"Tuesday: its tooltip says it's NYJ's Week 6 report and Week 7's isn't out ({c['chipTip'][:90]!r})")
    ok(not re.search(r"\bout\b", c["chipCls"]), "Tuesday: no Out status colour on the Week 7 card")
    ok("last week" in c["projSub"] and "30%" in c["projSub"], f"Tuesday: the projection tile names the prior as last week's ({c['projSub']!r})")
    o = outlook(pg, BREECE)
    if o: ok(o["kind"] == "upcoming" and near(o["est"], 0.3 * o["cond"], 0.02), f"Tuesday: Week 7 projection {o['est']:.1f} = 30% of {o['cond']:.1f} (calibrated prior, not ruled out)")
    txt = open_card(pg, BREECE, "practice")
    ok("Week 6 report · last week" in txt and "No Week 7 practice report from NYJ yet" in txt, "Tuesday: the Practice Report tab labels NYJ's report as last week's")
    pg.close()

    # Wednesday, before NYJ's report (another team has reported)
    pg = page_for("wed_none")
    c = open_card(pg, BREECE)
    ok(c["chip"] == "" and "did not practice" not in c["text"], f"Wednesday before NYJ's report: no status on the card ({c['chip']!r})")
    txt = open_card(pg, BREECE, "practice")
    ok("No Week 7 practice report yet" in txt, "Wednesday before NYJ's report: Practice Report tab says Week 7's isn't out")
    pg.close()

    # Wednesday's practice-only report
    pg = page_for("wed")
    c = open_card(pg, BREECE)
    ok("did not practice (Wed)" in c["chip"] and "On practice report" in c["chip"], f"Wednesday practice-only report: this week's DNP, dated ({c['chip']!r})")
    ok("Week 7" in c["chipTip"], "Wednesday: the chip's tooltip names the Week 7 report")
    o = outlook(pg, BREECE)
    if o: ok(near(o["est"], 0.3 * o["cond"], 0.02), f"Wednesday practice-only report: projection keeps the 30% prior ({o['est']:.1f}), never a full {o['cond']:.1f}")
    pg.close()

    # Friday's final report
    pg = page_for("fri")
    c = open_card(pg, BREECE)
    ok(c["chip"].startswith("Questionable") and "limited practice (Fri)" in c["chip"], f"Friday final report: {c['chip']!r}")
    ok("Questionable" in c["projSub"] and "68%" in c["projSub"] and "last week" not in c["projSub"], f"Friday: the projection tile says this week's Questionable ({c['projSub']!r})")
    ok("Braelon Allen" in c["notes"] or "Allen" in c["notes"], "Friday: this week's practice notes list his ruled-out teammate")
    pg.close()

    # Out last week, off this week's report
    pg = page_for("back")
    c = open_card(pg, BREECE)
    ok(c["chip"] == "Not on Week 7 report", f"Returning: {c['chip']!r}")
    o = outlook(pg, BREECE)
    if o: ok(near(o["est"], o["cond"], 0.02), f"Returning: full projection {o['est']:.1f}")
    pg.close()

    # Thursday game already played: the Week 7 report isn't Week 8's
    pg = page_for("thu")
    c = open_card(pg, SWIFT)
    ok("prior" in c["chipCls"] and "Out in Week 7" in c["chip"] and "did not practice" not in c["text"], f"After a Thursday game: next week's card shows the Week 7 Out only as a dated note ({c['chip']!r})")
    ok("Final" in c["text"], "After a Thursday game: the card shows his played Week 7 game as Final")
    pg.close()

    # phone: the dated note wraps inside the card
    pg = page_for("tue", 390)
    c = open_card(pg, BREECE)
    w = pg.evaluate("() => { const b = [...document.querySelectorAll('#player-body .tw-card .st-badge.prior')].find(x => x.getBoundingClientRect().width > 0), c = b && b.closest('.tw-card'); return b ? [b.getBoundingClientRect().right, c.getBoundingClientRect().right] : null; }")
    ok(w is not None and w[0] <= w[1] + 0.5, f"390px: the dated note stays inside the card ({w})")
    pg.close()

    ok(not errs, f"No page errors ({errs[:2]})")
    br.close()

srv.shutdown()
print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
