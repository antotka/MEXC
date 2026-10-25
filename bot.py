import asyncio
import os
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    MenuButtonWebApp,
    Message,
    WebAppInfo,
)
from aiohttp import web

BOT_TOKEN = os.environ["BOT_TOKEN"]
WEBAPP_URL = os.environ["WEBAPP_URL"].rstrip("/")      # публичный https-адрес сервиса (Render)
REF_LINK = os.environ.get("REF_LINK", "https://www.mexc.com")  # ваша реферальная ссылка
PROMO_URL = os.environ.get("PROMO_URL", "")            # официальная страница акции
CTA_URL = os.environ.get("CTA_URL", REF_LINK)          # куда ведёт кнопка: t.me/менеджер, t.me/бот?start=... или реф-ссылка
PORT = int(os.environ.get("PORT", "8080"))

HTML = (Path(__file__).parent / "index.html").read_text(encoding="utf-8")
HTML = HTML.replace("__REF_LINK__", REF_LINK).replace("__CTA_URL__", CTA_URL).replace("__PROMO_URL__", PROMO_URL)

TEXTS = {
    "ru": {
        "start": "Калькулятор бонуса за пополнение на MEXC.\n\nДвигайте ползунок и смотрите, как растёт бонус. "
                 "Расчёт ориентировочный, условия акции смотрите на официальной странице.",
        "btn": "Открыть калькулятор",
    },
    "ko": {
        "start": "MEXC 입금 보너스 계산기입니다.\n\n슬라이더를 움직여 보너스를 확인하세요. "
                 "예상 계산이며, 정확한 조건은 공식 이벤트 페이지에서 확인하세요.",
        "btn": "계산기 열기",
    },
    "en": {
        "start": "MEXC deposit bonus calculator.\n\nMove the slider to see how the bonus grows. "
                 "The numbers are estimates; check the official promo page for exact terms.",
        "btn": "Open calculator",
    },
}


def pick_lang(code: str | None) -> str:
    code = (code or "en")[:2]
    if code in ("ru", "uk", "be", "kk"):
        return "ru"
    return code if code in TEXTS else "en"


dp = Dispatcher()


@dp.message(CommandStart())
async def start(message: Message):
    t = TEXTS[pick_lang(message.from_user.language_code if message.from_user else None)]
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=t["btn"], web_app=WebAppInfo(url=WEBAPP_URL))]]
    )
    await message.answer(t["start"], reply_markup=kb)


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
    app.router.add_get("/", index)
    app.router.add_get("/health", health)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
