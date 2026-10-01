"""Market-implied team ratings from NFL betting lines.

Every posted spread and total implies a score for each team:
  home implied = (total + spread) / 2,  away implied = (total - spread) / 2
(nflverse spread_line is from the home team's side: positive = home favored.)

We fit  implied = league_avg + home_edge*is_home + offense[team] - defense[opponent]
with a little ridge shrinkage, then use it to fill in every remaining game
that doesn't have a line yet. Source: nflverse/nfldata games.csv.
"""
import numpy as np, pandas as pd

GAMES_URL = "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"
SEASON = 2026
LAST_FANTASY_WEEK = 17
PLAYOFF_WEEKS = (15, 16, 17)   # league playoffs start week 15
PLAYOFF_WEIGHT = 1.5           # those weeks count 1.5x in rest-of-season averages
RIDGE = 2.0

def load_games(path=GAMES_URL):
    g = pd.read_csv(path)
    return g[(g.season == SEASON) & (g.game_type == "REG")].copy()

def implied_rows(g):
    """One row per team per game that has a line."""
    lined = g.dropna(subset=["spread_line", "total_line"])
    rows = []
    for _, r in lined.iterrows():
        neutral = str(r.get("location", "")).lower() == "neutral"
        home_pts = (r.total_line + r.spread_line) / 2
        away_pts = (r.total_line - r.spread_line) / 2
        rows.append((r.week, r.home_team, r.away_team, 0 if neutral else 1, home_pts))
        rows.append((r.week, r.away_team, r.home_team, 0, away_pts))
    return pd.DataFrame(rows, columns=["week", "team", "opp", "home", "implied"])

def fit_ratings(rows):
    teams = sorted(set(rows.team) | set(rows.opp))
    idx = {t: i for i, t in enumerate(teams)}
    n = len(teams)
    X = np.zeros((len(rows), 2 * n + 1))
    for k, r in enumerate(rows.itertuples()):
        X[k, idx[r.team]] = 1          # offense
        X[k, n + idx[r.opp]] = -1      # opponent defense
        X[k, 2 * n] = r.home           # home edge
    mu = rows.implied.mean()
    y = rows.implied.to_numpy() - mu
    pen = np.eye(2 * n + 1) * RIDGE
    pen[-1, -1] = 0                    # don't shrink home edge
    beta = np.linalg.solve(X.T @ X + pen, X.T @ y)
    off = dict(zip(teams, beta[:n])); dfn = dict(zip(teams, beta[n:2 * n]))
    return {"mu": mu, "home": beta[-1], "off": off, "def": dfn}

def team_game_totals(g, ratings):
    """Implied points for every team in every regular-season game:
    the posted line where one exists, otherwise the ratings' prediction."""
    lined = implied_rows(g).set_index(["week", "team"]).implied
    out = []
    for _, r in g.iterrows():
        neutral = str(r.get("location", "")).lower() == "neutral"
        for team, opp, home in ((r.home_team, r.away_team, 0 if neutral else 1), (r.away_team, r.home_team, 0)):
            key = (r.week, team)
            if key in lined.index:
                pts, src = lined[key], "line"
            else:
                pts = ratings["mu"] + ratings["home"] * home + ratings["off"][team] - ratings["def"][opp]
                src = "model"
            out.append({"week": r.week, "team": team, "opp": opp, "implied": pts, "source": src,
                        "played": pd.notna(r.home_score)})
    return pd.DataFrame(out)

def rest_of_season(tg):
    fut = tg[(~tg.played) & (tg.week <= LAST_FANTASY_WEEK)].copy()
    fut["w"] = np.where(fut.week.isin(PLAYOFF_WEEKS), PLAYOFF_WEIGHT, 1.0)
    ros = fut.groupby("team").apply(lambda d: np.average(d.implied, weights=d.w), include_groups=False)
    games = fut.groupby("team").size()
    return pd.DataFrame({"ros_implied": ros, "ros_games": games})

if __name__ == "__main__":
    import sys
    g = load_games(sys.argv[1] if len(sys.argv) > 1 else GAMES_URL)
    rows = implied_rows(g)
    rt = fit_ratings(rows)
    tg = team_game_totals(g, rt)
    # sanity: how well do ratings reproduce the posted lines?
    chk = tg[tg.source == "line"].merge(rows, on=["week", "team"], suffixes=("", "_line"))
    pred = [rt["mu"] + rt["home"] * h + rt["off"][t] - rt["def"][o] for t, o, h in zip(rows.team, rows.opp, rows.home)]
    print(f"lines used: {len(rows)//2} games; league avg {rt['mu']:.1f}; home edge {rt['home']:.2f}; "
          f"fit error (MAE) {np.mean(np.abs(np.array(pred) - rows.implied)):.2f} pts")
    ros = rest_of_season(tg).sort_values("ros_implied", ascending=False)
    print(ros.head(5).round(1).to_string()); print("..."); print(ros.tail(3).round(1).to_string())
