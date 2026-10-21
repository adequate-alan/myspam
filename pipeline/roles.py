"""Who is expected to play: the role layer between a projection and a weekly expectation (Alan, Oct 12).

A player's projection (ros_model.py, `proj_ppg` / `n1_ppg` / the stat line) is *conditional*: what he scores per game
when he plays his usual role (for a quarterback, a full start). Before Oct 12 that conditional number was shown as
everyone's weekly projection, so every quarterback who had ever started a game (Case Keenum, Chicago's QB3, after one
spot start) was projected like a starter. This module turns the depth chart, injury status and practice participation
into a per-player multiplier for the next game and for later weeks:

    expected weekly points = conditional projection × multiplier

Quarterbacks share one job, so their chances are exclusive and cascade down the depth chart:
    P(QB1 starts) = a1;  P(QB2 starts) = (1 − a1) · a2;  P(QB3 starts) = (1 − a1)(1 − a2) · a3 …
where a = his availability. A third-stringer only starts when both quarterbacks ahead of him are out. The quarterback
next in line also gets a small relief share (RELIEF) of the games the starter starts. A quarterback who isn't on his
team's depth chart at all gets nothing (unless the team has no depth chart in the file, then nothing is known and the
multiplier stays 1).

RB, WR and TE share the field (several play every game; their per-game role already reflects how much they play when
they do), so their multiplier is their availability alone.

Availability, once this game's final injury report is out (the stats file's report for his team's next week with game
designations: Friday, or Wednesday before a Thursday game): no designation 1.0; Questionable 0.75 (0.9 / 0.75 / 0.4 when his latest practice was full / limited / did not
practice); Doubtful 0.15; Out, IR, PUP, suspended 0. Before it (Monday, Tuesday), Sleeper's designation on the depth
chart (data/depth_charts.json, refreshed with every stats run) is still last week's game status, so it only lowers his
chance (CARRY: Questionable 0.85, Doubtful 0.5, Out 0.3; IR 0): the starting job stays genuinely uncertain until the
report says otherwise. Wednesday and Thursday's practice-only reports (no designations yet) don't decide: a player on
them keeps that pre-report rule, a player not on them is healthy (Oct 21).

Later weeks: a short-term designation (Questionable / Doubtful / Out) is assumed to clear (LATER_AVAIL) and IR stays out.
Sleeper drops an injured quarterback down the depth chart (Chicago, Oct 12: Bagent, Keenum, Williams-Out), so a
short-term-injured quarterback goes back to QB1 when he is the team's established starter (more starts than the listed
QB1 over this season and last; `starts`: games with ≥ START_SNAP of the snaps, last season at half weight) and his
availability decides: ruled Out for this game, the next man up starts; listed Out from last week, a 30% chance; later
weeks 85%. A healthy quarterback the team moved ahead of him (a benching, a starting announcement) keeps the job.

Nothing here touches rankings, values, tiers or history; ROS PPG keeps its conditional meaning. build_roles.py writes
data/roles.json for the browser; snapshot_projections.py stores the multipliers with each pre-game forecast.
"""
import re

QB_SLOTS = {"QB": ["QB"]}
SLOTS = {"QB": ["QB"], "RB": ["RB"], "WR": ["LWR", "RWR", "SWR", "WR"], "TE": ["TE"]}
RELIEF = 0.04          # the next quarterback in line: share of a game he can expect in relief while the starter starts
START_SNAP = 0.5       # a game counts as a start with at least half the offensive snaps
PRIOR_START_W = 0.5    # last season's starts count half toward the established starter
LATER_AVAIL = 0.85     # a short-term-injured player's availability for weeks after the next game
SHORT_TERM = ("Questionable", "Doubtful", "Out")


