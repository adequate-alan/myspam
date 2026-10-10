"""Rest-of-season projected points per game (ROS PPG) and the next-4 outlook for the current season → projections.csv.

The model lives in ros_model.py (role-based: recent opportunities with injury-shortened games scaled by snap share,
opportunity values fitted on the previous seasons, partial own efficiency, team environment from betting lines,
remaining schedule, small-sample shrinkage); ros_backtest.py scores it against 2024-25. This script runs it on
data/stats/<SEASON>.json (so build_stats.py must run first) and writes one row per player keyed by Sleeper ID:
    sleeper_id, player, pos, team, games, g_eff, prior_g, ppg, healthy_ppg, base_ppg, env, sched, env4, sched4, proj_ppg, n4_ppg,
    rank_score, proj_rank, line_json (the projected per-game stat line, which the browser scores with the league's scoring)
merge_projections.py puts proj_ppg / rank_score / games into RANKINGS_CSV and the per-player factors into data/projections.json.

    python3 project_players.py [games.csv]     (default: nflverse's games.csv)
"""
import os, re, sys
import pandas as pd
import ros_model as m
import team_ratings as tr

HERE = os.path.dirname(os.path.abspath(__file__))
SEASON = 2026
HIST_SEASONS = [2024, 2025]
COLS = ["sleeper_id", "player", "pos", "team", "games", "g_eff", "prior_g", "ppg", "healthy_ppg", "base_ppg", "env", "sched",
        "env4", "sched4", "proj_ppg", "n4_ppg", "rank_score", "proj_rank", "line_json"]

def norm(name):
    """Name key used by the name-based fallbacks (merge_projections.py, build_sleeper_ids.py)."""
    n = re.sub(r"[^a-z ]", "", str(name).lower().replace("-", " "))
    return re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", n).split().__str__()

def stats_path(season):
    return os.path.join(HERE, "..", "data", "stats", f"{season}.json")

def project(games_path=tr.GAMES_URL, season=SEASON):
    import json
    sc = m.scoring()
    hist = {y: m.load_stats(stats_path(y)) for y in HIST_SEASONS}
    rates = m.league_rates([m.frame(hist[y], sc) for y in HIST_SEASONS])
    stats = m.load_stats(stats_path(season))
    games = pd.read_csv(games_path)
    out = m.project(stats, games, stats["through_week"], prior_stats=hist[season - 1], rates=rates, use_future_lines=True, sc=sc)
    out["line_json"] = out.line.map(json.dumps)
    return out[COLS], rates

if __name__ == "__main__":
    out, rates = project(sys.argv[1] if len(sys.argv) > 1 else tr.GAMES_URL)
    print("league rates (2024-25):"); print(pd.DataFrame({p: {k: v for k, v in r.items() if k != "opps"} for p, r in rates.items()}).round(3).to_string())
    out.round(3).sort_values("proj_ppg", ascending=False).to_csv("projections.csv", index=False)
    for p in m.POS:
        top = out[out.pos == p].sort_values("proj_rank").head(6)
        print(f"\n{p}:"); print(top[["player", "team", "games", "prior_g", "ppg", "healthy_ppg", "base_ppg", "env", "sched", "proj_ppg", "n4_ppg"]].round(2).to_string(index=False))
