# SunChaser — Product Requirements Document

## Overview
SunChaser is a personal flight, award, and hotel price tracker for travel out of the New York City area (JFK, EWR, LGA). It monitors cash fares, points/miles redemptions across all major loyalty programs, and hotel prices — then sends Telegram alerts when prices hit your thresholds and provides a web dashboard to view deals and manage your watchlist.

---

## Goals
- Save money on flights by catching price drops automatically
- Maximize value from credit card points (Amex MR, Chase UR) and airline miles
- Minimize days off work by surfacing the best fare-per-day-off options
- Travel to interesting destinations with minimal manual searching

---

## Out of Scope
- Google Calendar integration
- Visa requirement lookups

---

## Users
- Single user (personal use), operating from the NYC metro area

---

## Core Features

### Phase 1 — MVP ✅
- Destination watchlist via config file
- Poll Amadeus API for round-trip cash fares (JFK, EWR, LGA → all destinations)
- Poll seats.aero API for award seat availability across all loyalty programs
- Store full price history in SQLite database
- Telegram alerts when cash or points prices fall below user thresholds
- FastAPI backend with REST endpoints
- Streamlit dashboard: 9 tabs covering all features

### Phase 2 — Enhancements ✅
- Price percentile tracking — is today's price cheap vs. 90-day history?
- Mistake fare detection — alert on drops >40% below average
- Price trend charts per route (line chart in dashboard)
- Cents-per-point calculator on all award prices (color-coded 🟢🟡🔴)
- Weekly Telegram digest — best cash and award deals of the past 7 days
- Flexible destination mode — "any destination under $X from NYC"
- Transfer partner optimizer — best credit card → airline transfer path per destination

### Phase 3 — Hotels ✅
- Amadeus Hotel Search API integration
- HotelPrice table (linked to destinations)
- Hotels tab in dashboard with best rates per destination
- Combined flight + hotel total cost estimate

---

## Data Sources
| Data | Source | Cost |
|---|---|---|
| Cash flight prices | Amadeus API | Free sandbox / paid production |
| Award availability | seats.aero Partner API | Paid tier required |
| Hotel prices | Amadeus Hotel Search API | Same credentials as flights |
| Alerts | Telegram Bot API | Free |

---

## Tech Stack
| Component | Choice |
|---|---|
| Language | Python 3.14 |
| API backend | FastAPI + Uvicorn |
| Dashboard | Streamlit (9 tabs) |
| Database | SQLite (upgradeable to Postgres) |
| ORM | SQLAlchemy |
| Scheduler | APScheduler |
| Alerting | Telegram Bot API |

---

## Loyalty Programs Tracked
**Credit Cards:** Amex Membership Rewards, Chase Ultimate Rewards

**Airlines:** Delta SkyMiles, United MileagePlus, American AAdvantage, JetBlue TrueBlue, Southwest Rapid Rewards, Alaska Mileage Plan, Air Canada Aeroplan, Air France/KLM Flying Blue, British Airways Avios, Emirates Skywards, Singapore KrisFlyer, Virgin Atlantic, Turkish Miles&Smiles, Cathay Pacific Asia Miles, Etihad Guest, ANA Mileage Club

---

## Alert Types
| Type | Trigger |
|---|---|
| Cash alert | Round-trip price drops below $X |
| Points alert | Award seat available for under N points |
| Both | Either condition |
| Mistake fare | Price drops >40% below 90-day average |
| Weekly digest | Best deals of the week, every Sunday 6pm |

---

## Scheduler
| Job | Schedule |
|---|---|
| Fetch cash prices | Daily 8:00am |
| Fetch award availability | Daily 8:30am and 8:30pm |
| Run alert checks | Daily 9:00am and 9:00pm |
| Mistake fare scan | Daily 9:15am and 9:15pm |
| Fetch hotel prices | Daily 9:30am |
| Weekly digest | Sundays 6:00pm |

---

## Running the App

```bash
# 1. Activate virtual environment
cd ~/SunChaser
source .venv/bin/activate

# 2. Fill in API keys
cp .env.example .env   # then edit .env

# 3. Initialize database and seed from config
python main.py --init

# 4. One-time data fetch to populate
python main.py --fetch
python main.py --fetch-hotels

# 5. Terminal 1 — API server
python main.py --serve

# 6. Terminal 2 — Streamlit dashboard
streamlit run dashboard/app.py

# 7. Terminal 3 — Scheduler daemon
python main.py --schedule
```

---

## File Structure
```
SunChaser/
├── PRD.md
├── TASKS.md
├── main.py                     ← Entry point
├── requirements.txt
├── .env.example / .env
├── analytics.py                ← Price percentile + mistake fare detection
├── optimizer.py                ← Transfer partner optimizer
├── config/
│   ├── settings.yaml
│   ├── destinations.yaml
│   └── loyalty_programs.yaml
├── db/
│   ├── models.py               ← All ORM models (incl. HotelPrice)
│   ├── database.py
│   └── seed.py
├── fetchers/
│   ├── flight_fetcher.py       ← Amadeus cash prices
│   ├── award_fetcher.py        ← seats.aero award availability
│   └── hotel_fetcher.py        ← Amadeus hotel prices
├── alerts/
│   ├── notifier.py             ← Telegram alerts + alert history
│   └── digest.py               ← Weekly digest + flexible destination search
├── scheduler/
│   └── jobs.py                 ← APScheduler (all jobs)
├── api/
│   ├── app.py
│   └── routes.py               ← REST endpoints
└── dashboard/
    └── app.py                  ← Streamlit (9 tabs)
```

---

## API Endpoints
| Method | Path | Description |
|---|---|---|
| GET | /api/destinations | List all destinations |
| PATCH | /api/destinations/{id}/toggle | Activate/pause a destination |
| GET | /api/prices/cash | Best cash prices (filterable) |
| GET | /api/prices/awards | Best award prices (filterable) |
| GET | /api/points | All loyalty program balances |
| PATCH | /api/points/{slug} | Update a program balance |
| GET | /api/alerts | Active alerts |
| POST | /api/alerts | Create an alert |
| DELETE | /api/alerts/{id} | Delete an alert |
