"""Is every scheduled data source current? (Alan, Nov 1: site audit P1-1, "source-specific schedules and alerts".)

Until Nov 1 only the Tuesday projections refresh was checked (weekly_due.py). This checks each source the scheduled
jobs keep fresh, against when that source can actually have new data, so a dropped or failing run is reported without
false alarms while a provider simply hasn't published yet:

  stats        data/stats/<season>.json: every game that kicked off in the last 10 days has player lines and a final
               score once two scheduled stats runs have had the chance to pick it up after nflverse usually posts
               (12 h after kickoff)
  practice     the injuries block in the same file: Sunday teams' Wednesday / Thursday / Friday reports, which reach
               nflverse the next morning ET (PR #94), once two stats runs have had the chance after that
  projections  data/projections.json: this week's Tuesday refresh (weekly_due.py, unchanged)
  roles        data/roles.json, rewritten by every stats run
  depth        data/depth_charts.json, rewritten by every stats run
  market       data/market/redraft.json: the last successful FantasyCalc sync (market-only and stats runs)

The run times come from the workflow's own cron lines, so a schedule change needs no edit here. GitHub starts
scheduled runs late (Nov 1: the 00:20 market run started 06:25), so each run gets GRACE to have finished, and one
dropped run is tolerated: a source is overdue only when the two latest runs that should have refreshed it both left
no trace.

States: current · pending (the provider has published; the next run picks it up) · waiting (the provider hasn't
published, or its sync is failing: a warning, overdue after CEILING) · overdue (fails the freshness job) · off
(nothing expected now, e.g. no games in the last 10 days).

  python3 pipeline/data_freshness.py [--root .] [--now 2026-11-01T14:00Z] [--online] [--github]
           [--upstream stats=2026-11-02T09:00Z,injuries=none]   (tests: upstream times instead of asking nflverse)

--online asks nflverse when its files were last rebuilt (one HEAD request each, only for a source that's late), to
tell a missed run (overdue) from a provider that hasn't posted (waiting). --github prints ::error:: / ::warning::
lines, appends a table to $GITHUB_STEP_SUMMARY and exits 1 when a source is overdue. Read-only: never writes data.
"""
import argparse, datetime as dt, json, os, re, sys
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import weekly_due

UTC, ET = dt.timezone.utc, ZoneInfo("America/New_York")
GRACE = dt.timedelta(hours=8)             # a scheduled run may start ~7 h late (Oct 30: the 08:30 run committed 15:10), plus its run time
CEILING = dt.timedelta(hours=48)          # a provider this late past due (or unreachable to ask) is reported overdue
STATS_AVAIL = dt.timedelta(hours=12)      # nflverse posts a game's player stats overnight, sometimes next morning
GAME_LEN = dt.timedelta(hours=4)
LOOKBACK = dt.timedelta(days=10)          # older games aren't re-checked (a cancelled game would alarm forever)
DAYS = ["wed", "thu", "fri"]
REPORT_POSTED_H = 16                      # = build_stats.REPORT_POSTED_H (clubs post the day's report by ~4 PM ET)
DAY_OF_REPORT = {2: "wed", 3: "thu", 4: "fri", 5: "fri", 6: "fri", 0: "fri", 1: None}   # = build_stats.DAY_OF_REPORT
# when a Sunday team's day-N report has reached nflverse (it rebuilds the file the next morning ET; Week 7 2026's
# Wednesday report arrived Thu 12:55 UTC): days before the Sunday game, at 16:00 UTC
REPORT_AVAIL = {"wed": 3, "thu": 2, "fri": 1}
NIGHTLY, MARKET = "15 7 * * *", "20 */8 * * *"
UPSTREAM = {"stats": ("stats_player", "stats_player_week_{}.csv"), "injuries": ("injuries", "injuries_{}.csv")}


def ts(s):
    if not s: return None
    try: return dt.datetime.fromisoformat(str(s).replace("Z", "+00:00")).astimezone(UTC)
    except ValueError: return None


