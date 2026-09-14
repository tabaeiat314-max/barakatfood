import httpx
from app.config import settings

BASE_URL = f"https://tapi.bale.ai/bot{settings.BALE_BOT_TOKEN}"


async def send_message(chat_id: str | int, text: str, reply_markup: dict | None = None):
    payload = {"chat_id": chat_id, "text": text}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(f"{BASE_URL}/sendMessage", json=payload)
        return resp.json()


async def request_contact(chat_id: str | int, text: str):
    reply_markup = {
        "keyboard": [
            [{"text": "ارسال شماره موبایل من", "request_contact": True}]
        ],
        "resize_keyboard": True,
        "one_time_keyboard": True,
    }
    return await send_message(chat_id, text, reply_markup=reply_markup)


async def remove_keyboard(chat_id: str | int, text: str):
    return await send_message(chat_id, text, reply_markup={"remove_keyboard": True})


def main_menu_keyboard(is_admin: bool, is_welfare_manager: bool) -> dict:
    rows = [
        [
            {"text": "🍽 سفارش"},
            {"text": "📋 سفارش‌های من"},
            {"text": "❌ لغو سفارش"},
        ],
    ]
    if is_welfare_manager or is_admin:
        rows.append([
            {"text": "👨‍💼 سفارش گروهی"},
            {"text": "ℹ️ راهنما"},
        ])
    else:
        rows.append([{"text": "ℹ️ راهنما"}])
    if is_admin:
        rows.append([
            {"text": "⚙️ مدیریت منو"},
            {"text": "📊 گزارش"},
            {"text": "⚙️ مدیریت سیستم"},
        ])
    return {
        "keyboard": rows,
        "resize_keyboard": True,
        "one_time_keyboard": False,
    }


async def edit_message_text(
    chat_id: str,
    message_id: int | str,
    text: str,
    reply_markup: dict | None = None,
):
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
    }

    if reply_markup is not None:
        payload["reply_markup"] = reply_markup

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{BASE_URL}/editMessageText",
            json=payload,
        )
        return resp.json()


async def delete_message(
    chat_id: str | int,
    message_id: int | str,
):
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
    }

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{BASE_URL}/deleteMessage",
            json=payload,
        )
        return resp.json()


async def answer_callback_query(callback_query_id: str, text: str | None = None):
    payload = {"callback_query_id": callback_query_id}
    if text:
        payload["text"] = text
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(f"{BASE_URL}/answerCallbackQuery", json=payload)
        return resp.json()


async def get_webhook_info():
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(f"{BASE_URL}/getWebhookInfo")
        return resp.json()


async def set_webhook(url: str):
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(f"{BASE_URL}/setWebhook", data={"url": url})
        return resp.json()
