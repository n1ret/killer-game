import logging
import sqlite3
from os import getenv
from random import shuffle

import telebot
from dotenv import load_dotenv
from telebot import BaseMiddleware, ExceptionHandler, types
from telebot.apihelper import ApiTelegramException

load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(levelname)-8s[%(asctime)s] %(message)s')
logger = logging.getLogger(__name__)


class LoggerExceptionHandler(ExceptionHandler):
    def handle(self, exception):
        logger.exception(exception)


class CallbackMiddleware(BaseMiddleware):
    def __init__(self):
        super().__init__()

        self.update_types = ['callback_query']

    def pre_process(self, call: types.CallbackQuery, data):
        call.data = call.data.split(":")

    def post_process(self, call: types.CallbackQuery, data, exception):
        try:
            bot.answer_callback_query(call.id)
        except Exception:
            pass


bot = telebot.TeleBot(getenv("TOKEN"), "html",
                      use_class_middlewares=True,
                      exception_handler=LoggerExceptionHandler())
bot.setup_middleware(CallbackMiddleware())


class CallbackFilter:
    def __init__(self, filter, len=-1):
        """Filter for callback queries

        Args:
            filter (str): first part of callback query
            len (int, optional): maximum number (including) of query parts. Defaults doesnt matter
        """
        self.filter = filter
        self.len = len

    def __call__(self, call: types.CallbackQuery):
        if self.len != -1 and len(call.data) > self.len:
            return False

        return call.data[0].lower() == self.filter


def conn_db() -> sqlite3.Connection:
    return sqlite3.connect("data.db")


@bot.message_handler(commands=["start"])
def start(message: types.Message):
    with conn_db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO users (id) VALUES (?)",
            (message.from_user.id,)
        )
        conn.commit()

    bot.send_message(
        message.chat.id,
        "<i>Бот \"киллер\"</i>\n"
        "Напиши свое ФИО"
    )


@bot.message_handler(commands=["admin"])
def admin(message: types.Message):
    if str(message.from_user.id) != getenv("ADMIN"):
        return
    
    spl = message.text.split()
    if len(spl) != 3 or spl[1] not in {"add", "remove"}:
        bot.send_message(
            message.chat.id,
            "Аргументы комманды:\n"
            "&lt;add|remove&gt; [user_id]"
        )
        return
    _, operation, target_id = spl

    with conn_db() as conn:
        cur = conn.cursor()
        target_user = cur.execute(
            "SELECT is_admin FROM users WHERE id = ?",
            (target_id,)
        ).fetchone()
    
        if target_user is None:
            bot.send_message(
                message.chat.id,
                "Пользователь с таким <b>ID не найден</b> в базе"
            )
            return
        is_target_user_admin, = target_user

        if operation == "add" and not is_target_user_admin:
            conn.execute(
                "UPDATE users SET is_admin = true WHERE id = ?",
                (target_id,)
            )
        elif operation == "remove" and is_target_user_admin:
            conn.execute(
                "UPDATE users SET is_admin = false WHERE id = ?",
                (target_id,)
            )
        else:
            bot.send_message(message.chat.id, "Значение не изменилось")
            return

        conn.commit()
    bot.send_message(message.chat.id, "Пользователь успешно изменён")


@bot.message_handler(commands=["disclaimer"])
def disclaimer(message: types.Message):
    bot.send_message(
        message.chat.id,
        "<b>Дисклеймер</b>\n\n"
        "Бот никак не связан с реальным миром.\n"
        "Название было выдвинуто заказчиком.\n"
        "Автор кода бота не несёт ответственности за действия участников"
    )


@bot.message_handler(commands=["cancel"])
def cancel(message: types.Message):
    with conn_db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO users (id) VALUES (?)",
            (message.from_user.id,)
        )

        cur = conn.cursor()
        target, = cur.execute("SELECT target FROM users WHERE id = ?",
                              (message.from_user.id,)).fetchone()
        if target is not None:
            rpl = types.InlineKeyboardMarkup()
            rpl.row(types.InlineKeyboardButton(
                "❌ Выйти", callback_data="confirm"
            ))

            bot.send_message(
                message.chat.id,
                "❌ Игра уже идёт, вы уверены что хотите <b>отменить участие</b>?",
                reply_markup=rpl
            )
            return
        conn.execute(
            "UPDATE users SET name = null WHERE id = ?",
            (message.from_user.id,)
        )
        conn.commit()

    bot.send_message(
        message.chat.id,
        "😢 Ты больше <b>не участвуешь</b> в игре"
    )


