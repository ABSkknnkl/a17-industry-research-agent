import asyncio, pathlib, sys
from playwright.async_api import async_playwright
ROOT = pathlib.Path(".").resolve()
OUT = ROOT / "scratch" / "shots"; OUT.mkdir(parents=True, exist_ok=True)
JOBS = [
    ("第五章_A版_券商研报版式.html", "a.png", 900),
    ("第五章_B版_数据手册多图风.html", "b.png", 1440),
    ("第五章_双风格对比.html", "cmp.png", 1680),
]
async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch()
        for fn, out, w in JOBS:
            pg = await b.new_page(viewport={"width": w, "height": 1200}, device_scale_factor=1)
            await pg.goto((ROOT / "output" / fn).as_uri())
            await pg.wait_for_timeout(900)
            await pg.screenshot(path=str(OUT / out), full_page=True)
            print("shot:", out)
            await pg.close()
        await b.close()
asyncio.run(main())
