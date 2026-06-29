#!/usr/bin/env python3
"""
🎮 Verifure Game 10.1 — Telegram Gaming Bot
Currency: VRF · 7 Games · Marriages · Bears · Admin Panel
Games: Duel · Cubes · Basketball · Football · Bowling · Darts · Slot
Deploy: Railway.app | Set BOT_TOKEN env var
Admin ID: 6254951831
"""

import asyncio
import io
import logging
import math
import os
import random
import uuid
from datetime import datetime, timedelta
from functools import wraps
from typing import Optional, Tuple

import aiosqlite
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQueryResultArticle,
    InputTextMessageContent,
    ReactionTypeEmoji,
    Update,
)
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    InlineQueryHandler,
    MessageHandler,
    filters,
)


# ══════════════════════════════════════════════════════
#  STYLED BUTTON — InlineKeyboardButton + style field
# ══════════════════════════════════════════════════════
# Telegram Bot API supports: style="success" 🟢  "danger" 🔴  "primary" 🔵
# python-telegram-bot may not expose `style` yet, so we inject it via to_dict.

class SBtn(InlineKeyboardButton):
    """
    InlineKeyboardButton с официальным параметром Telegram API `style`.
    Значения: "success" (зелёный) | "danger" (красный) | "primary" (синий)
    """
    _cache: dict = {}  # id(self) → style str

    def __init__(self, text: str, *, style: str = None, **kwargs):
        super().__init__(text, **kwargs)
        if style:
            SBtn._cache[id(self)] = style

    def to_dict(self, **kwargs) -> dict:
        d = super().to_dict(**kwargs)
        s = SBtn._cache.get(id(self))
        if s:
            d["style"] = s
        return d

    def __del__(self) -> None:
        SBtn._cache.pop(id(self), None)

# ══════════════════════════════════════════════════════
#                       CONFIG
# ══════════════════════════════════════════════════════

BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
DB_PATH:   str = os.getenv("DB_PATH", "verifure.db")

# ── VRF Economy ───────────────────────────────────────
STARTING_VRF        = 500
DAILY_BONUS_BASE    = 100
DAILY_STREAK_BONUS  = 10    # extra VRF per streak day (max 7)
DAILY_MARRIED_BONUS = 15    # extra VRF when married
GIFT_COST           = 75
GIFT_REWARD         = 100
GIFT_MARRIED_REWARD = 150
GIFT_COOLDOWN_H     = 1
LOVE_REWARD         = 15
LOVE_MARRIED_REWARD = 35
LOVE_COOLDOWN_M     = 30
MAX_BET             = 500
MIN_BET             = 10

# ── Referral ──────────────────────────────────────────
REFERRAL_BONUS_INVITER = 200   # VRF to the person who shared the link
REFERRAL_BONUS_NEW     = 150   # VRF to the new user

# ── Telegram message effects (private chat only) ──────
# These are built-in Telegram effect IDs (🔥 ❤ 🎉 👍 💩 🌟)
MSG_EFFECT_FIRE      = "5046589136895476552"
MSG_EFFECT_HEART     = "5044134455711629726"
MSG_EFFECT_CONFETTI  = "5046507253588062484"
MSG_EFFECT_THUMBSUP  = "5107584321108051014"
MSG_EFFECT_POOP      = "5104841245755180586"   # for losses 😄
MSG_EFFECT_STAR      = "5104858069535582021"

# ── XP / Levels ──────────────────────────────────────
XP_PER_MSG_MIN  = 2
XP_PER_MSG_MAX  = 8
XP_MSG_COOLDOWN = 60        # seconds between XP gains from messages
XP_PER_WIN      = 50
XP_PER_GAME     = 20

# ── Game defaults ─────────────────────────────────────
DEFAULT_ROUNDS  = 3
MAX_ROUNDS      = 10
JOIN_TIMEOUT    = 120       # seconds to accept an invite

# ── Admin IDs from env (plus hardcoded) ───────────────
ADMIN_IDS: list[int] = [6254951831] + [
    int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()
]

# ══════════════════════════════════════════════════════
#                   EMOJI
# ══════════════════════════════════════════════════════

E_ACCEPT = "✅"
E_DECLINE= "❌"
E_STARS  = "⭐️"
E_WIN1   = "🏆"
E_WIN2   = "🥈"
E_RING   = "💍"
E_LOVE   = "❤️"
E_ALERT  = "⚠️"

# ── Semantic aliases ──────────────────────────────────
E_BEAR   = "🐻"   # Bear collectible
E_WARN   = "⚠️"   # Warning / alert
E_BOOM   = "💥"   # Mine explosion
E_VRF    = "💎"   # VRF coin
E_WAIT   = "⏳"   # Waiting player
E_FIRST  = "🥇"   # 1st place
E_SECOND = "🥈"   # 2nd place
E_BONUS  = "⭐"   # Bonus / daily

# ══════════════════════════════════════════════════════
#             IN-MEMORY GAME STATE
# ══════════════════════════════════════════════════════

duel_challenges: dict = {}   # key: f"{cid}:{c_id}:{o_id}"
cubes_games: dict     = {}   # key: game_id (str)
sports_games: dict    = {}   # key: game_id (str)
slot_games: dict      = {}   # key: game_id (str)
mines_games: dict     = {}   # key: f"{uid}:{cid}"
ttt_games: dict       = {}   # key: game_id (str)
battle_games: dict    = {}   # key: game_id (str)  — Battleship

# ══════════════════════════════════════════════════════
#               LEVEL / RANK SYSTEM
# ══════════════════════════════════════════════════════

def xp_for_level(n: int) -> int:
    return 0 if n <= 1 else 50 * n * (n - 1)

def get_level(xp: int) -> int:
    if xp <= 0:
        return 1
    n = int((1 + math.sqrt(1 + 8 * xp / 50)) / 2)
    return max(1, min(n, 100))

def get_progress(xp: int) -> Tuple[int, int, int, float]:
    lvl  = get_level(xp)
    curr = xp_for_level(lvl)
    nxt  = xp_for_level(lvl + 1) if lvl < 100 else curr + 1
    pct  = (xp - curr) / max(1, nxt - curr)
    return lvl, curr, nxt, min(pct, 1.0)

def xp_bar(xp: int, length: int = 12) -> str:
    _, _, _, pct = get_progress(xp)
    filled = round(pct * length)
    return "█" * filled + "░" * (length - filled)

RANKS = [
    (1,  "🌱 Новичок"),  (5,  "📖 Ученик"),   (10, "⚡ Игрок"),
    (15, "🌟 Про"),      (20, "💎 Знаток"),    (25, "🔥 Ветеран"),
    (30, "👑 Авторитет"),(40, "🏆 Легенда"),   (50, "🌙 Мастер"),
    (75, "🚀 Сенсей"),   (100,"⚜️ Бог игры"),
]
MILESTONES = {10, 20, 30, 50, 75, 100}

def get_rank(level: int) -> str:
    result = RANKS[0][1]
    for lvl, name in RANKS:
        if level >= lvl:
            result = name
    return result

# ══════════════════════════════════════════════════════
#               SLOT MACHINE COMBOS
# ══════════════════════════════════════════════════════

def parse_slot(value: int) -> Tuple[str, int]:
    """Map Telegram 🎰 dice value (1-64) to combo name and multiplier."""
    if value <= 22:  return ("🎰 BAR",         2)
    if value <= 38:  return ("🍋 Лимон",        3)
    if value <= 50:  return ("🍒 Вишня",        5)
    if value <= 57:  return ("7️⃣ Семёрка",     10)
    if value <= 62:  return ("💎 Бриллиант",   20)
    return                  ("⭐ ДЖЕКПОТ",     100)

# ══════════════════════════════════════════════════════
#               SPORTS GAME MAPS
# ══════════════════════════════════════════════════════

# Game type → (emoji, dice_emoji, display_name, score_func)
SPORT_EMOJI = {
    "basket":   "🏀",
    "football": "⚽",
    "bowling":  "🎳",
    "darts":    "🎯",
}
SPORT_NAME = {
    "basket":   "Баскетбол",
    "football": "Футбол",
    "bowling":  "Боулинг",
    "darts":    "Дартс",
}
BOWLING_PINS = {1: 0, 2: 3, 3: 5, 4: 6, 5: 8, 6: 10}
DARTS_SCORES = {1: 1, 2: 2, 3: 5, 4: 10, 5: 25, 6: 50}

def score_throw(game_type: str, value: int) -> Tuple[int, str]:
    """Returns (points, label) for a single throw."""
    if game_type == "basket":
        scored = value in (4, 5)
        return (2 if scored else 0), ("🏀 Гол! +2" if scored else "❌ Мимо")
    if game_type == "football":
        scored = value in (3, 4, 5)
        return (1 if scored else 0), ("⚽ Гол! +1" if scored else "❌ Мимо")
    if game_type == "bowling":
        pts = BOWLING_PINS.get(value, 0)
        label = f"🎳 {'Страйк! ' if pts == 10 else ''}+{pts} кегл."
        return pts, label
    if game_type == "darts":
        pts = DARTS_SCORES.get(value, 1)
        label = f"🎯 {'Булл! ' if pts == 50 else ''}+{pts} очк."
        return pts, label
    return value, str(value)

# ══════════════════════════════════════════════════════
#                     LOGGING
# ══════════════════════════════════════════════════════

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("verifure")


# ══════════════════════════════════════════════════════
#          STATISTICS IMAGE GENERATOR 📊
# ══════════════════════════════════════════════════════