def fmt(t):
    return t.astimezone(UTC).strftime("%a %b %d %H:%M UTC") if t else "never"


def report_day(t):
    if t is None: return None
    return DAY_OF_REPORT[(t.astimezone(ET) - dt.timedelta(hours=REPORT_POSTED_H)).weekday()]


# ---------- the workflow's schedule ----------
def crons(workflow):
    """[(cron, tz)] from the workflow's `- cron:` lines, with an optional `timezone:` line under each."""
    out, lines = [], open(workflow, encoding="utf-8").read().splitlines()
    for i, l in enumerate(lines):
        m = re.match(r'\s*-\s*cron:\s*"([^"]+)"', l)
        if not m: continue
        tz = re.match(r'\s*timezone:\s*"([^"]+)"', lines[i + 1]) if i + 1 < len(lines) else None
        out.append((m.group(1), tz.group(1) if tz else "UTC"))
    return out


def _field(f, lo, hi):
    vals = set()
    for part in f.split(","):
        if part == "*": vals |= set(range(lo, hi + 1))
        elif part.startswith("*/"): vals |= set(range(lo, hi + 1, int(part[2:])))
        else: vals.add(int(part))
    return vals


def cron_times(expr, tz, start, end):
    """Every time `expr` fires in [start, end] (UTC)."""
    mi, ho, dom, mo, dow = expr.split()
    zone = UTC if tz == "UTC" else ZoneInfo(tz)
    mins, hours, doms, mons = _field(mi, 0, 59), _field(ho, 0, 23), _field(dom, 1, 31), _field(mo, 1, 12)
    dows = {d % 7 for d in _field(dow, 0, 7)}
    day, last, out = (start - dt.timedelta(days=1)).astimezone(zone).date(), (end + dt.timedelta(days=1)).astimezone(zone).date(), []
    while day <= last:
        if day.month in mons and day.day in doms and (day.weekday() + 1) % 7 in dows:
            for h in sorted(hours):
                for m in sorted(mins):
                    t = dt.datetime(day.year, day.month, day.day, h, m, tzinfo=zone).astimezone(UTC)
                    if start <= t <= end: out.append(t)
        day += dt.timedelta(days=1)
    return out


class Schedule:
    """Scheduled refresh runs by kind: `stats` (every run that runs build_stats, roles and depth charts: stats-only and
    the Tuesday weekly) and `market` (those plus the 8-hourly market runs). Catch-ups (minute 37) only act when the
    weekly refresh is missing and the nightly suite refreshes nothing, so neither counts."""
    def __init__(self, workflow):
        cs = [(c, tz) for c, tz in crons(workflow) if c != NIGHTLY and not c.startswith("37 ")]
        self.kinds = {"stats": [x for x in cs if x[0] != MARKET], "market": cs}

    def runs(self, kind, start, end):
        return sorted({t for c, tz in self.kinds[kind] for t in cron_times(c, tz, start, end)})

    def due_after(self, avail, kind):
        """When data available at `avail` must be in: the second scheduled run after it, plus GRACE."""
        r = self.runs(kind, avail, avail + dt.timedelta(days=14))
        return r[1] + GRACE if len(r) > 1 else None

    def required_since(self, kind, now):
        """A source every run rewrites must be newer than the older of the last two runs that should have finished."""
        r = self.runs(kind, now - dt.timedelta(days=14), now - GRACE)
        return r[-2] if len(r) > 1 else None


