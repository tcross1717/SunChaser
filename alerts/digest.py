"""
Weekly digest: best cash and award deals from the past 7 days, sent via Telegram.
"""
import logging
from datetime import datetime, timedelta
from sqlalchemy import func
from db.database import get_session
from db.models import FlightPrice, AwardPrice, Route, Destination, LoyaltyProgram
from alerts.notifier import _send_telegram

logger = logging.getLogger(__name__)


def _best_cash_deals(limit: int = 5) -> list[dict]:
    session = get_session()
    cutoff = datetime.utcnow() - timedelta(days=7)

    # Best (lowest) price per route seen in the past week
    subq = (
        session.query(
            FlightPrice.route_id,
            func.min(FlightPrice.price).label("min_price"),
        )
        .filter(FlightPrice.fetched_at >= cutoff, FlightPrice.cabin_class == "economy")
        .group_by(FlightPrice.route_id)
        .subquery()
    )

    rows = (
        session.query(FlightPrice, Route, Destination)
        .join(subq, (FlightPrice.route_id == subq.c.route_id) & (FlightPrice.price == subq.c.min_price))
        .join(Route, FlightPrice.route_id == Route.id)
        .join(Destination, Route.destination_id == Destination.id)
        .filter(Route.is_active == True)
        .order_by(FlightPrice.price.asc())
        .limit(limit)
        .all()
    )

    session.close()
    return [
        {
            "origin": route.origin.iata_code,
            "destination": dest.name,
            "price": fp.price,
            "airline": fp.airline,
            "departs": fp.departure_date,
        }
        for fp, route, dest in rows
    ]


def _best_award_deals(limit: int = 5) -> list[dict]:
    session = get_session()
    cutoff = datetime.utcnow() - timedelta(days=7)

    subq = (
        session.query(
            AwardPrice.route_id,
            AwardPrice.program_id,
            func.min(AwardPrice.points_required).label("min_pts"),
        )
        .filter(AwardPrice.fetched_at >= cutoff, AwardPrice.cabin_class == "economy")
        .group_by(AwardPrice.route_id, AwardPrice.program_id)
        .subquery()
    )

    rows = (
        session.query(AwardPrice, Route, Destination, LoyaltyProgram)
        .join(
            subq,
            (AwardPrice.route_id == subq.c.route_id)
            & (AwardPrice.program_id == subq.c.program_id)
            & (AwardPrice.points_required == subq.c.min_pts),
        )
        .join(Route, AwardPrice.route_id == Route.id)
        .join(Destination, Route.destination_id == Destination.id)
        .join(LoyaltyProgram, AwardPrice.program_id == LoyaltyProgram.id)
        .filter(Route.is_active == True)
        .order_by(AwardPrice.points_required.asc())
        .limit(limit)
        .all()
    )

    session.close()
    return [
        {
            "origin": route.origin.iata_code,
            "destination": dest.name,
            "points": ap.points_required,
            "fees": ap.cash_fees,
            "program": prog.name,
            "date": ap.availability_date,
        }
        for ap, route, dest, prog in rows
    ]


def send_weekly_digest():
    cash = _best_cash_deals()
    awards = _best_award_deals()

    if not cash and not awards:
        logger.info("Weekly digest: no data to send.")
        return

    lines = [f"*SunChaser Weekly Digest — {datetime.today().strftime('%b %d')}*\n"]

    if cash:
        lines.append("*Best Cash Deals This Week:*")
        for i, d in enumerate(cash, 1):
            lines.append(
                f"{i}. {d['origin']} → {d['destination']} — "
                f"${d['price']:.0f} ({d['airline'] or '?'}) | Departs {d['departs']}"
            )

    if awards:
        lines.append("\n*Best Award Deals This Week:*")
        for i, d in enumerate(awards, 1):
            fees = f" + ${d['fees']:.0f} fees" if d.get("fees") else ""
            lines.append(
                f"{i}. {d['origin']} → {d['destination']} — "
                f"{d['points']:,} pts{fees} [{d['program']}] | {d['date']}"
            )

    _send_telegram("\n".join(lines))
    logger.info("Weekly digest sent.")


def check_flexible_destination_alerts(max_cash: float, cabin: str = "economy") -> list[dict]:
    """
    Find any active route where the best current price is under max_cash.
    Used for the 'any destination under $X' query mode.
    """
    session = get_session()
    cutoff = datetime.utcnow() - timedelta(hours=24)

    rows = (
        session.query(FlightPrice, Route, Destination)
        .join(Route, FlightPrice.route_id == Route.id)
        .join(Destination, Route.destination_id == Destination.id)
        .filter(
            FlightPrice.price <= max_cash,
            FlightPrice.cabin_class == cabin,
            FlightPrice.fetched_at >= cutoff,
            Route.is_active == True,
        )
        .order_by(FlightPrice.price.asc())
        .all()
    )

    session.close()
    return [
        {
            "origin": route.origin.iata_code,
            "destination": dest.name,
            "iata": dest.iata_code,
            "region": dest.region,
            "price": fp.price,
            "airline": fp.airline,
            "departs": fp.departure_date,
        }
        for fp, route, dest in rows
    ]
