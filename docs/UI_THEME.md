# Data Designer — UI theme and screens (dark, sampled from crustdata.com)

> **Reference:** five crustdata.com screenshots supplied by the team (hero, Resources mega-menu, logo grid, testimonial cards, footer). Every colour below was **sampled from those images with PIL**, not guessed.
> **Working prototype:** [`ui/prototype/index.html`](../ui/prototype/index.html). Open it in a browser; no build step, no server. Screens are in [`ui/prototype/screens/`](../ui/prototype/screens/).
> **Branding rule:** the product is **Data Designer** with its own shield-and-check logo. Do **not** use Crustdata's logo, wordmark or testimonial content. The footer says "Data by Crustdata · reasoning by Claude".

---

## 1. Design tokens (`ui/prototype/styles.css` → `datadesigner/ui/static/theme.css` in Phase 2)

| Token | Value | Sampled from |
|---|---|---|
| `--bg` | `#000000` | page background (all screenshots) |
| `--nav` / `--panel` | `#0B0A18` | nav pill and mega-menu background |
| `--panel-2` | `#141125` | mega-menu item cards |
| `--panel-3` / `--line` | `#19172D` | mega-menu right panel, card borders |
| `--line-soft` | `#141414` | logo-grid cell borders |
| `--pill` | `#434151` | "Coming soon" pill |
| `--brand` | `#5752CA` | Dashboard / Get a Demo buttons |
| `--brand-logo` | `#5644ED` | logo stroke |
| `--brand-hl` | `#544FC2` | highlighted hero word ("employee") |
| `--brand-label` | `#8681F7` | section labels ("LEARN", "COMPARE") |
| `--hero-0 → 1 → 2` | `#000000 → #161533 → #2E2B6A` | hero gradient, top to bottom |
| `--ink` | `#FFFFFF` | headlines, body |
| `--ink-nav` | `#85858C` | nav links |
| `--ink-muted` | `#AAAAAA` | "Proudly backed by…" line, footer headings |
| `--ink-sub` | `#6B6888` | mega-menu item subtitles |
| `--ink-link` | `#A29FBA` | "→ vs Clay" list links |
| `--c-purple / --c-cyan / --c-green` | `#6C5FE6 / #00A9CC / #12A06A` | testimonial cards |
| `--c-green-dk` | `#0E8055` | round arrow button on the green card |
| divider | `linear-gradient(90deg, transparent, #777, transparent)` | footer rule |

**Type:** Inter for UI and Inter Display for headlines (`letter-spacing:-.025em` to `-.035em`, weight 600), JetBrains Mono for codes, IDs and API calls. Hero headline `clamp(40px, 5.4vw, 76px)`.
**Shape:** nav pill radius 24px; cards 16px; menu items 12px; buttons 12px; pills 999px.
**Motion:** 180ms `cubic-bezier(.2,.7,.2,1)`; route fade-up 280ms; the hero's rotating word (checked → sourced → scored) echoes the reference's "employee / growth lead" swap. `prefers-reduced-motion` turns all motion off.

### 1.1 Verdict and label colours (dark-adapted; text + icon always shown, never colour alone)

| Class | Text | Background | Icon |
|---|---|---|---|
| VERIFIED | `#3DD68C` | `rgba(61,214,140,.12)` | ✅ |
| PARTIALLY VERIFIED | `#7CCFB4` | `rgba(124,207,180,.12)` | 🟢 |
| UNVERIFIED | `#F5B83D` | `rgba(245,184,61,.12)` | 🟡 |
| OUTDATED | `#8FA3C7` | `rgba(143,163,199,.13)` | ⏳ |
| NOT VERIFIABLE | `#A29FBA` | `rgba(162,159,186,.12)` | ⚪ |
| FALSE | `#FF6B6B` | `rgba(255,107,107,.13)` | ❌ |
| NOT CHECKED | `#8C89A6` | `rgba(107,104,136,.18)` | ⚫ |

Labels: positive (RECOMMEND / PURSUE / CLEAR) `#3DD68C` · with conditions / CONSIDER `#22C3E6` · HOLD `#F5B83D` · PASS / REJECT / NOT RECOMMENDED `#FF6B6B`. All pass 4.5:1 on `#0B0A18`.

---

## 2. Components (reference pattern → Data Designer use)

