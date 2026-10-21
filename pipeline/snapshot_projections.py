"""Save this week's pre-game projections so live accuracy can be measured later (Alan, Oct 15: the historical backtest
can't reproduce live betting signals, so store the forecasts before the games and score them afterwards).

    python3 snapshot_projections.py [projections.csv] [../data/stats/2026.json] [../data/projections]

Writes data/projections/<season>/wk<N>.json, N = the week after through_week, with one record per projected player:
rest-of-season PPG, next-4 PPG, next-game PPG (the same line with only the next game's environment and matchup),
the projected stat line, every component (base PPG, market environment and matchup factors for ROS / next 4 / next
game), the inputs behind them and the confidence score. eval_projections.py scores them.

Freshness (Oct 21 audit): the Week 6 forecast was stored on Oct 10, after only Thursday's Week 5 game, because a
Thursday game already makes `through_week` count the week; the write-once rule then kept that stale forecast. Now a
forecast is stored only when every game of `through_week` is final, and a later run replaces it until the forecast
week's first kickoff (the latest pregame forecast is the one scored); from the first kickoff on it is never rewritten.
Each record also keeps the forecasts the audit replaced, so they stay comparison baselines: n1_legacy (the site's weekly
projection before Oct 21: ROS PPG x the browser's Vegas and matchup, legacy_context) and n4_legacy (ros_model.LEGACY_N4).
"""
import json, os, sys, datetime
from zoneinfo import ZoneInfo
import pandas as pd

ET = ZoneInfo("America/New_York")

def week_state(stats, week):
    """(all of that week's games final, first kickoff of that week as UTC datetime or None) from the stats schedule."""
    cols = stats.get("schedule_cols") or []
    ci = {c: i for i, c in enumerate(cols)}
    final, kicks = True, []
    for rows in (stats.get("schedule") or {}).values():
        for r in rows:
            if r[ci.get("w", 0)] != week: continue
            if r[ci.get("pf", 4)] is None: final = False
            d, t = (r[ci["date"]] if "date" in ci else None), (r[ci["time"]] if "time" in ci else None)
            if d:
                hh, mm = (t or "13:00").split(":")[:2]
                y, mo, dd = (int(x) for x in d.split("-"))
                kicks.append(datetime.datetime(y, mo, dd, int(hh), int(mm), tzinfo=ET).astimezone(datetime.timezone.utc))
    return final, (min(kicks) if kicks else None)

def legacy_context(stats, week):
    """The site's weekly calibration before Oct 21 (index.html gameContext), kept as a comparison baseline: Vegas = his
    team's implied total this week vs its average over its unplayed lined games, ^0.75, capped +-15%; matchup = what the
    opponent allowed his position per game vs average, weight 0.35 g/(g+4), capped +-10%. (team, pos) -> (env, mx)."""
    import numpy as np, ros_model as m
    ci = {c: i for i, c in enumerate(stats.get("schedule_cols") or [])}
    imp = lambda r: (r[ci["total"]] / 2 - r[ci["spread"]] / 2) if r[ci["total"]] is not None and r[ci["spread"]] is not None else None
    d = m.frame(stats, m.scoring()); d = d[d.week < week]
    tot = d.groupby(["opp", "pos"]).agg(pts=("pts", "sum"), g=("week", "nunique")); tot["ppg"] = tot.pts / tot.g
    avg = tot.groupby("pos").ppg.mean()
    out = {}
    for tm, rows in (stats.get("schedule") or {}).items():
        nxt = [r for r in rows if r[ci["w"]] == week]
        if not nxt: continue
        r = nxt[0]; now = imp(r); avgs = [imp(x) for x in rows if x[ci["pf"]] is None and imp(x) is not None]
        env = max(0.85, min(1.15, (now / np.mean(avgs)) ** 0.75)) if now is not None and len(avgs) >= 2 else 1.0
        for pos in ("QB", "RB", "WR", "TE"):
            mx = 1.0
            if (r[ci["opp"]], pos) in tot.index:
                x = tot.loc[(r[ci["opp"]], pos)]; w = 0.35 * x.g / (x.g + 4); mx = max(0.9, min(1.1, 1 + w * (x.ppg / avg[pos] - 1)))
            out[(tm, pos)] = (env, mx)
    return out

