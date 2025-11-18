import os
import sqlite3
from datetime import datetime
import asyncio
import dateparser

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    MessageHandler,
    filters,
    CommandHandler
)

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.cron import CronTrigger

TOKEN = os.getenv("BOT_TOKEN", "YOUR_TOKEN_HERE")

DB_PATH = "reminders.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            text TEXT,
            time TEXT,
            cron TEXT,
            active INTEGER DEFAULT 1
        )"""
    )
    conn.commit()
    conn.close()

async def send_reminder(context: ContextTypes.DEFAULT_TYPE):
    job_id = context.job.id
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT user_id, text FROM reminders WHERE id=?", (job_id,))
    row = cur.fetchone()
    conn.close()

    if row:
        user_id, text = row
        await context.bot.send_message(chat_id=user_id, text=f"🔔 Reminder: {text}")

async def parse_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message.text.lower()

    dt = dateparser.parse(msg, languages=["en"])
    is_recurring = msg.startswith("every ")

    event_text = msg
    if "remind me to" in msg:
        event_text = msg.split("remind me to")[-1].strip()
    elif "remind me about" in msg:
        event_text = msg.split("remind me about")[-1].strip()

    if dt and not is_recurring:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO reminders (user_id, text, time) VALUES (?, ?, ?)",
            (update.message.chat_id, event_text, dt.isoformat())
        )
        reminder_id = cur.lastrowid
        conn.commit()
        conn.close()

        context.application.job_queue.run_once(
            send_reminder,
            when=(dt - datetime.now()).total_seconds(),
            job_id=str(reminder_id)
        )

        await update.message.reply_text(
            f"✅ I'll remind you to "{event_text}" on {dt}."
        )
        return

    if is_recurring:
        try:
            parts = msg.replace("every", "").strip().split(" ")
            weekday = parts[0]
            time_str = parts[-1]

            hour, minute = map(int, time_str.split(":"))

            days_map = {
                "monday": "0",
                "tuesday": "1",
                "wednesday": "2",
                "thursday": "3",
                "friday": "4",
                "saturday": "5",
                "sunday": "6"
            }

            cron = f"{minute} {hour} * * {days_map[weekday]}"

            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO reminders (user_id, text, cron) VALUES (?, ?, ?)",
                (update.message.chat_id, event_text, cron)
            )
            reminder_id = cur.lastrowid
            conn.commit()
            conn.close()

            context.application.job_queue.run_daily(
                send_reminder,
                time=datetime.strptime(time_str, "%H:%M").time(),
                days=[int(days_map[weekday])],
                job_id=str(reminder_id)
            )

            await update.message.reply_text(
                f"🔄 Recurring reminder set: "{event_text}" every {weekday} at {time_str}."
            )
            return

        except:
            await update.message.reply_text("❌ Could not parse recurring reminder.")
            return

    await update.message.reply_text("❌ I couldn't understand the reminder format.")

async def list_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT id, text, time, cron FROM reminders WHERE user_id=?", (update.message.chat_id,))
    rows = cur.fetchall()
    conn.close()

    if not rows:
        await update.message.reply_text("You have no reminders.")
        return

    msg = "📋 *Your reminders:*

"
    for r in rows:
        rid, text, t, c = r
        if t:
            msg += f"{rid}. {text} — ⏰ {t}
"
        else:
            msg += f"{rid}. {text} — 🔄 {c}
"

    await update.message.reply_text(msg)

async def cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /cancel <id>")
        return

    rid = context.args[0]

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("DELETE FROM reminders WHERE id=?", (rid,))
    conn.commit()
    conn.close()

    try:
        context.application.job_queue.get_jobs_by_tag(rid)[0].schedule_removal()
    except:
        pass

    await update.message.reply_text(f"❌ Reminder {rid} removed.")

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "💡 *Examples:*
"
        ""Remind me to water the plants tomorrow at 9:00"
"
        ""Every Friday at 18:30 remind me to take out the trash"
"
    )

async def main():
    init_db()

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, parse_message))
    app.add_handler(CommandHandler("list", list_cmd))
    app.add_handler(CommandHandler("cancel", cancel_cmd))
    app.add_handler(CommandHandler("help", help_cmd))

    await app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
