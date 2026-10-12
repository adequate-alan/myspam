"""Write data/roles.json: who is expected to play each team's next game and later weeks (roles.py).

Reads data/stats/<season>.json (schedule, snaps, injury report), the previous season's stats (established starters)
and data/depth_charts.json (Sleeper depth order and designations), so it runs after build_stats.py and
build_depth_charts.py in every stats refresh. Output, keyed by Sleeper ID:
  {"updated", "season", "source", "note",
   "players": {sid: [n, l, s, sl, depth, status, team, week, fresh]}}
n / l = expected-points multiplier for his team's next game / later weeks; s / sl = chance to start (quarterbacks,
null otherwise); depth = place on his team's depth chart at his position; status = designation used (or null);
week = his team's next game; fresh = 1 when that game's injury report is out (else the status is last week's).
The browser multiplies the conditional projection by n or l (contextProjection).

    python3 build_roles.py [season]
"""
import json, os, sys
from datetime import datetime, timezone
import roles

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data")


def load(path):
    try:
        return json.load(open(path))
    except (OSError, ValueError):
        return None


def build(season):
    stats = load(os.path.join(DATA, "stats", f"{season}.json"))
    depth = load(os.path.join(DATA, "depth_charts.json"))
    prior = load(os.path.join(DATA, "stats", f"{season - 1}.json"))
    if not stats or not depth or len(depth.get("teams") or {}) < 30:
        sys.exit("Stats or depth charts missing; data/roles.json not written (the site falls back to no role adjustment)")
    R = roles.team_roles(stats, depth, prior)
    r3 = lambda v: None if v is None else round(v, 3)
    players = {sid: [r3(r["n"]), r3(r["l"]), r3(r["s"]), r3(r["sl"]), r["depth"], r["status"], r["team"], r["week"], int(r["fresh"])] for sid, r in sorted(R.items())}
    return {"updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"), "season": season,
            "source": f"Sleeper depth charts ({depth.get('updated')}) + injury report (week {(stats.get('injuries') or {}).get('week')})",
            "note": "Expected-points multipliers: n = next game, l = later weeks; s / sl = chance to start (QB). See pipeline/roles.py.",
            "players": players}


if __name__ == "__main__":
    season = int(sys.argv[1]) if len(sys.argv) > 1 else 2026
    out = build(season)
    path = os.path.join(DATA, "roles.json")
    with open(path, "w") as f:
        json.dump(out, f, separators=(",", ":"))
    print(f"Wrote {path}: {len(out['players'])} players")
