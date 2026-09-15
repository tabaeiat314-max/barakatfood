import asyncio
import random
import time

import jdatetime
import re
import string
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Request
from sqlalchemy import func

from app.bale.client import (
    answer_callback_query,
    delete_message,
    edit_message_text,
    main_menu_keyboard,
    remove_keyboard,
    request_contact,
    send_message,
)
from app.db import SessionLocal
from app.models import (
    Company,
    Employee,
    Food,
    MenuEntry,
    PersonalOrder,
    Setting,
    Site,
    WelfareManagerAssignment,
    WelfareOrder,
)

router = APIRouter()

IRAN_TZ = timezone(timedelta(hours=3, minutes=30))


async def _delete_later(chat_id, message_id, delay: float = 0.05):
    """حذف پیام کاربر بعد از تاخیر کوتاه (برای فلوی welfare)."""
    await asyncio.sleep(delay)
    try:
        await delete_message(chat_id, message_id)
    except Exception:
        pass


_WELFARE_LOCKS: dict = {}
_MENU_LOCKS: dict = {}


def _get_welfare_lock(chat_id):
    key = str(chat_id)
    lock = _WELFARE_LOCKS.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _WELFARE_LOCKS[key] = lock
    return lock


def _get_menu_lock(chat_id):
    key = str(chat_id)
    lock = _MENU_LOCKS.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _MENU_LOCKS[key] = lock
    return lock

# وضعیت موقت مکالمه هر کاربر
SESSIONS: dict[str, dict] = {}
_LAST_MSG_IDS: dict[str, dict] = {}
_MENU_MSGS: dict[str, list] = {}


async def _delete_menu_msgs(chat_id):
    """حذف همه‌ی پیام‌های ربات در فلوی menu (پایدار، خارج از session)."""
    key = str(chat_id)
    ids = _MENU_MSGS.pop(key, [])
    print(f"[DBG-MENUDEL] chat={chat_id} ids={ids}", flush=True)
    for mid in ids:
        try:
            r = await delete_message(chat_id, mid)
            print(f"[DBG-MENUDEL] deleted mid={mid} result={r}", flush=True)
        except Exception as e:
            print(f"[DBG-MENUDEL] error mid={mid}: {e}", flush=True)


def _track_menu_msg(chat_id, mid):
    if not mid:
        return
    key = str(chat_id)
    _MENU_MSGS.setdefault(key, []).append(mid)

ADMIN_ROLES = {"ادمین", "مدیر سیستم", "مدیر سیستم تست"}

BUTTON_COMMANDS = {
    "🍽 سفارش": "/order",
    "📋 سفارش‌های من": "/myorder",
    "❌ لغو سفارش": "/cancel",
    "👨‍💼 سفارش گروهی": "/welfare",
    "⚙️ مدیریت منو": "/menu",
    "📊 گزارش": "/report",
    "⚙️ مدیریت سیستم": "/sysadmin",
    "ℹ️ راهنما": "/help",
}


# =========================================================
# ابزارهای عمومی
# =========================================================

def now_iran() -> datetime:
    return datetime.now(IRAN_TZ)


def today_iran() -> date:
    return now_iran().date()


def to_jalali(g_date: date) -> str:
    j = jdatetime.date.fromgregorian(date=g_date)
    return j.strftime("%Y/%m/%d")


def normalize_mobile(raw: str) -> str:
    digits = re.sub(r"\D", "", raw or "")

    if digits.startswith("98"):
        digits = "0" + digits[2:]

    if digits.startswith("9") and len(digits) == 10:
        digits = "0" + digits

    return digits


def get_setting_value(db, key: str, default: str) -> str:
    row = db.query(Setting).filter(Setting.key == key).first()
    return row.value if row else default


def parse_time(value: str, default_hour: int, default_minute: int):
    try:
        h, m = value.split(":")
        return int(h), int(m)
    except (ValueError, AttributeError):
        return default_hour, default_minute


def deadline_today(db, setting_key: str, default: str) -> datetime:
    value = get_setting_value(db, setting_key, default)
    hour, minute = parse_time(value, 9, 0)

    current = now_iran()

    return current.replace(
        hour=hour,
        minute=minute,
        second=0,
        microsecond=0,
    )


def same_day_deadline_passed(db) -> bool:
    return now_iran() > deadline_today(
        db,
        "SAME_DAY_DEADLINE",
        "09:00",
    )


def normal_deadline_passed(db) -> bool:
    return now_iran() > deadline_today(
        db,
        "NORMAL_DEADLINE",
        "15:00",
    )



def can_create_order_for_date(db, target_date):
    """
    بررسی امکان ثبت سفارش جدید:

    امروز:
        تا SAME_DAY_DEADLINE

    فردا:
        تا NORMAL_DEADLINE در روز جاری

    سایر تاریخ‌ها:
        مجاز نیست
    """
    today = today_iran()

    if target_date == today:
        return not same_day_deadline_passed(db)

    if target_date == today + timedelta(days=1):
        return not normal_deadline_passed(db)

    return False


def can_increase_order(db, target_date):
    """
    افزایش تعداد سفارش:

    فقط برای امروز و فردا و فقط تا مهلت مربوطه.
    """
    today = today_iran()

    if target_date == today:
        return not same_day_deadline_passed(db)

    if target_date == today + timedelta(days=1):
        return not normal_deadline_passed(db)

    return False



def can_increase_order(db, target_date: date) -> bool:
    """
    افزایش تعداد:

    امروز:
        تا 09:00

    فردا:
        از 15:00 امروز تا 09:00 فردا نیز مجاز
    """

    current = now_iran()
    current_date = current.date()

    if target_date == current_date:
        return not same_day_deadline_passed(db)

    if target_date == current_date + timedelta(days=1):
        tomorrow_9 = (
            current + timedelta(days=1)
        ).replace(
            hour=9,
            minute=0,
            second=0,
            microsecond=0,
        )

        return current < tomorrow_9

    return False


def can_reduce_or_cancel(db, target_date: date) -> bool:
    """
    کاهش یا لغو فقط در مهلت ثبت اولیه مجاز است.

    امروز:
        قبل از 09:00

    فردا:
        قبل از 15:00 امروز
    """

    return can_create_order_for_date(db, target_date)


def make_code(prefix: str, db, model) -> str:
    """کد پیگیری کوتاه: PREFIX-MMDD-NNNN (مثلاً W-0915-0042)."""
    today = today_iran()
    date_part = today.strftime("%m%d")

    total = db.query(model).count()

    for i in range(100):
        seq = total + 1 + i
        code = f"{prefix}-{date_part}-{seq:04d}"

        exists = (
            db.query(model)
            .filter(model.tracking_code == code)
            .first()
        )

        if not exists:
            return code

    raise RuntimeError("امکان تولید کد پیگیری یکتا وجود ندارد")


def get_employee(chat_id: str, db):
    return (
        db.query(Employee)
        .filter(Employee.bale_chat_id == str(chat_id))
        .first()
    )


def get_menu(db, site_id: int, target_date: date):
    return (
        db.query(MenuEntry)
        .filter(
            MenuEntry.site_id == site_id,
            MenuEntry.date == target_date,
            MenuEntry.status == "منتشر",
            MenuEntry.is_selectable == True,  # noqa: E712
        )
        .order_by(MenuEntry.display_order)
        .all()
    )


def clear_session(chat_id: str):
    SESSIONS.pop(str(chat_id), None)


NAV_HOME_BUTTON = {"text": "🏠 منوی اصلی", "callback_data": "nav:home"}
NAV_BACK_BUTTON = {"text": "🔙 بازگشت", "callback_data": "nav:back"}


def with_nav_row(keyboard_rows: list, back: bool = True) -> dict:
    rows = list(keyboard_rows)
    nav_row = [NAV_BACK_BUTTON, NAV_HOME_BUTTON] if back else [NAV_HOME_BUTTON]
    rows.append(nav_row)
    return {"inline_keyboard": rows}


def chunk_keyboard_labels(labels: list[str], min_columns: int = 2, max_columns: int = 3) -> list[list[str]]:
    """
    چیدمان دکمه‌های reply keyboard در ۲ یا ۳ ستون بر اساس طول متوسط برچسب‌ها.
    """
    if not labels:
        return []
    avg_len = sum(len(label) for label in labels) / len(labels)
    columns = max_columns if avg_len <= 10 else min_columns
    rows = []
    for i in range(0, len(labels), columns):
        rows.append(labels[i:i + columns])
    return rows


async def send_main_menu(chat_id: str, prefix: str | None = None):
    clear_session(chat_id)

    db = SessionLocal()
    try:
        employee = get_employee(chat_id, db)
        if not employee:
            await send_message(chat_id, "ابتدا دستور /start را ارسال کنید.")
            return

        is_admin = employee.role in ADMIN_ROLES
        is_welfare_manager = (
            db.query(WelfareManagerAssignment)
            .filter(
                WelfareManagerAssignment.employee_id == employee.id,
                WelfareManagerAssignment.is_active == True,  # noqa: E712
            )
            .first()
            is not None
        )

        message = (prefix + "\n\n" if prefix else "") + "🏠 منوی اصلی"

        await send_message(
            chat_id,
            message,
            reply_markup=main_menu_keyboard(is_admin, is_welfare_manager),
        )
    finally:
        db.close()


# =========================================================
# START / HELP
# =========================================================

async def handle_nav(chat_id: str, value: str):
    if value == "home":
        # جمع‌آوری همه‌ی message_idهای شناخته‌شده برای حذف
        session = SESSIONS.get(str(chat_id)) or {}
        to_delete = []
        for key in (
            "welfare_inline_msg_id",
            "welfare_reply_msg_id",
            "welfare_date_msg_id",
            "welfare_msg_id",
            "welfare_qty_msg_id",
            "menu_food_msg_id",
            "menu_site_msg_id",
        ):
            mid = session.get(key)
            if mid:
                to_delete.append(mid)
        # پیام‌های carrier منو (ممکن است چندتا باشند)
        for mid in session.get("menu_carrier_ids") or []:
            if mid:
                to_delete.append(mid)

        clear_session(chat_id)

        for mid in to_delete:
            try:
                await delete_message(chat_id, mid)
            except Exception:
                pass

        # حذف همه‌ی پیام‌های ردیابی‌شده‌ی menu
        await _delete_menu_msgs(chat_id)

        await send_main_menu(chat_id)
        return True

    if value != "back":
        return False

    session = SESSIONS.get(str(chat_id))

    if not session:
        await send_main_menu(chat_id)
        return True

    state = session.get("state")

    if state == "order_choose_food":
        employee_id = session.get("employee_id")
        site_id = session.get("site_id")
        SESSIONS[str(chat_id)] = {
            "state": "order_choose_date",
            "employee_id": employee_id,
            "site_id": site_id,
        }
        await send_order_date_menu(chat_id)
        return True

    if state == "order_choose_quantity":
        target_date = session.get("target_date")
        employee_id = session.get("employee_id")
        site_id = session.get("site_id")
        editing_order_id = session.get("editing_order_id")

        db = SessionLocal()
        try:
            menu_entries = get_menu(db, site_id, target_date)

            if not menu_entries:
                clear_session(chat_id)
                await send_main_menu(chat_id)
                return True

            message = (
                f"منوی سفارش برای {to_jalali(target_date)}:\n\n"
                "لطفاً غذای مورد نظر را از دکمه‌های پایین انتخاب کنید."
            )

            keyboard_rows = chunk_keyboard_labels([entry.food.name for entry in menu_entries])
            keyboard_rows.append(["🔙 بازگشت", "🏠 منوی اصلی"])

            new_session = {
                "state": "order_choose_food",
                "employee_id": employee_id,
                "site_id": site_id,
                "target_date": target_date,
                "options": [entry.id for entry in menu_entries],
                "option_labels": [entry.food.name for entry in menu_entries],
            }
            if editing_order_id:
                new_session["editing_order_id"] = editing_order_id

            SESSIONS[str(chat_id)] = new_session

            await send_message(
                chat_id,
                message,
                reply_markup={
                    "keyboard": keyboard_rows,
                    "resize_keyboard": True,
                    "one_time_keyboard": False,
                },
            )
            return True
        finally:
            db.close()

    if state == "order_confirm":
        await send_message(
            chat_id,
            "لطفاً تعداد جدید را ارسال کنید.\nمثال: 2",
            reply_markup=with_nav_row([]),
        )
        session["state"] = "order_choose_quantity"
        return True

    clear_session(chat_id)
    await send_main_menu(chat_id)
    return True


