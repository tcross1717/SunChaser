from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel
from db.database import get_session
from db.models import (
    Destination, Route, FlightPrice, AwardPrice,
    LoyaltyProgram, UserPoints, Alert,
)

router = APIRouter()


def db():
    session = get_session()
    try:
        yield session
    finally:
        session.close()


# ── Destinations ──────────────────────────────────────────────────────────────

@router.get("/destinations")
def list_destinations(session: Session = Depends(db)):
    return [
        {"id": d.id, "name": d.name, "iata_code": d.iata_code,
         "country": d.country, "region": d.region, "is_active": d.is_active}
        for d in session.query(Destination).all()
    ]


@router.patch("/destinations/{dest_id}/toggle")
def toggle_destination(dest_id: int, session: Session = Depends(db)):
    dest = session.get(Destination, dest_id)
    if not dest:
        raise HTTPException(status_code=404, detail="Destination not found")
    dest.is_active = not dest.is_active
    session.commit()
    return {"id": dest.id, "is_active": dest.is_active}


# ── Prices ────────────────────────────────────────────────────────────────────

@router.get("/prices/cash")
def cash_prices(
    destination_iata: str | None = None,
    cabin: str = "economy",
    limit: int = 50,
    session: Session = Depends(db),
):
    query = (
        session.query(FlightPrice, Route, Destination)
        .join(Route, FlightPrice.route_id == Route.id)
        .join(Destination, Route.destination_id == Destination.id)
        .filter(FlightPrice.cabin_class == cabin, Route.is_active == True)
    )
    if destination_iata:
        query = query.filter(Destination.iata_code == destination_iata.upper())

    rows = query.order_by(FlightPrice.price.asc()).limit(limit).all()
    return [
        {
            "destination": dest.name,
            "iata": dest.iata_code,
            "origin": route.origin.iata_code,
            "price": fp.price,
            "currency": fp.currency,
            "cabin": fp.cabin_class,
            "airline": fp.airline,
            "departs": fp.departure_date,
            "returns": fp.return_date,
            "fetched_at": fp.fetched_at,
        }
        for fp, route, dest in rows
    ]


@router.get("/prices/awards")
def award_prices(
    destination_iata: str | None = None,
    program_slug: str | None = None,
    cabin: str = "economy",
    limit: int = 50,
    session: Session = Depends(db),
):
    query = (
        session.query(AwardPrice, Route, Destination, LoyaltyProgram)
        .join(Route, AwardPrice.route_id == Route.id)
        .join(Destination, Route.destination_id == Destination.id)
        .join(LoyaltyProgram, AwardPrice.program_id == LoyaltyProgram.id)
        .filter(AwardPrice.cabin_class == cabin, Route.is_active == True)
    )
    if destination_iata:
        query = query.filter(Destination.iata_code == destination_iata.upper())
    if program_slug:
        query = query.filter(LoyaltyProgram.slug == program_slug)

    rows = query.order_by(AwardPrice.points_required.asc()).limit(limit).all()
    return [
        {
            "destination": dest.name,
            "iata": dest.iata_code,
            "origin": route.origin.iata_code,
            "program": prog.name,
            "program_slug": prog.slug,
            "points": ap.points_required,
            "cash_fees": ap.cash_fees,
            "cabin": ap.cabin_class,
            "date": ap.availability_date,
            "fetched_at": ap.fetched_at,
        }
        for ap, route, dest, prog in rows
    ]


# ── Points Balances ───────────────────────────────────────────────────────────

@router.get("/points")
def list_points(session: Session = Depends(db)):
    rows = (
        session.query(UserPoints, LoyaltyProgram)
        .join(LoyaltyProgram, UserPoints.program_id == LoyaltyProgram.id)
        .all()
    )
    return [
        {
            "program": prog.name,
            "slug": prog.slug,
            "type": prog.program_type,
            "currency": prog.currency_name,
            "balance": up.balance,
            "updated_at": up.updated_at,
        }
        for up, prog in rows
    ]


class PointsUpdate(BaseModel):
    balance: int


@router.patch("/points/{slug}")
def update_points(slug: str, body: PointsUpdate, session: Session = Depends(db)):
    prog = session.query(LoyaltyProgram).filter_by(slug=slug).first()
    if not prog:
        raise HTTPException(status_code=404, detail="Program not found")
    up = session.query(UserPoints).filter_by(program_id=prog.id).first()
    if not up:
        raise HTTPException(status_code=404, detail="UserPoints record not found")
    up.balance = body.balance
    session.commit()
    return {"slug": slug, "balance": up.balance}


# ── Alerts ────────────────────────────────────────────────────────────────────

class AlertCreate(BaseModel):
    destination_iata: str
    alert_type: str = "cash"       # "cash", "points", "both"
    max_cash_price: float | None = None
    max_points: int | None = None
    program_slug: str | None = None
    cabin_class: str = "economy"


@router.get("/alerts")
def list_alerts(session: Session = Depends(db)):
    alerts = session.query(Alert).filter(Alert.is_active == True).all()
    return [
        {
            "id": a.id,
            "destination": a.destination.name,
            "type": a.alert_type,
            "max_cash": a.max_cash_price,
            "max_points": a.max_points,
            "cabin": a.cabin_class,
        }
        for a in alerts
    ]


@router.post("/alerts", status_code=201)
def create_alert(body: AlertCreate, session: Session = Depends(db)):
    dest = session.query(Destination).filter_by(iata_code=body.destination_iata.upper()).first()
    if not dest:
        raise HTTPException(status_code=404, detail="Destination not found")

    program_id = None
    if body.program_slug:
        prog = session.query(LoyaltyProgram).filter_by(slug=body.program_slug).first()
        if not prog:
            raise HTTPException(status_code=404, detail="Program not found")
        program_id = prog.id

    alert = Alert(
        destination_id=dest.id,
        alert_type=body.alert_type,
        max_cash_price=body.max_cash_price,
        max_points=body.max_points,
        program_id=program_id,
        cabin_class=body.cabin_class,
    )
    session.add(alert)
    session.commit()
    return {"id": alert.id, "destination": dest.name, "type": alert.alert_type}


@router.delete("/alerts/{alert_id}")
def delete_alert(alert_id: int, session: Session = Depends(db)):
    alert = session.get(Alert, alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    alert.is_active = False
    session.commit()
    return {"deleted": alert_id}
