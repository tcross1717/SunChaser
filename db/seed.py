import os
import yaml
import logging
from db.database import get_session
from db.models import DepartureAirport, Destination, Route, LoyaltyProgram, UserPoints

logger = logging.getLogger(__name__)

CONFIG_DIR = os.path.join(os.path.dirname(__file__), "..", "config")


def _load(filename: str) -> dict:
    with open(os.path.join(CONFIG_DIR, filename)) as f:
        return yaml.safe_load(f)


def seed_from_config():
    session = get_session()
    settings = _load("settings.yaml")
    destinations_cfg = _load("destinations.yaml")
    programs_cfg = _load("loyalty_programs.yaml")

    # Departure airports
    airports: dict[str, DepartureAirport] = {}
    for a in settings.get("departure_airports", []):
        obj = session.query(DepartureAirport).filter_by(iata_code=a["code"]).first()
        if not obj:
            obj = DepartureAirport(iata_code=a["code"], name=a["name"])
            session.add(obj)
            session.flush()
            logger.info(f"Added airport: {a['code']}")
        airports[a["code"]] = obj

    # Destinations + routes from each NYC airport
    for d in destinations_cfg.get("destinations", []):
        dest = session.query(Destination).filter_by(iata_code=d["iata_code"]).first()
        if not dest:
            dest = Destination(
                name=d["name"],
                iata_code=d["iata_code"],
                country=d.get("country"),
                region=d.get("region"),
                notes=d.get("notes"),
            )
            session.add(dest)
            session.flush()
            logger.info(f"Added destination: {d['name']}")

        for airport in airports.values():
            exists = session.query(Route).filter_by(
                origin_id=airport.id, destination_id=dest.id
            ).first()
            if not exists:
                session.add(Route(origin_id=airport.id, destination_id=dest.id))

    # Loyalty programs + user point balances
    for p in programs_cfg.get("programs", []):
        prog = session.query(LoyaltyProgram).filter_by(slug=p["id"]).first()
        if not prog:
            prog = LoyaltyProgram(
                slug=p["id"],
                name=p["name"],
                program_type=p["type"],
                currency_name=p.get("currency", "points"),
                transfer_partners=p.get("transfer_partners", []),
            )
            session.add(prog)
            session.flush()
            logger.info(f"Added program: {p['name']}")

        pts = session.query(UserPoints).filter_by(program_id=prog.id).first()
        if not pts:
            session.add(UserPoints(program_id=prog.id, balance=p.get("balance", 0)))
        else:
            pts.balance = p.get("balance", pts.balance)

    session.commit()
    session.close()
    logger.info("Seed complete.")