def _stats_image_sync(u: dict, display_name: str) -> Optional[bytes]:
    """
    Draw a stats card using Pillow (PIL).
    Falls back to None if Pillow is not installed.
    Add 'Pillow' to requirements.txt to enable.
    """
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return None

    # ── Palette ───────────────────────────────────────────
    BG      = (13,  17,  23)
    CARD    = (22,  27,  34)
    TRACK   = (33,  38,  45)
    BORDER  = (48,  54,  61)
    WHITE   = (201, 209, 217)
    MUTED   = (125, 133, 144)
    GOLD    = (227, 179,  65)
    GREEN   = (63,  185,  80)
    RED     = (248,  81,  73)
    BLUE    = (42,  120, 214)
    GRAY    = (72,   79,  88)
    ORANGE  = (210, 159,  34)
    BROWN   = (161, 136, 127)

    # ── Data ──────────────────────────────────────────────
    wins   = int(u.get("wins",        0))
    losses = int(u.get("losses",      0))
    draws  = int(u.get("draws",       0))
    total  = int(u.get("total_games", 0))
    vrf    = int(u.get("vrf",         0))
    streak = int(u.get("win_streak",  0))
    mstrk  = int(u.get("max_streak",  0))
    bears  = int(u.get("bears",       0))
    xp     = int(u.get("experience",  0))
    lvl    = get_level(xp)
    rnk    = get_rank(lvl)
    _, c_xp, n_xp, pct = get_progress(xp)
    wr     = round(wins / max(1, total) * 100, 1)
    profit = vrf - STARTING_VRF
    p_sign = "+" if profit >= 0 else ""
    p_col  = GREEN if profit >= 0 else RED

    # ── Canvas ────────────────────────────────────────────
    W, H = 900, 538
    img  = Image.new("RGB", (W, H), BG)
    d    = ImageDraw.Draw(img)

    # ── Fonts (DejaVu is standard on Ubuntu/Railway) ──────
    _REG = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
    ]
    _BOLD = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
    ]

    def _font(paths: list, size: int):
        for p in paths:
            try:
                return ImageFont.truetype(p, size)
            except (OSError, IOError):
                continue
        try:
            return ImageFont.load_default(size=size)
        except TypeError:
            return ImageFont.load_default()

    f10  = _font(_REG,  10); f11 = _font(_REG,  11)
    f12  = _font(_REG,  12); f14 = _font(_REG,  14)
    fb12 = _font(_BOLD, 12); fb14 = _font(_BOLD, 14)
    fb20 = _font(_BOLD, 20); fb24 = _font(_BOLD, 24)
    fb28 = _font(_BOLD, 28)

    # ── Draw helpers ──────────────────────────────────────
    def _tw(s: str, font) -> int:
        b = d.textbbox((0, 0), s, font=font)
        return b[2] - b[0]

    def tl(x, y, s, font, fill=WHITE):
        d.text((x, y), s, font=font, fill=fill)

    def tr(x, y, s, font, fill=WHITE):
        d.text((x - _tw(s, font), y), s, font=font, fill=fill)

    def tc(cx, y, s, font, fill=WHITE):
        d.text((cx - _tw(s, font) // 2, y), s, font=font, fill=fill)

    def rr(x1, y1, x2, y2, fill=CARD, r=10, outline=None):
        try:
            d.rounded_rectangle(
                [x1, y1, x2, y2], radius=r, fill=fill,
                outline=outline, width=1 if outline else 0,
            )
        except AttributeError:
            d.rectangle([x1, y1, x2, y2], fill=fill, outline=outline)

    def hrule(y, x1=25, x2=W-25):
        d.line([(x1, y), (x2, y)], fill=TRACK, width=1)

    # ══════════════════════════════════════════════════════
    # HEADER
    # ══════════════════════════════════════════════════════
    tc(W//2, 12, display_name, fb24)
    tc(W//2, 46,
       f"{fmt(vrf)} VRF   |   Ур.{lvl} — {rnk}   |   W/R {wr}%",
       f14, GOLD)

    # ══════════════════════════════════════════════════════
    # METRIC CARDS  (Победы / Поражения / Ничьи)
    # ══════════════════════════════════════════════════════
    CY1, CY2 = 76, 170
    CW = (W - 40) // 3
    for i, (lbl, val, col) in enumerate([
        ("Победы",    wins,   GREEN),
        ("Поражения", losses, RED),
        ("Ничьи",     draws,  GRAY),
    ]):
        cx1 = 15 + i * (CW + 5)
        cx2 = cx1 + CW
        mid = (cx1 + cx2) // 2
        rr(cx1, CY1, cx2, CY2)
        tc(mid, CY1 + 8,  lbl, f11, MUTED)
        tc(mid, CY1 + 30, str(val), fb28, col)
        pv = round(val / max(1, total) * 100, 1)
        tc(mid, CY1 + 74, f"{pv}%", f10, MUTED)

    # ══════════════════════════════════════════════════════
    # LEVEL PROGRESS BAR
    # ══════════════════════════════════════════════════════
    LY1 = 178
    rr(15, LY1, W-15, LY1 + 56)
    tl(25, LY1 + 8, f"Уровень {lvl} → {lvl+1}", f12, MUTED)
    tr(W-25, LY1 + 8,
       f"{int(pct*100)}%   |   {xp-c_xp:,} / {n_xp-c_xp:,} XP", f12, MUTED)
    rr(25, LY1+32, W-25, LY1+50, fill=TRACK, r=9)
    fw = max(18, int((W-50) * pct))
    rr(25, LY1+32, 25+fw, LY1+50, fill=BLUE, r=9)

    # ══════════════════════════════════════════════════════
    # W / L / D  RATIO BAR
    # ══════════════════════════════════════════════════════
    WY1 = 242
    rr(15, WY1, W-15, WY1 + 62)
    tl(25, WY1 + 8, "W / L / D", f12, MUTED)

    BX, BW = 25, W - 50
    BY1, BY2 = WY1+30, WY1+46

    rr(BX, BY1, BX+BW, BY2, fill=TRACK, r=8)   # track
    if total > 0:
        ww = int(BW * wins   / total)
        lw = int(BW * losses / total)
        dw = BW - ww - lw
        gap = 3
        # Wins
        if ww > 0:
            rr(BX, BY1, BX+ww, BY2, fill=GREEN, r=8)
        # Losses
        if lw > 0:
            xl = BX + ww + (gap if ww else 0)
            d.rectangle([xl, BY1, xl+lw, BY2], fill=RED)
            if dw <= 0:  # round right end
                rr(BX+BW-8, BY1, BX+BW, BY2, fill=RED, r=8)
        # Draws
        if dw > 0:
            xd = BX + ww + lw + (gap*2 if (ww+lw) else 0)
            d.rectangle([xd, BY1, BX+BW, BY2], fill=GRAY)
            rr(BX+BW-8, BY1, BX+BW, BY2, fill=GRAY, r=8)
        # Legend
        lx = BX
        for lc, lt, lv in [(GREEN,"Победы",wins),(RED,"Пор.",losses),(GRAY,"Ничья",draws)]:
            d.ellipse([lx, BY2+5, lx+8, BY2+13], fill=lc)
            tl(lx+12, BY2+4, f"{lt}: {lv}", f10, MUTED)
            lx += 130
    else:
        tc(BX + BW//2, BY1+4, "Нет игр", f11, MUTED)

    # ══════════════════════════════════════════════════════
    # STATS TABLE
    # ══════════════════════════════════════════════════════
    TY = 312
    rows = [
        ("Всего игр",       str(total),                   WHITE),
        ("Текущий стрик",   f"{streak}  (рекорд: {mstrk})", ORANGE),
        ("Медведей",        str(bears),                   BROWN),
        ("VRF от старта",   f"{p_sign}{fmt(profit)}",     p_col),
        ("Всего побед",     str(wins),                    GREEN),
    ]
    RH = 40
    TH = len(rows) * RH + 16
    rr(15, TY, W-15, TY+TH)
    for i, (lbl, val, col) in enumerate(rows):
        ry = TY + 10 + i * RH
        tl(25, ry, lbl, f14, MUTED)
        tr(W-25, ry, val, fb14, col)
        if i < len(rows)-1:
            hrule(ry + RH - 2)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf.read()



# ══════════════════════════════════════════════════════
#         RICH MESSAGE HELPER  📄
# ══════════════════════════════════════════════════════

async def send_rich(
    bot,
    chat_id: int,
    markdown: str = "",
    fallback_html: str = "",
    reply_to_id: int = None,
    reply_markup=None,
    html: str = "",
) -> bool:
    """
    Send via sendRichMessage (tables, headings, lists…) with fallback to plain HTML.
    html=          → rich HTML content (full sendRichMessage tags)
    fallback_html= → simple HTML for regular send_message
    markdown=      → rich Markdown alternative (used when html is empty)
    """
    fb_text = fallback_html or html or markdown

    # ── Try sendRichMessage ───────────────────────────
    rich_msg: dict = {"html": html} if html else {"markdown": markdown or " "}
    kw: dict = {"chat_id": chat_id, "rich_message": rich_msg}
    if reply_to_id:
        kw["reply_parameters"] = {"message_id": reply_to_id}
    if reply_markup:
        try:
            kw["reply_markup"] = reply_markup.to_dict()
        except Exception:
            pass
    try:
        await bot.do_api_request("sendRichMessage", api_kwargs=kw)
        return True
    except Exception:
        pass

    # ── Fallback: regular HTML send_message ───────────
    msg_kw: dict = {"chat_id": chat_id, "text": fb_text, "parse_mode": ParseMode.HTML}
    if reply_to_id:
        msg_kw["reply_parameters"] = {"message_id": reply_to_id}
    if reply_markup:
        msg_kw["reply_markup"] = reply_markup
    try:
        await bot.send_message(**msg_kw)
        return False
    except Exception:
        pass

    # ── Last resort: plain text ───────────────────────
    import re as _re
    plain = _re.sub(r"<[^>]+>", "", fb_text)[:4096].strip()
    if plain:
        try:
            p_kw: dict = {"chat_id": chat_id, "text": plain}
            if reply_markup:
                p_kw["reply_markup"] = reply_markup
            await bot.send_message(**p_kw)
        except Exception:
            pass
    return False

# ══════════════════════════════════════════════════════
#                    DATABASE
# ══════════════════════════════════════════════════════

async def db_init() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                user_id      INTEGER,
                chat_id      INTEGER,
                username     TEXT    DEFAULT '',
                first_name   TEXT    DEFAULT '',
                vrf          INTEGER DEFAULT 500,
                experience   INTEGER DEFAULT 0,
                level        INTEGER DEFAULT 1,
                wins         INTEGER DEFAULT 0,
                losses       INTEGER DEFAULT 0,
                draws        INTEGER DEFAULT 0,
                total_games  INTEGER DEFAULT 0,
                win_streak   INTEGER DEFAULT 0,
                max_streak   INTEGER DEFAULT 0,
                bears        INTEGER DEFAULT 0,
                last_xp      TEXT    DEFAULT NULL,
                last_daily   TEXT    DEFAULT NULL,
                daily_streak INTEGER DEFAULT 0,
                last_gift    TEXT    DEFAULT NULL,
                last_love    TEXT    DEFAULT NULL,
                PRIMARY KEY (user_id, chat_id)
            );

            CREATE TABLE IF NOT EXISTS marriages (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user1_id   INTEGER NOT NULL,
                user2_id   INTEGER NOT NULL,
                chat_id    INTEGER NOT NULL,
                married_at TEXT    NOT NULL,
                UNIQUE (user1_id, chat_id),
                UNIQUE (user2_id, chat_id)
            );

            CREATE TABLE IF NOT EXISTS proposals (
                proposer_id INTEGER NOT NULL,
                target_id   INTEGER NOT NULL,
                chat_id     INTEGER NOT NULL,
                created_at  TEXT    NOT NULL,
                PRIMARY KEY (proposer_id, chat_id)
            );

            CREATE TABLE IF NOT EXISTS admins (
                user_id    INTEGER PRIMARY KEY,
                username   TEXT    DEFAULT '',
                first_name TEXT    DEFAULT '',
                added_by   INTEGER,
                added_at   TEXT    NOT NULL
            );

            CREATE TABLE IF NOT EXISTS daily_activity (
                date     TEXT    NOT NULL,
                chat_id  INTEGER NOT NULL,
                messages INTEGER DEFAULT 0,
                games    INTEGER DEFAULT 0,
                PRIMARY KEY (date, chat_id)
            );


        """)
        await db.commit()
        # ── Migrations (safe: ignore if column already exists) ──
        try:
            await db.execute(
                "ALTER TABLE users ADD COLUMN last_bio_bonus TEXT DEFAULT NULL"
            )
            await db.commit()
        except Exception:
            pass  # Column already exists
        for col_sql in (
            "ALTER TABLE users ADD COLUMN referral_by    INTEGER DEFAULT NULL",
            "ALTER TABLE users ADD COLUMN referral_count INTEGER DEFAULT 0",
        ):
            try:
                await db.execute(col_sql)
                await db.commit()
            except Exception:
                pass
    log.info("Database initialised at %s", DB_PATH)


async def db_log_activity(cid: int, msgs: int = 0, gms: int = 0) -> None:
    """Increment daily message/game counters for a chat."""
    today = datetime.now().strftime("%Y-%m-%d")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO daily_activity (date, chat_id, messages, games)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(date, chat_id) DO UPDATE SET
                   messages = messages + excluded.messages,
                   games    = games    + excluded.games""",
            (today, cid, msgs, gms),
        )
        await db.commit()


async def db_get_activity(cid: int, days: int = 30) -> list:
    """Return (date, messages, games) rows for the last N days."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            """SELECT date, messages, games
               FROM daily_activity
               WHERE chat_id = ?
                 AND date >= date('now', ? || ' days')
               ORDER BY date""",
            (cid, f"-{days}"),
        ) as cur:
            return await cur.fetchall()


# ── Users ──────────────────────────────────────────────

async def db_ensure_user(uid: int, cid: int, username: str, first_name: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO users (user_id, chat_id, username, first_name, vrf)
               VALUES (?,?,?,?,?)
               ON CONFLICT(user_id, chat_id) DO UPDATE SET
                 username=excluded.username, first_name=excluded.first_name""",
            (uid, cid, username or "", first_name or "", STARTING_VRF),
        )
        await db.commit()


async def db_get_user(uid: int, cid: int) -> Optional[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM users WHERE user_id=? AND chat_id=?", (uid, cid)
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def db_add_vrf(uid: int, cid: int, amount: int) -> int:
    """Add VRF. Returns new balance."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET vrf=vrf+? WHERE user_id=? AND chat_id=?",
            (amount, uid, cid),
        )
        await db.commit()
        async with db.execute(
            "SELECT vrf FROM users WHERE user_id=? AND chat_id=?", (uid, cid)
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else 0


async def db_set_vrf(uid: int, cid: int, amount: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET vrf=? WHERE user_id=? AND chat_id=?",
            (max(0, amount), uid, cid),
        )
        await db.commit()
    return max(0, amount)


async def db_deduct_vrf(uid: int, cid: int, amount: int) -> bool:
    """Deduct VRF only if user has enough. Returns success."""
    u = await db_get_user(uid, cid)
    if not u or u["vrf"] < amount:
        return False
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET vrf=vrf-? WHERE user_id=? AND chat_id=?",
            (amount, uid, cid),
        )
        await db.commit()
    return True


async def db_add_xp(uid: int, cid: int, amount: int) -> Tuple[int, bool]:
    """Add XP. Returns (new_level, leveled_up)."""
    u = await db_get_user(uid, cid)
    if not u:
        return 1, False
    old_lvl = get_level(u["experience"])
    new_xp   = u["experience"] + amount
    new_lvl  = get_level(new_xp)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET experience=?, level=?, last_xp=? WHERE user_id=? AND chat_id=?",
            (new_xp, new_lvl, _now(), uid, cid),
        )
        await db.commit()
    return new_lvl, new_lvl > old_lvl


async def db_record_game(
    uid: int, cid: int, won: bool, draw: bool = False,
    streak_reset: bool = True
) -> None:
    """Update win/loss/streak counters."""
    u = await db_get_user(uid, cid)
    if not u:
        return
    streak = u["win_streak"]
    max_s  = u["max_streak"]
    if won:
        streak += 1
        max_s   = max(max_s, streak)
    elif not draw and streak_reset:
        streak = 0

    async with aiosqlite.connect(DB_PATH) as db:
        if won:
            await db.execute(
                """UPDATE users SET wins=wins+1, total_games=total_games+1,
                   win_streak=?, max_streak=? WHERE user_id=? AND chat_id=?""",
                (streak, max_s, uid, cid),
            )
        elif draw:
            await db.execute(
                "UPDATE users SET draws=draws+1, total_games=total_games+1 WHERE user_id=? AND chat_id=?",
                (uid, cid),
            )
        else:
            await db.execute(
                """UPDATE users SET losses=losses+1, total_games=total_games+1,
                   win_streak=0 WHERE user_id=? AND chat_id=?""",
                (uid, cid),
            )
        await db.commit()

    # Bears milestone: every 10th win
    u2 = await db_get_user(uid, cid)
    if u2 and won and u2["wins"] % 10 == 0:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE users SET bears=bears+1 WHERE user_id=? AND chat_id=?",
                (uid, cid),
            )
            await db.commit()

    # Log one game per winner to daily activity chart
    if won:
        await db_log_activity(cid, gms=1)


async def db_can_earn_xp(uid: int, cid: int) -> bool:
    u = await db_get_user(uid, cid)
    if not u or not u["last_xp"]:
        return True
    return (datetime.now() - datetime.fromisoformat(u["last_xp"])).total_seconds() >= XP_MSG_COOLDOWN


# ── Leaderboard ────────────────────────────────────────

async def db_top(cid: int, sort: str = "vrf", limit: int = 10) -> list:
    col = {"vrf": "vrf", "level": "experience", "wins": "wins"}.get(sort, "vrf")
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            f"SELECT * FROM users WHERE chat_id=? ORDER BY {col} DESC LIMIT ?",
            (cid, limit),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def db_rank_pos(uid: int, cid: int, col: str = "vrf") -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            f"""SELECT COUNT(*)+1 FROM users
                WHERE chat_id=? AND {col}>(SELECT {col} FROM users WHERE user_id=? AND chat_id=?)""",
            (cid, uid, cid),
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else 1


async def db_count_users(cid: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM users WHERE chat_id=?", (cid,)) as cur:
            return (await cur.fetchone())[0]


async def db_find_user_by_username(username: str, cid: int) -> Optional[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM users WHERE LOWER(username)=? AND chat_id=?",
            (username.lower().lstrip("@"), cid),
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


# ── Marriages ──────────────────────────────────────────

async def db_get_marriage(uid: int, cid: int) -> Optional[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM marriages WHERE (user1_id=? OR user2_id=?) AND chat_id=?",
            (uid, uid, cid),
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def db_get_proposal_to(target_id: int, cid: int) -> Optional[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM proposals WHERE target_id=? AND chat_id=?", (target_id, cid)
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def db_create_marriage(uid1: int, uid2: int, cid: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO marriages (user1_id,user2_id,chat_id,married_at) VALUES(?,?,?,?)",
            (uid1, uid2, cid, _now()),
        )
        await db.execute(
            "DELETE FROM proposals WHERE chat_id=? AND (proposer_id IN(?,?) OR target_id IN(?,?))",
            (cid, uid1, uid2, uid1, uid2),
        )
        await db.commit()


async def db_delete_marriage(mid: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM marriages WHERE id=?", (mid,))
        await db.commit()


async def db_all_marriages(cid: int) -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM marriages WHERE chat_id=? ORDER BY married_at DESC", (cid,)
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


# ── Admins ─────────────────────────────────────────────

async def db_add_admin(uid: int, username: str, first_name: str, added_by: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO admins(user_id,username,first_name,added_by,added_at) VALUES(?,?,?,?,?)",
            (uid, username or "", first_name or "", added_by, _now()),
        )
        await db.commit()


async def db_remove_admin(uid: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("DELETE FROM admins WHERE user_id=?", (uid,))
        await db.commit()
        return cur.rowcount > 0


async def db_list_admins() -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM admins ORDER BY added_at") as cur:
            return [dict(r) for r in await cur.fetchall()]


async def is_bot_admin(uid: int) -> bool:
    if uid in ADMIN_IDS:
        return True
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT 1 FROM admins WHERE user_id=?", (uid,)) as cur:
            return bool(await cur.fetchone())


async def is_group_or_bot_admin(update: Update) -> bool:
    uid = update.effective_user.id
    if await is_bot_admin(uid):
        return True
    try:
        member = await update.effective_chat.get_member(uid)
        return member.status in ("administrator", "creator")
    except TelegramError:
        return False





# ══════════════════════════════════════════════════════
#                    HELPERS
# ══════════════════════════════════════════════════════

def _now() -> str:
    return datetime.now().isoformat()

def mention(uid: int, name: str) -> str:
    safe = str(name).replace("<", "&lt;").replace(">", "&gt;").replace("&", "&amp;")
    return f'<a href="tg://user?id={uid}">{safe}</a>'

def fmt(n: int) -> str:
    if n >= 1_000_000: return f"{n/1_000_000:.1f}M"
    if n >= 10_000:    return f"{n/1_000:.1f}K"
    return f"{n:,}".replace(",", " ")

def fmt_cd(seconds: int) -> str:
    h, m, s = seconds // 3600, (seconds % 3600) // 60, seconds % 60
    if h: return f"{h}ч {m}м"
    if m: return f"{m}м {s}с"
    return f"{s}с"

def days_ago(dt_str: str) -> int:
    return (datetime.now() - datetime.fromisoformat(dt_str)).days

def partner_id(m: dict, uid: int) -> int:
    return m["user2_id"] if m["user1_id"] == uid else m["user1_id"]

def calc_bet(vrf: int, other_vrf: int) -> int:
    """Auto bet: 10% of lowest balance, clamped."""
    return max(MIN_BET, min(MAX_BET, min(vrf, other_vrf) // 10))

MEDALS = [E_FIRST, E_SECOND, "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]

def only_groups(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_chat.type == "private":
            await update.message.reply_text("❌ Эта команда работает только в групповых чатах.")
            return
        return await func(update, context)
    return wrapper

async def _react(update: Update, emoji: str = "🎉") -> None:
    try:
        await update.message.react([ReactionTypeEmoji(emoji=emoji)])
    except TelegramError:
        pass

async def _resolve_target(update: Update, context: ContextTypes.DEFAULT_TYPE, cid: int):
    if update.message.reply_to_message:
        t = update.message.reply_to_message.from_user
        if not t.is_bot:
            return t, None
    if context.args:
        uname = context.args[0].lstrip("@")
        row   = await db_find_user_by_username(uname, cid)
        if row:
            class _FakeUser:
                id = row["user_id"]; first_name = row["first_name"]
                username = row["username"]; is_bot = False
            return _FakeUser(), None
        return None, f"❌ @{uname} не найден в чате."
    return None, "❌ Укажи пользователя: ответь на его сообщение или /команда @username"


# ══════════════════════════════════════════════════════
#                BASE COMMANDS
# ══════════════════════════════════════════════════════

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    u   = update.effective_user
    cid = update.effective_chat.id

    # ── Handle referral deep link in private chat ─────────
    if update.effective_chat.type == "private" and context.args:
        arg = context.args[0]
        if arg.startswith("ref_"):
            inviter_id = None
            try:
                inviter_id = int(arg[4:])
            except ValueError:
                pass
            if inviter_id and inviter_id != u.id:
                # Find inviter in any chat and reward both
                async with aiosqlite.connect(DB_PATH) as db:
                    # Check if user already has a referral_by set
                    async with db.execute(
                        "SELECT referral_by FROM users WHERE user_id=? LIMIT 1", (u.id,)
                    ) as cur:
                        row = await cur.fetchone()
                    already = row and row[0] is not None if row else False

                    if not already:
                        # Credit inviter in all their chats
                        await db.execute(
                            "UPDATE users SET vrf=vrf+?, referral_count=referral_count+1 WHERE user_id=?",
                            (REFERRAL_BONUS_INVITER, inviter_id),
                        )
                        # Mark new user's referral_by
                        await db.execute(
                            "UPDATE users SET referral_by=? WHERE user_id=?",
                            (inviter_id, u.id),
                        )
                        # Credit new user if they exist
                        await db.execute(
                            "UPDATE users SET vrf=vrf+? WHERE user_id=?",
                            (REFERRAL_BONUS_NEW, u.id),
                        )
                        await db.commit()
                        try:
                            await context.bot.send_message(
                                inviter_id,
                                f"🎉 <b>Реферальный бонус!</b>\n\n"
                                f"👤 {u.first_name} зарегистрировался по твоей ссылке!\n"
                                f"💎 +{fmt(REFERRAL_BONUS_INVITER)} VRF",
                                parse_mode=ParseMode.HTML,
                            )
                        except TelegramError:
                            pass
                        await update.message.reply_text(
                            f"🎉 <b>Реферальный бонус!</b>\n\n"
                            f"Ты зарегистрировался по ссылке от друга!\n"
                            f"💎 +{fmt(REFERRAL_BONUS_NEW)} VRF тебе на счёт!",
                            parse_mode=ParseMode.HTML,
                        )

    if update.effective_chat.type == "private":
        rich_h = (
            "<h1>👋 Verifure Game</h1>"
            "<p>Игровой Telegram бот с внутренней валютой <b>VRF</b>!</p>"
            "<hr/>"
            "<h2>🎮 Игры на VRF</h2>"
            "<ul>"
            "<li>⚔️ <b>Дуэль</b> · 🎲 <b>Кубики</b> · 🎰 <b>Слот-машина</b></li>"
            "<li>🏀 Баскетбол · ⚽ Футбол · 🎳 Боулинг · 🎯 Дартс</li>"
            "<li>💣 <b>Мины</b> <i>(соло)</i> · ❌⭕ <b>Крестики-нолики</b> · 🚢 <b>Морской Бой</b></li>"
            "</ul>"
            "<hr/>"
            f"<blockquote>💎 Стартовый баланс: <b>{STARTING_VRF} VRF</b></blockquote>"
            "<footer>📌 Добавь меня в группу и напиши /start</footer>"
        )
        fb_h = (
            "👋 <b>Привет! Я Verifure Game</b>\n\n"
            f"💎 Стартовый баланс: <b>{STARTING_VRF} VRF</b>\n\n"
            "⚔️ Дуэль · 🎲 Кубики · 🏀 Баскетбол · ⚽ Футбол\n"
            "🎳 Боулинг · 🎯 Дартс · 🎰 Слот · 💣 Мины · ❌⭕ Крестики\n\n"
            "📌 Добавь меня в группу и напиши /start"
        )
        await send_rich(context.bot, cid, html=rich_h, fallback_html=fb_h,
                        reply_to_id=update.message.message_id)
        return

    await db_ensure_user(u.id, cid, u.username or "", u.first_name)
    uu = await db_get_user(u.id, cid)
    bal = uu["vrf"] if uu else STARTING_VRF

    rich_h = (
        f"<h2>👋 Привет, {u.first_name}!</h2>"
        f"<blockquote>💎 На твоём счёте <b>{fmt(bal)} VRF</b></blockquote>"
        "<hr/>"
        "<h3>🚀 Быстрый старт</h3>"
        "<ul>"
        "<li>/duel — ⚔️ Дуэль <i>(ответом на сообщение соперника)</i></li>"
        "<li>/cubes — 🎲 Кубики <i>(ответом)</i></li>"
        "<li>/slot — 🎰 Слот PvP <i>(ответом)</i></li>"
        "<li>/mines — 💣 Мины <i>(соло)</i></li>"
        "<li>/tictac — ❌⭕ Крестики-нолики <i>(ответом)</i></li>"
        "<li>/seabattle — 🚢 Морской Бой <i>(ответом, PvP в ЛС)</i></li>"
        "<li>/daily — ⚡ Ежедневный бонус</li>"
        "</ul>"
        "<footer>📖 /help — посмотреть все команды</footer>"
    )
    fb_h = (
        f"👋 Привет, {mention(u.id, u.first_name)}!\n\n"
        f"💎 Баланс: <b>{fmt(bal)} VRF</b>\n\n"
        "⚔️ /duel · 🎲 /cubes · 🎰 /slot · 💣 /mines · ❌⭕ /tictac\n"
        "⚡ /daily · 📖 /help"
    )
    await send_rich(context.bot, cid, html=rich_h, fallback_html=fb_h,
                    reply_to_id=update.message.message_id)




async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cid = update.effective_chat.id
    rich_h = (
        "<h1>📖 Verifure Game — Помощь</h1>"
        "<h3>👤 Профиль &amp; Активность</h3>"
        "<ul>"
        "<li>/profile — профиль и баланс VRF</li>"
        "<li>/top — 🏆 топ игроков <i>(VRF / Уровень / Победы)</i></li>"
        "<li>/stats — 📊 статистика чата</li>"
        "<li>/daily — ⚡ ежедневный бонус</li>"
        "<li>/bonus — статус всех кулдаунов</li>"
        "</ul>"
        "<h3>🎮 Игры <i>(ответом на сообщение соперника)</i></h3>"
        "<ul>"
        "<li>/duel — ⚔️ Дуэль на VRF</li>"
        "<li>/cubes <code>[раунды] [ставка]</code> — 🎲 Кубики</li>"
        "<li>/basket — 🏀 Баскетбол</li>"
        "<li>/football — ⚽ Футбол</li>"
        "<li>/bowling — 🎳 Боулинг</li>"
        "<li>/darts — 🎯 Дартс</li>"
        "<li>/slot — 🎰 Слот-машина PvP</li>"
        "<li>/mines — 💣 Мины <i>(соло)</i></li>"
        "<li>/tictac — ❌⭕ Крестики-нолики</li>"
        "<li>/seabattle — 🚢 Морской Бой <i>(PvP в ЛС)</i></li>"
        "</ul>"
        "<h3>💒 Браки</h3>"
        "<ul>"
        "<li>/marry — предложение руки и сердца</li>"
        "<li>/accept · /reject — ответ на предложение</li>"
        "<li>/divorce — развод · /marriage — карточка пары</li>"
        "<li>/marriages — все пары чата</li>"
        "</ul>"
        "<h3>🎁 Активности</h3>"
        "<ul>"
        "<li>/gift — 🎁 подарить VRF <i>(ответом, стоит 75 VRF)</i></li>"
        "<li>/love — ❤️ послать любовь <i>(ответом, +VRF обоим)</i></li>"
        "</ul>"
        "<h3>🛡️ Администраторы</h3>"
        "<ul>"
        "<li>/admin — панель управления</li>"
        "<li>/givevrf <code>&lt;n&gt;</code> · /takevrf <code>&lt;n&gt;</code> — выдать/забрать VRF</li>"
        "<li>/givebear · /addadmin · /removeadmin · /listadmins</li>"
        "</ul>"
        "<hr/>"
        "<details open><summary>⚙️ Механика</summary>"
        "<ul>"
        f"<li>Начальный баланс: <b>{STARTING_VRF} VRF</b></li>"
        f"<li>Ежедневный бонус: <b>{DAILY_BONUS_BASE} VRF</b> + стрик (до +60)</li>"
        f"<li>💍 Брак: <b>+{DAILY_MARRIED_BONUS} VRF</b> к ежедневному</li>"
        f"<li>🎁 Подарок: <b>{GIFT_COST} VRF</b> &rarr; <b>{GIFT_REWARD} VRF</b> получателю</li>"
        "<li>🐻 Медведь за каждые <b>10 побед</b></li>"
        f"<li>🔗 Реферал: <b>+{REFERRAL_BONUS_INVITER} VRF</b> тебе &amp; <b>+{REFERRAL_BONUS_NEW} VRF</b> другу</li>"
        "</ul>"
        "</details>"
    )
    fb_h = (
        "📖 <b>Verifure Game — Помощь</b>\n\n"
        "<b>👤 Профиль:</b> /profile /top /stats /daily /bonus /ref\n"
        "<b>🎮 Игры:</b> /duel /cubes /basket /football /bowling /darts /slot /mines /tictac /seabattle\n"
        "<b>💒 Браки:</b> /marry /accept /reject /divorce /marriage /marriages\n"
        "<b>🎁 Активности:</b> /gift /love\n"
        "<b>🛡️ Админ:</b> /admin /givevrf /takevrf /givebear /addadmin\n\n"
        f"💎 Старт: <b>{STARTING_VRF} VRF</b> · Бонус: <b>{DAILY_BONUS_BASE} VRF/день</b> · 🐻 за 10 побед!\n"
        f"🔗 Реф. ссылка: /ref"
    )
    await send_rich(context.bot, cid, html=rich_h, fallback_html=fb_h,
                    reply_to_id=update.message.message_id)


# ══════════════════════════════════════════════════════
#           REFERRAL SYSTEM 🔗
# ══════════════════════════════════════════════════════

async def cmd_ref(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show personal referral link + stats."""
    u   = update.effective_user
    cid = update.effective_chat.id
    await db_ensure_user(u.id, cid, u.username or "", u.first_name)
    uu  = await db_get_user(u.id, cid)

    bot_info = await context.bot.get_me()
    bot_username = bot_info.username
    ref_link = f"https://t.me/{bot_username}?start=ref_{u.id}"

    ref_count = uu.get("referral_count") or 0
    earned    = ref_count * REFERRAL_BONUS_INVITER

    ref_text = (
        f"🔗 <b>Реферальная ссылка</b>\n\n"
        f"Поделись ссылкой — получите бонус оба:\n"
        f"💎 Ты получишь: <b>+{fmt(REFERRAL_BONUS_INVITER)} VRF</b> за каждого\n"
        f"💎 Друг получит: <b>+{fmt(REFERRAL_BONUS_NEW)} VRF</b>\n\n"
        f"📊 Приглашено: <b>{ref_count}</b> чел. · Заработано: <b>{fmt(earned)} VRF</b>\n\n"
        f"<code>{ref_link}</code>"
    )
    await update.message.reply_text(
        ref_text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("📤 Поделиться", switch_inline_query=f"ref {u.id}"),
        ]]),
    )


# ══════════════════════════════════════════════════════
#         STATS IMAGE COMMAND 📊
# ══════════════════════════════════════════════════════