| Reference pattern | Data Designer component |
|---|---|
| Floating nav pill with two purple buttons | Nav: Ask · Runs · Memos ▾ · Approvals (count) · Audit · Setup; right: credits today, `replay`/`live` pill, **New ask** |
| Resources mega-menu (icon tiles left, "Compare" arrow list in a lighter panel right) | **Memos ▾** menu: Market IM, Company IM, Research Memo, Find-list Memo · Runs, Approvals, Watchers ("Phase 3" pill) · Standards arrow list |
| Gradient hero, big headline, highlighted word, one CTA | Ask hero: tabs Investing / Research / Compliance, Answer / Full diligence toggle, query box, **Reason about it →**, sample chips (organiser inputs pre-loaded) |
| Three coloured testimonial cards with round arrow button | "From a sentence to a signed decision": Scout (purple) · Check (cyan) · Decide & act (green) |
| Logo grid with hairline borders | "Sources, ranked before they are read": T1 MCA21, GST, EPFO·VAHAN · T1-M reliable media · T2 Crustdata company / people / jobs & web · T3·T4 deck & self-published |
| Footer columns + gradient divider | Product · Memos · Standards · Built for · attribution and the "suggestions only" line |
| White chat bubble with red badge | **Ask the analyst**: explains any number on screen with citations; never changes a score |

Other components: reasoning-card modal (phrase → intent → parameters → metric → role → origin tag; ≤ 3 radio questions; **Confirm & run**), stage timeline with credits per stage and budget bar (**Cut budget**, **Kill & resume**), monospace call log, verdict badge (icon + class + code), evidence drawer (quote-locked passage with the matched span highlighted, tier, record and retrieval dates, field path, sha256), scorecard with 4-segment points bars (floor solid, ceiling faint) and per-row **[?]** working, floor–ceiling score bar with ticks at 50 and 75, inference card with strength pill and the line "Inference — not a verified fact", Gmail preview with **Approve & send / Edit / Reject** and the exactly-once dots (intent · sent · reconciled), hash-chained journal.

---

## 3. Screens (all in the prototype)

| # | Route | Screen | Key behaviour |
|---|---|---|---|
| 01 | `#/ask` | Ask | `/` focuses the box; Ctrl/⌘+Enter reasons; chips fill the box and pick the card |
| 02 | modal | Reasoning card | origin tags: from query · term library · assumed — confirm · proposed — confirm · proxy; nothing runs before **Confirm & run** |
| 03 | `#/run/<family>` | Run | stages tick live; credits per call; kill shows "resumed from checkpoint · 0 actions repeated" |
| 04 | `#/market` | Market IM | suggestion banner → stats → shortlist (MH share bar, R1 floor–ceiling bar with the 60 line) → funnel, label rules, the Delhi-HQ answer |
| 05 | `#/company` | Company IM | **fixed order: 1 Gates → 2 Scorecard → 3 Result → 4 Suggested decision → 5 Your decision** (accept, or override with a required reason) |
| 06 | `#/company` → Deck fact-check | Slide map + evidence drawer | class counts strip; click a row for the passage |
| 07 | `#/company` → Leadership | Bio claims with classes + LF-01…07 bars + LF-C |
| — | Financials · Technology · Regions tabs | pillar bars + health grade; TC-C; footprint share by state and location basis |
| 08 | `#/memo/research` | Research Memo (RESEARCH_QA) | answer → ranking bars → inference cards → R3, strength rule, method |
| 09 | `#/memo/findlist` | Research Memo (FIND_LIST) | founders with classes, near-misses shown (never padded in), R3 |
| 10–11 | `#/approvals` | Approvals | TEST MODE banner; edit in place; approve → intent → 250 OK → IMAP reconcile; reject journals |
| 12 | `#/audit` | Journal | filter; **Verify chain** |
| 13 | `#/setup` | Setup & connections | Crustdata ✓, Claude and Gmail "asked at first run", mail mode |
| 14 | bubble | Ask the analyst | suggested questions; canned answers in the prototype, `claude-sonnet-5-5` over the evidence store in the build |
| 15 | Memos ▾ | Mega-menu | |
| 16 | 400 px | Mobile | no horizontal scroll on any route (checked with Playwright) |

---

## 4. Porting to the app (Phase 2)

1. Copy `styles.css` to `datadesigner/ui/static/theme.css` unchanged; the tokens are the contract.
2. Each `view*()` function in `app.js` becomes a Jinja partial under `datadesigner/ui/templates/`; `window.DD` fields become the JSON returned by the API endpoints of the same name (plan §4.2D).
3. Interactions that change state (confirm, decide, approve, reject, kill) become HTMX `hx-post` calls; the toast text is the server's response message.
4. The `ui-theme-reviewer` sub-agent compares app screenshots with `ui/prototype/screens/` and fails the review on any token drift, missing icon on a badge, contrast < 4.5:1, or horizontal scroll at 400 px.

## 5. Accessibility and quality bar

- Contrast ≥ 4.5:1 for text; focus ring `#8681F7`; every control reachable by keyboard; Esc closes modal, drawer and chat.
- Every badge has text and an icon; charts have text values beside the bars.
- Tables scroll horizontally inside their card; the page never does.
- Numbers use the Indian locale (₹1,20,000; "₹186 cr"); dates as "22 Nov 2026" with IST where relevant.
- No layout shift during HTMX swaps; route changes fade in (or not at all with reduced motion).
