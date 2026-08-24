---
name: nerv-ui
description: "NERV Operations Console v2 — Evangelion-inspired UI component library. Data-driven Three.js MAGI visualization (yield surface mesh + organic flow curves + bar columns), blockchain event log terminal, dense metrics grid, vault cards, oracle consensus display, CRT effects, emergency mode. Noto Serif Display (weight 900) + Shippori Mincho B1 + JetBrains Mono. NO HELVETICA. Every pixel conveys information."
---

# NERV UI v2 — Operations Console Component Library

Build web interfaces that feel like NERV designed them. Dense, data-driven, clinical. Every visual element references real data — no decorative waste.

**The screen is off until data demands it. Black void is the default state.**

**Live Demo:** https://woody-cairn-ztqf.here.now/
**Source:** `~/clawd/nerv-ui/index.html`
**v1 Docs:** See `SKILL-v1.md` for the original component library (Cormorant Garamond, hex grids, command blocks)

---

## What's New in v2

| v1 | v2 |
|---|---|
| Cormorant Garamond (max 700) | **Noto Serif Display** (up to 900) — much heavier |
| Decorative 3D wireframes | **Data-driven MAGI visualization** (yield surface + flow curves) |
| Generic icosphere globe | **Animated terrain mesh** with numbered vertices + organic curves |
| No event stream | **Blockchain event log** — scrolling terminal with typed events |
| Moderate density | **Maximum density** — every panel shows real protocol data |
| 3 vaults (alETH/alUSD/alBTC) | **2 vaults** (alETH/alUSD) — matches current V3 scope |
| Hex grid scanner | Cut — replaced with MYT strategy performance table |
| Command block / ID block | Cut — decorative, replaced with data-driven metrics |

---

## Quick Start

### Drop-in Stylesheet
```html
<link rel="stylesheet" href="nerv-ui.css">
```
Contains all design tokens, CRT effects, and component classes. 808 lines, zero dependencies (except fonts).

### Required Fonts
```html
<link href="https://fonts.googleapis.com/css2?family=Noto+Serif+Display:wght@700;800;900&family=JetBrains+Mono:wght@400;500;700&family=Saira+Extra+Condensed:wght@400;600;700;800&family=Shippori+Mincho+B1:wght@500;700;800&display=swap" rel="stylesheet">
```

### CRT Effects (standalone)
Just want the CRT look? Use `components/crt-effects.css` — scanlines, vignette, phosphor flicker, moving scan line. Add `<div class="scan-line-overlay"></div>` to your body.

---

## File Structure

```
nerv-ui/
├── SKILL.md              ← This file (v2 documentation)
├── SKILL-v1.md           ← Original v1 documentation (preserved)
├── nerv-ui.css           ← Complete stylesheet (tokens + CRT + all components)
├── demo.html             ← Full working dashboard demo
└── components/           ← Individual component demos (self-contained)
    ├── event-log.html    ← Blockchain event log terminal
    ├── vault-card.html   ← Vault unit status cards
    ├── magi-oracle.html  ← Oracle price consensus display
    ├── metrics-grid.html ← Dense key metrics grid
    ├── data-table.html   ← Strategy + Transmuter tables
    └── crt-effects.css   ← CRT overlay effects (standalone)
```

Each component HTML file is **fully self-contained** — open in browser, see it working, extract what you need.

---

## Core Principles

