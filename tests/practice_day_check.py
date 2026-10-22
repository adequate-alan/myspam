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
  D. No Last-Modified (a local file, an offline HEAD): the run's weekday labels the report, as before.

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
                   ("2026-10-21T13:00", "wed")]:  # Wed morning: Thursday-game teams' Tuesday report
    ok(bs.report_day(utc(when)) == want, f"A. rebuilt {when}Z holds the {want} report")
ok(bs.report_day(None) is None, "A. no rebuild time, no report day")

# B. A week of runs. Synthetic file: one team, two players.
COLS = ["season", "season_type", "game_type", "team", "week", "gsis_id", "position", "full_name", "first_name",
        "last_name", "report_primary_injury", "report_secondary_injury", "report_status", "practice_primary_injury",
        "practice_secondary_injury", "practice_status"]
TXT = {"DNP": "Did Not Participate In Practice", "LP": "Limited Participation in Practice", "FP": "Full Participation in Practice"}
tmp = tempfile.mkdtemp()
def report(week, rows):
    p = os.path.join(tmp, f"inj_{len(os.listdir(tmp))}_{{}}.csv")
    recs = [dict(season=2026, season_type="REG", game_type="REG", team="NYJ", week=week, gsis_id=g, position=pos,
                 full_name=n, first_name=n.split()[0], last_name=n.split()[-1], report_primary_injury=inj,
                 report_secondary_injury=None, report_status=st, practice_primary_injury=inj,
                 practice_secondary_injury=None, practice_status=TXT[pr]) for g, pos, n, inj, pr, st in rows]
    pd.DataFrame(recs, columns=COLS).to_csv(p.format(2026), index=False)
    return p
ids = {"00-1": "8155", "00-2": "9001"}
row = lambda out, name: next(r for r in out["teams"]["NYJ"] if r[0] == name)
day = lambda r: dict(zip(["wed", "thu", "fri"], r[6:9]))

wed = report(7, [("00-1", "RB", "Breece Hall", "Quadricep", "DNP", None), ("00-2", "WR", "Test Receiver", "Hamstring", "LP", None)])
thu = report(7, [("00-1", "RB", "Breece Hall", "Quadricep", "LP", None), ("00-2", "WR", "Test Receiver", "Hamstring", "FP", None)])
fri = report(7, [("00-1", "RB", "Breece Hall", "Quadricep", "FP", "Questionable"), ("00-2", "WR", "Test Receiver", "Hamstring", "FP", None)])

o1 = bs.injuries(2026, ids, src=wed, day="thu", modified=utc("2026-10-22T12:55"))   # Thursday run, Wednesday's file
ok(day(row(o1, "Breece Hall")) == {"wed": "DNP", "thu": None, "fri": None}, "B. Thursday's run files Wednesday's DNP under Wed, not Thu")
ok(o1.get("day") == "wed" and o1.get("source_updated") == "2026-10-22T12:55Z", "B. the file records the source's rebuild time and report day")
o2 = bs.injuries(2026, ids, src=wed, prev=o1, day="thu", modified=utc("2026-10-22T12:55"))   # Thu evening run, file unchanged
ok(day(row(o2, "Breece Hall")) == {"wed": "DNP", "thu": None, "fri": None}, "B. an unchanged file re-read later adds nothing (no copy into Thu)")
o3 = bs.injuries(2026, ids, src=thu, prev=o2, day="fri", modified=utc("2026-10-23T12:10"))   # Friday morning: Thursday's
ok(day(row(o3, "Breece Hall")) == {"wed": "DNP", "thu": "LP", "fri": None}, "B. Thursday's LP lands under Thu, Wednesday's DNP kept")
ok(row(o3, "Breece Hall")[4] == "LP", "B. the latest practice status follows the newest report")
o4 = bs.injuries(2026, ids, src=thu, prev=o3, day="fri", modified=utc("2026-10-23T12:10"))   # Friday 6 PM run, file unchanged
ok(day(row(o4, "Breece Hall"))["fri"] is None, "B. Friday's evening run on Thursday's file leaves Fri empty")
o5 = bs.injuries(2026, ids, src=fri, prev=o4, day="fri", modified=utc("2026-10-24T13:00"))   # Saturday: the final report
ok(day(row(o5, "Breece Hall")) == {"wed": "DNP", "thu": "LP", "fri": "FP"}, "B. Friday's final report fills Fri and keeps Thursday's LP")
ok(row(o5, "Breece Hall")[3] == "Questionable", "B. the game designation comes with the final report")
ok(day(row(o5, "Test Receiver")) == {"wed": "LP", "thu": "FP", "fri": "FP"}, "B. every player's days are kept apart")
nxt = report(8, [("00-1", "RB", "Breece Hall", "Quadricep", "LP", None)])
o6 = bs.injuries(2026, ids, src=nxt, prev=o5, day="thu", modified=utc("2026-10-29T12:55"))
ok(o6["week"] == 8 and day(row(o6, "Breece Hall")) == {"wed": "LP", "thu": None, "fri": None}, "B. a new week starts from its own Wednesday report")

# C. Repair of a file labelled by the run's weekday (Week 7 as committed Oct 22 14:04 UTC: Wednesday's report under Thu)
legacy = {"week": 7, "cols": bs.INJURY_COLS, "teams": {"NYJ": [["Breece Hall", "RB", "8155", None, "DNP", "Quadricep", None, "DNP", None]]}}
o7 = bs.injuries(2026, ids, src=wed, prev=legacy, day="thu", modified=utc("2026-10-22T12:55"))
ok(day(row(o7, "Breece Hall")) == {"wed": "DNP", "thu": None, "fri": None}, "C. Wednesday's report filed under Thu is moved to Wed")

# D. No rebuild time: the run's weekday, as before
o8 = bs.injuries(2026, ids, src=wed, day="thu")
ok(day(row(o8, "Breece Hall"))["thu"] == "DNP" and "source_updated" not in o8, "D. no Last-Modified: labelled by the run's day")
ok(bs.source_modified(wed) is None, "D. a local file has no Last-Modified lookup")

print(f"\n{'FAILED' if failures else 'OK'}: {len(failures)} failure(s)")
sys.exit(1 if failures else 0)
