"""Data freshness, source by source (Alan, Nov 1: site audit P1-1, "source-specific schedules and alerts"). No browser.

pipeline/data_freshness.py decides, for each source the scheduled jobs refresh, whether the site's copy is current,
will be picked up by the next run, has missed one refresh (a warning), is waiting on its provider (a warning) or is
overdue (fails the freshness job).
Synthetic data on the real workflow's schedule, with nflverse's rebuild times given instead of asked for:

  A. The schedule is read from the workflow: Eastern-time crons follow daylight saving, the 8-hourly market runs,
     the nightly suite and the catch-ups don't count as refreshes.
  B. A normal week: every source current at many times of the week, no warning.
  C. Roles / depth charts: one dropped run is tolerated (GitHub drops some), two in a row are overdue; a late start
     within the grace isn't.
  D. Market: two missed syncs overdue; FantasyCalc failing while our runs ran = waiting, overdue after 48 h.
  E. Stats: a game's lines before they're due = current; due and nflverse hasn't published = waiting; nflverse
     published and no run since yet = pending, one run since = behind (warning), two = overdue; unknown for 48 h = overdue.
  F. Practice reports (Alan's table, Nov 1): nflverse not posting = waiting, a warning, never a failure (the site
     honestly shows it as Pending); nflverse posted it and no refresh since = pending, one refresh missed = behind
     (warning), two missed = overdue (fails); caught up = current. Wed / Thu / Fri due times; no games = off.
  G. Projections follow weekly_due.py unchanged.
  H. report_day matches build_stats.report_day (when pandas is installed).
  I. The command line: --github prints ::error:: / ::warning::, writes the summary table and exits 1 only when overdue.

    python3 tests/data_freshness_check.py
"""
import datetime as dt, json, os, shutil, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "pipeline"))
import data_freshness as df

failures = []
def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond: failures.append(msg)

U = lambda s: dt.datetime.fromisoformat(s).replace(tzinfo=df.UTC)
Z = lambda t: t.strftime("%Y-%m-%dT%H:%MZ")
WF = os.path.join(ROOT, ".github/workflows/site.yml")
S = df.Schedule(WF)

# A. the schedule
sat = S.runs("stats", U("2026-10-31T00:00"), U("2026-10-31T23:59"))
sat2 = S.runs("stats", U("2026-11-07T00:00"), U("2026-11-07T23:59"))
ok(U("2026-10-31T13:17") in sat and U("2026-10-31T20:17") in sat and U("2026-11-07T14:17") in sat2 and U("2026-11-07T21:17") in sat2,
   "A. Saturday's 9:17 AM / 4:17 PM ET runs are 13:17 / 20:17 UTC in daylight time and 14:17 / 21:17 UTC after the clocks change")
mk = S.runs("market", U("2026-11-03T00:00"), U("2026-11-03T23:59")); st = S.runs("stats", U("2026-11-03T00:00"), U("2026-11-03T23:59"))
ok({U("2026-11-03T00:20"), U("2026-11-03T08:20"), U("2026-11-03T16:20")} <= set(mk) and not any(t.minute == 20 for t in st)
   and U("2026-11-03T14:00") in st and U("2026-11-03T08:30") in st,
   "A. Market runs every 8 hours count for the market only; Tuesday's 08:30 and weekly 14:00 runs refresh stats too")
allday = S.runs("market", U("2026-11-02T00:00"), U("2026-11-09T00:00"))
ok(not any(t.minute == 37 or (t.hour, t.minute) == (7, 15) for t in allday), "A. The nightly suite and the weekly catch-ups aren't counted as refreshes")

