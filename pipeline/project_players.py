"""Rest-of-season points-per-game projections from this season's games and betting lines.

1. Opportunity values: what an average target, carry and pass attempt was worth
   at each position in 2023-2025 under this league's scoring.
2. Expected PPG ("xPPG") for each player = his 2026 targets/carries/attempts per game
   x those opportunity values. Usage stabilizes much faster than touchdowns.
3. Base PPG = OPP_WEIGHT x xPPG + (1 - OPP_WEIGHT) x actual PPG.
4. Team environment: scale by (team's rest-of-season implied points / team's implied
   points in the games he played) ^ ENV_ELASTICITY, from team_ratings.py.
5. Projection score (rank_score): pull small samples toward replacement level
   (PRIOR_GAMES games of replacement-level play). The site uses it to re-order
   the players on your board, then reads that order off the same curve as your
   rankings, so the two are measured the same way before blending.
Output: projections.csv
"""
import numpy as np, pandas as pd, re, sys
import team_ratings as tr

BASE = "https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_{}.csv"
HIST_SEASONS = [2023, 2024, 2025]
SEASON = 2026
POS = ["QB", "RB", "WR", "TE"]
OPP_WEIGHT = 0.6        # share of base projection from usage (vs. actual points)
ENV_ELASTICITY = 0.75   # how strongly team scoring changes carry into player points
MIN_GAMES = 1
PRIOR_GAMES = 2         # small-sample shrinkage toward replacement before ranking

def score(d):
    f = lambda c: d[c].fillna(0)
    te = (d.position == "TE").astype(float)
    d = d.assign(
        pass_pts=0.04 * f("passing_yards") + 4 * f("passing_tds") - 2 * f("passing_interceptions")
                 + 2 * f("passing_2pt_conversions") - 2 * f("sack_fumbles_lost"),
        rush_pts=0.1 * f("rushing_yards") + 6 * f("rushing_tds") + 2 * f("rushing_2pt_conversions")
                 - 2 * f("rushing_fumbles_lost"),
        rec_pts=(1 + 0.5 * te) * f("receptions") + 0.1 * f("receiving_yards") + 6 * f("receiving_tds")
                + 2 * f("receiving_2pt_conversions") - 2 * f("receiving_fumbles_lost"))
    return d.assign(pts=d.pass_pts + d.rush_pts + d.rec_pts)

def load(season, src):
    d = pd.read_csv(src.format(season), low_memory=False)
    d = d[(d.season_type == "REG") & (d.week <= 17) & d.position.isin(POS)].copy()
    return score(d)

def opportunity_values(hist):
    """Average points per pass attempt, carry and target, by position."""
    s = hist.groupby("position")[["pass_pts", "rush_pts", "rec_pts", "attempts", "carries", "targets"]].sum()
    return pd.DataFrame({
        "per_att": s.pass_pts / s.attempts.replace(0, np.nan),
        "per_carry": s.rush_pts / s.carries.replace(0, np.nan),
        "per_target": s.rec_pts / s.targets.replace(0, np.nan)}).fillna(0)

def norm(name):
    n = re.sub(r"[^a-z ]", "", str(name).lower().replace("-", " "))
    return re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", n).split().__str__()

def project(src=BASE, games_path=tr.GAMES_URL):
    hist = pd.concat([load(y, src) for y in HIST_SEASONS])
    ov = opportunity_values(hist)
    cur = load(SEASON, src)

    # team environment
    g = tr.load_games(games_path)
    ratings = tr.fit_ratings(tr.implied_rows(g))
    tg = tr.team_game_totals(g, ratings)
    ros = tr.rest_of_season(tg)
    past = tg[tg.played][["week", "team", "implied"]]

    cur = cur.merge(past, on=["week", "team"], how="left")
    agg = cur.groupby(["player_id", "player_display_name", "position"]).agg(
        team=("team", "last"), games=("week", "nunique"), pts=("pts", "sum"),
        att=("attempts", "sum"), car=("carries", "sum"), tgt=("targets", "sum"),
        past_implied=("implied", "mean")).reset_index()
    agg = agg[agg.games >= MIN_GAMES]
    o = ov.loc[agg.position].reset_index(drop=True)
    agg = agg.reset_index(drop=True)
    agg["actual_ppg"] = agg.pts / agg.games
    agg["x_ppg"] = (agg.att * o.per_att + agg.car * o.per_carry + agg.tgt * o.per_target) / agg.games
    agg["base_ppg"] = OPP_WEIGHT * agg.x_ppg + (1 - OPP_WEIGHT) * agg.actual_ppg
    agg = agg.merge(ros, left_on="team", right_index=True, how="left")
    agg["env"] = (agg.ros_implied / agg.past_implied) ** ENV_ELASTICITY
    agg["proj_ppg"] = agg.base_ppg * agg.env.fillna(1)
    import json, os
    repl = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "curves.json")))["replacement"]
    prior = agg.position.map(repl)
    agg["rank_score"] = (agg.games * agg.proj_ppg + PRIOR_GAMES * prior) / (agg.games + PRIOR_GAMES)
    agg["proj_rank"] = agg.groupby("position").rank_score.rank(ascending=False, method="first").astype(int)
    agg["key"] = agg.player_display_name.map(norm)
    return agg, ov

if __name__ == "__main__":
    local = len(sys.argv) > 1
    src = sys.argv[1] + "/stats_player_week_{}.csv" if local else BASE
    games = sys.argv[1] + "/games.csv" if local else tr.GAMES_URL
    agg, ov = project(src, games)
    print("points per opportunity (2023-25, league scoring):"); print(ov.round(3).to_string())
    cols = ["player_display_name", "position", "team", "games", "actual_ppg", "x_ppg", "env", "proj_ppg", "rank_score", "proj_rank"]
    agg[cols].round(3).sort_values("proj_ppg", ascending=False).to_csv("projections.csv", index=False)
    for p in POS:
        top = agg[agg.position == p].sort_values("proj_rank").head(6)
        print(f"\n{p}:"); print(top[cols].round(2).to_string(index=False))
