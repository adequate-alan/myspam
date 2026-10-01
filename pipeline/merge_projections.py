"""Write proj_ppg, proj_score and games columns from projections.csv into the site's RANKINGS_CSV.
Players are matched on position + a normalized name (case, punctuation and
Jr./Sr./II/III ignored). ALIASES covers spellings that still differ."""
import re, sys, pandas as pd
from project_players import norm

ALIASES = {
    "Kaliff Raymond": "Kalif Raymond",
    "Jacorey Croskey-Merritt": "Jacory Croskey-Merritt",
    "Emmet Johnson": "Emmett Johnson",
    "Tyler Allegier": "Tyler Allgeier",
    "Oronde Gasden": "Oronde Gadsden II",
}

def merge(site_path, proj_path="projections.csv"):
    proj = pd.read_csv(proj_path)
    proj["key"] = proj.player_display_name.map(norm)
    look = {(r.key, r.position): r for r in proj.itertuples()}
    s = open(site_path).read()
    m = re.search(r"const RANKINGS_CSV = `\n(.*?)\n`;", s, re.S)
    lines = m.group(1).splitlines()
    head = lines[0].split(",")
    head = [h for h in head if h != "proj_rank"]
    for col in ("proj_ppg", "proj_score", "games"):
        if col not in head: head.append(col)
    ip, ir, ig = head.index("proj_ppg"), head.index("proj_score"), head.index("games")
    old_head = lines[0].split(",")
    out, missing = [",".join(head)], []
    for l in lines[1:]:
        row = dict(zip(old_head, l.split(",")))
        c = [row.get(h, "") for h in head]
        r = look.get((norm(ALIASES.get(c[0], c[0])), c[1]))
        c[ip], c[ir], c[ig] = (f"{r.proj_ppg:.2f}", f"{r.rank_score:.2f}", str(int(r.games))) if r is not None else ("", "", "")
        if r is None: missing.append(f"{c[1]} {c[0]}")
        out.append(",".join(c[:len(head)]))
    s = s[:m.start(1)] + "\n".join(out) + s[m.end(1):]
    open(site_path, "w").write(s)
    return missing

if __name__ == "__main__":
    print("no projection (rank-only):", merge(sys.argv[1]))
