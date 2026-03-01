import logging
from apscheduler.schedulers.blocking import BlockingScheduler
from fetchers.scraper_fetcher import fetch_all_routes
from fetchers.award_fetcher import fetch_all_award_routes
from fetchers.hotel_fetcher import fetch_all_hotel_destinations
from alerts.notifier import run_all_checks
from analytics import detect_mistake_fares
from alerts.digest import send_weekly_digest

logger = logging.getLogger(__name__)


def start_scheduler():
    scheduler = BlockingScheduler()

    # Cash prices — once daily at 8:00am
    scheduler.add_job(fetch_all_routes, "cron", hour=8, minute=0, id="fetch_flights")

    # Award availability — twice daily at 8:30am and 8:30pm
    scheduler.add_job(fetch_all_award_routes, "cron", hour="8,20", minute=30, id="fetch_awards")

    # Alert checks + mistake fare scan — run after each fetch
    scheduler.add_job(run_all_checks, "cron", hour="9,21", minute=0, id="check_alerts")
    scheduler.add_job(detect_mistake_fares, "cron", hour="9,21", minute=15, id="mistake_fares")

    # Hotel prices — once daily at 9:00am
    scheduler.add_job(fetch_all_hotel_destinations, "cron", hour=9, minute=30, id="fetch_hotels")

    # Weekly digest — Sundays at 6:00pm
    scheduler.add_job(send_weekly_digest, "cron", day_of_week="sun", hour=18, minute=0, id="weekly_digest")

    logger.info("Scheduler started. SunChaser is watching for deals...")
    scheduler.start()
