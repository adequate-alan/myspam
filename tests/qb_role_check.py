"""Who is expected to play: backup quarterbacks and injured players in weekly projections (Alan, Oct 12).

Found by Alan: in the Week 6 board, Caleb Williams (CHI QB1, injured) was projected 19.2 and Case Keenum (CHI QB3) 19.1.
AM's projections are conditional (what he scores per game when he plays his role; a quarterback's per start), and the
weekly projection showed that number for everyone, so every quarterback who had ever started was projected like a
starter, and injured players (A.J. Brown on IR, 13.7) kept full projections until that week's injury report.
The fix is a role layer (pipeline/roles.py → data/roles.json → contextProjection): expected = conditional × the chance
he plays that role. This suite checks it at three levels:

  A. roles.py on synthetic depth charts and injury reports: starter, backup, third-string, injured starter (ruled Out,
     Questionable by practice, last week's Out, IR), promoted backup, both ahead of QB3 out, a QB missing from the chart,
     RB / WR / TE availability, a stale report; and on the repo's real files, for all 32 teams: start chances sum to at
     most 1 and no team has two quarterbacks expected to start.
  B. ros_model.py: a quarterback's relief appearance is a fraction of a game of evidence (not a start with a starter's
     workload missing), and an RB / WR / TE without a usable previous season is no longer pulled halfway to a starter's
     workload when he plays a few snaps.
  C. The page (frozen test board, frozen Week 4 calendar, roles computed by roles.py from synthetic charts): expected
     = conditional × role, a ruled-out starter reads Out, a promoted backup is projected from his own line, a backup's
     ROS PPG is "If he starts" with no position rank, the Week view shows the expected number, no page errors.

    python3 tests/qb_role_check.py            (CHROMIUM=/path for a non-Playwright Chromium)
"""
import copy, functools, http.server, json, os, re, socketserver, sys, threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "pipeline")); sys.path.insert(0, os.path.join(ROOT, "tests"))
import roles, ros_model as m
import numpy as np

failures = []
def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond: failures.append(msg)
near = lambda a, b, tol=0.011: a is not None and b is not None and abs(a - b) <= tol

# ---------------------------------------------------------------- A. roles.py on synthetic charts
CALEB, BAGENT, KEENUM, OTHER = "11560", "11256", "1737", "9999901"
COLS = ["w", "tm", "opp", "pass_att", "snap"]
INJ_COLS = ["name", "pos", "sid", "status", "practice", "injury", "wed", "thu", "fri"]

def stats_syn(report=None, report_week=6, games=None):
    """CHI with its Week 6 game unplayed; Caleb 2 starts, Bagent 2, Keenum 1 this season (last season: Caleb 17)."""
    g = games or {CALEB: [[1, "CHI", "CAR", 30, 1.0], [2, "CHI", "MIN", 26, 0.86]],
                  BAGENT: [[2, "CHI", "MIN", 9, 0.14], [4, "CHI", "NYJ", 34, 1.0], [5, "CHI", "GB", 21, 0.67]],
                  KEENUM: [[3, "CHI", "PHI", 34, 1.0], [5, "CHI", "GB", 19, 0.33]]}
    return {"season": 2026, "through_week": 5, "cols": COLS,
            "players": {sid: {"n": sid, "p": "QB", "g": gl} for sid, gl in g.items()},
            "schedule_cols": ["w", "opp", "home", "date", "pf", "pa"],
            "schedule": {"CHI": [[5, "GB", 0, "2026-10-11", 7, 31], [6, "ATL", 0, "2026-10-18", None, None], [7, "NE", 1, "2026-10-22", None, None]],
                         "DET": [[5, "KC", 1, "2026-10-11", 20, 17], [6, "TB", 1, "2026-10-18", None, None]]},
            "injuries": {"week": report_week, "cols": INJ_COLS, "teams": {"CHI": report or []}}}
PRIOR = {"cols": COLS, "players": {CALEB: {"n": "c", "p": "QB", "g": [[w, "CHI", "X", 30, 1.0] for w in range(1, 18)]}}}

