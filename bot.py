"""
bot.py — TeraBox Video Downloader Bot (with owner approval system)
=========================================================
Flow for new users:
  1. User sends /start → bot asks them to request access
  2. Bot forwards request card to OWNER with [✅ Approve] [❌ Ban] buttons
  3. Owner taps a button → user is notified instantly
  4. Approved users can use the bot normally
  5. Owner can /listusers, /ban <id>, /unban <id>, /revoke <id> anytime
"""

import asyncio
import logging
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

from telegram import (
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from config import Config
from downloader import TeraboxDownloader
from queue_manager import DownloadQueue
from user_db import UserDB
from utils import (
    bytes_to_human,
    cleanup_file,
    format_duration,
    is_terabox_url,
    safe_edit_message,
)

# ── Logging ────────────────────────────────────────────────────────────────────
Path("logs").mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler("logs/activity.log"),
        logging.FileHandler("logs/error.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
logging.getLogger().handlers[1].setLevel(logging.ERROR)
logger = logging.getLogger("TeraBot")

# ── Rate limiter ───────────────────────────────────────────────────────────────
rate_tracker: dict[int, list[float]] = defaultdict(list)


def is_rate_limited(user_id: int) -> bool:
    now = time.time()
    window_start = now - Config.RATE_LIMIT_WINDOW
    rate_tracker[user_id] = [t for t in rate_tracker[user_id] if t > window_start]
    if len(rate_tracker[user_id]) >= Config.RATE_LIMIT_REQUESTS:
        return True
    rate_tracker[user_id].append(now)
    return False


# ══════════════════════════════════════════════════════════════════════════════
# ACCESS REQUEST SYSTEM
# ══════════════════════════════════════════════════════════════════════════════

def _approval_keyboard(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Approve", callback_data=f"approve|{user_id}"),
        InlineKeyboardButton("❌ Ban",     callback_data=f"ban|{user_id}"),
    ]])


def _user_card(record: dict) -> str:
    import datetime
    uname = f"@{record['username']}" if record.get("username") else "no username"
    ts = datetime.datetime.fromtimestamp(record["requested_at"]).strftime("%Y-%m-%d %H:%M")
    return (
        f"👤 <b>Access Request</b>\n\n"
        f"Name: <b>{record.get('first_name', 'Unknown')}</b>\n"
        f"Username: <code>{uname}</code>\n"
        f"User ID: <code>{record['id']}</code>\n"
        f"Requested at: {ts}"
    )


async def _notify_user(bot, user_id: int, text: str) -> None:
    try:
        await bot.send_message(chat_id=user_id, text=text, parse_mode=ParseMode.HTML)
    except Exception as exc:
        logger.warning("Could not notify user %s: %s", user_id, exc)


# ══════════════════════════════════════════════════════════════════════════════
# /start
# ══════════════════════════════════════════════════════════════════════════════

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    db: UserDB = context.bot_data["db"]

    # Owner bypass
    if user.id == Config.OWNER_ID:
        await update.message.reply_text(
            f"👑 Welcome back, <b>Owner</b>!\n\n"
            f"<b>Owner Commands:</b>\n"
            f"/pending — Review pending requests\n"
            f"/listusers — All users &amp; statuses\n"
            f"/ban &lt;id&gt; — Ban a user\n"
            f"/unban &lt;id&gt; — Unban a user\n"
            f"/revoke &lt;id&gt; — Revoke approval\n\n"
            f"Send a TeraBox link to download videos.",
            parse_mode=ParseMode.HTML,
        )
        return

    status = db.status(user.id)

    if status == "approved":
        await update.message.reply_text(
            f"👋 Welcome back, <b>{user.first_name}</b>!\nSend me a TeraBox link.",
            parse_mode=ParseMode.HTML,
        )
        return

    if status == "banned":
        await update.message.reply_text("⛔ You have been banned from this bot.")
        return

    if status == "pending":
        await update.message.reply_text(
            "⏳ Your request is <b>pending approval</b>. You'll be notified once the owner reviews it.",
            parse_mode=ParseMode.HTML,
        )
        return

    # New user — register and ping owner
    is_new = db.request_access(user.id, user.username, user.first_name)
    await update.message.reply_text(
        f"👋 Hello, <b>{user.first_name}</b>!\n\n"
        f"This bot is <b>invite-only</b>.\n"
        f"✅ Your access request has been sent to the owner.\n"
        f"You'll get a message here once it's approved or declined.",
        parse_mode=ParseMode.HTML,
    )

    if is_new:
        record = db.get(user.id)
        try:
            await context.bot.send_message(
                chat_id=Config.OWNER_ID,
                text=_user_card(record),
                parse_mode=ParseMode.HTML,
                reply_markup=_approval_keyboard(user.id),
            )
            logger.info("Forwarded access request from user %s to owner", user.id)
        except Exception as exc:
            logger.error("Could not ping owner: %s", exc)