# synthetic data: two teams, Week 8 Thursday game and Week 8 / 9 Sunday games
def stats_file(lines=(), scores=(), inj=None, updated="2026-10-31T17:46Z"):
    sch = {"NYJ": [[8, "LV", 1, "2026-11-01", None, None, "13:00", 0, 0, None, None], [9, "KC", 0, "2026-11-08", None, None, "13:00", 0, 0, None, None]],
           "LV":  [[8, "NYJ", 0, "2026-11-01", None, None, "13:00", 0, 0, None, None], [9, "DEN", 1, "2026-11-08", None, None, "16:25", 0, 0, None, None]],
           "SEA": [[8, "LA", 1, "2026-10-29", None, None, "20:15", 0, 0, None, None], [9, "ARI", 1, "2026-11-08", None, None, "16:05", 0, 0, None, None]],
           "LA":  [[8, "SEA", 0, "2026-10-29", None, None, "20:15", 0, 0, None, None], [9, "NO", 0, "2026-11-08", None, None, "13:00", 0, 0, None, None]]}
    for tm, w in scores:
        for r in sch[tm]:
            if r[0] == w: r[4], r[5] = 24, 17
    players = {str(i): {"n": f"P{i}", "p": "WR", "g": [[w, tm, "X"] + [0] * 31]} for i, (tm, w) in enumerate(lines)}
    return {"season": 2026, "through_week": 8, "updated": updated, "players": players, "schedule": sch,
            "injuries": inj if inj is not None else {"week": 8, "day": "fri", "source_updated": "2026-10-31T13:34Z", "teams": {}, "undated": []}}

TMP = tempfile.mkdtemp()
def root(stats=None, roles="2026-10-31T23:26Z", depth="2026-10-31T23:26Z", market=None, proj="2026-10-27T14:40Z", name="r"):
    root.n = getattr(root, "n", 0) + 1
    d = os.path.join(TMP, f"{name}{root.n}")
    os.makedirs(os.path.join(d, "data/stats")); os.makedirs(os.path.join(d, "data/market")); os.makedirs(os.path.join(d, ".github/workflows"))
    shutil.copy(WF, os.path.join(d, ".github/workflows/site.yml"))
    w = lambda p, o: json.dump(o, open(os.path.join(d, p), "w"))
    w("data/stats/2026.json", stats if stats is not None else stats_file(lines=[("SEA", 8), ("LA", 8)], scores=[("SEA", 8), ("LA", 8)]))
    w("data/roles.json", {"updated": roles}); w("data/depth_charts.json", {"updated": depth}); w("data/projections.json", {"updated": proj})
    w("data/market/redraft.json", market or {"updated": "2026-11-01T06:25Z", "sync": {"attempted": "2026-11-01T06:25Z", "ok": True}})
    return d
def run(d, now, up=None):
    up = up or {}
    return {r["source"]: r for r in df.check_all(d, U(now), lambda k, s: up.get(k))}

# B. a normal week, every source refreshed by the run just before
def current_at(now):
    t = U(now); last = max(S.runs("stats", t - dt.timedelta(days=3), t - dt.timedelta(hours=1)))
    mlast = max(S.runs("market", t - dt.timedelta(days=3), t - dt.timedelta(hours=1)))
    up = Z(last + dt.timedelta(hours=1)); mup = Z(mlast + dt.timedelta(hours=1))
    played = [(tm, 8) for tm in ("SEA", "LA")] + ([(tm, 8) for tm in ("NYJ", "LV")] if t > U("2026-11-02T15:00") else [])
    inj = {"week": 8, "day": "fri", "source_updated": "2026-10-31T13:34Z"} if t < U("2026-11-03") else {"week": 8, "day": "fri", "source_updated": "2026-10-31T13:34Z"}
    d = root(stats_file(lines=played, scores=played, inj=inj), roles=up, depth=up, proj="2026-11-03T14:40Z" if t > U("2026-11-03T14:40") else "2026-10-27T14:40Z",
             market={"updated": mup, "sync": {"attempted": mup, "ok": True}}, name="b")
    return run(d, now)
bad = {}
for now in ["2026-10-31T21:00", "2026-11-01T09:00", "2026-11-01T20:00", "2026-11-02T10:00", "2026-11-02T20:00", "2026-11-03T03:00", "2026-11-04T12:00", "2026-11-05T09:00"]:
    res = current_at(now)
    b = {k: r["state"] for k, r in res.items() if r["state"] not in ("current", "pending", "off")}
    if b: bad[now] = b
