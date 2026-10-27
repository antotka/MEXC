import asyncio
import hashlib
import hmac
import html
import json
import os
import re
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qsl
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    MenuButtonWebApp,
    Message,
    WebAppInfo,
)
from aiohttp import web

BOT_TOKEN = os.environ["BOT_TOKEN"]
WEBAPP_URL = os.environ["WEBAPP_URL"].rstrip("/")            # публичный https-адрес сервиса (Render)
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0") or 0)         # ваш Telegram id: сюда приходят метрики
TZ = ZoneInfo(os.environ.get("TIMEZONE", "Europe/Moscow"))   # часовой пояс для времени в метриках
PORT = int(os.environ.get("PORT", "8080"))

HTML = (Path(__file__).parent / "index.html").read_text(encoding="utf-8")

# Сообщения для человека: части разделяются строкой --- и уходят в чат отдельными сообщениями.
# Фото и видео: строка вида [photo:FILE_ID] подпись  или  [video:FILE_ID] подпись
_offer = (Path(__file__).parent / "offer_message.txt").read_text(encoding="utf-8")
OFFER_PARTS = [p.strip() for p in re.split(r"^\s*---\s*$", _offer, flags=re.M) if p.strip()]
MEDIA_RE = re.compile(r"^\[(photo|video):([^\]\s]+)\]\s*(.*)$", re.S)
_last_sent: dict[int, float] = {}

# ---------- метрики ----------
EVENT_TITLES = {
    "start": "🚀 Запустил бота",
    "open": "📱 Открыл калькулятор",
    "calc": "🧮 Считал бонус",
    "guide": "📩 Получил связку",
    "mgr": "💬 Нажал «Написать менеджеру»",
}
STATS: dict[str, int] = defaultdict(int)           # счётчики хранятся в памяти и обнуляются при перезапуске
UNIQ: dict[str, set] = defaultdict(set)
_ev_times: dict[int, list] = defaultdict(list)
TEXTS = {
    "ru": {
        "start": "Калькулятор бонуса за пополнение на MEXC.\n\n"
                 "Как работает связка:\n"
                 "1. Регистрируетесь на бирже по моей реферальной ссылке.\n"
                 "2. Пополняете счёт от $10 и переводите средства с Bithumb на MEXC.\n"
                 "3. MEXC начисляет бонус по акции: чем больше сумма, тем выше процент (примерно от 3% до 9,8%).\n"
                 "4. Можно повторить до 5 прокруток на одну биржу, вознаграждение не больше $2 000.\n\n"
                 "Стать рефералом можно, если вы не зарегистрированы, не вводили реферальный код или вводили его не позднее 1 года назад.\n\n"
                 "Нажмите «Открыть калькулятор» и подвигайте ползунок. Вопросы: в личные сообщения менеджера или в описании бота.",
        "btn": "Открыть калькулятор",
    },
    "ko": {
        "start": "MEXC 입금 보너스 계산기입니다.\n\n"
                 "연결 방식:\n"
                 "1. 제 추천 링크로 거래소에 가입합니다.\n"
                 "2. $10 이상 입금하고 Bithumb에서 MEXC로 이체합니다.\n"
                 "3. MEXC가 이벤트에 따라 보너스를 지급합니다. 금액이 클수록 보너스율이 높습니다(약 3%~9.8%).\n"
                 "4. 거래소당 최대 5회 반복 가능, 보상은 최대 $2,000입니다.\n\n"
                 "아직 가입하지 않았거나, 추천 코드를 입력하지 않았거나, 입력한 지 1년이 지나지 않았다면 추천인이 될 수 있습니다.\n\n"
                 "\"계산기 열기\"를 눌러 슬라이더를 움직여 보세요. 문의: 매니저에게 개인 메시지 또는 봇 설명 확인.",
        "btn": "계산기 열기",
    },
    "en": {
        "start": "MEXC deposit bonus calculator.\n\n"
                 "How it works:\n"
                 "1. Register on the exchange through my referral link.\n"
                 "2. Deposit from $10 and transfer funds from Bithumb to MEXC.\n"
                 "3. MEXC credits a promo bonus: the larger the amount, the higher the rate (roughly 3% to 9.8%).\n"
                 "4. Up to 5 rounds per exchange, reward capped at $2,000.\n\n"
                 "You can become my referral if you are not registered, never entered a referral code, or entered one no more than 1 year ago.\n\n"
                 "Tap \"Open calculator\" and move the slider. Questions: message the manager or see the bot description.",
        "btn": "Open calculator",
    },
}


def pick_lang(code: str | None) -> str:
    code = (code or "en")[:2]
    if code in ("ru", "uk", "be", "kk"):
        return "ru"
    return code if code in TEXTS else "en"


def user_dict(u) -> dict:
    return {
        "id": u.id,
        "first_name": u.first_name,
        "last_name": u.last_name,
        "username": u.username,
        "language_code": u.language_code,
    }


def who(user: dict) -> str:
    name = " ".join(filter(None, [user.get("first_name"), user.get("last_name")])) or "без имени"
    text = f'<a href="tg://user?id={user["id"]}">{html.escape(name)}</a>'
    if user.get("username"):
        text += f' @{html.escape(user["username"])}'
    return f'{text} · id <code>{user["id"]}</code> · {html.escape(user.get("language_code") or "?")}'


