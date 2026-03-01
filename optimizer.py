"""
Transfer partner optimizer.

Given a destination, shows which credit card programs (Amex MR, Chase UR)
can transfer to airline programs that have award availability — ranked by
lowest points cost and best cents-per-point value.
"""
from db.database import get_session
from db.models import AwardPrice, Route, Destination, LoyaltyProgram, UserPoints


def optimize_transfers(destination_iata: str, cabin: str = "economy") -> list[dict]:
    """
    For a destination, find all award options reachable via credit card transfers.
    Returns a ranked list of (credit card → airline program → route) with:
      - points required (in airline currency after transfer)
      - cash fees
      - whether the user has enough points to cover it
      - estimated cents per point vs a reference cash price
    """
    session = get_session()

    dest = session.query(Destination).filter_by(iata_code=destination_iata.upper()).first()
    if not dest:
        session.close()
        return []

    routes = (
        session.query(Route)
        .filter(Route.destination_id == dest.id, Route.is_active == True)
        .all()
    )

    # Load all credit card programs with their transfer partners
    cc_programs = (
        session.query(LoyaltyProgram)
        .filter(LoyaltyProgram.program_type == "credit_card")
        .all()
    )

    # Load all airline programs keyed by slug
    airline_programs = {
        p.slug: p
        for p in session.query(LoyaltyProgram).filter(LoyaltyProgram.program_type == "airline").all()
    }

    # User balances keyed by program_id
    balances = {up.program_id: up.balance for up in session.query(UserPoints).all()}

    results = []

    for route in routes:
        # Best cash price for reference (for cpp calculation)
        from db.models import FlightPrice
        best_cash = (
            session.query(FlightPrice)
            .filter(FlightPrice.route_id == route.id, FlightPrice.cabin_class == cabin)
            .order_by(FlightPrice.price.asc())
            .first()
        )
        cash_reference = best_cash.price if best_cash else None

        # All award options for this route
        award_rows = (
            session.query(AwardPrice, LoyaltyProgram)
            .join(LoyaltyProgram, AwardPrice.program_id == LoyaltyProgram.id)
            .filter(AwardPrice.route_id == route.id, AwardPrice.cabin_class == cabin)
            .order_by(AwardPrice.points_required.asc())
            .all()
        )

        for award, airline_prog in award_rows:
            if not award.points_required:
                continue

            # Which credit cards can transfer to this airline?
            transferable_from = [
                cc for cc in cc_programs
                if cc.transfer_partners and airline_prog.slug in cc.transfer_partners
            ]

            for cc in transferable_from:
                cc_balance = balances.get(cc.id, 0)
                can_book = cc_balance >= award.points_required

                cpp = None
                if cash_reference and award.points_required:
                    effective_cash = cash_reference - (award.cash_fees or 0)
                    cpp = round((effective_cash / award.points_required) * 100, 2)

                results.append({
                    "origin": route.origin.iata_code,
                    "destination": dest.name,
                    "dest_iata": dest.iata_code,
                    "credit_card": cc.name,
                    "cc_slug": cc.slug,
                    "airline_program": airline_prog.name,
                    "airline_slug": airline_prog.slug,
                    "points_required": award.points_required,
                    "cash_fees": award.cash_fees or 0,
                    "cabin": cabin,
                    "date": award.availability_date,
                    "cc_balance": cc_balance,
                    "can_book": can_book,
                    "points_needed": max(0, award.points_required - cc_balance),
                    "cents_per_point": cpp,
                    "cash_reference": cash_reference,
                })

    session.close()

    # Sort: bookable first, then by cents per point descending (higher = better value)
    results.sort(key=lambda r: (-r["can_book"], -(r["cents_per_point"] or 0)))
    return results
