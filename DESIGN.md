---
name: Adequate
description: Fantasy football rankings, values and trade tools. A dense, readable analytics board.
colors:
  am-red: "#C83B4B"
  am-red-hover-dark: "#CB4756"
  am-red-hover-light: "#B63342"
  am-red-text-dark: "#EB5F6F"
  am-red-text-light: "#B83443"
  dark-page: "#08090B"
  dark-surface: "#14161B"
  dark-raised: "#1F2228"
  dark-control: "#1A1C22"
  dark-border: "#2B2F36"
  dark-text: "#F6F7F9"
  dark-text-secondary: "#A7ABB3"
  dark-text-muted: "#878D96"
  light-page: "#ECEEF2"
  light-surface: "#FFFFFF"
  light-table-head: "#F7F8FA"
  light-control: "#E3E6EB"
  light-border: "#D2D6DD"
  light-text: "#101114"
  light-text-secondary: "#50545C"
  light-text-muted: "#62676F"
  pos-qb: "#E8735F"
  pos-rb: "#2FB67E"
  pos-wr: "#4F8EE0"
  pos-te: "#9D7FE0"
  pos-flex: "#DDA23C"
  pos-sf: "#D16C8C"
  negative-dark: "#E0806F"
  negative-light: "#A63A2E"
  focus-ring-dark: "#A7ABB3"
  focus-ring-light: "#50545C"
typography:
  wordmark:
    fontFamily: "Archivo, Arial, sans-serif"
    fontWeight: 900
    letterSpacing: "-0.02em"
  title:
    fontFamily: "proxima-nova, Proxima Nova, Arial, sans-serif"
    fontSize: "1.6rem"
    fontWeight: 600
    letterSpacing: "-0.02em"
  body:
    fontFamily: "proxima-nova, Proxima Nova, Arial, sans-serif"
    fontSize: "0.88rem"
    fontWeight: 500
  data:
    fontFamily: "proxima-nova, Proxima Nova, Arial, sans-serif"
    fontWeight: 700
    fontFeature: "tnum"
  label:
    fontFamily: "proxima-nova, Proxima Nova, Arial, sans-serif"
    fontSize: "0.62rem"
    fontWeight: 600
    letterSpacing: "0.09em"
rounded:
  tag: "4px"
  control: "6px"
  md: "8px"
  card: "8px"
  pill: "999px"
spacing:
  row-desktop: "59px"
  row-tablet: "49px"
  row-phone: "43px"
  gutter-phone: "16px"
components:
  button-primary:
    backgroundColor: "{colors.am-red}"
    textColor: "#FFFFFF"
    rounded: "{rounded.control}"
  button-primary-hover:
    backgroundColor: "{colors.am-red-hover}"
  position-badge:
    rounded: "{rounded.tag}"
    height: "22px"
  segmented-button:
    rounded: "{rounded.control}"
    height: "30px"
---

# Design System: Adequate

## Overview

**Creative North Star: "The Scout's Board"** (a working name; rename freely)

Adequate reads like a well-kept board in a scouting room: a single expert's conviction, laid out densely and plainly so a manager can scan, compare and decide fast.
- **The data is the decoration.** Names and numbers carry the weight. Chrome recedes into neutral grays. One brand red marks what is selected, what is yours, and the main action.
- **The board is the hero.** Tables are compact, rows are even, and numbers line up.

These are explicitly rejected:
- the generic SaaS dashboard look (cards in cards, roomy whitespace, gradients, glows, decorative icons)
- a second accent color
- projections-first hierarchy: worth (AM rank and value) and projected production (ROS PPG) are equal reads, side by side

**Key characteristics:**
- Information density with readable type.
- A strong hierarchy built from weight and size, not from boxes.
- Dark is the flagship theme; light is a polished equal with real surface separation.
- Effects are restrained. Transitions run about 90–160 ms and are off under reduced motion.
- Changes are incremental. Never redesign a page without clear justification.

## Colors

The palette has three kinds of color only: AM red, the semantic position colors, and grayscale. Every value lives as a CSS token at the top of `index.html`; never hard-code a color.

