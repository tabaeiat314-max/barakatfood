import logging

logger = logging.getLogger(__name__)

ADMIN_USER_IDS = [12345678]

async def send_reminder_push_job():
    logger.info("تست Job یادآوری")

async def send_daily_excel_report_job():
    logger.info("تست Job ارسال گزارش اکسل")