async def handle_start(chat_id: str):
    # پاک کردن همه‌ی پیام‌های menu قبلی
    await _delete_menu_msgs(chat_id)

    # حذف پیام خوش‌آمد قبلی
    last = _LAST_MSG_IDS.get(str(chat_id)) or {}
    old_welcome = last.get("start_welcome")
    if old_welcome:
        try:
            await delete_message(chat_id, old_welcome)
        except Exception:
            pass

    db = SessionLocal()
    try:
        employee = (
            db.query(Employee)
            .filter(Employee.bale_chat_id == str(chat_id))
            .first()
        )
        if employee:
            role_text = employee.role or "کاربر"
            is_admin = employee.role in ADMIN_ROLES
            is_welfare_manager = (
                db.query(WelfareManagerAssignment)
                .filter(
                    WelfareManagerAssignment.employee_id == employee.id,
                    WelfareManagerAssignment.is_active == True,  # noqa: E712
                )
                .first()
                is not None
            )
            # حذف پیام خوش‌آمد قبلی (اگر داشتیم)
            last = _LAST_MSG_IDS.get(str(chat_id)) or {}
            old_welcome = last.get("start_welcome")
            if old_welcome:
                try:
                    await delete_message(chat_id, old_welcome)
                except Exception:
                    pass

            _r = await send_message(
                chat_id,
                f"خوش آمدید {employee.full_name} ✅\n"
                f"نقش: {role_text}\n\n"
                "از دکمه‌های پایین صفحه استفاده کنید 👇",
                reply_markup=main_menu_keyboard(is_admin, is_welfare_manager),
            )
            if isinstance(_r, dict):
                _nid = _r.get("result", {}).get("message_id")
                if _nid:
                    _LAST_MSG_IDS.setdefault(str(chat_id), {})["start_welcome"] = _nid
            return
    finally:
        db.close()

    await request_contact(
        chat_id,
        "سلام 👋\n"
        "به ربات سفارش غذای برکت خوش آمدید.\n\n"
        "برای شناسایی شما، لطفاً شماره موبایل ثبت‌شده "
        "در سامانه را با دکمه زیر ارسال کنید.",
    )


async def handle_help(chat_id: str):
    await send_message(
        chat_id,
        "راهنمای ربات برکت:\n\n"
        "/start - شناسایی کاربر\n"
        "/order - ثبت سفارش\n"
        "/myorder - مشاهده سفارش‌ها\n"
        "/cancel - لغو سفارش\n"
        "/welfare - ثبت سفارش گروهی\n"
        "/menu - مدیریت منو\n"
        "/report - گزارش آشپزخانه امروز\n"
        "/help - راهنما",
    )


async def handle_sysadmin(chat_id: str):
    db = SessionLocal()
    try:
        employee = (
            db.query(Employee)
            .filter(Employee.bale_chat_id == str(chat_id))
            .first()
        )
        if not employee:
            await send_message(
                chat_id,
                "ابتدا باید شناسایی شوید. لطفاً دستور /start را ارسال کنید.",
            )
            return

        if employee.role not in ADMIN_ROLES:
            await send_message(chat_id, "شما دسترسی به مدیریت سیستم ندارید.")
            return

        is_welfare_manager = (
            db.query(WelfareManagerAssignment)
            .filter(
                WelfareManagerAssignment.employee_id == employee.id,
                WelfareManagerAssignment.is_active == True,  # noqa: E712
            )
            .first()
            is not None
        )

        await send_message(
            chat_id,
            "🔧 بخش «مدیریت سیستم» در حال ساخت است.\n\n"
            "به‌زودی در این بخش:\n"
            "• مدیریت پرسنل\n"
            "• مدیریت سایت‌ها\n"
            "• تنظیمات سیستم\n"
            "• پشتیبان‌گیری خودکار\n\n"
            "از دکمه‌های زیر می‌توانید فعلاً استفاده کنید 👇",
            reply_markup=main_menu_keyboard(True, is_welfare_manager),
        )
    finally:
        db.close()


# =========================================================
# CONTACT
# =========================================================

async def handle_contact(chat_id: str, phone_number: str):
    mobile = normalize_mobile(phone_number)

    db = SessionLocal()

    try:
        employee = (
            db.query(Employee)
            .filter(Employee.mobile == mobile)
            .first()
        )

        if not employee:
            await remove_keyboard(
                chat_id,
                "شماره موبایل شما در سامانه ثبت نشده است.\n"
                "لطفاً با واحد رفاه شرکت تماس بگیرید.",
            )
            return

        employee.bale_chat_id = str(chat_id)
        db.commit()

        role_text = employee.role or "کاربر"

        is_admin = employee.role in ADMIN_ROLES
        is_welfare_manager = (
            db.query(WelfareManagerAssignment)
            .filter(
                WelfareManagerAssignment.employee_id == employee.id,
                WelfareManagerAssignment.is_active == True,  # noqa: E712
            )
            .first()
            is not None
        )

        await send_message(
            chat_id,
            f"خوش آمدید {employee.full_name} ✅\n"
            f"نقش: {role_text}\n\n"
            "از دکمه‌های پایین صفحه استفاده کنید 👇",
            reply_markup=main_menu_keyboard(is_admin, is_welfare_manager),
        )

    finally:
        db.close()


# =========================================================
# ORDER
# =========================================================

async def send_order_date_menu(chat_id: str, prefix: str | None = None):
    message = ""

    if prefix:
        message += prefix + "\n\n"

    db = SessionLocal()
    try:
        today = today_iran()
        tomorrow = today + timedelta(days=1)
        today_ok = can_create_order_for_date(db, today)
        tomorrow_ok = can_create_order_for_date(db, tomorrow)
    finally:
        db.close()

    date_labels = []
    if today_ok:
        date_labels.append("1️⃣ امروز")
    if tomorrow_ok:
        date_labels.append("2️⃣ فردا")

    if not date_labels:
        message += "⛔ در حال حاضر مهلت ثبت سفارش برای امروز و فردا به پایان رسیده است."
        keyboard = {
            "keyboard": [["🏠 منوی اصلی"]],
            "resize_keyboard": True,
            "one_time_keyboard": False,
        }
        await send_message(chat_id, message, reply_markup=keyboard)
        return

    message += "برای چه روزی می‌خواهید سفارش ثبت کنید؟"

    keyboard = {
        "keyboard": [date_labels, ["🏠 منوی اصلی"]],
        "resize_keyboard": True,
        "one_time_keyboard": False,
    }

    await send_message(chat_id, message, reply_markup=keyboard)


async def handle_order(chat_id: str):
    db = SessionLocal()

    try:
        employee = get_employee(chat_id, db)

        if not employee:
            await send_message(
                chat_id,
                "ابتدا باید شناسایی شوید.\n"
                "دستور /start را ارسال کنید.",
            )
            return

        # فقط وضعیت انتخاب روز را ایجاد می‌کنیم.
        # بررسی مهلت بعد از انتخاب روز انجام می‌شود.
        SESSIONS[str(chat_id)] = {
            "state": "order_choose_date",
            "employee_id": employee.id,
            "site_id": employee.site_id,
        }

        await send_order_date_menu(chat_id)

    finally:
        db.close()


async def handle_order_date_choice(chat_id: str, text: str, force_new: bool = False):
    session = SESSIONS.get(str(chat_id))

    if force_new:
        db_auto = SessionLocal()
        try:
            employee = get_employee(chat_id, db_auto)
            if not employee:
                return False
            SESSIONS[str(chat_id)] = {
                "state": "order_choose_date",
                "employee_id": employee.id,
                "site_id": employee.site_id,
            }
            session = SESSIONS[str(chat_id)]
        finally:
            db_auto.close()

    if not session:
        return False

    if session.get("state") != "order_choose_date":
        return False

    choice_text = text.strip()

    if "امروز" in choice_text:
        choice_text = "1"
    elif "فردا" in choice_text:
        choice_text = "2"

    if choice_text not in {"1", "2"}:
        await send_message(
            chat_id,
            "لطفاً فقط 1 یا 2 را ارسال کنید.\n\n"
            "1️⃣ امروز\n"
            "2️⃣ فردا",
        )
        return True

    # تاریخ هدف
    target_date = today_iran()

    if choice_text == "2":
        target_date = target_date + timedelta(days=1)

    db = SessionLocal()

    try:
        employee = (
            db.query(Employee)
            .filter(Employee.id == session["employee_id"])
            .first()
        )

        if not employee:
            await send_message(
                chat_id,
                "کاربر پیدا نشد.",
            )
            clear_session(chat_id)
            return True

        # -----------------------------------------------------
        # بررسی سفارش قبلی
        # -----------------------------------------------------

        existing = (
            db.query(PersonalOrder)
            .filter(
                PersonalOrder.employee_id == employee.id,
                PersonalOrder.date == target_date,
            )
            .first()
        )

        if existing:

            if can_increase_order(db, target_date):

                await send_message(
                    chat_id,
                    f"برای تاریخ {to_jalali(target_date)} "
                    "قبلاً سفارش دارید.\n\n"
                    f"غذا: {existing.food.name}\n"
                    f"تعداد فعلی: {existing.quantity}\n\n"
                    "برای افزایش تعداد، تعداد جدید را ارسال کنید.\n"
                    "مثال: 3",
                )

                SESSIONS[str(chat_id)] = {
                    "state": "increase_quantity",
                    "employee_id": employee.id,
                    "order_id": existing.id,
                    "target_date": target_date,
                }

            else:

                await send_message(
                    chat_id,
                    f"برای تاریخ {to_jalali(target_date)} "
                    "سفارش شما قبلاً ثبت شده است.\n\n"
                    f"غذا: {existing.food.name}\n"
                    f"تعداد: {existing.quantity}\n"
                    f"کد پیگیری: {existing.tracking_code}",
                )

                # در این حالت انتخاب روز تمام شده است.
                clear_session(chat_id)

            return True

        # -----------------------------------------------------
        # بررسی مهلت ثبت سفارش
        # -----------------------------------------------------

        if not can_create_order_for_date(db, target_date):

            if target_date == today_iran():

                deadline = get_setting_value(
                    db,
                    "SAME_DAY_DEADLINE",
                    "09:00",
                )

                prefix = (
                    "⛔ مهلت ثبت سفارش امروز "
                    f"تا ساعت {deadline} بوده و به پایان رسیده است."
                )

            else:

                deadline = get_setting_value(
                    db,
                    "NORMAL_DEADLINE",
                    "15:00",
                )

                prefix = (
                    "⛔ مهلت ثبت سفارش فردا "
                    f"تا ساعت {deadline} امروز بوده و به پایان رسیده است."
                )

            # بسیار مهم:
            # Session را پاک نمی‌کنیم.
            # کاربر باید بتواند دوباره 1 یا 2 را انتخاب کند.
            SESSIONS[str(chat_id)] = {
                "state": "order_choose_date",
                "employee_id": employee.id,
                "site_id": employee.site_id,
            }

            await send_order_date_menu(
                chat_id,
                prefix=prefix,
            )

            return True

        # -----------------------------------------------------
        # دریافت منوی همان روز
        # -----------------------------------------------------

        menu_entries = get_menu(
            db,
            employee.site_id,
            target_date,
        )

        if not menu_entries:

            prefix = (
                f"برای تاریخ {to_jalali(target_date)} "
                "منوی منتشرشده‌ای وجود ندارد."
            )

            # کاربر بتواند روز دیگر را انتخاب کند.
            SESSIONS[str(chat_id)] = {
                "state": "order_choose_date",
                "employee_id": employee.id,
                "site_id": employee.site_id,
            }

            await send_order_date_menu(
                chat_id,
                prefix=prefix,
            )

            return True

        # -----------------------------------------------------
        # نمایش غذاها
        # -----------------------------------------------------

        message = (
            f"منوی سفارش برای {to_jalali(target_date)}:\n\n"
            "لطفاً غذای مورد نظر را از دکمه‌های پایین انتخاب کنید."
        )

        keyboard_rows = chunk_keyboard_labels([entry.food.name for entry in menu_entries])
        keyboard_rows.append(["🔙 بازگشت", "🏠 منوی اصلی"])

        SESSIONS[str(chat_id)] = {
            "state": "order_choose_food",
            "employee_id": employee.id,
            "site_id": employee.site_id,
            "target_date": target_date,
            "options": [entry.id for entry in menu_entries],
            "option_labels": [entry.food.name for entry in menu_entries],
        }

        await send_message(
            chat_id,
            message,
            reply_markup={
                "keyboard": keyboard_rows,
                "resize_keyboard": True,
                "one_time_keyboard": False,
            },
        )

    finally:
        db.close()

    return True


# =========================================================
# انتخاب غذا
# =========================================================

async def handle_order_food_choice(chat_id: str, text: str):
    session = SESSIONS.get(str(chat_id))

    if not session or session.get("state") != "order_choose_food":
        return False

    choice_text = text.strip()
    options = session["options"]
    option_labels = session.get("option_labels") or []

    choice = None
    if choice_text.isdigit():
        choice = int(choice_text)
    elif choice_text in option_labels:
        choice = option_labels.index(choice_text) + 1

    if not choice or choice < 1 or choice > len(options):
        await send_message(
            chat_id,
            "لطفاً یکی از گزینه‌های موجود را انتخاب کنید.",
        )
        return True

    menu_entry_id = options[choice - 1]

    db = SessionLocal()

    try:
        entry = (
            db.query(MenuEntry)
            .filter(MenuEntry.id == menu_entry_id)
            .first()
        )

        if not entry:
            await send_message(
                chat_id,
                "غذای انتخاب‌شده پیدا نشد.",
            )
            clear_session(chat_id)
            return True

        await send_message(
            chat_id,
            f"غذای انتخاب‌شده:\n"
            f"🍽 {entry.food.name}\n\n"
            "تعداد غذا را ارسال کنید.\n"
            "مثال: 2",
            reply_markup=with_nav_row([]),
        )

        session["state"] = "order_choose_quantity"
        session["menu_entry_id"] = entry.id
        session["food_id"] = entry.food_id

    finally:
        db.close()

    return True


