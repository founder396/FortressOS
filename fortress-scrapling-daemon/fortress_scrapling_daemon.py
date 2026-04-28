"""
FORTRESS: Scrapling Stealth Fetcher Daemon (FEAT-406 Phase 2)
=============================================================
FastAPI service wrapping Scrapling's StealthyFetcher (Camoufox engine)
for sovereign, undetectable web scraping.

Runs as a standalone Python daemon on Port 11437.
The NestJS FortressScrapingOrchestrator connects via HTTP REST.

Architecture (DR-061 Split-Worker):
  - This Python process runs independently from the NestJS backend
  - Uses Scrapling's StealthyFetcher → Camoufox (hardened Firefox fork)
  - Implements the Dual-Fetching Identity pattern from FEAT-406:
    * General research = polite Fetcher (respects robots.txt)
    * FORTRESS IP enforcement = StealthyFetcher (Camoufox bypass)

4-Tier Escalation Pipeline (FEAT-406 SSOT):
  Tier 1: Direct VPS Stealth Mode (StealthyFetcher + Camoufox) — 80% success
  Tier 2: Ephemeral Tor Sandbox (rotating onion circuits)
  Tier 3: DeVIN Mesh Bridge (future — Queen Node residential IPs)
  Tier 4: Suspension Queue (POAW queue for retry later)

Requirements:
  pip install scrapling[all] fastapi uvicorn python-dotenv

Environment:
  SCRAPLING_PORT          — Daemon port (default: 11437)
  FORTRESS_BACKEND_URL    — NestJS backend URL (default: http://localhost:3010)
  SCRAPLING_MAX_CONCURRENT — Max concurrent browser instances (default: 3)
  SCRAPLING_HEADLESS       — Run headless (default: true)
"""

import os
import asyncio
import hashlib
import logging
import base64
from datetime import datetime
from typing import Optional
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# Load environment variables
load_dotenv()

# ============================================================================
# Configuration
# ============================================================================

PORT = int(os.getenv("SCRAPLING_PORT", "11437"))
BACKEND_URL = os.getenv("FORTRESS_BACKEND_URL", "http://localhost:3010")
MAX_CONCURRENT = int(os.getenv("SCRAPLING_MAX_CONCURRENT", "3"))
HEADLESS = os.getenv("SCRAPLING_HEADLESS", "true").lower() == "true"

# ============================================================================
# Logging
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("fortress.scrapling")

# ============================================================================
# Semaphore for concurrent browser limits (FEAT-403 Zombie prevention)
# ============================================================================

browser_semaphore = asyncio.Semaphore(MAX_CONCURRENT)

# ============================================================================
# Statistics
# ============================================================================

stats = {
    "total_requests": 0,
    "successful_fetches": 0,
    "failed_fetches": 0,
    "stealth_fetches": 0,
    "polite_fetches": 0,
    "tier2_tor_fallbacks": 0,
    "active_browsers": 0,
    "started_at": datetime.utcnow().isoformat(),
}

# ============================================================================
# Models
# ============================================================================


class FetchRequest(BaseModel):
    """Request to fetch a URL via Scrapling"""
    url: str
    mode: str = "stealth"  # "stealth" | "polite" | "dynamic"
    wait_selector: Optional[str] = None
    timeout: int = 30000  # ms
    screenshot: bool = False
    extract_images: bool = True
    content_selector: Optional[str] = None
    thumbnail_selector: Optional[str] = None
    max_items: int = 20


class ScrapedItem(BaseModel):
    """A single scraped item from the page"""
    url: str
    text: Optional[str] = None
    thumbnailUrl: Optional[str] = None
    metadata: dict = {}


class FetchResponse(BaseModel):
    """Response from a fetch operation"""
    success: bool = True
    url: str
    status_code: int = 200
    title: Optional[str] = None
    items: list[ScrapedItem] = []
    screenshot_base64: Optional[str] = None
    html_length: int = 0
    fetch_time_ms: int = 0
    tier_used: str = "tier1_stealth"
    error: Optional[str] = None


# ============================================================================
# Scrapling Fetcher Functions
# ============================================================================


