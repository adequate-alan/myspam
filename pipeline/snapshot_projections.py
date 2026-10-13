"""Save this week's pre-game projections so live accuracy can be measured later (Alan, Oct 15: the historical backtest
can't reproduce live betting signals, so store the forecasts before the games and score them afterwards).

    python3 snapshot_projections.py [projections.csv] [../data/stats/2026.json] [../data/projections]

Writes data/projections/<season>/wk<N>.json, N = the next unplayed week, with one record per projected player:
rest-of-season PPG, next-4 PPG, next-game PPG (the same line with only the next game's environment and matchup),
the projected stat line, every component (base PPG, market environment and matchup factors for ROS / next 4 / next
game), the inputs behind them and the confidence score. Never overwritten once written (a later run the same week
is skipped), so the stored forecast is always the one made before the games. eval_projections.py scores them.
"""
import json, os, sys, datetime
import pandas as pd

def main(proj_path="projections.csv", stats_path="../data/stats/2026.json", out_dir="../data/projections"):
    stats = json.load(open(stats_path)); season = stats["season"]; week = stats["through_week"] + 1
    d = os.path.join(out_dir, str(season)); os.makedirs(d, exist_ok=True)
    out = os.path.join(d, f"wk{week:02d}.json")
    if os.path.exists(out):
        print(f"{out} already stored; kept the earlier forecast"); return
    proj = pd.read_csv(proj_path, dtype={"sleeper_id": str})
    # the role layer (Oct 12; roles.py, data/roles.json): the stored forecasts above are conditional (per game played,
    # a quarterback's per start); store who was expected to play at the time too, so the expected-points forecast
    # (n1 × role) can be scored later exactly as it was known before the games
    try: roles = json.load(open(os.path.join(out_dir, "..", "roles.json"))).get("players", {})
    except (OSError, ValueError): roles = {}
    recs = {}
    for r in proj.itertuples():
        recs[str(r.sleeper_id)] = dict(
            pos=r.pos, team=r.team, ros=round(float(r.proj_ppg), 2), n4=round(float(r.n4_ppg), 2), n1=round(float(r.n1_ppg), 2),
            base=round(float(r.base_ppg), 2), env=round(float(r.env), 3), sched=round(float(r.sched), 3),
            env4=round(float(r.env4), 3), sched4=round(float(r.sched4), 3), env1=round(float(r.env1), 3), sched1=round(float(r.sched1), 3),
            g_eff=round(float(r.g_eff), 2), prior_g=int(r.prior_g), healthy_ppg=round(float(r.healthy_ppg), 2),
            conf=round(float(r.conf), 3), cur_share=round(float(getattr(r, "cur_share", 1.0)), 3), moved=str(getattr(r, "moved", False)) in ("True", "1", "1.0"),
            line=json.loads(r.line_json), props=None)   # props: filled in once a props feed exists
        ro = roles.get(str(r.sleeper_id))
        if ro and ro[7] == week:   # role for this very week: multiplier, chance to start, depth, designation
            recs[str(r.sleeper_id)].update(role=ro[0], start=ro[2], depth=ro[4], status=ro[5], n1_exp=round(float(r.n1_ppg) * ro[0], 2))
    json.dump({"season": season, "week": week, "made": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%MZ"),
               "model": "ros-v3", "roles": bool(roles), "scoring": "base", "players": recs}, open(out, "w"), separators=(",", ":"))
    print(f"stored {len(recs)} forecasts for week {week} in {out}")

if __name__ == "__main__":
    main(*sys.argv[1:])
