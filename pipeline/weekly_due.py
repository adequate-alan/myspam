"""Is this week's projections refresh missing? (Alan, Oct 13: GitHub's scheduler skipped the Tuesday 14:00 UTC run.)

The weekly refresh (projections, stored forecast, ranking-history snapshot) belongs to the week that starts Tuesday
14:00 UTC, after Monday Night Football. This week's refresh counts as done when data/projections.json was written after
Tuesday 04:00 UTC (MNF has ended by then): by the scheduled run, a catch-up or a manual run. A failed weekly run commits
nothing, so a missing or incomplete refresh leaves the file older than that.

  python3 pipeline/weekly_due.py [--file data/projections.json] [--now 2026-10-13T16:00Z] [--github-output]

Prints one line and, with --github-output, writes state=<...> to $GITHUB_OUTPUT:
  done     this week's refresh is there: nothing to do
  due      missing, inside the catch-up window (Tuesday 14:00 → Thursday 00:00 UTC): run the weekly refresh now
  overdue  missing and the catch-up window has passed: report it (the freshness check fails the run)
Idempotent by construction: the answer only depends on the file's own `updated`, so once a refresh is committed every
later run says `done`, and the workflow asks again on the latest main just before committing.
"""
import argparse, datetime as dt, json, os, sys

UTC = dt.timezone.utc
DONE_AFTER = dt.timedelta(hours=10)    # Tuesday 04:00 UTC counts as this week's (MNF is over)
WINDOW = dt.timedelta(hours=34)        # Tuesday 14:00 → Thursday 00:00 UTC

def parse(s):
    for f in ("%Y-%m-%dT%H:%MZ", "%Y-%m-%dT%H:%M:%SZ"):
        try: return dt.datetime.strptime(s, f).replace(tzinfo=UTC)
        except (TypeError, ValueError): pass
    return None

def week_start(now):
    """The latest Tuesday 14:00 UTC at or before `now`."""
    t = (now - dt.timedelta(days=(now.weekday() - 1) % 7)).replace(hour=14, minute=0, second=0, microsecond=0)
    return t if t <= now else t - dt.timedelta(days=7)

def state(updated, now):
    start = week_start(now)
    if updated is not None and updated >= start - DONE_AFTER: return "done", start
    if now - start >= WINDOW: return "overdue", start
    return "due", start

def read_updated(path):
    try: return parse(json.load(open(path, encoding="utf-8")).get("updated"))
    except (OSError, ValueError, AttributeError): return None

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default="data/projections.json"); ap.add_argument("--now", default="")
    ap.add_argument("--github-output", action="store_true")
    a = ap.parse_args()
    now = parse(a.now or os.environ.get("WEEKLY_DUE_NOW", "")) or dt.datetime.now(UTC)   # the env var: tests only
    upd = read_updated(a.file)
    st, start = state(upd, now)
    msg = (f"weekly refresh {st}: week from {start:%a %b %d %H:%M} UTC, projections updated "
           f"{upd:%a %b %d %H:%M} UTC" if upd else f"weekly refresh {st}: week from {start:%a %b %d %H:%M} UTC, "
           "projections file missing or unreadable")
    print(msg)
    if a.github_output and os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as f: f.write(f"state={st}\nmessage={msg}\n")
    sys.exit(0)
