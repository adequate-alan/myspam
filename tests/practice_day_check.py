"""Practice reports land on the right day (Alan, Oct 22: "this week's practice reports haven't updated"). No browser.

nflverse rebuilds its injuries file about once a day, in the morning ET, so a Thursday run reads Wednesday's report.
build_stats.injuries used to label whatever it read by the run's weekday: Wednesday's DNP / LP / FP went under Thu,
Thursday's under Fri, Friday's final report overwrote Thursday's, and a run on an unchanged file copied the same
report into the next day. Now the day comes from the source file's Last-Modified (report_day).

  A. report_day: a file rebuilt Thu 8:55 AM ET holds Wednesday's report; after ~4 PM ET Thursday's; Saturday's and
     Sunday's rebuilds hold Friday's; Tuesday's (Thursday-game teams) counts as Wednesday.
  B. A week of runs on synthetic files: each day's status lands in its own column, an unchanged file re-read later
     writes nothing new, Friday's final report never overwrites Thursday's, the latest status and game designation
     follow the newest report, and a new week starts empty.
  C. A file labelled the old way (Wednesday's report under Thu) is repaired on the next run: no column after the
     source's report day stays filled.
  D. No source time at all (a local file, no Last-Modified and no release time): the latest status is kept with its
     day unconfirmed (`undated`), never labelled by the run's weekday (Alan, Oct 22: that was the original bug).
  E. A team whose game isn't on Sunday (Thursday, Monday, Saturday) practices on other days: its latest status is kept,
     undated, and old day labels are cleared; Sunday teams in the same file are still dated.
  F. A per-row `date_modified` (nflverse's 2024 files had one; 2025-26 don't) dates each row on its own.
  G. No Last-Modified header: the release asset's update time from GitHub's API dates the file instead.
  H. No schedule for the week: nothing is dated.

    python3 tests/practice_day_check.py
"""
import os, sys, tempfile
from datetime import datetime, timezone
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "pipeline"))
import build_stats as bs

failures = []
def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond: failures.append(msg)

utc = lambda s: datetime.fromisoformat(s).replace(tzinfo=timezone.utc)

# A. Which practice day a rebuild time holds (Week 7 2026: Wed Oct 21 … Sat Oct 24; EDT = UTC-4)
for when, want in [("2026-10-22T12:55", "wed"),   # Thu 8:55 AM ET: the real Week 7 rebuild, Wednesday's report
                   ("2026-10-22T19:30", "wed"),   # Thu 3:30 PM ET: Thursday's report not posted yet
                   ("2026-10-22T21:30", "thu"),   # Thu 5:30 PM ET
                   ("2026-10-23T12:00", "thu"),   # Fri morning: Thursday's
                   ("2026-10-23T22:00", "fri"),   # Fri evening: the final report
                   ("2026-10-24T13:00", "fri"),   # Sat morning
                   ("2026-10-25T13:00", "fri"),   # Sun morning
                   ("2026-10-21T13:00", None)]:   # Wed morning: no Sunday team's Wednesday report yet
    ok(bs.report_day(utc(when)) == want, f"A. rebuilt {when}Z holds " + (f"the {want} report" if want else "no new report"))
ok(bs.report_day(None) is None, "A. no rebuild time, no report day")
ok(bs.report_day(utc("2026-10-20T22:00")) is None, "A. a rebuild Tuesday evening holds no Sunday team's report")

# B. A week of runs. Synthetic file: one team, two players.
COLS = ["season", "season_type", "game_type", "team", "week", "gsis_id", "position", "full_name", "first_name",
        "last_name", "report_primary_injury", "report_secondary_injury", "report_status", "practice_primary_injury",
        "practice_secondary_injury", "practice_status"]
GAMES = pd.DataFrame([dict(season=2026, game_type="REG", week=w, away_team=a, home_team=h, gameday=g) for w, a, h, g in [
    (7, "NYJ", "CAR", "2026-10-25"), (7, "LA", "SEA", "2026-10-22"), (7, "DAL", "WAS", "2026-10-26"),
    (8, "NYJ", "MIA", "2026-11-01")]])   # NYJ Sunday · LAR Thursday · DAL Monday
TXT = {"DNP": "Did Not Participate In Practice", "LP": "Limited Participation in Practice", "FP": "Full Participation in Practice"}
tmp = tempfile.mkdtemp()
def report(week, rows, team="NYJ", extra=None, modified=None):
    p = os.path.join(tmp, f"inj_{len(os.listdir(tmp))}_{{}}.csv")
    recs = [dict(season=2026, season_type="REG", game_type="REG", team=team, week=week, gsis_id=g, position=pos,
                 full_name=n, first_name=n.split()[0], last_name=n.split()[-1], report_primary_injury=inj,
                 report_secondary_injury=None, report_status=st, practice_primary_injury=inj,
                 practice_secondary_injury=None, practice_status=TXT[pr]) for g, pos, n, inj, pr, st in rows]
    df = pd.DataFrame(recs, columns=COLS)
    if extra is not None:   # more teams' rows
        df = pd.concat([df, pd.read_csv(extra.format(2026))])
    if modified is not None:   # per-row date_modified, as nflverse's 2024 files had
        df["date_modified"] = modified
    df.to_csv(p.format(2026), index=False)
    return p
