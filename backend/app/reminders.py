"""
یادآوری خودکار مهلت ثبت سفارش برای کارمندانی که هنوز سفارش نداده‌اند.
"""
from datetime import datetime, timedelta, date as date_type

from app.db import SessionLocal
from app.models import Employee, MenuEntry, PersonalOrder, Setting
from app.bale.router import IRAN_TZ, ADMIN_ROLES, get_setting_value, build_kitchen_report_lines, to_jalali
from app.bale.client import send_message


def _reminder_already_sent(db, key: str, today_str: str) -> bool:
    setting = db.query(Setting).filter(Setting.key == key).first()
    return setting is not None and setting.value == today_str


def _mark_reminder_sent(db, key: str, today_str: str):
    setting = db.query(Setting).filter(Setting.key == key).first()
    if setting:
        setting.value = today_str
    else:
        setting = Setting(
            key=key,
            value=today_str,
            value_type="داخلی",
            description="آخرین تاریخ ارسال یادآوری خودکار (داخلی، دستی تغییر ندهید)",
        )
        db.add(setting)
    db.commit()


async def _send_reminder_for_date(db, target_date: date_type, deadline_label: str) -> int:
    order_date_idx = 1 if target_date == datetime.now(IRAN_TZ).date() else 2
    quick_order_keyboard = {
        "inline_keyboard": [
            [{"text": "🍽 سفارش سریع", "callback_data": f"order_date:{order_date_idx}"}]
        ]
    }
    site_ids_with_menu = {
        row[0]
        for row in db.query(MenuEntry.site_id)
        .filter(MenuEntry.date == target_date, MenuEntry.status == "منتشر")
        .distinct()
    }
    if not site_ids_with_menu:
        return 0

    employees = (
        db.query(Employee)
        .filter(
            Employee.is_active == True,  # noqa: E712
            Employee.site_id.in_(site_ids_with_menu),
            Employee.bale_chat_id.isnot(None),
        )
        .all()
    )

    ordered_employee_ids = {
        row[0]
        for row in db.query(PersonalOrder.employee_id)
        .filter(
            PersonalOrder.date == target_date,
            PersonalOrder.status != "لغو شده",
        )
        .distinct()
    }

    sent_count = 0
    for emp in employees:
        if emp.id in ordered_employee_ids:
            continue
        try:
            await send_message(
                emp.bale_chat_id,
                f"⏰ یادآوری: مهلت ثبت سفارش غذای {deadline_label} رو به پایان است "
                "و شما هنوز سفارش ثبت نکرده‌اید.\n"
                "برای ثبت سفارش، دستور /order را ارسال کنید.",
                reply_markup=quick_order_keyboard,
            )
            sent_count += 1
        except Exception:
            pass
    return sent_count


async def _send_kitchen_report_for_date(db, target_date):
    lines = build_kitchen_report_lines(db, target_date)
    if not lines:
        return

    admins = (
        db.query(Employee)
        .filter(
            Employee.role.in_(ADMIN_ROLES),
            Employee.is_active == True,  # noqa: E712
            Employee.bale_chat_id.isnot(None),
        )
        .all()
    )

    message = "📊 گزارش خودکار آشپزخانه (رأس مهلت سفارش)\n\n" + "\n".join(lines)

    for admin in admins:
        try:
            await send_message(admin.bale_chat_id, message)
        except Exception:
            pass


async def check_and_send_reminders():
    db = SessionLocal()
    try:
        if get_setting_value(db, "REMINDER_ENABLED", "بله") != "بله":
            return

        now = datetime.now(IRAN_TZ)
        today = now.date()
        today_str = today.isoformat()

        lead_minutes = int(get_setting_value(db, "REMINDER_LEAD_MINUTES", "30"))

        same_day_deadline_str = get_setting_value(db, "SAME_DAY_DEADLINE", "09:00")
        sd_h, sd_m = map(int, same_day_deadline_str.split(":"))
        sd_deadline_dt = now.replace(hour=sd_h, minute=sd_m, second=0, microsecond=0)
        if timedelta(0) <= (sd_deadline_dt - now) <= timedelta(minutes=lead_minutes):
            key = "REMINDER_SENT_SAMEDAY"
            if not _reminder_already_sent(db, key, today_str):
                await _send_reminder_for_date(db, today, "امروز")
                _mark_reminder_sent(db, key, today_str)

            report_key = "KITCHEN_REPORT_SENT_SAMEDAY"
            if not _reminder_already_sent(db, report_key, today_str):
                await _send_kitchen_report_for_date(db, today)
                _mark_reminder_sent(db, report_key, today_str)

        normal_deadline_str = get_setting_value(db, "NORMAL_DEADLINE", "15:00")
        nd_h, nd_m = map(int, normal_deadline_str.split(":"))
        nd_deadline_dt = now.replace(hour=nd_h, minute=nd_m, second=0, microsecond=0)
        if timedelta(0) <= (nd_deadline_dt - now) <= timedelta(minutes=lead_minutes):
            key = "REMINDER_SENT_NORMAL"
            tomorrow = today + timedelta(days=1)
            if not _reminder_already_sent(db, key, today_str):
                await _send_reminder_for_date(db, tomorrow, "فردا")
                _mark_reminder_sent(db, key, today_str)

            report_key = "KITCHEN_REPORT_SENT_NORMAL"
            if not _reminder_already_sent(db, report_key, today_str):
                await _send_kitchen_report_for_date(db, tomorrow)
                _mark_reminder_sent(db, report_key, today_str)
    finally:
        db.close()