ok(not bad, f"B. A normal week: no warning or alarm at any of 8 times from Saturday to Thursday {bad}")

# C. roles / depth charts: one dropped run tolerated, two overdue
# runs Mon 05:00, 08:30, 15:00 UTC; data from the Sunday 15:00 run (committed 19:00)
r1 = run(root(roles="2026-11-01T19:00Z", depth="2026-11-01T19:00Z", name="c"), "2026-11-02T17:00")   # due: Mon 05:00 and 08:30 (+8 h by 16:30)
r2 = run(root(roles="2026-11-02T06:10Z", depth="2026-11-02T06:10Z", name="c"), "2026-11-02T17:00")   # Mon 05:00 ran, 08:30 dropped
r3 = run(root(roles="2026-11-01T19:00Z", depth="2026-11-01T19:00Z", name="c"), "2026-11-02T16:00")   # 08:30 still within its grace
ok(r1["roles"]["state"] == "overdue" and r1["depth charts"]["state"] == "overdue" and "Mon Nov 02 05:00" in r1["roles"]["detail"],
   f"C. Two scheduled runs in a row leave no update: roles and depth charts overdue ({r1['roles']['detail']})")
ok(r2["roles"]["state"] == "current" and r3["roles"]["state"] == "current",
   "C. One dropped run is tolerated, and a run still inside its 8-hour grace isn't missed yet")

# Alan, Nov 1: a run that succeeded with nothing new must never read as a missed refresh. Both builders stamp
# `updated` with the run's own time on every successful write, whatever the content, and the check reads only that.
src = {f: open(os.path.join(ROOT, "pipeline", f)).read() for f in ("build_roles.py", "build_depth_charts.py")}
ok(all('"updated": datetime.now(timezone.utc)' in t for t in src.values()),
   "C. build_roles.py and build_depth_charts.py stamp `updated` = now on every run, unchanged content included")
same = run(root(roles="2026-11-02T06:10Z", depth="2026-11-02T06:10Z", name="c"), "2026-11-02T17:00")
ok(same["roles"]["state"] == same["depth charts"]["state"] == "current",
   "C. Identical depth charts / roles from a successful run = current (only the stamp is read, never a content diff)")

# D. market
mk_ok = lambda up, att=None, okk=True, err="": {"updated": up, "sync": {"attempted": att or up, "ok": okk, "error": err}}
d1 = run(root(market=mk_ok("2026-11-02T00:40Z"), name="d"), "2026-11-02T18:00")   # runs 05:00, 08:20, 08:30 since: last two due 08:20 / 08:30
d2 = run(root(market=mk_ok("2026-11-02T09:00Z"), name="d"), "2026-11-02T18:00")
d3 = run(root(market=mk_ok("2026-11-02T00:40Z", "2026-11-02T15:30Z", False, "HTTP 503"), name="d"), "2026-11-02T18:00")
d4 = run(root(market=mk_ok("2026-10-31T00:40Z", "2026-11-02T15:30Z", False, "HTTP 503"), name="d"), "2026-11-02T18:00")
d5 = run(root(market=mk_ok("2026-11-02T09:00Z", "2026-11-02T16:40Z", False, "HTTP 503"), name="d"), "2026-11-02T18:00")
ok(d1["market"]["state"] == "overdue" and d2["market"]["state"] == "current", "D. Market: no sync from the last two scheduled runs = overdue; a recent one = current")
ok(d3["market"]["state"] == "waiting" and "HTTP 503" in d3["market"]["detail"] and d4["market"]["state"] == "overdue",
   "D. Our runs ran but FantasyCalc failed = waiting (named), overdue once the values are 48 h old")
ok(d5["market"]["state"] == "current" and "failed" in d5["market"]["detail"], "D. One failed sync after a good one stays current, with the failure noted")

