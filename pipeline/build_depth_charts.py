"""NFL depth charts for the player pages' Depth Chart tab, from Sleeper's player database.

Sleeper's documented, keyless /players/nfl endpoint carries each player's depth chart slot
(depth_chart_position: QB, RB, LWR, RWR, SWR, TE, LT ... LCB, FS, K ...) and order (1 = starter),
plus his injury status. Sleeper asks callers to fetch it at most about once a day, and it's ~5 MB,
so the browser never calls it: this job (run with every stats refresh) writes a small file instead.

Writes data/depth_charts.json:
  {"updated": "2026-10-04T15:02Z", "source": "Sleeper",
   "teams": {"KC": {"QB": [[sleeper_id, name, pos, injury_status], ...], "LWR": [...], ...}}}
Each list is in depth order (starter first). Only players Sleeper lists on a team's depth chart.

Run from the pipeline folder: python build_depth_charts.py [out_path]
"""
import json, os, sys, time, urllib.request
from datetime import datetime, timezone

URL = "https://api.sleeper.app/v1/players/nfl"
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join("..", "data", "depth_charts.json")


def fetch(url, tries=3):
    for k in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "SPAM fantasy depth charts (github.com/spamfantasy)"})
            with urllib.request.urlopen(req, timeout=90) as r:
                return json.load(r)
        except Exception as e:  # network hiccup: retry, then give up without touching the old file
            if k == tries - 1:
                raise
            print("retrying after", e)
            time.sleep(5 * (k + 1))


def build(players):
    teams = {}
    for sid, p in (players or {}).items():
        if not isinstance(p, dict):
            continue
        team, slot, order = p.get("team"), p.get("depth_chart_position"), p.get("depth_chart_order")
        if not team or not slot or order is None:
            continue
        try:
            order = int(order)
        except (TypeError, ValueError):
            continue
        name = p.get("full_name") or " ".join(x for x in (p.get("first_name"), p.get("last_name")) if x)
        if not name:
            continue
        pos = p.get("position") or ""
        inj = p.get("injury_status") or ("IR" if p.get("status") == "Injured Reserve" else "")
        teams.setdefault(team, {}).setdefault(str(slot), []).append((order, name, [str(sid), name, pos, inj or ""]))
    out = {}
    for team in sorted(teams):
        out[team] = {slot: [row for _, _, row in sorted(lst, key=lambda x: (x[0], x[1]))] for slot, lst in sorted(teams[team].items())}
    return out


def main():
    players = fetch(URL)
    teams = build(players)
    if len(teams) < 30:   # a broken or partial response: keep the last good file
        sys.exit(f"Only {len(teams)} teams with depth charts; not writing {OUT}")
    data = {"updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"), "source": "Sleeper", "teams": teams}
    with open(OUT, "w") as f:
        json.dump(data, f, separators=(",", ":"))
    print(f"Wrote {OUT}: {len(teams)} teams, {sum(len(v) for t in teams.values() for v in t.values())} players")


if __name__ == "__main__":
    main()
