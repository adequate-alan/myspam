"""Expected fantasy points (xFP) inputs for the Rankings stat columns: data/opportunity/<season>.json.

Stats data only. Nothing here reads or writes the rankings in index.html.

Source: ffverse's ffopportunity (MIT; https://github.com/ffverse/ffopportunity), weekly expected-points data built from
nflverse play-by-play: for every target, carry and pass attempt, a trained model (xgboost, by down, distance, field
position, air yards, ...) gives the expected catch, yards, first down and touchdown. We keep the expected stat line,
not ffopportunity's points total (that one is in its own default scoring), so the browser scores it with each league's
own settings (gamePoints), exactly like an actual stat line. Rankings shows it as xFP (Alan, Oct 12: "Weighted
Opportunity" only if the data supports a defensible expected-points model; this is that model, not a weighted count).

Per player-week: [week, x_rec, x_rec_yd, x_rec_td, x_rec_fd, x_rush_yd, x_rush_td, x_rush_fd,
                  x_pass_cmp, x_pass_yd, x_pass_td, x_pass_int, x_pass_fd, x_2pt]
Targets, carries and pass attempts are the actual counts (from data/stats). Fumbles and sacks have no expected value in
the source and are left out of xFP; yardage bonuses are not applied to expected yards.
Run from the pipeline folder: python build_opportunity.py 2026
"""
import json, os, sys
from datetime import datetime, timezone
import pandas as pd
from build_stats import sleeper_map, IDS_URL

EP_URL = "https://github.com/ffverse/ffopportunity/releases/download/latest-data/ep_weekly_{}.csv"
COLS = ["w", "x_rec", "x_rec_yd", "x_rec_td", "x_rec_fd", "x_rush_yd", "x_rush_td", "x_rush_fd",
        "x_pass_cmp", "x_pass_yd", "x_pass_td", "x_pass_int", "x_pass_fd", "x_2pt"]
SRC = {"x_rec": ["receptions_exp"], "x_rec_yd": ["rec_yards_gained_exp"], "x_rec_td": ["rec_touchdown_exp"],
       "x_rec_fd": ["rec_first_down_exp"], "x_rush_yd": ["rush_yards_gained_exp"], "x_rush_td": ["rush_touchdown_exp"],
       "x_rush_fd": ["rush_first_down_exp"], "x_pass_cmp": ["pass_completions_exp"], "x_pass_yd": ["pass_yards_gained_exp"],
       "x_pass_td": ["pass_touchdown_exp"], "x_pass_int": ["pass_interception_exp"], "x_pass_fd": ["pass_first_down_exp"],
       "x_2pt": ["pass_two_point_conv_exp", "rec_two_point_conv_exp", "rush_two_point_conv_exp"]}


def build(season, ids, src=EP_URL):
    d = pd.read_csv(src.format(season), low_memory=False)
    d = d[d.position.isin(["QB", "RB", "WR", "TE"])].copy()
    d["sid"] = d.player_id.map(ids)
    d = d[d.sid.notna()].sort_values(["sid", "week"])
    players = {}
    for sid, rows in d.groupby("sid"):
        log = []
        for r in rows.itertuples():
            row = [int(r.week)]
            for k in COLS[1:]:
                v = sum(0 if pd.isna(getattr(r, c, 0)) else float(getattr(r, c, 0)) for c in SRC[k])
                row.append(round(v, 2))
            log.append(row)
        players[sid] = log
    return {"season": season, "through_week": int(d.week.max()) if len(d) else 0,
            "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
            "source": "ffverse/ffopportunity expected points (nflverse play-by-play)", "cols": COLS, "players": players}


if __name__ == "__main__":
    seasons = [int(x) for x in sys.argv[1:]] or [2026]
    here = os.path.dirname(os.path.abspath(__file__))
    out_dir = os.path.join(here, "..", "data", "opportunity")
    os.makedirs(out_dir, exist_ok=True)
    ids = sleeper_map(os.environ.get("IDS_SRC", IDS_URL))
    for s in seasons:
        data = build(s, ids, os.environ.get("EP_SRC", EP_URL))
        path = os.path.join(out_dir, f"{s}.json")
        with open(path, "w") as f:
            json.dump(data, f, separators=(",", ":"))
        print(f"{s}: {len(data['players'])} players through week {data['through_week']}, {os.path.getsize(path) / 1024:.0f} KB")