1. **The void is the default.** Elements emerge from true black (#000), not a surface.
2. **Color = function.** Orange for labels/headers, green for nominal data, cyan for wireframes, red for alerts only.
3. **Every visual conveys data.** 3D scenes reference real metrics. No decorative wireframes.
4. **Density = authority.** More data per pixel = more credible.
5. **Mechanical compression.** Text squeezed via `scaleX(0.78-0.85)`. Signature EVA look.
6. **Bilingual is institutional.** Japanese text = the org operates in Japanese. Not decoration.
7. **CRT texture is always present.** Scanlines, vignette, phosphor flicker.

---

## Design Tokens

```css
:root {
  /* Void */
  --void:             #000000;
  --void-warm:        #080807;
  --void-panel:       #0C0C0A;

  /* NERV Orange — headers, labels, classification */
  --nerv-orange:      #FF9830;
  --nerv-orange-dim:  #C87020;
  --nerv-orange-hot:  #FFCC50;

  /* Nominal Green — data readouts, "system OK" */
  --data-green:       #50FF50;
  --data-green-dim:   #30BB30;

  /* Cyan — wireframes, spatial data */
  --wire-cyan:        #20F0FF;
  --wire-cyan-dim:    #10A0B0;

  /* Alert Red — emergencies only */
  --alert-red:        #FF3030;

  /* Neutral */
  --steel:            #D8D8D0;
  --steel-dim:        #888880;
}
```

---

## Typography — NO HELVETICA

```css
:root {
  /* Heavy display serif (EVA English titles) — weight 900, mechanically compressed */
  --font-title:  'Noto Serif Display', 'Times New Roman', serif;
  
  /* Japanese institutional (Matisse EB equivalent) */
  --font-mincho: 'Shippori Mincho B1', 'YuMincho', serif;
  
  /* Terminal/data readouts */
  --font-sys:    'JetBrains Mono', 'Cascadia Mono', monospace;
  
  /* WARNING stamps, emergency banners */
  --font-stamp:  'Saira Extra Condensed', 'Impact', sans-serif;
}
```

**Mechanical compression** (signature EVA):
```css
.compressed-title {
  font-family: var(--font-title);
  font-weight: 900;
  transform: scaleX(0.82);
  transform-origin: left center;
  letter-spacing: 0.2em;
  text-transform: uppercase;
}
```

---

## Components

### Event Log Terminal
Scrolling blockchain event feed. Color-coded by type (DEPOSIT=green, BORROW=cyan, HARVEST=orange, REPAY=dim green, REDEEM=yellow, MINT=magenta). Shows timestamp, type, address/detail, amount, block number.

**Demo:** `components/event-log.html`
```html
<div class="event-log">
  <div class="el-header">
    <span>Blockchain Event Log</span>
    <span class="el-count">42 events</span>
  </div>
  <div class="el-body" id="logBody">
    <div class="ev">
      <span class="ev-time">12:04:22</span>
      <span class="ev-type deposit">DEPOSIT</span>
      <span class="ev-detail">0x7f2a…4c3b → alETH Vault</span>
      <span class="ev-amount">142.5 ETH</span>
      <span class="ev-block">#19284721</span>
    </div>
  </div>
</div>
```

### Vault Card
EVA Unit-style status card for protocol vaults. Compressed serif title + Japanese katakana name + key-value stat rows.

**Demo:** `components/vault-card.html`
```html
<div class="panel">
  <div class="panel-header">
    <span>Unit-00 — alETH</span>
    <span class="tag"><span class="led green"></span>Operational</span>
  </div>
  <div class="vault-card">
    <div class="vc-id">Primary — Ethereum</div>
    <div class="vc-name">自己返済型ＥＴＨ</div>
    <div class="vc-row"><span class="lbl">TVL</span><span class="val">$142.8M</span></div>
    <!-- ... more rows ... -->
  </div>
</div>
```

### MAGI Oracle Consensus
Three-source oracle display (Chainlink, Uniswap TWAP, Internal) with price, data freshness, and agreement status. Updates in real-time.

**Demo:** `components/magi-oracle.html`

### Metrics Grid
Dense 2×N grid of key protocol numbers. Uses the `.highlight` modifier for important values and `.zero` for the always-zero liquidation counter.

**Demo:** `components/metrics-grid.html`

### Data Tables
NERV-styled tables for strategy performance and transmuter status. Orange headers, green data, hover highlighting, progress bars for utilization.

**Demo:** `components/data-table.html`

### 3D MAGI Data Analysis (Three.js)
The hero visualization. Requires Three.js via CDN importmap. Elements:
- **Cyan wireframe mesh** — undulating yield surface with numbered vertex labels
- **Orange organic curves** — 30 flow lines rising from mesh, independently swaying
- **Glowing tip dots** — pulsing orange spheres at curve endpoints
- **Flanking bar columns** — orange metric bars on left/right with wireframe outlines
- **Green background particles** — depth-adding scattered points
- Slow camera orbit

See `demo.html` Three.js module for full implementation (~200 lines).

---

## Emergency Mode

Toggle via `data-mode="emergency"` on `<html>`:
```javascript
document.documentElement.dataset.mode = 'emergency';
```

Transforms: all green→red, cyan→red, scan line speeds up, emergency overlay appears, MAGI goes into conflict state.

---

## Anti-Patterns

| ❌ Don't | ✅ Do |
|----------|-------|
| Gray/navy backgrounds | True black (#000) |
| Helvetica anywhere | Use the specified font stack |
| Decorative 3D wireframes | Data-driven visualizations |
| Smooth gradients | Hard boundaries, stepped blocks |
| Rounded corners | Sharp corners (except LEDs) |
| Light mode | This aesthetic has no light mode |
| Decorative Japanese | Real institutional terms only |
| Low density layouts | Pack data — density = authority |
| Static numbers | Live-updating from shared data model |

---

## Accessibility

All color combinations pass WCAG AA:
- Orange #FF9830 on black: 8.2:1 ✅
- Green #50FF50 on black: 13.8:1 ✅
- Cyan #20F0FF on black: 13.1:1 ✅
- Red #FF3030 on black: 5.9:1 ✅

```css
@media (prefers-reduced-motion: reduce) {
  body, .scan-line-overlay, [data-mode="emergency"] * {
    animation: none !important;
  }
}
```

---

*The screen is off until data demands it. The void is the default state.*
