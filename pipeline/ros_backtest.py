"""Backtest for ros_model.py: project from weeks 2, 3, 4, 6, 8 and 10 of 2024 and 2025 and score against what each
player actually averaged in his healthy games over the rest of the fantasy season (weeks cutoff+1..17), against
simple baselines. League rates are fitted on the *other* season, team ratings only on games through the cutoff and
no future betting lines are used, so nothing from after the cutoff leaks in. 2025 cases have a previous season
(2024) as the prior; 2024 cases have none (the stats files start in 2024), which shows what the prior is worth.

    python3 ros_backtest.py <games.csv> [--grid]

Players scored: at least 1 game of evidence before the cutoff and 4 healthy games after it, among the fantasy-relevant
pool (top 32 QB / 50 RB / 70 WR / 24 TE by pre-cutoff healthy PPG, or by prior-season PPG at week 2-3).
Metrics: mean absolute error (PPG) and the mean within-position Spearman rank correlation; since Oct 13 also, by
segment (role changes vs last season, team changes, position, week), the bias and the error of the projected main
opportunity per game, for the model before the per-stat prior weights (K_PRIOR 2) and now, and now with the prior
weights fitted on the other half of the players (split-half: no case is scored with weights fitted on its own player).
"""
import sys, json
import numpy as np, pandas as pd
import ros_model as m

SEASONS = [2024, 2025]
CUTOFFS = [2, 3, 4, 6, 8, 10]
POOL = {"QB": 32, "RB": 50, "WR": 70, "TE": 24}

def targets(d, cutoff):
    fut = d[(d.week > cutoff) & (d.week <= m.LAST_WEEK) & (d.f >= 1)]
    t = fut.groupby("id").agg(target=("pts", "mean"), n_after=("pts", "size"))
    n4 = fut[fut.week <= cutoff + m.NEXT_N].groupby("id").agg(target4=("pts", "mean"), n4=("pts", "size"))
    return t[t.n_after >= 4].join(n4)

def baselines(d, cutoff):
    past = d[d.week <= cutoff].sort_values("week"); g = past.groupby("id")
    return pd.DataFrame({"season_ppg": g.pts.mean(), "healthy_ppg": past[past.f >= 1].groupby("id").pts.mean(),
                         "last3_ppg": g.apply(lambda s: s.pts.tail(3).mean(), include_groups=False)})

def spearman(a, b):
    return pd.Series(a).rank().corr(pd.Series(b).rank())

def score(pred, ev):
    j = ev.join(pred.rename("pred"), how="inner").dropna(subset=["pred"])
    mae = (j.pred - j.target).abs().mean()
    rho = np.mean([spearman(s.pred, s.target) for _, s in j.groupby("pos") if len(s) > 5])
    return mae, rho, len(j)

def build_cases(games_path, kw=None):
    games = pd.read_csv(games_path); sc = m.scoring()
    stats = {y: m.load_stats(f"../data/stats/{y}.json") for y in SEASONS}
    frames = {y: m.frame(stats[y], sc) for y in SEASONS}
    rates = {y: m.league_rates([frames[o] for o in SEASONS if o != y]) for y in SEASONS}
    # prior weights from the one pair of complete seasons we have (2024 -> 2025): the same constants the live model
    # uses. They're estimated from season-to-season variance, not from these cases' outcomes; split_half() re-estimates
    # them on half the players and scores the other half, so no case is scored with weights fitted on its own player
    kw = kw if kw is not None else m.prior_weights(frames[2024], frames[2025])
    cases = []
    for y in SEASONS:
        prior = stats.get(y - 1)
        for c in CUTOFFS:
            d = frames[y]
            ctx = m.prepare(stats[y], games, c, prior_stats=prior, rates=rates[y], use_future_lines=False, sc=sc, kw=kw)
            ev = targets(d, c).join(baselines(d, c)).join(d.groupby("id").pos.first())
            ev = ev[ev.index.isin(set(g["sid"] for g in ctx["groups"]))]
            pool_by = ev.healthy_ppg.fillna(ev.season_ppg)
            if prior and c <= 3:   # at week 2-3 the pool is the previous season's regulars plus this season's early leaders
                pp = frames[y - 1].groupby("id").pts.mean()
                pool_by = pd.concat([pool_by, pp.reindex(ev.index)], axis=1).max(axis=1)
            ev["pool_rank"] = pool_by.groupby(ev.pos).rank(ascending=False)
            ev = ev[ev.pool_rank <= ev.pos.map(POOL)]
            ctx["future_frame"] = d[(d.week > c) & (d.week <= m.LAST_WEEK) & (d.f >= 1)]
            cases.append((y, c, ctx, ev))
    return cases