# E. stats: Sunday Nov 1, 1 PM ET game NYJ-LV (kickoff 18:00 UTC: EST from Nov 1). Due: two runs after 06:00 UTC Mon
# (08:30, 15:00) + 8 h = Mon 23:00 UTC
thu = [("SEA", 8), ("LA", 8)]
e_none = root(stats_file(lines=thu, scores=thu), name="e")
e_due = df.Schedule(WF).due_after(df.kickoff("2026-11-01", "13:00") + df.STATS_AVAIL, "stats")
ok(e_due == U("2026-11-02T23:00"), f"E. A Sunday 1 PM ET game's stats are due Monday 23:00 UTC (two runs after the usual overnight post + 8 h): {e_due}")
ok(run(e_none, "2026-11-02T22:00")["stats"]["state"] == "current", "E. Before it's due, missing lines are fine")
w = run(e_none, "2026-11-03T01:00", {"stats": U("2026-10-30T09:00")})["stats"]
ok(w["state"] == "waiting" and "Week 8" in w["detail"] and "NYJ" in w["detail"], f"E. Due, nflverse hasn't rebuilt since the game = waiting ({w['detail']})")
o = run(e_none, "2026-11-03T01:00", {"stats": U("2026-11-02T06:00")})["stats"]
ok(o["state"] == "overdue" and "nflverse published" in o["detail"], "E. nflverse rebuilt after the game and two of our runs have passed since = overdue")
p = run(e_none, "2026-11-03T01:00", {"stats": U("2026-11-02T16:00")})["stats"]
ok(p["state"] == "pending", "E. nflverse rebuilt after the game, no run has had its 8 h since = picked up next run, no annotation")
b = run(e_none, "2026-11-03T01:00", {"stats": U("2026-11-02T14:00")})["stats"]
ok(b["state"] == "behind" and "Mon Nov 02 15:00" in b["detail"], f"E. ...one run (Mon 15:00) has had its 8 h and missed it = behind, a warning ({b['detail']})")
ok(run(e_none, "2026-11-03T01:00")["stats"]["state"] == "waiting" and run(e_none, "2026-11-05T00:00")["stats"]["state"] == "overdue",
   "E. nflverse can't be asked: a warning first, overdue 48 h past due")
half = root(stats_file(lines=thu + [("NYJ", 8)], scores=thu + [("NYJ", 8), ("LV", 8)]), name="e")
ok(run(half, "2026-11-03T01:00", {"stats": U("2026-11-02T06:00")})["stats"]["state"] == "overdue", "E. One team's lines missing is enough")
full = root(stats_file(lines=thu + [("NYJ", 8), ("LV", 8)], scores=thu + [("NYJ", 8), ("LV", 8)]), name="e")
ok(run(full, "2026-11-03T01:00")["stats"]["state"] == "current", "E. Every game due has lines and a score = current")

# F. practice reports for Week 9 (Sunday Nov 8). Wed report reaches nflverse ~Thu Nov 5 morning ET; due two runs after
# Thu 16:00 UTC (Thu 22:00, Fri 08:30) + 8 h = Fri 16:30 UTC. Thu: two runs after Fri 16:00 (Fri 22:00, Sat 14:17) + 8 h
# = Sat 22:17. Fri: two runs after Sat 16:00 (16:45, 21:17) + 8 h = Sun 05:17 UTC.
def prac(week, day, src, now, up=None):
    st = stats_file(lines=thu + [("NYJ", 8), ("LV", 8)], scores=thu + [("NYJ", 8), ("LV", 8)],
                    inj={"week": week, "day": day, "source_updated": src})
    return run(root(st, name="f"), now, {"injuries": up} if up else None)["practice"]
