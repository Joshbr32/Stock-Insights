# stock_insights/widgets.py
**Purpose:** Harbor building blocks shared by every QWidget window/dialog: theme colour lookup, role-coloured labels, panels, forms, the button row, confirm boxes, and money/status formatting.
**Used by:** main_window, connection_dialog, settings_dialog, admin_dialogs, symbol_history_dialog, portfolio_tab, file_actions, dialogs/*.  **Depends on:** PySide6, `theme.ThemeManager` (imported lazily).

## Key types and functions
| Name | Kind | What it does / contract |
|---|---|---|
| `SpinnerLabel` | QLabel | Braille text spinner; `start(ms)`, `stop()`. |
| `find_theme_manager(widget=None)` | func | `.theme` on widget/ancestors → top-level window `.theme` → any ThemeManager child of a top-level (main.py's startup one). May return None. |
| `theme_color(token, widget=None)` | func → QColor | Harbor token (`bg, card, card2, text, text_muted, border, primary, good, bad, ...`; `error` = `bad`) from `ThemeManager.tokens()`; falls back to QPalette and Harbor good/bad. |
| `set_text_role(label, role)` | func | Roles `muted/good/bad/error/""`. Sets property `role` and a per-widget `color:` rule recomputed on every Palette/StyleChange (event filter), so theme switches recolour it. |
| `pl_role(value)` | func | `good`/`bad`/`muted` for a P/L number. |
| `muted_label`, `heading_label(text, px)`, `scaled_font(font, px, weight)` | funcs | Type scale 12/13/15/20/28 px relative to the app font (respects the font-size setting). |
| `dialog_layout(dialog)` | func | Root QVBoxLayout, 16 px margins, 12 px spacing. |
| `make_form()` / `align_form_labels(*forms)` | funcs | QFormLayout (left labels, fields grow) / equal label widths across stacked panels. |
| `Panel(title, parent, subtitle)` | QFrame | Card section with 16 px padding; `.body` QVBoxLayout, `.form()` lazily adds a form. Property `role="panel"`. |
| `add_dialog_buttons(dialog, layout, primary_text, on_primary, cancel_text, leading)` | func → (row, primary) | `[leading…] stretch [Cancel] [Primary]`; primary is the default button. `primary_text=None` → single close button. Plain row (not QDialogButtonBox) so the primary stays on the right on Windows. |
| `confirm(parent, title, text, action, destructive, detail)` | func → bool | QMessageBox whose accept button names the action; Cancel is default when destructive. |
| `fmt_money`, `fmt_signed_money`, `fmt_int`, `fmt_status` | funcs | `$1,234.56`, `+$412.50` / `−$88.00` (U+2212), `1,234`, `WAITING`→`Pending` etc. |

## Data and state
None persisted. Labels carry the dynamic property `role`; panels `role="panel"`; primary buttons `role="primary"`.

## How to change it safely
- Never hard-code colours here except the documented no-theme fallback.
- `_apply_role_color` must compare before `setStyleSheet` (setting a stylesheet sends StyleChange → recursion guard).
- If theme.py gains `QLabel[role=...]` / `QFrame[role="panel"]` rules, the per-widget colour still wins; keep them consistent.
- Check visually with `scripts/ui_snapshot_dialogs.py`.

## Map
- 1-50 docstring, imports, spacing constants
- 53-82 SpinnerLabel
- 85-238 theme access, roles, fonts
- 241-357 layout helpers (dialog_layout, make_form, align_form_labels, Panel, add_dialog_buttons)
- 359-378 confirm
- 380-415 formatting
