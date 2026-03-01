"""
Flight price scraper using Playwright + Google Flights.
No API key needed — runs a headless Chromium browser.

Replaces SerpAPI. Saves all records over time so price history accumulates.
"""
import asyncio
import logging
import re
from datetime import datetime, timedelta

from playwright.async_api import async_playwright, BrowserContext
from sqlalchemy.orm import joinedload

from db.database import get_session
from db.models import Route, FlightPrice

logger = logging.getLogger(__name__)


# ── Text parsers ───────────────────────────────────────────────────────────────

def _parse_price(text: str) -> float | None:
    m = re.search(r"\$([\d,]+)", text)
    return float(m.group(1).replace(",", "")) if m else None


def _parse_stops(text: str) -> int:
    t = text.lower()
    if "nonstop" in t:
        return 0
    m = re.search(r"(\d+)\s*stop", t)
    return int(m.group(1)) if m else 0


def _parse_duration(text: str) -> int | None:
    h = re.search(r"(\d+)\s*hr", text)
    m = re.search(r"(\d+)\s*min", text)
    if h or m:
        return (int(h.group(1)) if h else 0) * 60 + (int(m.group(1)) if m else 0)
    return None


def _parse_time(raw: str) -> str | None:
    """Convert '8:30 AM' or '20:30' → 'HH:MM' 24-hour."""
    m = re.search(r"(\d{1,2}):(\d{2})\s*(AM|PM)?", raw, re.I)
    if not m:
        return None
    h, mn, ampm = int(m.group(1)), int(m.group(2)), (m.group(3) or "").upper()
    if ampm == "PM" and h != 12:
        h += 12
    elif ampm == "AM" and h == 12:
        h = 0
    return f"{h:02d}:{mn:02d}"


# ── Google Flights scraper ─────────────────────────────────────────────────────

async def _search_one(
    ctx: BrowserContext,
    origin: str,
    dest: str,
    dep_date: str,
    ret_date: str,
) -> list[dict]:
    """Scrape one origin→dest roundtrip on one date from Google Flights."""
    page = await ctx.new_page()
    offers: list[dict] = []

    try:
        # Google Flights pre-filled URL (hash format)
        url = (
            f"https://www.google.com/travel/flights?hl=en"
            f"#flt={origin}.{dest}.{dep_date}"
            f"*{dest}.{origin}.{ret_date}"
            f";c:USD;e:1;sd:1;t:f"
        )
        await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        await page.wait_for_timeout(3_500)

        # Dismiss cookie/consent banners if present
        for btn_name in ["Accept all", "Agree", "I agree", "OK"]:
            try:
                btn = page.get_by_role("button", name=re.compile(btn_name, re.I))
                if await btn.count():
                    await btn.first.click()
                    await page.wait_for_timeout(800)
                    break
            except Exception:
                pass

        # Wait for flight result list items
        try:
            await page.wait_for_selector('[role="listitem"]', timeout=12_000)
        except Exception:
            logger.warning(f"No results loaded for {origin}→{dest} {dep_date}")
            return []

        items = await page.locator('[role="listitem"]').all()

        for item in items:
            try:
                text = (await item.inner_text()).strip()
            except Exception:
                continue

            if not text or "$" not in text:
                continue

            lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

            # ── Price ──
            price = None
            for ln in lines:
                if "$" in ln:
                    p = _parse_price(ln)
                    if p and p > 30:
                        price = p
                        break
            if not price:
                continue

            # ── Stops ──
            stops = 0
            for ln in lines:
                if "stop" in ln.lower() or "nonstop" in ln.lower():
                    stops = _parse_stops(ln)
                    break

            # ── Duration ──
            duration = None
            for ln in lines:
                if "hr" in ln.lower():
                    duration = _parse_duration(ln)
                    if duration:
                        break

            # ── Times — find "HH:MM AM/PM" patterns ──
            time_hits = re.findall(r"\d{1,2}:\d{2}\s*(?:AM|PM)?", text, re.I)
            dep_time = _parse_time(time_hits[0]) if len(time_hits) >= 1 else None
            arr_time = _parse_time(time_hits[1]) if len(time_hits) >= 2 else None

            # ── Airline — first meaningful line that isn't a time/price/stop/duration ──
            airline = None
            skip_patterns = re.compile(
                r"^\$|^\d{1,2}:\d{2}|\bstop|\bhr\b|\bmin\b|\bnonstop\b|\+\d",
                re.I,
            )
            for ln in lines:
                if len(ln) > 2 and not skip_patterns.search(ln):
                    airline = ln
                    break

            # ── Flight number (e.g. "AA 100") ──
            fn_match = re.search(r"\b([A-Z]{1,3})\s*(\d{1,4})\b", text)
            flight_number = f"{fn_match.group(1)} {fn_match.group(2)}" if fn_match else None

            offers.append({
                "price":            price,
                "airline":          airline,
                "stops":            stops,
                "duration_minutes": duration,
                "departure_time":   dep_time,
                "arrival_time":     arr_time,
                "flight_number":    flight_number,
            })

    except Exception as e:
        logger.error(f"Scrape error {origin}→{dest} {dep_date}: {e}")
    finally:
        await page.close()

    return offers