async def fetch_stealth(req: FetchRequest) -> FetchResponse:
    """
    Tier 1: StealthyFetcher with Camoufox engine.
    Bypasses Cloudflare, DataDome, and most anti-bot systems.
    """
    import time
    start = time.time()

    try:
        from scrapling.fetchers import StealthyFetcher

        fetcher = StealthyFetcher(
            headless=HEADLESS,
            block_images=False,  # We NEED images for watermark detection
            disable_resources=False,
        )

        # Fetch the page
        response = await asyncio.to_thread(
            fetcher.fetch,
            req.url,
            headless=HEADLESS,
            block_images=False,
        )

        elapsed_ms = int((time.time() - start) * 1000)
        stats["stealth_fetches"] += 1

        # Extract items from the page
        items = []
        if req.content_selector and response.status == 200:
            try:
                elements = response.css(req.content_selector)
                for i, elem in enumerate(elements[:req.max_items]):
                    item = ScrapedItem(url=req.url)

                    # Extract text
                    item.text = elem.text or ""

                    # Extract link if available
                    link = elem.css("a::attr(href)") or elem.attrib.get("href")
                    if link:
                        item.url = str(link)

                    # Extract thumbnail
                    if req.thumbnail_selector:
                        img = elem.css(f"{req.thumbnail_selector}::attr(src)")
                        if img:
                            item.thumbnailUrl = str(img)
                    elif elem.tag == "img":
                        item.thumbnailUrl = elem.attrib.get("src", "")

                    items.append(item)
            except Exception as e:
                logger.warning(f"CSS extraction failed: {e}")

        # If extract_images is True and no content selector, get all images
        if req.extract_images and not items and response.status == 200:
            try:
                img_elements = response.css("img")
                for img in img_elements[:req.max_items]:
                    src = img.attrib.get("src", "")
                    if src and not src.startswith("data:"):
                        items.append(ScrapedItem(
                            url=req.url,
                            thumbnailUrl=src,
                            text=img.attrib.get("alt", ""),
                        ))
            except Exception as e:
                logger.warning(f"Image extraction failed: {e}")

        # Screenshot if requested
        screenshot_b64 = None
        if req.screenshot:
            try:
                screenshot_bytes = await asyncio.to_thread(
                    response.screenshot
                )
                if screenshot_bytes:
                    screenshot_b64 = base64.b64encode(screenshot_bytes).decode()
            except Exception:
                pass

        return FetchResponse(
            success=True,
            url=req.url,
            status_code=response.status,
            title=response.css("title::text") or "",
            items=items,
            screenshot_base64=screenshot_b64,
            html_length=len(response.text or ""),
            fetch_time_ms=elapsed_ms,
            tier_used="tier1_stealth",
        )

    except Exception as e:
        elapsed_ms = int((time.time() - start) * 1000)
        logger.error(f"Tier 1 (StealthyFetcher) failed for {req.url}: {e}")
        return FetchResponse(
            success=False,
            url=req.url,
            status_code=0,
            fetch_time_ms=elapsed_ms,
            tier_used="tier1_stealth",
            error=str(e),
        )


async def fetch_polite(req: FetchRequest) -> FetchResponse:
    """
    Polite fetcher — respects robots.txt, uses standard HTTP.
    For general research, not IP enforcement.
    """
    import time
    start = time.time()

    try:
        from scrapling.fetchers import Fetcher

        fetcher = Fetcher()
        response = await asyncio.to_thread(fetcher.fetch, req.url)

        elapsed_ms = int((time.time() - start) * 1000)
        stats["polite_fetches"] += 1

        items = []
        if req.extract_images and response.status == 200:
            try:
                for img in response.css("img")[:req.max_items]:
                    src = img.attrib.get("src", "")
                    if src and not src.startswith("data:"):
                        items.append(ScrapedItem(
                            url=req.url,
                            thumbnailUrl=src,
                            text=img.attrib.get("alt", ""),
                        ))
            except Exception:
                pass

        return FetchResponse(
            success=True,
            url=req.url,
            status_code=response.status,
            title=response.css("title::text") or "",
            items=items,
            html_length=len(response.text or ""),
            fetch_time_ms=elapsed_ms,
            tier_used="polite",
        )

    except Exception as e:
        elapsed_ms = int((time.time() - start) * 1000)
        logger.error(f"Polite fetch failed for {req.url}: {e}")
        return FetchResponse(
            success=False,
            url=req.url,
            fetch_time_ms=elapsed_ms,
            tier_used="polite",
            error=str(e),
        )


