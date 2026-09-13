path = "backend/app/bale/router.py"

with open(path, "r", encoding="utf-8") as f:
    content = f.read()

# ---------------------------------------------------------
# 1. text-based nav buttons ("🔙 بازگشت" / "🏠 منوی اصلی") -
#    handled before BUTTON_COMMANDS / slash-command dispatch
# ---------------------------------------------------------
old = """    contact = message.get("contact")
    text = (message.get("text") or "").strip()

    if text in BUTTON_COMMANDS:
        text = BUTTON_COMMANDS[text]

    # شماره موبایل"""

new = """    contact = message.get("contact")
    text = (message.get("text") or "").strip()

    if text == "🔙 بازگشت":
        await handle_nav(chat_id, "back")
        return {"ok": True}

    if text == "🏠 منوی اصلی":
        await handle_nav(chat_id, "home")
        return {"ok": True}

    if text in BUTTON_COMMANDS:
        text = BUTTON_COMMANDS[text]

    # شماره موبایل"""

assert content.count(old) == 1, "step 1 anchor not found or not unique"
content = content.replace(old, new)

# ---------------------------------------------------------
# 2. send_order_date_menu -> reply (bottom) keyboard instead of inline
# ---------------------------------------------------------
old = """    date_row = []
    if today_ok:
        date_row.append({"text": "1\uFE0F\u20E3 \u0627\u0645\u0631\u0648\u0632", "callback_data": "order_date:1"})
    if tomorrow_ok:
        date_row.append({"text": "2\uFE0F\u20E3 \u0641\u0631\u062F\u0627", "callback_data": "order_date:2"})

    if not date_row:
        message += "\u26D4 \u062F\u0631 \u062D\u0627\u0644 \u062D\u0627\u0636\u0631 \u0645\u0647\u0644\u062A \u062B\u0628\u062A \u0633\u0641\u0627\u0631\u0634 \u0628\u0631\u0627\u06CC \u0627\u0645\u0631\u0648\u0632 \u0648 \u0641\u0631\u062F\u0627 \u0628\u0647 \u067E\u0627\u06CC\u0627\u0646 \u0631\u0633\u06CC\u062F\u0647 \u0627\u0633\u062A."
        keyboard = with_nav_row([], back=False)
        await send_message(chat_id, message, reply_markup=keyboard)
        return

    message += "\u0628\u0631\u0627\u06CC \u0686\u0647 \u0631\u0648\u0632\u06CC \u0645\u06CC\u200C\u062E\u0648\u0627\u0647\u06CC\u062F \u0633\u0641\u0627\u0631\u0634 \u062B\u0628\u062A \u06A9\u0646\u06CC\u062F\u061F"

    keyboard = with_nav_row(
        [date_row],
        back=False,
    )

    await send_message(chat_id, message, reply_markup=keyboard)"""

new = """    date_labels = []
    if today_ok:
        date_labels.append("1\uFE0F\u20E3 \u0627\u0645\u0631\u0648\u0632")
    if tomorrow_ok:
        date_labels.append("2\uFE0F\u20E3 \u0641\u0631\u062F\u0627")

    if not date_labels:
        message += "\u26D4 \u062F\u0631 \u062D\u0627\u0644 \u062D\u0627\u0636\u0631 \u0645\u0647\u0644\u062A \u062B\u0628\u062A \u0633\u0641\u0627\u0631\u0634 \u0628\u0631\u0627\u06CC \u0627\u0645\u0631\u0648\u0632 \u0648 \u0641\u0631\u062F\u0627 \u0628\u0647 \u067E\u0627\u06CC\u0627\u0646 \u0631\u0633\u06CC\u062F\u0647 \u0627\u0633\u062A."
        keyboard = {
            "keyboard": [["\U0001F3E0 \u0645\u0646\u0648\u06CC \u0627\u0635\u0644\u06CC"]],
            "resize_keyboard": True,
            "one_time_keyboard": False,
        }
        await send_message(chat_id, message, reply_markup=keyboard)
        return

    message += "\u0628\u0631\u0627\u06CC \u0686\u0647 \u0631\u0648\u0632\u06CC \u0645\u06CC\u200C\u062E\u0648\u0627\u0647\u06CC\u062F \u0633\u0641\u0627\u0631\u0634 \u062B\u0628\u062A \u06A9\u0646\u06CC\u062F\u061F"

    keyboard = {
        "keyboard": [date_labels, ["\U0001F3E0 \u0645\u0646\u0648\u06CC \u0627\u0635\u0644\u06CC"]],
        "resize_keyboard": True,
        "one_time_keyboard": False,
    }

    await send_message(chat_id, message, reply_markup=keyboard)"""

assert content.count(old) == 1, "step 2 anchor not found or not unique"
content = content.replace(old, new)

# ---------------------------------------------------------
# 3. handle_order_date_choice -> accept the emoji-labeled reply-button
#    text ("1️⃣ امروز" / "2️⃣ فردا") in addition to bare "1"/"2"
# ---------------------------------------------------------
old = """    choice_text = text.strip()

    if choice_text not in {"1", "2"}:
        await send_message(
            chat_id,
            "\u0644\u0637\u0641\u0627\u064B \u0641\u0642\u0637 1 \u06CC\u0627 2 \u0631\u0627 \u0627\u0631\u0633\u0627\u0644 \u06A9\u0646\u06CC\u062F.\\n\\n"
            "1\uFE0F\u20E3 \u0627\u0645\u0631\u0648\u0632\\n"
            "2\uFE0F\u20E3 \u0641\u0631\u062F\u0627","""

new = """    choice_text = text.strip()

    if "\u0627\u0645\u0631\u0648\u0632" in choice_text:
        choice_text = "1"
    elif "\u0641\u0631\u062F\u0627" in choice_text:
        choice_text = "2"

    if choice_text not in {"1", "2"}:
        await send_message(
            chat_id,
            "\u0644\u0637\u0641\u0627\u064B \u0641\u0642\u0637 1 \u06CC\u0627 2 \u0631\u0627 \u0627\u0631\u0633\u0627\u0644 \u06A9\u0646\u06CC\u062F.\\n\\n"
            "1\uFE0F\u20E3 \u0627\u0645\u0631\u0648\u0632\\n"
            "2\uFE0F\u20E3 \u0641\u0631\u062F\u0627","""

assert content.count(old) == 1, "step 3 anchor not found or not unique"
content = content.replace(old, new)

if content == open(path, "r", encoding="utf-8").read():
    print("NOTHING CHANGED")
else:
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print("Patched successfully.")