@bot.message_handler(commands=["menu", "stats", "status"])
def killer_menu(message: types.Message):
    with conn_db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO users (id) VALUES (?)",
            (message.from_user.id,)
        )
        conn.commit()

        cur = conn.cursor()
        killer_name, target_name = cur.execute(
            "SELECT killers.name, targets.name FROM users as killers "
            "LEFT JOIN users as targets "
            "ON killers.target = targets.id "
            "WHERE killers.id = ?",
            (message.from_user.id,)
        ).fetchone()

        players_count = cur.execute(
            "SELECT COUNT(*) FROM users WHERE name is not null"
        ).fetchone()[0]

    rpl = types.InlineKeyboardMarkup()
    if killer_name is None:
        text = "Ты <b>не участвуешь</b>\nНапиши ФИО для принятия участия в игре"
    else:
        text = (
            f"Ты <b>участвуешь</b>. Всего игроков зарегистрировано: <i>{players_count}</i>\n"
            f"👤 <b>Твоё имя</b>: {killer_name}\n"
            "🎯 <b>Цель</b>: " +
            (f"<tg-spoiler>{target_name}</tg-spoiler>"
             if target_name is not None else
             "Не выбрана")
        )
        if target_name is not None:
            rpl.row(types.InlineKeyboardButton("🔪 Цель убита", callback_data="kill"))

    bot.send_message(
        message.chat.id,
        text,
        reply_markup=rpl
    )


@bot.callback_query_handler(CallbackFilter("kill", 1))
def kill(call: types.CallbackQuery):
    with conn_db() as conn:
        cur = conn.cursor()
        row = cur.execute(
            "SELECT targets.id, killers.is_kill_requested FROM users as killers "
            "LEFT JOIN users as targets "
            "ON killers.target = targets.id "
            "WHERE killers.id = ?",
            (call.from_user.id,)
        ).fetchone()
        if row is None:
            return
        target_id, is_kill_requested = row
        if target_id is None:
            bot.answer_callback_query(call.id, "Сообщение устарело", True)
            return
    
        if not is_kill_requested:
            conn.execute("UPDATE users SET is_kill_requested = true WHERE id = ?",
                         (call.from_user.id,))
            
            rpl = types.InlineKeyboardMarkup()
            rpl.row(
                types.InlineKeyboardButton("Да", callback_data="confirm"),
                types.InlineKeyboardButton("Нет", callback_data="deny")
            )

            bot.send_message(
                target_id,
                "🔪 Тебя <b>убили</b>?",
                reply_markup=rpl
            )

            conn.commit()

    bot.edit_message_text(
        "🕑 Ожидайте подтверждения",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=types.InlineKeyboardMarkup()
    )


@bot.callback_query_handler(CallbackFilter("confirm", 1))
def confirm(call: types.CallbackQuery):
    with conn_db() as conn:
        cur = conn.cursor()
        row = cur.execute(
            "SELECT killers.id, killers.name, targets.target FROM users as targets "
            "JOIN users as killers "
            "ON targets.id = killers.target "
            "WHERE targets.id = ?",
            (call.from_user.id,)
        ).fetchone()
        if row is None:
            bot.answer_callback_query(call.id, "Сообщение устарело", True)
            return
        killer_id, killer_name, target_target = row
        new_target_name = cur.execute("SELECT name FROM users WHERE id = ?",
                                      (target_target,)).fetchone()

        conn.execute("UPDATE users SET "
                     "is_kill_requested = false, target = ?, kills = kills+1 "
                     "WHERE id = ?",
                     (target_target, killer_id))
        conn.execute("UPDATE users SET target = null WHERE id = ?",
                     (call.from_user.id,))

        if target_target == killer_id:
            conn.execute("UPDATE users SET "
                         "target = 0 "
                         "WHERE id = ?",
                         (killer_id,))

        conn.commit()
    
    if target_target == killer_id:
        for tgid, in cur.execute("SELECT id FROM users").fetchall():
            try:
                bot.send_message(
                    tgid,
                    f"🎉 <i>Игра окончена</i>\nПобедитель: <b>{killer_name}</b>"
                )
            except ApiTelegramException:
                pass
        return

    bot.send_message(
        killer_id,
        "✅ Подтверждено\n"
        f"🎯 Твоя <b>следующая цель</b>: {new_target_name}"
    )
    bot.edit_message_text(
        "🎯 Ваша <b>цель передана</b>\n"
        f"{killer_name}",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=types.InlineKeyboardMarkup()
    )


@bot.callback_query_handler(CallbackFilter("deny", 1))
def deny(call: types.CallbackQuery):
    with conn_db() as conn:
        cur = conn.cursor()
        row = cur.execute(
            "SELECT killers.id FROM users as targets "
            "JOIN users as killers "
            "ON targets.id = killers.target "
            "WHERE targets.id = ?",
            (call.from_user.id,)
        ).fetchone()
        if row is None:
            bot.answer_callback_query(call.id, "Сообщение устарело", True)
            return
        killer_id, = row

        conn.execute("UPDATE users SET "
                     "is_kill_requested = false "
                     "WHERE id = ?",
                     (killer_id,))
        conn.commit()

    bot.send_message(
        killer_id,
        "❌ <b>Не подтверждено</b>"
    )
    bot.edit_message_text(
        "✅ <b>Отклонено</b>",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=types.InlineKeyboardMarkup()
    )


