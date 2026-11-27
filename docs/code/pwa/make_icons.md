# pwa/make_icons.py
**Purpose:** Generates PWA icons (192, 512, maskable 512) into `pwa/icons/` with Pillow.
**Used by:** run manually (`python pwa/make_icons.py`).  **Depends on:** Pillow.

## Key types and functions
| Name | Kind | Contract |
|---|---|---|
| `render_icon(size, maskable=False)` | func | Returns a PIL image: cream square, "Si" monogram, crimson rule. Maskable uses a larger safe-zone pad and no border. |
| `main()` | func | Creates `pwa/icons/` and saves the three PNGs. Guarded by `__main__`, so importing no longer writes files. |

## Data and state
Writes `icon-192.png`, `icon-512.png`, `icon-maskable-512.png`, referenced by the PWA manifest and service worker.

## How to change it safely
The service worker caches the icons; bump its VERSION if the icons change and must reach installed phones.

## Map
Constants 1-13; `render_icon` 16-55; `main` 58-end.