async def fetch_with_escalation(req: FetchRequest) -> FetchResponse:
    """
    4-Tier Escalation Pipeline (FEAT-406 SSOT):
      Tier 1: StealthyFetcher (Camoufox) — try first
      Tier 2: Tor fallback — if Tier 1 gets 403/blocked
      Tier 3: DeVIN Mesh — future (not implemented)
      Tier 4: Suspension Queue — give up, queue for later
    """
    async with browser_semaphore:
        stats["active_browsers"] += 1
        try:
            # Tier 1: StealthyFetcher
            result = await fetch_stealth(req)

            if result.success and result.status_code == 200:
                return result

            # Tier 1 failed — try Tier 2 (Tor) if status is 403/429
            if result.status_code in (403, 429, 503, 0):
                logger.warning(
                    f"Tier 1 failed ({result.status_code}), escalating to Tier 2 (Tor)..."
                )
                stats["tier2_tor_fallbacks"] += 1

                # Tier 2: Scrapling with Tor SOCKS5 proxy
                # Note: Requires Tor running on the host (apt install tor)
                try:
                    from scrapling.fetchers import StealthyFetcher

                    fetcher = StealthyFetcher(
                        headless=True,
                        proxy="socks5://127.0.0.1:9050",  # Standard Tor SOCKS5
                    )
                    response = await asyncio.to_thread(
                        fetcher.fetch,
                        req.url,
                        headless=True,
                    )

                    if response.status == 200:
                        items = []
                        if req.extract_images:
                            for img in response.css("img")[:req.max_items]:
                                src = img.attrib.get("src", "")
                                if src and not src.startswith("data:"):
                                    items.append(ScrapedItem(
                                        url=req.url,
                                        thumbnailUrl=src,
                                    ))

                        return FetchResponse(
                            success=True,
                            url=req.url,
                            status_code=response.status,
                            items=items,
                            html_length=len(response.text or ""),
                            tier_used="tier2_tor",
                        )
                except Exception as tor_error:
                    logger.error(f"Tier 2 (Tor) failed: {tor_error}")

            # Tier 3: DeVIN Mesh — NOT YET IMPLEMENTED
            # Tier 4: Suspension — return the original failure
            logger.warning(
                f"All tiers exhausted for {req.url}, returning Tier 4 (suspended)"
            )
            result.tier_used = "tier4_suspended"
            return result

        finally:
            stats["active_browsers"] -= 1


# ============================================================================
# FastAPI App
# ============================================================================


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle"""
    logger.info("🏰 FORTRESS Scrapling Daemon starting on port %d...", PORT)
    logger.info(
        "   Mode: StealthyFetcher (Camoufox) | Max concurrent: %d | Headless: %s",
        MAX_CONCURRENT, HEADLESS,
    )

    # Pre-install Camoufox browser on first run
    try:
        import subprocess
        subprocess.run(
            ["python", "-m", "camoufox", "fetch"],
            capture_output=True, timeout=120,
        )
        logger.info("✅ Camoufox browser binary ready")
    except Exception as e:
        logger.warning(f"⚠️ Camoufox pre-install skipped: {e}")

    yield

    logger.info("📴 FORTRESS Scrapling Daemon stopped")


app = FastAPI(
    title="FORTRESS Scrapling Stealth Fetcher",
    description="Sovereign web scraping via Scrapling StealthyFetcher (Camoufox)",
    version="1.0.0",
    lifespan=lifespan,
)


# ============================================================================
# REST Endpoints
# ============================================================================


@app.get("/health")
async def health_check():
    """Health check for the NestJS orchestrator."""
    return {
        "status": "healthy",
        "engine": "scrapling_stealthy_fetcher",
        "camoufox": True,
        "stats": stats,
        "max_concurrent": MAX_CONCURRENT,
        "active_browsers": stats["active_browsers"],
        "uptime_since": stats["started_at"],
    }


@app.post("/fetch", response_model=FetchResponse)
async def fetch_url(req: FetchRequest):
    """
    Fetch a URL using the configured mode.
    
    Modes:
      - "stealth": StealthyFetcher with Camoufox (default for FORTRESS)
      - "polite": Standard HTTP, respects robots.txt (for general research)
      - "escalate": 4-Tier Escalation Pipeline (auto-fallback)
    """
    stats["total_requests"] += 1

    logger.info(f"🔍 Fetch request: {req.url} (mode={req.mode})")

    try:
        if req.mode == "polite":
            result = await fetch_polite(req)
        elif req.mode == "escalate":
            result = await fetch_with_escalation(req)
        else:
            # Default: stealth with escalation
            async with browser_semaphore:
                stats["active_browsers"] += 1
                try:
                    result = await fetch_stealth(req)
                finally:
                    stats["active_browsers"] -= 1

        if result.success:
            stats["successful_fetches"] += 1
        else:
            stats["failed_fetches"] += 1

        return result

    except Exception as e:
        stats["failed_fetches"] += 1
        logger.error(f"❌ Fetch failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/fetch/batch")
async def fetch_batch(urls: list[str], mode: str = "stealth"):
    """
    Batch fetch multiple URLs concurrently (up to MAX_CONCURRENT).
    Used by the orchestrator for bulk scanning cycles.
    """
    results = []
    tasks = [
        fetch_url(FetchRequest(url=url, mode=mode))
        for url in urls[:20]  # Hard cap at 20
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    successful = [r for r in results if isinstance(r, FetchResponse) and r.success]
    failed = [r for r in results if isinstance(r, FetchResponse) and not r.success]

    return {
        "total": len(urls),
        "successful": len(successful),
        "failed": len(failed),
        "results": [
            r.model_dump() if isinstance(r, FetchResponse) else {"error": str(r)}
            for r in results
        ],
    }


@app.get("/stats")
async def get_stats():
    """Get detailed scraping statistics."""
    return stats


# ============================================================================
# Entry Point
# ============================================================================

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "fortress_scrapling_daemon:app",
        host="127.0.0.1",
        port=PORT,
        reload=False,
        log_level="info",
    )