# =========================================================
# تعداد سفارش جدید
# =========================================================

async def handle_order_quantity(chat_id: str, text: str):
    session = SESSIONS.get(str(chat_id))

    if not session or session.get("state") != "order_choose_quantity":
        return False

    if not text.strip().isdigit():
        await send_message(
            chat_id,
            "تعداد باید یک عدد مثبت باشد.",
        )
        return True

    quantity = int(text.strip())

    if quantity <= 0 or quantity > 10000:
        await send_message(
            chat_id,
            "تعداد نامعتبر است.",
        )
        return True

    db = SessionLocal()

    try:
        employee = (
            db.query(Employee)
            .filter(Employee.id == session["employee_id"])
            .first()
        )

        entry = (
            db.query(MenuEntry)
            .filter(MenuEntry.id == session["menu_entry_id"])
            .first()
        )

        if not employee or not entry:
            await send_message(
                chat_id,
                "اطلاعات سفارش پیدا نشد.",
            )
            clear_session(chat_id)
            return True

        target_date = session["target_date"]

        # دوباره مهلت را کنترل می‌کنیم.
        if not can_create_order_for_date(db, target_date):
            await send_message(
                chat_id,
                "در زمان ثبت نهایی، مهلت سفارش به پایان رسیده است.",
            )
            clear_session(chat_id)
            return True

        existing = (
            db.query(PersonalOrder)
            .filter(
                PersonalOrder.employee_id == employee.id,
                PersonalOrder.date == target_date,
            )
            .first()
        )

        editing_order_id = session.get("editing_order_id")

        if existing and existing.id != editing_order_id:
            await send_message(
                chat_id,
                "برای این تاریخ قبلاً سفارش ثبت شده است.",
            )
            clear_session(chat_id)
            return True

        session["quantity"] = quantity

        await send_message(
            chat_id,
            "لطفاً سفارش را بررسی کنید:\n\n"
            f"📅 تاریخ: {to_jalali(target_date)}\n"
            f"🍽 غذا: {entry.food.name}\n"
            f"🔢 تعداد: {quantity}",
            reply_markup={
                "keyboard": [
                    ["✅ تأیید", "❌ انصراف"],
                    ["🏠 منوی اصلی"],
                ],
                "resize_keyboard": True,
                "one_time_keyboard": False,
            },
        )

        session["state"] = "order_confirm"

    finally:
        db.close()

    return True


# =========================================================
# تأیید سفارش
# =========================================================

async def handle_order_confirm(chat_id: str, text: str):
    session = SESSIONS.get(str(chat_id))

    if not session or session.get("state") != "order_confirm":
        return False

    value = text.strip()

    # نرمال‌سازی: حذف ایموجی و نیم‌فاصله برای مقایسه‌ی مقاوم
    norm = re.sub(r"[^\w]", "", value, flags=re.UNICODE)
    confirm_kw = "\u062a\u0623\u06cc\u06cc\u062f"  # تأیید
    cancel_kw = "\u0627\u0646\u0635\u0631\u0627\u0641"  # انصراف
    if norm == confirm_kw or value == "1":
        value = "1"
    elif norm == cancel_kw or value == "2":
        value = "2"

    db = SessionLocal()

    try:
        employee = (
            db.query(Employee)
            .filter(Employee.id == session["employee_id"])
            .first()
        )

        if employee:
            is_admin = employee.role in ADMIN_ROLES
            is_welfare_manager = (
                db.query(WelfareManagerAssignment)
                .filter(
                    WelfareManagerAssignment.employee_id == employee.id,
                    WelfareManagerAssignment.is_active == True,  # noqa: E712
                )
                .first()
                is not None
            )
        else:
            is_admin = False
            is_welfare_manager = False

        main_kb = main_menu_keyboard(is_admin, is_welfare_manager)

        if value == "2":
            clear_session(chat_id)
            await send_message(
                chat_id,
                "ثبت سفارش لغو شد.",
                reply_markup=main_kb,
            )
            return True

        if value != "1":
            await send_message(
                chat_id,
                "لطفاً از دکمه‌های «✅ تأیید» یا «❌ انصراف» استفاده کنید.",
                reply_markup=main_kb,
            )
            return True

        entry = (
            db.query(MenuEntry)
            .filter(MenuEntry.id == session["menu_entry_id"])
            .first()
        )

        if not employee or not entry:
            await send_message(
                chat_id,
                "اطلاعات سفارش ناقص است.",
                reply_markup=main_kb,
            )
            clear_session(chat_id)
            return True

        target_date = session["target_date"]
        quantity = session["quantity"]

        if not can_create_order_for_date(db, target_date):
            await send_message(
                chat_id,
                "مهلت ثبت سفارش به پایان رسیده است.",
                reply_markup=main_kb,
            )
            clear_session(chat_id)
            return True

        existing = (
            db.query(PersonalOrder)
            .filter(
                PersonalOrder.employee_id == employee.id,
                PersonalOrder.date == target_date,
            )
            .first()
        )

        editing_order_id = session.get("editing_order_id")

        if existing and existing.id != editing_order_id:
            await send_message(
                chat_id,
                f"این سفارش قبلاً ثبت شده است.\n"
                f"کد پیگیری: {existing.tracking_code}",
                reply_markup=main_kb,
            )
            clear_session(chat_id)
            return True

        if existing and existing.id == editing_order_id:
            existing.food_id = entry.food_id
            existing.quantity = quantity
            db.commit()

            await send_message(
                chat_id,
                "سفارش شما با موفقیت ویرایش شد ✅\n\n"
                f"📅 تاریخ: {to_jalali(target_date)}\n"
                f"🍽 غذا: {entry.food.name}\n"
                f"🔢 تعداد: {quantity}\n"
                f"🎫 کد پیگیری: {existing.tracking_code}",
                reply_markup=main_kb,
            )
        else:
            tracking_code = make_code(
                "P",
                db,
                PersonalOrder,
            )

            order = PersonalOrder(
                tracking_code=tracking_code,
                date=target_date,
                employee_id=employee.id,
                food_id=entry.food_id,
                quantity=quantity,
                status="ثبت شده",
                source="Bale",
                created_by=employee.full_name,
            )

            db.add(order)
            db.commit()

            await send_message(
                chat_id,
                "سفارش شما با موفقیت ثبت شد ✅\n\n"
                f"📅 تاریخ: {to_jalali(target_date)}\n"
                f"🍽 غذا: {entry.food.name}\n"
                f"🔢 تعداد: {quantity}\n"
                f"🎫 کد پیگیری: {tracking_code}",
                reply_markup=main_kb,
            )

    finally:
        db.close()
        clear_session(chat_id)

    return True


# =========================================================
# افزایش تعداد سفارش
# =========================================================

async def handle_increase_quantity(chat_id: str, text: str):
    session = SESSIONS.get(str(chat_id))

    if not session or session.get("state") != "increase_quantity":
        return False

    if not text.strip().isdigit():
        await send_message(
            chat_id,
            "لطفاً تعداد جدید را به صورت عدد ارسال کنید.",
        )
        return True

    new_quantity = int(text.strip())

    if new_quantity <= 0 or new_quantity > 10000:
        await send_message(
            chat_id,
            "تعداد نامعتبر است.",
        )
        return True

    db = SessionLocal()

    try:
        order = (
            db.query(PersonalOrder)
            .filter(
                PersonalOrder.id == session["order_id"],
            )
            .first()
        )

        if not order:
            await send_message(
                chat_id,
                "سفارش پیدا نشد.",
            )
            clear_session(chat_id)
            return True

        if not can_increase_order(db, order.date):
            await send_message(
                chat_id,
                "مهلت افزایش تعداد این سفارش به پایان رسیده است.",
            )
            clear_session(chat_id)
            return True

        if new_quantity < order.quantity:
            await send_message(
                chat_id,
                f"امکان کاهش سفارش وجود ندارد.\n"
                f"تعداد فعلی: {order.quantity}\n\n"
                "فقط می‌توانید تعداد را افزایش دهید.",
            )
            return True

        if new_quantity == order.quantity:
            await send_message(
                chat_id,
                "تعداد جدید با تعداد فعلی برابر است.",
            )
            return True

        old_quantity = order.quantity
        order.quantity = new_quantity

        db.commit()

        await send_message(
            chat_id,
            "تعداد سفارش افزایش یافت ✅\n\n"
            f"غذا: {order.food.name}\n"
            f"تعداد قبلی: {old_quantity}\n"
            f"تعداد جدید: {new_quantity}\n"
            f"کد پیگیری: {order.tracking_code}",
        )

    finally:
        db.close()
        clear_session(chat_id)

    return True


# =========================================================
# MY ORDER
# =========================================================

async def handle_myorder(chat_id: str):
    db = SessionLocal()

    try:
        employee = get_employee(chat_id, db)

        if not employee:
            await send_message(
                chat_id,
                "ابتدا دستور /start را ارسال کنید.",
            )
            return

        current = today_iran()
        tomorrow = current + timedelta(days=1)

        orders = (
            db.query(PersonalOrder)
            .filter(
                PersonalOrder.employee_id == employee.id,
                PersonalOrder.date.in_([current, tomorrow]),
            )
            .order_by(PersonalOrder.date)
            .all()
        )

        if not orders:
            await send_message(
                chat_id,
                "برای امروز و فردا سفارشی ثبت نشده است.",
            )
            return

        lines = ["📋 سفارش‌های شما:\n"]
        order_ids = []
        keyboard_rows = []

        for order in orders:
            if order.date == current:
                title = "امروز"
            else:
                title = "فردا"

            lines.extend(
                [
                    f"📅 {title} ({to_jalali(order.date)})",
                    f"🍽 غذا: {order.food.name}",
                    f"🔢 تعداد: {order.quantity}",
                    f"🎫 کد پیگیری: {order.tracking_code}",
                    f"📌 وضعیت: {order.status}",
                    "",
                ]
            )

            if can_reduce_or_cancel(db, order.date):
                order_ids.append(order.id)
                idx = len(order_ids)
                keyboard_rows.append(
                    [
                        {"text": f"✏️ ویرایش ({title})", "callback_data": f"myorder_edit:{idx}"},
                        {"text": f"❌ لغو ({title})", "callback_data": f"myorder_cancel:{idx}"},
                    ]
                )

        if order_ids:
            SESSIONS[str(chat_id)] = {
                "state": "myorder_actions",
                "order_ids": order_ids,
            }
        else:
            lines.append("مهلت ویرایش یا لغو سفارش‌های فوق به پایان رسیده است.")

        await send_message(
            chat_id,
            "\n".join(lines),
            reply_markup={"inline_keyboard": keyboard_rows} if keyboard_rows else None,
        )

    finally:
        db.close()


# =========================================================
# CANCEL
# =========================================================

async def handle_myorder_cancel(chat_id: str, text: str):
    session = SESSIONS.get(str(chat_id))

    if not session or session.get("state") != "myorder_actions":
        return False

    if not text.strip().isdigit():
        return True

    choice = int(text.strip())
    order_ids = session["order_ids"]

    if choice < 1 or choice > len(order_ids):
        return True

    db = SessionLocal()

    try:
        order = (
            db.query(PersonalOrder)
            .filter(PersonalOrder.id == order_ids[choice - 1])
            .first()
        )

        if not order:
            await send_message(chat_id, "سفارش پیدا نشد.")
            clear_session(chat_id)
            return True

        if not can_reduce_or_cancel(db, order.date):
            await send_message(chat_id, "مهلت لغو این سفارش به پایان رسیده است.")
            clear_session(chat_id)
            return True

        db.delete(order)
        db.commit()

        await send_message(chat_id, "سفارش با موفقیت لغو شد ✅")

    finally:
        db.close()
        clear_session(chat_id)

    return True


