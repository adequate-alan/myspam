"""Rest-of-season projected points per game (ROS PPG) for the current season → projections.csv.

The model lives in ros_model.py (role-based: recent opportunities with injury-shortened games scaled by snap share,
opportunity values fitted on the previous seasons, partial own efficiency, team environment from betting lines,
remaining schedule, small-sample shrinkage); ros_backtest.py scores it against 2024-25. This script runs it on
data/stats/<SEASON>.json (so build_stats.py must run first) and writes one row per player keyed by Sleeper ID:
    sleeper_id, player, pos, team, games, g_eff, ppg, healthy_ppg, role_x, eff, env, sched, proj_ppg, rank_score, proj_rank
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
COLS = ["sleeper_id", "player", "pos", "team", "games", "g_eff", "ppg", "healthy_ppg", "role_x", "eff", "env", "sched",
        "proj_ppg", "rank_score", "proj_rank"]

def norm(name):
    """Name key used by the name-based fallbacks (merge_projections.py, build_sleeper_ids.py)."""
    n = re.sub(r"[^a-z ]", "", str(name).lower().replace("-", " "))
    return re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", n).split().__str__()

def stats_path(season):
    return os.path.join(HERE, "..", "data", "stats", f"{season}.json")

def project(games_path=tr.GAMES_URL, season=SEASON):
    sc = m.scoring()
    ov = m.fit_opportunity_values([m.frame(m.load_stats(stats_path(y)), sc) for y in HIST_SEASONS])
    stats = m.load_stats(stats_path(season))
    games = pd.read_csv(games_path)
    out = m.project(stats, games, stats["through_week"], ov=ov, use_future_lines=True, sc=sc)
    return out[COLS], ov

if __name__ == "__main__":
    out, ov = project(sys.argv[1] if len(sys.argv) > 1 else tr.GAMES_URL)
    print("points per opportunity (2024-25, site scoring):")
    print(pd.DataFrame(ov).T.round(2).to_string())
    out.round(3).sort_values("proj_ppg", ascending=False).to_csv("projections.csv", index=False)
    for p in m.POS:
        top = out[out.pos == p].sort_values("proj_rank").head(6)
        print(f"\n{p}:"); print(top[["player", "team", "games", "ppg", "healthy_ppg", "role_x", "eff", "env", "sched", "proj_ppg"]].round(2).to_string(index=False))
