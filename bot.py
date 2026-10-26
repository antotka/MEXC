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