def chart(qbs, extra=None):
    t = {"CHI": {"QB": [[sid, sid, "QB", st] for sid, st in qbs]}}
    if extra: t["DET"] = extra
    return {"teams": t}

def inj(sid, status, fri=None):
    return [sid, "QB", sid, status, fri, "x", None, None, fri]

def run(qbs, report=None, report_week=6, extra=None):
    return roles.team_roles(stats_syn(report, report_week), chart(qbs, extra), PRIOR)

def chk(R, sid, n=None, l=None, s=None, msg=""):
    r = R[sid]
    good = (n is None or near(r["n"], n)) and (l is None or near(r["l"], l)) and (s is None or near(r["s"], s))
    ok(good, f"{msg}: n={r['n']:.3f} l={r['l']:.3f} s={r['s']:.3f} (want{'' if n is None else f' n={n}'}{'' if l is None else f' l={l}'}{'' if s is None else f' s={s}'})")

# 1. healthy starter: QB1 starts, QB2 only relief, QB3 nothing
R = run([(CALEB, ""), (BAGENT, ""), (KEENUM, "")])
chk(R, CALEB, n=1, s=1, msg="Healthy starter: Caleb (QB1) expected to start")
chk(R, BAGENT, n=0.04, s=0, msg="Healthy starter: Bagent (QB2) only a small relief share")
chk(R, KEENUM, n=0, s=0, msg="Healthy starter: Keenum (QB3) gets nothing")
# 2. starter ruled Out on this week's report (Sleeper lists him 3rd): QB2 starts, QB3 still nothing
R = run([(BAGENT, ""), (KEENUM, ""), (CALEB, "Out")], report=[inj(CALEB, "Out", "DNP")])
chk(R, CALEB, n=0, s=0, msg="Starter ruled Out: Caleb 0")
chk(R, BAGENT, n=1, s=1, msg="Starter ruled Out: Bagent (next in line) starts")
chk(R, KEENUM, n=0, s=0, msg="Starter ruled Out: Keenum (QB3) does not inherit the job")
chk(R, CALEB, l=0.85, msg="Starter ruled Out: Caleb back as the established starter in later weeks (85%)")
# 3. both ahead of QB3 out: only then does QB3 start
R = run([(CALEB, "Out"), (BAGENT, "Out"), (KEENUM, "")], report=[inj(CALEB, "Out"), inj(BAGENT, "Out")])
chk(R, KEENUM, n=1, s=1, msg="QB1 and QB2 both Out: Keenum (QB3) starts")
# 4. Questionable starter: his latest practice decides, the rest goes to QB2, QB3 still nothing
for fri, a in (("FP", 0.9), ("LP", 0.75), ("DNP", 0.4)):
    R = run([(CALEB, "Questionable"), (BAGENT, ""), (KEENUM, "")], report=[inj(CALEB, "Questionable", fri)])
    chk(R, CALEB, s=a, msg=f"Questionable starter, Friday {fri}: Caleb {round(100 * a)}% to start")
    chk(R, BAGENT, s=round(1 - a, 3), msg=f"Questionable starter, Friday {fri}: Bagent starts the rest")
    chk(R, KEENUM, s=0, msg=f"Questionable starter, Friday {fri}: Keenum 0")
    ok(abs(sum(R[x]["s"] for x in (CALEB, BAGENT, KEENUM)) - 1) < 1e-9, f"Questionable starter, Friday {fri}: start chances sum to 1")
