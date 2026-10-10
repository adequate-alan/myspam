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
    recs = {}
    for r in proj.itertuples():
        recs[str(r.sleeper_id)] = dict(
            pos=r.pos, team=r.team, ros=round(float(r.proj_ppg), 2), n4=round(float(r.n4_ppg), 2), n1=round(float(r.n1_ppg), 2),
            base=round(float(r.base_ppg), 2), env=round(float(r.env), 3), sched=round(float(r.sched), 3),
            env4=round(float(r.env4), 3), sched4=round(float(r.sched4), 3), env1=round(float(r.env1), 3), sched1=round(float(r.sched1), 3),
            g_eff=round(float(r.g_eff), 2), prior_g=int(r.prior_g), healthy_ppg=round(float(r.healthy_ppg), 2),
            conf=round(float(r.conf), 3), line=json.loads(r.line_json), props=None)   # props: filled in once a props feed exists
    json.dump({"season": season, "week": week, "made": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%MZ"),
               "model": "ros-v2", "scoring": "base", "players": recs}, open(out, "w"), separators=(",", ":"))
    print(f"stored {len(recs)} forecasts for week {week} in {out}")

if __name__ == "__main__":
    main(*sys.argv[1:])
