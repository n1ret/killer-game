import asyncio
import logging
from os import getenv

from aiogram import Bot, Dispatcher, types
from aiogram.enums import ParseMode
from dotenv import load_dotenv

from callbacks import router as callbacks_router
from messages import router as messages_router
from utils import conn_db

load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(levelname)-8s[%(asctime)s] %(message)s')
logger = logging.getLogger(__name__)

dp = Dispatcher()
dp.include_routers(callbacks_router, messages_router)


@dp.error()
async def error_handler(event: types.ErrorEvent):
    logger.exception(event.exception)


async def main():
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

    bot = Bot(getenv("TOKEN"), parse_mode=ParseMode.HTML)
    await dp.start_polling(bot)


if __name__ == "__main__":    
    asyncio.run(main())