# 5. promoted backup (a starting announcement / benching: the healthy starter listed behind him) keeps the job, also later
R = run([(BAGENT, ""), (CALEB, ""), (KEENUM, "")])
chk(R, BAGENT, n=1, l=1, s=1, msg="Promoted backup: Bagent listed QB1 over a healthy Caleb starts, now and later")
chk(R, CALEB, n=0.04, l=0.04, msg="Promoted backup: the healthy ex-starter is the backup, not restored")
# 6. last week's Out (no report for this game yet): genuinely uncertain, not ruled out
R = run([(BAGENT, ""), (KEENUM, ""), (CALEB, "Out")], report=[inj(CALEB, "Out")], report_week=5)
chk(R, CALEB, s=0.3, l=0.85, msg="Last week's Out, no report yet: Caleb 30% to start (85% later)")
chk(R, BAGENT, s=0.7, msg="Last week's Out, no report yet: Bagent 70%")
chk(R, KEENUM, n=0, msg="Last week's Out, no report yet: Keenum 0")
ok(R[CALEB]["fresh"] is False and R[BAGENT]["fresh"] is False, "Last week's report is marked stale (fresh = False)")
# 7. IR starter: out now and not restored later
R = run([(BAGENT, ""), (KEENUM, ""), (CALEB, "IR")])
chk(R, CALEB, n=0, l=0, msg="IR starter: 0 now and later")
chk(R, BAGENT, n=1, l=1, msg="IR starter: Bagent starts now and later")
# 8. a quarterback not on his team's chart: 0; a team with no chart: nothing known (1)
R = run([(CALEB, ""), (BAGENT, "")])
ok(roles.multiplier(R, KEENUM, "QB", "CHI", 6, {"CHI"}) == 0.0, "A quarterback missing from his team's chart: multiplier 0")
ok(roles.multiplier(R, "7777", "QB", "SEA", 6, {"CHI"}) == 1.0, "A team with no chart: no adjustment (1)")
ok(roles.multiplier(R, CALEB, "QB", "CHI", 6, {"CHI"}) == 1.0 and roles.multiplier(R, BAGENT, "QB", "CHI", 7, {"CHI"}) == R[BAGENT]["l"],
   "multiplier(): next game uses n, later weeks use l")
# 9. RB / WR / TE share the field: availability only, backups keep their own role
RB1, RB2, WR1, TE1 = "8001", "8002", "8003", "8004"
extra = {"RB": [[RB1, "a", "RB", "Out"], [RB2, "b", "RB", ""]], "LWR": [[WR1, "c", "WR", "Questionable"]], "TE": [[TE1, "d", "TE", "IR"]]}
st = stats_syn(); st["injuries"]["teams"]["DET"] = [[RB1, "RB", RB1, "Out", "DNP", "x", None, None, "DNP"], [WR1, "WR", WR1, "Questionable", "LP", "x", None, None, "LP"]]
R = roles.team_roles(st, chart([(CALEB, "")], extra), PRIOR)
ok(R[RB1]["n"] == 0 and R[RB2]["n"] == 1, "RB: the starter ruled Out gets 0, the healthy backup keeps his own role (1, not exclusive)")
ok(near(R[WR1]["n"], 0.75) and R[WR1]["s"] is None, "WR: Questionable with a limited practice 75%, no start chance (not exclusive)")
ok(R[TE1]["n"] == 0 and R[TE1]["l"] == 0, "TE on IR: 0 now and later")
# 10. the repo's real files, all 32 teams
stats = json.load(open(os.path.join(ROOT, "data/stats/2026.json"))); depth = json.load(open(os.path.join(ROOT, "data/depth_charts.json")))
prior = json.load(open(os.path.join(ROOT, "data/stats/2025.json")))
R = roles.team_roles(stats, depth, prior)
by = {}
for r in R.values():
    if r["pos"] == "QB": by.setdefault(r["team"], []).append(r)
ok(len(by) >= 32, f"Real depth charts: quarterback rooms for {len(by)} teams")
bad = [t for t, rs in by.items() if sum(r["s"] for r in rs) > 1 + 1e-9 or sum(r["sl"] for r in rs) > 1 + 1e-9]
ok(not bad, f"Real data: each team's start chances sum to at most 1 (next game and later){' · ' + ', '.join(bad) if bad else ''}")
two = [t for t, rs in by.items() if sum(1 for r in rs if r["n"] >= 0.5) > 1]
ok(not two, f"Real data: no team has two quarterbacks expected to start{' · ' + ', '.join(two) if two else ''}")
third = [f"{r['team']} QB{r['depth']}" for rs in by.values() for r in rs if r["depth"] >= 3 and r["n"] >= 0.5 and not all(x["avail"] < 0.5 for x in rs if x["depth"] < r["depth"])]
ok(not third, f"Real data: no third-string or deeper QB expected to start while someone ahead of him is likely available{' · ' + ', '.join(third) if third else ''}")

