"""
SunChaser Telegram Bot — interactive query interface.

Run:  python bot.py

Commands
--------
/help          list all commands
/deals         top 5 cheapest flights right now
/to <IATA>     best prices to a destination  (e.g. /to LHR  or  /to London)
/mistakes      mistake fares ≥40% below 90-day average
/awards <IATA> best award redemptions to a destination
/status        database stats & last fetch time
"""
import os
import logging
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv
from sqlalchemy import func

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

_TG = "https://api.telegram.org/bot{token}/{method}"


# ── Telegram helpers ──────────────────────────────────────────────────────────

def _send(text: str, chat_id: str) -> None:
    try:
        requests.post(
            _TG.format(token=os.getenv("TELEGRAM_BOT_TOKEN", ""), method="sendMessage"),
            json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
            timeout=10,
        )
    except Exception as e:
        logger.error(f"Send failed: {e}")


def _get_updates(offset: int) -> list[dict]:
    try:
        resp = requests.get(
            _TG.format(token=os.getenv("TELEGRAM_BOT_TOKEN", ""), method="getUpdates"),
            params={"offset": offset, "timeout": 30, "allowed_updates": ["message"]},
            timeout=35,
        )
        resp.raise_for_status()
        return resp.json().get("result", [])
    except Exception as e:
        logger.error(f"getUpdates failed: {e}")
        return []


# ── Command handlers ──────────────────────────────────────────────────────────

def cmd_help(chat_id: str, _args: str) -> None:
    _send(
        "*SunChaser Bot* ✈\n\n"
        "/deals — top 5 cheapest flights right now\n"
        "/to `LHR` — best prices to a destination\n"
        "/mistakes — mistake fares (≥40% below avg)\n"
        "/awards `LHR` — best award redemptions\n"
        "/status — DB stats & last fetch time",
        chat_id,
    )


def cmd_deals(chat_id: str, _args: str) -> None:
    from db.database import get_session
    from db.models import FlightPrice, Route, Destination, DepartureAirport
    from sqlalchemy.orm import joinedload

    session = get_session()
    cutoff = datetime.utcnow() - timedelta(hours=24)
    rows = (
        session.query(FlightPrice, Route, Destination, DepartureAirport)
        .join(Route,             FlightPrice.route_id  == Route.id)
        .join(Destination,       Route.destination_id  == Destination.id)
        .join(DepartureAirport,  Route.origin_id       == DepartureAirport.id)
        .filter(
            FlightPrice.cabin_class == "economy",
            FlightPrice.fetched_at  >= cutoff,
            Route.is_active         == True,
        )
        .order_by(FlightPrice.price.asc())
        .limit(5)
        .all()
    )
    session.close()

    if not rows:
        _send("No flight data yet — run `python main.py --fetch` first.", chat_id)
        return

    lines = ["*✈ Top 5 Deals Right Now*\n"]
    for i, (fp, route, dest, orig) in enumerate(rows, 1):
        airline = fp.airline or "Various"
        stops   = "Nonstop" if (fp.stops or 0) == 0 else f"{fp.stops} stop(s)"
        lines.append(
            f"{i}. *{orig.iata_code} → {dest.iata_code}* — ${fp.price:,.0f}\n"
            f"   {dest.name} · {airline} · {stops}\n"
            f"   Departs {fp.departure_date}"
        )
    _send("\n".join(lines), chat_id)


def cmd_to(chat_id: str, args: str) -> None:
    from db.database import get_session
    from db.models import FlightPrice, Route, Destination, DepartureAirport

    if not args:
        _send("Usage: /to `LHR`  or  /to `London`", chat_id)
        return

    query = args.strip()
    session = get_session()
    cutoff = datetime.utcnow() - timedelta(hours=48)

    dest = (
        session.query(Destination)
        .filter(
            (Destination.iata_code == query.upper()) |
            (func.lower(Destination.name) == query.lower())
        )
        .first()
    )
    if not dest:
        session.close()
        _send(
            f"Destination *{query}* not found.\n"
            "Try an IATA code like `LHR`, `CDG`, `NRT`, `CUN`.",
            chat_id,
        )
        return

    rows = (
        session.query(FlightPrice, Route, DepartureAirport)
        .join(Route,            FlightPrice.route_id == Route.id)
        .join(DepartureAirport, Route.origin_id      == DepartureAirport.id)
        .filter(
            Route.destination_id    == dest.id,
            FlightPrice.cabin_class == "economy",
            FlightPrice.fetched_at  >= cutoff,
            Route.is_active         == True,
        )
        .order_by(FlightPrice.price.asc())
        .limit(6)
        .all()
    )
    session.close()

    if not rows:
        _send(f"No recent data for {dest.name}. Try running a fresh fetch.", chat_id)
        return

    lines = [f"*✈ Flights to {dest.name} ({dest.iata_code})*\n"]
    for fp, route, orig in rows:
        airline = fp.airline or "Various"
        stops   = "Nonstop" if (fp.stops or 0) == 0 else f"{fp.stops} stop(s)"
        dur     = (
            f"{fp.duration_minutes // 60}h {fp.duration_minutes % 60}m"
            if fp.duration_minutes else ""
        )
        lines.append(
            f"*{orig.iata_code} → {dest.iata_code}* — ${fp.price:,.0f}\n"
            f"   {airline} · {stops}{' · ' + dur if dur else ''}\n"
            f"   Departs {fp.departure_date}"
        )
    _send("\n".join(lines), chat_id)


