# Design consistency pass: Oct 12, 2026

This pass covers the six recommendations Alan approved from the Oct 12 site audit (`design-audit-2026-10-12.md`). It is a draft PR and won't be merged without Alan's approval. Before/after screenshots are in `design-consistency-2026-10-12/`.

Every screenshot was taken locally with a mock league and a frozen clock. The container can't reach Adobe Fonts, the Sleeper photo CDN or ESPN logos, so the screenshots show Arial, initials and abbreviations.

## What changed

1. **Shared components.** One token set for tags, pills and labels (`--tag-r`, `--tag-fs`, `--tag-fs-caps`, `--tag-ls-caps`, `--tag-pad`, `--eyebrow-*`, `--micro-fs`), plus four families:
   - box tags
   - filled pills
   - outline caps pills
   - micro-labels and eyebrows

   The Trade Finder's mode switch and the calculator's lens now use the same segmented switch as AM Board / League-adjusted. Focus rings are the neutral `--focus-ring` everywhere. Class names and identity are unchanged.
2. **Neutral calculator verdict.** The headline is now heading color. A small dot carries the outcome: the winning side's color, or a hollow ring for an even trade.
3. **Drawer key figures.** There are now two equal blocks: **AM rank + value** (what he's worth) and **ROS PPG** (what he'll produce). Season PPG, Total, Healthy PPG and the production ranks sit on one quieter line under them. The design doesn't put projections first.
4. **One meaning for ▲/▼.** The arrows now always mean movement over time. In League-adjusted view, the board reference is a labelled "AM #12" / "AM WR5", not an arrow.
5. **Desktop columns.** The position + tier column is a fixed 140px next to the value. The player column takes the spare width. The gap from tier to value was about 350px at 1440px and is now 140px. Rows stay 59px.
6. **Waiver Wire.** I benchmarked it first:
   - The table never has more than about 260 rows.
   - Scrolling drops 0 frames, even at a 4× CPU throttle.
   - The cost is script work, not DOM size.

   So there's no pagination and no virtualization. I fixed the actual slow spot (kickoff formatting and grade memoization in the sort): the matchup sort went from 208 to 56 ms for 115 rows, and from 1,151 to 528 ms for 223 rows at 4× CPU.

I also added `PRODUCT.md` (Impeccable init: users, purpose, positioning, constraints, principles) and `DESIGN.md` (tokens, components, do's and don'ts). Neither contains credentials or secrets.

## Impeccable critique

The critique had two isolated assessments.

**A: design review on rendered screenshots** (both themes; 1440, 1280, 1024, 390 and 375px).

- **Strengths:**
  - The drawer's two equal key figures read as "worth" and "production" side by side.
  - "AM #N" is clearer than an arrow that meant two things.
  - The unified switches.
  - A calmer verdict.
- **Fixed after review:**
  - The finder switch wrapped awkwardly. It's now one row from 1280px and wraps below.
  - "AM #N" clipped on phones. It now wraps.
  - The tier/value gap was still wide. It's 140px now.
  - Switch and verdict weights matched the Three Weights rule.

**B: detector and browser evidence** (`impeccable detect` static and URL mode, plus a computed-style scan of 80 screens each).

- No regressions in page overflow, off-screen elements, small targets or contrast.
- The red verdict's contrast failure on dark phones is gone.
- Two trade-setup labels grew.
- The detector's new `design-system-*` findings (63) come from adding `DESIGN.md`. They are existing drift between the CSS and the newly documented ramp, not regressions. They're backlog.
- The "AM #N" reference was the smallest text on the board (9.3px). It's now 0.64rem.
- Unchanged and documented: the small uppercase density labels, the team-color strip, the striped partial-projection bar, and the lifted Trade Finder cards.

## Open questions for Alan

- **Verdict dot color.** Side A's dot is always red and side B's is gray, whoever reads the sentence. Keep it, or make both neutral and rely on the sentence?
- **"Mgr:" on phones** (shipped in PR #22) adds about 30px. Long manager names now truncate a few characters sooner, and the full name is in the tooltip.
- **Tier → value gap.** 140px at 1440px. Tighter is possible, but the tier text starts to crowd the value at 1280px.
