from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Float, DateTime, Boolean,
    ForeignKey, JSON, Text, UniqueConstraint,
)
from sqlalchemy.orm import relationship, declarative_base

Base = declarative_base()


class DepartureAirport(Base):
    __tablename__ = "departure_airports"

    id = Column(Integer, primary_key=True)
    iata_code = Column(String(3), unique=True, nullable=False)
    name = Column(String, nullable=False)
    city = Column(String, nullable=False, default="New York")

    routes = relationship("Route", back_populates="origin")


class Destination(Base):
    __tablename__ = "destinations"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    iata_code = Column(String(3), unique=True, nullable=False)
    country = Column(String)
    region = Column(String)
    notes = Column(Text)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    routes = relationship("Route", back_populates="destination")
    alerts = relationship("Alert", back_populates="destination")


class Route(Base):
    __tablename__ = "routes"
    __table_args__ = (UniqueConstraint("origin_id", "destination_id"),)

    id = Column(Integer, primary_key=True)
    origin_id = Column(Integer, ForeignKey("departure_airports.id"), nullable=False)
    destination_id = Column(Integer, ForeignKey("destinations.id"), nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    origin = relationship("DepartureAirport", back_populates="routes")
    destination = relationship("Destination", back_populates="routes")
    flight_prices = relationship("FlightPrice", back_populates="route")
    award_prices = relationship("AwardPrice", back_populates="route")


class FlightPrice(Base):
    __tablename__ = "flight_prices"

    id = Column(Integer, primary_key=True)
    route_id = Column(Integer, ForeignKey("routes.id"), nullable=False)
    price = Column(Float, nullable=False)
    currency = Column(String(3), default="USD")
    departure_date = Column(String)       # YYYY-MM-DD
    return_date = Column(String)
    trip_length_days = Column(Integer)
    airline = Column(String)
    cabin_class = Column(String, default="economy")
    source = Column(String, default="google_flights")
    fetched_at = Column(DateTime, default=datetime.utcnow)
    # Detail fields
    stops = Column(Integer, default=0)
    departure_time = Column(String)       # HH:MM
    arrival_time = Column(String)         # HH:MM
    terminal = Column(String)             # departure terminal, e.g. "5" or "B"
    duration_minutes = Column(Integer)
    flight_number = Column(String)

    route = relationship("Route", back_populates="flight_prices")


class LoyaltyProgram(Base):
    __tablename__ = "loyalty_programs"

    id = Column(Integer, primary_key=True)
    slug = Column(String, unique=True, nullable=False)
    name = Column(String, nullable=False)
    program_type = Column(String, nullable=False)   # "credit_card" or "airline"
    currency_name = Column(String, default="points")
    transfer_partners = Column(JSON)                # list of partner slugs
    notes = Column(Text)

    user_points = relationship("UserPoints", back_populates="program", uselist=False)
    award_prices = relationship("AwardPrice", back_populates="program")


class UserPoints(Base):
    __tablename__ = "user_points"

    id = Column(Integer, primary_key=True)
    program_id = Column(Integer, ForeignKey("loyalty_programs.id"), nullable=False, unique=True)
    balance = Column(Integer, default=0)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    program = relationship("LoyaltyProgram", back_populates="user_points")


class AwardPrice(Base):
    __tablename__ = "award_prices"

    id = Column(Integer, primary_key=True)
    route_id = Column(Integer, ForeignKey("routes.id"), nullable=False)
    program_id = Column(Integer, ForeignKey("loyalty_programs.id"), nullable=False)
    points_required = Column(Integer)
    cash_fees = Column(Float)
    cabin_class = Column(String, default="economy")
    availability_date = Column(String)   # YYYY-MM-DD
    fetched_at = Column(DateTime, default=datetime.utcnow)

    route = relationship("Route", back_populates="award_prices")
    program = relationship("LoyaltyProgram", back_populates="award_prices")


class Alert(Base):
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True)
    destination_id = Column(Integer, ForeignKey("destinations.id"), nullable=False)
    max_cash_price = Column(Float)
    max_points = Column(Integer)
    program_id = Column(Integer, ForeignKey("loyalty_programs.id"), nullable=True)
    cabin_class = Column(String, default="economy")
    alert_type = Column(String, default="cash")   # "cash", "points", "both"
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    destination = relationship("Destination", back_populates="alerts")
    history = relationship("AlertHistory", back_populates="alert")


class AlertHistory(Base):
    __tablename__ = "alert_history"

    id = Column(Integer, primary_key=True)
    alert_id = Column(Integer, ForeignKey("alerts.id"), nullable=False)
    triggered_at = Column(DateTime, default=datetime.utcnow)
    price_found = Column(Float)
    points_found = Column(Integer)
    message = Column(Text)
    sent_at = Column(DateTime)

    alert = relationship("Alert", back_populates="history")


# ── Hotels ────────────────────────────────────────────────────────────────────

class HotelPrice(Base):
    __tablename__ = "hotel_prices"

    id = Column(Integer, primary_key=True)
    destination_id = Column(Integer, ForeignKey("destinations.id"), nullable=False)
    hotel_name = Column(String, nullable=False)
    hotel_id = Column(String)               # Amadeus hotel ID
    price_per_night = Column(Float, nullable=False)
    currency = Column(String(3), default="USD")
    check_in = Column(String)               # YYYY-MM-DD
    check_out = Column(String)
    nights = Column(Integer)
    rating = Column(Float)                  # star rating if available
    source = Column(String, default="amadeus")
    fetched_at = Column(DateTime, default=datetime.utcnow)

    destination = relationship("Destination", back_populates="hotel_prices")


# Add back-reference to Destination
Destination.hotel_prices = relationship("HotelPrice", back_populates="destination")
