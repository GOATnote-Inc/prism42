"""Quick probe of the Recents page DOM so we can build a download-from-Recents flow."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parent
PROFILE_DIR = Path.home() / ".runway-automation-profile"
RUNWAY = "https://app.runwayml.com"


async def main() -> None:
    pw = await async_playwright().start()
    context = await pw.chromium.launch_persistent_context(
        user_data_dir=str(PROFILE_DIR), headless=False, viewport={"width": 1600, "height": 1000}
    )
    page = context.pages[0] if context.pages else await context.new_page()
    try:
        await page.goto(RUNWAY)
        await page.wait_for_load_state("domcontentloaded", timeout=15000)
        await page.wait_for_timeout(2000)

        # Click Recents nav
        await page.locator("button[aria-label='Recents']").first.click(timeout=5000)
        await page.wait_for_load_state("domcontentloaded", timeout=15000)
        await page.wait_for_timeout(3000)

        print("recents url:", page.url)
        # Save full HTML
        out_html = ROOT / "dom-dumps" / "recents.html"
        out_html.parent.mkdir(exist_ok=True)
        out_html.write_text((await page.content())[:300000])

        # Inventory likely-relevant elements
        items: list[dict] = []
        # Try a bunch of selectors that might hold list items
        for sel in [
            "[data-testid*='generation' i]",
            "[data-testid*='asset' i]",
            "[data-testid*='item' i]",
            "[data-testid*='card' i]",
            "article",
            "li",
            "div[class*='card' i]",
            "div[class*='grid' i] > div",
        ]:
            try:
                n = await page.locator(sel).count()
                if n:
                    items.append({"sel": sel, "count": n})
            except Exception:
                pass

        # Find all visible video/img with timestamps near them
        all_videos = page.locator("video, img[src*='cloudfront' i], img[src*='runway' i]")
        n = await all_videos.count()
        sample: list[dict] = []
        for i in range(min(n, 25)):
            v = all_videos.nth(i)
            try:
                if not await v.is_visible(timeout=200):
                    continue
                tag = await v.evaluate("e => e.tagName.toLowerCase()")
                src = await v.get_attribute("src")
                box = await v.bounding_box()
                # Look for nearest text (sibling or ancestor)
                near_text = await v.evaluate("""e => {
                    let cur = e;
                    for (let i=0; i<6 && cur; i++) {
                        const t = (cur.innerText||'').slice(0,160);
                        if (t.length>5) return t;
                        cur = cur.parentElement;
                    }
                    return '';
                }""")
                sample.append({
                    "tag": tag, "src": (src or "")[:140], "box": box,
                    "near_text": near_text[:160],
                })
            except Exception:
                pass

        # Check for download buttons anywhere
        dl = []
        for sel in [
            "button[aria-label*='Download' i]",
            "button[aria-label*='download' i]",
            "[role='menuitem']:has-text('Download')",
            "button:has-text('Download')",
            "a[download]",
        ]:
            try:
                n = await page.locator(sel).count()
                if n:
                    dl.append({"sel": sel, "count": n})
            except Exception:
                pass

        result = {"url": page.url, "items": items, "sample_videos": sample, "download_buttons": dl}
        (ROOT / "recents-probe.json").write_text(json.dumps(result, indent=2, default=str))
        print(json.dumps(result, indent=2, default=str)[:6000])
    finally:
        await context.close()
        await pw.stop()


if __name__ == "__main__":
    asyncio.run(main())
