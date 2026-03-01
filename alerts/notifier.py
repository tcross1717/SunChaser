import os
import logging
import requests
from datetime import datetime
from db.database import get_session
from db.models import Alert, FlightPrice, AwardPrice, Route, AlertHistory, UserPoints

logger = logging.getLogger(__name__)

TELEGRAM_URL = "https://api.telegram.org/bot{token}/sendMessage"


def _send_telegram(message: str) -> bool:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        logger.error("TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set.")
        return False

    try:
        resp = requests.post(
            TELEGRAM_URL.format(token=token),
            json={"chat_id": chat_id, "text": message, "parse_mode": "Markdown"},
            timeout=10,
        )
        resp.raise_for_status()
        return True
    except requests.RequestException as e:
        logger.error(f"Telegram send failed: {e}")
        return False


def cents_per_point(cash_price: float, points: int) -> float:
    if not points:
        return 0.0
    return round((cash_price / points) * 100, 2)


def check_cash_alerts():
    session = get_session()
    alerts = (
        session.query(Alert)
        .filter(Alert.is_active == True, Alert.alert_type.in_(["cash", "both"]))
        .all()
    )

    for alert in alerts:
        routes = (
            session.query(Route)
            .filter(Route.destination_id == alert.destination_id, Route.is_active == True)
            .all()
        )
        for route in routes:
            best = (
                session.query(FlightPrice)
                .filter(
                    FlightPrice.route_id == route.id,
                    FlightPrice.cabin_class == alert.cabin_class,
                )
                .order_by(FlightPrice.price.asc())
                .first()
            )
            if not best or not alert.max_cash_price:
                continue
            if best.price > alert.max_cash_price:
                continue

            msg = (
                f"*SunChaser Deal: {route.destination.name}*\n"
                f"{route.origin.iata_code} → {route.destination.iata_code}\n"
                f"💰 ${best.price:.0f} ({best.cabin_class}) | Departs {best.departure_date}\n"
                f"Airline: {best.airline or 'Unknown'}\n"
                f"Your threshold: ${alert.max_cash_price:.0f}"
            )
            sent = _send_telegram(msg)
            if sent:
                session.add(
                    AlertHistory(
                        alert_id=alert.id,
                        price_found=best.price,
                        message=msg,
                        sent_at=datetime.utcnow(),
                    )
                )

    session.commit()
    session.close()


def check_award_alerts():
    session = get_session()
    alerts = (
        session.query(Alert)
        .filter(Alert.is_active == True, Alert.alert_type.in_(["points", "both"]))
        .all()
    )

    for alert in alerts:
        routes = (
            session.query(Route)
            .filter(Route.destination_id == alert.destination_id, Route.is_active == True)
            .all()
        )

        user_balance = None
        if alert.program_id:
            up = session.query(UserPoints).filter_by(program_id=alert.program_id).first()
            user_balance = up.balance if up else None

        for route in routes:
            query = (
                session.query(AwardPrice)
                .filter(AwardPrice.route_id == route.id)
            )
            if alert.program_id:
                query = query.filter(AwardPrice.program_id == alert.program_id)
            if alert.cabin_class:
                query = query.filter(AwardPrice.cabin_class == alert.cabin_class)

            best = query.order_by(AwardPrice.points_required.asc()).first()
            if not best or not alert.max_points:
                continue
            if best.points_required > alert.max_points:
                continue

            if user_balance is not None:
                can_book = (
                    "You have enough points!"
                    if user_balance >= best.points_required
                    else f"Need {best.points_required - user_balance:,} more points"
                )
            else:
                can_book = ""

            msg = (
                f"*SunChaser Award: {route.destination.name}*\n"
                f"{route.origin.iata_code} → {route.destination.iata_code}\n"
                f"🏆 {best.points_required:,} pts + ${best.cash_fees or 0:.0f} fees "
                f"({best.cabin_class}) | {best.availability_date}\n"
                f"Program: {best.program.name}\n"
                + (f"{can_book}" if can_book else "")
            )
            sent = _send_telegram(msg)
            if sent:
                session.add(
                    AlertHistory(
                        alert_id=alert.id,
                        points_found=best.points_required,
                        message=msg,
                        sent_at=datetime.utcnow(),
                    )
                )

    session.commit()
    session.close()


def run_all_checks():
    check_cash_alerts()
    check_award_alerts()
