import logging
import sqlite3
import asyncio
import os
from datetime import datetime, time
import pytz

from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
)

# ──────────────────────────────────────────────
# НАСТРОЙКИ — замени на свои
# ──────────────────────────────────────────────
BOT_TOKEN = os.environ["BOT_TOKEN"]
MANAGER_CHAT_ID = int(os.environ["MANAGER_CHAT_ID"])
TIMEZONE = "Asia/Yekaterinburg"        # твой часовой пояс

REMINDER_TIME = time(21, 10)           # напоминание в 21:10
SUMMARY_TIME  = time(9, 0)            # сводка в 09:00 следующего дня

# ──────────────────────────────────────────────
# Состояния диалога
# ──────────────────────────────────────────────
CHOOSE_ROLE, ENTER_NAME, Q1, Q2, Q3, Q4 = range(6)

ROLES = ["Бариста", "Администратор", "Управляющий"]

QUESTIONS = [
    "1️⃣ *Общий вайб смены* — как она прошла?",
    "2️⃣ *Что было хорошо сегодня?* Что-то поразило?",
    "3️⃣ *Какие были сложности?* Что не получилось? Были спорные ситуации?",
    "4️⃣ *Что ещё важно знать?* Или что стоит улучшить?",
]

THANK_YOU_MESSAGES = [
    "🔥 Нет слов, ты — супер!",
    "⭐️ Отличный отчёт! Ты молодец!",
    "💪 Вот это я понимаю — профессионал!",
    "🚀 Спасибо! С такими сотрудниками всё получится!",
    "✨ Красавчик! Отчёт принят, ты лучший!",
    "🎯 Точно в цель! Отличная работа сегодня!",
    "💫 Ты просто огонь! Спасибо за отчёт!",
]

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# База данных
# ──────────────────────────────────────────────
def init_db():
    conn = sqlite3.connect("reports.db")
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            username TEXT,
            name TEXT,
            role TEXT,
            q1 TEXT,
            q2 TEXT,
            q3 TEXT,
            q4 TEXT,
            date TEXT,
            sent_to_manager INTEGER DEFAULT 0
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            chat_id INTEGER PRIMARY KEY,
            username TEXT,
            reminded_today INTEGER DEFAULT 0,
            last_reminded TEXT
        )
    """)
    conn.commit()
    conn.close()

def save_report(chat_id, username, name, role, answers):
    conn = sqlite3.connect("reports.db")
    c = conn.cursor()
    today = datetime.now(pytz.timezone(TIMEZONE)).strftime("%Y-%m-%d")
    c.execute("""
        INSERT INTO reports (chat_id, username, name, role, q1, q2, q3, q4, date)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (chat_id, username, name, role, answers[0], answers[1], answers[2], answers[3], today))
    conn.commit()
    conn.close()

def register_user(chat_id, username):
    conn = sqlite3.connect("reports.db")
    c = conn.cursor()
    c.execute("""
        INSERT OR IGNORE INTO users (chat_id, username) VALUES (?, ?)
    """, (chat_id, username or str(chat_id)))
    conn.commit()
    conn.close()

def get_all_users():
    conn = sqlite3.connect("reports.db")
    c = conn.cursor()
    c.execute("SELECT chat_id FROM users")
    users = [row[0] for row in c.fetchall()]
    conn.close()
    return users

def get_unsent_reports():
    conn = sqlite3.connect("reports.db")
    c = conn.cursor()
    yesterday = datetime.now(pytz.timezone(TIMEZONE))
    # Получаем отчёты за вчера (или сегодня если ещё не отправлены)
    c.execute("""
        SELECT name, role, q1, q2, q3, q4, date, username
        FROM reports
        WHERE sent_to_manager = 0
        ORDER BY date DESC, id ASC
    """)
    rows = c.fetchall()
    conn.close()
    return rows

def mark_reports_sent():
    conn = sqlite3.connect("reports.db")
    c = conn.cursor()
    c.execute("UPDATE reports SET sent_to_manager = 1 WHERE sent_to_manager = 0")
    conn.commit()
    conn.close()

# ──────────────────────────────────────────────
# Хэндлеры диалога
# ──────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    register_user(user.id, user.username)

    keyboard = [[role] for role in ROLES]
    await update.message.reply_text(
        f"👋 Привет! Время заполнить отчёт о рабочем дне.\n\n*Выбери свою должность:*",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True),
    )
    return CHOOSE_ROLE

async def choose_role(update: Update, context: ContextTypes.DEFAULT_TYPE):
    role = update.message.text
    if role not in ROLES:
        await update.message.reply_text("Пожалуйста, выбери должность из списка 👇")
        return CHOOSE_ROLE

    context.user_data["role"] = role
    await update.message.reply_text(
        "✍️ *Напиши своё имя и фамилию:*",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove(),
    )
    return ENTER_NAME