@only_groups
async def cmd_statsimg(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send statistics as a styled image card."""
    if update.message.reply_to_message and not update.message.reply_to_message.from_user.is_bot:
        target = update.message.reply_to_message.from_user
    else:
        target = update.effective_user

    cid = update.effective_chat.id
    await db_ensure_user(target.id, cid, target.username or "", target.first_name)
    u = await db_get_user(target.id, cid)
    if not u:
        return

    display = f"@{u['username']}" if u.get("username") else u.get("first_name", "Игрок")

    # Run in executor to avoid blocking the event loop
    loop = asyncio.get_event_loop()
    img_bytes = await loop.run_in_executor(None, _stats_image_sync, u, display)

    if img_bytes is None:
        await update.message.reply_text(
            "❌ <b>Pillow не установлен!</b>\n\n"
            "Добавь в <code>requirements.txt</code>:\n"
            "<code>Pillow</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    lvl     = get_level(u["experience"])
    wr      = round(u["wins"] / max(1, u["total_games"]) * 100, 1)
    profit  = u["vrf"] - STARTING_VRF
    p_sign  = "+" if profit >= 0 else ""

    caption = (
        f"📊 <b>Статистика {mention(target.id, u['first_name'])}</b>\n"
        f"💎 {fmt(u['vrf'])} VRF  ·  Уровень {lvl} — {get_rank(lvl)}\n"
        f"🏆 {u['wins']} побед ({wr}%)  ·  🎮 {u['total_games']} игр\n"
        f"💰 Баланс от старта: <b>{p_sign}{fmt(profit)} VRF</b>"
    )

    await context.bot.send_photo(
        chat_id=cid,
        photo=io.BytesIO(img_bytes),
        caption=caption,
        parse_mode=ParseMode.HTML,
    )


# ══════════════════════════════════════════════════════
#         ACTIVITY CHART COMMAND 📈
# ══════════════════════════════════════════════════════

def _activity_chart_sync(rows: list) -> Optional[bytes]:
    """
    Generate 'Статистика активности' bar chart using matplotlib.
    rows: list of (date 'YYYY-MM-DD', messages: int, games: int)
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
        from datetime import datetime as _dt, timedelta as _td
    except ImportError:
        return None

    if not rows:
        return None

    # ── Fill all dates in range (0 for missing days) ──────
    all_dates: dict = {}
    if rows:
        start = _dt.strptime(rows[0][0],  "%Y-%m-%d")
        end   = _dt.strptime(rows[-1][0], "%Y-%m-%d")
        cur   = start
        while cur <= end:
            all_dates[cur.strftime("%Y-%m-%d")] = [0, 0]
            cur += _td(days=1)
    for date_s, msg, gm in rows:
        all_dates[date_s] = [int(msg), int(gm)]

    sorted_dates = sorted(all_dates)
    messages = [all_dates[d][0] for d in sorted_dates]
    games    = [all_dates[d][1] for d in sorted_dates]
    labels   = [d[8:10] + "." + d[5:7] for d in sorted_dates]   # DD.MM
    n        = len(sorted_dates)
    x        = np.arange(n)
    bar_w    = 0.40

    # ── Figure ────────────────────────────────────────────
    fig, ax = plt.subplots(figsize=(13, 5.5))
    fig.patch.set_facecolor("#f4f4f4")
    ax.set_facecolor("#f4f4f4")

    # ── Bars ──────────────────────────────────────────────
    # Lime-green for messages, orange for games
    ax.bar(x - bar_w / 2, messages, bar_w,
           color="#b5e61d", zorder=3, label="Сообщения")
    ax.bar(x + bar_w / 2, games,    bar_w,
           color="#f07030", zorder=3, label="Игры")

    # ── X-axis: show label every ~2 days ─────────────────
    step = max(1, n // 15)
    ax.set_xticks(x[::step])
    ax.set_xticklabels(labels[::step], fontsize=9, color="#444444")
    ax.tick_params(axis="x", bottom=False, top=False)
    ax.set_xlim(-0.7, n - 0.3)

    # ── Y-axis left ───────────────────────────────────────
    ax.tick_params(axis="y", labelsize=9, labelcolor="#444444",
                   left=True, right=False)
    ax.set_ylim(bottom=0)

    # ── Twin Y-axis (right) with "Сообщения" label ────────
    ax2 = ax.twinx()
    ax2.set_ylim(ax.get_ylim())
    yticks = ax.get_yticks()
    ax2.set_yticks(yticks)
    ax2.set_yticklabels(
        [str(int(t)) if t >= 0 and t == int(t) else "" for t in yticks],
        fontsize=9, color="#3344cc",
    )
    ax2.set_ylabel("Сообщения", fontsize=9, color="#3344cc",
                   rotation=90, labelpad=8)
    ax2.tick_params(axis="y", colors="#3344cc", right=True, width=0.5)
    ax2.spines["right"].set_color("#3344cc")
    ax2.spines["right"].set_linewidth(0.8)

    # ── Grid ──────────────────────────────────────────────
    ax.yaxis.grid(True, color="#cccccc", linestyle="-",
                  linewidth=0.5, zorder=0)
    ax.set_axisbelow(True)

    # ── Spines: hide all except right (handled by ax2) ───
    for sp in ("top", "right", "left", "bottom"):
        ax.spines[sp].set_visible(False)
    ax2.spines["top"].set_visible(False)
    ax2.spines["left"].set_visible(False)
    ax2.spines["bottom"].set_visible(False)

    # ── Title + legend ────────────────────────────────────
    ax.set_title("Статистика активности", fontsize=13,
                 color="#333333", pad=10)
    ax.legend(loc="upper right", fontsize=9,
              framealpha=0.7, frameon=True)

    plt.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="PNG", dpi=130, bbox_inches="tight",
                facecolor="#f4f4f4", edgecolor="none")
    plt.close(fig)
    buf.seek(0)
    return buf.read()


@only_groups
async def cmd_activity(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send the group's activity chart (messages + games per day)."""
    cid  = update.effective_chat.id
    days = 30
    if context.args:
        try:
            days = min(90, max(7, int(context.args[0])))
        except ValueError:
            pass

    rows = await db_get_activity(cid, days)
    if not rows:
        await update.message.reply_text(
            "📊 <b>Данных пока нет</b>\n\nАктивность начнёт отслеживаться с этого момента.",
            parse_mode=ParseMode.HTML,
        )
        return

    loop      = asyncio.get_event_loop()
    img_bytes = await loop.run_in_executor(None, _activity_chart_sync, list(rows))

    if img_bytes is None:
        await update.message.reply_text(
            "❌ Установи matplotlib:\n<code>pip install matplotlib</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    total_msgs  = sum(r[1] for r in rows)
    total_games = sum(r[2] for r in rows)
    await context.bot.send_photo(
        chat_id=cid,
        photo=io.BytesIO(img_bytes),
        caption=(
            f"📈 <b>Активность чата — последние {days} дн.</b>\n\n"
            f"💬 Сообщений: <b>{fmt(total_msgs)}</b>\n"
            f"🎮 Игр сыграно: <b>{fmt(total_games)}</b>"
        ),
        parse_mode=ParseMode.HTML,
    )


# ══════════════════════════════════════════════════════
#           INLINE QUERY HANDLER 🔍
# ══════════════════════════════════════════════════════

async def on_inline_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle @BotName queries from any chat."""
    query   = update.inline_query
    uid     = query.from_user.id
    q_text  = (query.query or "").strip().lower()

    # Try to fetch the user's data from any chat they've played in
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM users WHERE user_id=? ORDER BY vrf DESC LIMIT 1", (uid,)
        ) as cur:
            row = await cur.fetchone()
    u_data = dict(row) if row else None

    results = []

    # ── Referral card ────────────────────────────────
    bot_info     = await context.bot.get_me()
    ref_link     = f"https://t.me/{bot_info.username}?start=ref_{uid}"
    ref_count    = (u_data.get("referral_count") or 0) if u_data else 0

    ref_article = InlineQueryResultArticle(
        id="ref",
        title="🔗 Моя реферальная ссылка",
        description=f"Пригласи друга — получи {REFERRAL_BONUS_INVITER} VRF",
        input_message_content=InputTextMessageContent(
            f"🎮 <b>Играй в Verifure Game!</b>\n\n"
            f"💎 Стартовый баланс {STARTING_VRF} VRF · Мины · Морской бой · Дуэли\n\n"
            f"🔗 Моя реферальная ссылка:\n{ref_link}",
            parse_mode=ParseMode.HTML,
        ),
    )
    results.append(ref_article)

    # ── Profile card ─────────────────────────────────
    if u_data:
        lvl     = get_level(u_data["experience"])
        rank_nm = get_rank(lvl)
        wr      = round(u_data["wins"] / max(1, u_data["total_games"]) * 100, 1)
        profile_article = InlineQueryResultArticle(
            id="profile",
            title=f"👤 Мой профиль — {fmt(u_data['vrf'])} VRF",
            description=f"Уровень {lvl} · {rank_nm} · {u_data['wins']} побед · W/R {wr}%",
            input_message_content=InputTextMessageContent(
                f"👤 <b>Мой профиль в Verifure Game</b>\n\n"
                f"💎 VRF: <b>{fmt(u_data['vrf'])}</b>\n"
                f"🏅 Уровень: <b>{lvl}</b> — {rank_nm}\n"
                f"🏆 Побед: <b>{u_data['wins']}</b>  ·  "
                f"🎮 Игр: <b>{u_data['total_games']}</b>  ·  "
                f"W/R: <b>{wr}%</b>\n"
                f"🔥 Стрик: <b>{u_data.get('win_streak', 0)}</b>  ·  "
                f"🐻 Медведей: <b>{u_data.get('bears', 0)}</b>\n\n"
                f"🎮 <b>Играй со мной!</b> {ref_link}",
                parse_mode=ParseMode.HTML,
            ),
        )
        results.insert(0, profile_article)

    # ── Game invite card ──────────────────────────────
    invite_article = InlineQueryResultArticle(
        id="invite",
        title="⚔️ Вызвать на дуэль / игру",
        description="Отправить вызов в любой чат",
        input_message_content=InputTextMessageContent(
            f"⚔️ <b>Вызываю на игру в Verifure Game!</b>\n\n"
            f"💎 Дуэли · 🎲 Кубики · 🎰 Слот · 💣 Мины · 🚢 Морской Бой\n\n"
            f"👉 Добавь бота в чат и используй /duel /slot /tictac /seabattle\n"
            f"🔗 {ref_link}",
            parse_mode=ParseMode.HTML,
        ),
    )
    results.append(invite_article)

    await query.answer(results, cache_time=30, is_personal=True)


# ══════════════════════════════════════════════════════
#           PROFILE & LEADERBOARD
# ══════════════════════════════════════════════════════

@only_groups
async def cmd_profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message.reply_to_message and not update.message.reply_to_message.from_user.is_bot:
        target = update.message.reply_to_message.from_user
    else:
        target = update.effective_user

    cid = update.effective_chat.id
    await db_ensure_user(target.id, cid, target.username or "", target.first_name)
    u = await db_get_user(target.id, cid)
    if not u:
        return

    lvl, _, _, pct = get_progress(u["experience"])
    bar     = xp_bar(u["experience"])
    rank_nm = get_rank(lvl)
    pos     = await db_rank_pos(target.id, cid)
    wr      = round(u["wins"] / max(1, u["total_games"]) * 100, 1)

    m = await db_get_marriage(target.id, cid)
    if m:
        pid   = partner_id(m, target.id)
        pu    = await db_get_user(pid, cid)
        pname = pu["first_name"] if pu else "Партнёр"
        d     = days_ago(m["married_at"])
        m_line = f"💍 {mention(pid, pname)} · {d} дн."
    else:
        m_line = "💔 Свободен(а)"

    uname = f"@{u['username']}" if u["username"] else u["first_name"]
    bars  = xp_bar(u["experience"], 14)

    # ── Rich profile card ────────────────────────────
    rich_h = (
        f"<h2>👤 {uname}</h2>"
        "<table bordered striped>"
        f"<tr><td>🏅 Уровень</td><td><b>{lvl}</b> &mdash; {rank_nm}</td></tr>"
        f"<tr><td>📊 Прогресс</td><td><code>{bars}</code> {int(pct*100)}%</td></tr>"
        f"<tr><td>💎 VRF</td><td><mark><b>{fmt(u['vrf'])}</b></mark></td></tr>"
        f"<tr><td>🏆 Место</td><td><b>#{pos}</b></td></tr>"
        f"<tr><td>🎮 Всего игр</td><td><b>{u['total_games']}</b></td></tr>"
        f"<tr><td>✅ Побед</td><td><b>{u['wins']}</b> ({wr}%)</td></tr>"
        f"<tr><td>❌ Поражений</td><td><b>{u['losses']}</b></td></tr>"
        f"<tr><td>🔥 Серия</td><td><b>{u['win_streak']}</b> (макс. {u['max_streak']})</td></tr>"
        f"<tr><td>🐻 Медведей</td><td><b>{u['bears']}</b></td></tr>"
        "</table>"
        f"<blockquote>{m_line}</blockquote>"
    )
    fb_h = (
        f"👤 <b>{mention(target.id, u['first_name'])}</b>\n\n"
        f"🏅 Ур. <b>{lvl}</b> — {rank_nm}  📊 [{bars}] {int(pct*100)}%\n"
        f"💎 VRF: <b>{fmt(u['vrf'])}</b>  🏆 <b>#{pos}</b>\n\n"
        f"🎮 Игр: <b>{u['total_games']}</b>  ✅ <b>{u['wins']}</b> ({wr}%)  ❌ <b>{u['losses']}</b>\n"
        f"🔥 Серия: <b>{u['win_streak']}</b> (макс. {u['max_streak']})  🐻 <b>{u['bears']}</b>\n\n"
        f"{m_line}"
    )
    await send_rich(context.bot, update.effective_chat.id, html=rich_h, fallback_html=fb_h,
                    reply_to_id=update.message.message_id)


@only_groups
async def cmd_top(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cid = update.effective_chat.id
    await _show_top(update, context, cid, "vrf")


async def _show_top(update_or_query, context, cid: int, sort: str, edit: bool = False) -> None:
    users  = await db_top(cid, sort, 10)
    titles = {"vrf": "💎 VRF", "level": "⭐ Уровень", "wins": "🏆 Победы"}
    title  = titles.get(sort, "VRF")

    kb = InlineKeyboardMarkup([[
        SBtn("💎 VRF",    style="primary", callback_data=f"top:vrf:{cid}"),
        SBtn("⭐ Уровень", style="primary", callback_data=f"top:level:{cid}"),
        SBtn("🏆 Победы", style="primary", callback_data=f"top:wins:{cid}"),
    ]])

    col_hdr = {"vrf": "VRF", "level": "Уровень / XP", "wins": "Побед"}.get(sort, "VRF")

    rich_rows = [
        f"<h2>🏆 Топ-10 &mdash; {title}</h2>",
        f"<table bordered striped>",
        f"<tr><th>#</th><th>Игрок</th><th align=\"right\">{col_hdr}</th></tr>",
    ]
    fb_rows = [f"🏆 <b>Топ-10 — {title}</b>\n"]

    for i, u in enumerate(users):
        lvl   = get_level(u["experience"])
        medal = MEDALS[i] if i < len(MEDALS) else f"{i+1}."
        name  = u["first_name"]
        uid   = u["user_id"]
        is_top3 = i < 3
        b_s = "<b>" if is_top3 else ""
        b_e = "</b>" if is_top3 else ""
        if sort == "wins":
            val_rich = f"{b_s}{u['wins']} побед{b_e}"
            val_fb   = f"{u['wins']} побед"
        elif sort == "level":
            val_rich = f"{b_s}Ур.{lvl}{b_e}"
            val_fb   = f"Ур.<b>{lvl}</b>"
        else:
            val_rich = f"{b_s}{fmt(u['vrf'])} VRF{b_e}"
            val_fb   = f"{fmt(u['vrf'])} VRF"
        mark_s = "<mark>" if i == 0 else ""
        mark_e = "</mark>" if i == 0 else ""
        rich_rows.append(
            f"<tr><td>{medal}</td><td>{b_s}{name}{b_e}</td>"
            f"<td align=\"right\">{mark_s}{val_rich}{mark_e}</td></tr>"
        )
        fb_rows.append(f"{medal} {mention(uid, name)} — {val_fb}")

    rich_rows.append("</table>")
    rich_h = "".join(rich_rows)
    fb_h   = "\n".join(fb_rows)

    if edit:
        await update_or_query.edit_message_text(fb_h, parse_mode=ParseMode.HTML, reply_markup=kb)
    else:
        await send_rich(context.bot, cid, html=rich_h, fallback_html=fb_h,
                        reply_to_id=update_or_query.message.message_id, reply_markup=kb)


@only_groups
async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cid   = update.effective_chat.id
    total = await db_count_users(cid)

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM marriages WHERE chat_id=?", (cid,)) as cur:
            marriages = (await cur.fetchone())[0]
        async with db.execute("SELECT SUM(total_games) FROM users WHERE chat_id=?", (cid,)) as cur:
            total_games = (await cur.fetchone())[0] or 0
        async with db.execute("SELECT SUM(vrf) FROM users WHERE chat_id=?", (cid,)) as cur:
            total_vrf = (await cur.fetchone())[0] or 0

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM users WHERE chat_id=? ORDER BY vrf DESC LIMIT 1", (cid,)
        ) as cur:
            richest = await cur.fetchone()
            richest = dict(richest) if richest else None

    rich_line = ""
    if richest:
        rich_line = (
            f"\n\n💰 <b>Богатейший:</b>\n"
            f"{mention(richest['user_id'], richest['first_name'])} — {fmt(richest['vrf'])} VRF"
        )

    chat_title = update.effective_chat.title or "Чат"
    rich_name  = richest["first_name"] if richest else "—"
    rich_vrf   = fmt(richest["vrf"]) if richest else "—"

    rich_h = (
        f"<h2>📊 Статистика чата</h2>"
        f"<p>💬 <b>{chat_title}</b></p>"
        "<table bordered striped>"
        f"<tr><td>👥 Игроков</td><td align=\"right\"><b>{total}</b></td></tr>"
        f"<tr><td>🎮 Сыграно игр</td><td align=\"right\"><b>{fmt(total_games)}</b></td></tr>"
        f"<tr><td>💎 VRF в обороте</td><td align=\"right\"><mark><b>{fmt(total_vrf)}</b></mark></td></tr>"
        f"<tr><td>💒 Браков</td><td align=\"right\"><b>{marriages}</b></td></tr>"
        f"<tr><td>👑 Богатейший</td><td align=\"right\"><b>{rich_name}</b> &mdash; {rich_vrf} VRF</td></tr>"
        "</table>"
    )
    fb_h = (
        f"📊 <b>Статистика чата — {chat_title}</b>\n\n"
        f"👥 Игроков: <b>{total}</b>\n"
        f"🎮 Сыграно: <b>{fmt(total_games)}</b>\n"
        f"💎 VRF в обороте: <b>{fmt(total_vrf)}</b>\n"
        f"💒 Браков: <b>{marriages}</b>"
        f"{rich_line}"
    )
    await send_rich(context.bot, update.effective_chat.id, html=rich_h, fallback_html=fb_h,
                    reply_to_id=update.message.message_id)


# ══════════════════════════════════════════════════════
#          DAILY / GIFT / LOVE / BONUS
# ══════════════════════════════════════════════════════

@only_groups
async def cmd_daily(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    u_obj = update.effective_user
    cid   = update.effective_chat.id
    await db_ensure_user(u_obj.id, cid, u_obj.username or "", u_obj.first_name)
    u     = await db_get_user(u_obj.id, cid)
    now   = datetime.now()
    cd    = 20 * 3600  # 20-hour cooldown

    # ── Cooldown check ────────────────────────────────────
    if u["last_daily"]:
        elapsed = (now - datetime.fromisoformat(u["last_daily"])).total_seconds()
        if elapsed < cd:
            rem = int(cd - elapsed)

            # ── Bio-bonus: can be used ONCE per cooldown period ─
            bio_bonus_used = False
            lbb = u.get("last_bio_bonus")
            if lbb:
                bio_elapsed = (now - datetime.fromisoformat(lbb)).total_seconds()
                bio_bonus_used = bio_elapsed < cd

            if bio_bonus_used:
                # Already used bio bypass this period
                await update.message.reply_text(
                    f"⏰ Следующий бонус через <b>{fmt_cd(rem)}</b>\n\n"
                    f"✅ Промо-бонус за <code>@VerifureGift</code> уже получен сегодня.",
                    parse_mode=ParseMode.HTML,
                )
                return

            # ── Check Telegram bio ──────────────────────────
            has_promo = False
            try:
                user_chat = await context.bot.get_chat(u_obj.id)
                bio = (user_chat.bio or "")
                has_promo = "@VerifureGift" in bio
            except TelegramError:
                pass  # Can't read bio — user hasn't started bot in DM

            if not has_promo:
                await update.message.reply_text(
                    f"⏰ Следующий бонус через <b>{fmt_cd(rem)}</b>\n\n"
                    f"💡 <b>Хочешь получить бонус прямо сейчас?</b>\n"
                    f"Добавь <code>@VerifureGift</code> в описание своего профиля Telegram "
                    f"и используй <b>/daily</b> снова — получишь бонус немедленно! 🎁",
                    parse_mode=ParseMode.HTML,
                )
                return

            # ── Bio found → give promo bonus ────────────────
            streak      = u.get("daily_streak") or 0
            streak_bonus = min(max(streak - 1, 0), 6) * DAILY_STREAK_BONUS
            m           = await db_get_marriage(u_obj.id, cid)
            marry_bonus  = DAILY_MARRIED_BONUS if m else 0
            promo_total  = DAILY_BONUS_BASE + streak_bonus + marry_bonus

            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    "UPDATE users SET last_bio_bonus=? WHERE user_id=? AND chat_id=?",
                    (_now(), u_obj.id, cid),
                )
                await db.commit()

            new_bal = await db_add_vrf(u_obj.id, cid, promo_total)

            rich_promo = (
                "<h2>🎁 Промо-бонус!</h2>"
                "<table bordered striped>"
                f"<tr><td>✅ <code>@VerifureGift</code></td><td align=\"right\">в профиле!</td></tr>"
                f"<tr><td>💎 База</td><td align=\"right\"><b>+{DAILY_BONUS_BASE} VRF</b></td></tr>"
            )
            if streak_bonus:
                rich_promo += f"<tr><td>🔥 Стрик {streak} дн.</td><td align=\"right\"><b>+{streak_bonus} VRF</b></td></tr>"
            if marry_bonus:
                rich_promo += f"<tr><td>💍 Бонус брака</td><td align=\"right\"><b>+{marry_bonus} VRF</b></td></tr>"
            rich_promo += (
                f"<tr><th>Итого</th><th align=\"right\"><mark><b>+{promo_total} VRF</b></mark></th></tr>"
                "</table>"
                f"<blockquote>💰 Баланс: <b>{fmt(new_bal)} VRF</b></blockquote>"
                f"<p>⏰ Следующий обычный бонус через <b>{fmt_cd(rem)}</b></p>"
            )
            fb_promo = (
                f"🎁 <b>Промо-бонус!</b>\n\n"
                f"✅ <code>@VerifureGift</code> найден в профиле!\n\n"
                f"💎 +{promo_total} VRF\n"
                f"💰 Баланс: <b>{fmt(new_bal)} VRF</b>\n\n"
                f"⏰ Следующий обычный бонус через <b>{fmt_cd(rem)}</b>"
            )
            await send_rich(context.bot, cid, html=rich_promo, fallback_html=fb_promo,
                            reply_to_id=update.message.message_id)
            return

    # ══════════════════════════════════════════════════════
    #  Normal daily bonus (cooldown passed)
    # ══════════════════════════════════════════════════════
    streak = u.get("daily_streak") or 0
    last_streak = u.get("last_daily")
    if last_streak:
        diff   = (now.date() - datetime.fromisoformat(last_streak).date()).days
        streak = streak + 1 if diff == 1 else 1
    else:
        streak = 1

    streak_bonus = min(streak - 1, 6) * DAILY_STREAK_BONUS
    m = await db_get_marriage(u_obj.id, cid)
    marry_bonus  = DAILY_MARRIED_BONUS if m else 0
    total        = DAILY_BONUS_BASE + streak_bonus + marry_bonus

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET last_daily=?, daily_streak=? WHERE user_id=? AND chat_id=?",
            (_now(), streak, u_obj.id, cid),
        )
        await db.commit()

    new_bal = await db_add_vrf(u_obj.id, cid, total)
    new_lvl, leveled_up = await db_add_xp(u_obj.id, cid, XP_PER_GAME)

    streak_bar = "🔥" * min(streak, 7) + "⬜" * (7 - min(streak, 7))

    rich_rows = [
        "<h2>⭐ Ежедневный бонус!</h2>",
        "<table bordered striped>",
        f"<tr><td>💎 База</td><td align=\"right\"><b>+{DAILY_BONUS_BASE} VRF</b></td></tr>",
    ]
    if streak_bonus:
        rich_rows.append(f"<tr><td>🔥 Стрик {streak} дн.</td><td align=\"right\"><b>+{streak_bonus} VRF</b></td></tr>")
    if marry_bonus:
        rich_rows.append(f"<tr><td>💍 Бонус брака</td><td align=\"right\"><b>+{marry_bonus} VRF</b></td></tr>")
    rich_rows.append(f"<tr><th>Итого</th><th align=\"right\"><mark><b>+{total} VRF</b></mark></th></tr>")
    rich_rows.append("</table>")
    rich_rows.append(f"<blockquote>💰 Баланс: <b>{fmt(new_bal)} VRF</b></blockquote>")
    rich_rows.append(f"<p>📅 Стрик: {streak_bar} <b>{streak}/7</b> дн.</p>")
    if leveled_up:
        rich_rows.append(f"<p>🎉 <b>Новый уровень: {new_lvl}!</b> {get_rank(new_lvl)}</p>")

    fb_parts = [f"⚡ <b>Ежедневный бонус!</b>\n\n├ База: +{DAILY_BONUS_BASE} VRF"]
    if streak_bonus:
        fb_parts.append(f"\n├ 🔥 Стрик {streak} дн.: +{streak_bonus} VRF")
    if marry_bonus:
        fb_parts.append(f"\n├ 💍 Бонус брака: +{marry_bonus} VRF")
    fb_parts.append(f"\n└ Итого: <b>+{total} VRF</b>\n\n💎 Баланс: <b>{fmt(new_bal)} VRF</b>")
    if leveled_up:
        fb_parts.append(f"\n🎉 Новый уровень: <b>{new_lvl}!</b> {get_rank(new_lvl)}")

    await send_rich(context.bot, update.effective_chat.id,
                    html="".join(rich_rows), fallback_html="".join(fb_parts),
                    reply_to_id=update.message.message_id)


@only_groups
async def cmd_bonus(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    u_obj = update.effective_user
    cid   = update.effective_chat.id
    await db_ensure_user(u_obj.id, cid, u_obj.username or "", u_obj.first_name)
    u = await db_get_user(u_obj.id, cid)

    daily_txt = "✅ Доступен"
    if u["last_daily"]:
        elapsed = (datetime.now() - datetime.fromisoformat(u["last_daily"])).total_seconds()
        rem = int(20 * 3600 - elapsed)
        if rem > 0:
            daily_txt = f"⏰ {fmt_cd(rem)}"

    def cd_txt(last_field: str, secs: int) -> str:
        last = u.get(last_field)
        if not last:
            return "✅ Доступен"
        rem = int(secs - (datetime.now() - datetime.fromisoformat(last)).total_seconds())
        return f"⏰ {fmt_cd(rem)}" if rem > 0 else "✅ Доступен"

    bio_bonus_txt = cd_txt("last_bio_bonus", 20 * 3600)
    m = await db_get_marriage(u_obj.id, cid)

    rich_h = (
        f"<h2>🎁 Бонусы</h2>"
        f"<p>{mention(u_obj.id, u_obj.first_name)}</p>"
        "<table bordered striped>"
        f"<tr><td>💎 VRF</td><td align=\"right\"><mark><b>{fmt(u['vrf'])}</b></mark></td></tr>"
        f"<tr><td>📅 Ежедневный</td><td align=\"right\">{daily_txt}</td></tr>"
        f"<tr><td>🎁 Промо @VerifureGift</td><td align=\"right\">{bio_bonus_txt}</td></tr>"
        f"<tr><td>🔥 Стрик</td><td align=\"right\"><b>{u.get('daily_streak', 0)}</b> дн.</td></tr>"
        f"<tr><td>💑 Брак</td><td align=\"right\">{'✅ +15 VRF' if m else '❌ Нет'}</td></tr>"
        f"<tr><td>🎁 Подарок /gift</td><td align=\"right\">{cd_txt('last_gift', GIFT_COOLDOWN_H * 3600)}</td></tr>"
        f"<tr><td>💕 Любовь /love</td><td align=\"right\">{cd_txt('last_love', LOVE_COOLDOWN_M * 60)}</td></tr>"
        f"<tr><td>🐻 Медведей</td><td align=\"right\"><b>{u['bears']}</b></td></tr>"
        f"<tr><td>🏆 Побед</td><td align=\"right\"><b>{u['wins']}</b></td></tr>"
        f"<tr><td>🎮 Всего игр</td><td align=\"right\"><b>{u['total_games']}</b></td></tr>"
        "</table>"
    )
    fb_h = (
        f"🎁 <b>Бонусы: {mention(u_obj.id, u_obj.first_name)}</b>\n\n"
        f"💎 VRF: <b>{fmt(u['vrf'])}</b>\n\n"
        f"📅 Ежедневный: {daily_txt}\n"
        f"🎁 Промо @VerifureGift: {bio_bonus_txt}\n"
        f"🔥 Стрик: {u.get('daily_streak', 0)} дн.\n"
        f"💑 Брак: {'✅ +15 VRF к бонусу' if m else '❌ Нет'}\n"
        f"🎀 Подарок /gift: {cd_txt('last_gift', GIFT_COOLDOWN_H * 3600)}\n"
        f"💕 Любовь /love: {cd_txt('last_love', LOVE_COOLDOWN_M * 60)}\n\n"
        f"🐻 Медведей: <b>{u['bears']}</b>\n"
        f"🏆 Побед: <b>{u['wins']}</b> · 🎮 Игр: <b>{u['total_games']}</b>"
    )
    await send_rich(context.bot, cid, html=rich_h, fallback_html=fb_h,
                    reply_to_id=update.message.message_id)


@only_groups
async def cmd_gift(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    sender = update.effective_user
    cid    = update.effective_chat.id

    if not update.message.reply_to_message or update.message.reply_to_message.from_user.is_bot:
        await update.message.reply_text("❌ Ответь на сообщение получателя!")
        return

    target = update.message.reply_to_message.from_user
    if target.id == sender.id:
        await update.message.reply_text("🎁 Нельзя дарить себе!")
        return

    await db_ensure_user(sender.id, cid, sender.username or "", sender.first_name)
    await db_ensure_user(target.id, cid, target.username or "", target.first_name)

    su = await db_get_user(sender.id, cid)
    if su["vrf"] < GIFT_COST:
        await update.message.reply_text(
            f"❌ Нужно {GIFT_COST} VRF · Есть: {su['vrf']} VRF"
        )
        return

    last_gift = su.get("last_gift")
    if last_gift:
        elapsed = (datetime.now() - datetime.fromisoformat(last_gift)).total_seconds()
        if elapsed < GIFT_COOLDOWN_H * 3600:
            rem = int(GIFT_COOLDOWN_H * 3600 - elapsed)
            await update.message.reply_text(f"⏰ Следующий подарок через {fmt_cd(rem)}")
            return

    m       = await db_get_marriage(sender.id, cid)
    reward  = GIFT_MARRIED_REWARD if (m and partner_id(m, sender.id) == target.id) else GIFT_REWARD

    if not await db_deduct_vrf(sender.id, cid, GIFT_COST):
        await update.message.reply_text("❌ Недостаточно VRF")
        return

    new_bal = await db_add_vrf(target.id, cid, reward)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET last_gift=? WHERE user_id=? AND chat_id=?",
                         (_now(), sender.id, cid))
        await db.commit()

    partner_mark = " 💍 (бонус партнёра)" if reward == GIFT_MARRIED_REWARD else ""
    await update.message.reply_text(
        f"🎁 {mention(sender.id, sender.first_name)} дарит VRF!\n"
        f"→ {mention(target.id, target.first_name)}\n"
        f"💎 +{reward} VRF{partner_mark}\n"
        f"Баланс: {fmt(new_bal)} VRF",
        parse_mode=ParseMode.HTML,
    )


@only_groups
async def cmd_love(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    sender = update.effective_user
    cid    = update.effective_chat.id

    if not update.message.reply_to_message or update.message.reply_to_message.from_user.is_bot:
        await update.message.reply_text("❌ Ответь на сообщение получателя!")
        return

    target = update.message.reply_to_message.from_user
    if target.id == sender.id:
        await update.message.reply_text("💘 Начни любить других, а не только себя!")
        return

    await db_ensure_user(sender.id, cid, sender.username or "", sender.first_name)
    await db_ensure_user(target.id, cid, target.username or "", target.first_name)

    su = await db_get_user(sender.id, cid)
    last_love = su.get("last_love")
    if last_love:
        elapsed = (datetime.now() - datetime.fromisoformat(last_love)).total_seconds()
        if elapsed < LOVE_COOLDOWN_M * 60:
            rem = int(LOVE_COOLDOWN_M * 60 - elapsed)
            await update.message.reply_text(f"⏰ Любовь можно слать через {fmt_cd(rem)}")
            return

    m           = await db_get_marriage(sender.id, cid)
    is_partner  = m and partner_id(m, sender.id) == target.id
    s_reward    = LOVE_MARRIED_REWARD if is_partner else LOVE_REWARD
    r_reward    = LOVE_MARRIED_REWARD if is_partner else LOVE_REWARD

    await db_add_vrf(sender.id, cid, s_reward)
    new_bal = await db_add_vrf(target.id, cid, r_reward)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET last_love=? WHERE user_id=? AND chat_id=?",
                         (_now(), sender.id, cid))
        await db.commit()

    actions = ["шлёт поцелуй 💋", "обнимает 🤗", "дарит цветок 🌸", "признаётся в любви 💌"]
    if is_partner:
        actions = ["целует свою половинку 💋", "обнимает любимого(ую) 🤗", "дарит красную розу 🌹"]

    await update.message.reply_text(
        f"{E_LOVE} {mention(sender.id, sender.first_name)} {random.choice(actions)}\n"
        f"→ {mention(target.id, target.first_name)}\n"
        f"💎 Оба получают +{r_reward} VRF"
        + (" 💍" if is_partner else ""),
        parse_mode=ParseMode.HTML,
    )
    await _react(update, "❤️")


# ══════════════════════════════════════════════════════
#                MARRIAGE COMMANDS
# ══════════════════════════════════════════════════════

@only_groups
async def cmd_marry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    proposer = update.effective_user
    cid      = update.effective_chat.id

    target, err = await _resolve_target(update, context, cid)
    if err:
        await update.message.reply_text(err)
        return
    if not target:
        await update.message.reply_text("❌ Укажи пользователя через ответ или @username")
        return
    if target.id == proposer.id:
        await update.message.reply_text("💘 Жениться на себе нельзя!")
        return
    if await db_get_marriage(proposer.id, cid):
        await update.message.reply_text("💍 Ты уже в браке! Сначала /divorce")
        return
    if await db_get_marriage(target.id, cid):
        await update.message.reply_text(
            f"💔 {mention(target.id, target.first_name)} уже в браке!",
            parse_mode=ParseMode.HTML,
        )
        return

    await db_ensure_user(proposer.id, cid, proposer.username or "", proposer.first_name)
    await db_ensure_user(target.id, cid, getattr(target, "username", "") or "", target.first_name)

    prop = await db_get_proposal_to(proposer.id, cid)
    if prop and prop["proposer_id"] == target.id:
        await db_create_marriage(proposer.id, target.id, cid)
        await update.message.reply_text(
            f"{E_RING} <b>Взаимная любовь — Свадьба!</b>\n\n"
            f"💑 {mention(proposer.id, proposer.first_name)} ❤️ "
            f"{mention(target.id, target.first_name)}\n\n"
            f"🎊 Поздравляем! Бонус к /daily активирован!",
            parse_mode=ParseMode.HTML,
        )
        await _react(update, "🎊")
        return

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO proposals(proposer_id,target_id,chat_id,created_at) VALUES(?,?,?,?)",
            (proposer.id, target.id, cid, _now()),
        )
        await db.commit()

    phrase = random.choice(["делает предложение", "встаёт на одно колено перед", "хочет связать жизнь с"])
    await update.message.reply_text(
        f"{E_RING} {mention(proposer.id, proposer.first_name)} {phrase} "
        f"{mention(target.id, target.first_name)}!\n\nПримешь предложение?",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[
            SBtn("Да! 💍", style="success", callback_data=f"ma:{proposer.id}:{target.id}"),
            SBtn("Нет 💔", style="danger", callback_data=f"mr:{proposer.id}:{target.id}"),
        ]]),
    )


@only_groups
async def cmd_accept(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    u   = update.effective_user
    cid = update.effective_chat.id
    prop = await db_get_proposal_to(u.id, cid)
    if not prop:
        await update.message.reply_text("❌ У тебя нет входящих предложений")
        return
    if await db_get_marriage(u.id, cid) or await db_get_marriage(prop["proposer_id"], cid):
        await update.message.reply_text("❌ Один из вас уже в браке!")
        return
    pu    = await db_get_user(prop["proposer_id"], cid)
    pname = pu["first_name"] if pu else "Партнёр"
    await db_create_marriage(prop["proposer_id"], u.id, cid)
    await update.message.reply_text(
        f"💒 <b>Поздравляем с бракосочетанием!</b>\n\n"
        f"💑 {mention(prop['proposer_id'], pname)} ❤️ {mention(u.id, u.first_name)}\n\n"
        f"🎊 Бонус к /daily активирован!",
        parse_mode=ParseMode.HTML,
    )
    await _react(update, "🎊")


@only_groups
async def cmd_reject(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    u   = update.effective_user
    cid = update.effective_chat.id
    prop = await db_get_proposal_to(u.id, cid)
    if not prop:
        await update.message.reply_text("❌ У тебя нет входящих предложений")
        return
    pu    = await db_get_user(prop["proposer_id"], cid)
    pname = pu["first_name"] if pu else "Пользователь"
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM proposals WHERE target_id=? AND chat_id=?", (u.id, cid))
        await db.commit()
    await update.message.reply_text(
        f"💔 {mention(u.id, u.first_name)} отклонил(а) предложение от {mention(prop['proposer_id'], pname)}",
        parse_mode=ParseMode.HTML,
    )


@only_groups
async def cmd_divorce(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    u   = update.effective_user
    cid = update.effective_chat.id
    m   = await db_get_marriage(u.id, cid)
    if not m:
        await update.message.reply_text("💔 Ты не в браке")
        return
    pid   = partner_id(m, u.id)
    pu    = await db_get_user(pid, cid)
    pname = pu["first_name"] if pu else "Партнёр"
    d     = days_ago(m["married_at"])
    await db_delete_marriage(m["id"])
    await update.message.reply_text(
        f"💔 <b>Развод оформлен</b>\n\nПосле {d} дней вместе...\n"
        f"{mention(u.id, u.first_name)} и {mention(pid, pname)} расстались.",
        parse_mode=ParseMode.HTML,
    )


@only_groups
async def cmd_marriage(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    u   = update.effective_user
    cid = update.effective_chat.id
    await db_ensure_user(u.id, cid, u.username or "", u.first_name)
    m = await db_get_marriage(u.id, cid)
    if not m:
        prop = await db_get_proposal_to(u.id, cid)
        if prop:
            pu    = await db_get_user(prop["proposer_id"], cid)
            pname = pu["first_name"] if pu else "Кто-то"
            await update.message.reply_text(
                f"{E_RING} Предложение от {mention(prop['proposer_id'], pname)}!\n"
                f"💍 /accept — принять · 💔 /reject — отклонить",
                parse_mode=ParseMode.HTML,
            )
        else:
            await update.message.reply_text("💔 Ты не в браке.\n\n/marry @username — найди пару!")
        return
    pid   = partner_id(m, u.id)
    pu    = await db_get_user(pid, cid)
    pname = pu["first_name"] if pu else "Партнёр"
    since = datetime.fromisoformat(m["married_at"])
    delta = datetime.now() - since
    await update.message.reply_text(
        f"💑 <b>Ваш брак</b>\n\n"
        f"  {mention(u.id, u.first_name)}\n  ❤️\n  {mention(pid, pname)}\n\n"
        f"⏰ Вместе: <b>{delta.days} дн. {delta.seconds//3600} ч.</b>\n"
        f"📅 С: <b>{since.strftime('%d.%m.%Y')}</b>\n\n"
        f"🎁 Бонус: +{DAILY_MARRIED_BONUS} VRF к /daily",
        parse_mode=ParseMode.HTML,
    )


@only_groups
async def cmd_marriages(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cid   = update.effective_chat.id
    all_m = await db_all_marriages(cid)
    if not all_m:
        await update.message.reply_text("💔 В чате пока нет пар.\n\n/marry — найди свою половинку!")
        return
    lines = [f"💑 <b>Пары чата ({len(all_m)})</b>\n"]
    shown = 0
    for m in all_m:
        u1 = await db_get_user(m["user1_id"], cid)
        u2 = await db_get_user(m["user2_id"], cid)
        if not u1 or not u2:
            continue
        shown += 1
        lines.append(
            f"{shown}. {mention(m['user1_id'], u1['first_name'])} ❤️ "
            f"{mention(m['user2_id'], u2['first_name'])} · {days_ago(m['married_at'])} дн."
        )
        if shown >= 15:
            break
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


# ══════════════════════════════════════════════════════
#                  DUEL GAME ⚔️
# ══════════════════════════════════════════════════════

@only_groups
async def cmd_duel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    challenger = update.effective_user
    cid        = update.effective_chat.id

    if not update.message.reply_to_message or update.message.reply_to_message.from_user.is_bot:
        await update.message.reply_text("⚔️ Ответь на сообщение соперника чтобы вызвать на дуэль!")
        return

    opponent = update.message.reply_to_message.from_user
    if opponent.id == challenger.id:
        await update.message.reply_text("⚔️ Нельзя вызвать самого себя!")
        return

    await db_ensure_user(challenger.id, cid, challenger.username or "", challenger.first_name)
    await db_ensure_user(opponent.id,   cid, opponent.username   or "", opponent.first_name)
    cu = await db_get_user(challenger.id, cid)
    ou = await db_get_user(opponent.id,   cid)

    bet = calc_bet(cu["vrf"], ou["vrf"])
    if cu["vrf"] < bet or ou["vrf"] < MIN_BET:
        await update.message.reply_text(f"❌ Недостаточно VRF для дуэли!\nМинимум: {MIN_BET} VRF")
        return

    key = f"{cid}:{challenger.id}:{opponent.id}"
    duel_challenges[key] = {
        "cid": cid, "c_id": challenger.id, "c_name": challenger.first_name,
        "o_id": opponent.id, "o_name": opponent.first_name, "bet": bet,
    }

    await update.message.reply_text(
        f"⚔️ <b>ВЫЗОВ НА ДУЭЛЬ!</b>\n\n"
        f"{E_ALERT} {mention(challenger.id, challenger.first_name)} вызывает\n"
        f"{mention(opponent.id, opponent.first_name)}!\n\n"
        f"💰 Ставка: <b>{bet} VRF</b>\n"
        f"🎲 Бросок определяется VRF (кости Telegram)\n"
        f"⭐ Бонус уровня добавляется к броску\n\n"
        f"{mention(opponent.id, opponent.first_name)}, принимаешь?",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[
            SBtn("Принять ⚔️", style="success",    callback_data=f"da:{challenger.id}:{opponent.id}"),
            SBtn("Отклонить", style="danger", callback_data=f"dd:{challenger.id}:{opponent.id}"),
        ]]),
    )


async def _run_duel(context: ContextTypes.DEFAULT_TYPE, data: dict) -> None:
    cid   = data["cid"]
    c_id, c_name = data["c_id"], data["c_name"]
    o_id, o_name = data["o_id"], data["o_name"]
    bet   = data["bet"]

    await context.bot.send_message(cid, f"⚔️ Дуэль! 🎲 {mention(c_id, c_name)} бросает...",
                                   parse_mode=ParseMode.HTML)
    await asyncio.sleep(1)
    msg_c = await context.bot.send_dice(chat_id=cid, emoji="🎲")
    c_roll = msg_c.dice.value
    await asyncio.sleep(3)

    await context.bot.send_message(cid, f"🎲 {mention(o_id, o_name)} бросает...",
                                   parse_mode=ParseMode.HTML)
    msg_o = await context.bot.send_dice(chat_id=cid, emoji="🎲")
    o_roll = msg_o.dice.value
    await asyncio.sleep(3)

    cu = await db_get_user(c_id, cid)
    ou = await db_get_user(o_id, cid)
    c_total = c_roll + get_level(cu["experience"] if cu else 0)
    o_total = o_roll + get_level(ou["experience"] if ou else 0)

    if c_total == o_total:
        await context.bot.send_message(
            cid,
            f"🤝 <b>НИЧЬЯ!</b>\n\n"
            f"{mention(c_id, c_name)}: {c_roll} (+ур.) = {c_total}\n"
            f"{mention(o_id, o_name)}: {o_roll} (+ур.) = {o_total}\n\n"
            f"Ставка {bet} VRF возвращена!",
            parse_mode=ParseMode.HTML,
        )
        await db_record_game(c_id, cid, won=False, draw=True)
        await db_record_game(o_id, cid, won=False, draw=True)
        return

    if c_total > o_total:
        w_id, w_name = c_id, c_name
        l_id         = o_id
    else:
        w_id, w_name = o_id, o_name
        l_id         = c_id

    await db_deduct_vrf(l_id, cid, bet)
    new_bal = await db_add_vrf(w_id, cid, bet)
    await db_add_xp(w_id, cid, XP_PER_WIN)
    await db_add_xp(l_id, cid, XP_PER_GAME)
    await db_record_game(w_id, cid, won=True)
    await db_record_game(l_id, cid, won=False)

    c_lvl = get_level(cu["experience"] if cu else 0)
    o_lvl = get_level(ou["experience"] if ou else 0)
    c_win = c_total > o_total
    o_win = o_total > c_total
    rich_h = (
        "<h2>⚔️ Дуэль &mdash; Итог</h2>"
        "<table bordered striped>"
        "<tr><th>Игрок</th><th align=\"center\">🎲</th>"
        "<th align=\"center\">+Ур.</th><th align=\"right\">Итого</th></tr>"
        f"<tr><td>{'<b>' if c_win else ''}{c_name}{'</b>' if c_win else ''}</td>"
        f"<td align=\"center\">{c_roll}</td><td align=\"center\">+{c_lvl}</td>"
        f"<td align=\"right\">{'<mark><b>' if c_win else ''}{c_total}{'</b></mark>' if c_win else ''}</td></tr>"
        f"<tr><td>{'<b>' if o_win else ''}{o_name}{'</b>' if o_win else ''}</td>"
        f"<td align=\"center\">{o_roll}</td><td align=\"center\">+{o_lvl}</td>"
        f"<td align=\"right\">{'<mark><b>' if o_win else ''}{o_total}{'</b></mark>' if o_win else ''}</td></tr>"
        "</table>"
        f"<blockquote>🏆 Победитель: <b>{w_name}</b><br/>"
        f"💎 +{fmt(bet)} VRF &rarr; Баланс: {fmt(new_bal)} VRF</blockquote>"
    )
    fb_h = (
        f"🏆 <b>ПОБЕДИТЕЛЬ!</b>\n\n"
        f"{mention(c_id, c_name)}: {c_roll} + ур. = <b>{c_total}</b>\n"
        f"{mention(o_id, o_name)}: {o_roll} + ур. = <b>{o_total}</b>\n\n"
        f"🥇 {mention(w_id, w_name)} побеждает!\n"
        f"💎 +{bet} VRF → Баланс: {fmt(new_bal)} VRF"
    )
    await send_rich(context.bot, cid, html=rich_h, fallback_html=fb_h)

    # Send message effect DM to winner for big wins
    if bet >= 200:
        try:
            effect = MSG_EFFECT_CONFETTI if bet >= 400 else MSG_EFFECT_STAR
            await context.bot.send_message(
                chat_id=w_id,
                text=f"🏆 <b>Победа в дуэли!</b>\n💎 +{fmt(bet)} VRF",
                parse_mode=ParseMode.HTML,
                message_effect_id=effect,
            )
        except TelegramError:
            pass
# ══════════════════════════════════════════════════════

@only_groups
async def cmd_cubes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    host = update.effective_user
    cid  = update.effective_chat.id

    if not update.message.reply_to_message or update.message.reply_to_message.from_user.is_bot:
        await update.message.reply_text("🎲 Ответь на сообщение соперника!")
        return
    opponent = update.message.reply_to_message.from_user
    if opponent.id == host.id:
        await update.message.reply_text("❌ Нельзя играть с собой!")
        return

    rounds = DEFAULT_ROUNDS
    bet    = 50
    try:
        if context.args and len(context.args) >= 1:
            rounds = max(1, min(int(context.args[0]), MAX_ROUNDS))
        if context.args and len(context.args) >= 2:
            bet = max(MIN_BET, min(int(context.args[1]), MAX_BET))
    except ValueError:
        await update.message.reply_text("❌ Использование: /cubes [раунды 1-10] [ставка 10-500]")
        return

    await db_ensure_user(host.id,     cid, host.username     or "", host.first_name)
    await db_ensure_user(opponent.id, cid, opponent.username or "", opponent.first_name)
    hu = await db_get_user(host.id, cid)
    if hu["vrf"] < bet:
        await update.message.reply_text(f"❌ Нужно {bet} VRF · Есть: {hu['vrf']} VRF")
        return

    game_id = str(uuid.uuid4())[:8]
    cubes_games[game_id] = {
        "host_id": host.id, "host_name": host.first_name,
        "opp_id": opponent.id, "opp_name": opponent.first_name,
        "cid": cid, "rounds": rounds, "bet": bet, "state": "waiting",
    }

    kb = InlineKeyboardMarkup([[
        SBtn(f"Принять 🎲 {bet} VRF", style="success", callback_data=f"cj:{game_id}"),
        SBtn("Отказать", style="danger", callback_data=f"cd:{game_id}"),
    ]])

    msg = await update.message.reply_text(
        f"🎲 <b>Игра в кости!</b>\n\n"
        f"🤺 {mention(host.id, host.first_name)} вызывает\n"
        f"{mention(opponent.id, opponent.first_name)}\n\n"
        f"📊 Раундов: <b>{rounds}</b>\n"
        f"💎 Ставка: <b>{bet} VRF</b> с каждого\n"
        f"🏆 Победитель забирает: <b>{bet*2} VRF</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=kb,
    )

    bot = context.bot
    mid = msg.message_id

    async def auto_cancel():
        await asyncio.sleep(JOIN_TIMEOUT)
        if game_id in cubes_games and cubes_games[game_id]["state"] == "waiting":
            del cubes_games[game_id]
            try:
                await bot.edit_message_reply_markup(cid, mid, reply_markup=None)
                await bot.send_message(cid, "⏰ Игра в кости истекла.")
            except TelegramError:
                pass

    context.application.create_task(auto_cancel())


async def _run_cubes(context: ContextTypes.DEFAULT_TYPE, game: dict) -> None:
    cid    = game["cid"]
    h_id, h_name = game["host_id"], game["host_name"]
    o_id, o_name = game["opp_id"],  game["opp_name"]
    rounds = game["rounds"]
    bet    = game["bet"]
    h_score = o_score = 0

    await context.bot.send_message(
        cid,
        f"🎲 <b>КОСТИ НАЧАЛИСЬ!</b>\n"
        f"{mention(h_id, h_name)} ⚔️ {mention(o_id, o_name)}\n"
        f"Раундов: {rounds} | Ставка: {bet} VRF",
        parse_mode=ParseMode.HTML,
    )
    await asyncio.sleep(2)

    for r in range(1, rounds + 1):
        await context.bot.send_message(cid,
            f"🎲 <b>Раунд {r}/{rounds}</b>\n{mention(h_id, h_name)} бросает...",
            parse_mode=ParseMode.HTML)
        h_val = (await context.bot.send_dice(chat_id=cid, emoji="🎲")).dice.value
        await asyncio.sleep(3)

        await context.bot.send_message(cid,
            f"{mention(o_id, o_name)} бросает...", parse_mode=ParseMode.HTML)
        o_val = (await context.bot.send_dice(chat_id=cid, emoji="🎲")).dice.value
        await asyncio.sleep(3)

        h_score += h_val
        o_score += o_val
        r_res = f"🏅 {mention(h_id, h_name)} берёт раунд!" if h_val > o_val else \
                f"🏅 {mention(o_id, o_name)} берёт раунд!" if o_val > h_val else "🤝 Ничья!"

        await context.bot.send_message(cid,
            f"📊 Раунд {r}: <b>{h_val}</b> vs <b>{o_val}</b>\n"
            f"{r_res}\nСчёт: <b>{h_score} — {o_score}</b>",
            parse_mode=ParseMode.HTML)
        await asyncio.sleep(2)

    if h_score == o_score:
        await db_record_game(h_id, cid, won=False, draw=True)
        await db_record_game(o_id, cid, won=False, draw=True)
        await context.bot.send_message(cid,
            f"🤝 <b>НИЧЬЯ!</b>\nИтог: {h_score} — {o_score}\nСтавки возвращены!",
            parse_mode=ParseMode.HTML)
        return

    w_id, w_name = (h_id, h_name) if h_score > o_score else (o_id, o_name)
    l_id         = o_id if w_id == h_id else h_id

    await db_deduct_vrf(l_id, cid, bet)
    new_bal = await db_add_vrf(w_id, cid, bet)
    await db_add_xp(w_id, cid, XP_PER_WIN)
    await db_add_xp(l_id, cid, XP_PER_GAME)
    await db_record_game(w_id, cid, won=True)
    await db_record_game(l_id, cid, won=False)

    h_win = h_score > o_score
    o_win = o_score > h_score
    cubes_rich = (
        "<h2>🎲 Кубики &mdash; Итог</h2>"
        "<table bordered striped>"
        "<tr><th>Игрок</th><th align=\"right\">Очки</th></tr>"
        f"<tr><td>{'<b>' if h_win else ''}{h_name}{'</b>' if h_win else ''}</td>"
        f"<td align=\"right\">{'<mark><b>' if h_win else ''}{h_score}{'</b></mark>' if h_win else ''}</td></tr>"
        f"<tr><td>{'<b>' if o_win else ''}{o_name}{'</b>' if o_win else ''}</td>"
        f"<td align=\"right\">{'<mark><b>' if o_win else ''}{o_score}{'</b></mark>' if o_win else ''}</td></tr>"
        "</table>"
        f"<blockquote>🏆 <b>{w_name}</b> побеждает!<br/>"
        f"Раундов: {rounds} | 💎 +{fmt(bet)} VRF &rarr; {fmt(new_bal)} VRF</blockquote>"
    )
    cubes_fb = (
        f"🏆 <b>ПОБЕДИТЕЛЬ!</b>\n{mention(w_id, w_name)}\n"
        f"📊 {h_score}:{o_score} | 💎 +{fmt(bet)} VRF"
    )
    await send_rich(context.bot, cid, html=cubes_rich, fallback_html=cubes_fb)


# ══════════════════════════════════════════════════════
#        SPORTS GAMES 🏀⚽🎳🎯 (shared logic)
# ══════════════════════════════════════════════════════

async def _cmd_sport(update: Update, context: ContextTypes.DEFAULT_TYPE, game_type: str) -> None:
    host = update.effective_user
    cid  = update.effective_chat.id

    if not update.message.reply_to_message or update.message.reply_to_message.from_user.is_bot:
        emoji = SPORT_EMOJI[game_type]
        await update.message.reply_text(f"{emoji} Ответь на сообщение соперника!")
        return

    opponent = update.message.reply_to_message.from_user
    if opponent.id == host.id:
        await update.message.reply_text("❌ Нельзя играть с собой!")
        return

    await db_ensure_user(host.id,     cid, host.username     or "", host.first_name)
    await db_ensure_user(opponent.id, cid, opponent.username or "", opponent.first_name)
    hu = await db_get_user(host.id, cid)
    ou = await db_get_user(opponent.id, cid)
    bet = calc_bet(hu["vrf"], ou["vrf"])

    if hu["vrf"] < bet or ou["vrf"] < bet:
        await update.message.reply_text(f"❌ Нужно {bet} VRF у обоих игроков!")
        return

    game_id = str(uuid.uuid4())[:8]
    sports_games[game_id] = {
        "type": game_type,
        "host_id": host.id, "host_name": host.first_name,
        "opp_id": opponent.id, "opp_name": opponent.first_name,
        "cid": cid, "rounds": DEFAULT_ROUNDS, "bet": bet, "state": "waiting",
    }

    emoji = SPORT_EMOJI[game_type]
    name  = SPORT_NAME[game_type]
    msg   = await update.message.reply_text(
        f"{emoji} <b>{name}!</b>\n\n"
        f"🤺 {mention(host.id, host.first_name)} вызывает\n"
        f"{mention(opponent.id, opponent.first_name)}\n\n"
        f"📊 Раундов: <b>{DEFAULT_ROUNDS}</b>\n"
        f"💎 Ставка: <b>{bet} VRF</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[
            SBtn(f"Принять {emoji}", style="success", callback_data=f"sj:{game_id}"),
            SBtn("Отказать", style="danger",       callback_data=f"sd:{game_id}"),
        ]]),
    )

    bot = context.bot
    mid = msg.message_id

    async def auto_cancel():
        await asyncio.sleep(JOIN_TIMEOUT)
        if game_id in sports_games and sports_games[game_id]["state"] == "waiting":
            del sports_games[game_id]
            try:
                await bot.edit_message_reply_markup(cid, mid, reply_markup=None)
                await bot.send_message(cid, f"⏰ Вызов на {name} истёк.")
            except TelegramError:
                pass

    context.application.create_task(auto_cancel())


async def _run_sports(context: ContextTypes.DEFAULT_TYPE, game: dict) -> None:
    cid    = game["cid"]
    gtype  = game["type"]
    h_id, h_name = game["host_id"], game["host_name"]
    o_id, o_name = game["opp_id"],  game["opp_name"]
    rounds = game["rounds"]
    bet    = game["bet"]
    emoji  = SPORT_EMOJI[gtype]
    name   = SPORT_NAME[gtype]

    h_total = o_total = 0

    await context.bot.send_message(
        cid,
        f"{emoji} <b>{name.upper()} НАЧАЛСЯ!</b>\n"
        f"{mention(h_id, h_name)} ⚔️ {mention(o_id, o_name)}",
        parse_mode=ParseMode.HTML,
    )
    await asyncio.sleep(2)

    for r in range(1, rounds + 1):
        await context.bot.send_message(cid,
            f"{emoji} <b>Раунд {r}/{rounds}</b>\n{mention(h_id, h_name)} бросает...",
            parse_mode=ParseMode.HTML)
        h_val = (await context.bot.send_dice(chat_id=cid, emoji=emoji)).dice.value
        h_pts, h_lbl = score_throw(gtype, h_val)
        await asyncio.sleep(3)

        await context.bot.send_message(cid,
            f"{mention(o_id, o_name)} бросает...", parse_mode=ParseMode.HTML)
        o_val = (await context.bot.send_dice(chat_id=cid, emoji=emoji)).dice.value
        o_pts, o_lbl = score_throw(gtype, o_val)
        await asyncio.sleep(3)

        h_total += h_pts
        o_total += o_pts
        r_res = f"🏅 {mention(h_id, h_name)} берёт раунд!" if h_pts > o_pts else \
                f"🏅 {mention(o_id, o_name)} берёт раунд!" if o_pts > h_pts else "🤝 Ничья!"

        await context.bot.send_message(cid,
            f"📊 Раунд {r}: {h_lbl} | {o_lbl}\n"
            f"{r_res}\nСчёт: <b>{h_total} — {o_total}</b>",
            parse_mode=ParseMode.HTML)
        await asyncio.sleep(2)

    if h_total == o_total:
        await db_record_game(h_id, cid, won=False, draw=True)
        await db_record_game(o_id, cid, won=False, draw=True)
        await context.bot.send_message(cid,
            f"🤝 <b>НИЧЬЯ!</b>\nИтог: {h_total} — {o_total}\nСтавки возвращены!",
            parse_mode=ParseMode.HTML)
        return

    w_id, w_name = (h_id, h_name) if h_total > o_total else (o_id, o_name)
    l_id         = o_id if w_id == h_id else h_id

    await db_deduct_vrf(l_id, cid, bet)
    new_bal = await db_add_vrf(w_id, cid, bet)
    await db_add_xp(w_id, cid, XP_PER_WIN)
    await db_add_xp(l_id, cid, XP_PER_GAME)
    await db_record_game(w_id, cid, won=True)
    await db_record_game(l_id, cid, won=False)

    h_win_s = h_total > o_total
    o_win_s = o_total > h_total
    sport_rich = (
        f"<h2>{emoji} {name} &mdash; Итог</h2>"
        "<table bordered striped>"
        "<tr><th>Игрок</th><th align=\"right\">Очки</th></tr>"
        f"<tr><td>{'<b>' if h_win_s else ''}{h_name}{'</b>' if h_win_s else ''}</td>"
        f"<td align=\"right\">{'<mark><b>' if h_win_s else ''}{h_total}{'</b></mark>' if h_win_s else ''}</td></tr>"
        f"<tr><td>{'<b>' if o_win_s else ''}{o_name}{'</b>' if o_win_s else ''}</td>"
        f"<td align=\"right\">{'<mark><b>' if o_win_s else ''}{o_total}{'</b></mark>' if o_win_s else ''}</td></tr>"
        "</table>"
        f"<blockquote>🏆 <b>{w_name}</b> побеждает!<br/>"
        f"Раундов: {rounds} | 💎 +{fmt(bet)} VRF &rarr; {fmt(new_bal)} VRF</blockquote>"
    )
    sport_fb = (
        f"🏆 <b>ПОБЕДИТЕЛЬ!</b>\n{mention(w_id, w_name)}\n"
        f"📊 {h_total}:{o_total} | 💎 +{fmt(bet)} VRF"
    )
    await send_rich(context.bot, cid, html=sport_rich, fallback_html=sport_fb)


@only_groups
async def cmd_basket(update, context):   await _cmd_sport(update, context, "basket")
@only_groups
async def cmd_football(update, context): await _cmd_sport(update, context, "football")
@only_groups
async def cmd_bowling(update, context):  await _cmd_sport(update, context, "bowling")
@only_groups
async def cmd_darts(update, context):    await _cmd_sport(update, context, "darts")


# ══════════════════════════════════════════════════════
#              SLOT MACHINE 🎰
# ══════════════════════════════════════════════════════

@only_groups
async def cmd_slot(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    host = update.effective_user
    cid  = update.effective_chat.id

    if not update.message.reply_to_message or update.message.reply_to_message.from_user.is_bot:
        await update.message.reply_text("🎰 Ответь на сообщение соперника!")
        return

    opponent = update.message.reply_to_message.from_user
    if opponent.id == host.id:
        await update.message.reply_text("❌ Нельзя играть с собой!")
        return

    await db_ensure_user(host.id,     cid, host.username     or "", host.first_name)
    await db_ensure_user(opponent.id, cid, opponent.username or "", opponent.first_name)
    hu = await db_get_user(host.id, cid)
    ou = await db_get_user(opponent.id, cid)
    bet = calc_bet(hu["vrf"], ou["vrf"])

    if hu["vrf"] < bet or ou["vrf"] < bet:
        await update.message.reply_text(f"❌ Нужно {bet} VRF у обоих игроков!")
        return

    game_id = str(uuid.uuid4())[:8]
    slot_games[game_id] = {
        "host_id": host.id, "host_name": host.first_name,
        "opp_id": opponent.id, "opp_name": opponent.first_name,
        "cid": cid, "bet": bet, "state": "waiting",
        "h_val": None, "o_val": None,
    }

    await update.message.reply_text(
        f"🎰 <b>СЛОТ-МАШИНА PvP!</b>\n\n"
        f"🤺 {mention(host.id, host.first_name)}\n"
        f"⚔️ {mention(opponent.id, opponent.first_name)}\n\n"
        f"💎 Ставка: <b>{bet} VRF</b> с каждого\n"
        f"🏆 Лучшая комбинация побеждает!",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[
            SBtn("Принять 🎰", style="success", callback_data=f"slj:{game_id}"),
            SBtn("Отказать", style="danger",       callback_data=f"sld:{game_id}"),
        ]]),
    )


# ══════════════════════════════════════════════════════
#              MINES GAME 💣
# ══════════════════════════════════════════════════════

MINES_TOTAL = 25  # 5 × 5 grid


def calc_mines_mult(safe_revealed: int, mines_count: int) -> float:
    """Fair payout multiplier with 3 % house edge."""
    if safe_revealed == 0:
        return 1.0
    safe_total = MINES_TOTAL - mines_count
    prob = 1.0
    for i in range(safe_revealed):
        prob *= (safe_total - i) / (MINES_TOTAL - i)
    return max(1.01, round(0.97 / prob, 2))


def _mines_grid_kb(uid: int, cid: int, game: dict) -> InlineKeyboardMarkup:
    """Render the live 5×5 grid + cashout/quit row."""
    grid, rev = game["grid"], game["revealed"]
    rows = []
    for r in range(5):
        row = []
        for c in range(5):
            i = r * 5 + c
            if rev[i]:
                txt = "💣" if grid[i] else "💎"
                cb  = "mg:noop"
            else:
                txt = "⬜"
                cb  = f"mg:c:{uid}:{cid}:{i}"
            row.append(InlineKeyboardButton(txt, callback_data=cb))
        rows.append(row)
    mult   = calc_mines_mult(game["safe_revealed"], game["mines_count"])
    payout = int(game["bet"] * mult)
    rows.append([
        InlineKeyboardButton(
            f"💸 Забрать {fmt(payout)} VRF  ({mult}×)",
            callback_data=f"mg:co:{uid}:{cid}",
        ),
        SBtn("Сдаться", style="danger", callback_data=f"mg:q:{uid}:{cid}"),
    ])
    return InlineKeyboardMarkup(rows)


def _mines_dead_kb(game: dict, boom_idx: int = -1) -> InlineKeyboardMarkup:
    """Non-clickable result grid revealing all mines."""
    grid, rev = game["grid"], game["revealed"]
    rows = []
    for r in range(5):
        row = []
        for c in range(5):
            i = r * 5 + c
            if i == boom_idx:
                txt = E_BOOM
            elif grid[i]:
                txt = "💣"
            elif rev[i]:
                txt = "💎"
            else:
                txt = "⬛"
            row.append(InlineKeyboardButton(txt, callback_data="mg:noop"))
        rows.append(row)
    rows.append([SBtn("Играть снова 🎮", style="success", callback_data="mg:new")])
    return InlineKeyboardMarkup(rows)


def _mines_header(game: dict) -> str:
    mult      = calc_mines_mult(game["safe_revealed"], game["mines_count"])
    payout    = int(game["bet"] * mult)
    safe_left = MINES_TOTAL - game["mines_count"] - game["safe_revealed"]
    return (
        f"💣 <b>Мины</b>  ·  Ставка: <b>{fmt(game['bet'])} VRF</b>\n"
        f"💣 Мин на поле: <b>{game['mines_count']}</b>  ·  "
        f"✅ Открыто: <b>{game['safe_revealed']}</b>  ·  "
        f"⚡ Множитель: <b>{mult}×</b>\n"
        f"💰 Забрать прямо сейчас: <b>{fmt(payout)} VRF</b>\n"
        f"🔍 Осталось безопасных: <b>{safe_left}</b>\n\n"
        f"Нажимай ⬜ — ищи 💎, избегай 💣!"
    )


def _mines_bet_kb(uid: int, cid: int) -> InlineKeyboardMarkup:
    row1 = [InlineKeyboardButton(f"💎 {v} VRF",
            callback_data=f"mg:b:{uid}:{cid}:{v}") for v in [10, 25, 50]]
    row2 = [InlineKeyboardButton(f"💎 {v} VRF",
            callback_data=f"mg:b:{uid}:{cid}:{v}") for v in [100, 200, 500]]
    return InlineKeyboardMarkup([row1, row2,
        [SBtn("Отмена", style="danger", callback_data="mg:cancel")]])


@only_groups
async def cmd_mines(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    u   = update.effective_user
    cid = update.effective_chat.id
    key = f"{u.id}:{cid}"

    # Resume existing game if still active
    if key in mines_games and mines_games[key]["state"] == "active":
        g = mines_games[key]
        await update.message.reply_text(
            "♻️ <b>У тебя уже есть активная игра!</b>\n\n" + _mines_header(g),
            parse_mode=ParseMode.HTML,
            reply_markup=_mines_grid_kb(u.id, cid, g),
        )
        return

    await db_ensure_user(u.id, cid, u.username or "", u.first_name)
    uu = await db_get_user(u.id, cid)
    if not uu:
        return

    await update.message.reply_text(
        f"💣 <b>Мины</b>\n\n"
        f"💎 Баланс: <b>{fmt(uu['vrf'])} VRF</b>\n\n"
        f"Открывай клетки — ищи 💎 и избегай 💣\n"
        f"Чем больше клеток откроешь — тем выше множитель!\n"
        f"В любой момент нажми <b>Забрать</b> и забери выигрыш 💸\n\n"
        f"Выбери ставку:",
        parse_mode=ParseMode.HTML,
        reply_markup=_mines_bet_kb(u.id, cid),
    )


# ══════════════════════════════════════════════════════
#              ADMIN COMMANDS
# ══════════════════════════════════════════════════════

@only_groups
async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_group_or_bot_admin(update):
        await update.message.reply_text("❌ Нет доступа — только для администраторов")
        return

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Статистика",    callback_data="ap:stats"),
         InlineKeyboardButton("🏆 Топ VRF",      callback_data="ap:top")],
        [InlineKeyboardButton("💑 Все браки",     callback_data="ap:marriages"),
         InlineKeyboardButton("👮 Бот-админы",   callback_data="ap:admins")],
        [InlineKeyboardButton("📋 Все команды",   callback_data="ap:cmds"),
         InlineKeyboardButton("ℹ️ Управление",   callback_data="ap:manage")],
        [SBtn("Закрыть", style="danger",       callback_data="ap:close")],
    ])
    await update.message.reply_text(
        f"🛡️ <b>Verifure Admin Panel</b>\n\n{E_ALERT} Выбери раздел:",
        parse_mode=ParseMode.HTML,
        reply_markup=kb,
    )


@only_groups
async def cmd_givevrf(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_group_or_bot_admin(update):
        await update.message.reply_text("❌ Только для администраторов")
        return
    if not update.message.reply_to_message or not context.args:
        await update.message.reply_text("Использование: /givevrf <сумма> (ответом)")
        return
    try:
        amount = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Укажи сумму: /givevrf 500")
        return
    target  = update.message.reply_to_message.from_user
    cid     = update.effective_chat.id
    await db_ensure_user(target.id, cid, target.username or "", target.first_name)
    new_bal = await db_add_vrf(target.id, cid, amount)
    await update.message.reply_text(
        f"✅ Выдано <b>{fmt(amount)} VRF</b> → {mention(target.id, target.first_name)}\n"
        f"💎 Баланс: {fmt(new_bal)} VRF",
        parse_mode=ParseMode.HTML,
    )


@only_groups
async def cmd_takevrf(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_group_or_bot_admin(update):
        await update.message.reply_text("❌ Только для администраторов")
        return
    if not update.message.reply_to_message or not context.args:
        await update.message.reply_text("Использование: /takevrf <сумма> (ответом)")
        return
    try:
        amount = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Укажи сумму")
        return
    target  = update.message.reply_to_message.from_user
    cid     = update.effective_chat.id
    u       = await db_get_user(target.id, cid)
    if not u:
        await update.message.reply_text("❌ Пользователь не найден")
        return
    new_val = max(0, u["vrf"] - amount)
    await db_set_vrf(target.id, cid, new_val)
    await update.message.reply_text(
        f"✅ Списано <b>{fmt(amount)} VRF</b> у {mention(target.id, target.first_name)}\n"
        f"💎 Баланс: {fmt(new_val)} VRF",
        parse_mode=ParseMode.HTML,
    )


@only_groups
async def cmd_givebear(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_group_or_bot_admin(update):
        await update.message.reply_text("❌ Только для администраторов")
        return
    if not update.message.reply_to_message:
        await update.message.reply_text("Ответь на сообщение пользователя")
        return
    target = update.message.reply_to_message.from_user
    cid    = update.effective_chat.id
    await db_ensure_user(target.id, cid, target.username or "", target.first_name)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET bears=bears+1 WHERE user_id=? AND chat_id=?",
                         (target.id, cid))
        await db.commit()
    u = await db_get_user(target.id, cid)
    await update.message.reply_text(
        f"{E_BEAR} {mention(target.id, target.first_name)} получает медведя!\n"
        f"Всего {E_BEAR}: {u['bears']}",
        parse_mode=ParseMode.HTML,
    )


@only_groups
async def cmd_addadmin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_group_or_bot_admin(update):
        await update.message.reply_text("❌ Нет доступа")
        return
    if not update.message.reply_to_message:
        await update.message.reply_text("❌ Ответь на сообщение пользователя")
        return
    t = update.message.reply_to_message.from_user
    if t.is_bot:
        await update.message.reply_text("❌ Нельзя добавить бота")
        return
    await db_add_admin(t.id, t.username or "", t.first_name or "", update.effective_user.id)
    await update.message.reply_text(
        f"✅ {mention(t.id, t.first_name)} добавлен как бот-администратор!",
        parse_mode=ParseMode.HTML,
    )


@only_groups
async def cmd_removeadmin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_group_or_bot_admin(update):
        await update.message.reply_text("❌ Нет доступа")
        return
    if not update.message.reply_to_message:
        await update.message.reply_text("❌ Ответь на сообщение пользователя")
        return
    t = update.message.reply_to_message.from_user
    if await db_remove_admin(t.id):
        await update.message.reply_text(f"✅ {mention(t.id, t.first_name)} удалён из бот-администраторов",
                                        parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text(f"❌ {mention(t.id, t.first_name)} не является бот-администратором",
                                        parse_mode=ParseMode.HTML)


@only_groups
async def cmd_listadmins(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_group_or_bot_admin(update):
        await update.message.reply_text("❌ Нет доступа")
        return
    admins = await db_list_admins()
    lines  = ["👮 <b>Бот-администраторы</b>\n"]
    for a in admins:
        uname = f" @{a['username']}" if a["username"] else ""
        lines.append(f"• {mention(a['user_id'], a['first_name'])}{uname}")
    if ADMIN_IDS:
        lines.append(f"\n🔧 Env ADMIN_IDS: {', '.join(map(str, ADMIN_IDS))}")
    if not admins and not ADMIN_IDS:
        lines.append("Нет бот-администраторов")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


# ══════════════════════════════════════════════════════
#                CALLBACK HANDLER
# ══════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════
#           TIC-TAC-TOE GAME ❌⭕
# ══════════════════════════════════════════════════════

TTT_SIZES: dict = {
    3: {"win": 3, "label": "3×3"},
    5: {"win": 4, "label": "5×5"},
    8: {"win": 5, "label": "8×8"},
}


def ttt_check_winner(board: list, size: int = 3, win: int = 3) -> Optional[str]:
    """Returns 'X' or 'O' if `win` consecutive marks found, else None."""
    for r in range(size):
        for col in range(size):
            sym = board[r * size + col]
            if not sym:
                continue
            # Horizontal →
            if col + win <= size and all(board[r * size + col + k] == sym for k in range(win)):
                return sym
            # Vertical ↓
            if r + win <= size and all(board[(r + k) * size + col] == sym for k in range(win)):
                return sym
            # Diagonal ↘
            if r + win <= size and col + win <= size and all(board[(r+k)*size+(col+k)] == sym for k in range(win)):
                return sym
            # Diagonal ↙
            if r + win <= size and col - win + 1 >= 0 and all(board[(r+k)*size+(col-k)] == sym for k in range(win)):
                return sym
    return None


def _ttt_sym(s: str) -> str:
    return {"X": "❌", "O": "⭕", "": "⬜"}.get(s, "⬜")


def ttt_board_kb(game_id: str, board: list, size: int = 3, locked: bool = False) -> InlineKeyboardMarkup:
    rows = []
    for r in range(size):
        row = []
        for col in range(size):
            i   = r * size + col
            sym = _ttt_sym(board[i])
            cb  = "ttt:noop" if (locked or board[i]) else f"ttt:{game_id}:{i}"
            row.append(InlineKeyboardButton(sym, callback_data=cb))
        rows.append(row)
    return InlineKeyboardMarkup(rows)


@only_groups
async def cmd_ttt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    host = update.effective_user
    cid  = update.effective_chat.id

    if not update.message.reply_to_message or update.message.reply_to_message.from_user.is_bot:
        await update.message.reply_text("❌⭕ Ответь на сообщение соперника чтобы начать крестики-нолики!")
        return

    opponent = update.message.reply_to_message.from_user
    if opponent.id == host.id:
        await update.message.reply_text("❌ Нельзя играть с собой!")
        return

    await db_ensure_user(host.id,     cid, host.username     or "", host.first_name)
    await db_ensure_user(opponent.id, cid, opponent.username or "", opponent.first_name)
    hu = await db_get_user(host.id, cid)
    ou = await db_get_user(opponent.id, cid)

    bet = calc_bet(hu["vrf"], ou["vrf"])
    bet = max(bet, 1)
    if hu["vrf"] < 1 or ou["vrf"] < 1:
        await update.message.reply_text("❌ Недостаточно VRF!")
        return

    o_m = mention(opponent.id, opponent.first_name)
    await update.message.reply_text(
        f"❌⭕ <b>Крестики-нолики</b>\n\n"
        f"⚔️ {mention(host.id, host.first_name)} vs {o_m}\n"
        f"💎 Расчётная ставка: <b>{bet} VRF</b>\n\n"
        f"📐 Выбери размер поля:",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("3×3  (3 в ряд)",
                    callback_data=f"ttsz:{host.id}:{opponent.id}:{cid}:3"),
                InlineKeyboardButton("5×5  (4 в ряд)",
                    callback_data=f"ttsz:{host.id}:{opponent.id}:{cid}:5"),
                InlineKeyboardButton("8×8  (5 в ряд)",
                    callback_data=f"ttsz:{host.id}:{opponent.id}:{cid}:8"),
            ],
            [SBtn("Отмена", style="danger", callback_data="ttsz:cancel")],
        ]),
    )



# ══════════════════════════════════════════════════════
#              BATTLESHIP GAME 🚢
# ══════════════════════════════════════════════════════

BS_SIZE  = 8                       # 8×8 grid
BS_SHIPS = [4, 3, 3, 2, 2, 2]     # ship lengths → 16 cells total
BS_TOTAL = sum(BS_SHIPS)           # 16


def _bs_place_ships(size: int, ships: list) -> list:
    """Randomly place ships with 1-cell buffer. Returns flat bool list."""
    grid = [False] * (size * size)
    for length in ships:
        for _ in range(3000):
            horiz = random.choice([True, False])
            if horiz:
                r = random.randint(0, size - 1)
                c = random.randint(0, size - length)
            else:
                r = random.randint(0, size - length)
                c = random.randint(0, size - 1)
            cells = [
                (r, c + k) if horiz else (r + k, c)
                for k in range(length)
            ]
            ok = True
            for rr, cc in cells:
                for dr in (-1, 0, 1):
                    for dc in (-1, 0, 1):
                        nr, nc = rr + dr, cc + dc
                        if 0 <= nr < size and 0 <= nc < size and grid[nr * size + nc]:
                            ok = False
                            break
                    if not ok:
                        break
                if not ok:
                    break
            if ok:
                for rr, cc in cells:
                    grid[rr * size + cc] = True
                break
    return grid


def _bs_alive(grid: list, shots: list) -> int:
    """Count ship cells not yet hit."""
    return sum(1 for i in range(len(grid)) if grid[i] and not shots[i])


def _bs_own_board(my_grid: list, opp_shots: list, size: int) -> str:
    """Render player's own board (ships visible) as monospace text."""
    COLS = "ABCDEFGH"[:size]
    lines = ["   " + " ".join(COLS)]
    for r in range(size):
        row = []
        for c in range(size):
            i = r * size + c
            if opp_shots[i] and my_grid[i]:
                row.append("💥")
            elif opp_shots[i]:
                row.append("🌊")
            elif my_grid[i]:
                row.append("🚢")
            else:
                row.append("⬜")
        lines.append(f"{r+1}  " + " ".join(row))
    return "\n".join(lines)


def _bs_player_text(game: dict, pnum: int) -> str:
    """Compose DM text for a given player (1 or 2)."""
    is1    = pnum == 1
    mygr   = game["grid1"] if is1 else game["grid2"]
    opgr   = game["grid2"] if is1 else game["grid1"]
    mysh   = game["shots1"] if is1 else game["shots2"]
    opsh   = game["shots2"] if is1 else game["shots1"]
    myname = game["p1_name"] if is1 else game["p2_name"]
    opname = game["p2_name"] if is1 else game["p1_name"]
    my_hp  = _bs_alive(mygr, opsh)
    op_hp  = _bs_alive(opgr, mysh)
    is_my  = game["turn"] == pnum
    turn_ln = "🎯 <b>ТВОЙ ХОД!</b> Нажми на клетку ниже ⬇️" if is_my \
              else f"⏳ <i>Ход {opname}, жди...</i>"
    board = _bs_own_board(mygr, opsh, BS_SIZE)
    return (
        f"🚢 <b>Морской Бой!</b>  ·  Флот: 🛳4 🚢3 🚢3 ⛵2 ⛵2 ⛵2\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 <b>{myname}</b>  ❤️ {my_hp}/{BS_TOTAL}  ·  "
        f"🎯 <b>{opname}</b>  ❤️ {op_hp}/{BS_TOTAL}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"{turn_ln}\n\n"
        f"<b>🗺 Твоё поле:</b>\n"
        f"<code>{board}</code>\n\n"
        f"<b>⬇️ Атакуй поле врага:</b>"
    )


def _bs_atk_kb(game_id: str, opp_grid: list, my_shots: list,
               pnum: int, reveal: bool = False) -> InlineKeyboardMarkup:
    """Inline keyboard: opponent grid (ships hidden) for firing."""
    sz   = BS_SIZE
    rows = []
    for r in range(sz):
        row = []
        for c in range(sz):
            i = r * sz + c
            if my_shots[i]:
                txt = "💥" if opp_grid[i] else "🌊"
                cb  = f"bs:x:{game_id}"
            elif reveal:
                txt = "🚢" if opp_grid[i] else "⬜"
                cb  = f"bs:x:{game_id}"
            else:
                txt = "⬜"
                cb  = f"bs:f:{game_id}:{pnum}:{i}"
            row.append(InlineKeyboardButton(txt, callback_data=cb))
        rows.append(row)
    return InlineKeyboardMarkup(rows)


@only_groups
async def cmd_seabattle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    host = update.effective_user
    cid  = update.effective_chat.id

    if (not update.message.reply_to_message
            or update.message.reply_to_message.from_user.is_bot):
        await update.message.reply_text(
            "🚢 <b>Морской Бой</b>\n\nОтветь на сообщение соперника чтобы начать!\n"
            "Игра ведётся в <b>личных сообщениях</b> с ботом (8×8, ставка VRF).",
            parse_mode=ParseMode.HTML,
        )
        return

    opp = update.message.reply_to_message.from_user
    if opp.id == host.id:
        await update.message.reply_text("❌ Нельзя играть с собой!")
        return

    await db_ensure_user(host.id, cid, host.username or "", host.first_name)
    await db_ensure_user(opp.id,  cid, opp.username  or "", opp.first_name)
    hu  = await db_get_user(host.id, cid)
    ou  = await db_get_user(opp.id,  cid)
    bet = calc_bet(hu["vrf"], ou["vrf"])
    if hu["vrf"] < bet or ou["vrf"] < bet:
        await update.message.reply_text(
            f"❌ Нужно <b>{fmt(bet)} VRF</b> у каждого!", parse_mode=ParseMode.HTML
        )
        return

    game_id = str(uuid.uuid4())[:8]
    battle_games[game_id] = {
        "game_id": game_id, "cid": cid, "bet": bet,
        "p1_id":  host.id, "p1_name": host.first_name, "p1_mid": None,
        "p2_id":  opp.id,  "p2_name": opp.first_name,  "p2_mid": None,
        "grid1":  None, "grid2": None,
        "shots1": [False] * (BS_SIZE * BS_SIZE),
        "shots2": [False] * (BS_SIZE * BS_SIZE),
        "turn": 1, "state": "waiting",
    }

    await update.message.reply_text(
        f"🚢 <b>МОРСКОЙ БОЙ!</b>\n\n"
        f"⚔️ {mention(host.id, host.first_name)} vs {mention(opp.id, opp.first_name)}\n"
        f"💎 Ставка: <b>{fmt(bet)} VRF</b>  ·  Поле: <b>8×8</b>\n"
        f"🛳 Флот: 4·3·3·2·2·2 (6 кораблей)\n\n"
        f"📨 Игра ведётся в <b>личных сообщениях</b> с ботом!\n"
        f"{mention(opp.id, opp.first_name)}, принимаешь вызов?",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[
            SBtn("Принять ⚔️", style="success", callback_data=f"bsj:{game_id}"),
            SBtn("Отказать", style="danger",  callback_data=f"bsd:{game_id}"),
        ]]),
    )

    bot = context.bot
    async def _bs_timeout() -> None:
        await asyncio.sleep(JOIN_TIMEOUT)
        if game_id in battle_games and battle_games[game_id]["state"] == "waiting":
            del battle_games[game_id]
            try:
                await bot.send_message(cid, "⏰ Приглашение в Морской Бой истекло.")
            except TelegramError:
                pass
    context.application.create_task(_bs_timeout())


# ══════════════════════════════════════════════════════
#           CASINO 777 HANDLER 🎰
# ══════════════════════════════════════════════════════

async def on_casino_777(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Reply when someone hits 777 on the slot machine."""
    msg = update.message
    if not msg or not msg.dice:
        return
    if msg.dice.emoji != "🎰" or msg.dice.value != 64:
        return
    if update.effective_chat.type == "private":
        return
    user = update.effective_user
    if not user or user.is_bot:
        return
    try:
        await msg.reply_text(
            f"🎰🎰🎰 <b>ДЖЕКПОТ! 777!</b> 🎰🎰🎰\n\n"
            f"🏆 {mention(user.id, user.first_name)} выбил <b>777</b>!\n"
            f"🎊 Невероятная удача! Поздравляем! 🎊",
            parse_mode=ParseMode.HTML,
        )
        await _react(update, "🎉")
        # Send confetti effect DM to the winner
        try:
            await context.bot.send_message(
                chat_id=user.id,
                text="🎰 <b>777! ДЖЕКПОТ!</b> 🎊\nТебе сегодня везёт!",
                parse_mode=ParseMode.HTML,
                message_effect_id=MSG_EFFECT_CONFETTI,
            )
        except TelegramError:
            pass
    except TelegramError:
        pass



# ══════════════════════════════════════════════════════
#           CANCEL COMMAND — /cancel / отмена
# ══════════════════════════════════════════════════════

@only_groups
async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Cancel all waiting/pending games the user is in."""
    uid       = update.effective_user.id
    cid       = update.effective_chat.id
    cancelled = []

    # Duel challenges (challenger or opponent)
    for k in [k for k, v in list(duel_challenges.items())
              if k.startswith(f"{cid}:") and (v.get("c_id") == uid or v.get("o_id") == uid)]:
        del duel_challenges[k]
        cancelled.append("⚔️ Дуэль")

    # Cubes (waiting)
    for k, v in list(cubes_games.items()):
        if v["cid"] == cid and v["state"] == "waiting" and uid in (v["host_id"], v["opp_id"]):
            del cubes_games[k]
            cancelled.append("🎲 Кубики")

    # Sports (waiting)
    for k, v in list(sports_games.items()):
        if v.get("cid") == cid and v.get("state") == "waiting" and uid in (v.get("host_id"), v.get("opp_id")):
            del sports_games[k]
            cancelled.append("🏅 Спорт")

    # Slot (active, not yet spun fully)
    for k, v in list(slot_games.items()):
        if v["cid"] == cid and uid in (v["host_id"], v["opp_id"]):
            del slot_games[k]
            cancelled.append("🎰 Слот")

    # TTT (waiting invite)
    for k, v in list(ttt_games.items()):
        if v["cid"] == cid and v["state"] == "waiting" and uid in (v["host_id"], v["opp_id"]):
            del ttt_games[k]
            cancelled.append("❌⭕ Крестики-нолики")

    # Battleship (waiting invite)
    for k, v in list(battle_games.items()):
        if v["cid"] == cid and v["state"] == "waiting" and uid in (v["p1_id"], v["p2_id"]):
            del battle_games[k]
            cancelled.append("🚢 Морской Бой")

    if cancelled:
        await update.message.reply_text(
            f"✅ <b>Отменено:</b> {', '.join(cancelled)}",
            parse_mode=ParseMode.HTML,
        )
    else:
        await update.message.reply_text("❌ Нет ожидающих игр для отмены")


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query    = update.callback_query
    data     = query.data
    cid      = query.message.chat_id
    who      = query.from_user

    # ── Top tabs ────────────────────────────────────────
    if data.startswith("top:"):
        _, sort, _ = data.split(":")
        await query.answer()
        await _show_top(query, context, cid, sort, edit=True)
        return

    # ── Marriage ────────────────────────────────────────
    if data.startswith("ma:") or data.startswith("mr:"):
        parts  = data.split(":")
        action = parts[0]
        p_id   = int(parts[1])
        t_id   = int(parts[2])

        if who.id != t_id:
            await query.answer("❌ Это предложение не для тебя!", show_alert=True)
            return
        prop = await db_get_proposal_to(t_id, cid)
        if not prop or prop["proposer_id"] != p_id:
            await query.answer("❌ Предложение уже недействительно", show_alert=True)
            await query.edit_message_reply_markup(None)
            return
        pu    = await db_get_user(p_id, cid)
        pname = pu["first_name"] if pu else "Партнёр"

        if action == "ma":
            if await db_get_marriage(p_id, cid) or await db_get_marriage(t_id, cid):
                await query.answer("❌ Один из вас уже в браке!", show_alert=True)
                return
            await db_create_marriage(p_id, t_id, cid)
            await query.answer("💍 Поздравляем!")
            await query.edit_message_text(
                f"💒 <b>СВАДЬБА!</b>\n\n"
                f"💑 {mention(p_id, pname)} ❤️ {mention(t_id, who.first_name)}\n\n"
                f"🎊 Поздравляем! Бонус к /daily активирован!",
                parse_mode=ParseMode.HTML,
            )
        else:
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("DELETE FROM proposals WHERE target_id=? AND chat_id=?",
                                 (t_id, cid))
                await db.commit()
            await query.answer("💔 Отклонено")
            await query.edit_message_text(
                f"💔 {mention(t_id, who.first_name)} отклонил(а) предложение от {mention(p_id, pname)}",
                parse_mode=ParseMode.HTML,
            )
        return

    # ── Duel ────────────────────────────────────────────
    if data.startswith("da:") or data.startswith("dd:"):
        parts  = data.split(":")
        action = parts[0]
        c_id   = int(parts[1])
        o_id   = int(parts[2])
        key    = f"{cid}:{c_id}:{o_id}"

        if who.id != o_id:
            await query.answer("❌ Вызов не для тебя!", show_alert=True)
            return
        if key not in duel_challenges:
            await query.answer("❌ Вызов уже неактуален", show_alert=True)
            await query.edit_message_reply_markup(None)
            return

        challenge = duel_challenges.pop(key)

        if action == "dd":
            await query.answer("🏳️ Ты отказался")
            await query.edit_message_text(
                f"🏳️ {mention(o_id, who.first_name)} отказался от дуэли!\n"
                f"{mention(c_id, challenge['c_name'])} остаётся непобеждённым.",
                parse_mode=ParseMode.HTML,
            )
            return

        # Check VRF
        cu = await db_get_user(c_id, cid)
        ou = await db_get_user(o_id, cid)
        bet = challenge["bet"]
        if not cu or cu["vrf"] < bet:
            await query.answer("❌ У вызывающего недостаточно VRF!", show_alert=True)
            return
        if not ou or ou["vrf"] < bet:
            await query.answer("❌ У тебя недостаточно VRF!", show_alert=True)
            return

        await query.answer("⚔️ Принято!")
        await query.edit_message_text(
            f"⚔️ <b>ДУЭЛЬ ПРИНЯТА!</b>\n"
            f"{mention(c_id, challenge['c_name'])} ⚔️ {mention(o_id, who.first_name)}\n"
            f"💰 Ставка: {bet} VRF · 🎲 Бросаем...",
            parse_mode=ParseMode.HTML,
        )
        context.application.create_task(_run_duel(context, challenge))
        return

    # ── Cubes join ──────────────────────────────────────
    if data.startswith("cj:") or data.startswith("cd:"):
        game_id = data[3:]
        game    = cubes_games.get(game_id)

        if not game:
            await query.answer("❌ Игра не найдена", show_alert=True)
            return
        if game["state"] != "waiting":
            await query.answer("❌ Игра уже началась", show_alert=True)
            return

        if data.startswith("cd:"):
            if who.id != game["opp_id"]:
                await query.answer("❌ Ты не соперник!", show_alert=True)
                return
            del cubes_games[game_id]
            await query.answer("❌ Отказано")
            await query.edit_message_text(
                f"❌ {mention(who.id, who.first_name)} отказался от игры в кости.",
                parse_mode=ParseMode.HTML,
            )
            return

        if who.id != game["opp_id"]:
            await query.answer("❌ Ты не соперник!", show_alert=True)
            return

        bet = game["bet"]
        hu  = await db_get_user(game["host_id"], cid)
        ou  = await db_get_user(who.id, cid)
        if not hu or hu["vrf"] < bet:
            await query.answer("❌ У хоста недостаточно VRF!", show_alert=True)
            return
        if not ou or ou["vrf"] < bet:
            await query.answer("❌ У тебя недостаточно VRF!", show_alert=True)
            return

        game["state"] = "playing"
        await query.answer("🎲 Поехали!")
        await query.edit_message_text(
            f"🎲 <b>Игра началась!</b>\n"
            f"{mention(game['host_id'], game['host_name'])} ⚔️ {mention(who.id, who.first_name)}\n"
            f"Раундов: {game['rounds']} | Ставка: {bet} VRF",
            parse_mode=ParseMode.HTML,
        )
        context.application.create_task(_run_cubes(context, game))
        return

    # ── Sports join ─────────────────────────────────────
    if data.startswith("sj:") or data.startswith("sd:"):
        game_id = data[3:]
        game    = sports_games.get(game_id)

        if not game:
            await query.answer("❌ Игра не найдена", show_alert=True)
            return
        if game["state"] != "waiting":
            await query.answer("❌ Игра уже началась", show_alert=True)
            return

        if data.startswith("sd:"):
            if who.id != game["opp_id"]:
                await query.answer("❌ Ты не соперник!", show_alert=True)
                return
            del sports_games[game_id]
            await query.answer("❌ Отказано")
            await query.edit_message_text(
                f"❌ {mention(who.id, who.first_name)} отказался от вызова.",
                parse_mode=ParseMode.HTML,
            )
            return

        if who.id != game["opp_id"]:
            await query.answer("❌ Ты не соперник!", show_alert=True)
            return

        bet = game["bet"]
        hu  = await db_get_user(game["host_id"], cid)
        ou  = await db_get_user(who.id, cid)
        if not hu or hu["vrf"] < bet:
            await query.answer("❌ У хоста недостаточно VRF!", show_alert=True)
            return
        if not ou or ou["vrf"] < bet:
            await query.answer("❌ У тебя недостаточно VRF!", show_alert=True)
            return

        game["state"] = "playing"
        emoji = SPORT_EMOJI[game["type"]]
        await query.answer(f"{emoji} Поехали!")
        await query.edit_message_text(
            f"{emoji} <b>Игра началась!</b>\n"
            f"{mention(game['host_id'], game['host_name'])} ⚔️ {mention(who.id, who.first_name)}\n"
            f"Ставка: {bet} VRF",
            parse_mode=ParseMode.HTML,
        )
        context.application.create_task(_run_sports(context, game))
        return

    # ── Slot join ────────────────────────────────────────
    if data.startswith("slj:") or data.startswith("sld:"):
        game_id = data[4:]
        game    = slot_games.get(game_id)

        if not game:
            await query.answer("❌ Игра не найдена", show_alert=True)
            return
        if game["state"] != "waiting":
            await query.answer("❌ Игра уже началась", show_alert=True)
            return

        if data.startswith("sld:"):
            if who.id != game["opp_id"]:
                await query.answer("❌ Ты не соперник!", show_alert=True)
                return
            del slot_games[game_id]
            await query.answer("❌ Отказано")
            await query.edit_message_text("❌ Вызов на слот отклонён.")
            return

        if who.id != game["opp_id"]:
            await query.answer("❌ Ты не соперник!", show_alert=True)
            return

        bet = game["bet"]
        hu  = await db_get_user(game["host_id"], cid)
        ou  = await db_get_user(who.id, cid)
        if not hu or hu["vrf"] < bet:
            await query.answer("❌ У хоста недостаточно VRF!", show_alert=True)
            return
        if not ou or ou["vrf"] < bet:
            await query.answer("❌ У тебя недостаточно VRF!", show_alert=True)
            return

        game["state"] = "active"
        await query.answer("🎰 Принято!")
        await query.edit_message_text(
            f"🎰 <b>Слот-машина!</b>\n\n"
            f"💎 Ставка: {bet} VRF\n\n"
            f"Нажимайте Крутить! (по одному разу каждый)\n\n"
            f"🕹 {mention(game['host_id'], game['host_name'])}: ожидает...\n"
            f"🕹 {mention(game['opp_id'], game['opp_name'])}: ожидает...",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[
                SBtn("Крутить! 🎰", style="primary", callback_data=f"slsp:{game_id}"),
            ]]),
        )
        return

    # ── Slot spin ────────────────────────────────────────
    if data.startswith("slsp:"):
        game_id = data[5:]
        game    = slot_games.get(game_id)

        if not game:
            await query.answer("❌ Игра не найдена", show_alert=True)
            return
        if game["state"] not in ("active",):
            await query.answer("❌ Игра завершена", show_alert=True)
            return

        is_host = who.id == game["host_id"]
        is_opp  = who.id == game["opp_id"]
        if not is_host and not is_opp:
            await query.answer("❌ Ты не участник!", show_alert=True)
            return
        if is_host and game["h_val"] is not None:
            await query.answer("✅ Ты уже крутил(а)!", show_alert=True)
            return
        if is_opp and game["o_val"] is not None:
            await query.answer("✅ Ты уже крутил(а)!", show_alert=True)
            return

        await query.answer("🎰 Крутим!")
        # Bot sends the dice
        dice_msg = await context.bot.send_dice(chat_id=cid, emoji="🎰")
        val = dice_msg.dice.value

        if is_host:
            game["h_val"] = val
        else:
            game["o_val"] = val

        # Check if both spun
        if game["h_val"] is not None and game["o_val"] is not None:
            h_combo, h_mult = parse_slot(game["h_val"])
            o_combo, o_mult = parse_slot(game["o_val"])
            bet = game["bet"]
            h_id, h_name = game["host_id"], game["host_name"]
            o_id, o_name = game["opp_id"],  game["opp_name"]

            del slot_games[game_id]

            if h_mult > o_mult:
                w_id, w_name, l_id = h_id, h_name, o_id
            elif o_mult > h_mult:
                w_id, w_name, l_id = o_id, o_name, h_id
            else:
                await db_record_game(h_id, cid, won=False, draw=True)
                await db_record_game(o_id, cid, won=False, draw=True)
                await context.bot.send_message(cid,
                    f"🤝 <b>НИЧЬЯ в слоте!</b>\n\n"
                    f"{mention(h_id, h_name)}: {h_combo} ({h_mult}x)\n"
                    f"{mention(o_id, o_name)}: {o_combo} ({o_mult}x)\n\n"
                    f"Ставки возвращены!",
                    parse_mode=ParseMode.HTML)
                return

            await db_deduct_vrf(l_id, cid, bet)
            new_bal = await db_add_vrf(w_id, cid, bet)
            await db_add_xp(w_id, cid, XP_PER_WIN)
            await db_add_xp(l_id, cid, XP_PER_GAME)
            await db_record_game(w_id, cid, won=True)
            await db_record_game(l_id, cid, won=False)

            h_slot_win = h_mult > o_mult
            o_slot_win = o_mult > h_mult
            slot_rich = (
                "<h2>🎰 Слот &mdash; Результат</h2>"
                "<table bordered striped>"
                "<tr><th>Игрок</th><th align=\"center\">Комбо</th><th align=\"right\">Множитель</th></tr>"
                f"<tr><td>{'<b>' if h_slot_win else ''}{h_name}{'</b>' if h_slot_win else ''}</td>"
                f"<td align=\"center\">{h_combo}</td>"
                f"<td align=\"right\">{'<mark><b>' if h_slot_win else ''}{h_mult}×{'</b></mark>' if h_slot_win else ''}</td></tr>"
                f"<tr><td>{'<b>' if o_slot_win else ''}{o_name}{'</b>' if o_slot_win else ''}</td>"
                f"<td align=\"center\">{o_combo}</td>"
                f"<td align=\"right\">{'<mark><b>' if o_slot_win else ''}{o_mult}×{'</b></mark>' if o_slot_win else ''}</td></tr>"
                "</table>"
                f"<blockquote>🏆 Победитель: <b>{w_name}</b><br/>"
                f"💎 +{fmt(bet)} VRF &rarr; {fmt(new_bal)} VRF</blockquote>"
            )
            slot_fb = (
                f"🏆 <b>СЛОТ</b>\n{h_name}: {h_combo} ({h_mult}×)\n"
                f"{o_name}: {o_combo} ({o_mult}×)\n\n🥇 {w_name} +{fmt(bet)} VRF"
            )
            await send_rich(context.bot, cid, html=slot_rich, fallback_html=slot_fb)
        else:
            # One player has spun, update message
            h_status = f"✅ {parse_slot(game['h_val'])[0]}" if game["h_val"] else f"{E_WAIT} ожидает..."
            o_status = f"✅ {parse_slot(game['o_val'])[0]}" if game["o_val"] else f"{E_WAIT} ожидает..."
            try:
                await query.edit_message_text(
                    f"🎰 <b>Слот-машина!</b>\n\n"
                    f"💎 Ставка: {game['bet']} VRF\n\n"
                    f"🕹 {mention(game['host_id'], game['host_name'])}: {h_status}\n"
                    f"🕹 {mention(game['opp_id'], game['opp_name'])}: {o_status}",
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup([[
                        SBtn("Крутить! 🎰", style="primary", callback_data=f"slsp:{game_id}"),
                    ]]),
                )
            except TelegramError:
                pass
        return

    # ── TTT size selection ──────────────────────────────
    if data.startswith("ttsz:"):
        if data == "ttsz:cancel":
            await query.answer("Отменено")
            try:
                await query.message.delete()
            except TelegramError:
                pass
            return

        parts  = data.split(":")
        h_id   = int(parts[1])
        o_id   = int(parts[2])
        cid2   = int(parts[3])
        size   = int(parts[4])

        if who.id != h_id:
            await query.answer("❌ Выбор только для хоста!", show_alert=True)
            return

        sz_cfg = TTT_SIZES.get(size)
        if not sz_cfg:
            await query.answer("❌ Неверный размер", show_alert=True)
            return

        hu = await db_get_user(h_id, cid2)
        ou = await db_get_user(o_id, cid2)
        if not hu or not ou:
            await query.answer("❌ Пользователи не найдены", show_alert=True)
            return

        bet = max(calc_bet(hu["vrf"], ou["vrf"]), 1)
        if hu["vrf"] < 1:
            await query.answer("❌ Недостаточно VRF!", show_alert=True)
            return
        if ou["vrf"] < 1:
            await query.answer("❌ У соперника недостаточно VRF!", show_alert=True)
            return

        win   = sz_cfg["win"]
        label = sz_cfg["label"]

        game_id = str(uuid.uuid4())[:8]
        ttt_games[game_id] = {
            "host_id": h_id,  "host_name": hu["first_name"],
            "opp_id":  o_id,  "opp_name":  ou["first_name"],
            "cid": cid2, "bet": bet, "state": "waiting",
            "board": [""] * (size * size),
            "turn": "host",
            "size": size,
            "win":  win,
        }

        await query.answer(f"Поле {label} выбрано!")
        h_m = mention(h_id, hu["first_name"])
        o_m = mention(o_id, ou["first_name"])

        await query.edit_message_text(
            f"❌⭕ <b>Крестики-нолики!</b>\n\n"
            f"❌ {h_m}\n"
            f"⭕ {o_m}\n\n"
            f"📐 Поле: <b>{label}</b> — победа при <b>{win} в ряд</b>\n"
            f"💎 Ставка: <b>{bet} VRF</b>\n\n"
            f"{o_m}, принимаешь вызов?",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[
                SBtn(f"Принять ⭕  {bet} VRF", style="success", callback_data=f"ttj:{game_id}"),
                SBtn("Отказать", style="danger",              callback_data=f"ttd:{game_id}"),
            ]]),
        )

        bot = context.bot
        msg_id = query.message.message_id
        async def _ttsz_timeout():
            await asyncio.sleep(JOIN_TIMEOUT)
            if game_id in ttt_games and ttt_games[game_id]["state"] == "waiting":
                del ttt_games[game_id]
                try:
                    await bot.edit_message_reply_markup(cid2, msg_id, reply_markup=None)
                    await bot.send_message(cid2, "⏰ Приглашение в крестики-нолики истекло.")
                except TelegramError:
                    pass
        context.application.create_task(_ttsz_timeout())
        return

    # ── TTT invite ──────────────────────────────────────
    if data.startswith("ttj:") or data.startswith("ttd:"):
        game_id = data[4:]
        game    = ttt_games.get(game_id)

        if not game:
            await query.answer("❌ Игра не найдена", show_alert=True)
            return
        if game["state"] != "waiting":
            await query.answer("❌ Игра уже началась", show_alert=True)
            return

        if data.startswith("ttd:"):
            if who.id != game["opp_id"]:
                await query.answer("❌ Ты не соперник!", show_alert=True)
                return
            del ttt_games[game_id]
            await query.answer("❌ Отказано")
            await query.edit_message_text(
                f"❌ {mention(who.id, who.first_name)} отказался от крестиков-ноликов.",
                parse_mode=ParseMode.HTML,
            )
            return

        if who.id != game["opp_id"]:
            await query.answer("❌ Ты не соперник!", show_alert=True)
            return

        bet = game["bet"]
        hu  = await db_get_user(game["host_id"], cid)
        ou  = await db_get_user(who.id, cid)
        if not hu or hu["vrf"] < bet:
            await query.answer("❌ У хоста недостаточно VRF!", show_alert=True)
            return
        if not ou or ou["vrf"] < bet:
            await query.answer("❌ У тебя недостаточно VRF!", show_alert=True)
            return

        game["state"] = "playing"
        sz   = game.get("size", 3)
        win  = game.get("win",  3)
        await query.answer("❌⭕ Начинаем!")
        h_m = mention(game["host_id"], game["host_name"])
        o_m = mention(who.id, who.first_name)
        await query.edit_message_text(
            f"❌⭕ <b>Крестики-нолики!</b>\n\n"
            f"❌ {h_m}\n"
            f"⭕ {o_m}\n\n"
            f"📐 Поле: <b>{sz}×{sz}</b> | Победа: <b>{win} в ряд</b>\n"
            f"💎 Ставка: <b>{bet} VRF</b>\n\n"
            f"🎮 Ход: {h_m} (❌)",
            parse_mode=ParseMode.HTML,
            reply_markup=ttt_board_kb(game_id, game["board"], sz),
        )
        return

    # ── TTT move ────────────────────────────────────────
    if data.startswith("ttt:"):
        parts = data.split(":")
        if parts[1] == "noop":
            await query.answer()
            return

        game_id = parts[1]
        cell    = int(parts[2])
        game    = ttt_games.get(game_id)

        if not game:
            await query.answer("❌ Игра не найдена", show_alert=True)
            return
        if game["state"] != "playing":
            await query.answer("❌ Игра завершена", show_alert=True)
            return

        is_host = who.id == game["host_id"]
        is_opp  = who.id == game["opp_id"]
        if not is_host and not is_opp:
            await query.answer("❌ Ты не участник!", show_alert=True)
            return

        if game["turn"] == "host" and not is_host:
            await query.answer("⏳ Сейчас ход ❌ (крестиков)!", show_alert=True)
            return
        if game["turn"] == "opp" and not is_opp:
            await query.answer("⏳ Сейчас ход ⭕ (ноликов)!", show_alert=True)
            return

        if game["board"][cell]:
            await query.answer("❌ Клетка уже занята!", show_alert=True)
            return

        game["board"][cell] = "X" if game["turn"] == "host" else "O"

        h_m = mention(game["host_id"], game["host_name"])
        o_m = mention(game["opp_id"],  game["opp_name"])
        bet = game["bet"]
        board_snap = game["board"][:]

        sz = game.get("size", 3)
        wn = game.get("win",  3)
        winner = ttt_check_winner(game["board"], sz, wn)
        if winner:
            game["state"] = "over"
            w_id   = game["host_id"] if winner == "X" else game["opp_id"]
            w_name = game["host_name"] if winner == "X" else game["opp_name"]
            l_id   = game["opp_id"]   if winner == "X" else game["host_id"]
            del ttt_games[game_id]

            await db_deduct_vrf(l_id, cid, bet)
            new_bal = await db_add_vrf(w_id, cid, bet)
            await db_add_xp(w_id, cid, XP_PER_WIN)
            await db_add_xp(l_id, cid, XP_PER_GAME)
            await db_record_game(w_id, cid, won=True)
            await db_record_game(l_id, cid, won=False)

            await query.answer(f"🏆 {w_name} победил!")
            await query.edit_message_text(
                f"❌⭕ <b>Крестики-нолики — Итог!</b>\n\n"
                f"❌ {h_m}\n"
                f"⭕ {o_m}\n\n"
                f"🏆 Победитель: <b>{mention(w_id, w_name)}</b>\n"
                f"💎 +{bet} VRF → Баланс: {fmt(new_bal)} VRF",
                parse_mode=ParseMode.HTML,
                reply_markup=ttt_board_kb(game_id, board_snap, sz, locked=True),
            )
            return

        if all(game["board"]):
            game["state"] = "over"
            del ttt_games[game_id]
            await db_record_game(game["host_id"], cid, won=False, draw=True)
            await db_record_game(game["opp_id"],  cid, won=False, draw=True)
            await query.answer("🤝 Ничья!")
            await query.edit_message_text(
                f"❌⭕ <b>Крестики-нолики — Ничья!</b>\n\n"
                f"❌ {h_m}\n"
                f"⭕ {o_m}\n\n"
                f"🤝 Ничья! Ставки возвращены.",
                parse_mode=ParseMode.HTML,
                reply_markup=ttt_board_kb(game_id, board_snap, sz, locked=True),
            )
            return

        # Continue
        game["turn"] = "opp" if game["turn"] == "host" else "host"
        next_m   = h_m if game["turn"] == "host" else o_m
        next_sym = "❌" if game["turn"] == "host" else "⭕"

        await query.answer()
        await query.edit_message_text(
            f"❌⭕ <b>Крестики-нолики!</b>\n\n"
            f"❌ {h_m}\n"
            f"⭕ {o_m}\n\n"
            f"📐 Поле: <b>{sz}×{sz}</b> | Победа: <b>{wn} в ряд</b>\n"
            f"💎 Ставка: <b>{bet} VRF</b>\n\n"
            f"🎮 Ход: {next_m} ({next_sym})",
            parse_mode=ParseMode.HTML,
            reply_markup=ttt_board_kb(game_id, game["board"], sz),
        )
        return

    # ── Mines Game ───────────────────────────────────────
    if data.startswith("mg:"):
        parts  = data.split(":")
        action = parts[1]

        if action == "noop":
            await query.answer()
            return

        if action == "cancel":
            await query.answer("Отменено")
            try:
                await query.message.delete()
            except TelegramError:
                pass
            return

        if action == "new":
            # Show bet selection again
            await query.answer()
            uu = await db_get_user(who.id, cid)
            bal = uu["vrf"] if uu else 0
            await query.edit_message_text(
                f"💣 <b>Мины</b>\n\n"
                f"💎 Баланс: <b>{fmt(bal)} VRF</b>\n\n"
                f"Выбери ставку:",
                parse_mode=ParseMode.HTML,
                reply_markup=_mines_bet_kb(who.id, cid),
            )
            return

        if action == "b":  # bet selected → choose mines count
            uid2 = int(parts[2])
            cid2 = int(parts[3])
            bet  = int(parts[4])
            if who.id != uid2:
                await query.answer("❌ Это не твоя кнопка!", show_alert=True)
                return
            uu = await db_get_user(uid2, cid2)
            if not uu or uu["vrf"] < bet:
                await query.answer(f"❌ Нужно {bet} VRF, у тебя {uu['vrf'] if uu else 0}", show_alert=True)
                return
            await query.answer()
            # Build mines count buttons with multiplier hints
            hint_rows = []
            for mc in [3, 5, 10, 15]:
                m1  = calc_mines_mult(1,  mc)
                m5  = calc_mines_mult(5,  mc)
                m10 = calc_mines_mult(10, mc)
                hint_rows.append(
                    f"  💣 <b>{mc} мин</b> → 1-й: {m1}×  5-й: {m5}×  10-й: {m10}×"
                )
            mines_kb = InlineKeyboardMarkup([
                [InlineKeyboardButton(f"💣 {mc} мин", callback_data=f"mg:mc:{uid2}:{cid2}:{mc}:{bet}")
                 for mc in [3, 5]],
                [InlineKeyboardButton(f"💣 {mc} мин", callback_data=f"mg:mc:{uid2}:{cid2}:{mc}:{bet}")
                 for mc in [10, 15]],
                [SBtn("Назад", style="primary", callback_data="mg:new")],
            ])
            await query.edit_message_text(
                f"💣 <b>Мины</b>  ·  Ставка: <b>{bet} VRF</b>\n\n"
                f"Выбери количество мин:\n"
                f"(больше мин = выше риск = выше множитель)\n\n"
                + "\n".join(hint_rows),
                parse_mode=ParseMode.HTML,
                reply_markup=mines_kb,
            )
            return

        if action == "mc":  # mines count chosen → start game
            uid2 = int(parts[2])
            cid2 = int(parts[3])
            mc   = int(parts[4])
            bet  = int(parts[5])
            if who.id != uid2:
                await query.answer("❌ Это не твоя кнопка!", show_alert=True)
                return
            key = f"{uid2}:{cid2}"
            if key in mines_games and mines_games[key]["state"] == "active":
                await query.answer("❌ У тебя уже есть активная игра!", show_alert=True)
                return
            if not await db_deduct_vrf(uid2, cid2, bet):
                await query.answer("❌ Недостаточно VRF!", show_alert=True)
                return
            # Generate grid
            mine_pos = set(random.sample(range(MINES_TOTAL), mc))
            mines_games[key] = {
                "user_id": uid2, "cid": cid2, "bet": bet, "mines_count": mc,
                "grid":     [i in mine_pos for i in range(MINES_TOTAL)],
                "revealed": [False] * MINES_TOTAL,
                "safe_revealed": 0, "state": "active",
            }
            await query.answer("🎮 Игра началась!")
            await query.edit_message_text(
                _mines_header(mines_games[key]),
                parse_mode=ParseMode.HTML,
                reply_markup=_mines_grid_kb(uid2, cid2, mines_games[key]),
            )
            return

        if action == "c":  # cell click
            uid2 = int(parts[2])
            cid2 = int(parts[3])
            idx  = int(parts[4])
            if who.id != uid2:
                await query.answer("❌ Это не твоя игра!", show_alert=True)
                return
            key  = f"{uid2}:{cid2}"
            game = mines_games.get(key)
            if not game or game["state"] != "active":
                await query.answer("❌ Игра не найдена или завершена", show_alert=True)
                return
            if game["revealed"][idx]:
                await query.answer("Уже открыто!", show_alert=True)
                return
            game["revealed"][idx] = True

            if game["grid"][idx]:  # 💣 BOMB
                game["state"] = "lost"
                del mines_games[key]
                await db_add_xp(uid2, cid2, XP_PER_GAME)
                await db_record_game(uid2, cid2, won=False)
                await query.answer("💥 БУМ!", show_alert=True)
                await query.edit_message_text(
                    f"<h2>{E_BOOM} БУМ! Мина!</h2>"
                    f"<table bordered>"
                    f"<tr><td>💎 Ставка</td><td align=\"right\"><s>{fmt(game['bet'])} VRF</s></td></tr>"
                    f"<tr><td>✅ Успел открыть</td><td align=\"right\"><b>{game['safe_revealed']}</b> клеток</td></tr>"
                    f"<tr><td>💣 Мин на поле</td><td align=\"right\"><b>{game['mines_count']}</b></td></tr>"
                    f"</table>"
                    f"<blockquote>Ставка <b>{fmt(game['bet'])} VRF</b> потеряна 😢</blockquote>",
                    parse_mode=ParseMode.HTML,
                    reply_markup=_mines_dead_kb(game, boom_idx=idx),
                )
            else:  # 💎 SAFE
                game["safe_revealed"] += 1
                safe_total = MINES_TOTAL - game["mines_count"]
                if game["safe_revealed"] == safe_total:  # All safe cells found!
                    game["state"] = "won"
                    mult   = calc_mines_mult(game["safe_revealed"], game["mines_count"])
                    payout = int(game["bet"] * mult)
                    del mines_games[key]
                    new_bal = await db_add_vrf(uid2, cid2, payout)
                    await db_add_xp(uid2, cid2, XP_PER_WIN)
                    await db_record_game(uid2, cid2, won=True)
                    await query.answer("🏆 Идеальная игра!", show_alert=True)
                    await query.edit_message_text(
                        f"🏆 <b>ИДЕАЛЬНО! Все клетки открыты!</b>\n\n"
                        f"💎 Ставка: <b>{fmt(game['bet'])} VRF</b>\n"
                        f"⚡ Множитель: <b>{mult}×</b>\n"
                        f"🏆 Выигрыш: <b>{fmt(payout)} VRF</b>\n"
                        f"💰 Баланс: <b>{fmt(new_bal)} VRF</b>",
                        parse_mode=ParseMode.HTML,
                        reply_markup=_mines_dead_kb(game),
                    )
                else:
                    mult = calc_mines_mult(game["safe_revealed"], game["mines_count"])
                    await query.answer(f"💎 Безопасно! Множитель: {mult}×")
                    await query.edit_message_text(
                        _mines_header(game),
                        parse_mode=ParseMode.HTML,
                        reply_markup=_mines_grid_kb(uid2, cid2, game),
                    )
            return

        if action == "co":  # cash out
            uid2 = int(parts[2])
            cid2 = int(parts[3])
            if who.id != uid2:
                await query.answer("❌ Это не твоя игра!", show_alert=True)
                return
            key  = f"{uid2}:{cid2}"
            game = mines_games.get(key)
            if not game or game["state"] != "active":
                await query.answer("❌ Игра не найдена или завершена", show_alert=True)
                return
            if game["safe_revealed"] == 0:
                await query.answer("❌ Сначала открой хотя бы одну клетку!", show_alert=True)
                return
            mult   = calc_mines_mult(game["safe_revealed"], game["mines_count"])
            payout = int(game["bet"] * mult)
            profit = payout - game["bet"]
            game["state"] = "won"
            del mines_games[key]
            new_bal = await db_add_vrf(uid2, cid2, payout)
            await db_add_xp(uid2, cid2, XP_PER_WIN)
            await db_record_game(uid2, cid2, won=True)
            await query.answer(f"💸 Забрал {fmt(payout)} VRF!", show_alert=True)
            await query.edit_message_text(
                f"<h3>💸 Выигрыш в Минах!</h3>"
                f"<table bordered striped>"
                f"<tr><td>💎 Ставка</td><td align=\"right\"><b>{fmt(game['bet'])} VRF</b></td></tr>"
                f"<tr><td>✅ Открыто</td><td align=\"right\"><b>{game['safe_revealed']}</b> клеток</td></tr>"
                f"<tr><td>⚡ Множитель</td><td align=\"right\"><b>{mult}×</b></td></tr>"
                f"<tr><td>🏆 Получено</td><td align=\"right\"><b>{fmt(payout)} VRF</b>"
                + (f" <mark>+{fmt(profit)}</mark>" if profit > 0 else "") +
                f"</td></tr>"
                f"<tr><td>💰 Баланс</td><td align=\"right\"><b>{fmt(new_bal)} VRF</b></td></tr>"
                f"</table>",
                parse_mode=ParseMode.HTML,
                reply_markup=_mines_dead_kb(game),
            )
            return

        if action == "q":  # quit → lose bet
            uid2 = int(parts[2])
            cid2 = int(parts[3])
            if who.id != uid2:
                await query.answer("❌ Это не твоя игра!", show_alert=True)
                return
            key  = f"{uid2}:{cid2}"
            game = mines_games.get(key)
            if not game or game["state"] != "active":
                await query.answer("❌ Игра не найдена", show_alert=True)
                return
            game["state"] = "quit"
            del mines_games[key]
            await db_record_game(uid2, cid2, won=False)
            await query.answer("🏳 Сдался")
            await query.edit_message_text(
                f"🏳 <b>Игра прекращена</b>\n\n"
                f"💎 Ставка <b>{fmt(game['bet'])} VRF</b> потеряна\n"
                f"✅ Было открыто: <b>{game['safe_revealed']}</b> клеток",
                parse_mode=ParseMode.HTML,
                reply_markup=_mines_dead_kb(game),
            )
            return

        await query.answer()
        return

    # ── Battleship: accept / decline ─────────────────────
    if data.startswith("bsj:") or data.startswith("bsd:"):
        game_id = data[4:]
        game    = battle_games.get(game_id)
        if not game:
            await query.answer("❌ Игра не найдена", show_alert=True)
            return
        if game["state"] != "waiting":
            await query.answer("❌ Уже началась или отменена", show_alert=True)
            return

        if data.startswith("bsd:"):
            if who.id != game["p2_id"]:
                await query.answer("❌ Это не твой вызов!", show_alert=True)
                return
            del battle_games[game_id]
            await query.answer("❌ Отказано")
            await query.edit_message_text(
                f"❌ {mention(who.id, who.first_name)} отказался от Морского боя.",
                parse_mode=ParseMode.HTML,
            )
            return

        # ── Accept ───────────────────────────────────────
        if who.id != game["p2_id"]:
            await query.answer("❌ Ты не соперник!", show_alert=True)
            return
        bet = game["bet"]
        p1u = await db_get_user(game["p1_id"], cid)
        p2u = await db_get_user(game["p2_id"], cid)
        if not p1u or p1u["vrf"] < bet:
            await query.answer("❌ У вызывающего недостаточно VRF!", show_alert=True)
            return
        if not p2u or p2u["vrf"] < bet:
            await query.answer("❌ У тебя недостаточно VRF!", show_alert=True)
            return

        game["grid1"] = _bs_place_ships(BS_SIZE, BS_SHIPS)
        game["grid2"] = _bs_place_ships(BS_SIZE, BS_SHIPS)
        game["state"] = "playing"
        await query.answer("🚢 Принято! Проверь личку бота.")

        # Send DM to each player
        failed = []
        for pn in (1, 2):
            p_is1  = pn == 1
            p_id   = game["p1_id"] if p_is1 else game["p2_id"]
            p_ogr  = game["grid2"] if p_is1 else game["grid1"]
            p_mysh = game["shots1"] if p_is1 else game["shots2"]
            try:
                dm = await context.bot.send_message(
                    chat_id=p_id,
                    text=_bs_player_text(game, pn),
                    parse_mode=ParseMode.HTML,
                    reply_markup=_bs_atk_kb(game_id, p_ogr, p_mysh, pn),
                )
                if p_is1:
                    game["p1_mid"] = dm.message_id
                else:
                    game["p2_mid"] = dm.message_id
            except TelegramError:
                failed.append(game["p1_name"] if p_is1 else game["p2_name"])

        if failed:
            del battle_games[game_id]
            await query.edit_message_text(
                f"❌ <b>Морской Бой не запущен!</b>\n\n"
                f"Игрок(и) <b>{', '.join(failed)}</b> не начали бота в личке.\n"
                f"Напишите боту /start в ЛС, затем попробуйте снова.",
                parse_mode=ParseMode.HTML,
            )
            return

        await query.edit_message_text(
            f"🚢 <b>МОРСКОЙ БОЙ НАЧАЛСЯ!</b>\n\n"
            f"⚔️ {mention(game['p1_id'], game['p1_name'])} vs "
            f"{mention(game['p2_id'], game['p2_name'])}\n"
            f"💎 Ставка: <b>{fmt(bet)} VRF</b>\n\n"
            f"📨 Игра идёт в <b>личных сообщениях!</b>\n"
            f"🎯 Первый ход: <b>{game['p1_name']}</b>",
            parse_mode=ParseMode.HTML,
        )
        return

    # ── Battleship: fire ──────────────────────────────────
    if data.startswith("bs:"):
        parts  = data.split(":")
        action = parts[1]

        if action in ("noop", "x"):
            await query.answer()
            return

        if action == "f" and len(parts) == 5:
            game_id = parts[2]
            pnum    = int(parts[3])
            cell    = int(parts[4])
            game    = battle_games.get(game_id)

            if not game or game["state"] != "playing":
                await query.answer("❌ Игра не найдена или завершена", show_alert=True)
                return

            is1 = pnum == 1
            pid = game["p1_id"] if is1 else game["p2_id"]
            if who.id != pid:
                await query.answer("❌ Это не твоя игра!", show_alert=True)
                return
            if game["turn"] != pnum:
                await query.answer("⏳ Сейчас не твой ход!", show_alert=True)
                return

            mysh = game["shots1"] if is1 else game["shots2"]
            opgr = game["grid2"] if is1 else game["grid1"]
            if mysh[cell]:
                await query.answer("Уже стрелял сюда!", show_alert=True)
                return

            mysh[cell] = True
            hit        = opgr[cell]
            await query.answer("💥 ПОПАДАНИЕ!" if hit else "🌊 Мимо!")

            # ── Check win ────────────────────────────────
            if _bs_alive(opgr, mysh) == 0:
                w_id   = pid
                w_name = game["p1_name"] if is1 else game["p2_name"]
                l_id   = game["p2_id"]   if is1 else game["p1_id"]
                l_name = game["p2_name"] if is1 else game["p1_name"]
                g_cid  = game["cid"]
                bet    = game["bet"]
                w_mid  = game["p1_mid"] if is1 else game["p2_mid"]
                l_mid  = game["p2_mid"] if is1 else game["p1_mid"]
                rev_shots = list(mysh)
                rev_opgr  = list(opgr)
                del battle_games[game_id]

                await db_deduct_vrf(l_id, g_cid, bet)
                new_bal = await db_add_vrf(w_id, g_cid, bet)
                await db_add_xp(w_id, g_cid, XP_PER_WIN)
                await db_add_xp(l_id, g_cid, XP_PER_GAME)
                await db_record_game(w_id, g_cid, won=True)
                await db_record_game(l_id, g_cid, won=False)

                try:
                    await context.bot.edit_message_text(
                        f"🏆 <b>ПОБЕДА!</b>\n\nТы потопил весь вражеский флот!\n\n"
                        f"💎 +{fmt(bet)} VRF  →  Баланс: {fmt(new_bal)} VRF",
                        chat_id=w_id, message_id=w_mid,
                        parse_mode=ParseMode.HTML,
                        reply_markup=_bs_atk_kb(game_id, rev_opgr, rev_shots, pnum, reveal=True),
                    )
                except TelegramError:
                    pass
                try:
                    await context.bot.edit_message_text(
                        f"💔 <b>ПОРАЖЕНИЕ!</b>\n\nТвой флот потоплен...\n\n"
                        f"💸 -{fmt(bet)} VRF",
                        chat_id=l_id, message_id=l_mid,
                        parse_mode=ParseMode.HTML,
                    )
                except TelegramError:
                    pass
                try:
                    await context.bot.send_message(
                        g_cid,
                        f"🚢 <b>МОРСКОЙ БОЙ — ФИНАЛ!</b>\n\n"
                        f"🏆 Победитель: {mention(w_id, w_name)}\n"
                        f"💔 Потоплен: {mention(l_id, l_name)}\n"
                        f"💎 Приз: <b>+{fmt(bet)} VRF</b>",
                        parse_mode=ParseMode.HTML,
                    )
                except TelegramError:
                    pass
                return

            # ── Continue: hit = same turn, miss = switch ─
            if not hit:
                game["turn"] = 2 if is1 else 1

            # Update both players' DMs
            for upn in (1, 2):
                up1    = upn == 1
                up_id  = game["p1_id"]  if up1 else game["p2_id"]
                up_mid = game["p1_mid"] if up1 else game["p2_mid"]
                up_ogr = game["grid2"]  if up1 else game["grid1"]
                up_sh  = game["shots1"] if up1 else game["shots2"]
                if up_mid is None:
                    continue
                try:
                    await context.bot.edit_message_text(
                        _bs_player_text(game, upn),
                        chat_id=up_id, message_id=up_mid,
                        parse_mode=ParseMode.HTML,
                        reply_markup=_bs_atk_kb(game_id, up_ogr, up_sh, upn),
                    )
                except TelegramError:
                    pass
            return

        await query.answer()
        return

    # ── Admin panel ──────────────────────────────────────
    if data.startswith("ap:"):
        uid   = who.id
        is_adm = await is_bot_admin(uid)
        if not is_adm:
            try:
                member = await query.message.chat.get_member(uid)
                is_adm = member.status in ("administrator", "creator")
            except TelegramError:
                pass
        if not is_adm:
            await query.answer("❌ Нет доступа", show_alert=True)
            return

        action  = data[3:]
        back_kb = InlineKeyboardMarkup([[SBtn("Назад", style="primary", callback_data="ap:back")]])

        if action == "back":
            await query.answer()
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("📊 Статистика",   callback_data="ap:stats"),
                 InlineKeyboardButton("🏆 Топ VRF",     callback_data="ap:top")],
                [InlineKeyboardButton("💑 Все браки",    callback_data="ap:marriages"),
                 InlineKeyboardButton("👮 Бот-админы",  callback_data="ap:admins")],
                [InlineKeyboardButton("📋 Все команды",  callback_data="ap:cmds"),
                 InlineKeyboardButton("ℹ️ Управление",  callback_data="ap:manage")],
                [SBtn("Закрыть", style="danger",      callback_data="ap:close")],
            ])
            await query.edit_message_text(
                f"🛡️ <b>Verifure Admin Panel</b>\n\n{E_ALERT} Выбери раздел:",
                parse_mode=ParseMode.HTML, reply_markup=kb,
            )

        elif action == "close":
            await query.answer("Закрыто")
            await query.message.delete()

        elif action == "stats":
            await query.answer()
            total = await db_count_users(cid)
            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute("SELECT COUNT(*) FROM marriages WHERE chat_id=?", (cid,)) as cur:
                    marriages = (await cur.fetchone())[0]
                async with db.execute("SELECT SUM(total_games),SUM(vrf),SUM(wins) FROM users WHERE chat_id=?", (cid,)) as cur:
                    row = await cur.fetchone()
                    games, vrf, wins = row[0] or 0, row[1] or 0, row[2] or 0
            await query.edit_message_text(
                f"📊 <b>Статистика чата</b>\n\n"
                f"👥 Игроков: <b>{total}</b>\n"
                f"🎮 Сыграно: <b>{fmt(games)}</b>\n"
                f"🏆 Побед: <b>{fmt(wins)}</b>\n"
                f"💎 VRF в обороте: <b>{fmt(vrf)}</b>\n"
                f"💒 Браков: <b>{marriages}</b>",
                parse_mode=ParseMode.HTML, reply_markup=back_kb,
            )

        elif action == "top":
            await query.answer()
            users = await db_top(cid, "vrf", 10)
            lines = ["💎 <b>Топ-10 VRF</b>\n"]
            for i, u in enumerate(users):
                medal = MEDALS[i] if i < len(MEDALS) else f"{i+1}."
                lines.append(
                    f"{medal} {mention(u['user_id'], u['first_name'])} — {fmt(u['vrf'])} VRF"
                    f" · {u['wins']}W/{u['losses']}L"
                )
            await query.edit_message_text("\n".join(lines), parse_mode=ParseMode.HTML, reply_markup=back_kb)

        elif action == "marriages":
            await query.answer()
            all_m = await db_all_marriages(cid)
            lines = [f"💑 <b>Все браки ({len(all_m)})</b>\n"]
            for i, m in enumerate(all_m[:10]):
                u1 = await db_get_user(m["user1_id"], cid)
                u2 = await db_get_user(m["user2_id"], cid)
                n1 = u1["first_name"] if u1 else "?"
                n2 = u2["first_name"] if u2 else "?"
                lines.append(f"{i+1}. {n1} ❤️ {n2} — {days_ago(m['married_at'])} дн.")
            await query.edit_message_text("\n".join(lines), parse_mode=ParseMode.HTML, reply_markup=back_kb)

        elif action == "admins":
            await query.answer()
            admins = await db_list_admins()
            lines  = ["👮 <b>Бот-администраторы</b>\n"]
            for a in admins:
                uname = f" @{a['username']}" if a["username"] else ""
                lines.append(f"• {a['first_name']}{uname}")
            if ADMIN_IDS:
                lines.append(f"\n🔧 Env: {', '.join(map(str, ADMIN_IDS))}")
            await query.edit_message_text("\n".join(lines), parse_mode=ParseMode.HTML, reply_markup=back_kb)

        elif action == "cmds":
            await query.answer()
            await query.edit_message_text(
                "📋 <b>Все команды</b>\n\n"
                "<b>Игроки:</b>\n"
                "/start /help /profile /top /stats /daily /bonus\n"
                "/marry /accept /reject /divorce /marriage /marriages\n"
                "/duel /cubes /basket /football /bowling /darts /slot\n"
                "/gift /love\n\n"
                "<b>Администраторы:</b>\n"
                "/admin /givevrf /takevrf /givebear\n"
                "/addadmin /removeadmin /listadmins",
                parse_mode=ParseMode.HTML, reply_markup=back_kb,
            )

        elif action == "manage":
            await query.answer()
            await query.edit_message_text(
                "ℹ️ <b>Управление игроками</b>\n\n"
                "/givevrf &lt;n&gt; — выдать VRF (ответом)\n"
                "/takevrf &lt;n&gt; — забрать VRF (ответом)\n"
                "/givebear — выдать медведя 🐻 (ответом)\n"
                "/addadmin — сделать бот-админом (ответом)\n"
                "/removeadmin — убрать бот-админа (ответом)",
                parse_mode=ParseMode.HTML, reply_markup=back_kb,
            )
        return

    await query.answer()