# ---------- upstream (nflverse) ----------
def upstream_modified(key, season):
    """When nflverse last rebuilt the file behind `key`: its Last-Modified, else the release asset's updated_at."""
    from email.utils import parsedate_to_datetime
    from urllib.request import Request, urlopen
    tag, name = UPSTREAM[key]; name = name.format(season)
    try:
        with urlopen(Request(f"https://github.com/nflverse/nflverse-data/releases/download/{tag}/{name}", method="HEAD"), timeout=30) as r:
            h = r.headers.get("Last-Modified")
        if h: return parsedate_to_datetime(h).astimezone(UTC)
    except Exception as e:
        print(f"{key}: no Last-Modified from nflverse ({e})", file=sys.stderr)
    try:
        with urlopen(Request(f"https://api.github.com/repos/nflverse/nflverse-data/releases/tags/{tag}",
                             headers={"Accept": "application/vnd.github+json"}), timeout=30) as r:
            a = next((a for a in json.load(r).get("assets", []) if a.get("name") == name), None)
        if a and a.get("updated_at"): return ts(a["updated_at"])
    except Exception as e:
        print(f"{key}: no release time from GitHub either ({e})", file=sys.stderr)
    return None


def result(source, state, updated, detail):
    return {"source": source, "state": state, "updated": updated.strftime("%Y-%m-%dT%H:%MZ") if updated else None, "detail": detail}


def late(source, updated, due, now, up, sched, waiting_msg, unknown_ceiling=True):
    """Data the provider should have had by `due` is missing. `up` = (provider has it: True / False / None unknown,
    when it was published). Once the provider has it, every scheduled refresh that should have finished since
    (start + GRACE) is a missed chance: none yet = pending, one = behind (a warning: one dropped run is tolerated),
    two or more = overdue (the run fails)."""
    has, when = up
    if has:
        missed = [r for r in sched.runs("stats", when, now) if r + GRACE <= now]
        if not missed:
            return result(source, "pending", updated, f"{waiting_msg}; nflverse published it {fmt(when)}, the next refresh picks it up")
        if len(missed) == 1:
            return result(source, "behind", updated, f"{waiting_msg}; nflverse published it {fmt(when)} and the refresh "
                                                     f"scheduled {fmt(missed[0])} didn't pick it up (overdue after one more)")
        return result(source, "overdue", updated, f"{waiting_msg}, but nflverse published it {fmt(when)} and the "
                                                  f"{len(missed)} refreshes scheduled since ({fmt(missed[0])} on) haven't picked it up")
    if has is None and not unknown_ceiling:
        return result(source, "waiting", updated, waiting_msg + " (couldn't ask nflverse)")
    if now >= due + CEILING:
        return result(source, "overdue", updated, waiting_msg + f", now {int((now - due).total_seconds() // 3600)} h past due")
    return result(source, "waiting", updated, waiting_msg + ("" if has is False else " (couldn't ask nflverse whether it has)"))


# ---------- checks ----------
def kickoff(date, time):
    h, m = (int(x) for x in (time or "13:00").split(":")[:2])
    y, mo, d = (int(x) for x in date.split("-"))
    return dt.datetime(y, mo, d, h, m, tzinfo=ET).astimezone(UTC)


def check_stats(stats, now, sched, upstream):
    upd = ts(stats.get("updated"))
    lines = {(g[0], g[1]) for p in stats.get("players", {}).values() for g in p.get("g", [])}
    missing, due_by = [], None
    for tm, rows in stats.get("schedule", {}).items():
        for r in rows:
            w, date, pf, time = r[0], r[3], r[4], r[6]
            if not date: continue
            k = kickoff(date, time)
            due = sched.due_after(k + STATS_AVAIL, "stats")
            if k < now - LOOKBACK or not due or now < due: continue
            if pf is None or (w, tm) not in lines:
                missing.append((k, w, tm)); due_by = due if due_by is None else min(due_by, due)
    if not missing:
        return result("stats", "current", upd, f"through Week {stats.get('through_week')}; every game due is in")
    games = sorted({(w, tm) for _, w, tm in missing})
    what = f"Week {games[0][0]} " + ", ".join(tm for w, tm in games if w == games[0][0])[:80] + (" and more" if len(games) > 4 else "")
    up_t = upstream("stats")
    ends = max(k for k, _, _ in missing) + GAME_LEN
    up = (None, None) if up_t is None else ((True, up_t) if up_t > ends and (upd is None or up_t > upd) else (False, up_t))
    return late("stats", upd, due_by, now, up, sched, f"no stats for {what}")