# ---------------------------------------------------------------- B. ros_model.py: relief games and backup priors
def mstats(players):
    cols = m.STATS + ["w", "tm", "opp", "snap"]
    out = {"season": 2026, "through_week": 5, "cols": cols, "players": {}, "short": {}}
    for sid, (pos, games) in players.items():
        out["players"][sid] = {"n": sid, "p": pos, "g": [[g.get(c, 0) for c in cols] for g in games]}
    return out
def qbg(w, att, snap): return dict(w=w, tm="CHI", opp="X", pass_att=att, pass_cmp=round(att * 0.65), pass_yd=att * 7, snap=snap)
def wrg(w, tgt, snap): return dict(w=w, tm="CHI", opp="X", rec_tgt=tgt, rec=round(tgt * 0.6), rec_yd=tgt * 8, snap=snap)
S = mstats({"qbA": ("QB", [qbg(1, 35, 1.0), qbg(2, 33, 1.0), qbg(3, 36, 1.0), qbg(4, 34, 1.0)]),
            "qbB": ("QB", [qbg(2, 3, 0.08), qbg(3, 34, 1.0), qbg(4, 2, 0.06)]),
            "wrA": ("WR", [wrg(w, 8, 0.9) for w in range(1, 5)]), "wrB": ("WR", [wrg(w, 0, 0.04) for w in range(1, 4)] + [wrg(4, 1, 0.05)])})
fr = m.frame(S, m.scoring())
rf = {(r.id, r.week): r.rf for r in fr.itertuples()}
ok(near(rf[("qbB", 2)], 0.15) and near(rf[("qbB", 3)], 1.0) and rf[("qbA", 1)] == 1.0, "frame(): a QB relief appearance (8% of the snaps) is 0.15 of a game of evidence, a start is 1")
ok(rf[("wrB", 1)] == 1.0, "frame(): other positions' low-snap games keep their full weight (their snaps are their role)")
orig_env = m.team_env
m.team_env = lambda *a, **k: ({}, {})
try:
    rates = m.league_rates([fr])
    ctx = m.prepare(S, None, 5, rates=rates)
    out = m.project_from(ctx).set_index("sleeper_id")
finally:
    m.team_env = orig_env
lb = out.loc["qbB"].line
ok(lb["pass_att"] > 28, f"Per-start volume of a backup with one start and two relief appearances: {lb['pass_att']:.1f} attempts (a starter's, not diluted toward 13)")
ok(out.loc["qbB"].g_eff < 1.5, f"Games of evidence for that backup: {out.loc['qbB'].g_eff:.2f} (one start + two partial relief games)")
lw = out.loc["wrB"].line
ok(lw["rec_tgt"] < 1.5, f"A WR on 4% of the snaps with no previous season: {lw['rec_tgt']:.2f} targets a game (not pulled halfway to a starter's ~8)")
ok(out.loc["wrA"].line["rec_tgt"] > 7, "A starting WR with no previous season keeps his workload")

# ---------------------------------------------------------------- C. the page
from playwright.sync_api import sync_playwright
import fixture_board as FB

FIX_WEEK = 4
def stats_fixture():
    d = json.load(open(os.path.join(ROOT, "data/stats/2026.json")))
    date_i = d["schedule_cols"].index("date")
    w_rows = [r for rows in d["schedule"].values() for r in rows if r[0] == FIX_WEEK]
    first = min(r[date_i] for r in w_rows)
    played = {t for t, rows in d["schedule"].items() if any(r[0] == FIX_WEEK and r[date_i] == first for r in rows)}
    for t, rows in d["schedule"].items():
        for r in rows:
            if r[0] > FIX_WEEK or (r[0] == FIX_WEEK and t not in played): r[4] = r[5] = None
    for pl in d["players"].values():
        pl["g"] = [g for g in pl["g"] if g[0] < FIX_WEEK or (g[0] == FIX_WEEK and g[1] in played)]
    d["short"] = {k: [x for x in v if x[0] < FIX_WEEK] for k, v in d["short"].items()}
    d["through_week"] = FIX_WEEK
    d["injuries"] = {"week": FIX_WEEK, "cols": INJ_COLS, "teams": {}}
    return d
