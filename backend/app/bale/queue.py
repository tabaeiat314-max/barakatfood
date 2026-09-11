import asyncio

from app.bale.client import send_message

_queue: asyncio.Queue = asyncio.Queue()
_worker_task = None


async def _worker():
    while True:
        chat_id, text, reply_markup = await _queue.get()
        try:
            await send_message(chat_id, text, reply_markup=reply_markup)
        except Exception as e:
            print(f"[bulk-queue] خطا در ارسال به {chat_id}: {e}", flush=True)
        finally:
            _queue.task_done()
        await asyncio.sleep(0.15)


def start_worker():
    global _worker_task
    if _worker_task is None:
        _worker_task = asyncio.create_task(_worker())


async def enqueue_message(chat_id: str, text: str, reply_markup: dict | None = None):
    await _queue.put((chat_id, text, reply_markup))


def queue_size() -> int:
    return _queue.qsize()