def check_practice(stats, now, sched, upstream):
    inj, sch = stats.get("injuries") or {}, stats.get("schedule", {})
    upd = ts(inj.get("source_updated"))
    sundays = {}
    for rows in sch.values():
        for r in rows:
            if r[3] and dt.date.fromisoformat(r[3]).weekday() == 6:
                sundays.setdefault(r[0], dt.date.fromisoformat(r[3]))
    nxt = sorted((s, w) for w, s in sundays.items() if now < dt.datetime(s.year, s.month, s.day, tzinfo=ET) + dt.timedelta(days=1))
    if not nxt:
        return result("practice", "off", upd, "no Sunday games ahead")
    sun, week = nxt[0]
    want, due = None, None
    for d in DAYS:
        a = dt.datetime(sun.year, sun.month, sun.day, 16, tzinfo=UTC) - dt.timedelta(days=REPORT_AVAIL[d])
        dd = sched.due_after(a, "stats")
        if dd and now >= dd: want, due = d, dd
    have_week, have_day = inj.get("week"), inj.get("day")
    have = f"Week {have_week} {have_day or 'undated'} report"
    has = lambda d: (have_week or 0) > week or (have_week == week and have_day in DAYS and DAYS.index(have_day) >= DAYS.index(d))
    up_t = upstream("injuries")
    week_start = dt.datetime(sun.year, sun.month, sun.day, tzinfo=ET).astimezone(UTC) - dt.timedelta(days=5)
    up_day = report_day(up_t) if up_t and up_t > week_start and (upd is None or up_t > upd) else None
    if up_day in DAYS and not has(up_day):
        # nflverse has a report we don't: from here on every refresh that misses it counts (late), due or not
        return late("practice", upd, due, now, (True, up_t), sched, f"Week {week} {up_day.title()} report not in yet (have the {have})")
    if want is None:
        return result("practice", "current", upd, f"{have}; Week {week}'s Wednesday report isn't due yet")
    if has(want):
        return result("practice", "current", upd, f"{have} (Week {week} {want} report due)")
    # due but nflverse hasn't posted it (or couldn't be asked): not ours to fix, and the site honestly shows it as
    # Pending, so a warning, never a failure
    r = late("practice", upd, due, now, (None if up_t is None else False, up_t), sched,
             f"Week {week} {want.title()} report not in yet (have the {have})", unknown_ceiling=True)
    if r["state"] == "overdue": r["state"] = "waiting"
    return r


def check_rewritten(source, path, updated, now, sched, kind, note=""):
    upd = ts(updated)
    need = sched.required_since(kind, now)
    if need is None or (upd and upd >= need):
        return result(source, "current", upd, f"refreshed {fmt(upd)}" + note)
    return result(source, "overdue", upd, f"not refreshed since {fmt(upd)}; the runs scheduled from {fmt(need)} on "
                                          f"left no update (check the refresh runs' logs for {os.path.basename(path)})" + note)


def check_market(market, now, sched):
    upd, sync = ts(market.get("updated")), market.get("sync") or {}
    need = sched.required_since("market", now)
    if need is None or (upd and upd >= need):
        warn = "" if sync.get("ok", True) else f"; the last attempt ({fmt(ts(sync.get('attempted')))}) failed: {sync.get('error') or 'no detail'}"
        return result("market", "current", upd, f"FantasyCalc synced {fmt(upd)}{warn}")
    att = ts(sync.get("attempted"))
    if att and att >= need and not sync.get("ok", True):   # our runs ran; FantasyCalc is failing
        r = result("market", "waiting", upd, f"FantasyCalc sync failing since {fmt(upd)} (last attempt {fmt(att)}: {sync.get('error') or 'no detail'})")
        if upd is None or now - upd >= CEILING: r["state"] = "overdue"
        return r
    return result("market", "overdue", upd, f"no FantasyCalc sync since {fmt(upd)}; the runs scheduled from {fmt(need)} on left no attempt")


