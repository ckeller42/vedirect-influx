#!/usr/bin/env python3
"""Render a Grafana dashboard to a PNG with Playwright (for README/docs).

Handles the usual headless-Grafana gotchas: logs in, waits for panel canvases to
actually draw (Grafana lazy-renders panels), uses kiosk mode for clean chrome-less
output, and sizes the capture to the dashboard's content height.

Usage:
  pip install playwright && playwright install chromium
  python scripts/screenshot-dashboard.py \
      --url http://localhost:3000 --user admin --password admin \
      --uid <dashboard-uid> --out docs/dashboard.png [--from now-12h] [--height 1170]

For Grafana Cloud, pass a viewer URL and a service-account token via --token instead
of --user/--password.
"""
import argparse
import asyncio


async def shot(args):
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(
            viewport={"width": args.width, "height": args.height},
            device_scale_factor=2,  # crisp 2x output
        )
        pg = await ctx.new_page()

        # auth: token (cloud) or form login (local)
        if args.token:
            await ctx.set_extra_http_headers({"Authorization": f"Bearer {args.token}"})
        else:
            await pg.goto(f"{args.url}/login", wait_until="networkidle", timeout=30000)
            await pg.fill("input[name=user]", args.user)
            await pg.fill("input[name=password]", args.password)
            await pg.click("button[type=submit]")
            await pg.wait_for_timeout(4000)

        # kiosk = no top nav/side menu; theme dark for a clean look
        url = f"{args.url}/d/{args.uid}?from={getattr(args, 'from')}&to={args.to}&kiosk&theme=dark"
        await pg.goto(url, wait_until="networkidle", timeout=30000)

        # Grafana lazy-renders: wait for a panel canvas, then settle for queries to draw
        try:
            await pg.wait_for_selector("canvas", timeout=20000)
        except Exception:
            pass
        await pg.wait_for_timeout(args.settle_ms)

        await pg.screenshot(path=args.out)  # viewport-sized; set --height to content
        print(f"saved {args.out}")
        await browser.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True, help="Grafana base URL")
    ap.add_argument("--uid", required=True, help="dashboard uid")
    ap.add_argument("--out", default="docs/dashboard.png")
    ap.add_argument("--user", default="admin")
    ap.add_argument("--password", default="admin")
    ap.add_argument("--token", default="", help="Grafana service-account token (cloud)")
    ap.add_argument("--from", default="now-12h", dest="from")
    ap.add_argument("--to", default="now")
    ap.add_argument("--width", type=int, default=1400)
    ap.add_argument("--height", type=int, default=1170, help="capture height = content height")
    ap.add_argument("--settle-ms", type=int, default=8000)
    asyncio.run(shot(ap.parse_args()))


if __name__ == "__main__":
    main()