### Primary
- **AM Red** (muted crimson #C83B4B since Oct 12, was #E4002B; hover #CB4756 dark / #B63342 light; tokens `--am-red`, `--am-red-hover`, `--am-red-text`). Used for:
  - the active nav underline and every selected state (a red underline on a neutral fill)
  - primary buttons
  - the wordmark period
  - "your team" (`--mine-accent`)
  - the selected player row (a faint wash plus a thin left edge)
  - major calls to action

  Red as *text* never uses the fill: it goes through `--am-red-text` (#EB5F6F dark, #B83443 light; `--mine-text` for your team) or `--st-dnp-text` / `--st-out-text`, so it clears 4.5:1 on every surface. White on the fill is 5.0:1.

### Semantic: positions
These colors are one palette shared by badges, value meters and lineup slots: QB coral #E8735F, RB emerald #2FB67E, WR blue #4F8EE0, TE violet #9D7FE0, FLEX amber #DDA23C, SF rose #D16C8C. Bench, IR and draft picks are gray. Light mode uses deeper versions (QB #C24A38, RB #1A8A5A, WR #2E69BD, TE #6E4CC2, FLEX #A06F17, SF #A8486A).

### Semantic: states
- **Warnings** are amber (`--warn` for fills and edges, `--warn-text` when amber is text: light `#7E5311`), never red.
- **Negatives** (fallers, losing sides, destructive actions) use a softer brick: #E0806F in dark, #A63A2E in light. It never reads as the brand.
- **Strong performances** (the Game Log's weekly finishes) use the RB emerald at low opacity: an elite finish gets a 15% tint (13% light) and the finish in green; a good finish a 10% tint (8% light) with neutral text (`--gl-elite-*` / `--gl-good-bg`). No left edge: an inset edge means yours / selected / current everywhere else. Two levels only, neutral for everything else, never a red or brick background for a bad game.
- **Practice and injury status:** one `--st-*` system covers FP, LP, DNP, Out, Questionable, Doubtful and IR.
- **NFL team colors** are small accents only (strips, edges, a photo ring). They come from `NFL_TEAMS` through `teamAccent`.

### Neutral
- **Dark theme:**
  - Page #08090B, surface #14161B, raised #1F2228, controls #1A1C22, table head #181A20, border #2B2F36 (Oct 12 refinement: a clearer step off the near-black page).
  - Text #F6F7F9, secondary #A7ABB3, muted #878D96.
- **Light theme:**
  - Page #ECEEF2 and surfaces #FFFFFF with #D2D6DD borders, table head #F7F8FA, controls #E3E6EB.
  - Text #101114, secondary #50545C, muted #62676F.

### Named rules
- **The One Red Rule.** Red means selection, your team, or the main action. Ordinary statistics, borders, labels and bars are never red.
- **The AA Floor Rule.** Muted text stays at 4.5:1 or above on every surface it sits on.

## Typography

- **Body and display:** Proxima Nova, from Alan's Adobe Fonts kit, with an Arial fallback. Never bundle the font files.
- **Wordmark:** Archivo. Use it for `ADEQUATE.` only.

**Character:** a sturdy sports sans with tabular figures, built for numbers first.

### Hierarchy
- **Title** (600, 1.6rem; 1.4rem on phones): page and dialog titles.
- **Data** (700, tabular): player names, ranks, values, verdict numbers, key figures.
- **Body** (500–600, 0.8–0.9rem): copy and table cells.
- **Metadata** (500): NFL team, owner, tier text, muted lines.
- **Label** (600, 0.58–0.62rem, uppercase, 0.06–0.1em tracking; muted labels are never heavier than 600): column guides, eyebrows and tags. These are the only uppercase text.

### Named rules
- **The Three Weights Rule.** Use 500, 600 and 700 only. These are the kit's cuts; other weights render synthesized.
- **The Sentence Case Rule.** Headings, tabs and buttons use sentence or title case. Uppercase is reserved for small letter-spaced labels.

## Layout

- **Page:** the content width is 1720px (`.wrap`). On the Rankings board, the board takes about 76% and the rail `clamp(300px, 24%, 390px)` from 1280px. Below 1280px the rail is hidden and its content moves inline.
- **Header:** one row of about 58px (wordmark, nav tabs, theme, league chip). Below 1100px the tabs scroll on a second row.
- **Toolbar:** one borderless row, sticky under the header from 760px.
- **Rows:**
  - Board rows are 59px on desktop, 49px on tablet and 43px on phones; My Team rows stay at 52px or less.
  - Rank, photo, position badge and value share one center line.
- **Board columns:** Rank | Player | Position + Tier | Value. Position + tier (140px) and value form one right-hand cluster, and the player column takes the spare width.
- **Phones:**
  - From 375px with a 16px gutter.
  - No sideways page scroll; nothing essential is hidden or clipped.
  - Secondary information moves (to a sub-line or the player drawer) rather than disappearing.
  - Names wrap between words, never mid-word.
- **Player drawer:** a right-side drawer above 760px (`clamp(440px, 36vw, 520px)`, no backdrop, the board stays usable) and a full-screen sheet on phones. Its layout follows its own container width.

## Elevation & Depth

The system is flat by default, with tonal layering.
- Surfaces separate by background step and a 1px border, not by shadow.
- A shadow appears only on true overlays: the dragged row, hover cards, dialogs, and a soft lift on Trade Finder cards.
- No glows.

## Shapes

- **Box tags** (position badges, status blocks, rank chips, verdict, role and fit tags): 4px.
- **Controls and segmented buttons:** 6px.
- **Cards and panels:** 8px.
- **Pills** (status, confidence, market, transaction kinds): fully round.
- **Value meters and stat bars:** 2px tall with 2px ends; stat bars (Week view, production sorts) use the position color at 50% so the number leads.
- **Lines:** borders are 1px; underline tabs use a 2px red bar.

## Components

These are the shared primitives (the "Shared components" block at the end of the main stylesheet). Class names stay as they are, because JS and tests use them.
- **Position badge `.pos.QB/RB/WR/TE/FLEX/SF/PICK`:**
  - A filled chip: the color mixed into the surface (30% dark, 16% light), a darker border in the same family, and brighter text.
  - 22px tall, 4px radius, weight 600.
  - Tiers beside it are plain muted text ("Tier 1"); a tag tier like "Out for season" is muted red.
- **Box tag:** a 4px-radius tinted rectangle, weight 700 (or 600 for fit tags). Used for verdicts, roles, injuries and status blocks.
- **Filled pill:** a round tinted pill (`--tag-pad`, `--tag-fs`, weight 600). Used for status, leverage, confidence, grades and history chips.
- **Outline caps pill:** a round pill with a 1px border in uppercase (`--tag-fs-caps`, `--tag-ls-caps`). Used for trade-history tags, market tags and freshness.
- **Transaction kind tag:** a soft filled tag in sentence case (`.mv-tag`: `--tag-fs`, 6px corner, the kind's `--tx-*` hue at 14% fill and 22% border, its text shade ≥ 6:1). Its hues (slate, gray-sage, brick, gray) are never position colors. The bidders count beside it is an outline control with a ›.
- **Caps micro-label and eyebrow:** text only, weight 600. Micro-labels are 0.58rem / 0.07em; eyebrows are 0.62rem / 0.09em.
- **Underline tab (`.tab`, `.chip-btn`):** transparent; the selected state is strong text plus a 2px red bar. Used for the main nav, position chips, League sub-tabs, drawer tabs and filter rows. Tablists use `aria-selected`; filter groups use `aria-pressed`.
- **Segmented switch (`.view-toggle` + `.vt-btn`):**
  - A neutral fill container with 30px buttons at 6px radius.
  - The active button gets a raised neutral fill plus a red inset underline.
  - Used for AM Board / League-adjusted, Trade Finder modes, the calculator's AM Value / Roster Impact lens, Power Rankings lenses, Standings view, the Compare lens and the Ranking History metric switch.
- **Dropdowns, checkboxes and radios:** all custom and themed (`SpamSelect`, global CSS). There are no native controls and no native dialogs.
- **Hover cards (`#hc`):** one themed tooltip system site-wide.
  - Rich cards open on hover or focus; on touch, a tap opens a bottom sheet.
  - Plain `title` text moves into the card while it is open.
  - Nothing essential lives only in a tooltip.
- **Focus:** a visible neutral 2px ring (`--focus-ring`), never red.
- **Movement glyphs:** ▲ / ▼ always mean movement over time (since the last update, or a change between two dates). A comparison between two boards, such as League-adjusted vs the AM Board, is a labelled reference ("AM #12"), never an arrow. The same goes for market edge ("AM +3" / "Mkt +2"), Standings ("+2 roster ahead"), the Compare leader (a neutral ●) and trending adds ("+4.2k adds").
- **Verdict headline (Trade Calculator):** neutral type; the words carry the result. A small neutral dot marks that one side is ahead, a hollow ring that it is even or split. Never a side color.
- **Player drawer key figures:** two equal blocks, AM rank + value and ROS PPG. Season numbers and production ranks sit on one quieter line beneath them.

## Do's and Don'ts

- **Do** reuse tokens and the shared primitives above before adding a class. Grep before adding a short utility class name: `.pr-*`, `.mv-*`, `.pd-*` and `.tw-*` are each shared by several features.
- **Do** keep numbers tabular and right-aligned in columns, with the strongest weight on the number that answers the screen's question.
- **Do** verify both themes at 1440, 1024, 390 and 375px before shipping a UI change.
- **Don't** add a second accent color, gradients, glows, decorative icons, or cards nested in cards.
- **Don't** use red for ordinary data or warnings.
- **Don't** hide essential information behind hover only, or truncate a name mid-word.
- **Don't** redesign a page wholesale; improve it incrementally and record the decision in `CLAUDE.md` §10.