ok(prac(8, "fri", "2026-10-31T13:34Z", "2026-11-04T12:00")["state"] == "current", "F. Wednesday: last week's report is fine, nothing due yet")
ok(prac(8, "fri", "2026-10-31T13:34Z", "2026-11-06T16:00")["state"] == "current", "F. Friday 16:00 UTC: Wednesday's report not due yet")
f1 = prac(8, "fri", "2026-10-31T13:34Z", "2026-11-06T17:00", U("2026-11-05T13:00"))
ok(f1["state"] == "overdue" and "Wed" in f1["detail"], f"F. Friday 17:00: nflverse has had Wednesday's report since Thursday morning and we don't = overdue ({f1['detail']})")
f2 = prac(8, "fri", "2026-10-31T13:34Z", "2026-11-06T17:00", U("2026-10-31T13:34"))
ok(f2["state"] == "waiting", "F. nflverse hasn't posted Week 9 yet = waiting")
ok(prac(8, "fri", "2026-10-31T13:34Z", "2026-11-09T02:00", U("2026-10-31T13:34"))["state"] == "waiting",
   "F. ...and it never turns into an alarm while nflverse hasn't posted (the site shows Pending)")
ok(prac(9, "wed", "2026-11-05T13:00Z", "2026-11-07T20:00")["state"] == "current", "F. Saturday 20:00: Wednesday's report in, Thursday's not due until 22:17")
f3 = prac(9, "wed", "2026-11-05T13:00Z", "2026-11-07T23:00", U("2026-11-06T13:10"))
ok(f3["state"] == "overdue" and "Thu" in f3["detail"], "F. Saturday 23:00: Thursday's report on nflverse since Friday but not here = overdue")
ok(prac(9, "thu", "2026-11-06T13:10Z", "2026-11-08T06:00", U("2026-11-07T15:00"))["state"] == "overdue"
   and prac(9, "fri", "2026-11-07T15:00Z", "2026-11-08T06:00")["state"] == "current",
   "F. Sunday 06:00: Friday's final report is due (overdue when nflverse had it, current once it's here)")
f4 = prac(9, "thu", "2026-11-06T13:10Z", "2026-11-08T06:00", U("2026-11-08T03:00"))
ok(f4["state"] == "pending", "F. nflverse posted Friday's report late: picked up by the next run, no alarm yet")
# alan's four states (Nov 1) on Thursday's Week 9 report, nflverse posting it Fri Nov 6 13:10 UTC (runs after it:
# Fri 15:00, Fri 22:00, Sat 14:17 ET-cron, ...; each counts once its 8 h have passed)
th = lambda now, up: prac(9, "wed", "2026-11-05T13:00Z", now, up)
s1, s2, s3 = th("2026-11-06T20:00", U("2026-11-06T13:10")), th("2026-11-07T02:00", U("2026-11-06T13:10")), th("2026-11-07T07:00", U("2026-11-06T13:10"))
ok(th("2026-11-07T23:00", U("2026-11-05T13:00"))["state"] == "waiting", "F. Alan's table: nflverse hasn't published Thursday's report = warning only")
ok(s1["state"] == "pending" and s2["state"] == "behind" and s3["state"] == "overdue",
   f"F. Alan's table: published, no refresh due yet = pending; one refresh missed = warning; two missed = failure ({s2['detail']} | {s3['detail']})")
ok(prac(9, "thu", "2026-11-06T13:10Z", "2026-11-07T07:00", U("2026-11-06T13:10"))["state"] == "current", "F. Alan's table: source updated and Adequate caught up = healthy")
ok(th("2026-11-07T02:00", U("2026-11-06T13:10"))["state"] == "behind" and prac(9, "wed", "2026-11-05T13:00Z", "2026-11-07T02:00")["state"] == "current",
   "F. Before Thursday's report is due by the clock, only nflverse's own publish time can raise it (offline it stays current)")
ok(prac(9, "fri", "2026-11-07T15:00Z", "2026-11-10T12:00")["state"] in ("current", "off"), "F. After the week's games, last week's final report is fine")
off = stats_file(lines=thu, scores=thu); [r.__setitem__(3, "2026-09-13") for rows in off["schedule"].values() for r in rows]
ok(run(root(off, name="f"), "2026-11-04T12:00")["practice"]["state"] == "off", "F. No Sunday games ahead (off-season) = not checked")