ids = {"00-1": "8155", "00-2": "9001"}
row = lambda out, name, tm="NYJ": next(r for r in out["teams"][tm] if r[0] == name)
day = lambda r: dict(zip(["wed", "thu", "fri"], r[6:9]))

wed = report(7, [("00-1", "RB", "Breece Hall", "Quadricep", "DNP", None), ("00-2", "WR", "Test Receiver", "Hamstring", "LP", None)])
thu = report(7, [("00-1", "RB", "Breece Hall", "Quadricep", "LP", None), ("00-2", "WR", "Test Receiver", "Hamstring", "FP", None)])
fri = report(7, [("00-1", "RB", "Breece Hall", "Quadricep", "FP", "Questionable"), ("00-2", "WR", "Test Receiver", "Hamstring", "FP", None)])

o1 = bs.injuries(2026, ids, src=wed, games=GAMES, modified=utc("2026-10-22T12:55"))   # Thursday run, Wednesday's file
ok(day(row(o1, "Breece Hall")) == {"wed": "DNP", "thu": None, "fri": None}, "B. Thursday's run files Wednesday's DNP under Wed, not Thu")
ok(o1.get("day") == "wed" and o1.get("source_updated") == "2026-10-22T12:55Z" and o1["undated"] == [], "B. the file records the source's rebuild time and report day")
o2 = bs.injuries(2026, ids, src=wed, prev=o1, games=GAMES, modified=utc("2026-10-22T12:55"))   # Thu evening run, file unchanged
ok(day(row(o2, "Breece Hall")) == {"wed": "DNP", "thu": None, "fri": None}, "B. an unchanged file re-read later adds nothing (no copy into Thu)")
o3 = bs.injuries(2026, ids, src=thu, prev=o2, games=GAMES, modified=utc("2026-10-23T12:10"))   # Friday morning: Thursday's
ok(day(row(o3, "Breece Hall")) == {"wed": "DNP", "thu": "LP", "fri": None}, "B. Thursday's LP lands under Thu, Wednesday's DNP kept")
ok(row(o3, "Breece Hall")[4] == "LP", "B. the latest practice status follows the newest report")
o4 = bs.injuries(2026, ids, src=thu, prev=o3, games=GAMES, modified=utc("2026-10-23T12:10"))   # Friday 6 PM run, file unchanged
ok(day(row(o4, "Breece Hall"))["fri"] is None, "B. Friday's evening run on Thursday's file leaves Fri empty")
o5 = bs.injuries(2026, ids, src=fri, prev=o4, games=GAMES, modified=utc("2026-10-24T13:00"))   # Saturday: the final report
ok(day(row(o5, "Breece Hall")) == {"wed": "DNP", "thu": "LP", "fri": "FP"}, "B. Friday's final report fills Fri and keeps Thursday's LP")
ok(row(o5, "Breece Hall")[3] == "Questionable", "B. the game designation comes with the final report")
ok(day(row(o5, "Test Receiver")) == {"wed": "LP", "thu": "FP", "fri": "FP"}, "B. every player's days are kept apart")
nxt = report(8, [("00-1", "RB", "Breece Hall", "Quadricep", "LP", None)])
o6 = bs.injuries(2026, ids, src=nxt, prev=o5, games=GAMES, modified=utc("2026-10-29T12:55"))
ok(o6["week"] == 8 and day(row(o6, "Breece Hall")) == {"wed": "LP", "thu": None, "fri": None}, "B. a new week starts from its own Wednesday report")

# C. Repair of a file labelled by the run's weekday (Week 7 as committed Oct 22 14:04 UTC: Wednesday's report under Thu)
legacy = {"week": 7, "cols": bs.INJURY_COLS, "teams": {"NYJ": [["Breece Hall", "RB", "8155", None, "DNP", "Quadricep", None, "DNP", None]]}}
o7 = bs.injuries(2026, ids, src=wed, prev=legacy, games=GAMES, modified=utc("2026-10-22T12:55"))
ok(day(row(o7, "Breece Hall")) == {"wed": "DNP", "thu": None, "fri": None}, "C. Wednesday's report filed under Thu is moved to Wed")

import roles
RCI = {c: i for i, c in enumerate(bs.INJURY_COLS)}