# ══════════════════════════════════════════════════════
#           MESSAGE HANDLER (XP from chat)
# ══════════════════════════════════════════════════════

async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    if update.effective_chat.type == "private":
        return
    u = update.effective_user
    if u.is_bot:
        return

    cid  = update.effective_chat.id
    text = (update.message.text or "").strip()
    low  = text.lower()
    pts  = low.split()
    word = pts[0] if pts else ""

    await db_ensure_user(u.id, cid, u.username or "", u.first_name)

    # ── Text shortcuts ────────────────────────────────────
    # б / баланс → balance
    if word in ("б", "баланс", "balance", "bal"):
        uu = await db_get_user(u.id, cid)
        bal = uu["vrf"] if uu else 0
        lvl = get_level(uu["experience"]) if uu else 1
        await update.message.reply_text(
            f"💎 {mention(u.id, u.first_name)}: <b>{fmt(bal)} VRF</b>  |  🏅 Ур. {lvl}",
            parse_mode=ParseMode.HTML,
        )
        return

    # отмена → cancel games
    if word in ("отмена", "стоп", "stop"):
        await cmd_cancel(update, context)
        return

    # топ → leaderboard
    if word in ("топ", "top", "лидеры"):
        await _show_top(update, context, cid, "vrf")
        return

    # проф / профиль → profile (reuse cmd_profile logic)
    if word in ("проф", "профиль", "профа", "пр"):
        context.args = []
        await cmd_profile(update, context)
        return

    # бонус → daily status
    if word in ("бонус", "bonus"):
        await cmd_bonus(update, context)
        return

    # ── Transfer: пер [сумма] (с реплеем или @username [сумма]) ─
    if word in ("пер", "перевод", "send", "tr"):
        sender = u
        amount_str = pts[1] if len(pts) > 1 else ""
        recipient  = None

        # Resolve recipient
        if update.message.reply_to_message and not update.message.reply_to_message.from_user.is_bot:
            recipient = update.message.reply_to_message.from_user
        elif len(pts) >= 3 and pts[1].startswith("@"):
            # "пер @username 500"
            uname_query = pts[1].lstrip("@").lower()
            amount_str  = pts[2] if len(pts) > 2 else ""
            async with aiosqlite.connect(DB_PATH) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(
                    "SELECT * FROM users WHERE LOWER(username)=? AND chat_id=? LIMIT 1",
                    (uname_query, cid)
                ) as cur:
                    row = await cur.fetchone()
            if row:
                class _FakeUser:
                    id = row["user_id"]
                    first_name = row["first_name"]
                    is_bot = False
                recipient = _FakeUser()
            else:
                await update.message.reply_text(f"❌ Пользователь @{uname_query} не найден в этом чате")
                return

        if not recipient:
            await update.message.reply_text(
                "❌ Ответь на сообщение получателя или укажи <b>@username</b>:\n"
                "<code>пер 500</code> (с реплеем) / <code>пер @username 500</code>",
                parse_mode=ParseMode.HTML,
            )
            return

        if recipient.id == sender.id:
            await update.message.reply_text("❌ Нельзя переводить себе!")
            return

        try:
            amount = int(amount_str.replace(",", "").replace(".", ""))
        except (ValueError, AttributeError):
            await update.message.reply_text("❌ Укажи сумму: <code>пер 500</code>", parse_mode=ParseMode.HTML)
            return

        if amount < 1:
            await update.message.reply_text("❌ Сумма должна быть минимум 1 VRF!")
            return

        await db_ensure_user(recipient.id, cid, getattr(recipient, "username", "") or "", recipient.first_name)
        su = await db_get_user(sender.id, cid)
        if su["vrf"] < amount:
            await update.message.reply_text(
                f"❌ Недостаточно VRF! Есть: <b>{fmt(su['vrf'])}</b>",
                parse_mode=ParseMode.HTML,
            )
            return

        await db_deduct_vrf(sender.id, cid, amount)
        new_bal = await db_add_vrf(recipient.id, cid, amount)

        await update.message.reply_text(
            f"💸 <b>Перевод!</b>\n\n"
            f"От: {mention(sender.id, sender.first_name)}\n"
            f"Кому: {mention(recipient.id, recipient.first_name)}\n"
            f"💎 Сумма: <b>{fmt(amount)} VRF</b>\n"
            f"💰 Баланс получателя: <b>{fmt(new_bal)} VRF</b>",
            parse_mode=ParseMode.HTML,
        )
        return

    # ── Cube dice: куб [1-6] [ставка] ─────────────────────
    if word in ("куб", "кубик", "dice") and len(pts) >= 3:
        try:
            val = int(pts[1])
            bet = int(pts[2].replace(",", ""))
        except ValueError:
            await update.message.reply_text(
                "❌ Формат: <code>куб [1-6] [ставка]</code>\nПример: <code>куб 4 500</code>",
                parse_mode=ParseMode.HTML,
            )
            return

        if not 1 <= val <= 6:
            await update.message.reply_text("❌ Число должно быть от <b>1</b> до <b>6</b>!", parse_mode=ParseMode.HTML)
            return
        if bet < 1:
            await update.message.reply_text("❌ Ставка минимум 1 VRF!")
            return

        uu = await db_get_user(u.id, cid)
        if uu["vrf"] < bet:
            await update.message.reply_text(
                f"❌ Недостаточно VRF! Есть: <b>{fmt(uu['vrf'])}</b>",
                parse_mode=ParseMode.HTML,
            )
            return

        dice_msg = await context.bot.send_dice(chat_id=cid, emoji="🎲")
        rolled   = dice_msg.dice.value
        await asyncio.sleep(4)

        if rolled == val:
            gain    = bet * 5
            new_bal = await db_add_vrf(u.id, cid, gain)
            await update.message.reply_text(
                f"🎲 Выпало <b>{rolled}</b> — УГАДАЛ! ✅\n\n"
                f"💎 +{fmt(gain)} VRF (×5)\n"
                f"💰 Баланс: <b>{fmt(new_bal)} VRF</b>",
                parse_mode=ParseMode.HTML,
            )
        else:
            new_bal = await db_deduct_vrf(u.id, cid, bet)
            await update.message.reply_text(
                f"🎲 Выпало <b>{rolled}</b> — промах! ❌\n\n"
                f"💸 -{fmt(bet)} VRF\n"
                f"💰 Баланс: <b>{fmt(new_bal)} VRF</b>",
                parse_mode=ParseMode.HTML,
            )
        return

    # ── XP from regular messages ──────────────────────────
    # Log every message to the daily activity chart
    await db_log_activity(cid, msgs=1)

    if not await db_can_earn_xp(u.id, cid):
        return

    xp = random.randint(XP_PER_MSG_MIN, XP_PER_MSG_MAX)
    m  = await db_get_marriage(u.id, cid)
    if m:
        xp = int(xp * 1.1)

    new_lvl, leveled_up = await db_add_xp(u.id, cid, xp)

    if leveled_up:
        rank_nm = get_rank(new_lvl)
        if new_lvl in MILESTONES:
            text = (
                f"{E_ALERT} <b>ОСОБЫЙ РУБЕЖ!</b>\n\n"
                f"{mention(u.id, u.first_name)} — <b>{new_lvl} уровень!</b>\n{rank_nm}\n\n"
                f"🏆 Поздравляем!"
            )
        else:
            tpls = [
                f"🎉 {mention(u.id, u.first_name)} — <b>уровень {new_lvl}!</b> {rank_nm}",
                f"⬆️ Новый уровень у {mention(u.id, u.first_name)}: <b>{new_lvl}!</b> {rank_nm}",
            ]
            text = random.choice(tpls)
        try:
            await update.message.reply_text(text, parse_mode=ParseMode.HTML)
            await _react(update, "🎉")
        except TelegramError:
            pass