def check_projections(path, now):
    upd = weekly_due.read_updated(path)
    st, start = weekly_due.state(upd, now)
    return result("projections", {"done": "current", "due": "pending", "overdue": "overdue"}[st], upd,
                  f"this week's refresh (from {fmt(start)}) " + {"done": "is in", "due": "is missing; a catch-up run will do it before Thursday 00:00 UTC",
                                                               "overdue": "was missed: run the workflow manually with stats_only off"}[st])


def load(path):
    try: return json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError): return {}


def check_all(root, now, upstream, workflow=None):
    sched = Schedule(workflow or os.path.join(root, ".github/workflows/site.yml"))
    sdir = os.path.join(root, "data/stats")
    seasons = sorted(int(f[:4]) for f in os.listdir(sdir) if re.fullmatch(r"\d{4}\.json", f)) if os.path.isdir(sdir) else []
    season = seasons[-1] if seasons else now.year
    stats = load(os.path.join(sdir, f"{season}.json"))
    up = lambda key: upstream(key, season)
    roles, depth = load(os.path.join(root, "data/roles.json")), load(os.path.join(root, "data/depth_charts.json"))
    return [
        check_stats(stats, now, sched, up) if stats else result("stats", "overdue", None, f"data/stats/{season}.json missing or unreadable"),
        check_practice(stats, now, sched, up) if stats else result("practice", "overdue", None, "no stats file"),
        check_projections(os.path.join(root, "data/projections.json"), now),
        check_rewritten("roles", "data/roles.json", roles.get("updated"), now, sched, "stats"),
        check_rewritten("depth charts", "data/depth_charts.json", depth.get("updated"), now, sched, "stats"),
        check_market(load(os.path.join(root, "data/market/redraft.json")), now, sched),
    ]


LABEL = {"current": "Current", "pending": "Picked up next run", "behind": "Missed one refresh", "waiting": "Waiting on provider", "overdue": "Overdue", "off": "Not checked"}

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="."); ap.add_argument("--now", default=""); ap.add_argument("--workflow", default="")
    ap.add_argument("--online", action="store_true"); ap.add_argument("--github", action="store_true")
    ap.add_argument("--upstream", default="", help="tests: key=ISO|none,… instead of asking nflverse")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    now = ts(a.now) or dt.datetime.now(UTC)
    fixed = {k: (None if v == "none" else ts(v)) for k, v in (p.split("=", 1) for p in a.upstream.split(",") if "=" in p)}
    cache = {}
    def upstream(key, season):
        if key in fixed: return fixed[key]
        if not a.online: return None
        if key not in cache: cache[key] = upstream_modified(key, season)
        return cache[key]
    res = check_all(a.root, now, upstream, a.workflow or None)
    if a.json:
        print(json.dumps({"now": now.strftime("%Y-%m-%dT%H:%MZ"), "sources": res}, indent=1))
    else:
        for r in res: print(f"{r['source']:<13} {r['state']:<8} {r['detail']}")
    if a.github:
        for r in res:
            if r["state"] == "overdue": print(f"::error title=Stale data: {r['source']}::{r['detail']}")
            elif r["state"] == "behind": print(f"::warning title=Missed one refresh: {r['source']}::{r['detail']}")
            elif r["state"] == "waiting": print(f"::warning title=Waiting on provider: {r['source']}::{r['detail']}")
        if os.environ.get("GITHUB_STEP_SUMMARY"):
            with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
                f.write(f"### Data freshness ({fmt(now)})\n\n| Source | Status | Last update | Detail |\n|---|---|---|---|\n")
                for r in res: f.write(f"| {r['source']} | {LABEL[r['state']]} | {r['updated'] or '–'} | {r['detail']} |\n")
        sys.exit(1 if any(r["state"] == "overdue" for r in res) else 0)