def cmd_mistakes(chat_id: str, _args: str) -> None:
    from analytics import detect_mistake_fares

    _send("🔍 Scanning for mistake fares...", chat_id)
    found = detect_mistake_fares(notify=False)

    if not found:
        _send("No mistake fares detected right now.", chat_id)
        return

    lines = [f"*💥 {len(found)} Mistake Fare(s) Found*\n"]
    for f in found[:5]:
        pct_str = (
            f" (lowest {f['percentile']:.0f}% ever seen)"
            if f.get("percentile") is not None else ""
        )
        lines.append(
            f"*{f['origin']} → {f['dest_iata']}* — ${f['price']:.0f} {f['cabin']}\n"
            f"   Normal avg ${f['avg_price']:.0f} · *{f['drop_pct']}% off*{pct_str}\n"
            f"   {f['airline'] or 'Various'} · Departs {f['departs']}"
        )
    _send("\n".join(lines), chat_id)


def cmd_awards(chat_id: str, args: str) -> None:
    from db.database import get_session
    from db.models import AwardPrice, Route, Destination, LoyaltyProgram

    if not args:
        _send("Usage: /awards `LHR`", chat_id)
        return

    query = args.strip().upper()
    session = get_session()
    dest = session.query(Destination).filter(Destination.iata_code == query).first()
    if not dest:
        session.close()
        _send(f"Destination `{query}` not found.", chat_id)
        return

    rows = (
        session.query(AwardPrice, Route, LoyaltyProgram)
        .join(Route,         AwardPrice.route_id  == Route.id)
        .join(LoyaltyProgram,AwardPrice.program_id == LoyaltyProgram.id)
        .filter(
            Route.destination_id    == dest.id,
            AwardPrice.cabin_class  == "economy",
            Route.is_active         == True,
        )
        .order_by(AwardPrice.points_required.asc())
        .limit(5)
        .all()
    )
    session.close()

    if not rows:
        _send(
            f"No award data for {dest.name} yet.\n"
            "Refresh your seats.aero key and re-run `python main.py --fetch`.",
            chat_id,
        )
        return

    lines = [f"*🏆 Awards to {dest.name} ({dest.iata_code})*\n"]
    for ap, route, prog in rows:
        fees = f" + ${ap.cash_fees:.0f} fees" if ap.cash_fees else ""
        lines.append(
            f"*{ap.points_required:,} pts*{fees} — {prog.name}\n"
            f"   {ap.cabin_class.title()} · {ap.availability_date}"
        )
    _send("\n".join(lines), chat_id)


def cmd_status(chat_id: str, _args: str) -> None:
    from db.database import get_session
    from db.models import FlightPrice, AwardPrice, HotelPrice, Route

    session = get_session()
    flight_count = session.query(FlightPrice).count()
    award_count  = session.query(AwardPrice).count()
    hotel_count  = session.query(HotelPrice).count()
    route_count  = session.query(Route).filter(Route.is_active == True).count()
    last_fetch   = session.query(func.max(FlightPrice.fetched_at)).scalar()
    session.close()

    last_str = last_fetch.strftime("%b %d %H:%M UTC") if last_fetch else "Never"
    _send(
        f"*📊 SunChaser Status*\n\n"
        f"✈ Flight prices: {flight_count:,}\n"
        f"🏆 Award prices:  {award_count:,}\n"
        f"🏨 Hotel prices:  {hotel_count:,}\n"
        f"🛣 Active routes: {route_count}\n"
        f"🕐 Last fetch:   {last_str}",
        chat_id,
    )


# ── Dispatch ──────────────────────────────────────────────────────────────────

COMMANDS: dict[str, callable] = {
    "/help":     cmd_help,
    "/deals":    cmd_deals,
    "/to":       cmd_to,
    "/mistakes": cmd_mistakes,
    "/awards":   cmd_awards,
    "/status":   cmd_status,
}


def _handle(message: dict) -> None:
    text    = message.get("text", "").strip()
    chat_id = str(message["chat"]["id"])

    if not text.startswith("/"):
        _send("Send /help to see available commands.", chat_id)
        return

    parts   = text.split(None, 1)
    cmd     = parts[0].lower().split("@")[0]   # strip @BotName suffix
    args    = parts[1] if len(parts) > 1 else ""

    handler = COMMANDS.get(cmd)
    if handler:
        try:
            handler(chat_id, args)
        except Exception as e:
            logger.error(f"Handler error for {cmd}: {e}", exc_info=True)
            _send(f"⚠️ Something went wrong: `{e}`", chat_id)
    else:
        _send(f"Unknown command `{cmd}`. Send /help for the list.", chat_id)


# ── Polling loop ──────────────────────────────────────────────────────────────

def run() -> None:
    logger.info("SunChaser bot started — polling for messages...")
    offset = 0
    while True:
        updates = _get_updates(offset)
        for update in updates:
            offset = update["update_id"] + 1
            msg = update.get("message")
            if msg and "text" in msg:
                logger.info(f"← {msg['chat']['id']}: {msg['text']!r}")
                _handle(msg)
        # No sleep needed — long-polling already waits up to 30 s server-side


if __name__ == "__main__":
    run()