# G. projections
pj = lambda u, now: run(root(proj=u, name="g"), now)["projections"]["state"]
ok(pj("2026-10-27T14:40Z", "2026-11-03T13:00") == "current" and pj("2026-10-27T14:40Z", "2026-11-03T15:00") == "pending"
   and pj("2026-10-27T14:40Z", "2026-11-05T01:00") == "overdue" and pj("2026-11-03T14:50Z", "2026-11-05T01:00") == "current",
   "G. Projections: this week's refresh missing = picked up by a catch-up until Thursday 00:00 UTC, then overdue")

# H. report_day agrees with the pipeline
try:
    import build_stats as bs
    same = all(df.report_day(U(t)) == bs.report_day(U(t)) for t in ["2026-10-22T12:55", "2026-10-22T21:30", "2026-10-23T12:00", "2026-10-24T13:00", "2026-10-25T13:00", "2026-10-20T22:00", "2026-11-05T13:00"])
    ok(same and df.REPORT_POSTED_H == bs.REPORT_POSTED_H and df.DAY_OF_REPORT == bs.DAY_OF_REPORT, "H. report_day and its constants match build_stats")
except ImportError:
    print("INFO H. pandas not installed: report_day not compared with build_stats")

# I. command line
def cli(d, now, up):
    summ = os.path.join(TMP, "summary.md"); open(summ, "w").close()
    r = subprocess.run([sys.executable, os.path.join(ROOT, "pipeline/data_freshness.py"), "--root", d, "--now", now, "--github", "--upstream", up],
                       capture_output=True, text=True, env={**os.environ, "GITHUB_STEP_SUMMARY": summ})
    return r.returncode, r.stdout, open(summ).read()
rc, out, summ = cli(root(stats_file(lines=thu, scores=thu), roles="2026-11-01T19:00Z", depth="2026-11-02T06:10Z", name="i"), "2026-11-02T17:00Z", "stats=none,injuries=none")
ok(rc == 1 and "::error title=Stale data: roles::" in out and "depth charts" not in out.split("::error")[1:].__str__()
   and "| roles | Overdue |" in summ and "| depth charts | Current |" in summ,
   "I. --github: an overdue source prints ::error::, the summary table lists every source, and the run fails")
rc, out, summ = cli(root(stats_file(lines=thu, scores=thu), roles="2026-11-02T20:00Z", depth="2026-11-02T20:00Z", market=mk_ok("2026-11-02T20:00Z"), name="i"),
                    "2026-11-03T01:00Z", "stats=2026-10-30T09:00Z,injuries=none")
ok(rc == 0 and "::warning title=Waiting on provider: stats::" in out and "::error" not in out and "| stats | Waiting on provider |" in summ,
   "I. A provider that hasn't published only warns: exit 0")
rc, out, summ = cli(root(stats_file(lines=thu, scores=thu), roles="2026-11-02T20:00Z", depth="2026-11-02T20:00Z", market=mk_ok("2026-11-02T20:00Z"), name="i"),
                    "2026-11-03T01:00Z", "stats=2026-11-02T14:00Z,injuries=none")
ok(rc == 0 and "::warning title=Missed one refresh: stats::" in out and "::error" not in out and "| stats | Missed one refresh |" in summ,
   "I. One missed refresh after nflverse published: ::warning::, exit 0")
rc, out, summ = cli(root(stats_file(lines=thu, scores=thu), market=mk_ok("2026-11-01T17:00Z"), name="i"), "2026-11-01T20:00Z", "stats=none,injuries=none")
ok(rc == 0 and "::error" not in out and "::warning" not in out, "I. Everything current: exit 0, no annotation")

shutil.rmtree(TMP, ignore_errors=True)
print(f"\n{'All checks passed' if not failures else str(len(failures)) + ' checks failed'}")
sys.exit(1 if failures else 0)