def norm_status(st):
    """Sleeper / injury-report designations → one of None, Questionable, Doubtful, Out, IR."""
    s = (st or "").strip().lower()
    if not s or s in ("na", "active", "healthy"): return None
    if s.startswith("q"): return "Questionable"
    if s.startswith("d"): return "Doubtful"
    if s.startswith("o"): return "Out"
    if s in ("ir", "pup", "sus", "nfi", "cov") or "reserve" in s or "suspend" in s or s.startswith("ir"): return "IR"
    return None


def availability(status, practice=None):
    """Chance he plays the game, from his designation and (when it's this game's report) his latest practice.

    Fitted Oct 21 on the final injury reports of 2023-25 (projection accuracy audit): Questionable after a full
    practice played 98% of the time, after a limited one 68%, after a DNP 50%; Doubtful 4%. A Questionable with no
    practice entry keeps 0.75."""
    st = norm_status(status)
    if st is None: return 1.0
    if st == "Questionable":
        p = (practice or "").upper()
        return AVAIL_Q.get(p, 0.75)
    if st == "Doubtful": return AVAIL_DOUBTFUL
    return 0.0


AVAIL_Q = {"FP": 0.98, "LP": 0.68, "DNP": 0.50}
AVAIL_DOUBTFUL = 0.04


# A designation from last week's report (Monday / Tuesday, before this week's first report): the player may well be
# back, so it lowers his chance without ruling him out; IR still does (Oct 12: Sleeper still lists last week's game
# status until the next report)
CARRY = {"Questionable": 0.85, "Doubtful": 0.5, "Out": 0.3, "IR": 0.0}


def latest_practice(row, ci):
    for k in ("fri", "thu", "wed"):
        if k in ci and row[ci[k]]: return row[ci[k]]
    return row[ci["practice"]] if "practice" in ci else None


def next_weeks(stats):
    """Team → its next unplayed regular-season week (from the schedule in the stats file)."""
    sc = stats.get("schedule_cols") or []
    wi, pi = (sc.index("w") if "w" in sc else 0), (sc.index("pf") if "pf" in sc else 4)
    out = {}
    for tm, rows in (stats.get("schedule") or {}).items():
        nxt = [r[wi] for r in rows if r[pi] is None]
        if nxt: out[tm] = min(nxt)
    return out


def starts(stats_list):
    """Sleeper ID → established-starter score: starts this season + PRIOR_START_W × starts last season."""
    out = {}
    for w, stats in stats_list:
        if not stats: continue
        ci = {c: i for i, c in enumerate(stats["cols"])}
        for sid, p in stats["players"].items():
            if p.get("p") != "QB": continue
            n = sum(1 for g in p["g"] if (g[ci["snap"]] or 0) >= START_SNAP)
            if n: out[sid] = out.get(sid, 0.0) + w * n
    return out