async def enter_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["name"] = update.message.text.strip()
    context.user_data["answers"] = []

    await update.message.reply_text(
        f"Отлично, *{context.user_data['name']}*! 🙌\n\nОтвечай на вопросы по очереди:\n\n{QUESTIONS[0]}",
        parse_mode="Markdown",
    )
    return Q1

async def answer_q1(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["answers"].append(update.message.text)
    await update.message.reply_text(QUESTIONS[1], parse_mode="Markdown")
    return Q2

async def answer_q2(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["answers"].append(update.message.text)
    await update.message.reply_text(QUESTIONS[2], parse_mode="Markdown")
    return Q3

async def answer_q3(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["answers"].append(update.message.text)
    await update.message.reply_text(QUESTIONS[3], parse_mode="Markdown")
    return Q4

async def answer_q4(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["answers"].append(update.message.text)

    user = update.effective_user
    name = context.user_data["name"]
    role = context.user_data["role"]
    answers = context.user_data["answers"]

    save_report(user.id, user.username, name, role, answers)

    # Случайная благодарность
    import random
    thanks = random.choice(THANK_YOU_MESSAGES)

    await update.message.reply_text(
        f"{thanks}\n\nОтчёт сохранён. Хорошего вечера! 🌙",
        reply_markup=ReplyKeyboardRemove(),
    )
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Отчёт отменён. Напиши /start чтобы начать заново.")
    return ConversationHandler.END

async def myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Твой chat_id: `{update.effective_user.id}`", parse_mode="Markdown")

# ──────────────────────────────────────────────
# Напоминание в 21:10
# ──────────────────────────────────────────────
async def send_reminders(context: ContextTypes.DEFAULT_TYPE):
    users = get_all_users()
    for chat_id in users:
        if chat_id == MANAGER_CHAT_ID:
            continue
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text="⏰ Жду твой отчёт о рабочем дне!\n\nНапиши /start чтобы заполнить 📋",
            )
        except Exception as e:
            logger.warning(f"Не удалось отправить напоминание {chat_id}: {e}")

# ──────────────────────────────────────────────
# Сводка в 09:00
# ──────────────────────────────────────────────
async def send_summary(context: ContextTypes.DEFAULT_TYPE):
    reports = get_unsent_reports()

    if not reports:
        await context.bot.send_message(
            chat_id=MANAGER_CHAT_ID,
            text="📊 *Сводка за вчера*\n\nОтчётов не поступало 😶",
            parse_mode="Markdown",
        )
        return

    text = "📊 *Сводка отчётов сотрудников*\n"
    text += f"_Дата: {datetime.now(pytz.timezone(TIMEZONE)).strftime('%d.%m.%Y')}_\n"
    text += "━" * 30 + "\n\n"

    for name, role, q1, q2, q3, q4, date, username in reports:
        tg = f"@{username}" if username else ""
        text += f"👤 *{name}* ({role}) {tg}\n"
        text += f"📅 _{date}_\n\n"
        text += f"💬 *Вайб смены:*\n{q1}\n\n"
        text += f"✅ *Что было хорошо:*\n{q2}\n\n"
        text += f"⚠️ *Сложности:*\n{q3}\n\n"
        text += f"💡 *Важное / улучшения:*\n{q4}\n\n"
        text += "─" * 25 + "\n\n"

    # Telegram лимит 4096 символов — разбиваем если нужно
    if len(text) <= 4096:
        await context.bot.send_message(
            chat_id=MANAGER_CHAT_ID,
            text=text,
            parse_mode="Markdown",
        )
    else:
        # Отправляем частями
        chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
        for chunk in chunks:
            await context.bot.send_message(
                chat_id=MANAGER_CHAT_ID,
                text=chunk,
                parse_mode="Markdown",
            )

    mark_reports_sent()

# ──────────────────────────────────────────────
# Запуск
# ──────────────────────────────────────────────
def main():
    init_db()

    app = Application.builder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            CHOOSE_ROLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, choose_role)],
            ENTER_NAME:  [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_name)],
            Q1: [MessageHandler(filters.TEXT & ~filters.COMMAND, answer_q1)],
            Q2: [MessageHandler(filters.TEXT & ~filters.COMMAND, answer_q2)],
            Q3: [MessageHandler(filters.TEXT & ~filters.COMMAND, answer_q3)],
            Q4: [MessageHandler(filters.TEXT & ~filters.COMMAND, answer_q4)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("myid", myid))

    tz = pytz.timezone(TIMEZONE)

    # Напоминание в 21:10
    app.job_queue.run_daily(
        send_reminders,
        time=REMINDER_TIME,
        timezone=tz,
        name="daily_reminder",
    )

    # Сводка в 09:00
    app.job_queue.run_daily(
        send_summary,
        time=SUMMARY_TIME,
        timezone=tz,
        name="daily_summary",
    )

    logger.info("Бот запущен!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
