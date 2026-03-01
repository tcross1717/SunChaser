"""
Price analytics: percentile ranking and mistake fare detection.
"""
import logging
from datetime import datetime, timedelta
from sqlalchemy import func
from db.database import get_session
from db.models import FlightPrice, Route, Destination, AlertHistory, Alert

logger = logging.getLogger(__name__)

MISTAKE_FARE_THRESHOLD = 0.40   # 40% below 90-day average = mistake fare
HISTORY_DAYS = 90


def price_percentile(route_id: int, cabin_class: str, price: float) -> float | None:
    """
    Returns what percentile the given price sits in for this route over the
    last HISTORY_DAYS days. 0 = cheapest ever seen, 100 = most expensive.
    Returns None if fewer than 5 data points exist.
    """
    session = get_session()
    cutoff = datetime.utcnow() - timedelta(days=HISTORY_DAYS)

    prices = [
        row[0]
        for row in session.query(FlightPrice.price)
        .filter(
            FlightPrice.route_id == route_id,
            FlightPrice.cabin_class == cabin_class,
            FlightPrice.fetched_at >= cutoff,
        )
        .all()
    ]
    session.close()

    if len(prices) < 5:
        return None

    prices.sort()
    below = sum(1 for p in prices if p < price)
    return round((below / len(prices)) * 100, 1)


def route_average(route_id: int, cabin_class: str, days: int = HISTORY_DAYS) -> float | None:
    """Average price for a route over the last N days."""
    session = get_session()
    cutoff = datetime.utcnow() - timedelta(days=days)

    result = (
        session.query(func.avg(FlightPrice.price))
        .filter(
            FlightPrice.route_id == route_id,
            FlightPrice.cabin_class == cabin_class,
            FlightPrice.fetched_at >= cutoff,
        )
        .scalar()
    )
    session.close()
    return float(result) if result else None


def detect_mistake_fares(notify: bool = True) -> list[dict]:
    """
    Scan all routes for prices that are MISTAKE_FARE_THRESHOLD below their
    90-day average. Returns a list of findings and optionally sends Telegram
    alerts for each.
    """
    from alerts.notifier import _send_telegram  # local import to avoid circular

    session = get_session()
    routes = session.query(Route).filter(Route.is_active == True).all()
    found = []

    for route in routes:
        for cabin in ("economy", "business", "first"):
            avg = route_average(route.id, cabin)
            if avg is None:
                continue

            # Best current price (fetched in the last 24 h)
            cutoff = datetime.utcnow() - timedelta(hours=24)
            best = (
                session.query(FlightPrice)
                .filter(
                    FlightPrice.route_id == route.id,
                    FlightPrice.cabin_class == cabin,
                    FlightPrice.fetched_at >= cutoff,
                )
                .order_by(FlightPrice.price.asc())
                .first()
            )
            if not best:
                continue

            drop_pct = (avg - best.price) / avg
            if drop_pct >= MISTAKE_FARE_THRESHOLD:
                pct = price_percentile(route.id, cabin, best.price)
                entry = {
                    "origin": route.origin.iata_code,
                    "destination": route.destination.name,
                    "dest_iata": route.destination.iata_code,
                    "price": best.price,
                    "avg_price": round(avg, 0),
                    "drop_pct": round(drop_pct * 100, 1),
                    "cabin": cabin,
                    "airline": best.airline,
                    "departs": best.departure_date,
                    "percentile": pct,
                }
                found.append(entry)
                logger.warning(
                    f"Mistake fare: {route.origin.iata_code}→{route.destination.iata_code} "
                    f"${best.price:.0f} vs avg ${avg:.0f} ({drop_pct*100:.0f}% off)"
                )

                if notify:
                    pct_str = f" — lowest {pct:.0f}% of prices seen" if pct is not None else ""
                    msg = (
                        f"*MISTAKE FARE ALERT*\n"
                        f"{route.origin.iata_code} → {route.destination.name}\n"
                        f"💥 ${best.price:.0f} ({cabin}) | {best.departure_date}\n"
                        f"Normal avg: ${avg:.0f} | *{drop_pct*100:.0f}% below average*{pct_str}\n"
                        f"Airline: {best.airline or 'Unknown'}\n"
                        f"Book fast — these don't last!"
                    )
                    _send_telegram(msg)

    session.close()
    return found