def main(proj_path="projections.csv", stats_path="../data/stats/2026.json", out_dir="../data/projections", now=None):
    stats = json.load(open(stats_path)); season = stats["season"]; week = stats["through_week"] + 1
    now = now or datetime.datetime.now(datetime.timezone.utc)
    done, _ = week_state(stats, stats["through_week"])
    if not done:
        print(f"Week {stats['through_week']} still has games to play; no forecast stored (it would miss their results)"); return
    _, kick = week_state(stats, week)
    d = os.path.join(out_dir, str(season)); os.makedirs(d, exist_ok=True)
    out = os.path.join(d, f"wk{week:02d}.json")
    if os.path.exists(out) and (kick is None or now >= kick):
        print(f"{out} already stored and Week {week} has started; kept the pregame forecast"); return
    proj = pd.read_csv(proj_path, dtype={"sleeper_id": str})
    # the role layer (Oct 12; roles.py, data/roles.json): the stored forecasts above are conditional (per game played,
    # a quarterback's per start); store who was expected to play at the time too, so the expected-points forecast
    # (n1 × role) can be scored later exactly as it was known before the games
    try: roles = json.load(open(os.path.join(out_dir, "..", "roles.json"))).get("players", {})
    except (OSError, ValueError): roles = {}
    recs = {}
    try: legacy = legacy_context(stats, week)
    except Exception as e: legacy = {}; print(f"no legacy weekly baseline: {e}")
    for r in proj.itertuples():
        recs[str(r.sleeper_id)] = dict(
            pos=r.pos, team=r.team, ros=round(float(r.proj_ppg), 2), n4=round(float(r.n4_ppg), 2), n1=round(float(r.n1_ppg), 2),
            base=round(float(r.base_ppg), 2), env=round(float(r.env), 3), sched=round(float(r.sched), 3),
            env4=round(float(r.env4), 3), sched4=round(float(r.sched4), 3), env1=round(float(r.env1), 3), sched1=round(float(r.sched1), 3),
            g_eff=round(float(r.g_eff), 2), prior_g=int(r.prior_g), healthy_ppg=round(float(r.healthy_ppg), 2),
            conf=round(float(r.conf), 3), cur_share=round(float(getattr(r, "cur_share", 1.0)), 3), moved=str(getattr(r, "moved", False)) in ("True", "1", "1.0"),
            line=json.loads(r.line_json), props=None,   # props: filled in once a props feed exists
            # Oct 21: the Next 4 before the audit (ros_model.LEGACY_N4), kept so it stays a comparison baseline; the
            # unweighted market / matchup factors; a role change (snap-share jump: n4 from a faster-updating line)
            n4_legacy=round(float(r.base_ppg) * float(r.env4_raw) ** 0.5 * float(r.sched4_raw) ** 0.25, 2) if hasattr(r, "env4_raw") else None,
            env4_raw=round(float(getattr(r, "env4_raw", 1.0)), 3), sched4_raw=round(float(getattr(r, "sched4_raw", 1.0)), 3),
            role_change=str(getattr(r, "role_change", False)) in ("True", "1", "1.0"))
        # the site's weekly projection before Oct 21 (ROS PPG x its own Vegas and matchup), scored beside n1 as a baseline
        lc = legacy.get((r.team, r.pos))
        recs[str(r.sleeper_id)]["n1_legacy"] = round(float(r.proj_ppg) * lc[0] * lc[1], 2) if lc else None
        ro = roles.get(str(r.sleeper_id))
        if ro and ro[7] == week:   # role for this very week: multiplier, chance to start, depth, designation
            recs[str(r.sleeper_id)].update(role=ro[0], start=ro[2], depth=ro[4], status=ro[5], n1_exp=round(float(r.n1_ppg) * ro[0], 2))
    json.dump({"season": season, "week": week, "made": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%MZ"),
               "model": "ros-v4", "kickoff": kick.strftime("%Y-%m-%dT%H:%MZ") if kick else None, "roles": bool(roles), "scoring": "base", "players": recs}, open(out, "w"), separators=(",", ":"))
    print(f"stored {len(recs)} forecasts for week {week} in {out} (first kickoff {kick})")

if __name__ == "__main__":
    main(*sys.argv[1:])
