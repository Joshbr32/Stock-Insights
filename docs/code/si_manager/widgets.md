# si_manager/widgets.py
**Purpose:** Building blocks: the painted state marks (shape per tone), panels, label-over-value facts, check rows and the verdict bar.
**Used by:** `pages.py`, `window.py`.  **Depends on:** `theme`; PySide6.

## Key types and functions
| Name | Kind | Contract |
|---|---|---|
| `draw_mark(painter, rect, tone)` | func | good = filled circle with a tick; warn = triangle with "!"; bad = rounded square with a cross; busy = ring with a dot; idle = empty ring. Ink is the `card` colour. |
| `mark_icon(tone, size)` | func | The same as a hi-dpi `QIcon` (table cells). |
| `Mark`, `StateMark` | QWidget | Shape alone; shape + word (word coloured by tone, `text` for idle). Accessible name = the word. |
| `Panel(title)` | QFrame | `#panel`: card tone, radius 10, padding 16; `body` is its QVBoxLayout. |
| `muted(text, px)` | func | Secondary text label. |
| `Facts(items, columns)` | QWidget | Grid of caption over value; `set(key, text)` ("–" when empty). |
| `CheckRow` | QWidget | Mark + wrapped sentence; `set(tone, sentence)`. |
| `VerdictBar` | QFrame | `set(tone, sentence, facts)`; warn/bad tint the bar and add a 4 px edge in the tone colour. |

## How to change it safely
Shapes carry the meaning; colours repeat it. Keep every tone's shape distinct.

## Map
- 1-18 docstring, imports
- 20-83 `draw_mark`, `mark_icon`
- 85-124 `Mark`, `StateMark`
- 126-193 `Panel`, `muted`, `Facts`, `CheckRow`
- 195-end `VerdictBar`
