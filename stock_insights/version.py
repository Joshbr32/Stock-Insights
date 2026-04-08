"""version.py — Single source of truth for the application version.

HOW TO RELEASE AN UPDATE
-------------------------
1. Bump APP_VERSION below (e.g. "1.0.1").
2. Rebuild the .exe with build.bat and give Raymond the new file.
3. Update the hosted version.json so existing copies can detect the new release:

   version.json (host this at UPDATE_MANIFEST_URL):
   {
       "version": "1.0.1",
       "notes": "Bug fixes and performance improvements.",
       "download_url": "https://github.com/Joshbr32/stock-insights/releases/latest"
   }

Recommended free hosting for version.json:
  • GitHub Gist  → https://gist.githubusercontent.com/YOUR_USERNAME/GIST_ID/raw/version.json
  • GitHub Release asset (rename to version.json and attach to every release)
  • Any static web host / Dropbox public link
"""

APP_VERSION = "1.0.0"

# Replace with the raw URL of your hosted version.json
UPDATE_MANIFEST_URL = (
    "https://gist.githubusercontent.com/Joshbr32/GIST_ID/raw/version.json"
)
