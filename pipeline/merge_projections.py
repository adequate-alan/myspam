"""Write proj_ppg, proj_score and games columns from projections.csv into the site's RANKINGS_CSV
(only when someone asks: those columns feed the value model, so they change values), or, with --json, write
data/projections.json for weekly points projections only, leaving the rankings untouched (the weekly default).
Players are matched on position + a normalized name (case, punctuation and
Jr./Sr./II/III ignored). ALIASES covers spellings that still differ."""
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


def merge(site_path, proj_path="projections.csv"):
    proj = pd.read_csv(proj_path)
    proj["key"] = proj.player_display_name.map(norm)
    look = {(r.key, r.position): r for r in proj.itertuples()}
    s = open(site_path).read()
    m = re.search(r"const RANKINGS_CSV = `\n(.*?)\n`;", s, re.S)
    lines = m.group(1).splitlines()
    head = next(csv.reader([lines[0]]))
    head = [h for h in head if h != "proj_rank"]
    for col in ("proj_ppg", "proj_score", "games"):
        if col not in head: head.append(col)
    ip, ir, ig = head.index("proj_ppg"), head.index("proj_score"), head.index("games")
    old_head = next(csv.reader([lines[0]]))
    out, missing = [_row(head)], []
    for l in lines[1:]:
        row = dict(zip(old_head, next(csv.reader([l]))))
        c = [row.get(h, "") for h in head]
        r = look.get((norm(ALIASES.get(c[0], c[0])), c[1]))
        c[ip], c[ir], c[ig] = (f"{r.proj_ppg:.2f}", f"{r.rank_score:.2f}", str(int(r.games))) if r is not None else ("", "", "")
        if r is None: missing.append(f"{c[1]} {c[0]}")
        out.append(_row(c[:len(head)]))
    s = s[:m.start(1)] + "\n".join(out) + s[m.end(1):]
    open(site_path, "w").write(s)
    return missing

def write_json(site_path, out_path, proj_path="projections.csv"):
    """Weekly projections for the browser (keyed by Sleeper ID): never touches RANKINGS_CSV, so values can't move."""
    import json, datetime
    proj = pd.read_csv(proj_path)
    proj["key"] = proj.player_display_name.map(norm)
    look = {(r.key, r.position): r for r in proj.itertuples()}
    s = open(site_path).read()
    lines = re.search(r"const RANKINGS_CSV = `\n(.*?)\n`;", s, re.S).group(1).splitlines()
    head = next(csv.reader([lines[0]])); out, missing = {}, []
    for l in lines[1:]:
        row = dict(zip(head, next(csv.reader([l]))))
        r = look.get((norm(ALIASES.get(row["player"], row["player"])), row["pos"]))
        if r is not None and row.get("sleeper_id"): out[row["sleeper_id"]] = round(float(r.proj_ppg), 2)
        elif r is None: missing.append(f'{row["pos"]} {row["player"]}')
    json.dump({"updated": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%MZ"), "ppg": out}, open(out_path, "w"), separators=(",", ":"))
    return missing

if __name__ == "__main__":
    if len(sys.argv) > 3 and sys.argv[2] == "--json":
        print("no projection:", write_json(sys.argv[1], sys.argv[3]))
    else:
        print("no projection (rank-only):", merge(sys.argv[1]))
