"""Weekly stats and schedules for the player pages: data/stats/<season>.json.

Stats data only. Nothing here reads or writes the rankings in index.html.

For each QB/RB/WR/TE with a Sleeper ID, every regular-season game:
  week, team, opponent and the raw stat components the site needs to score a game
  under any league's settings (Sleeper scoring keys: pass_yd, rec, rush_td, ...).
Fantasy points are calculated in the browser, so league scoring can be applied.

Also each team's schedule (opponent, home/away, date, score) for bye weeks and
upcoming opponents.

Sources: nflverse player stats (weekly) and nflverse schedules, matched to Sleeper
IDs with the DynastyProcess player ID table.
Run from the pipeline folder: python build_stats.py 2026 [2025 2024 ...]
"""
import json, os, sys
from datetime import datetime, timezone
import pandas as pd

STATS_URL = "https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_{}.csv"
GAMES_URL = "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"
IDS_URL = "https://raw.githubusercontent.com/dynastyprocess/data/master/files/db_playerids.csv"
POS = ["QB", "RB", "WR", "TE"]
TEAM_FIX = {"LA": "LAR", "WSH": "WAS", "JAC": "JAX", "LVR": "LV", "OAK": "LV", "SD": "LAC", "STL": "LAR"}

# column in the output (named like Sleeper scoring keys) -> nflverse column(s) summed
COMPONENTS = {
    "pass_cmp": ["completions"], "pass_att": ["attempts"], "pass_yd": ["passing_yards"], "pass_td": ["passing_tds"],
    "pass_int": ["passing_interceptions"], "pass_2pt": ["passing_2pt_conversions"], "pass_sack": ["sacks_suffered"],
    "pass_fd": ["passing_first_downs"],
    "rush_att": ["carries"], "rush_yd": ["rushing_yards"], "rush_td": ["rushing_tds"],
    "rush_2pt": ["rushing_2pt_conversions"], "rush_fd": ["rushing_first_downs"],
    "rec_tgt": ["targets"], "rec": ["receptions"], "rec_yd": ["receiving_yards"], "rec_td": ["receiving_tds"],
    "rec_2pt": ["receiving_2pt_conversions"], "rec_fd": ["receiving_first_downs"],
    "fum_lost": ["sack_fumbles_lost", "rushing_fumbles_lost", "receiving_fumbles_lost"],
}
COLS = ["w", "tm", "opp"] + list(COMPONENTS) + ["tgt_share"]


def team(t):
    return TEAM_FIX.get(t, t) if isinstance(t, str) else ""


def sleeper_map(src=IDS_URL):
    d = pd.read_csv(src, low_memory=False, usecols=["gsis_id", "sleeper_id", "db_season"])
    d = d[d.gsis_id.notna() & d.sleeper_id.notna()]
    d = d.sort_values("db_season", ascending=False).drop_duplicates("gsis_id")
    return dict(zip(d.gsis_id, d.sleeper_id.astype("int64").astype(str)))


def schedule(games, season):
    g = games[(games.season == season) & (games.game_type == "REG")]
    out = {}
    for r in g.itertuples():
        a, h = team(r.away_team), team(r.home_team)
        sa = None if pd.isna(r.away_score) else int(r.away_score)
        sh = None if pd.isna(r.home_score) else int(r.home_score)
        out.setdefault(a, []).append([int(r.week), h, 0, r.gameday, sa, sh])
        out.setdefault(h, []).append([int(r.week), a, 1, r.gameday, sh, sa])
    return {t: sorted(v) for t, v in sorted(out.items())}


def build(season, ids, games, stats_src=STATS_URL):
    d = pd.read_csv(stats_src.format(season), low_memory=False)
    d = d[(d.season_type == "REG") & d.position.isin(POS)].copy()
    d["sid"] = d.player_id.map(ids)
    d = d[d.sid.notna()].sort_values(["sid", "week"])
    players = {}
    for sid, rows in d.groupby("sid"):
        log = []
        for r in rows.itertuples():
            row = [int(r.week), team(r.team), team(r.opponent_team)]
            for cols in COMPONENTS.values():
                row.append(int(round(sum(0 if pd.isna(getattr(r, c)) else getattr(r, c) for c in cols))))
            ts = getattr(r, "target_share")
            row.append(None if pd.isna(ts) else round(float(ts), 3))
            log.append(row)
        last = rows.iloc[-1]
        players[sid] = {"n": last.player_display_name, "p": last.position, "g": log}
    return {
        "season": season,
        "through_week": int(d.week.max()) if len(d) else 0,
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),   # when this file was built (UTC)
        "cols": COLS,
        "players": players,
        "schedule": schedule(games, season),
    }


if __name__ == "__main__":
    seasons = [int(x) for x in sys.argv[1:]] or [2026]
    here = os.path.dirname(os.path.abspath(__file__))
    out_dir = os.path.join(here, "..", "data", "stats")
    os.makedirs(out_dir, exist_ok=True)
    stats_src = os.environ.get("STATS_SRC", STATS_URL)
    ids = sleeper_map(os.environ.get("IDS_SRC", IDS_URL))
    games = pd.read_csv(os.environ.get("GAMES_SRC", GAMES_URL), low_memory=False)
    for s in seasons:
        data = build(s, ids, games, stats_src)
        path = os.path.join(out_dir, f"{s}.json")
        with open(path, "w") as f:
            json.dump(data, f, separators=(",", ":"))
        print(f"{s}: {len(data['players'])} players through week {data['through_week']}, "
              f"{os.path.getsize(path) / 1024:.0f} KB")
