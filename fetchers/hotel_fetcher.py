"""
Hotel price fetcher using SerpAPI Google Hotels.
Pulls real, live hotel prices — no test data.
Uses the same SERPAPI_API_KEY as the flight fetcher.
"""
import os
import logging
from datetime import datetime, timedelta
from serpapi import GoogleSearch
from db.database import get_session
from db.models import HotelPrice, Destination

logger = logging.getLogger(__name__)


def _search_hotels(
    destination_name: str,
    check_in: str,
    check_out: str,
    adults: int = 1,
) -> list[dict]:
    """Query SerpAPI Google Hotels and return raw property results."""
    params = {
        "engine": "google_hotels",
        "q": f"hotels in {destination_name}",
        "check_in_date": check_in,
        "check_out_date": check_out,
        "adults": adults,
        "currency": "USD",
        "hl": "en",
        "gl": "us",
        "api_key": os.getenv("SERPAPI_API_KEY"),
    }

    try:
        results = GoogleSearch(params).get_dict()
        return results.get("properties", [])
    except Exception as e:
        logger.error(f"SerpAPI hotel error for {destination_name} on {check_in}: {e}")
        return []


def fetch_hotels_for_destination(
    destination: Destination,
    check_in: str,
    check_out: str,
    adults: int = 1,
    max_results: int = 10,
):
    properties = _search_hotels(destination.name, check_in, check_out, adults)
    if not properties:
        logger.info(f"No hotel results for {destination.name} ({check_in})")
        return

    check_in_dt = datetime.strptime(check_in, "%Y-%m-%d")
    check_out_dt = datetime.strptime(check_out, "%Y-%m-%d")
    nights = (check_out_dt - check_in_dt).days

    session = get_session()
    saved = 0

    for prop in properties[:max_results]:
        # SerpAPI returns rate as total or per-night depending on the result
        rate = prop.get("rate_per_night") or prop.get("total_rate")
        if not rate:
            continue

        # rate may be a dict {"lowest": "$120", "extracted_lowest": 120}
        if isinstance(rate, dict):
            price_per_night = rate.get("extracted_lowest") or rate.get("extracted_before_taxes_fees")
        else:
            price_per_night = rate

        if not price_per_night:
            continue

        session.add(
            HotelPrice(
                destination_id=destination.id,
                hotel_name=prop.get("name", "Unknown"),
                hotel_id=prop.get("property_token") or prop.get("place_id"),
                price_per_night=float(price_per_night),
                currency="USD",
                check_in=check_in,
                check_out=check_out,
                nights=nights,
                rating=prop.get("overall_rating"),
                source="google_hotels",
            )
        )
        saved += 1

    session.commit()
    session.close()
    logger.info(f"Saved {saved} hotel prices for {destination.name} ({check_in} – {check_out})")


def fetch_all_hotel_destinations(nights: int = 7, lookahead_days: int = 60):
    """Fetch hotel prices for all active destinations across upcoming Fridays."""
    session = get_session()
    destinations = session.query(Destination).filter(Destination.is_active == True).all()
    session.close()

    today = datetime.today()
    check_in_dates = []
    for i in range(lookahead_days):
        candidate = today + timedelta(days=i)
        if candidate.weekday() == 4:   # Friday
            check_in_dates.append(candidate.strftime("%Y-%m-%d"))

    for dest in destinations:
        for check_in in check_in_dates:
            check_out = (
                datetime.strptime(check_in, "%Y-%m-%d") + timedelta(days=nights)
            ).strftime("%Y-%m-%d")
            logger.info(f"Fetching hotels: {dest.name} {check_in} – {check_out}")
            fetch_hotels_for_destination(dest, check_in, check_out)
