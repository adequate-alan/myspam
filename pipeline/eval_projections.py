"""Score the stored pre-game projections (data/projections/<season>/wk*.json) against what happened, by component,
so the live value of the market and matchup signals is measured on genuinely out-of-sample results.

    python3 eval_projections.py [../data/stats/2026.json] [../data/projections]

For every stored week whose games have been played: the next-game forecast (n1) against that week's actual points, and
the variants recomposed from the stored components: base alone (v2 without market), base × market environment,
base × matchup, base × both; the next-4 forecast against the healthy PPG of the following four weeks once they're
played; the ROS forecast against the healthy PPG of the rest of the season so far. Injury-shortened games are left out
of the targets (the forecast is for a full game). Pool: players with a stored forecast of at least 5 PPG, so the
numbers describe fantasy-relevant players. Prints MAE and rank correlation per variant and per week.
"""
import json, os, sys, glob
import numpy as np, pandas as pd
import ros_model as m

def actuals(stats, sc):
    d = m.frame(stats, sc)
    return d[d.f >= 1][["id", "week", "pts"]]

def spearman(a, b):
    return pd.Series(a).rank().corr(pd.Series(b).rank())

def main(stats_path="../data/stats/2026.json", proj_dir="../data/projections"):
    stats = json.load(open(stats_path)); sc = m.scoring(); act = actuals(stats, sc); through = stats["through_week"]
    files = sorted(glob.glob(os.path.join(proj_dir, str(stats["season"]), "wk*.json")))
    if not files: print("no stored forecasts yet"); return
    rows = []
    for fn in files:
        snap = json.load(open(fn)); wk = snap["week"]
        if wk > through: continue
        a1 = act[act.week == wk].set_index("id").pts
        a4 = act[(act.week >= wk) & (act.week < wk + m.NEXT_N)].groupby("id").pts.agg(["mean", "size"])
        aros = act[act.week >= wk].groupby("id").pts.agg(["mean", "size"])
        for sid, p in snap["players"].items():
            if p["ros"] < 5: continue
            r = dict(week=wk, sid=sid, pos=p["pos"], conf=p["conf"], ros=p["ros"], n4=p["n4"], n1=p["n1"],
                     v_base=p["base"], v_market=p["base"] * p["env1"], v_matchup=p["base"] * p["sched1"], v_both=p["n1"],
                     act1=a1.get(sid), act4=a4["mean"].get(sid) if a4["size"].get(sid, 0) >= 3 else None,
                     actros=aros["mean"].get(sid) if aros["size"].get(sid, 0) >= 3 else None)
            rows.append(r)
    if not rows: print(f"no stored week has been played yet (stats through week {through})"); return
    d = pd.DataFrame(rows)
    def report(pred, truth, label):
        j = d.dropna(subset=[truth])
        if len(j) < 20: return
        mae = (j[pred] - j[truth]).abs().mean(); rho = np.mean([spearman(s[pred], s[truth]) for _, s in j.groupby(["week", "pos"]) if len(s) > 5])
        print(f"  {label:34s} MAE {mae:.2f}  rho {rho:.3f}  n {len(j)}")
    print(f"stored weeks scored: {sorted(d.week.unique().tolist())} (stats through week {through})")
    print("next game:")
    for pred, label in (("v_base", "v2, no market / matchup"), ("v_market", "v2 + team market (implied totals)"), ("v_matchup", "v2 + matchup (defense vs position)"), ("v_both", "v2 + both (the stored next-game forecast)")):
        report(pred, "act1", label)
    print("next 4:"); report("n4", "act4", "next-4 forecast"); report("v_base", "act4", "v2 base alone")
    print("rest of season so far:"); report("ros", "actros", "ROS forecast"); report("v_base", "actros", "v2 base alone")
    print("by confidence (next game):")
    for lo, hi, lab in ((0, 0.4, "low"), (0.4, 0.7, "moderate"), (0.7, 1.01, "high")):
        j = d[(d.conf >= lo) & (d.conf < hi)].dropna(subset=["act1"])
        if len(j) >= 20: print(f"  {lab:10s} MAE {(j.v_both - j.act1).abs().mean():.2f}  n {len(j)}")

if __name__ == "__main__":
    main(*sys.argv[1:])