def evaluate(cases, params, seasons=None, cutoffs=None, horizon="ros"):
    """horizon "ros": proj_ppg vs the rest-of-season healthy PPG; "n4": n4_ppg vs the healthy PPG of the next 4 weeks (3+ games)."""
    maes, rhos, ns = [], [], []
    for y, c, ctx, ev in cases:
        if (seasons and y not in seasons) or (cutoffs and c not in cutoffs): continue
        if horizon == "n4": ev = ev[ev.n4 >= 3].assign(target=lambda e: e.target4)
        out = m.project_from(ctx, params).set_index("sleeper_id")[("n4_ppg" if horizon == "n4" else "proj_ppg")]
        mae, rho, n = score(out, ev); maes.append(mae); rhos.append(rho); ns.append(n)
    return np.mean(maes), np.mean(rhos), sum(ns)

OLD = dict(m.PARAMS, K_PRIOR=2.0)   # the model before Oct 13: one prior weight (2 games) for every opportunity stat

def main_vol(x, pos):
    """A position's main opportunity per game (KW_MAIN summed): QB dropbacks + carries, RB carries + targets, WR / TE targets."""
    return sum(x[o] for o in m.KW_MAIN[pos])

def segment_rows(cases, params, project=None):
    """One row per scored case: projected and actual ROS PPG and main opportunity, last season's and this season's
    pre-cutoff opportunity, whether he changed teams. `project` swaps in another project_from (split_half)."""
    project = project or m.project_from
    rows = []
    for y, c, ctx, ev in cases:
        out = project(ctx, params).set_index("sleeper_id")
        fut = ctx["future_frame"]
        for g in ctx["groups"]:
            sid = g["sid"]
            if sid not in ev.index or sid not in out.index: continue
            pos, pr = g["pos"], g["prior"]
            cur = np.average(main_vol({o: g["opps"][o] / g["rf"] for o in m.OPPS}, pos), weights=g["rf"])
            f = fut[fut.id == sid]
            rows.append(dict(y=y, c=c, sid=sid, pos=pos, cur=cur, prior=(main_vol(pr["opps"], pos) if pr and pr["g"] >= 4 else np.nan),
                             moved=bool(pr and pr.get("team") and pr["team"] != g["team"]), proj=out.loc[sid, "proj_ppg"], target=ev.loc[sid, "target"],
                             projv=main_vol(out.loc[sid, "line"], pos), actv=main_vol(f, pos).mean()))
    r = pd.DataFrame(rows); r["err"] = r.proj - r.target; r["verr"] = r.projv - r.actv
    r["lr"] = np.log((r.cur + 1) / (r.prior + 1))
    return r

SEGMENTS = [("all cases", lambda r: r.index == r.index), ("with a previous season", lambda r: r.prior.notna()),
            ("workload up 30%+ vs last season", lambda r: r.lr > np.log(1.3)), ("workload up 50%+", lambda r: r.lr > np.log(1.5)),
            ("workload down 30%+", lambda r: r.lr < -np.log(1.3)), ("workload within 15%", lambda r: r.lr.abs() < np.log(1.15)),
            ("changed teams", lambda r: r.prior.notna() & r.moved), ("changed teams, workload up 30%+", lambda r: r.moved & (r.lr > np.log(1.3)))] + \
           [(f"with a previous season, {p}", (lambda p: lambda r: r.prior.notna() & (r.pos == p))(p)) for p in m.POS] + \
           [(f"with a previous season, week {c}", (lambda c: lambda r: r.prior.notna() & (r.c == c))(c)) for c in CUTOFFS]

def segment_table(r):
    """{segment: (n, PPG MAE, PPG bias, opportunity MAE, opportunity bias)}; bias = projected - actual."""
    out = {}
    for name, sel in SEGMENTS:
        s = r[sel(r)]
        out[name] = (len(s), s.err.abs().mean(), s.err.mean(), s.verr.abs().mean(), s.verr.mean())
    return out

def split_half(cases, games_frames):
    """project_from with the prior weights fitted on the other half of the players (by Sleeper ID parity)."""
    half = lambda sid: int(sid) % 2 if str(sid).isdigit() else 0
    part = lambda d, h: d[d.id.map(half) == h]
    kws = {h: m.prior_weights(part(games_frames[2024], h), part(games_frames[2025], h)) for h in (0, 1)}
    def project(ctx, params):
        outs = []
        for h in (0, 1):
            c = dict(ctx, kw=kws[1 - h], groups=[g for g in ctx["groups"] if half(g["sid"]) == h])
            outs.append(m.project_from(c, params))
        return pd.concat(outs)
    return project