async def handle_myorder_edit(chat_id: str, text: str):
    session = SESSIONS.get(str(chat_id))

    if not session or session.get("state") != "myorder_actions":
        return False

    if not text.strip().isdigit():
        return True

    choice = int(text.strip())
    order_ids = session["order_ids"]

    if choice < 1 or choice > len(order_ids):
        return True

    db = SessionLocal()

    try:
        order = (
            db.query(PersonalOrder)
            .filter(PersonalOrder.id == order_ids[choice - 1])
            .first()
        )

        if not order:
            await send_message(chat_id, "سفارش پیدا نشد.")
            clear_session(chat_id)
            return True

        if not can_reduce_or_cancel(db, order.date):
            await send_message(chat_id, "مهلت ویرایش این سفارش به پایان رسیده است.")
            clear_session(chat_id)
            return True

        employee = get_employee(chat_id, db)

        if not employee:
            await send_message(chat_id, "کاربر پیدا نشد.")
            clear_session(chat_id)
            return True

        target_date = order.date
        menu_entries = get_menu(db, employee.site_id, target_date)

        if not menu_entries:
            await send_message(
                chat_id,
                f"برای تاریخ {to_jalali(target_date)} منوی منتشرشده‌ای وجود ندارد.",
            )
            clear_session(chat_id)
            return True

        message = (
            f"ویرایش سفارش {to_jalali(target_date)} — غذای جدید را انتخاب کنید:\n\n"
            "لطفاً غذای مورد نظر را از دکمه‌های پایین انتخاب کنید."
        )

        keyboard_rows = chunk_keyboard_labels([entry.food.name for entry in menu_entries])
        keyboard_rows.append(["🔙 بازگشت", "🏠 منوی اصلی"])

        SESSIONS[str(chat_id)] = {
            "state": "order_choose_food",
            "employee_id": employee.id,
            "site_id": employee.site_id,
            "target_date": target_date,
            "options": [entry.id for entry in menu_entries],
            "option_labels": [entry.food.name for entry in menu_entries],
            "editing_order_id": order.id,
        }

        await send_message(
            chat_id,
            message,
            reply_markup={
                "keyboard": keyboard_rows,
                "resize_keyboard": True,
                "one_time_keyboard": False,
            },
        )

    finally:
        db.close()

    return True


async def handle_cancel(chat_id: str):
    db = SessionLocal()

    try:
        employee = get_employee(chat_id, db)

        if not employee:
            await send_message(
                chat_id,
                "ابتدا دستور /start را ارسال کنید.",
            )
            return

        current = today_iran()
        tomorrow = current + timedelta(days=1)

        orders = (
            db.query(PersonalOrder)
            .filter(
                PersonalOrder.employee_id == employee.id,
                PersonalOrder.date.in_([current, tomorrow]),
            )
            .order_by(PersonalOrder.date)
            .all()
        )

        cancellable = [
            order
            for order in orders
            if can_reduce_or_cancel(db, order.date)
        ]

        if not cancellable:
            await send_message(
                chat_id,
                "در حال حاضر سفارش قابل لغو وجود ندارد.\n\n"
                "لغو فقط در مهلت مجاز سفارش امکان‌پذیر است.",
            )
            return

        lines = [
            "کدام سفارش را می‌خواهید لغو کنید؟\n",
        ]

        for idx, order in enumerate(cancellable, start=1):
            lines.append(
                f"{idx}. "
                f"{to_jalali(order.date)} - "
                f"{order.food.name} - "
                f"{order.quantity} عدد"
            )

        lines.append("\nیا روی یکی از دکمه‌ها بزنید.")

        SESSIONS[str(chat_id)] = {
            "state": "cancel_choose",
            "order_ids": [o.id for o in cancellable],
        }

        keyboard = {
            "inline_keyboard": [
                [
                    {
                        "text": f"{idx}. {order.food.name} - {to_jalali(order.date)}",
                        "callback_data": f"cancel_choice:{idx}",
                    }
                ]
                for idx, order in enumerate(cancellable, start=1)
            ]
        }

        await send_message(
            chat_id,
            "\n".join(lines),
            reply_markup=keyboard,
        )

    finally:
        db.close()


async def handle_cancel_choice(chat_id: str, text: str):
    session = SESSIONS.get(str(chat_id))

    if not session or session.get("state") != "cancel_choose":
        return False

    if not text.strip().isdigit():
        await send_message(
            chat_id,
            "لطفاً شماره سفارش را ارسال کنید.",
        )
        return True

    choice = int(text.strip())
    order_ids = session["order_ids"]

    if choice < 1 or choice > len(order_ids):
        await send_message(
            chat_id,
            "شماره سفارش نامعتبر است.",
        )
        return True

    db = SessionLocal()

    try:
        order = (
            db.query(PersonalOrder)
            .filter(PersonalOrder.id == order_ids[choice - 1])
            .first()
        )

        if not order:
            await send_message(
                chat_id,
                "سفارش پیدا نشد.",
            )
            clear_session(chat_id)
            return True

        if not can_reduce_or_cancel(db, order.date):
            await send_message(
                chat_id,
                "مهلت لغو این سفارش به پایان رسیده است.",
            )
            clear_session(chat_id)
            return True

        db.delete(order)
        db.commit()

        await send_message(
            chat_id,
            "سفارش با موفقیت لغو شد ✅",
        )

    finally:
        db.close()
        clear_session(chat_id)

    return True


# =========================================================
# WELFARE
# =========================================================

async def render_welfare_selection(chat_id: str):
    # قفل per-chat برای جلوگیری از race در فشار سریع ➕/➖
    async with _get_welfare_lock(chat_id):
        await _render_welfare_selection_impl(chat_id)


async def _render_welfare_selection_impl(chat_id: str):
    session = SESSIONS.get(str(chat_id))

    if not session or session.get("state") != "welfare_select":
        return

    # رفع پیام تکراری: اگر علامت «تازه برگشتیم از quantity» ست است، ریست کن
    if session.pop("welfare_just_returned", False):
        session["welfare_reply_sent"] = False
        session.pop("welfare_qty_msg_id", None)
        session.pop("welfare_qty_input", None)

    db = SessionLocal()

    try:
        options = session.get("options", [])
        selected = session.setdefault("selected", {})
        active_food_id = session.get("active_food_id")

        menu_entries = (
            db.query(MenuEntry)
            .filter(MenuEntry.id.in_(options))
            .filter(MenuEntry.status == "منتشر")
            .filter(MenuEntry.is_selectable == True)  # noqa: E712
            .order_by(MenuEntry.display_order)
            .all()
        )

        entry_map = {entry.id: entry for entry in menu_entries}

        # شمارش تکرار نام غذاها برای تفکیک نام‌های تکراری
        name_counts = {}
        for entry in menu_entries:
            base = entry.food.name
            name_counts[base] = name_counts.get(base, 0) + 1

        name_seen = {}
        inline_buttons = []
        food_name_map = {}

        lines = [
            "👨‍💼 ثبت سفارش گروهی",
            f"📅 تاریخ: {to_jalali(session['target_date'])}",
            "",
        ]

        for entry in menu_entries:
            base = entry.food.name
            name_seen[base] = name_seen.get(base, 0) + 1

            if name_counts[base] > 1:
                display_name = f"{base} #{name_seen[base]}"
            else:
                display_name = base

            qty = selected.get(entry.id, 0)
            mark = " ✅" if entry.id == active_food_id else ""

            # اگر در حال تایپ برای این غذا هستیم، buffer را نمایش بده
            typing_buf = session.get(f"_typing_{entry.id}", "")
            if entry.id == active_food_id and typing_buf:
                lines.append(f"{display_name}{mark} — {typing_buf}▌")
            elif qty:
                lines.append(f"{display_name}{mark} — {qty} عدد")
            else:
                lines.append(f"{display_name}{mark}")

            if entry.id == active_food_id:
                prefix = "✅"
            else:
                prefix = "🍽"

            if qty:
                label = f"{prefix} {display_name} ({qty} عدد)"
            else:
                label = f"{prefix} {display_name}"

            inline_buttons.append({
                "text": label,
                "callback_data": f"welfare_food:{entry.id}",
            })
            food_name_map[label] = entry.id

        lines.append("")
        if active_food_id and active_food_id in entry_map:
            lines.append("با ➖ / ➕ تعداد را تنظیم کنید.")
        else:
            lines.append("از دکمه‌های چسبیده به همین پیام غذا را انتخاب کنید 👇")

        session["food_name_map"] = food_name_map
        text = "\n".join(lines)

        # inline ۲ ستونه
        inline_rows = []
        for i in range(0, len(inline_buttons), 2):
            inline_rows.append(inline_buttons[i:i + 2])
        inline_kb = {"inline_keyboard": inline_rows}

        # پیام inline (غذاها) - ارسال یا ویرایش
        inline_msg_id = session.get("welfare_inline_msg_id")
        inline_ok = False
        if inline_msg_id:
            try:
                r = await edit_message_text(chat_id, inline_msg_id, text, inline_kb)
                if isinstance(r, dict) and r.get("ok"):
                    inline_ok = True
            except Exception:
                pass

        if not inline_ok:
            r = await send_message(chat_id, text, inline_kb)
            if isinstance(r, dict):
                new_inline_id = r.get("result", {}).get("message_id")
                if new_inline_id:
                    session["welfare_inline_msg_id"] = new_inline_id

        # کیبورد پایین (کنترل‌ها) - فقط یک بار در هر فاز ارسال شود
        if not session.get("welfare_reply_sent"):
            _empty = "\u200b"  # ZWSP نامرئی
            reply_kb = {
                "keyboard": [
                    ["1", "2", "3", "➕"],
                    ["4", "5", "6", "➖"],
                    ["7", "8", "9", "✍️ پاک"],
                    [_empty, "0", _empty, "✅ ثبت"],
                ],
                "resize_keyboard": True,
                "one_time_keyboard": False,
            }

            r = await send_message(
                chat_id,
                "\u2060",
                reply_kb,
            )
            new_reply_id = None
            if isinstance(r, dict):
                new_reply_id = r.get("result", {}).get("message_id")

            # حذف پیام تاریخ (کیبورد قدیمی 1️⃣/2️⃣)
            date_msg_id = session.get("welfare_date_msg_id")
            if date_msg_id:
                try:
                    await delete_message(chat_id, date_msg_id)
                except Exception:
                    pass
                session.pop("welfare_date_msg_id", None)

            # حذف پیام reply قبلی
            old_reply_id = session.get("welfare_reply_msg_id")
            if old_reply_id and old_reply_id != new_reply_id:
                try:
                    await delete_message(chat_id, old_reply_id)
                except Exception:
                    pass

            if new_reply_id:
                session["welfare_reply_msg_id"] = new_reply_id
            session["welfare_reply_sent"] = True

    finally:
        db.close()


async def send_welfare_date_menu(chat_id: str):
    db = SessionLocal()
    try:
        today = today_iran()
        tomorrow = today + timedelta(days=1)

        today_ok = can_create_order_for_date(db, today)
        tomorrow_ok = can_create_order_for_date(db, tomorrow)
    finally:
        db.close()

    date_buttons = []

    if today_ok:
        date_buttons.append("1️⃣ امروز")

    if tomorrow_ok:
        date_buttons.append("2️⃣ فردا")

    rows = []

    if date_buttons:
        rows.append(date_buttons)

    rows.append(["🏠 منوی اصلی"])

    if not today_ok and not tomorrow_ok:
        await send_message(
            chat_id,
            "⛔ مهلت ثبت سفارش برای امروز و فردا به پایان رسیده است.",
            reply_markup={
                "keyboard": [["🏠 منوی اصلی"]],
                "resize_keyboard": True,
                "one_time_keyboard": False,
            },
        )
        return

    result = await send_message(
        chat_id,
        "👨‍💼 ثبت سفارش گروهی\n\nبرای چه روزی می‌خواهید سفارش ثبت کنید؟",
        reply_markup={
            "keyboard": rows,
            "resize_keyboard": True,
            "one_time_keyboard": False,
        },
    )

    if isinstance(result, dict):
        new_id = result.get("result", {}).get("message_id")
        if new_id:
            SESSIONS.setdefault(str(chat_id), {})["welfare_date_msg_id"] = new_id


async def handle_welfare(chat_id: str):
    db = SessionLocal()
    try:
        employee = get_employee(chat_id, db)

        if not employee:
            await send_message(
                chat_id,
                "ابتدا دستور /start را ارسال کنید.",
            )
            return

        is_admin = employee.role in ADMIN_ROLES

        assignment = (
            db.query(WelfareManagerAssignment)
            .filter(
                WelfareManagerAssignment.employee_id == employee.id,
                WelfareManagerAssignment.is_active == True,
            )
            .first()
        )

        if not assignment and not is_admin:
            await send_message(
                chat_id,
                "شما دسترسی ثبت سفارش گروهی ندارید.",
            )
            return

        # اگر session قبلی وجود دارد، پیام inline قدیمی را حذف کن
        old = SESSIONS.get(str(chat_id)) or {}
        old_inline = old.pop("welfare_inline_msg_id", None)
        old_reply = old.pop("welfare_reply_msg_id", None)
        old_date = old.pop("welfare_date_msg_id", None)

        SESSIONS[str(chat_id)] = {
            "state": "welfare_choose_date",
            "employee_id": employee.id,
        }

    finally:
        db.close()

    for mid in (old_inline, old_reply, old_date):
        if mid:
            try:
                await delete_message(chat_id, mid)
            except Exception:
                pass

    await send_welfare_date_menu(chat_id)