# ── Async fetch loop ───────────────────────────────────────────────────────────

async def _run(routes: list, departure_dates: list[str], trip_length_days: int):
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            locale="en-US",
            viewport={"width": 1400, "height": 900},
        )

        for route in routes:
            origin = route.origin.iata_code
            dest   = route.destination.iata_code
            logger.info(f"Scraping {origin} → {dest}")
            total_saved = 0

            for dep_date in departure_dates:
                ret_date = (
                    datetime.strptime(dep_date, "%Y-%m-%d")
                    + timedelta(days=trip_length_days)
                ).strftime("%Y-%m-%d")

                offers = await _search_one(ctx, origin, dest, dep_date, ret_date)

                if offers:
                    session = get_session()
                    for o in offers:
                        session.add(FlightPrice(
                            route_id         = route.id,
                            price            = o["price"],
                            currency         = "USD",
                            departure_date   = dep_date,
                            return_date      = ret_date,
                            trip_length_days = trip_length_days,
                            airline          = o.get("airline"),
                            cabin_class      = "economy",
                            source           = "scraper",
                            stops            = o.get("stops", 0),
                            departure_time   = o.get("departure_time"),
                            arrival_time     = o.get("arrival_time"),
                            duration_minutes = o.get("duration_minutes"),
                            flight_number    = o.get("flight_number"),
                            terminal         = None,
                        ))
                        total_saved += 1
                    session.commit()
                    session.close()

                # Polite delay between pages
                await asyncio.sleep(2)

            logger.info(f"Saved {total_saved} prices for {origin}→{dest}")

        await browser.close()


# ── Public entry point ─────────────────────────────────────────────────────────

def fetch_all_routes(lookahead_days: int = 90, trip_length_days: int = 7):
    """Fetch flight prices for all active routes via Playwright scraper.

    All records are kept — never deleted — so price history builds up over time.
    The historical chart in the dashboard shows how prices changed across fetches.
    """
    session = get_session()
    routes = (
        session.query(Route)
        .options(joinedload(Route.origin), joinedload(Route.destination))
        .filter(Route.is_active == True)
        .all()
    )
    session.close()

    # Bi-weekly dates from 2 weeks out → lookahead window
    departure_dates = [
        (datetime.today() + timedelta(days=i)).strftime("%Y-%m-%d")
        for i in range(14, lookahead_days, 14)
    ]

    logger.info(
        f"Scraping {len(routes)} routes × {len(departure_dates)} dates "
        f"= {len(routes) * len(departure_dates)} searches"
    )
    asyncio.run(_run(routes, departure_dates, trip_length_days))