def compare(cases, frames):
    """The model before Oct 13 against the current one, by segment, plus the current one scored out of sample."""
    tabs = {"before (K 2)": segment_table(segment_rows(cases, OLD)), "now": segment_table(segment_rows(cases, m.PARAMS)),
            "now, split-half": segment_table(segment_rows(cases, m.PARAMS, split_half(cases, frames)))}
    print("prior weighting, before vs now (PPG MAE / bias, main opportunity per game MAE / bias; bias = projected - actual):")
    for name, _ in SEGMENTS:
        n = tabs["now"][name][0]
        print(f"  {name:38s} n {n:4d}  " + "   ".join(f"{k}: {v[name][1]:.3f} / {v[name][2]:+.2f}, opp {v[name][3]:.2f} / {v[name][4]:+.2f}" for k, v in tabs.items()))
    return tabs

def run(games_path, grid=False):
    cases = build_cases(games_path)
    sc = m.scoring(); frames = {y: m.frame(m.load_stats(f"../data/stats/{y}.json"), sc) for y in SEASONS}
    kw = cases[0][2]["kw"]
    print(f"prior weights (2024 -> 2025; games of evidence; a new team: K / {kw['move']:.2f}, level x {kw['lvl']:.3f}):")
    print(pd.DataFrame(kw["K"]).round(2).to_string())
    compare(cases, frames)
    print("baselines (mean over season/cutoff cases):")
    for b in ("season_ppg", "healthy_ppg", "last3_ppg"):
        r = [score(ev[b], ev) for _, _, _, ev in cases]
        print(f"  {b:12s} MAE {np.nanmean([x[0] for x in r]):.3f}  rho {np.nanmean([x[1] for x in r]):.3f}  n {sum(x[2] for x in r)}")
    mae, rho, n = evaluate(cases, m.PARAMS)
    print(f"ros_model (PARAMS) MAE {mae:.3f}  rho {rho:.3f}  n {n}")
    for y in SEASONS:
        for c in CUTOFFS:
            mae, rho, n = evaluate(cases, m.PARAMS, [y], [c]); hb = [score(ev.healthy_ppg, ev) for yy, cc, _, ev in cases if yy == y and cc == c][0]
            print(f"  {y} week {c:2d}: n {n:3d}  model MAE {mae:.2f} rho {rho:.3f}   healthy PPG MAE {hb[0]:.2f} rho {hb[1]:.3f}")
    if grid:
        space = dict(K_PRIOR=[None, 1, 2, 4, 8], K_NOPRIOR=[0.5, 1, 2], PRIOR_EFF_W=[0, 0.5, 1.0], K_EFF=[30, 60, 120, 240],
                     EFF_W=[0.5, 0.75, 1.0], HALF_LIFE=[5, 10, 20, 100], ENV_EL=[0, 0.5, 1.0], SCHED_EL=[0, 0.25, 0.5], PRIOR_GAMES=[0, 0.5, 1])
        best = dict(m.PARAMS); best_mae = evaluate(cases, best)[0]
        for _ in range(2):
            for k, vals in space.items():
                for v in vals:
                    p = dict(best); p[k] = v
                    mae, rho, _ = evaluate(cases, p)
                    print(f"  {k}={str(v):<5} MAE {mae:.3f} rho {rho:.3f}")
                    if mae < best_mae - 1e-4: best_mae, best = mae, p
            print("best so far", {k: best[k] for k in space}, round(best_mae, 3))
        mae, rho, _ = evaluate(cases, best)
        print("BEST", json.dumps({k: best[k] for k in space}), f"MAE {mae:.3f} rho {rho:.3f}")
    # the next-4 outlook: its own environment / schedule strength against the healthy PPG of the next four weeks
    print("next 4 (n4_ppg vs the next 4 weeks' healthy PPG):")
    for e in (0, 0.5, 1.0):
        for sc_ in (0, 0.25, 0.5, 1.0):
            p = dict(m.PARAMS); p["ENV4_EL"] = e; p["SCHED4_EL"] = sc_
            mae, rho, n = evaluate(cases, p, horizon="n4")
            print(f"  ENV4_EL={e} SCHED4_EL={sc_}: MAE {mae:.3f} rho {rho:.3f} n {n}")
    hb = [score(ev[ev.n4 >= 3].assign(target=lambda e: e.target4).healthy_ppg, ev[ev.n4 >= 3].assign(target=lambda e: e.target4)) for _, _, _, ev in cases]
    print(f"  healthy PPG baseline: MAE {np.nanmean([x[0] for x in hb]):.3f} rho {np.nanmean([x[1] for x in hb]):.3f}")

if __name__ == "__main__":
    run(sys.argv[1], grid="--grid" in sys.argv)
