"""Write the ROS projections (projections.csv from project_players.py) into the site.

    python3 merge_projections.py ../index.html                              → proj_ppg, proj_score, games columns of RANKINGS_CSV
    python3 merge_projections.py ../index.html --json ../data/projections.json → data/projections.json for the browser

Players are matched on Sleeper ID; rows without one fall back to position + normalized name (ALIASES for spellings
that still differ). The JSON carries `ppg` (ROS PPG by Sleeper ID, what the site's weekly projections and the
ROS PPG line read) and `f` (the model's factors per player: [games of evidence, role xPPG, efficiency, environment,
schedule, healthy PPG], all in the site's base scoring; the drawer's "why" line and confidence tag read them)."""
import csv, io, re, sys, pandas as pd
from project_players import norm

ALIASES = {
    "Kaliff Raymond": "Kalif Raymond",
    "Jacorey Croskey-Merritt": "Jacory Croskey-Merritt",
    "Emmet Johnson": "Emmett Johnson",
    "Tyler Allegier": "Tyler Allgeier",
    "Oronde Gasden": "Oronde Gadsden II",
    "Bhaysul Tuten": "Bhayshul Tuten",
    "Travis Ettienne Jr.": "Travis Etienne",
    "Rashod Batemen": "Rashod Bateman",
}

def _row(cells):
    """One CSV line, quoting cells with commas or quotes (custom tier names can have them)."""
    b = io.StringIO(); csv.writer(b, lineterminator="").writerow(cells); return b.getvalue()

def _lookup(proj_path):
    proj = pd.read_csv(proj_path, dtype={"sleeper_id": str})
    by_id = {str(r.sleeper_id): r for r in proj.itertuples()}
    by_name = {(norm(r.player), r.pos): r for r in proj.itertuples()}
    def find(row):
        r = by_id.get(str(row.get("sleeper_id") or ""))
        return r if r is not None else by_name.get((norm(ALIASES.get(row["player"], row["player"])), row["pos"]))
    return find

def _rankings(site_path):
    s = open(site_path).read()
    m = re.search(r"const RANKINGS_CSV = `\n(.*?)\n`;", s, re.S)
    return s, m, m.group(1).splitlines()

def merge(site_path, proj_path="projections.csv"):
    find = _lookup(proj_path)
    s, m, lines = _rankings(site_path)
    old_head = next(csv.reader([lines[0]]))
    head = [h for h in old_head if h != "proj_rank"]
    for col in ("proj_ppg", "proj_score", "games"):
        if col not in head: head.append(col)
    ip, ir, ig = head.index("proj_ppg"), head.index("proj_score"), head.index("games")
    out, missing = [_row(head)], []
    for l in lines[1:]:
        row = dict(zip(old_head, next(csv.reader([l]))))
        c = [row.get(h, "") for h in head]
        r = find(row)
        c[ip], c[ir], c[ig] = (f"{r.proj_ppg:.2f}", f"{r.rank_score:.2f}", str(int(r.games))) if r is not None else ("", "", "")
        if r is None: missing.append(f"{c[1]} {c[0]}")
        out.append(_row(c[:len(head)]))
    s = s[:m.start(1)] + "\n".join(out) + s[m.end(1):]
    open(site_path, "w").write(s)
    return missing

def write_json(site_path, out_path, proj_path="projections.csv"):
    """ROS projections for the browser (keyed by Sleeper ID): never touches RANKINGS_CSV, so values can't move."""
    import json, datetime
    find = _lookup(proj_path)
    _, _, lines = _rankings(site_path)
    head = next(csv.reader([lines[0]])); ppg, f, missing = {}, {}, []
    for l in lines[1:]:
        row = dict(zip(head, next(csv.reader([l]))))
        r = find(row)
        if r is not None and row.get("sleeper_id"):
            ppg[row["sleeper_id"]] = round(float(r.proj_ppg), 2)
            f[row["sleeper_id"]] = [round(float(r.g_eff), 2), round(float(r.role_x), 2), round(float(r.eff), 3),
                                    round(float(r.env), 3), round(float(r.sched), 3), round(float(r.healthy_ppg), 2)]
        elif r is None: missing.append(f'{row["pos"]} {row["player"]}')
    json.dump({"updated": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%MZ"), "ppg": ppg, "f": f},
              open(out_path, "w"), separators=(",", ":"))
    return missing

if __name__ == "__main__":
    if len(sys.argv) > 3 and sys.argv[2] == "--json":
        print("no projection:", write_json(sys.argv[1], sys.argv[3]))
    else:
        print("no projection (rank-only):", merge(sys.argv[1]))
