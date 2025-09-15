# parser.py
import asyncio
from typing import List, Tuple, Optional
from playwright.async_api import async_playwright

async def sniff_one(url: str, headless: bool, wait_ms: int) -> Tuple[str, Optional[str], str]:
    hit_mp4 = None
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        ctx = await browser.new_context()
        page = await ctx.new_page()

        def on_request(req):
            nonlocal hit_mp4
            u = req.url
            if "douyinvod.com" in u and ("mime_type=video_mp4" in u or u.endswith(".mp4")):
                if not hit_mp4:
                    hit_mp4 = u

        page.on("request", on_request)

        try:
            await page.goto(url, wait_until="domcontentloaded")
            await page.wait_for_timeout(wait_ms)
        except Exception as e:
            await browser.close()
            return url, None, f"❌ 加载失败: {e}"

        await browser.close()
    return url, hit_mp4, ("✅ 解析成功" if hit_mp4 else "❌ 未捕获到直链")

async def sniff_serial(urls: List[str], headless: bool, wait_ms: int):
    results = []
    for u in urls:
        results.append(await sniff_one(u, headless, wait_ms))
    return results