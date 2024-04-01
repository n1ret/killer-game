import logging
from contextlib import asynccontextmanager
from os import getenv
from typing import TYPE_CHECKING

import uvicorn
from aiogram import Bot, Dispatcher, types
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from dotenv import load_dotenv
from fastapi import FastAPI

from callbacks import router as callbacks_router
from messages import router as messages_router
from utils import conn_db

load_dotenv()

WEBHOOK_PATH = f"/bot/{getenv('TOKEN')}"
WEBHOOK_URL = getenv("URL") + WEBHOOK_PATH
PEM_CERT = getenv("PEM_CERT")

logging.basicConfig(level=logging.INFO, format="%(name)s %(levelname)-8s[%(asctime)s] %(message)s")
logger = logging.getLogger("main")
logger.setLevel(logging.INFO)

dp = Dispatcher()
dp.include_routers(callbacks_router, messages_router)


@dp.error()
async def error_handler(event: types.ErrorEvent):
    logger.exception(event.exception)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if TYPE_CHECKING:
        app.state.bot = Bot()

    webhook_info = await app.state.bot.get_webhook_info()
    if webhook_info.url != WEBHOOK_URL:
        await app.state.bot.set_webhook(
            url=WEBHOOK_URL,
            certificate=types.FSInputFile(PEM_CERT)
        )

    yield

    await app.state.bot.close()


app = FastAPI(lifespan=lifespan)


@app.post(WEBHOOK_PATH)
async def bot_webhook(update: dict):
    telegram_update = types.Update.model_validate(update)
    await dp.feed_update(app.state.bot, telegram_update)


def main():
    with conn_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                name TEXT,
                target INTEGER REFERENCES users(id) ON DELETE CASCADE,
                kills INTEGER DEFAULT 0,
                is_kill_requested BOOL DEFAULT false,
                is_admin BOOL DEFAULT false
            )
        """)
        conn.commit()

    app.state.bot = Bot(
        getenv("TOKEN"),
        default=DefaultBotProperties(
            parse_mode=ParseMode.HTML
        )
    )
    logger.info("Server started")
    uvicorn.run(app, host="127.0.0.1", port=9998, log_level=logging.WARNING)


if __name__ == "__main__":
    main()