async def handle_welfare_date_choice(chat_id: str, value: str):
    session = SESSIONS.get(str(chat_id))

    if not session or session.get("state") != "welfare_choose_date":
        return False

    # اگر state الان welfare_waiting_quantity یا welfare_select است،
    # این handler نباید ورودی را مصرف کند (تا dispatcher به handler درست برسد)
    # این گارد قبلاً وجود داشت ولی چون در انتهای پیام متن fallback می‌آمد،
    # حالا فقط وقتی value یکی از این دو دکمه‌ی واقعی است، ادامه بده
    if value not in ("1", "2") and value not in ("1️⃣ امروز", "2️⃣ فردا"):
        return False

    if value == "1️⃣ امروز":
        value = "1"
    elif value == "2️⃣ فردا":
        value = "2"

    if value not in {"1", "2"}:
        return True

    target_date = today_iran()

    if value == "2":
        target_date += timedelta(days=1)

    db = SessionLocal()
    try:
        employee = (
            db.query(Employee)
            .filter(Employee.id == session["employee_id"])
            .first()
        )

        if not employee:
            await send_message(chat_id, "کاربر پیدا نشد.")
            clear_session(chat_id)
            return True

        is_admin = employee.role in ADMIN_ROLES

        assignment = (
            db.query(WelfareManagerAssignment)
            .filter(
                WelfareManagerAssignment.employee_id == employee.id,
                WelfareManagerAssignment.is_active == True,
            )
            .first()
        )

        if not assignment and not is_admin:
            await send_message(
                chat_id,
                "شما دسترسی ثبت سفارش گروهی ندارید.",
            )
            clear_session(chat_id)
            return True

        if not can_create_order_for_date(db, target_date):
            label = "امروز" if value == "1" else "فردا"
            await send_message(
                chat_id,
                f"⛔ مهلت ثبت سفارش برای {label} به پایان رسیده است.",
            )
            return True

        if assignment:
            site_id = assignment.site_id
        else:
            active_site = (
                db.query(Site)
                .filter(Site.is_active == True)
                .order_by(Site.id)
                .first()
            )

            if not active_site:
                await send_message(
                    chat_id,
                    "هیچ سایت فعالی برای ثبت سفارش گروهی وجود ندارد.",
                )
                return True

            site_id = active_site.id

        menu_entries = get_menu(
            db,
            site_id,
            target_date,
        )

        if not menu_entries:
            await send_message(
                chat_id,
                f"برای تاریخ {to_jalali(target_date)} منوی قابل سفارش ثبت نشده است.",
            )
            return True

        old_date_msg_id = (SESSIONS.get(str(chat_id)) or {}).get("welfare_date_msg_id")
        SESSIONS[str(chat_id)] = {
            "state": "welfare_select",
            "options": [entry.id for entry in menu_entries],
            "selected": {},
            "active_food_id": None,
            "site_id": site_id,
            "target_date": target_date,
            "employee_id": employee.id,
            "welfare_date_msg_id": old_date_msg_id,
        }

    finally:
        db.close()

    await render_welfare_selection(chat_id)
    return True


async def handle_welfare_food_choice(chat_id: str, value: str):
    session = SESSIONS.get(str(chat_id))

    if not session:
        return

    current_state = session.get("state")

    # اگر در حالت ورود تعداد هستیم، عدد فعلی را ذخیره کن و به select برگرد
    if current_state == "welfare_waiting_quantity":
        buf = session.get("welfare_qty_input", "")
        old_food_id = session.get("active_food_id")
        if buf and buf.isdigit() and old_food_id:
            try:
                n = int(buf)
                if 1 <= n <= 9999:
                    selected = session.setdefault("selected", {})
                    selected[old_food_id] = n
            except ValueError:
                pass

        # لغو تایمر auto و پاک کردن پیام عددی
        _t = _QTY_TIMERS.pop(str(chat_id), None)
        if _t and not _t.done():
            _t.cancel()
        await _welfare_cleanup_qty_msg(chat_id, session)
        session["state"] = "welfare_select"
        session["welfare_reply_sent"] = False
        session.pop("welfare_qty_input", None)

    if session.get("state") != "welfare_select":
        return

    try:
        entry_id = int(value)
    except (TypeError, ValueError):
        return

    if entry_id not in session.get("options", []):
        return

    selected = session.setdefault("selected", {})

    if entry_id not in selected:
        selected[entry_id] = 1

    session["active_food_id"] = entry_id

    await render_welfare_selection(chat_id)


async def handle_welfare_quantity_request(chat_id: str, value: str):
    session = SESSIONS.get(str(chat_id))

    if not session or session.get("state") != "welfare_select":
        return

    try:
        entry_id = int(value)
    except (TypeError, ValueError):
        return

    if entry_id not in session.get("options", []):
        return

    session["active_food_id"] = entry_id
    session["state"] = "welfare_waiting_quantity"
    session["welfare_reply_sent"] = False
    # عدد اولیه: از selected اگر داشت، وگرنه خالی
    existing_qty = (session.get("selected") or {}).get(entry_id, 0)
    session["welfare_qty_input"] = str(existing_qty) if existing_qty else ""

    # پاک کردن پیام عددی قبلی (اگر مانده)
    old_qty_msg = session.pop("welfare_qty_msg_id", None)
    if old_qty_msg:
        try:
            await delete_message(chat_id, old_qty_msg)
        except Exception:
            pass

    numeric_kb = {
        "keyboard": [
            ["5", "10", "20", "50", "100"],
            ["➖", "➕", "✍️ پاک", "✅ تأیید"],
            ["⬅️ انصراف"],
        ],
        "resize_keyboard": True,
        "one_time_keyboard": False,
    }

    initial_qty = existing_qty if existing_qty else 0
    r = await send_message(
        chat_id,
        f"🔢 تعداد فعلی: {initial_qty}\n"
        "با دکمه‌های 5/10/20/50/100 اضافه کنید یا ➖/➕ برای کم/زیاد یک‌تایی.",
        reply_markup=numeric_kb,
    )
    if isinstance(r, dict):
        new_id = r.get("result", {}).get("message_id")
        if new_id:
            session["welfare_qty_msg_id"] = new_id


async def handle_welfare_plus(chat_id: str, value: str):
    session = SESSIONS.get(str(chat_id))

    if not session or session.get("state") != "welfare_select":
        return

    try:
        entry_id = int(value)
    except (TypeError, ValueError):
        return

    selected = session.setdefault("selected", {})

    if entry_id not in selected:
        selected[entry_id] = 1
    else:
        selected[entry_id] += 1

    session["active_food_id"] = entry_id

    await render_welfare_selection(chat_id)


async def handle_welfare_minus(chat_id: str, value: str):
    session = SESSIONS.get(str(chat_id))

    if not session or session.get("state") != "welfare_select":
        return

    try:
        entry_id = int(value)
    except (TypeError, ValueError):
        return

    selected = session.setdefault("selected", {})

    if entry_id not in selected:
        return

    if selected[entry_id] <= 1:
        selected.pop(entry_id, None)
        if session.get("active_food_id") == entry_id:
            session["active_food_id"] = None
    else:
        selected[entry_id] -= 1

    await render_welfare_selection(chat_id)


async def handle_welfare_remove(chat_id: str, value: str):
    session = SESSIONS.get(str(chat_id))

    if not session or session.get("state") != "welfare_select":
        return

    try:
        entry_id = int(value)
    except (TypeError, ValueError):
        return

    selected = session.setdefault("selected", {})
    selected.pop(entry_id, None)

    if session.get("active_food_id") == entry_id:
        session["active_food_id"] = None

    await render_welfare_selection(chat_id)


async def handle_welfare_submit(chat_id: str):
    session = SESSIONS.get(str(chat_id))

    if not session or session.get("state") != "welfare_select":
        return

    selected = session.get("selected") or {}

    if not selected:
        await send_message(
            chat_id,
            "⚠️ حداقل یک غذا را انتخاب کنید.",
        )
        return

    db = SessionLocal()

    try:
        employee = get_employee(chat_id, db)

        if not employee:
            await send_message(
                chat_id,
                "ابتدا دستور /start را ارسال کنید.",
            )
            return

        target_date = session["target_date"]

        if not can_create_order_for_date(db, target_date):
            await send_message(
                chat_id,
                "⛔ مهلت ثبت سفارش به پایان رسیده است.",
            )
            return

        menu_entries = (
            db.query(MenuEntry)
            .filter(
                MenuEntry.id.in_(list(selected.keys())),
                MenuEntry.site_id == session["site_id"],
                MenuEntry.date == target_date,
                MenuEntry.status == "منتشر",
                MenuEntry.is_selectable == True,
            )
            .all()
        )

        entry_map = {entry.id: entry for entry in menu_entries}

        invalid = [
            entry_id
            for entry_id in selected
            if entry_id not in entry_map
        ]

        if invalid:
            await send_message(
                chat_id,
                "⚠️ یکی از غذاهای انتخاب‌شده دیگر قابل سفارش نیست. دوباره منو را باز کنید.",
            )
            return

        created_items = []

        # یک کد پایه برای کل سفارش گروهی
        base_code = make_code("W", db, WelfareOrder)

        idx = 0
        for entry_id, quantity in selected.items():
            if quantity <= 0:
                continue

            entry = entry_map[entry_id]
            idx += 1
            code = base_code if idx == 1 else f"{base_code}-{idx}"

            order = WelfareOrder(
                tracking_code=code,
                date=target_date,
                site_id=session["site_id"],
                food_id=entry.food_id,
                quantity=quantity,
                status="نهایی",
                source="Bale",
                created_by=employee.full_name,
            )

            db.add(order)
            created_items.append((entry.food.name, quantity))

        db.commit()

        lines = [
            "✅ سفارش گروهی با موفقیت ثبت شد.",
            f"📅 تاریخ: {to_jalali(target_date)}",
            f"🔖 کد پیگیری: {base_code}",
            "",
        ]

        for food_name, quantity in created_items:
            lines.append(f"🍽 {food_name}: {quantity} عدد")

        # جمع‌آوری همه‌ی message_idهای مرتبط با این سفارش
        inline_msg_id = session.get("welfare_inline_msg_id")
        reply_msg_id = session.get("welfare_reply_msg_id")
        date_msg_id = session.get("welfare_date_msg_id")
        legacy_msg_id = session.get("welfare_msg_id")
        qty_msg_id = session.get("welfare_qty_msg_id")

        clear_session(chat_id)

        is_admin = employee.role in ADMIN_ROLES
        is_welfare_manager = (
            db.query(WelfareManagerAssignment)
            .filter(
                WelfareManagerAssignment.employee_id == employee.id,
                WelfareManagerAssignment.is_active == True,  # noqa: E712
            )
            .first()
            is not None
        )

        await send_message(
            chat_id,
            "\n".join(lines),
            reply_markup=main_menu_keyboard(is_admin, is_welfare_manager),
        )

        for mid in (inline_msg_id, reply_msg_id, date_msg_id, legacy_msg_id, qty_msg_id):
            if mid:
                try:
                    await delete_message(chat_id, mid)
                except Exception:
                    pass

    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


_QTY_TIMERS: dict = {}
_WELFARE_NUM_TIMERS: dict = {}


def _schedule_welfare_number_commit(chat_id, food_id):
    """بعد از 0.8 ثانیه سکوت، عدد تایپ‌شده را در selected می‌نشاند."""
    key = f"{chat_id}:{food_id}"
    old = _WELFARE_NUM_TIMERS.pop(key, None)
    if old and not old.done():
        old.cancel()

    async def _commit():
        await asyncio.sleep(0.8)
        session = SESSIONS.get(str(chat_id))
        if not session or session.get("state") != "welfare_select":
            return
        if session.get("active_food_id") != food_id:
            return

        buf = session.get(f"_typing_{food_id}", "")
        if not buf or not buf.isdigit():
            return

        try:
            n = int(buf)
        except ValueError:
            return
        if n < 0 or n > 9999:
            n = min(max(n, 0), 9999)

        selected = session.setdefault("selected", {})
        selected[food_id] = n
        session[f"_typing_{food_id}"] = ""

        await render_welfare_selection(chat_id)

    async def _wrapper():
        try:
            await _commit()
        except Exception:
            pass

    try:
        _WELFARE_NUM_TIMERS[key] = asyncio.create_task(_wrapper())
    except RuntimeError:
        pass


def _schedule_qty_autoconfirm(chat_id, buf: str):
    """بعد از 1.5 ثانیه سکوت، عدد را خودکار تأیید می‌کند."""
    key = str(chat_id)
    # لغو تایمر قبلی
    old = _QTY_TIMERS.pop(key, None)
    if old and not old.done():
        old.cancel()

    async def _auto():
        await asyncio.sleep(0.7)
        session = SESSIONS.get(key)
        if not session or session.get("state") != "welfare_waiting_quantity":
            return
        # اگر کاربر رقم جدیدی زده، تایمر جدید جایگزین شده — پس این یکی اجرا نشود
        current_buf = session.get("welfare_qty_input", "")
        if current_buf != buf:
            return
        # auto-apply
        ok = await _welfare_apply_quantity(chat_id, session)
        if not ok:
            return
        await _welfare_cleanup_qty_msg(chat_id, session)
        session["state"] = "welfare_select"
        session["welfare_reply_sent"] = False
        session.pop("welfare_qty_input", None)
        await render_welfare_selection(chat_id)

    async def _wrapper():
        try:
            await _auto()
        except Exception:
            pass

    try:
        _QTY_TIMERS[key] = asyncio.create_task(_wrapper())
    except RuntimeError:
        pass


