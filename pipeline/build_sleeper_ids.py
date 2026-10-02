"""Sleeper player IDs for the site.

1. data/sleeper_players.json: {sleeper_id: [name, position, team, gsis_id, birthdate]}
   for every QB/RB/WR/TE/K with a Sleeper ID, so the site can name any rostered player
   (ranked or not) without calling Sleeper's 5 MB players endpoint. This is the
   player identity table: photos come from Sleeper's CDN by sleeper_id, stats from
   nflverse by gsis_id (see build_stats.py).
2. data/platform_ids.json: ESPN and Yahoo player IDs -> Sleeper IDs (league imports).
3. Adds a sleeper_id column to RANKINGS_CSV in index.html so ranked players can
   be matched to Sleeper rosters. Matching: position + normalized name, with
   ALIASES from merge_projections.py for spellings that differ.

Source: DynastyProcess player ID table (github.com/dynastyprocess/data).
Run from the pipeline folder: python build_sleeper_ids.py [path/to/index.html]
"""
import json, os, re, sys
import pandas as pd
from project_players import norm
from merge_projections import ALIASES

IDS_URL = "https://raw.githubusercontent.com/dynastyprocess/data/master/files/db_playerids.csv"
POS = {"QB": "QB", "RB": "RB", "WR": "WR", "TE": "TE", "PK": "K", "K": "K"}
TEAM_FIX = {"LVR": "LV", "JAC": "JAX", "LAR": "LAR", "KCC": "KC", "GBP": "GB", "NEP": "NE", "NOS": "NO",
            "SFO": "SF", "TBB": "TB", "LA": "LAR", "WSH": "WAS"}


def load_ids(src=IDS_URL):
    d = pd.read_csv(src, low_memory=False)
    d = d[d.sleeper_id.notna() & d.position.isin(POS)].copy()
    d["sleeper_id"] = d.sleeper_id.astype("int64").astype(str)
    d["pos"] = d.position.map(POS)
    d["team"] = d.team.fillna("FA").map(lambda t: TEAM_FIX.get(t, t))
    d["key"] = d.name.map(norm)
    # newest record first when a Sleeper ID appears more than once
    return d.sort_values("db_season", ascending=False).drop_duplicates("sleeper_id")


def write_players(ids, out_path):
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    clean = lambda v: "" if pd.isna(v) else str(v)
    data = {r.sleeper_id: [r.name, r.pos, r.team, clean(r.gsis_id), clean(r.birthdate)] for r in ids.itertuples()}
    with open(out_path, "w") as f:
        json.dump(data, f, separators=(",", ":"))
    return len(data)


def write_platform_ids(ids, out_path):
    """data/platform_ids.json: {"espn": {espn_id: sleeper_id}, "yahoo": {yahoo_id: sleeper_id}}
    so leagues imported from ESPN (and Yahoo, when IDs are available) map to the same players."""
    out = {"espn": {}, "yahoo": {}}
    for col, key in (("espn_id", "espn"), ("yahoo_id", "yahoo")):
        if col not in ids.columns:
            continue
        for r in ids[ids[col].notna()].itertuples():
            out[key][str(int(getattr(r, col)))] = r.sleeper_id
    with open(out_path, "w") as f:
        json.dump(out, f, separators=(",", ":"))
    return {k: len(v) for k, v in out.items()}


def tag_rankings(ids, site_path):
    s = open(site_path).read()
    m = re.search(r"const RANKINGS_CSV = `\n(.*?)\n`;", s, re.S)
    lines = m.group(1).splitlines()
    head = lines[0].split(",")
    if "sleeper_id" not in head:
        head.append("sleeper_id")
    old_head = lines[0].split(",")
    isid = head.index("sleeper_id")
    # prefer players with a real team when names collide
    ids = ids.assign(fa=(ids.team == "FA").astype(int)).sort_values(["fa", "db_season"], ascending=[True, False])
    look = {}
    for r in ids.itertuples():
        look.setdefault((r.key, r.pos), r.sleeper_id)
    out, missing = [",".join(head)], []
    for line in lines[1:]:
        row = dict(zip(old_head, line.split(",")))
        name, pos = row.get("player", ""), row.get("pos", "")
        sid = look.get((norm(ALIASES.get(name, name)), pos), "")
        if not sid:
            missing.append(f"{pos} {name}")
        c = [row.get(h, "") for h in head]
        c[isid] = sid
        out.append(",".join(c))
    s = s[:m.start(1)] + "\n".join(out) + s[m.end(1):]
    open(site_path, "w").write(s)
    return missing


if __name__ == "__main__":
    site = sys.argv[1] if len(sys.argv) > 1 else "../index.html"
    src = sys.argv[2] if len(sys.argv) > 2 else IDS_URL
    here = os.path.dirname(os.path.abspath(__file__))
    ids = load_ids(src)
    n = write_players(ids, os.path.join(here, "..", "data", "sleeper_players.json"))
    plat = write_platform_ids(ids, os.path.join(here, "..", "data", "platform_ids.json"))
    print("platform_ids.json:", plat)
    missing = tag_rankings(ids, site)
    print(f"sleeper_players.json: {n} players")
    print("ranked players without a Sleeper ID:", missing or "none")