STATS_FIX = stats_fixture()
FRIDAY = "2026-10-02T16:00:00Z"   # Friday noon ET of Week 4: CHI plays Sunday

def roles_file(qbs, report=None, report_week=FIX_WEEK):
    st = copy.deepcopy(STATS_FIX); st["injuries"] = {"week": report_week, "cols": INJ_COLS, "teams": {"CHI": report or []}}
    R = roles.team_roles(st, chart(qbs), prior)
    return {sid: [r["n"], r["l"], r["s"], r["sl"], r["depth"], r["status"], r["team"], r["week"], int(r["fresh"])] for sid, r in R.items()}

class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a): pass
srv = socketserver.TCPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=ROOT))
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{srv.server_address[1]}"
HEALTHY = roles_file([(CALEB, ""), (BAGENT, ""), (KEENUM, "")])

with sync_playwright() as p:
    kw = {"executable_path": os.environ["CHROMIUM"]} if os.environ.get("CHROMIUM") else {}
    br = p.chromium.launch(**kw)
    pg = br.new_page(viewport={"width": 1440, "height": 1000})
    errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.add_init_script("window.__SPM_TEST_HOOKS = true;")
    pg.clock.install(time=FRIDAY)
    FB.route(pg, BASE)
    pg.route("**/data/stats/2026.json", lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps(STATS_FIX)))
    pg.route("**/data/roles.json*", lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps({"updated": "test", "players": HEALTHY})))
    pg.route(re.compile(r"https://(sleepercdn\.com|a\.espncdn\.com|api\.sleeper\.(app|com)|use\.typekit\.net)/.*"), lambda r: r.abort())
    pg.goto(BASE + "/#rankings"); pg.wait_for_timeout(2500)
    get = lambda sid, w=FIX_WEEK: pg.evaluate("([s, w]) => SPM.weekOutlookOf(s, w)", [sid, w])
    setr = lambda R: pg.evaluate("R => SPM.setRoles(R, 'test')", R)

    # healthy starter
    c, b, k = get(CALEB), get(BAGENT), get(KEENUM)
    ok(c["kind"] == "upcoming" and near(c["est"], c["cond"], 0.001), f"Page, healthy: Caleb's weekly projection is his own conditional number ({c['est']:.1f})")
    ok(near(b["est"], 0.04 * b["cond"], 0.02), f"Page, healthy: Bagent (QB2) {b['est']:.1f} = 4% relief share of his {b['cond']:.1f}")
    ok(k["est"] == 0 and k["cond"] > 5, f"Page, healthy: Keenum (QB3) 0.0 expected (if he started: {k['cond']:.1f})")
    ok(any("QB3 on the depth chart" in s and "if he starts" in s for s in k["inputs"]), "Page: Keenum's projection inputs say QB3 on the depth chart and what he'd score if he started")
    ok(c["rosRank"] is not None and k["rosRank"] is None and k["backup"] and b["backup"], "Page: backups' ROS PPG has no QB rank (\"If he starts\"); the starter keeps his")
    ok(k["ros"] is not None and k["ros"] > 0, "Page: Keenum's ROS PPG itself is unchanged (conditional per start)")
    # The board's team column can lag a move (J.J. McCarthy: MIN on the board, NYG's QB3 on Sleeper): the role from the
    # roles file still applies when Sleeper's player file puts him on the roles' team (Oct 14 valuation audit)
    MCC = "11565"
    sp_team = json.load(open(os.path.join(ROOT, "data", "sleeper_players.json"))).get(MCC, [None, None, None])[2]
    brd_team = next((l.split(",")[2] for l in open(os.path.join(ROOT, "tests", "fixtures", "board", "rankings.csv")) if f",{MCC}," in l), None)
    if sp_team and brd_team and sp_team != brd_team:
        setr({**HEALTHY, MCC: [0.0, 0.0, 0.0, 0.0, 3, None, sp_team, FIX_WEEK, 1]})
        m = get(MCC)
        ok(m["est"] == 0 and m["cond"] > 0, f"Page, board team {brd_team} vs Sleeper {sp_team}: McCarthy (QB3 on {sp_team}'s chart) is projected 0.0, not his conditional {m['cond']:.1f}")
        ok(m["backup"] and m["rosRank"] is None, "Page: and his ROS PPG reads \"If he starts\" with no QB rank")
        setr({**HEALTHY, MCC: [0.0, 0.0, 0.0, 0.0, 3, None, "ZZZ", FIX_WEEK, 1]})
        ok(get(MCC)["est"] > 0, "Page: a roles entry for a team neither the board nor Sleeper names him on still isn't applied")
        setr(HEALTHY)
    else:
        ok(True, f"Page: McCarthy's board and Sleeper teams agree ({brd_team}), team-mismatch case not testable on this data")
    # starter ruled Out this week (Sleeper lists him 3rd)
    setr(roles_file([(BAGENT, ""), (KEENUM, ""), (CALEB, "Out")], report=[inj(CALEB, "Out", "DNP")]))
    c, b, k = get(CALEB), get(BAGENT), get(KEENUM)
    ok(c["kind"] == "out" and c["est"] == 0, "Page, starter ruled Out: Caleb reads Out")
    ok(near(b["est"], b["cond"], 0.001), f"Page, starter ruled Out: Bagent projected from his own line ({b['est']:.1f})")
    ok(k["est"] == 0, "Page, starter ruled Out: Keenum (QB3) still 0, he doesn't inherit Caleb's projection")
    ok(abs(b["cond"] - c["cond"]) > 1, f"Page: the promoted backup's projection is his own ({b['cond']:.1f}), not a copy of the starter's ({c['cond']:.1f})")
    c5 = get(CALEB, 5)
    ok(c5["kind"] == "upcoming" and near(c5["est"], 0.85 * c5["cond"], 0.02), f"Page: in later weeks Caleb is back as the starter at 85% ({c5['est']:.1f})")
    # last week's Out, no report yet
    setr(roles_file([(BAGENT, ""), (KEENUM, ""), (CALEB, "Out")], report=[inj(CALEB, "Out")], report_week=FIX_WEEK - 1))
    c, b = get(CALEB), get(BAGENT)
    ok(c["kind"] == "upcoming" and near(c["est"], 0.3 * c["cond"], 0.02) and near(b["est"], (0.7 + 0.04 * 0.3) * b["cond"], 0.02),
       f"Page, uncertain (last week's Out): Caleb {c['est']:.1f} (30%), Bagent {b['est']:.1f} (70%)")
    ok(any("last week" in s for s in c["inputs"]), "Page: the input line says the designation is last week's")
    # Safeguard: a missing, unreadable or incomplete roles file never brings back starter-level projections for backups.
    # The fallback starter is the team's QB with the most snaps in its latest game (from the stats file).
    ci = {c: i for i, c in enumerate(STATS_FIX["cols"])}
    last = {}
    for sid_, pl in STATS_FIX["players"].items():
        if pl.get("p") != "QB" or not pl["g"]: continue
        g = pl["g"][-1]; tm, w, sn = g[ci["tm"]], g[ci["w"]], g[ci["snap"]] or 0
        if tm and (tm not in last or (w, sn) > last[tm][:2]): last[tm] = (w, sn, sid_)
    chi_fb = last["CHI"][2]
    def qb_rooms():
        return pg.evaluate("""async () => { const out = {}; const sp = await (await fetch('data/sleeper_players.json')).json();
          for (const [sid, v] of Object.entries(sp)) { if (v[1] !== 'QB' || !v[2]) continue; const o = await SPM.weekOutlookOf(sid, 4);
            if (o && o.kind === 'upcoming' && o.est != null && o.est >= 5) (out[v[2]] = out[v[2]] || []).push([v[0], Math.round(o.est * 10) / 10]); }
          return out; }""")
    for label, R in (("missing", {}), ("unreadable", "garbage"), ("malformed entries", {CALEB: [2, 1, 1, 1, 1, None, "CHI", 4, 1], KEENUM: ["x"]})):
        setr(R)
        c, b, k = get(CALEB), get(BAGENT), get(KEENUM)
        fb = {CALEB: c, BAGENT: b, KEENUM: k}
        starters = [s_ for s_, o in fb.items() if o["est"] > 0]
        ok(all(o["fallback"] for o in fb.values()) and starters == ([chi_fb] if chi_fb in fb else []),
           f"Page, roles {label}: CHI's QBs fall back to the latest starter only ({[n for n, s_ in (('Caleb', CALEB), ('Bagent', BAGENT), ('Keenum', KEENUM)) if s_ in starters]})")
        ok(all(o["est"] == 0 for s_, o in fb.items() if s_ != chi_fb), f"Page, roles {label}: every CHI QB but the latest starter gets 0 (on this frozen Week 4 board Keenum started CHI's latest game, Week 3)")
        ok(any("Depth-chart roles" in x for x in (fb[chi_fb] if chi_fb in fb else k)["inputs"]), f"Page, roles {label}: the input line says the roles data is unavailable")
        note = pg.evaluate("() => SPM.rolesNote()")
        ok(note.startswith("Depth-chart roles"), f"Page, roles {label}: a visible warning ({note})")
    rooms = qb_rooms()
    multi = {t: v for t, v in rooms.items() if len(v) > 1}
    ok(not multi and len(rooms) >= 28, f"Page, no roles file: across {len(rooms)} teams no QB room has two projections of 5+ points" + (f" ({multi})" if multi else ""))
    # stale file: still used (its depth order protects backups), flagged
    pg.evaluate("R => SPM.setRoles(R, '2026-09-01T12:00Z')", HEALTHY)
    k, c = get(KEENUM), get(CALEB)
    note = pg.evaluate("() => SPM.rolesNote()")
    ok(k["est"] == 0 and not k["fallback"] and "out of date" in note, f"Page, stale roles file: still applied (Keenum 0.0) with a warning ({note})")
    ok(any("out of date" in x for x in c["inputs"]), "Page, stale roles file: the input line carries the warning")
    # the Week view shows the expected number
    setr(HEALTHY)
    pg.evaluate("() => { const s = document.getElementById('rk-week'); s.value = '4'; s.dispatchEvent(new Event('change')); }"); pg.wait_for_timeout(500)
    pg.click("#pos-chips [data-pos=QB]"); pg.wait_for_timeout(400)
    cell = pg.evaluate("""() => { const out = {}; document.querySelectorAll('#rank-body tr.player').forEach(tr => { const n = tr.querySelector('.pl-name'); const v = tr.querySelector('.pnum');
        if (n && v) out[n.textContent.trim()] = Number(v.firstChild.textContent); }); return out; }""")
    k, c = get(KEENUM), get(CALEB)
    cnt = pg.evaluate("() => document.getElementById('rank-count').textContent")
    ok("Depth-chart roles" in cnt, f"Week view: the count line warns that the roles data is incomplete in this test setup ({cnt[:120]})")
    ok(cell.get("Case Keenum") is not None and near(cell["Case Keenum"], k["est"], 0.06) and near(cell.get("Caleb Williams"), c["est"], 0.06),
       f"Week 4 view: Keenum {cell.get('Case Keenum')} and Caleb {cell.get('Caleb Williams')} show the expected numbers")
    # the drawer's ROS line labels the backup
    pg.evaluate("() => { const s = document.getElementById('rk-week'); s.value = ''; s.dispatchEvent(new Event('change')); }"); pg.wait_for_timeout(400)
    pg.locator("#rank-body tr.player", has_text="Case Keenum").locator(".pl-name").click(); pg.wait_for_timeout(1200)
    txt = pg.evaluate("() => (document.querySelector('dialog.pm[open] .pk-ros, dialog.pm[open] .pm-ros') || {}).textContent || ''")
    ok("If he starts" in txt and not re.search(r"\bQB\d+\b", txt.split("If he starts")[0].replace("ROS PPG", "")), f"Drawer: Keenum's ROS PPG reads \"If he starts\" with no QB rank ({txt.strip()[:80]})")
    ok(not errs, "No page errors" + (": " + "; ".join(errs[:3]) if errs else ""))
    br.close()

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