# ══════════════════════════════════════════════════════
#                       MAIN
# ══════════════════════════════════════════════════════

async def on_startup(app: Application) -> None:
    await db_init()
    from telegram import BotCommand, BotCommandScopeAllGroupChats, BotCommandScopeDefault
    cmds = [
        BotCommand("start",    "🏠 Старт / Главное меню"),
        BotCommand("profile",  "👤 Мой профиль"),
        BotCommand("statsimg", "📊 Статистика картинкой"),
        BotCommand("activity", "📈 График активности чата [дней]"),
        BotCommand("top",      "🏆 Топ игроков"),
        BotCommand("stats",    "📊 Статистика чата"),
        BotCommand("daily",    "⚡ Ежедневный бонус"),
        BotCommand("bonus",    "📋 Статус бонусов"),
        BotCommand("ref",      "🔗 Реферальная ссылка (+VRF за друга)"),
        BotCommand("gift",     "🎁 Подарить VRF (ответом)"),
        BotCommand("love",     "💝 Любовь (ответом)"),
        BotCommand("duel",     "⚔️ Дуэль (ответом)"),
        BotCommand("cubes",    "🎲 Кубики (ответом)"),
        BotCommand("basket",   "🏀 Баскетбол (ответом)"),
        BotCommand("football", "⚽ Футбол (ответом)"),
        BotCommand("bowling",  "🎳 Боулинг (ответом)"),
        BotCommand("darts",    "🎯 Дартс (ответом)"),
        BotCommand("slot",     "🎰 Слот PvP (ответом)"),
        BotCommand("mines",    "💣 Мины — соло"),
        BotCommand("tictac",   "❌⭕ Крестики-нолики (ответом)"),
        BotCommand("seabattle","🚢 Морской Бой (ответом, PvP в ЛС)"),
        BotCommand("cancel",   "🚫 Отменить ожидающую игру"),
        BotCommand("marry",    "💒 Предложение"),
        BotCommand("marriage", "💑 Карточка брака"),
        BotCommand("marriages","👫 Все пары"),
        BotCommand("divorce",  "💔 Развод"),
        BotCommand("help",     "ℹ️ Помощь"),
    ]
    try:
        await app.bot.set_my_commands(cmds, scope=BotCommandScopeDefault())
        await app.bot.set_my_commands(cmds, scope=BotCommandScopeAllGroupChats())
    except Exception:
        pass
    log.info("Verifure Game 10.1 is online!")


