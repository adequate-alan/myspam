"""Points-by-positional-finish curves and replacement levels.
League: 12 teams, full PPR, TE premium (+0.5/rec for TE), superflex.
Scoring (league settings): pass yd 0.04, pass TD 4, INT -2, rush/rec yd 0.1,
rush/rec TD 6, reception 1, 2-pt 2, TE reception +0.5, fumble lost -2.
No return TDs.
Lineup: 1QB 2RB 3WR 1TE 1FLEX(RB/WR/TE) 1SF(QB/RB/WR/TE).
Source: nflverse weekly player stats, regular season weeks 1-17, 2023-2025.
"""
import pandas as pd, numpy as np, json

SEASONS = [2023, 2024, 2025]
MIN_GAMES = 8
DEPTH = {"QB": 40, "RB": 80, "WR": 100, "TE": 40}
TEAMS = 12
SLOTS = {"QB": 1, "RB": 2, "WR": 3, "TE": 1}
FLEX = {"n": 1, "eligible": ["RB", "WR", "TE"]}
SUPERFLEX = {"n": 1, "eligible": ["QB", "RB", "WR", "TE"]}
BENCH_PER_TEAM = {"QB": 1, "RB": 2, "WR": 2, "TE": 1}   # 6 bench spots

frames = []
for y in SEASONS:
    d = pd.read_csv(f"https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_{y}.csv", low_memory=False)
    d = d[(d.season_type == "REG") & (d.week <= 17) & d.position.isin(DEPTH)]
    d = d.copy()
    f = lambda c: d[c].fillna(0)
    d["pts"] = (0.04 * f("passing_yards") + 4 * f("passing_tds") - 2 * f("passing_interceptions")
                + 0.1 * f("rushing_yards") + 6 * f("rushing_tds")
                + 1 * f("receptions") + 0.1 * f("receiving_yards") + 6 * f("receiving_tds")
                + 2 * (f("passing_2pt_conversions") + f("rushing_2pt_conversions") + f("receiving_2pt_conversions"))
                - 2 * (f("sack_fumbles_lost") + f("rushing_fumbles_lost") + f("receiving_fumbles_lost"))
                + np.where(d.position == "TE", 0.5 * f("receptions"), 0))
    frames.append(d)
wk = pd.concat(frames)

seasons = (wk.groupby(["season", "player_id", "player_display_name", "position"])
             .agg(games=("week", "nunique"), pts=("pts", "sum")).reset_index())
seasons = seasons[seasons.games >= MIN_GAMES]
seasons["ppg"] = seasons.pts / seasons.games

curves = {}
for pos, depth in DEPTH.items():
    cols = []
    for y in SEASONS:
        s = seasons[(seasons.season == y) & (seasons.position == pos)].ppg.sort_values(ascending=False).to_numpy()
        s = np.pad(s[:depth], (0, max(0, depth - len(s))), mode="edge")
        cols.append(s)
    avg = np.mean(cols, axis=0)
    # light smoothing, then force non-increasing
    sm = pd.Series(avg).rolling(3, center=True, min_periods=1).mean().to_numpy().copy()
    sm[0] = avg[0]
    sm = np.minimum.accumulate(sm)
    curves[pos] = [round(float(v), 2) for v in sm]

# Replacement: fill every starting slot league-wide with the best available
starters = {p: TEAMS * n for p, n in SLOTS.items()}
def next_best(eligible):
    return max(eligible, key=lambda p: curves[p][starters[p]] if starters[p] < DEPTH[p] else -1)
for _ in range(TEAMS * FLEX["n"]):
    starters[next_best(FLEX["eligible"])] += 1
for _ in range(TEAMS * SUPERFLEX["n"]):
    starters[next_best(SUPERFLEX["eligible"])] += 1
replacement = {p: curves[p][starters[p]] for p in DEPTH}  # first non-starter
rostered = {p: starters[p] + round(TEAMS * BENCH_PER_TEAM[p]) for p in DEPTH}
waiver = {p: curves[p][min(rostered[p], DEPTH[p] - 1)] for p in DEPTH}  # first unrostered

out = {"curves": curves, "starters": starters, "replacement": replacement,
       "rostered": rostered, "waiver": waiver,
       "seasons": SEASONS, "min_games": MIN_GAMES}
json.dump(out, open("curves.json", "w"))
print("starters per position:", starters)
print("replacement PPG:", replacement)
print("rostered per position:", rostered)
print("waiver PPG:", waiver)
for p in DEPTH:
    c = curves[p]
    print(p, "1:", c[0], "6:", c[5], "12:", c[11], "24:", c[23], "36:", c[35] if len(c) > 35 else "-")