async def track(bot: Bot, user: dict, event: str, detail: str = ""):
    """Считает событие и присылает его вам в личные сообщения от бота."""
    STATS[event] += 1
    UNIQ[event].add(user["id"])
    if not ADMIN_ID:
        return
    now = datetime.now(TZ).strftime("%d.%m %H:%M:%S")
    line = EVENT_TITLES[event] + (f" — {html.escape(detail)}" if detail else "")
    try:
        await bot.send_message(ADMIN_ID, f"{line}\n{who(user)}\n🕒 {now}", parse_mode="HTML")
    except Exception as e:
        print("notify admin failed:", e)


dp = Dispatcher()


@dp.message(CommandStart())
async def start(message: Message, command: CommandObject, bot: Bot):
    if not message.from_user:
        return
    t = TEXTS[pick_lang(message.from_user.language_code)]
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=t["btn"], web_app=WebAppInfo(url=WEBAPP_URL))]]
    )
    await message.answer(t["start"], reply_markup=kb)
    await track(bot, user_dict(message.from_user), "start", command.args or "")


@dp.message(Command("id"))
async def my_id(message: Message):
    if message.from_user:
        await message.answer(f"Ваш Telegram id: {message.from_user.id}")


@dp.message(Command("stats"))
async def stats(message: Message):
    if not message.from_user or message.from_user.id != ADMIN_ID:
        return
    lines = ["📊 Статистика с последнего перезапуска бота:"]
    for key, title in EVENT_TITLES.items():
        lines.append(f"{title}: {STATS[key]} (уникальных: {len(UNIQ[key])})")
    await message.answer("\n".join(lines))


@dp.message(F.photo | F.video)
async def media_file_id(message: Message):
    """Пришлите боту фото или видео: он ответит строкой для offer_message.txt."""
    if not message.from_user:
        return
    if ADMIN_ID and message.from_user.id != ADMIN_ID:
        return
    if message.photo:
        await message.answer(f"[photo:{message.photo[-1].file_id}]")
    elif message.video:
        await message.answer(f"[video:{message.video.file_id}]")


def check_init_data(init_data: str, max_age: int = 86400):
    """Проверяет подпись Telegram Mini App и возвращает данные пользователя или None."""
    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received = pairs.pop("hash", None)
    if not received or "user" not in pairs:
        return None
    check = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    calc = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc, received):
        return None
    if time.time() - int(pairs.get("auth_date", "0")) > max_age:
        return None
    return json.loads(pairs["user"])


async def deliver_offer(bot: Bot, user_id: int):
    for part in OFFER_PARTS:
        m = MEDIA_RE.match(part)
        try:
            if m:
                kind, file_id, caption = m.group(1), m.group(2), m.group(3).strip() or None
                if kind == "photo":
                    await bot.send_photo(user_id, file_id, caption=caption)
                else:
                    await bot.send_video(user_id, file_id, caption=caption)
            else:
                await bot.send_message(user_id, part)
        except Exception as e:
            print("send failed:", e)
            if not m:        # сбой фото/видео не должен мешать тексту; сбой текста сообщаем человеку
                raise
        await asyncio.sleep(0.4)


async def api_offer(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"ok": False}, status=400)
    user = check_init_data(str(body.get("initData", "")))
    if not user:
        return web.json_response({"ok": False}, status=403)
    uid = user["id"]
    if time.time() - _last_sent.get(uid, 0) < 20:       # защита от повторных нажатий
        return web.json_response({"ok": True})
    _last_sent[uid] = time.time()
    bot: Bot = request.app["bot"]
    try:
        await deliver_offer(bot, uid)
    except Exception as e:
        print("deliver_offer failed:", e)
        return web.json_response({"ok": False}, status=500)
    await track(bot, user, "guide")
    return web.json_response({"ok": True})


async def api_event(request: web.Request) -> web.Response:
    """События из калькулятора: открыл, считал, нажал «менеджер»."""
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"ok": False}, status=400)
    user = check_init_data(str(body.get("initData", "")))
    if not user:
        return web.json_response({"ok": False}, status=403)
    event = body.get("event")
    if event not in ("open", "calc", "mgr"):
        return web.json_response({"ok": False}, status=400)

    now = time.time()                                    # не больше 20 событий в минуту от одного человека
    times = [t for t in _ev_times[user["id"]] if now - t < 60]
    if len(times) >= 20:
        return web.json_response({"ok": True})
    times.append(now)
    _ev_times[user["id"]] = times

    detail = ""
    if event == "calc":
        try:
            data = body.get("data") or {}
            dep = float(data.get("deposit", 0))
            bonus = float(data.get("bonus", 0))
            spins = int(data.get("spins", 1))
            detail = f"${dep:,.0f} × {max(1, min(spins, 5))} прокр. → бонус ${bonus:,.0f}".replace(",", " ")
        except Exception:
            detail = ""
    await track(request.app["bot"], user, event, detail)
    return web.json_response({"ok": True})


async def index(_: web.Request) -> web.Response:
    return web.Response(text=HTML, content_type="text/html", headers={"Cache-Control": "no-store"})


async def health(_: web.Request) -> web.Response:
    return web.Response(text="ok")


async def main():
    bot = Bot(BOT_TOKEN)
    await bot.set_chat_menu_button(
        menu_button=MenuButtonWebApp(text="Bonus", web_app=WebAppInfo(url=WEBAPP_URL))
    )

    app = web.Application()
    app["bot"] = bot
    app.router.add_post("/api/offer", api_offer)
    app.router.add_post("/api/event", api_event)
    app.router.add_get("/", index)
    app.router.add_get("/health", health)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