# D. No source time: the latest status is kept, its day isn't confirmed, and nothing is labelled by the run's day
o8 = bs.injuries(2026, ids, src=wed, games=GAMES)
ok(day(row(o8, "Breece Hall")) == {"wed": None, "thu": None, "fri": None} and row(o8, "Breece Hall")[4] == "DNP",
   "D. no source time: DNP kept as his latest status, under no day")
ok(o8["undated"] == ["NYJ"] and o8["day"] is None and "source_updated" not in o8, "D. the team is marked undated, no report day, no source time")
o9 = bs.injuries(2026, ids, src=thu, prev=o3, games=GAMES)   # Thursday's file arrives with no time: Wed's DNP stays, LP undated
ok(day(row(o9, "Breece Hall")) == {"wed": "DNP", "thu": "LP", "fri": None} and row(o9, "Breece Hall")[4] == "LP",
   "D. days already dated this week stay; the newest status is the latest")
o10 = bs.injuries(2026, ids, src=fri, prev=o3, games=GAMES)
ok(day(row(o10, "Breece Hall")) == {"wed": "DNP", "thu": "LP", "fri": None} and row(o10, "Breece Hall")[4] == "FP" and o10["undated"] == ["NYJ"],
   "D. an undated FP never fills Fri (or overwrites Thu)")
ok(roles.latest_practice(row(o10, "Breece Hall"), RCI) == "FP", "D. roles read the newest status, not the newest dated day")
ok(bs.source_modified(wed) is None, "D. a local file has no source-time lookup")

# E. Thursday- and Monday-game teams in the same file as a Sunday team
mixed = report(7, [("00-3", "WR", "Thursday Receiver", "Ankle", "LP", "Questionable")], team="LA",
               extra=report(7, [("00-4", "RB", "Monday Back", "Knee", "DNP", None)], team="DAL", extra=wed))
legacy_thu = {"week": 7, "cols": bs.INJURY_COLS, "teams": {"LAR": [["Thursday Receiver", "WR", None, None, "DNP", "Ankle", "DNP", "DNP", None]]}}
o11 = bs.injuries(2026, ids, src=mixed, prev=legacy_thu, games=GAMES, modified=utc("2026-10-22T12:55"))
tr = row(o11, "Thursday Receiver", "LAR")
ok(day(tr) == {"wed": None, "thu": None, "fri": None} and tr[4] == "LP" and tr[3] == "Questionable",
   "E. a Thursday-game team: latest LP and its designation kept, no Wed / Thu / Fri day (old labels cleared)")
ok(day(row(o11, "Monday Back", "DAL")) == {"wed": None, "thu": None, "fri": None} and row(o11, "Monday Back", "DAL")[4] == "DNP",
   "E. a Monday-game team: latest DNP kept, no day")
ok(o11["undated"] == ["DAL", "LAR"], "E. both teams marked undated")
ok(day(row(o11, "Breece Hall")) == {"wed": "DNP", "thu": None, "fri": None} and o11["day"] == "wed",
   "E. the Sunday team in the same file is still dated (Wed)")

# F. Per-row date_modified dates each row; the file time doesn't override it
rowdated = report(7, [("00-1", "RB", "Breece Hall", "Quadricep", "LP", None)], modified="2026-10-22T20:40:00Z")   # Thu 4:40 PM ET
o12 = bs.injuries(2026, ids, src=rowdated, prev=o1, games=GAMES, modified=utc("2026-10-24T13:00"))   # file rebuilt Saturday
ok(day(row(o12, "Breece Hall")) == {"wed": "DNP", "thu": "LP", "fri": None}, "F. a row changed Thu evening is Thursday's report, not Friday's")

# G. No Last-Modified: the release asset's updated_at
import io, json, urllib.request
calls = []
def fake_urlopen(req, timeout=None):
    calls.append(req.get_method())
    if req.get_method() == "HEAD":
        raise OSError("no header")
    body = json.dumps({"assets": [{"name": "injuries_2026.csv", "updated_at": "2026-10-22T12:55:53Z"}]}).encode()
    class R(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): return False
    return R(body)
real = urllib.request.urlopen
urllib.request.urlopen = fake_urlopen
try:
    m = bs.source_modified(bs.INJ_URL.format(2026))
finally:
    urllib.request.urlopen = real
ok(m == utc("2026-10-22T12:55:53") and calls == ["HEAD", "GET"], "G. no Last-Modified: the release's update time dates the file")

# H. No schedule: nothing dated
o13 = bs.injuries(2026, ids, src=wed, modified=utc("2026-10-22T12:55"))
ok(day(row(o13, "Breece Hall")) == {"wed": None, "thu": None, "fri": None} and o13["undated"] == ["NYJ"], "H. no schedule: undated, not guessed")

print(f"\n{'FAILED' if failures else 'OK'}: {len(failures)} failure(s)")
sys.exit(1 if failures else 0)
