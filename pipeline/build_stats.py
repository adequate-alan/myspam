"""Weekly stats and schedules for the player pages: data/stats/<season>.json.

Stats data only. Nothing here reads or writes the rankings in index.html.

For each QB/RB/WR/TE with a Sleeper ID, every regular-season game:
  week, team, opponent and the raw stat components the site needs to score a game
  under any league's settings (Sleeper scoring keys: pass_yd, rec, rush_td, ...).
Fantasy points are calculated in the browser, so league scoring can be applied.

Also each team's schedule (opponent, home/away, date, score) for bye weeks and
upcoming opponents, plus the betting context nflverse carries for each game:
kickoff time (ET), the team's spread (negative = favored), game total, roof and stadium.

Also, for the player pages' matchup context:
  defense   each defense's run and pass efficiency allowed (EPA per play, success rate,
            explosive-play rate: runs of 10+ yards, passes of 20+), from nflverse play-by-play
  injuries  the latest week's injury report per team: game status, practice status, injury, and the
            practice status by day (Wed/Thu/Fri). nflverse keeps only the latest practice status, so
            each run records it under its own day (Eastern time: Wed, Thu, or Fri for Fri-Mon runs)
            and carries the days already recorded this week over from the previous file.

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
PBP_URL = "https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_{}.csv.gz"
INJ_URL = "https://github.com/nflverse/nflverse-data/releases/download/injuries/injuries_{}.csv"
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


def num(x):
    return None if pd.isna(x) else float(x)


def text(x):
    return None if pd.isna(x) else str(x)


# Schedule row: [week, opponent, home (1/0), date, points for, points against,
#                kickoff ET "HH:MM", team spread (negative = favored), game total, roof, stadium]
SCHEDULE_COLS = ["w", "opp", "home", "date", "pf", "pa", "time", "spread", "total", "roof", "stadium"]


def schedule(games, season):
    g = games[(games.season == season) & (games.game_type == "REG")]
    out = {}
    for r in g.itertuples():
        a, h = team(r.away_team), team(r.home_team)
        sa = None if pd.isna(r.away_score) else int(r.away_score)
        sh = None if pd.isna(r.home_score) else int(r.home_score)
        line = num(getattr(r, "spread_line", None))   # nflverse: home team's expected margin
        extra = [text(getattr(r, "gametime", None)), None, num(getattr(r, "total_line", None)),
                 text(getattr(r, "roof", None)), text(getattr(r, "stadium", None))]
        away, home = list(extra), list(extra)
        if line is not None:
            away[1], home[1] = line, -line
        out.setdefault(a, []).append([int(r.week), h, 0, r.gameday, sa, sh] + away)
        out.setdefault(h, []).append([int(r.week), a, 1, r.gameday, sh, sa] + home)
    return {t: sorted(v, key=lambda x: x[0]) for t, v in sorted(out.items())}


DEFENSE_COLS = ["g", "run_plays", "run_epa", "run_success", "run_expl", "pass_plays", "pass_epa", "pass_success", "pass_expl"]


def defense(season, src=PBP_URL):
    """Per defense, regular season: games, then for runs and dropbacks: plays, EPA/play, success rate, explosive rate."""
    p = pd.read_csv(src.format(season), low_memory=False,
                    usecols=["season_type", "game_id", "defteam", "play_type", "rush", "qb_dropback", "epa", "success", "yards_gained"])
    p = p[(p.season_type == "REG") & p.defteam.notna() & p.epa.notna()]
    run = p[(p.rush == 1) & (p.play_type == "run")]
    drop = p[p.qb_dropback == 1]
    out = {}
    for d, rows in p.groupby("defteam"):
        r, q = run[run.defteam == d], drop[drop.defteam == d]
        def stats(x, big):
            return [int(len(x)), round(float(x.epa.mean()), 3) if len(x) else None,
                    round(float(x.success.mean()), 3) if len(x) else None,
                    round(float((x.yards_gained >= big).mean()), 3) if len(x) else None]
        out[team(d)] = [int(rows.game_id.nunique())] + stats(r, 10) + stats(q, 20)
    return {"cols": DEFENSE_COLS, "teams": dict(sorted(out.items()))}


PRACTICE = {"Did Not Participate In Practice": "DNP", "Limited Participation in Practice": "LP", "Full Participation in Practice": "FP"}
INJURY_COLS = ["name", "pos", "sid", "status", "practice", "injury", "wed", "thu", "fri"]
DAY_OF_RUN = {2: "wed", 3: "thu", 4: "fri", 5: "fri", 6: "fri", 0: "fri"}   # Monday=0 ... Tuesday (1): new week, no report yet


def practice_day(now=None):
    from zoneinfo import ZoneInfo
    now = now or datetime.now(ZoneInfo("America/New_York"))
    return DAY_OF_RUN.get(now.weekday())


def injuries(season, ids, src=INJ_URL, prev=None, day=None):
    """The latest regular-season week's report: per team, everyone listed (game status, latest practice status,
    injury) plus practice status by day, carried over from prev (the last file's injuries) for the same week."""
    d = pd.read_csv(src.format(season), low_memory=False)
    d = d[d.season_type == "REG"]
    if not len(d):
        return None
    wk = int(d.week.max())
    d = d[d.week == wk]
    old = {}
    if prev and prev.get("week") == wk and "wed" in prev.get("cols", []):
        c = prev["cols"]
        for t, rows in prev.get("teams", {}).items():
            for r in rows:
                old[(t, r[c.index("name")])] = {k: r[c.index(k)] for k in ("wed", "thu", "fri")}
    teams = {}
    for r in d.itertuples():
        inj = r.report_primary_injury if isinstance(r.report_primary_injury, str) else r.practice_primary_injury
        tm, prac = team(r.team), PRACTICE.get(r.practice_status) if isinstance(r.practice_status, str) else None
        days = dict(old.get((tm, r.full_name), {"wed": None, "thu": None, "fri": None}))
        if day and prac:
            days[day] = prac
        teams.setdefault(tm, []).append([
            r.full_name, r.position, ids.get(r.gsis_id) if isinstance(r.gsis_id, str) else None,
            r.report_status if isinstance(r.report_status, str) else None, prac,
            inj if isinstance(inj, str) else None, days["wed"], days["thu"], days["fri"]])
    return {"week": wk, "cols": INJURY_COLS, "teams": dict(sorted(teams.items()))}


def optional(label, fn, *args):
    try:
        return fn(*args)
    except Exception as e:   # matchup extras never block the stats file
        print(f"  {label} skipped: {e}")
        return None


def build(season, ids, games, stats_src=STATS_URL, pbp_src=PBP_URL, inj_src=INJ_URL, prev=None):
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
        "schedule_cols": SCHEDULE_COLS,
        "schedule": schedule(games, season),
        "defense": optional("defense", defense, season, pbp_src),
        "injuries": optional("injuries", injuries, season, ids, inj_src, (prev or {}).get("injuries"), practice_day()),
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
        path = os.path.join(out_dir, f"{s}.json")
        try:
            with open(path) as f:
                prev = json.load(f)
        except (OSError, ValueError):
            prev = None
        data = build(s, ids, games, stats_src, os.environ.get("PBP_SRC", PBP_URL), os.environ.get("INJ_SRC", INJ_URL), prev)
        with open(path, "w") as f:
            json.dump(data, f, separators=(",", ":"))
        print(f"{s}: {len(data['players'])} players through week {data['through_week']}, "
              f"{os.path.getsize(path) / 1024:.0f} KB")
