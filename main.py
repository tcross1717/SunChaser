import os
import logging
import argparse
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="SunChaser — Flight & Award Price Tracker")
    parser.add_argument("--init", action="store_true", help="Init DB and seed from config files")
    parser.add_argument("--fetch", action="store_true", help="Run a one-time flight + award fetch")
    parser.add_argument("--fetch-hotels", action="store_true", help="Run a one-time hotel fetch")
    parser.add_argument("--check", action="store_true", help="Run alert checks now")
    parser.add_argument("--serve", action="store_true", help="Start the FastAPI server")
    parser.add_argument("--schedule", action="store_true", help="Start the scheduler daemon")
    args = parser.parse_args()

    from db.database import init_db
    init_db()

    if args.init:
        from db.seed import seed_from_config
        seed_from_config()
        logger.info("Database initialized and seeded from config.")
        return

    if args.fetch:
        from fetchers.scraper_fetcher import fetch_all_routes
        from fetchers.award_fetcher import fetch_all_award_routes
        fetch_all_routes()
        fetch_all_award_routes()
        return

    if args.fetch_hotels:
        from fetchers.hotel_fetcher import fetch_all_hotel_destinations
        fetch_all_hotel_destinations()
        return

    if args.check:
        from alerts.notifier import run_all_checks
        run_all_checks()
        return

    if args.serve:
        import uvicorn
        uvicorn.run("api.app:app", host="0.0.0.0", port=8000, reload=True)
        return

    # Default: start scheduler
    from scheduler.jobs import start_scheduler
    start_scheduler()


if __name__ == "__main__":
    main()