async def _welfare_cleanup_qty_msg(chat_id: str, session: dict):
    """حذف پیام عددی از چت."""
    old_id = session.pop("welfare_qty_msg_id", None)
    if old_id:
        try:
            await delete_message(chat_id, old_id)
        except Exception:
            pass


async def _welfare_apply_quantity(chat_id: str, session: dict) -> bool:
    """اعمال تعداد وارد شده روی غذای فعال. اگر معتبر بود True برمی‌گرداند."""
    buf = session.get("welfare_qty_input", "")

    if not buf or not buf.isdigit():
        # پیام خطا در پیام عددی
        msg_id = session.get("welfare_qty_msg_id")
        if msg_id:
            try:
                await edit_message_text(
                    chat_id,
                    msg_id,
                    "⛔ عددی وارد نشده. اول یک رقم بزنید.",
                )
            except Exception:
                pass
        return False

    quantity = int(buf)

    if quantity <= 0 or quantity > 9999:
        msg_id = session.get("welfare_qty_msg_id")
        if msg_id:
            try:
                await edit_message_text(
                    chat_id,
                    msg_id,
                    "⛔ عدد باید بین ۱ و ۹۹۹۹ باشد.",
                )
            except Exception:
                pass
        return False

    entry_id = session.get("active_food_id")
    if not entry_id or entry_id not in session.get("options", []):
        return False

    selected = session.setdefault("selected", {})
    selected[entry_id] = quantity
    return True


async def handle_welfare_quantities(chat_id: str, text: str):
    session = SESSIONS.get(str(chat_id))

    if not session or session.get("state") != "welfare_waiting_quantity":
        return False

    text = (text or "").strip()

    # ➕ و ➖ برای ویرایش عدد در حال ورود
    if text == "➕":
        buf = session.get("welfare_qty_input", "") or "0"
        try:
            n = int(buf) + 1
        except ValueError:
            n = 1
        if n > 9999:
            n = 9999
        session["welfare_qty_input"] = str(n)
        msg_id = session.get("welfare_qty_msg_id")
        if msg_id:
            try:
                await edit_message_text(chat_id, msg_id, f"🔢 تعداد فعلی: {n}")
            except Exception:
                pass
        return True

    if text == "➖":
        buf = session.get("welfare_qty_input", "") or "0"
        try:
            n = int(buf) - 1
        except ValueError:
            n = 0
        if n < 0:
            n = 0
        session["welfare_qty_input"] = str(n) if n > 0 else ""
        msg_id = session.get("welfare_qty_msg_id")
        if msg_id:
            display = session["welfare_qty_input"] or "0"
            try:
                await edit_message_text(chat_id, msg_id, f"🔢 تعداد فعلی: {display}")
            except Exception:
                pass
        return True

    # انصراف → برگشت به انتخاب غذا بدون تغییر
    if text == "⬅️ انصراف":
        # لغو تایمر auto
        _t = _QTY_TIMERS.pop(str(chat_id), None)
        if _t and not _t.done():
            _t.cancel()
        await _welfare_cleanup_qty_msg(chat_id, session)
        session["state"] = "welfare_select"
        session["welfare_reply_sent"] = False
        await render_welfare_selection(chat_id)
        return True

    # تأیید → اعمال تعداد
    if text == "✅ تأیید":
        # لغو تایمر auto
        _t = _QTY_TIMERS.pop(str(chat_id), None)
        if _t and not _t.done():
            _t.cancel()
        ok = await _welfare_apply_quantity(chat_id, session)
        if not ok:
            return True
        await _welfare_cleanup_qty_msg(chat_id, session)
        session["state"] = "welfare_select"
        session["welfare_reply_sent"] = False
        session.pop("welfare_qty_input", None)
        await render_welfare_selection(chat_id)
        return True

    # نگاشت اعداد فارسی به لاتین
    _fa_digits = "۰۱۲۳۴۵۶۷۸۹"
    _en_digits = "0123456789"
    _tr = str.maketrans(_fa_digits, _en_digits)
    text_normalized = text.translate(_tr)

    # ✍️ پاک → صفر کردن
    if text == "✍️ پاک":
        session["welfare_qty_input"] = ""
        msg_id = session.get("welfare_qty_msg_id")
        if msg_id:
            try:
                await edit_message_text(chat_id, msg_id, "🔢 تعداد فعلی: 0")
            except Exception:
                pass
        return True

    # دکمه‌های افزودنی: 5, 10, 20, 50, 100
    if text in {"5", "10", "20", "50", "100"}:
        add = int(text)
        try:
            cur = int(session.get("welfare_qty_input", "0") or "0")
        except ValueError:
            cur = 0
        new_val = cur + add
        if new_val > 9999:
            new_val = 9999
        session["welfare_qty_input"] = str(new_val)
        msg_id = session.get("welfare_qty_msg_id")
        if msg_id:
            try:
                await edit_message_text(chat_id, msg_id, f"🔢 تعداد فعلی: {new_val}")
            except Exception:
                pass
        return True

    # دکمه‌های عددی (یک رقم) → append/prepend بر اساس message_id (فقط برای تایپ دستی)
    if text_normalized.isdigit() and len(text_normalized) == 1:
        text = text_normalized
        cur_mid = session.get("_cur_msg_id")
        last_mid = session.get("_last_digit_mid")
        buf = session.get("welfare_qty_input", "")

        if last_mid is None or cur_mid is None or cur_mid > last_mid:
            new_buf = buf + text
        else:
            new_buf = text + buf

        if len(new_buf) > 5:
            new_buf = new_buf[:5]
        buf = new_buf
        session["welfare_qty_input"] = buf
        if cur_mid is not None:
            session["_last_digit_mid"] = cur_mid

        msg_id = session.get("welfare_qty_msg_id")
        if msg_id:
            display = buf if buf else "(هنوز وارد نشده)"
            try:
                await edit_message_text(
                    chat_id,
                    msg_id,
                    f"🔢 عدد وارد شده: {display}",
                )
            except Exception:
                pass
        return True

    # تایپ دستی عدد کامل (چندرقمی) → جایگزین
    if text_normalized.isdigit() and len(text_normalized) > 1:
        text = text_normalized
        if len(text) <= 5:
            session["welfare_qty_input"] = text
            cur_mid = session.get("_cur_msg_id")
            if cur_mid is not None:
                session["_last_digit_mid"] = cur_mid

        msg_id = session.get("welfare_qty_msg_id")
        if msg_id:
            try:
                await edit_message_text(
                    chat_id,
                    msg_id,
                    f"🔢 عدد وارد شده: {session.get('welfare_qty_input', '')}",
                )
            except Exception:
                pass
        _schedule_qty_autoconfirm(chat_id, session.get("welfare_qty_input", ""))
        return True

    # بقیه متن‌ها نادیده گرفته می‌شوند
    return True


async def handle_welfare_reply_action(chat_id: str, text: str) -> bool:
    """مسیریابی دکمه‌های reply keyboard در حالت welfare_select."""
    session = SESSIONS.get(str(chat_id))

    if not session or session.get("state") != "welfare_select":
        return False

    text = (text or "").strip()
    # ZWSP (دکمه‌های نامرئی) را نادیده بگیر
    if text == "\u200b":
        return True

    active_food_id = session.get("active_food_id")

    async def _warn_no_food():
        r = await send_message(
            chat_id,
            "⚠️ اول یک غذا از دکمه‌های چسبیده به پیام بالا انتخاب کنید.",
        )
        if isinstance(r, dict):
            wid = r.get("result", {}).get("message_id")
            if wid:
                asyncio.create_task(_delete_later(chat_id, wid, 1.5))

    # ✍️ پاک — پاک کردن عدد فعلی
    if text == "✍️ پاک":
        if active_food_id:
            session[f"_typing_{active_food_id}"] = ""
            session.pop(f"_typing_last_mid_{active_food_id}", None)
            selected = session.setdefault("selected", {})
            selected[active_food_id] = 0
            await render_welfare_selection(chat_id)
        return True

    # 🗑 حذف — قبل از بررسی اعداد
    if text == "🗑":
        if not active_food_id:
            await _warn_no_food()
            return True
        await handle_welfare_remove(chat_id, str(active_food_id))
        return True

    # اگر عدد زد ولی غذایی فعال نیست → هشدار
    if text.isdigit() and not active_food_id:
        await _warn_no_food()
        return True

    # اعداد ۰–۹ → append/prepend فوری
    if text.isdigit() and len(text) == 1 and active_food_id:
        buf_key = f"_typing_{active_food_id}"
        last_mid_key = f"_typing_last_mid_{active_food_id}"

        cur_mid = session.get("_cur_msg_id")
        last_mid = session.get(last_mid_key)
        buf = session.get(buf_key, "")

        if last_mid is None or cur_mid is None or cur_mid > last_mid:
            new_buf = buf + text
        else:
            new_buf = text + buf

        if len(new_buf) > 4:
            new_buf = new_buf[:4]
        session[buf_key] = new_buf
        if cur_mid is not None:
            session[last_mid_key] = cur_mid

        try:
            n = int(new_buf)
        except ValueError:
            n = 0
        if n > 9999:
            n = 9999
        selected = session.setdefault("selected", {})
        selected[active_food_id] = n

        await render_welfare_selection(chat_id)
        return True

    if text == "➕":
        if not active_food_id:
            await _warn_no_food()
            return True
        session[f"_typing_{active_food_id}"] = ""
        await handle_welfare_plus(chat_id, str(active_food_id))
        return True

    if text == "➖":
        if not active_food_id:
            await _warn_no_food()
            return True
        session[f"_typing_{active_food_id}"] = ""
        await handle_welfare_minus(chat_id, str(active_food_id))
        return True

    if text == "🗑 حذف":
        if not active_food_id:
            await _warn_no_food()
            return True
        await handle_welfare_remove(chat_id, str(active_food_id))
        return True

    if text == "✍️ ورود تعداد":
        # دیگر استفاده نمی‌شود، ولی برای سازگاری عقب‌رو حفظ می‌شود
        if not active_food_id:
            await _warn_no_food()
            return True
        await handle_welfare_quantity_request(chat_id, str(active_food_id))
        return True

    if text in ("✅ ثبت", "✅ ثبت سفارش"):
        if active_food_id:
            session[f"_typing_{active_food_id}"] = ""
        await handle_welfare_submit(chat_id)
        return True

    food_name_map = session.get("food_name_map") or {}

    if text in food_name_map:
        entry_id = food_name_map[text]
        selected = session.setdefault("selected", {})

        if entry_id not in selected:
            selected[entry_id] = 1

        session["active_food_id"] = entry_id

        await render_welfare_selection(chat_id)
        return True

    return False


# ADMIN MENU
# =========================================================

async def handle_menu_admin(chat_id: str):
    # پاک کردن پیام‌های menu قبلی
    await _delete_menu_msgs(chat_id)

    db = SessionLocal()

    try:
        employee = get_employee(chat_id, db)

        if not employee:
            await send_message(
                chat_id,
                "ابتدا دستور /start را ارسال کنید.",
            )
            return

        if employee.role not in ADMIN_ROLES and not employee.can_debug:
            await send_message(
                chat_id,
                "شما دسترسی مدیریت منو را ندارید.",
            )
            return

        sites = (
            db.query(Site)
            .filter(Site.is_active == True)  # noqa: E712
            .order_by(Site.id)
            .all()
        )

        if not sites:
            await send_message(
                chat_id,
                "هیچ سایتی ثبت نشده است.",
            )
            return

        names = [site.name for site in sites]
        if len(names) != len(set(names)):
            await send_message(
                chat_id,
                "⚠️ نام سایت‌ها تکراری است. لطفاً ابتدا از پنل مدیریت اصلاح کنید.",
            )
            return

        SESSIONS[str(chat_id)] = {
            "state": "menu_choose_site",
            "options": [site.id for site in sites],
            "site_options": {site.name: site.id for site in sites},
        }

        keyboard_rows = [[site.name] for site in sites]
        keyboard_rows.append(["🏠 منوی اصلی"])

        _r = await send_message(
            chat_id,
            "مدیریت منو\n\nسایت مورد نظر را از دکمه‌های پایین انتخاب کنید 👇",
            reply_markup={
                "keyboard": keyboard_rows,
                "resize_keyboard": True,
                "one_time_keyboard": False,
            },
        )
        if isinstance(_r, dict):
            _nid = _r.get("result", {}).get("message_id")
            if _nid:
                _track_menu_msg(chat_id, _nid)

    finally:
        db.close()