# ══════════════════════════════════════════════════════════════════════════════
# Approval / Ban callbacks (owner taps buttons on request card)
# ══════════════════════════════════════════════════════════════════════════════

async def cb_approve(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if update.effective_user.id != Config.OWNER_ID:
        await query.answer("⛔ Only the owner can do this.", show_alert=True)
        return
    await query.answer("✅ Approved!")

    user_id = int(query.data.split("|")[1])
    db: UserDB = context.bot_data["db"]
    record = db.get(user_id)
    db.approve(user_id)

    name = record["first_name"] if record else str(user_id)
    await query.edit_message_text(
        f"✅ <b>{name}</b> (<code>{user_id}</code>) — <b>Approved</b>",
        parse_mode=ParseMode.HTML,
    )
    await _notify_user(
        context.bot, user_id,
        "🎉 <b>Your access has been approved!</b>\n\nSend me a TeraBox link to start downloading.",
    )
    logger.info("Owner approved user %s", user_id)


async def cb_ban_request(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if update.effective_user.id != Config.OWNER_ID:
        await query.answer("⛔ Only the owner can do this.", show_alert=True)
        return
    await query.answer("🚫 Banned.")

    user_id = int(query.data.split("|")[1])
    db: UserDB = context.bot_data["db"]
    record = db.get(user_id)
    db.ban(user_id)

    name = record["first_name"] if record else str(user_id)
    await query.edit_message_text(
        f"🚫 <b>{name}</b> (<code>{user_id}</code>) — <b>Banned</b>",
        parse_mode=ParseMode.HTML,
    )
    await _notify_user(context.bot, user_id, "⛔ Your access request was <b>declined</b>.")
    logger.info("Owner banned user %s", user_id)


# ══════════════════════════════════════════════════════════════════════════════
# Owner management commands
# ══════════════════════════════════════════════════════════════════════════════

def _owner_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id != Config.OWNER_ID:
            await update.message.reply_text("⛔ Owner only.")
            return
        return await func(update, context)
    wrapper.__name__ = func.__name__
    return wrapper


@_owner_only
async def cmd_pending(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db: UserDB = context.bot_data["db"]
    pending = db.all_by_status("pending")
    if not pending:
        await update.message.reply_text("📭 No pending requests.")
        return
    await update.message.reply_text(f"⏳ <b>{len(pending)} pending request(s):</b>", parse_mode=ParseMode.HTML)
    for record in pending:
        await update.message.reply_text(
            _user_card(record), parse_mode=ParseMode.HTML,
            reply_markup=_approval_keyboard(record["id"]),
        )


@_owner_only
async def cmd_listusers(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db: UserDB = context.bot_data["db"]
    all_users = db.all_users()
    if not all_users:
        await update.message.reply_text("📭 No users yet.")
        return

    def _fmt(users):
        if not users:
            return "  None"
        return "\n".join(
            f"  • <code>{u['id']}</code>  {u['first_name']}  "
            f"({'@'+u['username'] if u.get('username') else '—'})"
            for u in users
        )

    approved = [u for u in all_users if u["status"] == "approved"]
    pending  = [u for u in all_users if u["status"] == "pending"]
    banned   = [u for u in all_users if u["status"] == "banned"]

    await update.message.reply_text(
        f"👥 <b>All Users ({len(all_users)})</b>\n\n"
        f"✅ <b>Approved ({len(approved)}):</b>\n{_fmt(approved)}\n\n"
        f"⏳ <b>Pending ({len(pending)}):</b>\n{_fmt(pending)}\n\n"
        f"🚫 <b>Banned ({len(banned)}):</b>\n{_fmt(banned)}",
        parse_mode=ParseMode.HTML,
    )


@_owner_only
async def cmd_ban(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db: UserDB = context.bot_data["db"]
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Usage: /ban <user_id>")
        return
    user_id = int(context.args[0])
    db.ban(user_id)
    await update.message.reply_text(f"🚫 User <code>{user_id}</code> banned.", parse_mode=ParseMode.HTML)
    await _notify_user(context.bot, user_id, "⛔ You have been <b>banned</b> from this bot.")


@_owner_only
async def cmd_unban(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db: UserDB = context.bot_data["db"]
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Usage: /unban <user_id>")
        return
    user_id = int(context.args[0])
    ok = db.unban(user_id)
    if ok:
        await update.message.reply_text(f"✅ User <code>{user_id}</code> unbanned.", parse_mode=ParseMode.HTML)
        await _notify_user(context.bot, user_id, "✅ Your ban was lifted. Send /start to request access again.")
    else:
        await update.message.reply_text("⚠️ User not found or not banned.")


@_owner_only
async def cmd_revoke(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db: UserDB = context.bot_data["db"]
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Usage: /revoke <user_id>")
        return
    user_id = int(context.args[0])
    ok = db.revoke(user_id)
    if ok:
        await update.message.reply_text(f"🔄 Approval revoked for <code>{user_id}</code>.", parse_mode=ParseMode.HTML)
        await _notify_user(context.bot, user_id, "⚠️ Your bot access has been <b>revoked</b> by the owner.")
    else:
        await update.message.reply_text("⚠️ User not found or not currently approved.")


# ══════════════════════════════════════════════════════════════════════════════
# Access guard helper
# ══════════════════════════════════════════════════════════════════════════════

def _check_access(db: UserDB, user_id: int) -> str | None:
    if user_id == Config.OWNER_ID:
        return None
    status = db.status(user_id)
    if status == "approved":
        return None
    if status == "banned":
        return "⛔ You are banned from this bot."
    if status == "pending":
        return "⏳ Your access is pending approval. Please wait."
    return "❌ You don't have access. Send /start to request it."


# ══════════════════════════════════════════════════════════════════════════════
# User commands (approved only)
# ══════════════════════════════════════════════════════════════════════════════

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db: UserDB = context.bot_data["db"]
    err = _check_access(db, update.effective_user.id)
    if err:
        await update.message.reply_text(err)
        return
    await update.message.reply_text(
        "<b>📖 Help</b>\n\n"
        "/start — Welcome\n"
        "/help — This message\n"
        "/queue — Active downloads\n"
        "/cancel — Cancel current download\n\n"
        "Paste any TeraBox link to start!",
        parse_mode=ParseMode.HTML,
    )


async def cmd_queue(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db: UserDB = context.bot_data["db"]
    user_id = update.effective_user.id
    err = _check_access(db, user_id)
    if err:
        await update.message.reply_text(err)
        return
    queue: DownloadQueue = context.bot_data["queue"]
    items = queue.user_queue(user_id)
    if not items:
        await update.message.reply_text("📭 No active downloads.")
        return
    lines = [f"📥 <b>Your queue ({len(items)}):</b>"]
    for i, item in enumerate(items, 1):
        lines.append(f"  {i}. {item['title'][:40]}… [{item['status']}]")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db: UserDB = context.bot_data["db"]
    user_id = update.effective_user.id
    err = _check_access(db, user_id)
    if err:
        await update.message.reply_text(err)
        return
    queue: DownloadQueue = context.bot_data["queue"]
    if queue.cancel_user(user_id):
        await update.message.reply_text("🛑 Download cancelled.")
    else:
        await update.message.reply_text("ℹ️ No active download.")


# ══════════════════════════════════════════════════════════════════════════════
# TeraBox link handler
# ══════════════════════════════════════════════════════════════════════════════

async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    db: UserDB = context.bot_data["db"]

    err = _check_access(db, user.id)
    if err:
        await update.message.reply_text(err)
        return

    if is_rate_limited(user.id):
        await update.message.reply_text(
            f"⏳ Too fast! Max {Config.RATE_LIMIT_REQUESTS} requests per {Config.RATE_LIMIT_WINDOW}s."
        )
        return

    url = update.message.text.strip()
    if not is_terabox_url(url):
        await update.message.reply_text("❌ Not a TeraBox link. Please send a valid TeraBox URL.")
        return

    status_msg = await update.message.reply_text("🔍 Fetching video info…")
    logger.info("User %s — submitted link: %s", user.id, url)

    downloader: TeraboxDownloader = context.bot_data["downloader"]
    try:
        info = await asyncio.get_event_loop().run_in_executor(None, downloader.fetch_info, url)
    except Exception as exc:
        logger.error("fetch_info error: %s", exc, exc_info=True)
        await safe_edit_message(status_msg, f"❌ Could not fetch video info.\n<code>{exc}</code>")
        return

    context.user_data["pending"] = {"url": url, "info": info}

    formats = info.get("formats", [])
    if not formats:
        await safe_edit_message(status_msg, "❌ No downloadable formats found.")
        return

    # Thumbnail + metadata
    caption = _build_caption(info)
    try:
        thumb = info.get("thumbnail")
        if thumb:
            await update.message.reply_photo(photo=thumb, caption=caption, parse_mode=ParseMode.HTML)
        else:
            await update.message.reply_text(caption, parse_mode=ParseMode.HTML)
    except Exception:
        await update.message.reply_text(caption, parse_mode=ParseMode.HTML)

    await safe_edit_message(
        status_msg, "🎬 <b>Choose video quality:</b>",
        reply_markup=_build_quality_keyboard(formats),
    )


def _build_caption(info: dict) -> str:
    return (
        f"📹 <b>{info.get('title','Unknown')[:60]}</b>\n\n"
        f"⏱ Duration: <code>{format_duration(info.get('duration', 0))}</code>\n"
        f"📦 Size: <code>{bytes_to_human(info.get('filesize_approx') or info.get('filesize') or 0)}</code>\n"
        f"👤 Uploader: <code>{info.get('uploader','Unknown')}</code>"
    )


def _build_quality_keyboard(formats: list) -> InlineKeyboardMarkup:
    seen: set = set()
    buttons = []
    for fmt in reversed(formats):
        label = str(fmt.get("format_note") or fmt.get("height") or "")
        if not label or label in seen:
            continue
        seen.add(label)
        size = fmt.get("filesize") or fmt.get("filesize_approx") or 0
        size_str = f" ({bytes_to_human(size)})" if size else ""
        buttons.append(InlineKeyboardButton(
            f"📺 {label}{size_str}", callback_data=f"quality|{fmt.get('format_id','best')}"
        ))
    buttons += [
        InlineKeyboardButton("⭐ Best", callback_data="quality|best"),
        InlineKeyboardButton("🔹 Smallest", callback_data="quality|worst"),
        InlineKeyboardButton("❌ Cancel", callback_data="quality|cancel"),
    ]
    rows = [buttons[i:i+2] for i in range(0, len(buttons), 2)]
    return InlineKeyboardMarkup(rows)


def _build_subtitle_keyboard(subtitles: dict) -> InlineKeyboardMarkup:
    buttons = [InlineKeyboardButton(f"💬 {lang}", callback_data=f"sub|{lang}") for lang in subtitles]
    buttons += [
        InlineKeyboardButton("🚫 No subtitles", callback_data="sub|none"),
        InlineKeyboardButton("❌ Cancel", callback_data="sub|cancel"),
    ]
    rows = [buttons[i:i+2] for i in range(0, len(buttons), 2)]
    return InlineKeyboardMarkup(rows)


async def cb_quality(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    _, fmt_id = query.data.split("|", 1)

    if fmt_id == "cancel":
        await query.edit_message_text("❌ Cancelled.")
        context.user_data.pop("pending", None)
        return

    pending = context.user_data.get("pending")
    if not pending:
        await query.edit_message_text("⚠️ Session expired. Send the link again.")
        return

    pending["format_id"] = fmt_id
    subtitles = pending["info"].get("subtitles", {})
    if subtitles:
        await query.edit_message_text(
            f"💬 <b>{len(subtitles)} subtitle language(s) available. Choose:</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=_build_subtitle_keyboard(subtitles),
        )
    else:
        pending["subtitle_lang"] = None
        await query.edit_message_text("📥 Queuing download…")
        await _enqueue_download(update, context, query.message)


async def cb_subtitle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    _, lang = query.data.split("|", 1)

    if lang == "cancel":
        await query.edit_message_text("❌ Cancelled.")
        context.user_data.pop("pending", None)
        return

    pending = context.user_data.get("pending")
    if not pending:
        await query.edit_message_text("⚠️ Session expired. Send the link again.")
        return

    pending["subtitle_lang"] = None if lang == "none" else lang
    await query.edit_message_text("📥 Queuing download…")
    await _enqueue_download(update, context, query.message)


async def _enqueue_download(update: Update, context: ContextTypes.DEFAULT_TYPE, status_msg) -> None:
    user_id = update.effective_user.id
    pending = context.user_data.pop("pending")
    queue: DownloadQueue = context.bot_data["queue"]
    job = {
        "user_id": user_id,
        "chat_id": update.effective_chat.id,
        "url": pending["url"],
        "format_id": pending.get("format_id", "best"),
        "subtitle_lang": pending.get("subtitle_lang"),
        "title": pending["info"].get("title", "video"),
        "status_msg": status_msg,
        "status": "queued",
        "cancelled": False,
    }
    position = queue.enqueue(user_id, job)
    msg = f"📋 Queued at position <b>{position}</b>. Please wait…" if position > 1 else "⬇️ Starting download…"
    await safe_edit_message(status_msg, msg)
    asyncio.create_task(_process_download(context, job))


async def _process_download(context: ContextTypes.DEFAULT_TYPE, job: dict) -> None:
    user_id = job["user_id"]
    chat_id = job["chat_id"]
    status_msg = job["status_msg"]
    downloader: TeraboxDownloader = context.bot_data["downloader"]
    queue: DownloadQueue = context.bot_data["queue"]
    job["status"] = "downloading"
    video_path = subtitle_path = None

    try:
        last_update = [0.0]

        async def progress_hook(d: dict) -> None:
            if job["cancelled"]:
                raise asyncio.CancelledError()
            now = time.time()
            if now - last_update[0] < 3:
                return
            last_update[0] = now
            if d["status"] == "downloading":
                pct   = d.get("_percent_str", "?%").strip()
                speed = d.get("_speed_str", "?").strip()
                eta   = d.get("_eta_str", "?").strip()
                bar   = _progress_bar(d.get("downloaded_bytes", 0),
                                      d.get("total_bytes") or d.get("total_bytes_estimate") or 0)
                await safe_edit_message(
                    status_msg,
                    f"⬇️ <b>Downloading…</b>\n{bar}\n📊 {pct}  🚀 {speed}  ⏱ {eta}",
                )

        video_path, subtitle_path = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: downloader.download(
                job["url"], job["format_id"], job["subtitle_lang"], progress_hook
            ),
        )

        if job["cancelled"]:
            await safe_edit_message(status_msg, "🛑 Cancelled.")
            return

        job["status"] = "uploading"
        await safe_edit_message(status_msg, "📤 <b>Uploading to Telegram…</b>")

        file_size = Path(video_path).stat().st_size
        title = job["title"][:50]

        if file_size > Config.TELEGRAM_FILE_LIMIT:
            await safe_edit_message(status_msg, f"📦 Large file ({bytes_to_human(file_size)}), sending as document…")
            with open(video_path, "rb") as f:
                await context.bot.send_document(
                    chat_id=chat_id, document=f,
                    filename=Path(video_path).name,
                    caption=f"📹 <b>{title}</b>", parse_mode=ParseMode.HTML,
                )
        else:
            with open(video_path, "rb") as f:
                await context.bot.send_video(
                    chat_id=chat_id, video=f,
                    caption=f"📹 <b>{title}</b>", parse_mode=ParseMode.HTML,
                    supports_streaming=True,
                )

        if subtitle_path and Path(subtitle_path).exists():
            with open(subtitle_path, "rb") as sf:
                await context.bot.send_document(
                    chat_id=chat_id, document=sf,
                    filename=Path(subtitle_path).name,
                    caption=f"💬 Subtitles — <b>{title}</b>", parse_mode=ParseMode.HTML,
                )

        await safe_edit_message(status_msg, "✅ <b>Done! Enjoy your video 🎉</b>")
        logger.info("User %s — completed: %s", user_id, title)

    except asyncio.CancelledError:
        await safe_edit_message(status_msg, "🛑 Download cancelled.")
    except Exception as exc:
        logger.error("Download error for user %s: %s", user_id, exc, exc_info=True)
        await safe_edit_message(status_msg, f"❌ <b>Failed.</b>\n<code>{exc}</code>")
    finally:
        job["status"] = "done"
        queue.remove(user_id, job)
        if video_path:
            cleanup_file(video_path)
        if subtitle_path:
            cleanup_file(subtitle_path)


def _progress_bar(done: int, total: int, width: int = 16) -> str:
    if total <= 0:
        return f"[{'▓'*4}{'░'*(width-4)}] ?"
    ratio = min(done / total, 1.0)
    filled = int(ratio * width)
    return f"[{'▓'*filled}{'░'*(width-filled)}] {ratio*100:.1f}%"


async def handle_unknown(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db: UserDB = context.bot_data["db"]
    err = _check_access(db, update.effective_user.id)
    if err:
        await update.message.reply_text(err)
        return
    await update.message.reply_text("🤔 Send me a TeraBox link to download a video!")


# ══════════════════════════════════════════════════════════════════════════════
# App factory & runner
# ══════════════════════════════════════════════════════════════════════════════

def build_app() -> Application:
    app = Application.builder().token(Config.BOT_TOKEN).build()
    app.bot_data["db"]         = UserDB()
    app.bot_data["downloader"] = TeraboxDownloader()
    app.bot_data["queue"]      = DownloadQueue()

    app.add_handler(CommandHandler("start",     cmd_start))
    app.add_handler(CommandHandler("help",      cmd_help))
    app.add_handler(CommandHandler("queue",     cmd_queue))
    app.add_handler(CommandHandler("cancel",    cmd_cancel))
    app.add_handler(CommandHandler("pending",   cmd_pending))
    app.add_handler(CommandHandler("listusers", cmd_listusers))
    app.add_handler(CommandHandler("ban",       cmd_ban))
    app.add_handler(CommandHandler("unban",     cmd_unban))
    app.add_handler(CommandHandler("revoke",    cmd_revoke))

    app.add_handler(CallbackQueryHandler(cb_approve,     pattern=r"^approve\|"))
    app.add_handler(CallbackQueryHandler(cb_ban_request, pattern=r"^ban\|"))
    app.add_handler(CallbackQueryHandler(cb_quality,     pattern=r"^quality\|"))
    app.add_handler(CallbackQueryHandler(cb_subtitle,    pattern=r"^sub\|"))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))
    app.add_handler(MessageHandler(filters.ALL, handle_unknown))
    return app


async def main() -> None:
    Config.validate()
    app = build_app()
    await app.bot.set_my_commands([
        BotCommand("start",     "Start / request access"),
        BotCommand("help",      "How to use"),
        BotCommand("queue",     "Your active downloads"),
        BotCommand("cancel",    "Cancel download"),
        BotCommand("pending",   "[Owner] Pending requests"),
        BotCommand("listusers", "[Owner] All users"),
        BotCommand("ban",       "[Owner] Ban a user"),
        BotCommand("unban",     "[Owner] Unban a user"),
        BotCommand("revoke",    "[Owner] Revoke approval"),
    ])
    logger.info("Bot starting…")
    async with app:
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)
        await asyncio.Event().wait()
        await app.updater.stop()
        await app.stop()


def run_with_restart() -> None:
    while True:
        try:
            asyncio.run(main())
        except KeyboardInterrupt:
            logger.info("Stopped.")
            break
        except Exception as exc:
            logger.critical("Crash: %s — restarting in 5s…", exc, exc_info=True)
            time.sleep(5)


if __name__ == "__main__":
    run_with_restart()