def main() -> None:
    if not BOT_TOKEN:
        log.critical("BOT_TOKEN environment variable is not set!")
        raise SystemExit(1)

    app = Application.builder().token(BOT_TOKEN).post_init(on_startup).build()

    # Core
    app.add_handler(CommandHandler("start",    cmd_start))
    app.add_handler(CommandHandler("help",    cmd_help))

    # Profile
    app.add_handler(CommandHandler("profile", cmd_profile))
    app.add_handler(CommandHandler("statsimg",  cmd_statsimg))
    app.add_handler(CommandHandler("activity",  cmd_activity))
    app.add_handler(CommandHandler("top",     cmd_top))
    app.add_handler(CommandHandler(["leaderboard", "lb"], cmd_top))
    app.add_handler(CommandHandler("stats",   cmd_stats))
    app.add_handler(CommandHandler("daily",   cmd_daily))
    app.add_handler(CommandHandler("bonus",   cmd_bonus))
    app.add_handler(CommandHandler("ref",     cmd_ref))

    # Inline mode (@BotName in any chat)
    app.add_handler(InlineQueryHandler(on_inline_query))

    # Marriage
    app.add_handler(CommandHandler("marry",    cmd_marry))
    app.add_handler(CommandHandler("accept",   cmd_accept))
    app.add_handler(CommandHandler("reject",   cmd_reject))
    app.add_handler(CommandHandler("divorce",  cmd_divorce))
    app.add_handler(CommandHandler("marriage", cmd_marriage))
    app.add_handler(CommandHandler("marriages",cmd_marriages))

    # Social
    app.add_handler(CommandHandler("gift",    cmd_gift))
    app.add_handler(CommandHandler("love",    cmd_love))

    # Games
    app.add_handler(CommandHandler("duel",    cmd_duel))
    app.add_handler(CommandHandler("cubes",   cmd_cubes))
    app.add_handler(CommandHandler("basket",  cmd_basket))
    app.add_handler(CommandHandler("football",cmd_football))
    app.add_handler(CommandHandler("bowling", cmd_bowling))
    app.add_handler(CommandHandler("darts",   cmd_darts))
    app.add_handler(CommandHandler("slot",    cmd_slot))
    app.add_handler(CommandHandler("mines",   cmd_mines))
    app.add_handler(CommandHandler(["tictac", "ttt"], cmd_ttt))
    app.add_handler(CommandHandler("seabattle", cmd_seabattle))
    app.add_handler(CommandHandler("cancel", cmd_cancel))

    # Admin
    app.add_handler(CommandHandler("admin",        cmd_admin))
    app.add_handler(CommandHandler("givevrf",      cmd_givevrf))
    app.add_handler(CommandHandler("takevrf",      cmd_takevrf))
    app.add_handler(CommandHandler("givebear",     cmd_givebear))
    app.add_handler(CommandHandler("addadmin",     cmd_addadmin))
    app.add_handler(CommandHandler("removeadmin",  cmd_removeadmin))
    app.add_handler(CommandHandler("listadmins",   cmd_listadmins))

    # Callbacks & messages
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.Dice, on_casino_777))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))

    log.info("Starting polling...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