async def handle_menu_site_choice(chat_id: str, text: str, msg_id: int | None = None):
    session = SESSIONS.get(str(chat_id))
    _s = session.get("state") if session else None
    print(f"[DBG-MENU] enter text={text!r} state={_s} msg_id={msg_id}", flush=True)

    if not session or session.get("state") != "menu_choose_site":
        return False

    # حذف همه‌ی پیام‌های مرحله‌ی قبل (پیام سایت)
    await _delete_menu_msgs(chat_id)

    text = (text or "").strip()
    site_options = session.get("site_options", {}) or {}

    site_id = None
    if text in site_options:
        site_id = site_options[text]
    elif text.isdigit():
        options = session.get("options", [])
        idx = int(text)
        if 1 <= idx <= len(options):
            site_id = options[idx - 1]

    if site_id is None:
        return False

    db = SessionLocal()

    try:
        site = (
            db.query(Site)
            .filter(Site.id == site_id)
            .first()
        )

        foods = (
            db.query(Food)
            .filter(Food.is_active == True)  # noqa: E712
            .order_by(Food.id)
            .all()
        )

        if not site or not foods:
            await send_message(
                chat_id,
                "سایت یا غذا پیدا نشد.",
            )
            clear_session(chat_id)
            return True

        session["state"] = "menu_choose_foods"
        session["site_id"] = site.id
        session["site_name"] = site.name
        session["food_options"] = {food.name: food.id for food in foods}

        # غذاهای قبلاً ثبت‌شده در منوی امروز این سایت را ✅ کن
        today = today_iran()
        existing_entries = (
            db.query(MenuEntry)
            .filter(
                MenuEntry.site_id == site.id,
                MenuEntry.date == today,
            )
            .all()
        )
        session["selected_foods"] = {e.food_id for e in existing_entries}

        if msg_id is not None:
            session["menu_food_msg_id"] = msg_id

    finally:
        db.close()

    # پیام «سایت را انتخاب کنید» را حذف کن (دیگر لازم نیست)
    site_msg = session.pop("menu_site_msg_id", None)
    if site_msg:
        try:
            await delete_message(chat_id, site_msg)
        except Exception:
            pass

    # carrier برای به‌روزرسانی کیبورد پایین
    _cr = await send_message(
        chat_id,
        "\u200b",
        reply_markup={
            "keyboard": [["📤 ثبت منو", "🏠 منوی اصلی"]],
            "resize_keyboard": True,
            "one_time_keyboard": False,
        },
    )
    if isinstance(_cr, dict):
        _cid = _cr.get("result", {}).get("message_id")
        _track_menu_msg(chat_id, _cid)

    await render_menu_food_selection(chat_id)
    return True


async def render_menu_food_selection(chat_id: str):
    session = SESSIONS.get(str(chat_id))
    if not session or session.get("state") != "menu_choose_foods":
        return

    food_options = session.get("food_options", {})
    selected = session.get("selected_foods", set())

    lines = [
        "👨‍💼 مدیریت منو",
        f"سایت: {session.get('site_name', '')}",
        f"📅 تاریخ: {to_jalali(today_iran())}",
        "",
    ]

    if selected:
        lines.append("غذاهای انتخابی:")
        for name, fid in food_options.items():
            if fid in selected:
                lines.append(f"✅ {name}")
        lines.append("")

    lines.append("روی غذاها بزنید تا انتخاب/لغو شوند.")
    lines.append("سپس «📤 ثبت منو» را بزنید.")

    food_buttons = []
    for name, fid in food_options.items():
        if fid in selected:
            label = f"✅ {name}"
        else:
            label = f"🍽 {name}"
        food_buttons.append({
            "text": label,
            "callback_data": f"menu_toggle:{fid}",
        })

    rows = []
    for i in range(0, len(food_buttons), 2):
        rows.append(food_buttons[i:i + 2])

    inline_kb = {"inline_keyboard": rows}

    msg_id = session.get("menu_food_msg_id")

    if msg_id:
        r = await edit_message_text(chat_id, msg_id, "\n".join(lines), inline_kb)
        if isinstance(r, dict) and not r.get("ok"):
            # اگر ویرایش نشد، پیام جدید بفرست
            r = await send_message(chat_id, "\n".join(lines), inline_kb)
            if isinstance(r, dict):
                nid = r.get("result", {}).get("message_id")
                if nid:
                    session["menu_food_msg_id"] = nid
    else:
        r = await send_message(chat_id, "\n".join(lines), inline_kb)
        if isinstance(r, dict):
            nid = r.get("result", {}).get("message_id")
            if nid:
                session["menu_food_msg_id"] = nid


async def handle_menu_toggle_cb(chat_id: str, value: str):
    """toggle غذا از طریق callback."""
    session = SESSIONS.get(str(chat_id))
    if not session or session.get("state") != "menu_choose_foods":
        return

    try:
        fid = int(value)
    except (TypeError, ValueError):
        return

    selected = session.get("selected_foods", set())
    if fid in selected:
        selected.discard(fid)
    else:
        selected.add(fid)
    session["selected_foods"] = selected

    await render_menu_food_selection(chat_id)


async def handle_menu_submit_cb(chat_id: str):
    """ثبت منو از طریق callback."""
    await handle_menu_submit(chat_id, "📤 ثبت منو")


async def handle_menu_toggle_food(chat_id: str, text: str) -> bool:
    session = SESSIONS.get(str(chat_id))
    if not session or session.get("state") != "menu_choose_foods":
        return False

    text = (text or "").strip()

    # اگر «📤 ثبت منو» یا «🏠 منوی اصلی» است، این handler دخالت نکند
    if text in ("📤 ثبت منو", "✅ ثبت منو", "🏠 منوی اصلی"):
        return False

    # تبدیل label با ✅ یا 🍽 به نام خالص
    stripped = text
    for prefix in ("✅ ", "🍽 "):
        if stripped.startswith(prefix):
            stripped = stripped[len(prefix):]
            break

    # پیدا کردن fid از روی نام خالص
    food_options = session.get("food_options", {}) or {}
    fid = None
    if stripped in food_options:
        fid = food_options[stripped]

    if fid is None:
        return False
    selected = session.get("selected_foods", set())
    if fid in selected:
        selected.discard(fid)
    else:
        selected.add(fid)
    session["selected_foods"] = selected

    await render_menu_food_selection(chat_id)
    return True


async def handle_menu_submit(chat_id: str, text: str = "") -> bool:
    session = SESSIONS.get(str(chat_id))
    if not session or session.get("state") != "menu_choose_foods":
        return False

    if (text or "").strip() not in ("📤 ثبت منو", "✅ ثبت منو"):
        return False

    selected = session.get("selected_foods", set())
    if not selected:
        await send_message(chat_id, "⚠️ حداقل یک غذا را انتخاب کنید.")
        return True

    site_id = session.get("site_id")
    db = SessionLocal()
    added = []
    removed = []
    try:
        target_date = today_iran()

        # همه‌ی entries امروز این سایت
        existing_entries = (
            db.query(MenuEntry)
            .filter(
                MenuEntry.site_id == site_id,
                MenuEntry.date == target_date,
            )
            .all()
        )
        existing_by_fid = {e.food_id: e for e in existing_entries}

        # حذف مواردی که در DB هستند ولی در انتخاب کاربر نیستند
        for food_id, entry in existing_by_fid.items():
            if food_id not in selected:
                food = db.query(Food).filter(Food.id == food_id).first()
                if food:
                    removed.append(food.name)
                db.delete(entry)
        db.flush()

        # اضافه کردن موارد جدید + به‌روزرسانی display_order
        for display_order, food_id in enumerate(sorted(selected), start=1):
            food = db.query(Food).filter(Food.id == food_id).first()
            if not food:
                continue
            if food_id in existing_by_fid:
                # به‌روزرسانی display_order
                existing_by_fid[food_id].display_order = display_order
            else:
                entry = MenuEntry(
                    date=target_date,
                    site_id=site_id,
                    food_id=food_id,
                    display_order=display_order,
                    status="منتشر",
                    is_selectable=True,
                )
                db.add(entry)
                added.append(food.name)

        db.commit()
    finally:
        db.close()

    # نقش کاربر برای کیبورد اصلی
    db2 = SessionLocal()
    is_admin = False
    is_wm = False
    try:
        emp = get_employee(chat_id, db2)
        if emp:
            is_admin = emp.role in ADMIN_ROLES
            is_wm = (
                db2.query(WelfareManagerAssignment)
                .filter(
                    WelfareManagerAssignment.employee_id == emp.id,
                    WelfareManagerAssignment.is_active == True,  # noqa: E712
                )
                .first()
                is not None
            )
    finally:
        db2.close()

    prev_msg_id = session.get("menu_food_msg_id")
    clear_session(chat_id)

    parts = []
    if added:
        parts.append("➕ اضافه شد: " + "، ".join(added))
    if removed:
        parts.append("➖ حذف شد: " + "، ".join(removed))
    if not added and not removed:
        msg = "ℹ️ منوی امروز بدون تغییر ماند."
    else:
        msg = "✅ منوی امروز به‌روزرسانی شد.\n\n" + "\n".join(parts)

    if prev_msg_id:
        try:
            await edit_message_text(chat_id, prev_msg_id, msg, {"inline_keyboard": []})
        except Exception:
            await send_message(chat_id, msg)
    else:
        await send_message(chat_id, msg)

    # state را menu_done بگذار تا auto-delete پیام‌های بعدی کاربر هم فعال بماند
    SESSIONS[str(chat_id)] = {"state": "menu_done"}

    # carrier برای برگرداندن کیبورد اصلی — با تأخیر در background
    async def _restore_main():
        await asyncio.sleep(3.0)
        try:
            if prev_msg_id:
                await delete_message(chat_id, prev_msg_id)
        except Exception:
            pass
        try:
            r = await send_message(
                chat_id,
                "🏠 به منوی اصلی برگشتید.",
                reply_markup=main_menu_keyboard(is_admin, is_wm),
            )
            if isinstance(r, dict):
                mid = r.get("result", {}).get("message_id")
                if mid:
                    asyncio.create_task(_delete_later(chat_id, mid, 2.5))
        except Exception:
            pass

    asyncio.create_task(_restore_main())

    return True


async def handle_menu_food_choice(chat_id: str, text: str):
    session = SESSIONS.get(str(chat_id))

    if not session or session.get("state") != "menu_choose_foods":
        return False

    parts = text.strip().split()

    if not parts or not all(p.isdigit() for p in parts):
        await send_message(
            chat_id,
            "فقط شماره غذاها را با فاصله ارسال کنید.\n"
            "مثال: 1 3",
        )
        return True

    indices = [int(p) for p in parts]

    if any(
        i < 1 or i > len(session["food_ids"])
        for i in indices
    ):
        await send_message(
            chat_id,
            "شماره غذا نامعتبر است.",
        )
        return True

    db = SessionLocal()

    try:
        target_date = today_iran()
        site_id = session["site_id"]

        added = []

        for display_order, index in enumerate(indices, start=1):
            food_id = session["food_ids"][index - 1]

            existing = (
                db.query(MenuEntry)
                .filter(
                    MenuEntry.site_id == site_id,
                    MenuEntry.date == target_date,
                    MenuEntry.food_id == food_id,
                )
                .first()
            )

            if existing:
                continue

            food = (
                db.query(Food)
                .filter(Food.id == food_id)
                .first()
            )

            if not food:
                continue

            entry = MenuEntry(
                date=target_date,
                site_id=site_id,
                food_id=food_id,
                display_order=display_order,
                status="منتشر",
                is_selectable=True,
            )

            db.add(entry)
            added.append(food.name)

        db.commit()

        if added:
            await send_message(
                chat_id,
                "منوی امروز منتشر شد ✅\n\n"
                + "\n".join(added),
            )
        else:
            await send_message(
                chat_id,
                "غذاهای انتخاب‌شده قبلاً در منوی امروز وجود داشتند.",
            )

    finally:
        db.close()
        clear_session(chat_id)

    return True


# =========================================================
# WEBHOOK
# =========================================================

def build_kitchen_report_lines(db, target_date) -> list[str] | None:
    personal_rows = (
        db.query(
            Site.id.label("site_id"),
            Site.name.label("site_name"),
            Food.name.label("food_name"),
            func.sum(PersonalOrder.quantity).label("qty"),
        )
        .join(Employee, PersonalOrder.employee_id == Employee.id)
        .join(Site, Employee.site_id == Site.id)
        .join(Food, PersonalOrder.food_id == Food.id)
        .filter(PersonalOrder.date == target_date)
        .group_by(Site.id, Site.name, Food.name)
        .all()
    )

    welfare_rows = (
        db.query(
            Site.id.label("site_id"),
            Site.name.label("site_name"),
            Food.name.label("food_name"),
            func.sum(WelfareOrder.quantity).label("qty"),
        )
        .join(Site, WelfareOrder.site_id == Site.id)
        .join(Food, WelfareOrder.food_id == Food.id)
        .filter(WelfareOrder.date == target_date)
        .group_by(Site.id, Site.name, Food.name)
        .all()
    )

    combined = {}
    for row in personal_rows:
        key = (row.site_name, row.food_name)
        combined.setdefault(key, {"personal": 0, "welfare": 0})
        combined[key]["personal"] += row.qty
    for row in welfare_rows:
        key = (row.site_name, row.food_name)
        combined.setdefault(key, {"personal": 0, "welfare": 0})
        combined[key]["welfare"] += row.qty

    if not combined:
        return None

    lines = [f"گزارش آشپزخانه - {to_jalali(target_date)}"]
    for (site_name, food_name), qty in combined.items():
        total = qty["personal"] + qty["welfare"]
        lines.append(
            f"{site_name} | {food_name}: شخصی {qty['personal']} + رفاهی {qty['welfare']} = {total}"
        )
    return lines


