"""
Award availability fetcher using the seats.aero Pro API.
Docs: https://developers.seats.aero/reference/cached-search
"""
import os
import logging
import requests
from datetime import datetime, timedelta
from sqlalchemy.orm import joinedload
from db.database import get_session
from db.models import Route, AwardPrice, LoyaltyProgram

logger = logging.getLogger(__name__)

SEATS_AERO_BASE = "https://seats.aero/partnerapi"

# Maps our program slugs → seats.aero source names
SLUG_TO_SOURCE: dict[str, str] = {
    "delta_skymiles": "delta",
    "united_mileageplus": "united",
    "american_aadvantage": "american",
    "alaska_mileage_plan": "alaska",
    "air_canada_aeroplan": "aeroplan",
    "air_france_flying_blue": "flyingblue",
    "british_airways_avios": "british",
    "emirates_skywards": "emirates",
    "singapore_krisflyer": "singapore",
    "virgin_atlantic": "virginatlantic",
    "turkish_miles_smiles": "turkish",
    "cathay_asia_miles": "cathay",
    "etihad_guest": "etihad",
    "ana_mileage_club": "ana",
    "jetblue_trueblue": "jetblue",
    "southwest_rapid_rewards": "southwest",
}

# Reverse map: seats.aero source name → our program slug
SOURCE_TO_SLUG: dict[str, str] = {v: k for k, v in SLUG_TO_SOURCE.items()}

# Cabin → (available flag, mileage cost field, taxes field)
CABIN_FIELDS: dict[str, tuple[str, str, str]] = {
    "economy":  ("YAvailable", "YMileageCostRaw", "YTotalTaxes"),
    "premium":  ("WAvailable", "WMileageCostRaw", "WTotalTaxes"),
    "business": ("JAvailable", "JMileageCostRaw", "JTotalTaxes"),
    "first":    ("FAvailable", "FMileageCostRaw", "FTotalTaxes"),
}


def _headers() -> dict:
    return {
        "Partner-Authorization": os.getenv("SEATS_AERO_API_KEY", ""),
        "Content-Type": "application/json",
    }


def fetch_award_availability(
    origin: str,
    destination: str,
    start_date: str,
    end_date: str | None = None,
) -> list[dict]:
    """
    Fetch all award availability for a route from seats.aero.
    Returns the raw list of availability records.
    """
    if not end_date:
        end_date = (
            datetime.strptime(start_date, "%Y-%m-%d") + timedelta(days=90)
        ).strftime("%Y-%m-%d")

    all_sources = ",".join(SLUG_TO_SOURCE.values())
    params = {
        "origin_airport": origin,
        "destination_airport": destination,
        "start_date": start_date,
        "end_date": end_date,
        "sources": all_sources,
        "order_by": "lowest_mileage",
        "take": 500,
    }

    try:
        resp = requests.get(
            f"{SEATS_AERO_BASE}/search",
            headers=_headers(),
            params=params,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("data", [])
    except requests.RequestException as e:
        logger.error(f"seats.aero error {origin}→{destination}: {e}")
        return []


def fetch_all_award_routes():
    session = get_session()
    routes = (
        session.query(Route)
        .options(joinedload(Route.origin), joinedload(Route.destination))
        .filter(Route.is_active == True)
        .all()
    )
    # Build slug → program_id map
    programs = session.query(LoyaltyProgram).all()
    slug_to_id: dict[str, int] = {p.slug: p.id for p in programs}
    session.close()

    start_date = (datetime.today() + timedelta(days=14)).strftime("%Y-%m-%d")

    for route in routes:
        origin = route.origin.iata_code
        dest = route.destination.iata_code
        logger.info(f"Fetching award availability: {origin}→{dest}")

        records = fetch_award_availability(origin, dest, start_date)
        if not records:
            continue

        session = get_session()
        saved = 0

        for rec in records:
            source = rec.get("Source", "").lower()
            prog_slug = SOURCE_TO_SLUG.get(source)
            if not prog_slug:
                continue
            program_id = slug_to_id.get(prog_slug)
            if not program_id:
                continue

            # Save one record per cabin that has availability
            for cabin, (avail_field, cost_field, tax_field) in CABIN_FIELDS.items():
                if not rec.get(avail_field):
                    continue
                points = rec.get(cost_field)
                if not points:
                    continue

                session.add(
                    AwardPrice(
                        route_id=route.id,
                        program_id=program_id,
                        points_required=int(points),
                        cash_fees=rec.get(tax_field),
                        cabin_class=cabin,
                        availability_date=rec.get("Date", "")[:10],
                    )
                )
                saved += 1

        session.commit()
        session.close()
        logger.info(f"Saved {saved} award records for {origin}→{dest}")
