"""Keep the AM Board's NFL team column in step with Sleeper (Oct 14 valuation audit).

The board's `team` column was written by hand and nothing refreshed it, so players who changed teams kept their
old one (J.J. McCarthy MIN -> NYG, Mike Washington Jr. MIN -> LV): wrong logos, wrong game lines, and roles from the
depth chart that didn't apply. This updates ONLY that column, matched by Sleeper ID (never by name), from Sleeper's
player database that build_depth_charts.py already fetches. Rank, position rank, tier, value, source and tier name
are never touched, so static_check --frozen-rankings still guards the scheduled run.

Rules: a player Sleeper lists without a team becomes FA; a player Sleeper doesn't know keeps his team; a team code
must be 2-3 capital letters; more than MAX_MOVES changes in one run is treated as a bad response and nothing is written.

Use: from build_depth_charts.py --board ../index.html, or  python sync_teams.py <players.json> <index.html>
"""
import json, re, sys

MAX_MOVES = 25
BLOCK = re.compile(r"(const RANKINGS_CSV = `\n)([\s\S]*?)(\n`;)")
TEAM = re.compile(r"^[A-Z]{2,3}$")


def split_csv(line):
    out, cur, q = [], "", False
    for ch in line:
        if ch == '"': q = not q; cur += ch
        elif ch == "," and not q: out.append(cur); cur = ""
        else: cur += ch
    out.append(cur)
    return out


def sync(html, players):
    """Returns (new_html, [(name, old, new)]). Raises ValueError on anything unexpected."""
    m = BLOCK.search(html)
    if not m or len(BLOCK.findall(html)) != 1:
        raise ValueError("expected exactly one RANKINGS_CSV block")
    lines = m.group(2).split("\n")
    cols = split_csv(lines[0])
    ti, si, ni = cols.index("team"), cols.index("sleeper_id"), cols.index("player")
    moves = []
    for k in range(1, len(lines)):
        if not lines[k].strip():
            continue
        row = split_csv(lines[k])
        p = players.get(row[si]) if row[si] else None
        if not isinstance(p, dict):
            continue
        new = p.get("team") or "FA"
        if not TEAM.match(new) or new == row[ti]:
            continue
        moves.append((row[ni], row[ti], new))
        row[ti] = new
        lines[k] = ",".join(row)
    if len(moves) > MAX_MOVES:
        raise ValueError(f"{len(moves)} team changes in one run (limit {MAX_MOVES}): not trusting this response")
    return html[:m.start(2)] + "\n".join(lines) + html[m.end(2):], moves


def apply(path, players):
    html = open(path, encoding="utf-8").read()
    new, moves = sync(html, players)
    if moves:
        with open(path, "w", encoding="utf-8") as f:
            f.write(new)
    for n, a, b in moves:
        print(f"Team updated from Sleeper: {n} {a} -> {b}")
    print(f"Board teams: {len(moves)} change(s)")
    return moves


if __name__ == "__main__":
    apply(sys.argv[2], json.load(open(sys.argv[1])))