def team_roles(stats, depth, prior_stats=None):
    """Sleeper ID → dict(pos, team, week, depth, status, fresh, avail, n, l, s, sl) (fresh: this game's report is out):
    n / l = expected-points multiplier for the next game / later weeks, s / sl = chance to start (quarterbacks)."""
    teams = (depth or {}).get("teams") or {}
    nxt = next_weeks(stats)
    inj = stats.get("injuries") or {}
    ici = {c: i for i, c in enumerate(inj.get("cols") or [])}
    report, fresh = {}, set()   # sid -> (status, practice) from this game's injury report; teams with this week's final report
    interim = set()             # players on this week's practice-only report (Wed / Thu, before game designations)
    for tm, rows in (inj.get("teams") or {}).items():
        if inj.get("week") != nxt.get(tm): continue   # a report for an earlier week says nothing about this game
        # Game designations (Questionable, Doubtful, Out) come with the final report (Friday; Wednesday before a Thursday
        # game). A practice-only report says who is hurt but not whether he plays (Oct 21: on Wednesday Kyle Monangai, DNP
        # and Questionable on Sleeper, went to a full 1.0 because "no designation" read as healthy), so until it's final
        # a listed player keeps the pre-report rule below; a player not on it is healthy.
        final = any(r[ici["status"]] for r in rows)
        if final: fresh.add(tm)
        for r in rows:
            if not r[ici["sid"]]: continue
            if final: report[str(r[ici["sid"]])] = (r[ici["status"]], latest_practice(r, ici))
            else: interim.add(str(r[ici["sid"]]))
    early = {tm for tm, rows in (inj.get("teams") or {}).items() if inj.get("week") == nxt.get(tm)} - fresh
    score = starts([(1.0, stats), (PRIOR_START_W, prior_stats)])
    out = {}
    for tm, chart in teams.items():
        wk = nxt.get(tm)
        for pos, slots in SLOTS.items():
            seen, order = set(), []
            # one ordered list per position: depth order across the position's slots (WR: LWR1, RWR1, SWR1, LWR2, …)
            lists = [chart.get(s, []) for s in slots]
            for i in range(max((len(x) for x in lists), default=0)):
                for lst in lists:
                    if i < len(lst) and lst[i][0] not in seen and lst[i][2] in (pos, ""):
                        seen.add(lst[i][0]); order.append(lst[i])
            rows = []
            for k, (sid, name, _, st) in enumerate(order):
                rep, sleeper = report.get(sid), norm_status(st)
                if tm in fresh:   # this game's report is out: it decides (Sleeper's IR / PUP aside, which the report omits)
                    status = norm_status(rep[0]) if rep and rep[0] else ("IR" if sleeper == "IR" else None)
                    a = availability(status, rep[1] if rep else None)
                elif tm in early and sid not in interim:   # not on this week's practice report: healthy (IR aside)
                    status = "IR" if sleeper == "IR" else None
                    a = 0.0 if status == "IR" else 1.0
                else:             # only last week's designation so far: lower his chance, don't rule him out
                    status = sleeper
                    a = CARRY.get(status, 1.0)
                al = 0.0 if status == "IR" else LATER_AVAIL if status in SHORT_TERM else 1.0
                rows.append(dict(sid=sid, name=name, pos=pos, team=tm, week=wk, depth=k + 1, status=status, avail=a, avail_l=al, fresh=tm in fresh))
            if pos == "QB":
                # Sleeper drops a hurt quarterback down the chart; the team's established starter goes back on top and his
                # availability decides (ruled Out this week: 0, so QB2 starts; last week's Out: 30%; later weeks: 85%)
                order_q = list(rows)
                hurt = [r for r in order_q if r["status"] in SHORT_TERM and score.get(r["sid"], 0) > score.get(order_q[0]["sid"], 0)]
                if hurt:
                    best = max(hurt, key=lambda r: score.get(r["sid"], 0))
                    order_q = [best] + [r for r in order_q if r is not best]
                cascade(order_q, "avail", "s", "n")
                cascade(order_q, "avail_l", "sl", "l")
            else:
                for r in rows: r["s"] = r["sl"] = None; r["n"] = r["avail"]; r["l"] = r["avail_l"]
            for r in rows:
                out.setdefault(r["sid"], r)   # a player listed at two positions keeps the first (his own position first)
    return out


def cascade(rows, akey, skey, mkey):
    """Exclusive starting job down an ordered list: P(start) and the expected-points multiplier (start + relief)."""
    left = 1.0
    for i, r in enumerate(rows):
        r[skey] = left * r[akey]
        relief = RELIEF * (1.0 - left) * r[akey] if i == 1 else 0.0   # QB2 sees some relief while QB1 plays
        r[mkey] = min(1.0, r[skey] + relief)
        left *= 1.0 - r[akey]


def multiplier(roles, sid, pos, team, week, depth_known):
    """Expected-points multiplier for one player and week (1 when nothing is known; 0 for a QB missing from his team's chart)."""
    r = roles.get(str(sid))
    if r and (team is None or r["team"] == team):
        if r["week"] is None or week is None or week <= r["week"]: return r["n"]
        return r["l"]
    if pos == "QB" and team and team in depth_known: return 0.0
    return 1.0
