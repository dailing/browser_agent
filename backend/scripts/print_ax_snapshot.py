"""Print page accessibility data for experimentation.

- cdp (default): Chromium CDP Accessibility.getFullAXTree as pretty JSON (large, full tree).
- aria: Playwright locator(\"html\").aria_snapshot() as YAML text (not JSON; easier to read in terminal).

From backend/: uv run python scripts/print_ax_snapshot.py https://example.com
"""

import argparse
import json
import sys

from playwright.sync_api import sync_playwright


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("url", help="Page URL")
    p.add_argument(
        "--mode",
        choices=("cdp", "aria"),
        default="aria",
        help="cdp=JSON AX tree via CDP; aria=Playwright YAML aria snapshot",
    )
    p.add_argument(
        "--wait",
        default="load",
        choices=("commit", "domcontentloaded", "load", "networkidle"),
        help="page.goto wait_until",
    )
    args = p.parse_args()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(args.url, wait_until=args.wait, timeout=60_000)
            if args.mode == "cdp":
                client = page.context.new_cdp_session(page)
                payload = client.send("Accessibility.getFullAXTree")
            else:
                yaml_text = page.locator("html").aria_snapshot()
        finally:
            browser.close()

    if args.mode == "cdp":
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        sys.stdout.write(yaml_text)


if __name__ == "__main__":
    main()