@bot.message_handler(commands=["clear_lb"])
def clear_leaderboard(message: types.Message):
    with conn_db() as conn:
        cur = conn.cursor()
        if cur.execute("SELECT 1 FROM users WHERE is_admin = true AND id = ?",
                       (message.from_user.id,)).fetchone() is None:
            bot.send_message(
                message.chat.id,
                "Доступ запрещён"
            )
            return

    rpl = types.InlineKeyboardMarkup()
    rpl.row(types.InlineKeyboardButton(
        "🔴 Подтверждаю", callback_data="clear_lb"
    ))

    bot.send_message(
        message.chat.id,
        "⚠️ Вы действительно хотите отчистить игру?",
        reply_markup=rpl
    )


@bot.callback_query_handler(CallbackFilter("clear_lb", 1))
def clear_lb_accept(call: types.CallbackQuery):
    with conn_db() as conn:
        cur = conn.cursor()
        if cur.execute("SELECT 1 FROM users WHERE is_admin = true AND id = ?",
                       (call.from_user.id,)).fetchone() is None:
            bot.answer_callback_query(
                call.id,
                "Доступ запрещён",
                True
            )
            return

        conn.execute("UPDATE users SET kills = 0, target = null")
        conn.commit()

    bot.edit_message_text(
        "✅ Таблица очищена",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=types.InlineKeyboardMarkup()
    )


@bot.message_handler(commands=["distribute"])
def distribute(message: types.Message):
    with conn_db() as conn:
        cur = conn.cursor()
        if cur.execute("SELECT 1 FROM users WHERE is_admin = true AND id = ?",
                       (message.from_user.id,)).fetchone() is None:
            bot.send_message(
                message.chat.id,
                "Доступ запрещён"
            )
            return

        users = {
            tgid: name
            for tgid, name in cur.execute(
                "SELECT id, name FROM users WHERE name is not null AND target is null"
            ).fetchall()
        }

    if len(users) <= 1:
        bot.send_message(
            message.chat.id,
            "😢 Слишком <b>мало игроков</b>"
        )
        return

    for_disribution = list(users.keys())
    shuffle(for_disribution)
    targets = {}
    for i in range(len(for_disribution)):
        targets[for_disribution[i]] = for_disribution[i+1 if i+1 < len(for_disribution) else 0]

    with conn_db() as conn:
        conn.executemany(
            "UPDATE users SET target = ? WHERE id = ?",
            map(lambda v: tuple(reversed(v)), targets.items())
        )
        conn.commit()

    for killer, target in targets.items():
        try:
            bot.send_message(
                killer,
                "🎯 Вам назначена <b>цель</b>:\n"
                f"<i>{users[target]}</i>"
            )
        except ApiTelegramException:
            pass

    bot.send_message(message.chat.id,
                     "✅ Цели распределены")


@bot.message_handler(commands=["leaderboard"])
def leaderboard(message: types.Message):
    text = "🗒️ Таблица <b>лидеров</b>:\n<i>Статус Имя: Киллов</i>\n"
    with conn_db() as conn:
        cur = conn.cursor()
        for name, kills, target_id in cur.execute(
            "SELECT name, kills, target FROM users WHERE name is not null ORDER BY kills DESC"
        ).fetchall():
            text += ('🟢' if target_id is not None else '🔴')+ f"{name}: {kills}\n"
    bot.send_message(
        message.chat.id,
        text
    )


@bot.message_handler(content_types=["text"])
def text_message(message: types.Message):
    if message.text[0] == '/':
        return

    with conn_db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO users (id) VALUES (?)",
            (message.from_user.id,)
        )
        conn.execute(
            "UPDATE users SET name = ? WHERE id = ?",
            (message.text, message.from_user.id)
        )
        conn.commit()

    bot.send_message(
        message.chat.id,
        "🎉 Теперь ты <b>участвуешь</b> в игре\n"
        "✏️ Твоим именем выбрано:\n"
        f"{message.text}\n\n"
        "Для отмены участия отправь <code>/cancel</code>"
    )


if __name__ == "__main__":
    with conn_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                name TEXT,
                target INTEGER REFERENCES users(id) ON DELETE CASCADE,
                kills INTEGER DEFAULT 0,
                is_kill_requested BOOL DEFAULT false,
                is_admin BOOl DEFAULT false
            )
        """)
        conn.commit()

    bot.polling(none_stop=True)
