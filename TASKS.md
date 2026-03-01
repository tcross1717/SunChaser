# SunChaser — Task Tracker

Legend: ✅ Done | 🔄 In Progress | ⬜ Not Started | ❌ Blocked

---

## Phase 1 — MVP ✅ Complete

### Setup & Infrastructure
- ✅ Create project directory structure
- ✅ Write PRD.md
- ✅ Write TASKS.md
- ✅ requirements.txt
- ✅ .env.example + .env (fill in your keys)
- ✅ Python 3.14 virtual environment (.venv)
- ✅ config/settings.yaml
- ✅ config/destinations.yaml
- ✅ config/loyalty_programs.yaml

### Database
- ✅ SQLAlchemy models (destinations, routes, prices, programs, alerts, hotels)
- ✅ Database init + session helpers
- ✅ Seed script (load config → DB)

### Data Fetching
- ✅ Amadeus flight price fetcher
- ✅ seats.aero award availability fetcher
- ✅ Amadeus hotel fetcher (full implementation)

### Alerting
- ✅ Telegram notifier (cash + points alerts)
- ✅ Alert history logging

### API & Dashboard
- ✅ FastAPI backend with REST endpoints
- ✅ Streamlit dashboard (9 tabs)

### Scheduler
- ✅ APScheduler daemon (flights, awards, hotels, mistake fares, weekly digest)

---

## Phase 2 — Enhancements ✅ Complete

- ✅ Price percentile tracking (analytics.py)
- ✅ Mistake fare detection — >40% drop from 90-day average (analytics.py)
- ✅ Price trend charts per route in dashboard (Price Trends tab)
- ✅ Cents-per-point displayed on all award rows (color-coded 🟢🟡🔴)
- ✅ Weekly Telegram digest — best deals of the week (alerts/digest.py)
- ✅ Flexible destination mode — any destination under $X (Flexible Search tab)
- ✅ Transfer partner optimizer — best credit card → airline path per destination (optimizer.py)

---

## Phase 3 — Hotels ✅ Complete

- ✅ HotelPrice SQLAlchemy model
- ✅ Amadeus Hotel Search fetcher (full implementation)
- ✅ Hotels tab in Streamlit dashboard
- ✅ Combined flight + hotel cost estimate per destination
- ✅ Hotel job added to scheduler (daily at 9:30am)

---

## Remaining: Your Setup Steps
- ⬜ Get Amadeus API credentials → https://developers.amadeus.com (free sandbox)
- ⬜ Get seats.aero Partner API key → https://seats.aero/partner-api
- ⬜ Create Telegram bot via @BotFather, get chat_id via @userinfobot
- ⬜ Fill in ~/SunChaser/.env with your keys
- ⬜ Run: `source .venv/bin/activate`
- ⬜ Run: `python main.py --init`
- ⬜ Run: `python main.py --fetch` (test flight + award data)
- ⬜ Run: `python main.py --fetch-hotels` (test hotel data)
- ⬜ Open 3 terminals and run: API server, dashboard, scheduler (see PRD.md)
- ⬜ Update loyalty_programs.yaml with your actual point balances
- ⬜ Add your real destinations to destinations.yaml

---

## Future Ideas
- ⬜ Push to a remote server (e.g. Railway, Render) so it runs 24/7 without your laptop
- ⬜ Postgres migration for production
- ⬜ Add more NYC-area airports (HPN, ISP) if useful
- ⬜ Seat map / aircraft type info
- ⬜ Fare class tracking (Y, J, F buckets)

---

## Bugs / Issues
<!-- Log issues here as you find them -->
