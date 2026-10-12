# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

- **Primary:** serious redraft fantasy football players (confirmed by Alan, Oct 12, 2026).
  - They are engaged managers who connect their own Sleeper league, or import an ESPN or Yahoo one.
  - They come to Adequate to decide something: start or sit, who to pick up, what to offer in a trade, whether a trade they made was fair.
  - They check in during the week and on game days, on desktop and on phones.
  - They read dense tables comfortably and expect expert tooling, not onboarding.
- **Owner:** Alan (GitHub `adequate-alan`). He maintains the AM Board and is the only one who publishes rankings.

## Product Purpose

Adequate is a fantasy football rankings, values and trade-tools site.

- **Core: the AM Board.** These are Alan's manual rankings, tiers and published values. The base format is 12-team, Full PPR, Superflex, TE premium +0.5, redraft.
- **Derived from the AM Board:**
  - League-adjusted values for any format.
  - Trade verdicts.
  - Power rankings.
  - The Trade Finder.
  - Waiver advice.
  - Player pages.

Success means two things:
- A manager can answer "what is this player worth, and what will he produce" for their own league in seconds.
- They trust the answer because every number shows where it came from.

## Positioning

The site is a single expert's conviction board, made portable to any league:
- The rankings are Alan's, never re-derived by a formula.
- Every league-specific number is a transparent derivation of them.
- Market sources (FantasyCalc, Flock) sit beside AM as a disagreement layer. They are never blended into AM.

Adequate is fundamentally a rankings and valuation platform, not a projections-first site (Alan, Oct 12). Projections (ROS PPG, Next 4, weekly) matter and are shown prominently, but they sit beside the ranking and value, never above them.

## Operating Context

- **Weekly workflow:**
  - Rankings can change any day Alan publishes.
  - Projections and stats refresh on a schedule (Tuesdays, plus game-day stats runs).
  - Market values refresh every 8 hours.
- **Where the work happens:** visitors work inside their own league's context: My Team, the League hub (Power Rankings, Standings, Matchups, Rosters, Transactions, Waiver Wire), the Trade Finder and the Trade Calculator.
- **Privacy:** league data is fetched and kept in the visitor's browser only.
- **Editing:** Alan edits the board in the site's own editor (drag, arrows, Move to rank, tier tools, value edits). Saving publishes to GitHub.

## Capabilities and Constraints

- **Static site:** one `index.html` (HTML, CSS and JS) plus JSON data, with no build step, framework or npm. It is deployed to GitHub Pages through release lanes; see `CLAUDE.md` §3 and §6.
- **The AM Board is the source of truth.**
  - Derived layers (league adjustment, projections, stats, market) never write back to ranks, tiers or values.
  - Nothing scheduled changes rankings.
- **Two-axis player read:** what AM thinks a player is worth (AM rank, tier, value) and what AM projects him to produce (ROS PPG, Next 4, weekly). Both always visible; neither replaces the other.
- **Terminology:**
  - AM Board, AM rank, AM value, League-adjusted.
  - ROS PPG, Next 4, Wk proj.
  - PPG = actual season PPG; Healthy PPG excludes injury-shortened games.
  - "Market" is reserved for FantasyCalc and Flock.
- **External data:** keyless public sources only (Sleeper, nflverse, FantasyCalc, ESPN logos). There are no API keys or secrets in the site or repo.
- **Undecided:**
  - Real editor authentication (a backend or GitHub App).
  - A player-props provider.
  - Whether the Waiver Wire needs virtualization; it is being benchmarked first.

## Brand Commitments

- **Name and wordmark:** the site is **Adequate**, with the wordmark `ADEQUATE.` (the period is part of the mark). "AM" stays the name of Alan's ranking system.
- **Voice:** understated and plain. Copy uses sentence case, says what was checked, and makes no hype claims.
- **Design brief (Alan, Oct 11):**
  - A sports analytics tool, not a generic SaaS dashboard.
  - Information density, readability, efficient navigation and consistency come first.
  - Make incremental improvements; never redesign without clear justification.
- The visual system is recorded in `DESIGN.md` and in the decisions logged in `CLAUDE.md` §10.

## Evidence on Hand

What exists:
- **Ranking history:** `data/rank_history.json` and exact board snapshots in `data/rank_snapshots/`.
- **Stats:** 2024–2026 seasons in `data/stats/`.
- **Projections:** `data/projections.json` and the stored weekly forecasts in `data/projections/`.
- **Market data:** `data/market/`.
- **Projection backtest:** results in `CLAUDE.md` §8.
- **Design audits:** `docs/design-audit-2026-10-12.md`.

What doesn't exist, and must never be invented:
- testimonials
- user counts
- accuracy claims beyond the backtest
- partnerships or licensing claims

## Product Principles

1. **Rankings first, projections beside them.** Every player view shows his worth (AM rank and value) and his projected production (ROS PPG) as separate, equally clear reads.
2. **Layers stay separate.** Derived, market and projection numbers never overwrite or blur the AM Board, and each is labelled for what it is.
3. **Honest numbers.** A missing number stays missing: no fake zeros, no invented history. Heuristics are labelled as heuristics. Claims say what they are based on.
4. **Built for the expert at speed.** Dense, scannable tables and consistent controls beat explanation and whitespace. Nothing essential hides behind a hover.
5. **Private by default.** A visitor's league stays in their browser.

## Accessibility & Inclusion

- **Contrast:** text meets WCAG AA (4.5:1). Muted text was tuned to it on every main surface (Alan, Oct 11).
- **Themes:** light and dark are both first-class.
- **Keyboard:** every control is usable from the keyboard, and keyboard focus uses a visible neutral ring.
- **Touch:** touch devices get tap equivalents for hover content.
- **Phones (375 px and up):**
  - Nothing essential is hidden or clipped.
  - Data tables may scroll sideways only when nothing essential is off screen.
