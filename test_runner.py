import os
import sys
import asyncio
import logging

# افزودن پوشه backend به مسیرهای شناسایی پایتون
sys.path.insert(0, os.path.abspath("backend"))
sys.path.insert(0, os.path.abspath("."))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("TestRunner")


async def run_diagnostics():
    print("\n==================================================")
    print("🚀 شروع عیب‌یابی و تست عملکرد سیستم غذا")
    print("==================================================\n")

    print("[۱/۴] تست اتصال دیتابیس و توابع خلاصه آمار...")
    try:
        from app.db import SessionLocal
        from app.bale.router import get_daily_summary_text, get_unregistered_employees_text

        db = SessionLocal()
        
        summary = get_daily_summary_text(db)
        print("  ✅ خروجی خلاصه آمار متنی:")
        print("  ---------------------------------")
        print(summary)
        print("  ---------------------------------")

        unregistered = get_unregistered_employees_text(db)
        print("  ✅ خروجی اسامی افراد بدون سفارش:")
        print("  ---------------------------------")
        print(unregistered)
        print("  ---------------------------------")
        
        db.close()
    except Exception as e:
        print(f"  ❌ خطا در بخش دیتابیس یا گزارش‌های متنی: {e}\n")

    print("[۲/۴] تست تولید اکسل گزارش سفارشات...")
    try:
        from app.db import SessionLocal
        from app.routers.reports import export_daily_orders_excel

        db = SessionLocal()
        res = export_daily_orders_excel(target_date=None, db=db)
        print(f"  ✅ تولید اکسل موفقیت‌آمیز بود. حجم فایل خروجی: {len(res.body)} بایت")
        db.close()
    except Exception as e:
        print(f"  ❌ خطا در تولید اکسل: {e}\n")

    print("[۳/۴] تست اجرای Jobهای APScheduler...")
    try:
        from app.services.scheduler import send_reminder_push_job, send_daily_excel_report_job

        print("  ⌛ اجرای send_reminder_push_job()...")
        await send_reminder_push_job()
        print("  ✅ Job یادآوری بدون کرش اجرا شد.")

        print("  ⌛ اجرای send_daily_excel_report_job()...")
        await send_daily_excel_report_job()
        print("  ✅ Job ارسال اکسل بدون کرش اجرا شد.")
    except Exception as e:
        print(f"  ❌ خطا در اجرای Jobها: {e}\n")

    print("\n==================================================")
    print("🏁 تست پایان یافت.")
    print("==================================================\n")


if __name__ == "__main__":
    asyncio.run(run_diagnostics())
