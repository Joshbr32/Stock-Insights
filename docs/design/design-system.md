# Stock Insights design system ("Harbor")

The visual language shared by the desktop app (PySide6 widgets + QML) and the mobile PWA.
Read this before changing any screen, colour, font or spacing.

## Subject, audience, job

- **Subject:** a personal trade tracker for a small group of friends who trade stocks.
- **Audience:** a handful of retail traders who open it many times a day, mostly on a Windows desktop, sometimes on a phone.
- **Primary job:** answer "am I on pace for my goal, and what is open right now?" in one glance, then make logging or closing a trade fast.

## The one bold element: the pace rail

Every other surface is quiet. The single memorable element is the **pace rail** at the top of the
goal dashboard (desktop) and the home view (PWA):

```
 Goal  $10,000 by Dec 31                                   $1,240 ahead of pace
 |=========================●=======|-------------------------------------------| $10,000
 $0                     $4,860   today's pace $3,620
```

- A full-width horizontal track from 0 to the goal target.
- A filled segment up to the current realised P/L, ending in a dot.
- A thin amber tick at **where you should be today** (the required pace), labelled underneath.
- One plain sentence at the right: "$1,240 ahead of pace" / "$860 behind pace" / "Goal reached".
- Amber (`pace`) is used **only** here (and the matching marker on the equity curve). Nowhere else.

## Colour tokens

Default theme. The other selectable themes in `stock_insights/theme.py` keep their own palettes but
must provide the same token names (add `pace` by deriving it from their `secondary` if missing).

| Token        | Light     | Dark      | Use                                                        |
|--------------|-----------|-----------|------------------------------------------------------------|
| `bg`         | `#E8ECEF` | `#161D24` | Window / page background ("harbor")                        |
| `card`       | `#F8FAFB` | `#1F2830` | Panels ("deck"); separated from `bg` by tone, not shadows   |
| `card2`      | `#EEF2F5` | `#27323C` | Raised rows, table header, hover, input fields              |
| `text`       | `#15202B` | `#E4EAF0` | Primary text and numbers                                    |
| `text_muted` | `#566472` | `#93A2B0` | Labels, secondary text (>= 4.5:1 on `card`)                 |
| `border`     | `#D3DAE0` | `#33404B` | Hairlines inside panels only (table rules, input outlines)  |
| `primary`    | `#2C55C9` | `#7FA2FF` | Interactive: buttons, links, focus ring, selected tab        |
| `text_on_color` | `#FFFFFF` | `#0E1620` | Text on `primary`                                       |
| `pace`       | `#B07610` | `#F0B43C` | Pace rail tick + equity-curve pace line. Never text.         |
| `good`       | `#0B7A5C` | `#4CC9A0` | Gains                                                      |
| `bad`        | `#B83A2E` | `#FF7B6B` | Losses                                                     |

Gain/loss is never shown by colour alone: signed numbers (`+$412.50`, `−$88.00`, with a real minus
sign U+2212) and, in tables, a ▲/▼ glyph before the % change.

## Type

- **Desktop:** `Segoe UI Variable Text` for UI text, `Segoe UI Variable Display` for numbers >= 20 px;
  fall back to `Segoe UI`, then the platform default. Check availability with `QFontDatabase` once
  in `theme.py` and expose the resolved families to QML. All numbers use tabular figures
  (`font.features: { "tnum": 1 }` in QML on Qt >= 6.7).
- **PWA:** system stack only (`system-ui, -apple-system, "Segoe UI Variable Text", "Segoe UI", Roboto, sans-serif`)
  with `font-variant-numeric: tabular-nums` on every number. No web fonts: they cost a network round
  trip on every cold start and the app must work offline.
- **Scale** (desktop px at "Normal" font size; PWA rem from a 15 px root): 12 · 13 (body) · 15 · 20 · 28 · 40.
  The 40 is used once: the current P/L inside the pace rail block.
- Weights: 400 body, 600 labels and headings, 650/700 only for the hero number.
- Sentence case everywhere. **No all-caps labels, no letter-spaced eyebrows, no monospace for data,
  no "A · B · C" meta strings, no "→" on buttons.**

## Shape, space, depth

- Spacing unit 4 px; panel padding 16; gaps between panels 12.
- Radius by hierarchy: panels 10, controls (buttons, inputs, combos) 6, pills/badges fully round, table rows 0.
- No drop shadows on desktop. Panels sit on `bg` by tone. Dialogs get the OS frame.
- Tables: 32 px rows, `border` hairline between rows, numbers right-aligned, text left-aligned,
  header in `text_muted` 12 px weight 600 on `card2`.

## Motion

- Only in response to the user: tab switch cross-fade (120 ms), menu/popup open (100 ms), row hover tint.
- One orchestrated moment: the pace-rail fill animates from 0 to its value once when an account first loads (400 ms, ease-out).
- Respect reduced motion (Windows "Show animations" off / `prefers-reduced-motion`): skip it.

## Words

- Name things by what the user does: "Log trade", "Close position", "Mark down", "Export CSV", "Back up data".
- Buttons say what happens; the result message reuses the verb ("Trade logged").
- Errors say what happened and what to do: "Can't reach the sync server. Changes are saved here and will sync when it's back."
- Empty states invite the next action: "No open positions. Log a trade to start tracking."

## Accessibility floor

- Text contrast >= 4.5:1 (>= 3:1 for 20 px+), focus ring visible on every control (2 px `primary`).
- Every action reachable by keyboard; tab order follows reading order.
- Hit targets >= 32 px desktop, >= 44 px PWA.
