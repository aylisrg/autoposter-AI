"""Website import: scrape the user's site and extract business context.

Flow:
1. Playwright fetch (handles JS-rendered sites).
2. readability-lxml + BeautifulSoup to strip nav/footer and get the main content.
3. Claude summarizes into a structured business profile.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass

from anthropic import Anthropic
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
from readability import Document

from app.config import settings


@dataclass
class ImportedProfile:
    name: str
    description: str
    products: str
    target_audience: str
    raw_text_length: int


async def _fetch_rendered(url: str) -> str:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=settings.playwright_headless)
        context = await browser.new_context()
        page = await context.new_page()
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        # Wait a bit for JS to settle
        try:
            await page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass
        html = await page.content()
        await browser.close()
        return html


def _extract_main_content(html: str) -> str:
    # readability's Document pulls the main article/content body
    doc = Document(html)
    summary_html = doc.summary()
    soup = BeautifulSoup(summary_html, "html.parser")
    text = soup.get_text(separator="\n", strip=True)
    # Title from readability is usually good
    title = doc.short_title() or ""
    return f"# {title}\n\n{text}" if title else text


def _summarize_to_profile(raw_text: str, site_url: str) -> ImportedProfile:
    client = Anthropic(api_key=settings.anthropic_api_key)
    prompt = f"""You are analyzing a business website to extract a structured profile.

Site URL: {site_url}

Content (main body, nav/footer stripped):
---
{raw_text[:15000]}
---

Return a JSON object with these keys, all strings:
- "name": the business name (just the name, not a tagline)
- "description": 1-2 sentences describing what they do, specific and concrete
- "products": comma-separated list of main products/services, or a short sentence
- "target_audience": 1 sentence on who they serve

Rules:
- Use only info from the site. Don't invent.
- If a field can't be determined, set to empty string "".
- NO marketing fluff. No "innovative solutions", no "cutting-edge". Plain descriptive \
language.

Return ONLY the JSON object, no preamble, no code fences.
"""
    resp = client.messages.create(
        model=settings.text_model,
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = resp.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        # Strip leading "json\n" if present
        raw = raw.split("\n", 1)[1] if raw.startswith("json") else raw
    data = json.loads(raw)
    return ImportedProfile(
        name=data.get("name", ""),
        description=data.get("description", ""),
        products=data.get("products", ""),
        target_audience=data.get("target_audience", ""),
        raw_text_length=len(raw_text),
    )


async def import_from_url(url: str) -> ImportedProfile:
    """End-to-end: fetch URL, extract, summarize."""
    html = await _fetch_rendered(url)
    text = _extract_main_content(html)
    # Claude call is sync — run in thread
    return await asyncio.to_thread(_summarize_to_profile, text, url)