async def handle_report(chat_id: str):
    db = SessionLocal()
    try:
        employee = (
            db.query(Employee)
            .filter(Employee.bale_chat_id == str(chat_id))
            .first()
        )
        if not employee:
            await send_message(
                chat_id,
                "ابتدا باید شناسایی شوید. لطفاً دستور /start را ارسال کنید.",
            )
            return

        if employee.role not in ADMIN_ROLES and not employee.can_debug:
            await send_message(chat_id, "شما دسترسی مشاهده گزارش را ندارید.")
            return

        today = today_iran()

        lines = build_kitchen_report_lines(db, today)

        if not lines:
            await send_message(chat_id, f"برای تاریخ {to_jalali(today)} سفارشی ثبت نشده است.")
            return

        await send_message(chat_id, "\n".join(lines))
    finally:
        db.close()


@router.post("/bale/webhook")
async def bale_webhook(request: Request):
    update = await request.json()

    callback = update.get("callback_query")

    if callback:
        cq_id = callback.get("id")
        data = callback.get("data") or ""
        cb_message = callback.get("message") or {}
        cb_chat = cb_message.get("chat") or {}
        cb_chat_id = cb_chat.get("id")

        if cb_chat_id is not None:
            prefix, _, value = data.partition(":")
            print(f"[DBG-CB] data={data!r} prefix={prefix!r} value={value!r}", flush=True)

            if prefix == "nav":
                await handle_nav(cb_chat_id, value)
            elif prefix == "welfare_date":
                await handle_welfare_date_choice(cb_chat_id, value)
            elif prefix == "order_date":
                await handle_order_date_choice(cb_chat_id, value, force_new=True)
            elif prefix == "order_food":
                await handle_order_food_choice(cb_chat_id, value)
            elif prefix == "order_confirm":
                await handle_order_confirm(cb_chat_id, value)
            elif prefix == "welfare_food":
                await handle_welfare_food_choice(cb_chat_id, value)
            elif prefix == "welfare_plus":
                await handle_welfare_plus(cb_chat_id, value)
            elif prefix == "welfare_minus":
                await handle_welfare_minus(cb_chat_id, value)
            elif prefix == "welfare_remove":
                await handle_welfare_remove(cb_chat_id, value)
            elif prefix == "welfare_qty":
                await handle_welfare_quantity_request(cb_chat_id, value)
            elif prefix == "welfare_submit":
                await handle_welfare_submit(cb_chat_id)
            elif prefix == "welfare_noop":
                pass
            elif prefix == "cancel_choice":
                await handle_cancel_choice(cb_chat_id, value)
            elif prefix == "myorder_edit":
                await handle_myorder_edit(cb_chat_id, value)
            elif prefix == "myorder_cancel":
                await handle_myorder_cancel(cb_chat_id, value)
            elif prefix == "menu_site_choice":
                await handle_menu_site_choice(cb_chat_id, value, cb_message.get("message_id"))
            elif prefix == "menu_toggle":
                await handle_menu_toggle_cb(cb_chat_id, value)
            elif prefix == "menu_submit":
                await handle_menu_submit_cb(cb_chat_id)
            elif prefix == "week_day":
                await handle_week_day_choice(cb_chat_id, value)
            elif prefix == "week_back":
                await handle_weekmenu(cb_chat_id)

        await answer_callback_query(cq_id)
        return {"ok": True}

    message = update.get("message") or {}
    chat = message.get("chat") or {}

    chat_id = chat.get("id")

    if chat_id is None:
        return {"ok": True}

    chat_key = str(chat_id)

    contact = message.get("contact")
    text = (message.get("text") or "").strip()

    # ذخیره message_id فعلی برای ترتیب‌دهی در welfare
    _mid = message.get("message_id")
    if _mid is not None:
        _sess = SESSIONS.get(chat_key)
        if _sess is not None:
            _sess["_cur_msg_id"] = _mid

    # حذف خودکار پیام کاربر:
    # - اگر دستور است (با / شروع می‌شود)
    # - اگر از دکمه‌های BUTTON_COMMANDS آمده
    # - یا در فلوهای menu و welfare و order است
    _mid = message.get("message_id")
    if _mid:
        _should_delete = (
            text.startswith("/")
            or text in BUTTON_COMMANDS
            or text in ("🏠 منوی اصلی", "🔙 بازگشت")
        )
        if not _should_delete:
            _sess = SESSIONS.get(str(chat_id))
            if _sess:
                _state = str(_sess.get("state", ""))
                if _state.startswith(("welfare", "menu", "order")) or _state == "menu_done":
                    _should_delete = True
        if _should_delete:
            try:
                await delete_message(chat_id, _mid)
            except Exception:
                pass

    # ZWSP / دکمه‌های نامرئی → نادیده
    if text in ("\u200b", "\u200c", "\u200d", "\u2060"):
        return {"ok": True}

    if text == "🔙 بازگشت":
        await handle_nav(chat_id, "back")
        return {"ok": True}

    if text == "🏠 منوی اصلی":
        await handle_nav(chat_id, "home")
        return {"ok": True}

    if text in BUTTON_COMMANDS:
        text = BUTTON_COMMANDS[text]

    # شماره موبایل
    if contact:
        await handle_contact(
            chat_id,
            contact.get("phone_number", ""),
        )
        return {"ok": True}

    # دستورات اصلی
    if text == "/start":
        # session را پاک کن ولی _LAST_MSG_IDS را نگه دار
        clear_session(chat_key)
        await handle_start(chat_id)
        return {"ok": True}

    if text == "/help":
        clear_session(chat_key)
        await handle_help(chat_id)
        return {"ok": True}

    if text == "/order":
        clear_session(chat_key)
        await handle_order(chat_id)
        return {"ok": True}

    if text == "/weekmenu":
        clear_session(chat_key)
        await handle_weekmenu(chat_id)
        return {"ok": True}

    if text == "/myorder":
        clear_session(chat_key)
        await handle_myorder(chat_id)
        return {"ok": True}

    if text == "/cancel":
        clear_session(chat_key)
        await handle_cancel(chat_id)
        return {"ok": True}

    if text == "/welfare":
        clear_session(chat_key)
        await handle_welfare(chat_id)
        return {"ok": True}

    if text == "/menu":
        clear_session(chat_key)
        await handle_menu_admin(chat_id)
        return {"ok": True}
    if text == "/report":
        clear_session(chat_key)
        await handle_report(chat_id)
        return {"ok": True}

    if text == "/sysadmin":
        clear_session(chat_key)
        await handle_sysadmin(chat_id)
        return {"ok": True}

    # ادامه وضعیت‌های مکالمه
    handlers = [
        handle_order_date_choice,
        handle_order_food_choice,
        handle_order_quantity,
        handle_order_confirm,
        handle_increase_quantity,
        handle_cancel_choice,
        handle_welfare_quantities,
        handle_welfare_reply_action,
        handle_welfare_date_choice,
        handle_menu_submit,
        handle_menu_site_choice,
    ]

    for handler in handlers:
        handled = await handler(chat_id, text)

        if handled:
            return {"ok": True}

    return {"ok": True}

def get_daily_summary_text(db):
    return "📋 خلاصه آمار ثبت‌شده (تست)"

def get_unregistered_employees_text(db):
    return "⚠️ لیست افراد سفارش‌نداده (تست)"

async def handle_send_reminder_to_unregistered(db):
    pass

async def handle_send_excel_report(chat_id, db):
    pass


def week_start_date():
    today = today_iran()
    days_since_saturday = (today.weekday() - 5) % 7
    return today - timedelta(days=days_since_saturday)


# =========================================================
# منوی هفتگی /weekmenu
# =========================================================

WEEKDAY_FA = {
    5: "شنبه",
    6: "یکشنبه",
    0: "دوشنبه",
    1: "سه‌شنبه",
    2: "چهارشنبه",
    3: "پنجشنبه",
    4: "جمعه",
}


async def handle_weekmenu(chat_id: str):
    db = SessionLocal()

    try:
        employee = get_employee(chat_id, db)

        if not employee:
            await send_message(
                chat_id,
                "ابتدا باید شناسایی شوید.\n"
                "دستور /start را ارسال کنید.",
            )
            return

        start_date = week_start_date()
        buttons = []

        for offset in range(7):
            target_date = start_date + timedelta(days=offset)

            has_menu = bool(get_menu(db, employee.site_id, target_date))

            has_order = (
                db.query(PersonalOrder)
                .filter(
                    PersonalOrder.employee_id == employee.id,
                    PersonalOrder.date == target_date,
                )
                .first()
                is not None
            )

            if has_order:
                icon = "✅"
            elif has_menu:
                icon = "🍽"
            else:
                icon = "🚫"

            weekday_fa = WEEKDAY_FA.get(target_date.weekday(), "")
            jalali_day = jdatetime.date.fromgregorian(date=target_date).day
            label = f"{icon} {weekday_fa} {jalali_day}"

            buttons.append({"text": label, "callback_data": f"week_day:{offset}"})

        rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]

        SESSIONS[str(chat_id)] = {
            "state": "weekmenu_choose_day",
            "employee_id": employee.id,
            "site_id": employee.site_id,
        }

        await send_message(
            chat_id,
            "📅 منوی هفتگی — روز موردنظر را انتخاب کنید:\n\n"
            "✅ = سفارش ثبت‌شده   🍽 = منو موجود   🚫 = بدون منو",
            reply_markup={"inline_keyboard": rows},
        )

    finally:
        db.close()


async def handle_week_day_choice(chat_id: str, value: str):
    session = SESSIONS.get(str(chat_id))

    if not session or session.get("state") != "weekmenu_choose_day":
        return

    try:
        offset = int(value)
    except ValueError:
        return

    target_date = week_start_date() + timedelta(days=offset)

    db = SessionLocal()

    try:
        employee = (
            db.query(Employee)
            .filter(Employee.id == session["employee_id"])
            .first()
        )

        if not employee:
            await send_message(chat_id, "کاربر پیدا نشد.")
            clear_session(chat_id)
            return

        existing = (
            db.query(PersonalOrder)
            .filter(
                PersonalOrder.employee_id == employee.id,
                PersonalOrder.date == target_date,
            )
            .first()
        )

        if existing:
            if can_increase_order(db, target_date):
                await send_message(
                    chat_id,
                    f"برای تاریخ {to_jalali(target_date)} "
                    "قبلاً سفارش دارید.\n\n"
                    f"غذا: {existing.food.name}\n"
                    f"تعداد فعلی: {existing.quantity}\n\n"
                    "برای افزایش تعداد، تعداد جدید را ارسال کنید.\n"
                    "مثال: 3",
                )
                SESSIONS[str(chat_id)] = {
                    "state": "increase_quantity",
                    "employee_id": employee.id,
                    "order_id": existing.id,
                    "target_date": target_date,
                }
            else:
                await send_message(
                    chat_id,
                    f"برای تاریخ {to_jalali(target_date)} "
                    "سفارش شما قبلاً ثبت شده است.\n\n"
                    f"غذا: {existing.food.name}\n"
                    f"تعداد: {existing.quantity}\n"
                    f"کد پیگیری: {existing.tracking_code}",
                )
                clear_session(chat_id)
            return

        if not can_create_order_for_date(db, target_date):
            if target_date == today_iran():
                deadline = get_setting_value(db, "SAME_DAY_DEADLINE", "09:00")
                msg = (
                    "⛔ مهلت ثبت سفارش امروز "
                    f"تا ساعت {deadline} بوده و به پایان رسیده است."
                )
            else:
                deadline = get_setting_value(db, "NORMAL_DEADLINE", "15:00")
                msg = (
                    f"⛔ مهلت ثبت سفارش {to_jalali(target_date)} "
                    "به پایان رسیده است."
                )
            await send_message(chat_id, msg)
            clear_session(chat_id)
            return

        menu_entries = get_menu(db, employee.site_id, target_date)

        if not menu_entries:
            await send_message(
                chat_id,
                f"برای تاریخ {to_jalali(target_date)} "
                "منوی منتشرشده‌ای وجود ندارد.",
            )
            clear_session(chat_id)
            return

        lines = [f"منوی سفارش برای {to_jalali(target_date)}:", ""]
        keyboard_rows = []

        for idx, entry in enumerate(menu_entries, start=1):
            lines.append(f"{idx}️⃣ {entry.food.name}")

        for idx, entry in enumerate(menu_entries, start=1):
            keyboard_rows.append(
                [{"text": f"{idx}. {entry.food.name}", "callback_data": f"order_food:{idx}"}]
            )

        keyboard_rows.append(
            [{"text": "🔙 بازگشت به هفته", "callback_data": "week_back:1"}]
        )

        SESSIONS[str(chat_id)] = {
            "state": "order_choose_food",
            "employee_id": employee.id,
            "site_id": employee.site_id,
            "target_date": target_date,
            "options": [entry.id for entry in menu_entries],
        }

        await send_message(
            chat_id,
            "\n".join(lines),
            reply_markup={"inline_keyboard": keyboard_rows},
        )

    finally:
        db.close()
