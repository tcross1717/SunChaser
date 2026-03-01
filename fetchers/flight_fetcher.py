"""
Flight price fetcher using SerpAPI Google Flights.
Pulls real, live prices — no test data.
Sign up at serpapi.com (free tier: 100 searches/month).
"""
import os
import logging
from datetime import datetime, timedelta
from serpapi import GoogleSearch
from sqlalchemy.orm import joinedload
from db.database import get_session
from db.models import Route, FlightPrice

logger = logging.getLogger(__name__)


def _search_flights(
    origin: str,
    destination: str,
    departure_date: str,
    return_date: str,
) -> list[dict]:
    """Query SerpAPI Google Flights and return raw best + other flight results."""
    params = {
        "engine": "google_flights",
        "departure_id": origin,
        "arrival_id": destination,
        "outbound_date": departure_date,
        "return_date": return_date,
        "currency": "USD",
        "hl": "en",
        "adults": 1,
        "api_key": os.getenv("SERPAPI_API_KEY"),
    }

    try:
        results = GoogleSearch(params).get_dict()
    except Exception as e:
        logger.error(f"SerpAPI error {origin}→{destination} on {departure_date}: {e}")
        return []

    offers = results.get("best_flights", []) + results.get("other_flights", [])
    return offers


def _parse_cabin(offer: dict) -> str:
    """Extract cabin class from a SerpAPI flight offer."""
    flights = offer.get("flights", [])
    if flights:
        return flights[0].get("travel_class", "economy").lower()
    return "economy"


def _parse_airline(offer: dict) -> str | None:
    """Extract primary airline from a SerpAPI flight offer."""
    flights = offer.get("flights", [])
    if flights:
        return flights[0].get("airline")
    return None


def _parse_details(offer: dict) -> dict:
    """Extract departure/arrival times, terminal, duration, stops, flight number."""
    legs = offer.get("flights", [])
    first = legs[0] if legs else {}
    last  = legs[-1] if legs else {}

    dep_airport = first.get("departure_airport", {})
    arr_airport = last.get("arrival_airport", {})

    def _time(ts: str | None) -> str | None:
        """Pull HH:MM from a 'YYYY-MM-DD HH:MM' string."""
        if ts and " " in ts:
            return ts.split(" ", 1)[1][:5]
        return ts[:5] if ts and len(ts) >= 5 else ts

    return {
        "departure_time":   _time(dep_airport.get("time")),
        "arrival_time":     _time(arr_airport.get("time")),
        "terminal":         dep_airport.get("terminal"),
        "duration_minutes": offer.get("total_duration"),
        "stops":            max(len(legs) - 1, 0),
        "flight_number":    first.get("flight_number"),
    }


def fetch_prices_for_route(route: Route, departure_dates: list[str], trip_length_days: int = 7):
    session = get_session()
    saved = 0

    for dep_date in departure_dates:
        ret_date = (
            datetime.strptime(dep_date, "%Y-%m-%d") + timedelta(days=trip_length_days)
        ).strftime("%Y-%m-%d")

        offers = _search_flights(
            route.origin.iata_code,
            route.destination.iata_code,
            dep_date,
            ret_date,
        )

        for offer in offers:
            price = offer.get("price")
            if not price:
                continue

            details = _parse_details(offer)
            session.add(
                FlightPrice(
                    route_id=route.id,
                    price=float(price),
                    currency="USD",
                    departure_date=dep_date,
                    return_date=ret_date,
                    trip_length_days=trip_length_days,
                    airline=_parse_airline(offer),
                    cabin_class=_parse_cabin(offer),
                    source="google_flights",
                    **details,
                )
            )
            saved += 1

    session.commit()
    session.close()
    logger.info(
        f"Saved {saved} prices for {route.origin.iata_code}→{route.destination.iata_code}"
    )


def fetch_all_routes(lookahead_days: int = 90, trip_length_days: int = 7):
    session = get_session()
    routes = (
        session.query(Route)
        .options(joinedload(Route.origin), joinedload(Route.destination))
        .filter(Route.is_active == True)
        .all()
    )
    session.close()

    # Bi-weekly departure dates starting 2 weeks out (saves ~60% of API calls vs weekly)
    departure_dates = [
        (datetime.today() + timedelta(days=i)).strftime("%Y-%m-%d")
        for i in range(14, lookahead_days, 14)
    ]

    for route in routes:
        logger.info(
            f"Fetching real prices: {route.origin.iata_code}→{route.destination.iata_code}"
        )
        fetch_prices_for_route(route, departure_dates, trip_length_days)
