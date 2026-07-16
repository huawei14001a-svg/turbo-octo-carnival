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
import threading
import uuid
from datetime import datetime, timedelta
from functools import wraps
from typing import Optional, Tuple

import aiosqlite
from telegram import (
    ChatPermissions,
    ForceReply,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQueryResultArticle,
    InputMediaPhoto,
    InputTextMessageContent,
    KeyboardButton,
    ReactionTypeEmoji,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
    WebAppInfo,
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
    MessageReactionHandler,
    TypeHandler,
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
WEBAPP_URL: str = os.getenv("WEBAPP_URL", "")  # Railway URL e.g. https://your-app.up.railway.app
# ⚠️ Bot API security update: с 20 июля 2026 Telegram по умолчанию запрещает
# Mini App'ам вызывать методы Mini App API с источников, отличных от
# домена самого Mini App'а. Наш /clicker — полностью самодостаточная HTML-
# страница без сторонних доменов/скриптов, так что это её не затрагивает.
# Если когда-нибудь начнём грузить сторонние ресурсы внутри Mini App —
# нужно либо привести их к домену WEBAPP_URL, либо отключить защиту через
# @BotFather (тогда ответственность за отсутствие ссылок на ненадёжные
# сайты внутри Mini App — на боте).

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

# ── Атаки на игроков (кража баланса у офлайн-пользователей) ──
# "Онлайн/офлайн" — это приближение: Bot API не даёт боту знать реальный
# статус присутствия пользователя, поэтому "офлайн" здесь означает
# "не проявлял активность в этом боте дольше ATTACK_OFFLINE_MIN минут".
ATTACK_COOLDOWN_MIN   = 20     # раз в сколько минут можно атаковать
ATTACK_OFFLINE_MIN    = 8      # цель должна молчать хотя бы столько минут
ATTACK_BASE_CHANCE    = 0.45   # базовый шанс успеха атаки
ATTACK_STEAL_PCT      = 0.15   # % баланса цели, который крадётся при успехе
ATTACK_MIN_TARGET_VRF = 100    # цель должна иметь хотя бы столько VRF
ATTACK_ROLE_BONUS     = 0.15   # бонус к шансу у роли "Налётчик"
ATTACK_DEFENSE_PENALTY_PER_LVL = 0.05   # штраф к шансу за уровень защиты клана цели

# ── Кланы ──────────────────────────────────────────────
CLAN_CREATE_COST      = 1000   # стоимость создания клана (спишется с автора)
CLAN_NAME_MIN, CLAN_NAME_MAX = 3, 24
CLAN_RAID_COOLDOWN_MIN = 90    # раз в сколько минут клан может рейдить
CLAN_RAID_BASE_CHANCE  = 0.40
CLAN_RAID_STEAL_PCT    = 0.12  # % казны цели при успешном рейде
CLAN_RAID_MIN_TREASURY = 200   # у цели должно быть хотя бы столько в казне
CLAN_DEFENSE_BASE_COST = 500   # цена апгрейда защиты — растёт с уровнем (×уровень)
CLAN_MAX_DEFENSE_LVL   = 10

CLAN_ROLES = {
    "raider":    {"emoji": "⚔️", "label": "Налётчик",
                 "desc": f"+{int(ATTACK_ROLE_BONUS*100)}% к шансу успеха в атаках/рейдах"},
    "defender":  {"emoji": "🛡", "label": "Страж",
                 "desc": "Усиливает защиту казны клана от чужих рейдов"},
    "treasurer": {"emoji": "💰", "label": "Казначей",
                 "desc": "Может выводить VRF из казны клана"},
    "member":    {"emoji": "👤", "label": "Житель",
                 "desc": "Без особых бонусов — просто участник клана"},
}

# ── Ферма (заменяет обычный ежедневный бонус, часть уходит в казну) ──
FARM_COOLDOWN_H   = 3
FARM_BASE_MIN     = 30
FARM_BASE_MAX     = 80
FARM_CLAN_SHARE   = 0.30   # доля фарма, которая автоматически уходит в казну клана

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
giveaway_setups: dict = {}   # key: setup_id (str) — Giveaway wizard
giveaway_active: dict = {}   # key: f"{cid}:{msg_id}" — Active giveaway
crash_rounds: dict    = {}   # key: cid (int) — Crash multiplier game
crash_setups: dict    = {}   # key: setup_id (str) — Crash setup wizard
crash_custom_pending: dict = {}  # key: (cid, uid) — waiting for a custom bet amount

# ══════════════════════════════════════════════════════
#               LEVEL / RANK SYSTEM
# ══════════════════════════════════════════════════════

def xp_for_level(n: int) -> int:
    return 0 if n <= 1 else 50 * n * (n - 1)

def get_level(xp: int) -> int:
    # Solve 50*n*(n-1) = xp  →  n = (1 + sqrt(1 + 4*xp/50)) / 2
    # The old code used 8*xp/50 which caused xp_for_level(n) to return n+1.
    if xp <= 0:
        return 1
    n = int((1 + math.sqrt(1 + 4 * xp / 50)) / 2)
    # Guard against floating-point overshoot at exact level thresholds
    while n < 100 and xp_for_level(n + 1) <= xp:
        n += 1
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
    tl(25, LY1 + 8, f"Ур. {lvl}  >  {lvl+1}", f12, MUTED)
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
    blocks: list = None,
    media: list = None,
) -> bool:
    """
    Send via sendRichMessage (tables, headings, lists…) with fallback to plain HTML.
    html=          → rich HTML content (full sendRichMessage tags)
    fallback_html= → simple HTML for regular send_message
    markdown=      → rich Markdown alternative (used when html/blocks are empty)
    blocks=        → Bot API 10.1+ structured InputRichBlock list (takes priority
                      over html/markdown when given — see rich_* builders below)
    media=         → Bot API 10.2 InputRichMessageMedia list, used together with
                      html/markdown when they reference tg://photo?id=/video?id=/audio?id=
    """
    fb_text = fallback_html or html or markdown

    # ── Try sendRichMessage ───────────────────────────
    if blocks:
        rich_msg: dict = {"blocks": blocks}
    elif html:
        rich_msg = {"html": html}
    else:
        rich_msg = {"markdown": markdown or " "}
    if media:
        rich_msg["media"] = media

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
#   RICH BLOCKS  🧱  (Bot API 10.1 — InputRichBlock* builders)
# ══════════════════════════════════════════════════════
# PTB не имеет типизированных классов для этих новых объектов, поэтому
# собираем обычные dict'ы точно по схеме InputRichBlock* — sendRichMessage
# принимает их напрямую через rich_message.blocks (см. send_rich выше).
# Используется, например, в /chatinfo и админ-панели (ap:stats).

def rich_heading(text, size: int = 2) -> dict:
    return {"type": "heading", "text": text, "size": max(1, min(6, size))}


def rich_paragraph(text) -> dict:
    return {"type": "paragraph", "text": text}


def rich_footer(text) -> dict:
    return {"type": "footer", "text": text}


def rich_divider() -> dict:
    return {"type": "divider"}


def rich_table_cell(text=None, header: bool = False, align: str = None,
                    colspan: int = None, rowspan: int = None) -> dict:
    cell: dict = {}
    if text is not None:
        cell["text"] = text
    if header:
        cell["is_header"] = True
    if align:
        cell["align"] = align
    if colspan and colspan > 1:
        cell["colspan"] = colspan
    if rowspan and rowspan > 1:
        cell["rowspan"] = rowspan
    return cell


def rich_table(cells: list, bordered: bool = True, striped: bool = True, caption=None) -> dict:
    d: dict = {"type": "table", "cells": cells}
    if bordered:
        d["is_bordered"] = True
    if striped:
        d["is_striped"] = True
    if caption:
        d["caption"] = caption
    return d


def rich_list_item(content, has_checkbox: bool = False, is_checked: bool = False) -> dict:
    blocks = [rich_paragraph(content)] if isinstance(content, str) else content
    item: dict = {"blocks": blocks}
    if has_checkbox:
        item["has_checkbox"] = True
        if is_checked:
            item["is_checked"] = True
    return item


def rich_list(items: list) -> dict:
    return {"type": "list", "items": items}


def rich_blockquote(blocks: list, credit=None) -> dict:
    d: dict = {"type": "blockquote", "blocks": blocks}
    if credit:
        d["credit"] = credit
    return d


def rich_pullquote(text, credit=None) -> dict:
    d: dict = {"type": "pullquote", "text": text}
    if credit:
        d["credit"] = credit
    return d


def rich_details(summary, blocks: list, is_open: bool = False) -> dict:
    d: dict = {"type": "details", "summary": summary, "blocks": blocks}
    if is_open:
        d["is_open"] = True
    return d


# ── InputRichMessageMedia (Bot API 10.2) ─────────────────
# Позволяет явно передать медиафайлы, на которые ссылается html/markdown
# через tg://photo?id=XXX, tg://video?id=XXX, tg://audio?id=XXX. Используются
# вместе с send_rich(..., media=[...]) при html=/markdown=.

def rich_media_photo(media_id: str, file) -> dict:
    return {"id": media_id, "media": {"type": "photo", "media": file}}


def rich_media_video(media_id: str, file) -> dict:
    return {"id": media_id, "media": {"type": "video", "media": file}}


def rich_media_audio(media_id: str, file) -> dict:
    return {"id": media_id, "media": {"type": "audio", "media": file}}


def rich_media_voice_note(media_id: str, file) -> dict:
    """InputMediaVoiceNote (Bot API 10.2) — голосовое сообщение как медиа
    внутри расширенного сообщения (ссылка tg://audio?id=... в тексте)."""
    return {"id": media_id, "media": {"type": "voice_note", "media": file}}


def rich_media_animation(media_id: str, file) -> dict:
    return {"id": media_id, "media": {"type": "animation", "media": file}}


# ══════════════════════════════════════════════════════
#   EPHEMERAL MESSAGES  👻  (Bot API 10.2)
# ══════════════════════════════════════════════════════
# Сообщение, отправленное с receiver_user_id, в группе видно ТОЛЬКО
# указанному пользователю + боту (остальные участники его не видят) —
# удобно для приватных вещей вроде админ-панели или личного баланса
# без спама в общий чат. PTB может ещё не знать про эти параметры/методы,
# поэтому всё идёт через do_api_request с аккуратным откатом на обычные
# send_message/edit_message_text/delete_message, если сервер не поддерживает.

async def is_bot_chat_admin(bot, chat_id: int) -> bool:
    """Проверяет, является ли сам бот администратором чата — при этом
    эфемерные сообщения можно слать любому участнику в любой момент,
    без callback_query_id / reply_parameters.ephemeral_message_id."""
    try:
        me = await bot.get_me()
        member = await bot.get_chat_member(chat_id, me.id)
        return member.status in ("administrator", "creator")
    except Exception:
        return False


async def send_ephemeral(
    bot, chat_id: int, receiver_user_id: int, text: str,
    reply_markup=None, reply_to_id: int = None, parse_mode=ParseMode.HTML,
    callback_query_id: str = None, ephemeral_reply_message_id: int = None,
    bot_is_admin: bool = None,
) -> Optional[dict]:
    """Пытается отправить эфемерное сообщение (видно только receiver_user_id).

    По правилам Bot API 10.2 запрос валиден ТОЛЬКО если выполнено одно из:
      1) передан callback_query_id — ответ на нажатие кнопки (в течение 15с);
      2) передан ephemeral_reply_message_id — ответ на входящее эфемерное
         сообщение (через reply_parameters.ephemeral_message_id);
      3) бот сам является администратором чата — тогда можно всегда,
         без (1) и (2). Проверяется автоматически, если bot_is_admin
         не передан явно (лишний API-вызов get_chat_member).

    Если ни одно из условий не выполнено — не шлём запрос вообще (чтобы не
    получить в ответ обычное видимое всем сообщение по ошибке), возвращаем
    None. Вызывающий код сам решает, что делать дальше (обычно — обычное
    сообщение как fallback).

    Возвращает распарсенный Message при успехе (там будет ephemeral_message_id),
    иначе None."""
    if bot_is_admin is None and not callback_query_id and not ephemeral_reply_message_id:
        bot_is_admin = await is_bot_chat_admin(bot, chat_id)

    if not (callback_query_id or ephemeral_reply_message_id or bot_is_admin):
        log.debug("send_ephemeral: none of callback_query_id/ephemeral_reply/admin — skipping, "
                  "would just send a normal visible message")
        return None

    kw: dict = {
        "chat_id": chat_id, "text": text,
        "receiver_user_id": receiver_user_id, "parse_mode": parse_mode,
    }
    if callback_query_id:
        kw["callback_query_id"] = callback_query_id
    if ephemeral_reply_message_id:
        kw["reply_parameters"] = {"ephemeral_message_id": ephemeral_reply_message_id}
    elif reply_to_id:
        kw["reply_parameters"] = {"message_id": reply_to_id}
    if reply_markup:
        try:
            kw["reply_markup"] = reply_markup.to_dict()
        except Exception:
            pass
    try:
        result = await bot.do_api_request("sendMessage", api_kwargs=kw)
        # Настоящее эфемерное сообщение обязано вернуть ephemeral_message_id —
        # если его нет, сервер молча прислал обычное сообщение (не поддерживает
        # ещё эту функцию), и нельзя считать это успехом приватной доставки.
        if isinstance(result, dict) and result.get("ephemeral_message_id"):
            return result
        log.debug("send_ephemeral: server accepted the call but returned no "
                 "ephemeral_message_id — feature likely not live yet on this server")
        return None
    except Exception as e:
        log.debug("send_ephemeral request failed: %s", e)
        return None


async def send_ephemeral_or_normal(
    bot, chat_id: int, receiver_user_id: int, text: str,
    reply_markup=None, reply_to_id: int = None, parse_mode=ParseMode.HTML,
    callback_query_id: str = None, ephemeral_reply_message_id: int = None,
    bot_is_admin: bool = None,
):
    """Как send_ephemeral, но с гарантированной доставкой: если эфемерный
    режим недоступен на сервере (или условия для него не выполнены) —
    просто шлёт обычное сообщение (ответом), чтобы пользователь точно
    получил ответ."""
    result = await send_ephemeral(
        bot, chat_id, receiver_user_id, text,
        reply_markup=reply_markup, reply_to_id=reply_to_id, parse_mode=parse_mode,
        callback_query_id=callback_query_id,
        ephemeral_reply_message_id=ephemeral_reply_message_id,
        bot_is_admin=bot_is_admin,
    )
    if result is not None:
        return result
    try:
        return await bot.send_message(
            chat_id=chat_id, text=text, parse_mode=parse_mode,
            reply_markup=reply_markup,
            reply_parameters={"message_id": reply_to_id} if reply_to_id else None,
        )
    except Exception:
        return None


async def edit_ephemeral_text(bot, chat_id: int, ephemeral_message_id: int,
                              text: str, reply_markup=None, parse_mode=ParseMode.HTML) -> bool:
    kw = {"chat_id": chat_id, "ephemeral_message_id": ephemeral_message_id,
          "text": text, "parse_mode": parse_mode}
    if reply_markup:
        try:
            kw["reply_markup"] = reply_markup.to_dict()
        except Exception:
            pass
    try:
        await bot.do_api_request("editEphemeralMessageText", api_kwargs=kw)
        return True
    except Exception as e:
        log.debug("editEphemeralMessageText unavailable: %s", e)
        return False


async def delete_ephemeral(bot, chat_id: int, ephemeral_message_id: int) -> bool:
    try:
        await bot.do_api_request(
            "deleteEphemeralMessage",
            api_kwargs={"chat_id": chat_id, "ephemeral_message_id": ephemeral_message_id},
        )
        return True
    except Exception as e:
        log.debug("deleteEphemeralMessage unavailable: %s", e)
        return False


# ══════════════════════════════════════════════════════
#   ПРИВАТНАЯ ДОСТАВКА  🔒  (реально работает уже сейчас)
# ══════════════════════════════════════════════════════
# receiver_user_id/эфемерные сообщения (Bot API 10.2, выше) на практике
# ещё не активны на серверах Telegram — вызов тихо откатывается на обычное
# сообщение, то есть его всё ещё видно всем в чате. Это НЕ настоящая
# приватность. Для реально приватной доставки прямо сейчас есть только
# один рабочий путь — личные сообщения (ЛС) бота с пользователем.
# Ограничение Telegram: бот не может первым написать пользователю, пока
# тот хотя бы раз не нажал /start в ЛС с ботом — если это ещё не
# произошло, оставляем короткую подсказку в группе с кнопкой запуска ЛС.

async def send_private_or_prompt(
    context, group_chat_id: int, user, text: str,
    reply_markup=None, prompt_reply_to_id: int = None,
) -> bool:
    """Пытается отправить `text` пользователю в ЛС (обычным send_message —
    у send_rich() все исключения гасятся внутри, поэтому для надёжного
    определения успеха/неудачи он тут не годится). При успехе возвращает
    True и в группе ничего лишнего не появляется. Если бот не может писать
    в ЛС (пользователь не жал /start боту) — оставляет короткую публичную
    подсказку с кнопкой «Открыть ЛС» и возвращает False."""
    try:
        await context.bot.send_message(
            chat_id=user.id, text=text, parse_mode=ParseMode.HTML,
            reply_markup=reply_markup,
        )
        return True
    except TelegramError as e:
        log.debug("Can't DM user %s yet: %s", user.id, e)

    # Не получилось — пользователь ещё не открывал ЛС с ботом
    try:
        bot_username = (await context.bot.get_me()).username
        start_url = f"https://t.me/{bot_username}?start=hi"
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("💬 Открыть ЛС с ботом", url=start_url),
        ]])
        await context.bot.send_message(
            chat_id=group_chat_id,
            text=(f"🔒 {mention(user.id, user.first_name)}, это приватная информация — "
                  f"я не могу написать тебе в ЛС, пока ты не нажмёшь /start у бота.\n"
                  f"Открой ЛС и повтори команду."),
            parse_mode=ParseMode.HTML,
            reply_markup=kb,
            reply_parameters={"message_id": prompt_reply_to_id} if prompt_reply_to_id else None,
        )
    except TelegramError:
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

            CREATE TABLE IF NOT EXISTS mutes (
                user_id  INTEGER NOT NULL,
                chat_id  INTEGER NOT NULL,
                muted_by INTEGER NOT NULL,
                muted_at TEXT    NOT NULL,
                until    TEXT    DEFAULT NULL,
                reason   TEXT    DEFAULT '',
                PRIMARY KEY (user_id, chat_id)
            );

            CREATE TABLE IF NOT EXISTS warns (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id   INTEGER NOT NULL,
                chat_id   INTEGER NOT NULL,
                warned_by INTEGER NOT NULL,
                warned_at TEXT    NOT NULL,
                reason    TEXT    DEFAULT '',
                active    INTEGER DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS referrals (
                user_id       INTEGER PRIMARY KEY,
                inviter_id    INTEGER NOT NULL,
                claimed_at    TEXT    NOT NULL,
                new_user_paid INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS clans (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id       INTEGER NOT NULL,
                name          TEXT    NOT NULL,
                leader_id     INTEGER NOT NULL,
                treasury      REAL    DEFAULT 0,
                defense_level INTEGER DEFAULT 1,
                created_at    TEXT    NOT NULL,
                UNIQUE (chat_id, name)
            );

            CREATE TABLE IF NOT EXISTS clan_members (
                user_id   INTEGER NOT NULL,
                chat_id   INTEGER NOT NULL,
                clan_id   INTEGER NOT NULL,
                role      TEXT    DEFAULT 'member',
                joined_at TEXT    NOT NULL,
                PRIMARY KEY (user_id, chat_id)
            );

            CREATE TABLE IF NOT EXISTS clan_applications (
                user_id    INTEGER NOT NULL,
                chat_id    INTEGER NOT NULL,
                clan_id    INTEGER NOT NULL,
                applied_at TEXT    NOT NULL,
                PRIMARY KEY (user_id, chat_id)
            );

            CREATE TABLE IF NOT EXISTS attack_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id     INTEGER NOT NULL,
                attacker_id INTEGER NOT NULL,
                target_type TEXT    NOT NULL,
                target_id   INTEGER NOT NULL,
                success     INTEGER NOT NULL,
                amount      REAL    DEFAULT 0,
                ts          TEXT    NOT NULL
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
            "ALTER TABLE users ADD COLUMN last_active     TEXT DEFAULT NULL",
            "ALTER TABLE users ADD COLUMN last_attack     TEXT DEFAULT NULL",
            "ALTER TABLE users ADD COLUMN last_farm       TEXT DEFAULT NULL",
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

        # Pay out a pending "new user" referral bonus the first time this
        # user gets a row in ANY chat (covers the case where they clicked
        # the referral link before ever talking to the bot in a group).
        async with db.execute(
            "SELECT 1 FROM referrals WHERE user_id=? AND new_user_paid=0", (uid,)
        ) as cur:
            pending = await cur.fetchone()
        if pending:
            await db.execute(
                "UPDATE users SET vrf=vrf+? WHERE user_id=? AND chat_id=?",
                (REFERRAL_BONUS_NEW, uid, cid),
            )
            await db.execute(
                "UPDATE referrals SET new_user_paid=1 WHERE user_id=?", (uid,)
            )
            await db.commit()


async def db_claim_referral(new_uid: int, inviter_id: int) -> bool:
    """
    Atomically record a referral claim. Returns True the first time this
    user_id is ever claimed (caller should pay out bonuses), False if
    already claimed before (no-op — prevents repeat/duplicate farming).
    """
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute(
                "INSERT INTO referrals (user_id, inviter_id, claimed_at) VALUES (?,?,?)",
                (new_uid, inviter_id, _now()),
            )
            await db.commit()
            return True
        except Exception:
            # PRIMARY KEY conflict (already claimed) — fail closed, no bonus.
            return False


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


async def db_touch_active(uid: int, cid: int) -> None:
    """Отмечает пользователя как 'недавно активного' — вызывается на каждое
    сообщение/команду. 'Офлайн' для атак = давно не было такой отметки."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET last_active=? WHERE user_id=? AND chat_id=?",
            (_now(), uid, cid),
        )
        await db.commit()


async def _touch_active_hook(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Глобальный хук (group=-1, выполняется первым): считает ЛЮБОЕ действие
    пользователя в группе (сообщение, команду, нажатие кнопки) признаком
    'онлайн'. Не мешает остальным хендлерам — ничего не возвращает/не глотает."""
    u = update.effective_user
    c = update.effective_chat
    if not u or not c or u.is_bot or c.type == "private":
        return
    try:
        await db_ensure_user(u.id, c.id, u.username or "", u.first_name)
        await db_touch_active(u.id, c.id)
    except Exception:
        pass


def user_is_offline(u: dict) -> bool:
    la = u.get("last_active")
    if not la:
        return True
    try:
        idle_min = (datetime.now() - datetime.fromisoformat(la)).total_seconds() / 60
    except Exception:
        return True
    return idle_min >= ATTACK_OFFLINE_MIN


# ── Кланы ────────────────────────────────────────────────

async def db_create_clan(cid: int, name: str, leader_id: int) -> Optional[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            cur = await db.execute(
                "INSERT INTO clans (chat_id, name, leader_id, treasury, defense_level, created_at) "
                "VALUES (?,?,?,0,1,?)",
                (cid, name, leader_id, _now()),
            )
            await db.execute(
                "INSERT INTO clan_members (user_id, chat_id, clan_id, role, joined_at) VALUES (?,?,?,?,?)",
                (leader_id, cid, cur.lastrowid, "leader", _now()),
            )
            await db.commit()
            return cur.lastrowid
        except Exception:
            return None


async def db_get_clan(clan_id: int) -> Optional[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM clans WHERE id=?", (clan_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def db_get_clan_by_name(cid: int, name: str) -> Optional[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM clans WHERE chat_id=? AND LOWER(name)=?", (cid, name.lower())
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def db_get_user_clan(uid: int, cid: int) -> Optional[dict]:
    """Клан пользователя + его роль в нём, одним запросом."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT c.*, m.role AS my_role FROM clan_members m
               JOIN clans c ON c.id = m.clan_id
               WHERE m.user_id=? AND m.chat_id=?""",
            (uid, cid),
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def db_list_clans(cid: int) -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT c.*, COUNT(m.user_id) AS member_count FROM clans c
               LEFT JOIN clan_members m ON m.clan_id = c.id
               WHERE c.chat_id=? GROUP BY c.id ORDER BY c.treasury DESC""",
            (cid,),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def db_get_clan_members(clan_id: int) -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT m.*, u.first_name, u.username, u.vrf FROM clan_members m
               JOIN users u ON u.user_id = m.user_id AND u.chat_id = m.chat_id
               WHERE m.clan_id=? ORDER BY
                 CASE m.role WHEN 'leader' THEN 0 ELSE 1 END, m.joined_at""",
            (clan_id,),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def db_add_clan_member(uid: int, cid: int, clan_id: int, role: str = "member") -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO clan_members (user_id, chat_id, clan_id, role, joined_at) "
            "VALUES (?,?,?,?,?)",
            (uid, cid, clan_id, role, _now()),
        )
        await db.commit()


async def db_remove_clan_member(uid: int, cid: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM clan_members WHERE user_id=? AND chat_id=?", (uid, cid))
        await db.commit()


async def db_set_member_role(uid: int, cid: int, role: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE clan_members SET role=? WHERE user_id=? AND chat_id=?", (role, uid, cid)
        )
        await db.commit()


async def db_delete_clan(clan_id: int, cid: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM clans WHERE id=?", (clan_id,))
        await db.execute("DELETE FROM clan_members WHERE clan_id=?", (clan_id,))
        await db.execute("DELETE FROM clan_applications WHERE clan_id=?", (clan_id,))
        await db.commit()


async def db_clan_treasury_add(clan_id: int, amount: float) -> float:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE clans SET treasury=treasury+? WHERE id=?", (amount, clan_id))
        await db.commit()
        async with db.execute("SELECT treasury FROM clans WHERE id=?", (clan_id,)) as cur:
            row = await cur.fetchone()
            return row[0] if row else 0.0


async def db_clan_treasury_sub(clan_id: int, amount: float) -> bool:
    clan = await db_get_clan(clan_id)
    if not clan or clan["treasury"] < amount:
        return False
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE clans SET treasury=treasury-? WHERE id=?", (amount, clan_id))
        await db.commit()
    return True


async def db_clan_set_defense(clan_id: int, level: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE clans SET defense_level=? WHERE id=?", (level, clan_id))
        await db.commit()


# ── Заявки в клан ──────────────────────────────────────

async def db_apply_to_clan(uid: int, cid: int, clan_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute(
                "INSERT INTO clan_applications (user_id, chat_id, clan_id, applied_at) VALUES (?,?,?,?)",
                (uid, cid, clan_id, _now()),
            )
            await db.commit()
            return True
        except Exception:
            return False


async def db_get_application(uid: int, cid: int) -> Optional[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM clan_applications WHERE user_id=? AND chat_id=?", (uid, cid)
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def db_get_clan_applications(clan_id: int) -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT a.*, u.first_name, u.username FROM clan_applications a
               JOIN users u ON u.user_id=a.user_id AND u.chat_id=a.chat_id
               WHERE a.clan_id=? ORDER BY a.applied_at""",
            (clan_id,),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def db_remove_application(uid: int, cid: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM clan_applications WHERE user_id=? AND chat_id=?", (uid, cid))
        await db.commit()


# ── Атаки ──────────────────────────────────────────────

async def db_log_attack(cid: int, attacker_id: int, target_type: str, target_id: int,
                        success: bool, amount: float) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO attack_log (chat_id, attacker_id, target_type, target_id, success, amount, ts) "
            "VALUES (?,?,?,?,?,?,?)",
            (cid, attacker_id, target_type, target_id, int(success), amount, _now()),
        )
        await db.execute(
            "UPDATE users SET last_attack=? WHERE user_id=? AND chat_id=?",
            (_now(), attacker_id, cid),
        )
        await db.commit()


def attack_cooldown_left(u: dict, cooldown_min: int) -> int:
    la = u.get("last_attack")
    if not la:
        return 0
    elapsed = (datetime.now() - datetime.fromisoformat(la)).total_seconds()
    left = cooldown_min * 60 - elapsed
    return max(0, int(left))


async def db_clan_last_raid(clan_id: int) -> Optional[str]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            """SELECT ts FROM attack_log WHERE attacker_id=-? AND target_type='clan_raid_marker'
               ORDER BY ts DESC LIMIT 1""",
            (clan_id,),
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else None


async def db_clan_mark_raid(clan_id: int) -> None:
    """Отдельная 'метка' времени последнего рейда клана — attacker_id=-clan_id
    (отрицательный), чтобы не заводить отдельную таблицу под один timestamp."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO attack_log (chat_id, attacker_id, target_type, target_id, success, amount, ts) "
            "VALUES (0, ?, 'clan_raid_marker', 0, 1, 0, ?)",
            (-clan_id, _now()),
        )
        await db.commit()


# ── Фарм ───────────────────────────────────────────────

def farm_cooldown_left(u: dict) -> int:
    lf = u.get("last_farm")
    if not lf:
        return 0
    elapsed = (datetime.now() - datetime.fromisoformat(lf)).total_seconds()
    left = FARM_COOLDOWN_H * 3600 - elapsed
    return max(0, int(left))


async def db_touch_farm(uid: int, cid: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET last_farm=? WHERE user_id=? AND chat_id=?", (_now(), uid, cid)
        )
        await db.commit()


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
    # Child-bot owners are super-admins in their own clone
    if uid in _child_bot_owners.values():
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
    safe = str(name).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return f'<a href="tg://user?id={uid}">{safe}</a>'

def fmt(n) -> str:
    n = int(round(n))
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
                claimed = await db_claim_referral(u.id, inviter_id)
                if claimed:
                    # Credit the inviter across every chat they're already in
                    async with aiosqlite.connect(DB_PATH) as db:
                        await db.execute(
                            "UPDATE users SET vrf=vrf+?, referral_count=referral_count+1 "
                            "WHERE user_id=?",
                            (REFERRAL_BONUS_INVITER, inviter_id),
                        )
                        await db.commit()
                        async with db.execute(
                            "SELECT COUNT(*) FROM users WHERE user_id=?", (u.id,)
                        ) as cur:
                            has_rows = (await cur.fetchone())[0] > 0

                    new_user_msg = (
                        f"🎉 <b>Реферальный бонус!</b>\n\n"
                        f"Ты зарегистрировался по ссылке от друга!\n"
                    )
                    if has_rows:
                        # Already has a group row somewhere — pay out now.
                        async with aiosqlite.connect(DB_PATH) as db:
                            await db.execute(
                                "UPDATE users SET vrf=vrf+? WHERE user_id=?",
                                (REFERRAL_BONUS_NEW, u.id),
                            )
                            await db.execute(
                                "UPDATE referrals SET new_user_paid=1 WHERE user_id=?",
                                (u.id,),
                            )
                            await db.commit()
                        new_user_msg += f"💎 +{fmt(REFERRAL_BONUS_NEW)} VRF тебе на счёт!"
                    else:
                        # No group row yet — db_ensure_user will pay this out
                        # automatically the first time you write in a group.
                        new_user_msg += (
                            f"💎 +{fmt(REFERRAL_BONUS_NEW)} VRF зачислятся, как только "
                            f"напишешь что-нибудь в группе с ботом!"
                        )

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
                    await update.message.reply_text(new_user_msg, parse_mode=ParseMode.HTML)

    # ── Константа кнопок — одинакова везде ─────────────
    _API_URL = "https://t.me/VerifureBot?startapp=db0bc7a5f6a70d9c"
    _MAIN_KB  = InlineKeyboardMarkup([[
        InlineKeyboardButton("🤖 Создать своего бота",
                             callback_data="start:create_bot"),
        InlineKeyboardButton("🔗 Наше API", url=_API_URL),
    ]])

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
            "<li>💥 Краш · 🏢 Башня · 🏰 Лабиринт</li>"
            "</ul>"
            "<hr/>"
            f"<blockquote>💎 Стартовый баланс: <b>{STARTING_VRF} VRF</b></blockquote>"
            "<footer>📌 Добавь меня в группу и напиши /start</footer>"
        )
        fb_h = (
            "👋 <b>Привет! Я Verifure Game</b>\n\n"
            f"💎 Стартовый баланс: <b>{STARTING_VRF} VRF</b>\n\n"
            "⚔️ Дуэль · 🎲 Кубики · 🏀 Баскетбол · ⚽ Футбол\n"
            "🎳 Боулинг · 🎯 Дартс · 🎰 Слот · 💣 Мины · ❌⭕ Крестики\n"
            "💥 Краш · 🏢 Башня · 🏰 Лабиринт\n\n"
            "📌 Добавь меня в группу и напиши /start"
        )

        # Child bot attribution
        my_bot_id = context.bot.id
        if my_bot_id in _child_bot_owners:
            settings = await _mb_get_settings(my_bot_id)
            welcome  = settings.get("welcome_text", "") if settings else ""
            if welcome:
                await update.message.reply_text(
                    welcome + "\n\n"
                    "<i>🤖 Создан через <a href=\"https://t.me/VerifureGameBot\">@VerifureGameBot</a></i>",
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                    reply_markup=_MAIN_KB,
                )
                return
            fb_h += "\n\n<i>🤖 Создан через <a href=\"https://t.me/VerifureGameBot\">@VerifureGameBot</a></i>"

        await send_rich(context.bot, cid, html=rich_h, fallback_html=fb_h,
                        reply_to_id=update.message.message_id,
                        reply_markup=_MAIN_KB)
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
        "<li>/crash — 💥 Краш <i>(весь чат)</i></li>"
        "<li>/tower — 🏢 Башня · /maze — 🏰 Лабиринт</li>"
        "<li>/daily — ⚡ Ежедневный бонус</li>"
        "</ul>"
        "<footer>📖 /help — посмотреть все команды</footer>"
    )
    fb_h = (
        f"👋 Привет, {mention(u.id, u.first_name)}!\n\n"
        f"💎 Баланс: <b>{fmt(bal)} VRF</b>\n\n"
        "⚔️ /duel · 🎲 /cubes · 🎰 /slot · 💣 /mines\n"
        "💥 /crash · 🏢 /tower · 🏰 /maze\n"
        "⚡ /daily · 📖 /help"
    )
    await send_rich(context.bot, cid, html=rich_h, fallback_html=fb_h,
                    reply_to_id=update.message.message_id,
                    reply_markup=_MAIN_KB)




async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cid = update.effective_chat.id
    rich_h = (
        "<h1>📖 Verifure Game — Помощь</h1>"
        "<h3>👤 Профиль & Активность</h3>"
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
        "<li>/crash — 🚀 Краш <i>(множитель растёт, забери до взрыва — весь чат)</i></li>"
        "<li>/giveaway — 🎁 Розыгрыш медведей среди реакций</li>"
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
        f"<li>🎁 Подарок: <b>{GIFT_COST} VRF</b> → <b>{GIFT_REWARD} VRF</b> получателю</li>"
        "<li>🐻 Медведь за каждые <b>10 побед</b></li>"
        f"<li>🔗 Реферал: <b>+{REFERRAL_BONUS_INVITER} VRF</b> тебе & <b>+{REFERRAL_BONUS_NEW} VRF</b> другу</li>"
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
    """Send group activity chart (messages + games per day)."""
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
            "📊 <b>Данных пока нет</b>\n\n"
            "Активность начнёт отслеживаться с этого момента. "
            "Напишите что-нибудь в чат и запустите /statsimg снова!",
            parse_mode=ParseMode.HTML,
        )
        return

    loop      = asyncio.get_running_loop()
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
            f"📈 <b>Статистика активности — {days} дн.</b>\n\n"
            f"💬 Сообщений: <b>{fmt(total_msgs)}</b>\n"
            f"🎮 Игр сыграно: <b>{fmt(total_games)}</b>"
        ),
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

    loop      = asyncio.get_running_loop()
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
#              BEAR GIVEAWAY 🐻🎁
# ══════════════════════════════════════════════════════

GW_REACT_EMOJIS = [
    "❤", "👍", "🔥", "🎉", "🥰", "👏",
    "😁", "🤔", "💯", "⚡", "🏆", "🐳",
    "😢", "🤩", "🙏", "👌", "😍", "🎃",
    "🤣", "💔", "😱", "🤩", "🥱", "😎",
]

# ── Keyboard builders ─────────────────────────────────

def _gw_kb_react(sid: str) -> InlineKeyboardMarkup:
    """Step 1: choose reaction (or any)."""
    rows = []
    for i in range(0, len(GW_REACT_EMOJIS), 6):
        rows.append([
            SBtn(e, style="primary", callback_data=f"gws:{sid}:r:{e}")
            for e in GW_REACT_EMOJIS[i:i+6]
        ])
    rows.append([SBtn("✨ Любую реакцию", style="success",
                      callback_data=f"gws:{sid}:r:any")])
    rows.append([SBtn("Отмена", style="danger",
                      callback_data=f"gws:{sid}:cancel")])
    return InlineKeyboardMarkup(rows)


def _gw_kb_bw(sid: str) -> InlineKeyboardMarkup:
    """Step 2: bears per winner × number of winners.
    Без ограничения по "балансу" — медведи не накапливаются внутренним
    счётчиком бота, их реально раздают админы (как подарки в Telegram),
    поэтому организатор розыгрыша сам решает, сколько разыграть."""
    presets = [(1,1),(1,2),(1,3),(2,1),(2,2),(3,1),(5,1),(3,3),(5,5),(10,1)]
    rows, row = [], []
    for b, w in presets:
        row.append(SBtn(f"{b}🐻×{w}", style="primary",
                        callback_data=f"gws:{sid}:bw:{b}:{w}"))
        if len(row) == 4:
            rows.append(row); row = []
    if row:
        rows.append(row)
    rows.append([SBtn("Отмена", style="danger",
                      callback_data=f"gws:{sid}:cancel")])
    return InlineKeyboardMarkup(rows)


def _gw_kb_time(sid: str) -> InlineKeyboardMarkup:
    """Step 3: choose duration."""
    return InlineKeyboardMarkup([
        [
            SBtn("1 мин",  style="primary", callback_data=f"gws:{sid}:t:1"),
            SBtn("3 мин",  style="primary", callback_data=f"gws:{sid}:t:3"),
            SBtn("5 мин",  style="primary", callback_data=f"gws:{sid}:t:5"),
        ],
        [
            SBtn("10 мин", style="primary", callback_data=f"gws:{sid}:t:10"),
            SBtn("15 мин", style="primary", callback_data=f"gws:{sid}:t:15"),
            SBtn("30 мин", style="primary", callback_data=f"gws:{sid}:t:30"),
        ],
        [SBtn("Отмена", style="danger", callback_data=f"gws:{sid}:cancel")],
    ])


def _gw_kb_confirm(sid: str) -> InlineKeyboardMarkup:
    """Step 4: confirm & launch."""
    return InlineKeyboardMarkup([
        [SBtn("🚀 Запустить розыгрыш!", style="success",
              callback_data=f"gws:{sid}:go")],
        [SBtn("Отмена", style="danger",
              callback_data=f"gws:{sid}:cancel")],
    ])


def _gw_active_text(gw: dict) -> str:
    """Live text for the giveaway message."""
    react_str  = f"«{gw['reaction']}»" if gw.get("reaction") else "любую реакцию"
    elapsed    = (datetime.now() - gw["start_time"]).total_seconds()
    remaining  = max(0, gw["minutes"] * 60 - elapsed)
    return (
        f"🐻 <b>РОЗЫГРЫШ МЕДВЕДЕЙ!</b>\n\n"
        f"🎁 Приз: <b>{gw['bears']}🐻</b> каждому из <b>{gw['winners']}</b> победителей\n"
        f"👇 Поставь {react_str} на это сообщение!\n\n"
        f"⏱ Осталось: <b>{fmt_cd(int(remaining))}</b>\n"
        f"👥 Участников: <b>{len(gw['participants'])}</b>\n\n"
        f"🔮 Победители выбираются случайно!"
    )


# ── Core giveaway logic ───────────────────────────────

async def _end_giveaway(bot, key: str) -> None:
    """Pick winners, award bears, edit the giveaway message."""
    gw = giveaway_active.pop(key, None)
    if not gw:
        return   # already ended or never existed (double-fire guard)

    cid       = gw["cid"]
    msg_id    = gw["msg_id"]
    org_id    = gw["org_id"]
    bears     = gw["bears"]
    winners_n = gw["winners"]
    parts     = list(gw["participants"])

    # ── No participants → просто ничья, награда никому не идёт ────
    # (раньше тут "возвращали" медведи организатору — но раз мы больше
    # не списываем их при старте розыгрыша, это превратилось бы в
    # бесплатный фарm медведей из ничего)
    if not parts:
        try:
            await bot.edit_message_text(
                f"🐻 <b>Розыгрыш завершён</b>\n\n"
                f"😔 Никто не поставил реакцию...",
                chat_id=cid, message_id=msg_id,
                parse_mode=ParseMode.HTML,
            )
        except TelegramError:
            pass
        return

    # ── Pick random winners ───────────────────────────
    actual = min(winners_n, len(parts))
    winners = random.sample(parts, actual)

    async with aiosqlite.connect(DB_PATH) as db:
        for w_id in winners:
            await db.execute(
                "UPDATE users SET bears=bears+? WHERE user_id=? AND chat_id=?",
                (bears, w_id, cid),
            )
        await db.commit()

    # ── Announce ──────────────────────────────────────
    lines = "\n".join(
        f"{'🥇' if i==0 else '🏆'} {mention(w_id, f'Победитель {i+1}')}"
        for i, w_id in enumerate(winners)
    )
    result = (
        f"🐻🎉 <b>РОЗЫГРЫШ ЗАВЕРШЁН!</b>\n\n"
        f"Победители ({actual} из {len(parts)} участников):\n"
        f"{lines}\n\n"
        f"🎁 Каждый получает: <b>{bears}🐻</b>"
    )
    try:
        await bot.edit_message_text(
            result, chat_id=cid, message_id=msg_id,
            parse_mode=ParseMode.HTML,
        )
    except TelegramError:
        try:
            await bot.send_message(cid, result,
                                   parse_mode=ParseMode.HTML,
                                   reply_to_message_id=msg_id)
        except TelegramError:
            pass

    # React with 🎉 on the finished giveaway message
    try:
        await bot.set_message_reaction(
            chat_id=cid, message_id=msg_id,
            reaction=[ReactionTypeEmoji("🎉")],
        )
    except TelegramError:
        pass


async def _giveaway_timer(bot, key: str, sid: str) -> None:
    """Background task: countdown updates + end trigger."""
    gw = giveaway_active.get(key)
    if not gw:
        return

    total   = gw["minutes"] * 60
    elapsed = 0
    step    = 60   # update interval (seconds)

    while elapsed < total:
        sleep_for = min(step, total - elapsed)
        await asyncio.sleep(sleep_for)
        elapsed += sleep_for

        gw = giveaway_active.get(key)
        if not gw or gw["state"] != "active":
            return

        if elapsed < total:
            # Update countdown
            try:
                await bot.edit_message_text(
                    _gw_active_text(gw),
                    chat_id=gw["cid"], message_id=gw["msg_id"],
                    parse_mode=ParseMode.HTML,
                )
            except TelegramError:
                pass

    await _end_giveaway(bot, key)
    giveaway_setups.pop(sid, None)


# ── Reaction tracking handler ─────────────────────────

async def on_reaction(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle MessageReactionUpdated — track giveaway participants."""
    mr   = update.message_reaction
    if not mr:
        return
    user = mr.user
    if not user or user.is_bot:
        return   # Anonymous or bot reactions can't be tracked

    key = f"{mr.chat.id}:{mr.message_id}"
    gw  = giveaway_active.get(key)
    if not gw or gw["state"] != "active":
        return

    required = gw["reaction"]   # None = accept any reaction

    def _has(reactions: list) -> bool:
        if not reactions:
            return False
        if required is None:
            return True
        for r in reactions:
            if isinstance(r, ReactionTypeEmoji) and r.emoji == required:
                return True
        return False

    had = _has(mr.old_reaction)
    has = _has(mr.new_reaction)

    if has and not had:
        gw["participants"].add(user.id)
    elif had and not has:
        gw["participants"].discard(user.id)


# ── /giveaway command ─────────────────────────────────

@only_groups
async def cmd_giveaway(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Launch the bear giveaway wizard.
    Медведи не проверяются по внутреннему балансу бота — их реально выдают
    админы как подарки прямо в Telegram, бот их не отслеживает 1:1, поэтому
    любой может настроить и запустить розыгрыш без проверки "баланса"."""
    u   = update.effective_user
    cid = update.effective_chat.id
    await db_ensure_user(u.id, cid, u.username or "", u.first_name)

    sid = str(uuid.uuid4())[:8]
    giveaway_setups[sid] = {
        "cid": cid, "org_id": u.id, "org_name": u.first_name,
        "reaction": None, "bears": 1, "winners": 1, "minutes": 5,
    }

    await update.message.reply_text(
        f"🐻 <b>Розыгрыш медведей</b>\n\n"
        f"<b>Шаг 1 / 3</b> — Выбери реакцию для участия:",
        parse_mode=ParseMode.HTML,
        reply_markup=_gw_kb_react(sid),
    )


# ══════════════════════════════════════════════════════
#              CRASH 🚀  (live multiplier, whole-chat)
# ══════════════════════════════════════════════════════
# Every player in the chat can join one round with their own bet.
# A multiplier climbs in real time; cash out before the rocket
# crashes to win bet × multiplier. Miss the window and you lose
# the bet. The whole chat plays the SAME round simultaneously.

CRASH_JOIN_SECONDS    = 20
CRASH_TICK_SECONDS    = 1.2
CRASH_GROWTH_K        = math.log(2) / 7        # multiplier doubles ~every 7s
CRASH_MAX_MULT        = 100.0
CRASH_INSTANT_CHANCE  = 0.04                    # 4% instant 1.00x crash
CRASH_RTP             = 0.96
CRASH_BET_PRESETS     = [25, 50, 100, 250, 500]


def _crash_point() -> float:
    """Provably-fair-style crash point generator (house edge baked in)."""
    r = random.random()
    if r < CRASH_INSTANT_CHANCE:
        return 1.00
    cp = CRASH_RTP / (1 - r)
    return round(min(CRASH_MAX_MULT, max(1.00, cp)), 2)


def _crash_mult_at(elapsed: float) -> float:
    return round(min(CRASH_MAX_MULT, math.exp(CRASH_GROWTH_K * elapsed)), 2)


def _crash_emoji(mult: float) -> str:
    if mult >= 10: return "⚡"
    if mult >= 5:  return "🔥"
    return "🚀"


def _crash_flavor(mult: float) -> str:
    if mult < 1.5: return "Взлёт!"
    if mult < 3:   return "Набираем высоту"
    if mult < 8:   return "Открытый космос"
    if mult < 20:  return "Глубокий космос"
    return "На пределе!"


# ══════════════════════════════════════════════════════
#   CRASH — Rocket image generator 🎨  (Pillow, 640×860)
# ══════════════════════════════════════════════════════
# Vertical portrait scene. Rocket ascends from launch pad
# at the bottom to deep space at the top. mode:
#   "pad"    — idle on the launch pad (sent at round start)
#   "flight" — ascending, multiplier baked into the image (every tick)
#   "crash"  — explosion burst at the final multiplier (round end)

_CR_W, _CR_H = 640, 860

_CR_SKY_LO   = (15, 40, 90)
_CR_SKY_MID  = (8, 18, 55)
_CR_SPACE    = (4, 7, 20)
_CR_GROUND   = (38, 48, 72)
_CR_CLOUD    = (210, 218, 230)
_CR_ROCK_W   = (230, 236, 244)
_CR_ROCK_G   = (170, 182, 200)
_CR_ENGINE   = (120, 130, 148)
_CR_STRIPE   = (255, 140, 40)
_CR_WIN_C    = (80, 138, 220)
_CR_FL_LO    = (255, 240, 180)
_CR_FL_MD    = (255, 165, 40)
_CR_FL_HI    = (255, 80, 45)
_CR_NEBULA_A = (20, 10, 60)
_CR_NEBULA_B = (40, 5, 30)

_crash_star_pool_cache: Optional[list] = None


def _cr_lerp(a: tuple, b: tuple, t: float) -> tuple:
    t = max(0.0, min(1.0, t))
    return tuple(round(a[i] + (b[i]-a[i])*t) for i in range(3))


def _cr_bg(frac: float) -> tuple:
    if frac < 0.45:
        return _cr_lerp(_CR_SKY_LO, _CR_SKY_MID, frac / 0.45)
    return _cr_lerp(_CR_SKY_MID, _CR_SPACE, (frac-0.45)/0.55)


def _cr_flame_color(frac: float) -> tuple:
    if frac < 0.4: return _cr_lerp(_CR_FL_LO, _CR_FL_MD, frac/0.4)
    return _cr_lerp(_CR_FL_MD, _CR_FL_HI, (frac-0.4)/0.6)


def _cr_star_pool() -> list:
    global _crash_star_pool_cache
    if _crash_star_pool_cache is not None:
        return _crash_star_pool_cache
    rng = random.Random(42)
    pool = []
    for _ in range(110):
        x  = rng.uniform(0, _CR_W)
        y  = rng.uniform(0, _CR_H * 0.88)
        r  = rng.uniform(0.5, 2.2)
        op = rng.uniform(0.25, 1.0)
        rv = rng.uniform(0.0, 0.9)
        pool.append((x, y, r, op, rv))
    _crash_star_pool_cache = pool
    return pool


def _cr_draw_stars(draw, frac: float) -> None:
    for x, y, r, op, rv in _cr_star_pool():
        if rv > frac: continue
        alpha = min(1.0, (frac - rv) / 0.08) * op
        s = round(255 * alpha)
        draw.ellipse([x-r, y-r, x+r, y+r], fill=(s, s, min(255, s+14)))


def _cr_draw_background(img, draw, frac: float) -> None:
    bg = _cr_bg(frac)
    img.paste(bg, [0, 0, _CR_W, _CR_H])
    if frac < 0.55:
        for band in range(0, _CR_H, 4):
            t = band / _CR_H
            lo = _cr_lerp(bg, _cr_lerp(bg, (20, 60, 130), 0.4), 1 - t)
            draw.rectangle([0, band, _CR_W, band+4], fill=lo)
    if frac > 0.35:
        sf = min(1.0, (frac-0.35)/0.5)
        for band in range(0, _CR_H, 3):
            t = band / _CR_H
            base = _cr_lerp(bg, _CR_SPACE, t*0.4)
            neb  = _cr_lerp(base,
                             _CR_NEBULA_A if t < 0.5 else _CR_NEBULA_B,
                             sf * 0.15 * (1-abs(t-0.5)*2))
            draw.rectangle([0, band, _CR_W, band+3], fill=neb)


def _cr_draw_ground(draw, frac: float) -> None:
    if frac > 0.18: return
    alpha = 1.0 - frac / 0.18
    gy = _CR_H - 80
    for dy in range(80):
        col = _cr_lerp(_CR_GROUND, (25, 35, 55), dy/80)
        draw.rectangle([0, gy+dy, _CR_W, gy+dy+1], fill=col)
    pc = tuple(round(c*alpha + b*(1-alpha)) for c, b in zip((55,65,90), _cr_bg(frac)))
    draw.rectangle([160, gy+8, 480, gy+18], fill=pc)
    for x in [220, 295, 345, 420]:
        draw.rectangle([x-3, gy+18, x+3, gy+62], fill=pc)
    draw.rectangle([460, gy-55, 478, gy+70], fill=pc)
    for h in range(-55, 70, 14):
        draw.line([(460, gy+h), (506, gy+h-17)], fill=pc, width=2)


def _cr_draw_clouds(draw, frac: float) -> None:
    if frac < 0.08 or frac > 0.55: return
    peak = 0.28
    alph = max(0.0, 1.0 - abs(frac-peak)/0.20) * 0.7
    if alph <= 0: return
    cy = _CR_H * (0.72 - frac*0.5)
    bg = _cr_bg(frac)
    for (cx, ry, rx, ry2) in [(95, cy, 42, 0.30), (62, cy+20, 28, 0.28),
                               (545, cy+12, 38, 0.30), (572, cy-8, 26, 0.26)]:
        col = tuple(round(_CR_CLOUD[i]*alph + bg[i]*(1-alph)) for i in range(3))
        draw.ellipse([cx-rx, ry-ry*ry2, cx+rx, ry+ry*ry2], fill=col)


def _cr_draw_rocket(draw, cx: float, nose_y: float, frac: float) -> None:
    fc   = _cr_flame_color(frac)
    bg   = _cr_bg(frac)
    BW, BH, NH, EBH, EBW, FW = 46, 120, 55, 32, 52, 28

    body_top = nose_y + NH
    body_bot = body_top + BH
    eng_top  = body_bot
    eng_bot  = eng_top + EBH

    trail_len = 36 + frac * (_CR_H * 0.67)
    flame_len = 28 + frac * 20
    flame_tip_y = eng_bot + flame_len
    for i in range(7):
        t0 = i / 7
        y0 = flame_tip_y + trail_len * t0
        y1 = flame_tip_y + trail_len * (i+1)/7
        w0, w1 = 8 + EBW*0.55*t0, 8 + EBW*0.55*(i+1)/7
        col = _cr_lerp(fc, bg, 0.18 + t0*0.82)
        draw.polygon([(cx-w0/2,y0),(cx+w0/2,y0),(cx+w1/2,y1),(cx-w1/2,y1)], fill=col)

    for mult, col in [(1.0, fc), (0.62, _cr_lerp(_CR_FL_LO, fc, 0.4)), (0.28, (255,255,255))]:
        fw2 = EBW*0.55*mult
        draw.polygon([(cx-fw2/2,eng_bot),(cx+fw2/2,eng_bot),(cx,flame_tip_y)], fill=col)

    draw.polygon([(cx-BW//2,eng_top),(cx+BW//2,eng_top),
                  (cx+EBW//2,eng_bot),(cx-EBW//2,eng_bot)], fill=_CR_ENGINE)
    draw.polygon([(cx-BW//2+6,eng_top+2),(cx+BW//2-6,eng_top+2),
                  (cx+EBW//2-10,eng_bot-4),(cx-EBW//2+10,eng_bot-4)],
                 fill=_cr_lerp(_CR_ENGINE,(200,210,225),0.25))
    draw.rectangle([cx-EBW//2-2,eng_bot-3,cx+EBW//2+2,eng_bot+2],
                   fill=_cr_lerp(_CR_ENGINE,_CR_ROCK_G,0.5))

    for side in (-1, 1):
        bx2 = cx + side * BW//2
        draw.polygon([(bx2, body_bot-30),(bx2, eng_bot),
                      (bx2+side*FW, eng_bot+12),(bx2+side*FW*0.6, body_bot-40)],
                     fill=_CR_ROCK_G)
        draw.line([(bx2+side*FW*0.6, body_bot-40),(bx2+side*FW, eng_bot+12)],
                  fill=_CR_ROCK_W, width=1)

    draw.rounded_rectangle([cx-BW//2,body_top,cx+BW//2,body_bot], radius=8, fill=_CR_ROCK_W)
    for py in range(int(body_top)+20, int(body_bot)-10, 22):
        draw.line([(cx-BW//2+4,py),(cx+BW//2-4,py)],
                  fill=_cr_lerp(_CR_ROCK_W,_CR_ROCK_G,0.25), width=1)
    sy = body_top + BH*0.68
    draw.rectangle([cx-BW//2,sy,cx+BW//2,sy+8], fill=_CR_STRIPE)
    draw.rectangle([cx-BW//2,sy,cx+BW//2,sy+3], fill=_cr_lerp(_CR_STRIPE,(255,255,255),0.35))

    wcy, wr = body_top + BH*0.35, 11
    draw.ellipse([cx-wr,wcy-wr,cx+wr,wcy+wr], fill=_cr_lerp(_CR_WIN_C,(0,0,0),0.35))
    draw.ellipse([cx-wr+2,wcy-wr+2,cx+wr-2,wcy-wr+2+wr],
                 fill=_cr_lerp(_CR_WIN_C,(255,255,255),0.35))

    fh = 28
    draw.polygon([(cx-BW//2,body_top),(cx+BW//2,body_top),
                  (cx+BW//2-10,body_top-fh),(cx-BW//2+10,body_top-fh)], fill=_CR_ROCK_W)
    draw.line([(cx-BW//2,body_top),(cx-BW//2+10,body_top-fh)], fill=_CR_ROCK_G, width=1)
    draw.line([(cx+BW//2,body_top),(cx+BW//2-10,body_top-fh)], fill=_CR_ROCK_G, width=1)

    nc_base_w = BW - 20
    nc_base_y = body_top - fh
    draw.polygon([(cx-nc_base_w//2,nc_base_y),(cx+nc_base_w//2,nc_base_y),
                  (cx,nose_y)], fill=_CR_ROCK_W)
    draw.polygon([(cx,nose_y),(cx,nc_base_y),(cx+nc_base_w//2,nc_base_y)],
                 fill=_cr_lerp(_CR_ROCK_W,_CR_ROCK_G,0.22))


def _cr_font(paths: list, size: int):
    from PIL import ImageFont
    for p in paths:
        try:
            return ImageFont.truetype(p, size)
        except (OSError, IOError):
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _cr_draw_hud(draw, mode: str, frac: float, label_main: str, label_sub: str) -> None:
    _BOLD = ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]
    _REG  = ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
    # Zone labels: Cyrillic can't render with PIL default font on some servers.
    # Visual height of rocket already conveys altitude zone to the player.
    # (labels suppressed — keep captions for zone text)
    if label_main:
        fc = (_cr_flame_color(frac) if mode == "flight"
              else ((232,238,245) if mode == "pad" else (255,80,45)))
        # Use only ASCII chars in the image so PIL default font renders on any server.
        # × is non-ASCII, replace with plain x; strip Cyrillic words from label.
        import re as _re
        ascii_label = _re.sub(r"[^-]", "", label_main).strip() or label_main[:4]
        try:
            f_big = _cr_font(_BOLD, 72)
            shadow = tuple(c // 6 for c in fc)
            draw.text((22, 22), ascii_label, font=f_big, fill=shadow)
            draw.text((20, 20), ascii_label, font=f_big, fill=fc)
        except Exception:
            pass
    # sub-label (Cyrillic zone name) is shown in the caption — skip in image
    bx, by, bh, bw = _CR_W-16, 60, _CR_H-140, 6
    draw.rectangle([bx, by, bx+bw, by+bh], fill=(30,35,55))
    fill_h = round(bh * frac)
    if fill_h > 0:
        draw.rectangle([bx, by+bh-fill_h, bx+bw, by+bh], fill=_cr_flame_color(frac))
    for tf in [0.25, 0.5, 0.75]:
        ty = by + bh - round(bh*tf)
        draw.line([(bx-3,ty),(bx+bw+2,ty)], fill=(60,70,100), width=1)


def _crash_image_sync(mode: str, value: float = 1.0,
                      label_main: str = "", label_sub: str = "") -> Optional[bytes]:
    """Render 640x860 vertical rocket scene. Returns None if Pillow unavailable."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None
    frac = 0.0 if mode == "pad" else min(1.0, math.log(max(1.01, value)) / math.log(40))
    img  = Image.new("RGB", (_CR_W, _CR_H), _cr_bg(frac))
    d    = ImageDraw.Draw(img)
    _cr_draw_background(img, d, frac)
    _cr_draw_stars(d, frac)
    _cr_draw_ground(d, frac)
    _cr_draw_clouds(d, frac)
    cx     = _CR_W // 2
    nose_y = round(655 - frac * 570)
    if mode == "crash":
        bx, by = cx, nose_y + 90
        rng2 = random.Random(77)
        for rad in range(110, 20, -10):
            col = _cr_lerp(_cr_bg(frac), _CR_FL_HI, 0.06+(110-rad)/110*0.25)
            d.ellipse([bx-rad,by-rad,bx+rad,by+rad], fill=col)
        for i in range(20):
            ang = (i/20)*2*math.pi + rng2.uniform(-0.08, 0.08)
            ln  = rng2.uniform(55, 115)
            sx, sy = bx+math.cos(ang)*100, by+math.sin(ang)*100
            ex, ey = bx+math.cos(ang)*(100+ln), by+math.sin(ang)*(100+ln)
            d.line([(sx,sy),(ex,ey)], fill=_CR_FL_HI, width=rng2.randint(2,5))
        for _ in range(14):
            ang = rng2.uniform(0, 2*math.pi)
            dist = rng2.uniform(70, 160)
            px2, py2 = bx+math.cos(ang)*dist, by+math.sin(ang)*dist
            sz = rng2.uniform(3, 9)
            d.ellipse([px2-sz,py2-sz,px2+sz,py2+sz],
                      fill=_cr_lerp(_CR_FL_HI, _CR_FL_MD, rng2.random()))
        for rad, col in [(90,_CR_FL_HI),(58,_CR_FL_MD),(30,_CR_FL_LO),(14,(255,255,255))]:
            d.ellipse([bx-rad,by-rad,bx+rad,by+rad], fill=col)
    else:
        _cr_draw_rocket(d, cx, nose_y, frac)
    _cr_draw_hud(d, mode, frac, label_main, label_sub)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


# ── Setup wizard keyboards ──────────────────────────────

def _crash_setup_mode_kb(sid: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [SBtn("⏱ По времени",  style="primary", callback_data=f"crs:{sid}:mode:time")],
        [SBtn("👥 По игрокам", style="primary", callback_data=f"crs:{sid}:mode:players")],
        [SBtn("Отмена", style="danger", callback_data=f"crs:{sid}:cancel")],
    ])


def _crash_setup_time_kb(sid: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [SBtn("10 сек", style="primary", callback_data=f"crs:{sid}:time:10"),
         SBtn("20 сек", style="primary", callback_data=f"crs:{sid}:time:20"),
         SBtn("30 сек", style="primary", callback_data=f"crs:{sid}:time:30")],
        [SBtn("45 сек", style="primary", callback_data=f"crs:{sid}:time:45"),
         SBtn("60 сек", style="primary", callback_data=f"crs:{sid}:time:60")],
        [SBtn("◀ Назад", style="primary", callback_data=f"crs:{sid}:back"),
         SBtn("Отмена",  style="danger",  callback_data=f"crs:{sid}:cancel")],
    ])


def _crash_setup_players_kb(sid: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [SBtn("2 чел.",  style="primary", callback_data=f"crs:{sid}:players:2"),
         SBtn("3 чел.",  style="primary", callback_data=f"crs:{sid}:players:3"),
         SBtn("5 чел.",  style="primary", callback_data=f"crs:{sid}:players:5")],
        [SBtn("8 чел.",  style="primary", callback_data=f"crs:{sid}:players:8"),
         SBtn("10 чел.", style="primary", callback_data=f"crs:{sid}:players:10")],
        [SBtn("◀ Назад", style="primary", callback_data=f"crs:{sid}:back"),
         SBtn("Отмена",  style="danger",  callback_data=f"crs:{sid}:cancel")],
    ])


# ── Round keyboards ──────────────────────────────────────

def _crash_join_kb(cid: int) -> InlineKeyboardMarkup:
    row1 = [SBtn(f"{a} VRF", style="primary",
                 callback_data=f"cr:join:{cid}:{a}")
            for a in CRASH_BET_PRESETS[:3]]
    row2 = [SBtn(f"{a} VRF", style="primary",
                 callback_data=f"cr:join:{cid}:{a}")
            for a in CRASH_BET_PRESETS[3:]]
    return InlineKeyboardMarkup([
        row1, row2,
        [SBtn("✏️ Своя сумма", style="primary", callback_data=f"cr:custom:{cid}")],
        [SBtn("Отменить раунд", style="danger", callback_data=f"cr:cancel:{cid}")],
    ])


def _crash_flight_kb(cid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        SBtn("💰 ЗАБРАТЬ СТАВКУ", style="success", callback_data=f"cr:cashout:{cid}")
    ]])


# ── Text builders ──────────────────────────────────────

def _crash_join_text(rnd: dict) -> str:
    """Caption shown on the pad photo during the join window."""
    players = rnd["players"]
    total   = sum(p["bet"] for p in players.values())
    items   = list(players.items())

    if rnd["join_mode"] == "players":
        target = rnd["target_players"]
        have   = len(players)
        bar    = "🟢" * have + "⬜" * max(0, target - have)
        status = f"👥 {bar}  <b>{have}/{target}</b> игроков"
    else:
        remain = max(0, int((rnd["join_deadline"] - datetime.now()).total_seconds()))
        status = f"⏱ До старта: <b>{remain} сек</b>"

    # Player rows
    prows = "\n".join(
        f"  • {mention(uid, p['name'])} — <code>{fmt(p['bet'])}</code> VRF"
        for uid, p in items[:10]
    ) or "  <i>Пока никто не зашёл...</i>"
    if len(items) > 10:
        prows += f"\n  <i>+{len(items)-10} ещё</i>"

    return (
        f"🚀 <b>КРАШ — ставки открыты!</b>\n"
        f"<i>Лови момент и забирай выигрыш до взрыва</i>\n\n"
        f"{status}\n"
        f"<blockquote expandable>💰 Банк: <b>{fmt(total)} VRF</b>\n\n"
        f"{prows}</blockquote>\n"
        f"⬇️ <b>Жми сумму чтобы войти</b>"
    )


def _crash_flight_text(rnd: dict, mult: float) -> str:
    """Rich caption for the live flight photo.
    The multiplier number itself is baked into the image — here we show
    who's still flying and who already cashed out."""
    players = rnd["players"]
    in_p    = [p for p in players.values() if not p["cashed"]]
    out_p   = sorted([p for p in players.values() if p["cashed"]],
                     key=lambda p: p["mult"], reverse=True)

    def in_row(p: dict) -> str:
        pot = round(p["bet"] * mult)
        return f"🟢 <b>{p['name']}</b>  <code>{fmt(p['bet'])}</code> → <b>{fmt(pot)}</b> VRF"

    def out_row(p: dict) -> str:
        payout = round(p["bet"] * p["mult"])
        return (f"💰 <b>{p['name']}</b>  ×{p['mult']:.2f} "
                f"→ <b>+{fmt(payout)}</b> VRF")

    in_lines  = "\n".join(in_row(p) for p in in_p[:6])
    out_lines = "\n".join(out_row(p) for p in out_p[:6])

    parts = []
    if in_lines:
        if len(in_p) > 6:
            in_lines += f"\n<i>+{len(in_p)-6} ещё в игре</i>"
        parts.append(f"<blockquote>🚀 Ещё в игре:\n{in_lines}</blockquote>")
    if out_lines:
        if len(out_p) > 6:
            out_lines += f"\n<i>+{len(out_p)-6} ещё</i>"
        parts.append(f"<blockquote>💰 Уже забрали:\n{out_lines}</blockquote>")

    body = "\n".join(parts) or "<i>—</i>"
    return f"{body}\n👇 <b>Жми ЗАБРАТЬ, пока не поздно!</b>"


def _crash_result_cards(crash_point: float, winners: list, losers: list) -> tuple:
    """
    Final results as a profile-style rich table card.
    Returns (rich_html, fallback_html) — same convention as /profile.
    """
    total_pot = sum(p for _, _, p in winners) + sum(b for _, b in losers)
    rows_rich = "".join(
        f"<tr><td>💰 {name}</td><td><b>×{m:.2f}</b> → <mark>+{fmt(payout)}</mark></td></tr>"
        for name, m, payout in winners
    ) + "".join(
        f"<tr><td>💥 {name}</td><td><b>-{fmt(bet)} VRF</b></td></tr>"
        for name, bet in losers
    )
    if not rows_rich:
        rows_rich = "<tr><td colspan='2'><i>Никто не участвовал</i></td></tr>"

    rich_h = (
        f"<h2>💥 Краш — взрыв на ×{crash_point:.2f}!</h2>"
        "<table bordered striped>"
        f"{rows_rich}"
        "</table>"
        f"<blockquote>🎮 Игроков: <b>{len(winners)+len(losers)}</b>"
        f"  ·  💎 В обороте: <b>{fmt(total_pot)} VRF</b></blockquote>"
    )

    win_lines = "\n".join(
        f"💰 {name} — ×{m:.2f} → <b>+{fmt(payout)} VRF</b>"
        for name, m, payout in winners
    ) or "<i>Никто не успел забрать...</i>"
    lose_lines = "\n".join(
        f"💥 {name} — <b>-{fmt(bet)} VRF</b>" for name, bet in losers
    ) or "<i>Все успели забрать вовремя!</i>"
    fb_h = (
        f"💥 <b>Краш — взрыв на ×{crash_point:.2f}!</b>\n\n"
        f"{win_lines}\n{lose_lines}\n\n"
        f"🎮 Игроков: <b>{len(winners)+len(losers)}</b>\n\n"
        f"🚀 Хочешь снова? /crash"
    )
    return rich_h, fb_h


# ── Round end (shared by timeout-crash and all-cashed-out) ──

async def _crash_end(bot, cid: int, final_mult: float) -> None:
    rnd = crash_rounds.get(cid)
    if not rnd or rnd["state"] == "ended":
        return
    rnd["state"]    = "ended"
    crash_point     = round(final_mult, 2)
    winners, losers = [], []

    for uid, p in rnd["players"].items():
        if p["cashed"]:
            payout = round(p["bet"] * p["mult"])
            winners.append((p["name"], p["mult"], payout))
        else:
            losers.append((p["name"], p["bet"]))
            try:
                await db_add_xp(uid, cid, XP_PER_GAME)
                await db_record_game(uid, cid, won=False)
            except Exception:
                pass

    crash_rounds.pop(cid, None)

    loop = asyncio.get_running_loop()
    img  = await loop.run_in_executor(
        None, _crash_image_sync, "crash", crash_point,
        f"x{crash_point:.2f}", "CRASH!",
    )
    light_caption = f"💥 <b>Взрыв на ×{crash_point:.2f}!</b>\nРезультаты ⬇️"
    try:
        if img:
            await bot.edit_message_media(
                chat_id=cid, message_id=rnd["msg_id"],
                media=InputMediaPhoto(media=io.BytesIO(img),
                                      caption=light_caption, parse_mode=ParseMode.HTML),
            )
        else:
            await bot.edit_message_caption(
                chat_id=cid, message_id=rnd["msg_id"],
                caption=light_caption, parse_mode=ParseMode.HTML,
            )
    except TelegramError:
        pass

    rich_h, fb_h = _crash_result_cards(crash_point, winners, losers)
    await send_rich(bot, cid, html=rich_h, fallback_html=fb_h,
                    reply_markup=_play_again_kb("crash", cid))


# ── Background tasks ───────────────────────────────────

async def _crash_join_loop(bot, cid: int) -> None:
    try:
        while True:
            rnd = crash_rounds.get(cid)
            if not rnd or rnd["state"] != "joining":
                return
            remain = (rnd["join_deadline"] - datetime.now()).total_seconds()
            if remain <= 0:
                break
            await asyncio.sleep(min(4, max(0.6, remain)))
            rnd = crash_rounds.get(cid)
            if not rnd or rnd["state"] != "joining":
                return
            try:
                await bot.edit_message_caption(
                    chat_id=cid, message_id=rnd["msg_id"],
                    caption=_crash_join_text(rnd), parse_mode=ParseMode.HTML,
                    reply_markup=_crash_join_kb(cid),
                )
            except TelegramError:
                pass

        rnd = crash_rounds.get(cid)
        if not rnd or rnd["state"] != "joining":
            return

        if not rnd["players"]:
            crash_rounds.pop(cid, None)
            try:
                await bot.edit_message_caption(
                    chat_id=cid, message_id=rnd["msg_id"],
                    caption="🚀 <b>Раунд отменён</b> — никто не присоединился.",
                    parse_mode=ParseMode.HTML, reply_markup=None,
                )
            except TelegramError:
                pass
            return

        rnd["state"]        = "flying"
        rnd["flight_start"] = datetime.now()
        await _crash_flight_loop(bot, cid)
    except Exception:
        log.exception("Crash join loop failed (cid=%s)", cid)
        crash_rounds.pop(cid, None)


async def _crash_flight_loop(bot, cid: int) -> None:
    try:
        loop = asyncio.get_running_loop()
        while True:
            await asyncio.sleep(CRASH_TICK_SECONDS)
            rnd = crash_rounds.get(cid)
            if not rnd or rnd["state"] != "flying":
                return
            elapsed  = (datetime.now() - rnd["flight_start"]).total_seconds()
            cur_mult = _crash_mult_at(elapsed)

            still_in = any(not p["cashed"] for p in rnd["players"].values())
            if cur_mult >= rnd["crash_point"] or not still_in:
                await _crash_end(bot, cid, min(cur_mult, rnd["crash_point"]))
                return

            img = await loop.run_in_executor(
                None, _crash_image_sync, "flight", cur_mult,
                f"x{cur_mult:.2f}", _crash_flavor(cur_mult),
            )
            try:
                if img:
                    await bot.edit_message_media(
                        chat_id=cid, message_id=rnd["msg_id"],
                        media=InputMediaPhoto(media=io.BytesIO(img),
                                              caption=_crash_flight_text(rnd, cur_mult),
                                              parse_mode=ParseMode.HTML),
                        reply_markup=_crash_flight_kb(cid),
                    )
                else:
                    await bot.edit_message_caption(
                        chat_id=cid, message_id=rnd["msg_id"],
                        caption=_crash_flight_text(rnd, cur_mult),
                        parse_mode=ParseMode.HTML, reply_markup=_crash_flight_kb(cid),
                    )
            except TelegramError:
                pass
    except Exception:
        log.exception("Crash flight loop failed (cid=%s)", cid)
        crash_rounds.pop(cid, None)


# ── Shared join logic (preset buttons AND custom-amount replies) ──

async def _crash_join_player(context: ContextTypes.DEFAULT_TYPE, rcid: int,
                              user, amount: int) -> tuple:
    """
    Validate + add a player to an open round. Returns (ok: bool, message: str).
    Used by both the preset bet buttons and the custom-amount text flow.
    """
    rnd = crash_rounds.get(rcid)
    if not rnd or rnd["state"] != "joining":
        return False, "❌ Окно ставок закрыто!"
    if user.id in rnd["players"]:
        return False, "Ты уже сделал ставку в этом раунде!"
    if amount < MIN_BET:
        return False, f"❌ Минимальная ставка: {MIN_BET} VRF"
    # No upper cap — deduct check handles the balance limit

    await db_ensure_user(user.id, rcid, user.username or "", user.first_name)
    u = await db_get_user(user.id, rcid)
    if not u or u["vrf"] < amount:
        return False, f"❌ Недостаточно VRF! Нужно {amount}."

    ok = await db_deduct_vrf(user.id, rcid, amount)
    if not ok:
        return False, "❌ Недостаточно VRF!"

    rnd["players"][user.id] = {
        "name": user.first_name, "bet": amount,
        "cashed": False, "mult": None,
    }

    # Players-mode: launch instantly once the target is reached
    if (rnd["join_mode"] == "players"
            and rnd["state"] == "joining"
            and len(rnd["players"]) >= rnd["target_players"]):
        rnd["state"]        = "flying"
        rnd["flight_start"] = datetime.now()
        try:
            await context.bot.edit_message_caption(
                chat_id=rcid, message_id=rnd["msg_id"],
                caption=f"✅ <b>Собрали {rnd['target_players']} игроков! Старт! 🚀</b>",
                parse_mode=ParseMode.HTML, reply_markup=None,
            )
        except TelegramError:
            pass
        context.application.create_task(_crash_flight_loop(context.bot, rcid))

    return True, f"✅ Ставка {amount} VRF принята! Удачи 🍀"


# ── Launch a configured round (called from the wizard) ──

async def _crash_launch(context: ContextTypes.DEFAULT_TYPE, query,
                         cid: int, setup: dict, mode: str,
                         join_seconds: Optional[int] = None,
                         target_players: Optional[int] = None) -> None:
    existing = crash_rounds.get(cid)
    if existing and existing["state"] != "ended":
        try:
            await query.edit_message_text(
                "⏳ Кто-то уже запустил раунд в этом чате — присоединяйся к нему выше!"
            )
        except TelegramError:
            pass
        return

    # Claim the slot SYNCHRONOUSLY (no await between check and write) so a
    # second concurrent /crash launch in the same chat can't race past the
    # check above while this one is still awaiting image generation / send.
    crash_rounds[cid] = {"cid": cid, "state": "launching"}

    now      = datetime.now()
    deadline = now + timedelta(seconds=join_seconds if mode == "time" else JOIN_TIMEOUT)

    # The wizard prompt is a text message — it can't be converted into a
    # photo via edit, so confirm it briefly and send the round as a new photo.
    try:
        await query.edit_message_text("🚀 Раунд запущен ⬇️")
    except TelegramError:
        pass

    rnd_stub = {
        "join_mode": mode, "join_deadline": deadline,
        "target_players": target_players, "players": {},
    }
    loop = asyncio.get_running_loop()
    img  = await loop.run_in_executor(
        None, _crash_image_sync, "pad", 1.0, "", "",
    )
    caption = _crash_join_text(rnd_stub)

    try:
        if img:
            msg = await context.bot.send_photo(
                chat_id=cid, photo=io.BytesIO(img),
                caption=caption, parse_mode=ParseMode.HTML,
                reply_markup=_crash_join_kb(cid),
            )
        else:
            msg = await context.bot.send_message(
                cid, caption, parse_mode=ParseMode.HTML,
                reply_markup=_crash_join_kb(cid),
            )
    except TelegramError:
        crash_rounds.pop(cid, None)   # release the claimed slot on failure
        return

    crash_rounds[cid] = {
        "cid": cid, "state": "joining",
        "starter_id": setup["starter_id"], "starter_name": setup["starter_name"],
        "msg_id": msg.message_id,
        "players": {},
        "crash_point": _crash_point(),
        "join_mode": mode,
        "join_seconds": join_seconds,
        "target_players": target_players,
        "join_started": now,
        "join_deadline": deadline,
        "flight_start": None,
    }

    context.application.create_task(_crash_join_loop(context.bot, cid))


# ── /crash command — opens the setup wizard ─────────────

@only_groups
async def cmd_crash(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cid = update.effective_chat.id
    u   = update.effective_user

    existing = crash_rounds.get(cid)
    if existing and existing["state"] != "ended":
        await update.message.reply_text(
            "⏳ Раунд уже идёт! Присоединяйся к нему выше ☝️"
            if existing["state"] == "joining" else
            "🚀 Ракета уже летит! Дождись следующего раунда.",
        )
        return

    await db_ensure_user(u.id, cid, u.username or "", u.first_name)

    sid = str(uuid.uuid4())[:8]
    crash_setups[sid] = {
        "cid": cid, "starter_id": u.id, "starter_name": u.first_name,
    }

    await update.message.reply_text(
        "🚀 <b>Краш</b>\n\n"
        "Как набираем игроков перед стартом ракеты?",
        parse_mode=ParseMode.HTML,
        reply_markup=_crash_setup_mode_kb(sid),
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

    # ── Giveaway launch card ──────────────────────────
    # Позволяет запустить визард розыгрыша прямо из Inline-режима — не нужно
    # писать /giveaway руками. ВАЖНО: чтобы бот мог считать реакции, он
    # обязательно должен уже состоять в том чате, где будет запущен
    # розыгрыш — это ограничение самого Telegram (апдейты о реакциях
    # приходят только из чатов, где бот присутствует), а не бота.
    gw_trigger = any(t in q_text for t in ("розыгрыш", "медвед", "giveaway", "🐻"))
    gw_sid = str(uuid.uuid4())[:8]
    giveaway_setups[gw_sid] = {
        "cid": None,   # определится в момент первого нажатия кнопки в реальном чате
        "org_id": uid, "org_name": query.from_user.first_name,
        "reaction": None, "bears": 1, "winners": 1, "minutes": 5,
    }
    gw_article = InlineQueryResultArticle(
        id=f"gw:{gw_sid}",
        title="🐻 Запустить розыгрыш медведей",
        description="Работает только в чатах, где бот уже добавлен",
        input_message_content=InputTextMessageContent(
            "🐻 <b>Розыгрыш медведей</b>\n\n<b>Шаг 1 / 3</b> — Выбери реакцию для участия:",
            parse_mode=ParseMode.HTML,
        ),
        reply_markup=_gw_kb_react(gw_sid),
    )
    if gw_trigger:
        results.insert(0, gw_article)
    else:
        results.append(gw_article)

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
        f"<tr><td>🏅 Уровень</td><td><b>{lvl}</b> — {rank_nm}</td></tr>"
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

    caller = update.effective_user
    result = await send_ephemeral_or_normal(
        context.bot, update.effective_chat.id, caller.id, fb_h,
        reply_to_id=update.message.message_id,
    )
    if isinstance(result, dict) and result.get("ephemeral_message_id"):
        try:
            await update.message.react([ReactionTypeEmoji(emoji="👀")])
        except TelegramError:
            pass
    elif not await is_bot_chat_admin(context.bot, update.effective_chat.id):
        try:
            await context.bot.send_message(
                update.effective_chat.id,
                "ℹ️ Сделай бота администратором чата, чтобы /profile был виден только тебе.",
                reply_to_message_id=update.message.message_id,
            )
        except TelegramError:
            pass


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
        f"<h2>🏆 Топ-10 — {title}</h2>",
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
        f"<tr><td>👑 Богатейший</td><td align=\"right\"><b>{rich_name}</b> — {rich_vrf} VRF</td></tr>"
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

    result = await send_ephemeral_or_normal(
        context.bot, cid, u_obj.id, fb_h, reply_to_id=update.message.message_id,
    )
    if isinstance(result, dict) and result.get("ephemeral_message_id"):
        try:
            await update.message.react([ReactionTypeEmoji(emoji="👀")])
        except TelegramError:
            pass
    elif not await is_bot_chat_admin(context.bot, cid):
        try:
            await context.bot.send_message(
                cid, "ℹ️ Сделай бота администратором чата, чтобы /bonus был виден только тебе.",
                reply_to_message_id=update.message.message_id,
            )
        except TelegramError:
            pass


@only_groups
async def cmd_clicker(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /clicker — открывает Telegram Mini App кликер (если WEBAPP_URL задан),
    или засчитывает VRF из текстовой команды /clicker [amount].
    """
    u   = update.effective_user
    cid = update.effective_chat.id

    # ── Mode A: Mini App is configured — send the keyboard button ─────────
    if WEBAPP_URL and not context.args:
        clicker_url = WEBAPP_URL.rstrip("/") + "/clicker"
        kb = ReplyKeyboardMarkup(
            [[KeyboardButton("🖱 Открыть кликер VRF", web_app=WebAppInfo(url=clicker_url))]],
            resize_keyboard=True,
            one_time_keyboard=False,
        )
        await update.message.reply_text(
            "👆 Нажми кнопку ниже чтобы открыть кликер.\n"
            "Накопи VRF и нажми <b>Отправить в бот</b> — монеты придут сюда!",
            parse_mode=ParseMode.HTML,
            reply_markup=kb,
        )
        return

    # ── Mode B: text-based fallback /clicker [amount] ─────────────────────
    CLICKER_DAILY_MAX = 500
    CLICKER_COOLDOWN  = timedelta(hours=24)

    if not context.args or not context.args[0].replace(".", "").isdigit():
        base_msg = (
            "🖱 <b>Кликер</b>\n\n"
            "Накапливай VRF в кликере и засылай в бот командой:\n"
            "<code>/clicker [сумма]</code>\n\n"
            "Ограничение: <b>500 VRF в сутки</b>"
        )
        if WEBAPP_URL:
            base_msg += f"\n\nМини-приложение: {WEBAPP_URL.rstrip('/')}/clicker"
        await update.message.reply_text(base_msg, parse_mode=ParseMode.HTML)
        return

    amount = int(float(context.args[0]))
    if amount <= 0:
        await update.message.reply_text("❌ Сумма должна быть больше 0!")
        return
    if amount > CLICKER_DAILY_MAX:
        await update.message.reply_text(
            f"❌ Максимум <b>{CLICKER_DAILY_MAX} VRF</b> в сутки из кликера.",
            parse_mode=ParseMode.HTML,
        )
        return

    await db_ensure_user(u.id, cid, u.username or "", u.first_name)

    async with aiosqlite.connect(DB_PATH) as db:
        for col in ["last_clicker_claim TEXT DEFAULT NULL",
                    "clicker_claimed_today INTEGER DEFAULT 0"]:
            try:
                await db.execute(f"ALTER TABLE users ADD COLUMN {col}")
            except Exception:
                pass
        await db.commit()
        async with db.execute(
            "SELECT last_clicker_claim, clicker_claimed_today FROM users "
            "WHERE user_id=? AND chat_id=?", (u.id, cid)
        ) as cur:
            row = await cur.fetchone()

    last_claim, claimed_today = (row or (None, 0))
    claimed_today = claimed_today or 0
    now = datetime.now()

    if last_claim:
        try:
            last_dt = datetime.fromisoformat(last_claim)
            if now - last_dt < CLICKER_COOLDOWN:
                remaining = max(0, CLICKER_DAILY_MAX - claimed_today)
                if remaining <= 0:
                    wait = int((last_dt + CLICKER_COOLDOWN - now).total_seconds())
                    await update.message.reply_text(
                        f"⏰ Суточный лимит кликера исчерпан!\n"
                        f"Следующее пополнение через <b>{fmt_cd(wait)}</b>.",
                        parse_mode=ParseMode.HTML,
                    )
                    return
                amount = min(amount, remaining)
        except ValueError:
            claimed_today = 0

    new_bal = await db_add_vrf(u.id, cid, amount)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET last_clicker_claim=?, clicker_claimed_today=? "
            "WHERE user_id=? AND chat_id=?",
            (now.isoformat(), claimed_today + amount, u.id, cid),
        )
        await db.commit()

    await update.message.reply_text(
        f"🖱 <b>Кликер — зачислено!</b>\n\n"
        f"💎 +{fmt(amount)} VRF\n"
        f"💰 Баланс: <b>{fmt(new_bal)} VRF</b>\n\n"
        f"<i>Осталось сегодня: {fmt(max(0, CLICKER_DAILY_MAX - claimed_today - amount))} VRF</i>",
        parse_mode=ParseMode.HTML,
    )


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

# ═══════════════════════════════════════════
#   PLAY-AGAIN button — all bet games
# ═══════════════════════════════════════════

def _play_again_kb(game: str, cid: int, bet: int = 0) -> InlineKeyboardMarkup:
    """Single 'Play again' row appended to any game result message."""
    return InlineKeyboardMarkup([[SBtn("\U0001f504 \u0415\u0449\u0451 \u0440\u0430\u0437", style="success",
                                       callback_data=f"ra:{game}:{cid}:{bet}")]])


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
        "<h2>⚔️ Дуэль — Итог</h2>"
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
        f"💎 +{fmt(bet)} VRF → Баланс: {fmt(new_bal)} VRF</blockquote>"
    )
    fb_h = (
        f"🏆 <b>ПОБЕДИТЕЛЬ!</b>\n\n"
        f"{mention(c_id, c_name)}: {c_roll} + ур. = <b>{c_total}</b>\n"
        f"{mention(o_id, o_name)}: {o_roll} + ур. = <b>{o_total}</b>\n\n"
        f"🥇 {mention(w_id, w_name)} побеждает!\n"
        f"💎 +{bet} VRF → Баланс: {fmt(new_bal)} VRF"
    )
    await send_rich(context.bot, cid, html=rich_h, fallback_html=fb_h,
                    reply_markup=_play_again_kb("duel", cid, bet))

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
        "<h2>🎲 Кубики — Итог</h2>"
        "<table bordered striped>"
        "<tr><th>Игрок</th><th align=\"right\">Очки</th></tr>"
        f"<tr><td>{'<b>' if h_win else ''}{h_name}{'</b>' if h_win else ''}</td>"
        f"<td align=\"right\">{'<mark><b>' if h_win else ''}{h_score}{'</b></mark>' if h_win else ''}</td></tr>"
        f"<tr><td>{'<b>' if o_win else ''}{o_name}{'</b>' if o_win else ''}</td>"
        f"<td align=\"right\">{'<mark><b>' if o_win else ''}{o_score}{'</b></mark>' if o_win else ''}</td></tr>"
        "</table>"
        f"<blockquote>🏆 <b>{w_name}</b> побеждает!<br/>"
        f"Раундов: {rounds} | 💎 +{fmt(bet)} VRF → {fmt(new_bal)} VRF</blockquote>"
    )
    cubes_fb = (
        f"🏆 <b>ПОБЕДИТЕЛЬ!</b>\n{mention(w_id, w_name)}\n"
        f"📊 {h_score}:{o_score} | 💎 +{fmt(bet)} VRF"
    )
    await send_rich(context.bot, cid, html=cubes_rich, fallback_html=cubes_fb,
                    reply_markup=_play_again_kb("cubes", cid, bet))


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
        f"<h2>{emoji} {name} — Итог</h2>"
        "<table bordered striped>"
        "<tr><th>Игрок</th><th align=\"right\">Очки</th></tr>"
        f"<tr><td>{'<b>' if h_win_s else ''}{h_name}{'</b>' if h_win_s else ''}</td>"
        f"<td align=\"right\">{'<mark><b>' if h_win_s else ''}{h_total}{'</b></mark>' if h_win_s else ''}</td></tr>"
        f"<tr><td>{'<b>' if o_win_s else ''}{o_name}{'</b>' if o_win_s else ''}</td>"
        f"<td align=\"right\">{'<mark><b>' if o_win_s else ''}{o_total}{'</b></mark>' if o_win_s else ''}</td></tr>"
        "</table>"
        f"<blockquote>🏆 <b>{w_name}</b> побеждает!<br/>"
        f"Раундов: {rounds} | 💎 +{fmt(bet)} VRF → {fmt(new_bal)} VRF</blockquote>"
    )
    sport_fb = (
        f"🏆 <b>ПОБЕДИТЕЛЬ!</b>\n{mention(w_id, w_name)}\n"
        f"📊 {h_total}:{o_total} | 💎 +{fmt(bet)} VRF"
    )
    await send_rich(context.bot, cid, html=sport_rich, fallback_html=sport_fb,
                    reply_markup=_play_again_kb("sport", cid, bet))


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

# ══════════════════════════════════════════════════════
#           MODERATION SYSTEM 🛡️  (hidden — admin only)
# ══════════════════════════════════════════════════════

_WARN_LIMIT = 3          # auto-mute after N warns
_WARN_AUTO_MUT = timedelta(hours=24)   # auto-mute duration


# ── Duration parser ───────────────────────────────────

def _mod_dur(args: list, default: Optional[timedelta] = timedelta(days=7)) -> tuple:
    """
    Parse duration from command args.
    Returns (Optional[timedelta], reason: str).
    `default` is returned verbatim whenever no valid duration is found
    (no args, or first arg isn't a recognised unit) — pass default=None
    for commands where "no duration given" should mean permanent.
    """
    FOREVER = {"навсегда", "perma", "forever", "перм", "perm", "inf", "∞"}
    SECS: dict = {
        frozenset({"с", "сек", "секунд", "секунды", "sec", "s"}):                          1,
        frozenset({"мин", "мин.", "минут", "минуты", "м", "min", "m", "minute", "minutes"}): 60,
        frozenset({"ч", "час", "часа", "часов", "h", "hour", "hours", "hr"}):             3600,
        frozenset({"д", "дн", "день", "дня", "дней", "d", "day", "days"}):              86400,
        frozenset({"н", "нед", "неделя", "недели", "недель", "w", "week", "weeks"}):    604800,
        frozenset({"мес", "месяц", "месяца", "месяцев", "mo", "month", "months"}):     2592000,
    }
    if not args:
        return default, ""

    first = args[0].lower()
    if first in FOREVER:
        return None, " ".join(args[1:])

    # Bare number with no unit (e.g. "/mute 10 спам") → assume minutes
    if first.isdigit():
        return timedelta(minutes=int(first)), " ".join(args[1:])

    import re as _re
    m = _re.match(r"^(\d+)([а-яёa-z.]+)$", first)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        for unit_set, secs in SECS.items():
            if unit in unit_set:
                return timedelta(seconds=n * secs), " ".join(args[1:])

    # First arg is not a recognised duration → all args = reason, use default
    return default, " ".join(args)


def _fmt_until(until: Optional[datetime]) -> str:
    if until is None:
        return "навсегда"
    rem = (until - datetime.now()).total_seconds()
    return fmt_cd(int(rem)) if rem > 0 else "истёк"


async def _is_protected(chat, uid: int) -> bool:
    """True if user is a group admin/creator (can't be moderated)."""
    try:
        m = await chat.get_member(uid)
        return m.status in ("administrator", "creator")
    except TelegramError:
        return False


# ── Moderation DB helpers ─────────────────────────────

async def db_log_mute(uid: int, cid: int, by: int,
                      until: Optional[datetime], reason: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO mutes (user_id,chat_id,muted_by,muted_at,until,reason)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(user_id,chat_id) DO UPDATE SET
                   muted_by=excluded.muted_by, muted_at=excluded.muted_at,
                   until=excluded.until, reason=excluded.reason""",
            (uid, cid, by, _now(),
             until.isoformat() if until else None, reason),
        )
        await db.commit()


async def db_clear_mute(uid: int, cid: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM mutes WHERE user_id=? AND chat_id=?", (uid, cid))
        await db.commit()


async def db_get_mutes(cid: int) -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM mutes WHERE chat_id=? ORDER BY muted_at DESC", (cid,)
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def db_add_warn(uid: int, cid: int, by: int, reason: str) -> int:
    """Add a warning and return total active warn count."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO warns (user_id,chat_id,warned_by,warned_at,reason) VALUES (?,?,?,?,?)",
            (uid, cid, by, _now(), reason),
        )
        await db.commit()
        async with db.execute(
            "SELECT COUNT(*) FROM warns WHERE user_id=? AND chat_id=? AND active=1",
            (uid, cid),
        ) as cur:
            return (await cur.fetchone())[0]


async def db_remove_last_warn(uid: int, cid: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id FROM warns WHERE user_id=? AND chat_id=? AND active=1 ORDER BY warned_at DESC LIMIT 1",
            (uid, cid),
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return False
        await db.execute("UPDATE warns SET active=0 WHERE id=?", (row[0],))
        await db.commit()
        return True


async def db_clear_warns(uid: int, cid: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM warns WHERE user_id=? AND chat_id=? AND active=1",
            (uid, cid),
        ) as cur:
            count = (await cur.fetchone())[0]
        await db.execute(
            "UPDATE warns SET active=0 WHERE user_id=? AND chat_id=?", (uid, cid)
        )
        await db.commit()
        return count


async def db_get_user_warns(uid: int, cid: int) -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM warns WHERE user_id=? AND chat_id=? AND active=1 ORDER BY warned_at DESC",
            (uid, cid),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def db_get_chat_warns(cid: int) -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT user_id, COUNT(*) AS cnt FROM warns
               WHERE chat_id=? AND active=1 GROUP BY user_id ORDER BY cnt DESC LIMIT 20""",
            (cid,),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


# ── Shared permissions ────────────────────────────────

_MUTED_PERMS = ChatPermissions(
    can_send_messages=False,
    can_send_polls=False,
    can_send_other_messages=False,
    can_add_web_page_previews=False,
)
_FULL_PERMS = ChatPermissions(
    can_send_messages=True,
    can_send_polls=True,
    can_send_other_messages=True,
    can_add_web_page_previews=True,
    can_invite_users=True,
)


# ── /мут /mute ────────────────────────────────────────

@only_groups
async def cmd_mute(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_group_or_bot_admin(update):
        return
    msg  = update.message
    caller = update.effective_user
    cid  = update.effective_chat.id

    if not msg.reply_to_message or msg.reply_to_message.from_user.is_bot:
        await msg.reply_text(
            "📌 Ответь на сообщение пользователя:\n"
            "<code>/mute [10m / 2h / 1d / навсегда] [причина]</code>\n"
            "По умолчанию: 7 дней",
            parse_mode=ParseMode.HTML,
        )
        return

    target = msg.reply_to_message.from_user
    if target.id == caller.id:
        await msg.reply_text("❌ Нельзя замутить себя")
        return
    if await _is_protected(update.effective_chat, target.id):
        await msg.reply_text("❌ Нельзя замутить администратора")
        return

    dur, reason = _mod_dur(context.args)
    until_dt   = datetime.now() + dur if dur else None

    try:
        await context.bot.restrict_chat_member(
            cid, target.id, _MUTED_PERMS, until_date=until_dt,
        )
    except TelegramError as e:
        await msg.reply_text(f"❌ Ошибка: {e}")
        return

    await db_ensure_user(target.id, cid, target.username or "", target.first_name)
    await db_log_mute(target.id, cid, caller.id, until_dt, reason)

    await msg.reply_text(
        f"🔇 {mention(target.id, target.first_name)} — <b>мут</b>\n"
        f"⏱ Срок: <b>{_fmt_until(until_dt)}</b>"
        + (f"\n📝 Причина: {reason}" if reason else ""),
        parse_mode=ParseMode.HTML,
    )


# ── /unmute /анмут /unmute ────────────────────────────

@only_groups
async def cmd_unmute(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_group_or_bot_admin(update):
        return
    msg = update.message

    if not msg.reply_to_message or msg.reply_to_message.from_user.is_bot:
        await msg.reply_text("📌 Ответь на сообщение пользователя: <code>/unmute</code>",
                             parse_mode=ParseMode.HTML)
        return

    target = msg.reply_to_message.from_user
    cid    = update.effective_chat.id

    try:
        await context.bot.restrict_chat_member(cid, target.id, _FULL_PERMS)
    except TelegramError as e:
        await msg.reply_text(f"❌ Ошибка: {e}")
        return

    await db_clear_mute(target.id, cid)
    await msg.reply_text(
        f"🔊 {mention(target.id, target.first_name)} — <b>мут снят</b>",
        parse_mode=ParseMode.HTML,
    )


# ── /кик /kick ───────────────────────────────────────

@only_groups
async def cmd_kick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_group_or_bot_admin(update):
        return
    msg  = update.message
    cid  = update.effective_chat.id

    if not msg.reply_to_message or msg.reply_to_message.from_user.is_bot:
        await msg.reply_text("📌 Ответь на сообщение: <code>/kick [причина]</code>",
                             parse_mode=ParseMode.HTML)
        return

    target = msg.reply_to_message.from_user
    if await _is_protected(update.effective_chat, target.id):
        await msg.reply_text("❌ Нельзя кикнуть администратора")
        return

    reason = " ".join(context.args) if context.args else ""
    try:
        await context.bot.ban_chat_member(cid, target.id)
        await asyncio.sleep(0.3)
        await context.bot.unban_chat_member(cid, target.id)
    except TelegramError as e:
        await msg.reply_text(f"❌ Ошибка: {e}")
        return

    await msg.reply_text(
        f"👢 {mention(target.id, target.first_name)} — <b>исключён</b>"
        + (f"\n📝 {reason}" if reason else ""),
        parse_mode=ParseMode.HTML,
    )


# ── /бан /ban ────────────────────────────────────────

@only_groups
async def cmd_ban(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_group_or_bot_admin(update):
        return
    msg    = update.message
    caller = update.effective_user
    cid    = update.effective_chat.id

    if not msg.reply_to_message or msg.reply_to_message.from_user.is_bot:
        await msg.reply_text(
            "📌 Ответь на сообщение:\n"
            "<code>/ban [срок] [причина]</code>  (без срока = навсегда)",
            parse_mode=ParseMode.HTML,
        )
        return

    target = msg.reply_to_message.from_user
    if await _is_protected(update.effective_chat, target.id):
        await msg.reply_text("❌ Нельзя забанить администратора")
        return

    dur, reason = _mod_dur(context.args, default=None)
    until_dt = datetime.now() + dur if dur else None

    try:
        await context.bot.ban_chat_member(
            cid, target.id, until_date=until_dt, revoke_messages=False,
        )
    except TelegramError as e:
        await msg.reply_text(f"❌ Ошибка: {e}")
        return

    await msg.reply_text(
        f"🚫 {mention(target.id, target.first_name)} — <b>заблокирован</b>\n"
        f"⏱ Срок: <b>{_fmt_until(until_dt)}</b>"
        + (f"\n📝 Причина: {reason}" if reason else ""),
        parse_mode=ParseMode.HTML,
    )


# ── /unban /unban ────────────────────────────────────

@only_groups
async def cmd_unban(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_group_or_bot_admin(update):
        return
    msg = update.message

    if not msg.reply_to_message:
        await msg.reply_text("📌 Ответь на сообщение: <code>/unban</code>",
                             parse_mode=ParseMode.HTML)
        return

    target = msg.reply_to_message.from_user
    cid    = update.effective_chat.id

    try:
        await context.bot.unban_chat_member(cid, target.id, only_if_banned=True)
    except TelegramError as e:
        await msg.reply_text(f"❌ Ошибка: {e}")
        return

    await msg.reply_text(
        f"✅ {mention(target.id, target.first_name)} — <b>разблокирован</b>",
        parse_mode=ParseMode.HTML,
    )


# ── /варн /warn ──────────────────────────────────────

@only_groups
async def cmd_warn(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_group_or_bot_admin(update):
        return
    msg    = update.message
    caller = update.effective_user
    cid    = update.effective_chat.id

    if not msg.reply_to_message or msg.reply_to_message.from_user.is_bot:
        await msg.reply_text("📌 Ответь на сообщение: <code>/pred [причина]</code>",
                             parse_mode=ParseMode.HTML)
        return

    target = msg.reply_to_message.from_user
    if await _is_protected(update.effective_chat, target.id):
        await msg.reply_text("❌ Нельзя варнить администратора")
        return

    reason = " ".join(context.args) if context.args else ""
    await db_ensure_user(target.id, cid, target.username or "", target.first_name)
    count = await db_add_warn(target.id, cid, caller.id, reason)

    filled  = "⚠️" * count
    empty   = "□" * max(0, _WARN_LIMIT - count)
    bar     = filled + empty

    text = (
        f"⚠️ {mention(target.id, target.first_name)} — <b>предупреждение</b>\n"
        f"Варнов: <b>{count}/{_WARN_LIMIT}</b>  {bar}"
        + (f"\n📝 Причина: {reason}" if reason else "")
    )

    if count >= _WARN_LIMIT:
        try:
            until_dt = datetime.now() + _WARN_AUTO_MUT
            await context.bot.restrict_chat_member(
                cid, target.id, _MUTED_PERMS, until_date=until_dt,
            )
            await db_log_mute(target.id, cid, caller.id, until_dt,
                              f"Автомут — {count} варнов")
            await db_clear_warns(target.id, cid)
            text += f"\n\n🔇 <b>Лимит!</b> Автомут на {fmt_cd(int(_WARN_AUTO_MUT.total_seconds()))}"
        except TelegramError:
            pass

    await msg.reply_text(text, parse_mode=ParseMode.HTML)


# ── /unpred /unwarn ────────────────────────────────

@only_groups
async def cmd_unwarn(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_group_or_bot_admin(update):
        return
    msg = update.message
    cid = update.effective_chat.id

    if not msg.reply_to_message or msg.reply_to_message.from_user.is_bot:
        await msg.reply_text("📌 Ответь на сообщение: <code>/unpred</code>",
                             parse_mode=ParseMode.HTML)
        return

    target = msg.reply_to_message.from_user
    ok = await db_remove_last_warn(target.id, cid)
    if ok:
        remaining = len(await db_get_user_warns(target.id, cid))
        await msg.reply_text(
            f"✅ Последний варн {mention(target.id, target.first_name)} снят. "
            f"Осталось: <b>{remaining}/{_WARN_LIMIT}</b>",
            parse_mode=ParseMode.HTML,
        )
    else:
        await msg.reply_text(
            f"❌ У {mention(target.id, target.first_name)} нет активных варнов",
            parse_mode=ParseMode.HTML,
        )


# ── /снятьваны / снять все варны ─────────────────────

@only_groups
async def cmd_clearwarns(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_group_or_bot_admin(update):
        return
    msg = update.message
    cid = update.effective_chat.id

    if not msg.reply_to_message or msg.reply_to_message.from_user.is_bot:
        await msg.reply_text("📌 Ответь на сообщение: <code>/clearpred</code>",
                             parse_mode=ParseMode.HTML)
        return

    target = msg.reply_to_message.from_user
    count  = await db_clear_warns(target.id, cid)
    await msg.reply_text(
        f"✅ Сняты все варны (<b>{count}</b>) у {mention(target.id, target.first_name)}",
        parse_mode=ParseMode.HTML,
    )


# ── /predlist — список варнов пользователя / чата ───────

@only_groups
async def cmd_warnlist(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_group_or_bot_admin(update):
        return
    msg = update.message
    cid = update.effective_chat.id

    # Reply → show specific user's warns
    if msg.reply_to_message and not msg.reply_to_message.from_user.is_bot:
        target = msg.reply_to_message.from_user
        warns  = await db_get_user_warns(target.id, cid)
        if not warns:
            await msg.reply_text(
                f"✅ У {mention(target.id, target.first_name)} нет варнов",
                parse_mode=ParseMode.HTML,
            )
            return
        lines = [
            f"{i+1}. <code>{w['warned_at'][:10]}</code>"
            + (f" — {w['reason']}" if w.get("reason") else "")
            for i, w in enumerate(warns)
        ]
        await msg.reply_text(
            f"⚠️ Варны {mention(target.id, target.first_name)}: "
            f"<b>{len(warns)}/{_WARN_LIMIT}</b>\n\n" + "\n".join(lines),
            parse_mode=ParseMode.HTML,
        )
        return

    # No reply → chat-wide warn overview
    rows = await db_get_chat_warns(cid)
    if not rows:
        await msg.reply_text("✅ Нет активных варнов в чате")
        return
    lines = [
        f"• {mention(r['user_id'], 'id'+str(r['user_id']))} — "
        f"<b>{r['cnt']}/{_WARN_LIMIT}</b> варн."
        for r in rows
    ]
    await msg.reply_text(
        f"⚠️ <b>Варны в чате</b>:\n\n" + "\n".join(lines),
        parse_mode=ParseMode.HTML,
    )


# ── /mutelist — список замутенных ─────────────────────────

@only_groups
async def cmd_mutelist(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_group_or_bot_admin(update):
        return
    cid   = update.effective_chat.id
    mutes = await db_get_mutes(cid)
    if not mutes:
        await update.message.reply_text("✅ Нет замутенных")
        return
    lines = []
    for m in mutes[:20]:
        until = datetime.fromisoformat(m["until"]) if m.get("until") else None
        r     = m.get("reason", "")
        lines.append(
            f"• {mention(m['user_id'], 'id'+str(m['user_id']))} — "
            f"⏱{_fmt_until(until)}"
            + (f" [{r}]" if r else "")
        )
    await update.message.reply_text(
        f"🔇 <b>Замутенные ({len(mutes)})</b>:\n\n" + "\n".join(lines),
        parse_mode=ParseMode.HTML,
    )


# ══════════════════════════════════════════════════════
#              ADMIN PANEL
# ══════════════════════════════════════════════════════

async def cmd_checkephemeral(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Реальная проверка: поддерживает ли сервер Telegram эфемерные
    сообщения ПРЯМО СЕЙЧАС. Не гадаем — пробуем настоящий вызов и смотрим,
    вернулся ли ephemeral_message_id."""
    if not await is_group_or_bot_admin(update):
        await update.message.reply_text("❌ Только для администраторов")
        return

    cid = update.effective_chat.id
    u   = update.effective_user
    bot_admin = await is_bot_chat_admin(context.bot, cid)

    lines = [
        "🔍 <b>Диагностика эфемерных сообщений</b>\n",
        f"{'✅' if bot_admin else '❌'} Бот — админ этого чата "
        f"({'можно слать эфемерные без ограничений' if bot_admin else 'нужен callback_query_id или ephemeral reply'})",
    ]

    if bot_admin:
        result = await send_ephemeral(
            context.bot, cid, u.id,
            "🔒 Тестовое эфемерное сообщение — если ты это видишь, а другие "
            "участники чата — нет, значит функция реально работает.",
            bot_is_admin=True,
        )
        if result:
            lines.append(f"✅ Сервер вернул ephemeral_message_id: <code>{result.get('ephemeral_message_id')}</code>")
            lines.append("🎉 Эфемерные сообщения РАБОТАЮТ на этом сервере!")
        else:
            lines.append("❌ Сервер принял запрос, но НЕ вернул ephemeral_message_id")
            lines.append("➡️ Значит функция технически ещё не активна на серверах Telegram "
                         "(даже при правильном вызове по всем правилам API).")
    else:
        lines.append("\nℹ️ Сделай бота администратором чата и повтори /checkephemeral, "
                     "чтобы протестировать без необходимости в callback_query_id.")

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_group_or_bot_admin(update):
        await update.message.reply_text("❌ Нет доступа — только для администраторов")
        return

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Статистика",    callback_data="ap:stats"),
         InlineKeyboardButton("🏆 Топ VRF",       callback_data="ap:top")],
        [InlineKeyboardButton("💑 Все браки",     callback_data="ap:marriages"),
         InlineKeyboardButton("👮 Бот-админы",    callback_data="ap:admins")],
        [InlineKeyboardButton("📋 Все команды",   callback_data="ap:cmds"),
         InlineKeyboardButton("ℹ️ Управление",   callback_data="ap:manage")],
        [InlineKeyboardButton("🛡️ Модерация",    callback_data="ap:mod")],
        [SBtn("Закрыть", style="danger",          callback_data="ap:close")],
    ])
    # Примечание: панель нарочно НЕ приватная — кнопки (ap:stats и т.д.)
    # завязаны на ID текущей группы через контекст callback-сообщения,
    # перенос в ЛС потребовал бы отдельно прокидывать group_id через каждый
    # callback_data. Плюс сама админ-панель — не такие чувствительные
    # персональные данные, как профиль/баланс, так что оставляем как есть.
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
    """Admin: /givebear [N] — reply to give N bears (default 1)."""
    if not await is_group_or_bot_admin(update):
        await update.message.reply_text("❌ Только для администраторов")
        return
    if not update.message.reply_to_message or update.message.reply_to_message.from_user.is_bot:
        await update.message.reply_text(
            "📌 Ответь на сообщение пользователя:\n"
            "<code>/givebear [кол-во]</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    # Parse optional count
    count = 1
    if context.args:
        try:
            count = int(context.args[0])
        except ValueError:
            pass
    count = max(1, min(count, 1000))

    target = update.message.reply_to_message.from_user
    cid    = update.effective_chat.id
    await db_ensure_user(target.id, cid, target.username or "", target.first_name)

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET bears=bears+? WHERE user_id=? AND chat_id=?",
            (count, target.id, cid),
        )
        await db.commit()

    u = await db_get_user(target.id, cid)
    await update.message.reply_text(
        f"🐻 {mention(target.id, target.first_name)} получает "
        f"<b>{count}🐻</b>!\n"
        f"Итого медведей: <b>{u['bears']}🐻</b>",
        parse_mode=ParseMode.HTML,
    )


@only_groups
async def cmd_takebear(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin: /takebear [N] — reply to remove N bears (default 1)."""
    if not await is_group_or_bot_admin(update):
        await update.message.reply_text("❌ Только для администраторов")
        return
    if not update.message.reply_to_message or update.message.reply_to_message.from_user.is_bot:
        await update.message.reply_text(
            "📌 Ответь на сообщение пользователя:\n"
            "<code>/takebear [кол-во]</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    count = 1
    if context.args:
        try:
            count = int(context.args[0])
        except ValueError:
            pass
    count = max(1, min(count, 1000))

    target = update.message.reply_to_message.from_user
    cid    = update.effective_chat.id
    await db_ensure_user(target.id, cid, target.username or "", target.first_name)

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET bears=MAX(0, bears-?) WHERE user_id=? AND chat_id=?",
            (count, target.id, cid),
        )
        await db.commit()

    u = await db_get_user(target.id, cid)
    await update.message.reply_text(
        f"🐻 У {mention(target.id, target.first_name)} изъято "
        f"<b>{count}🐻</b>.\n"
        f"Осталось медведей: <b>{u['bears']}🐻</b>",
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

    # Crash (joining phase, starter only — refunds everyone)
    crash_rnd = crash_rounds.get(cid)
    if crash_rnd and crash_rnd["state"] == "joining" and crash_rnd["starter_id"] == uid:
        for puid, p in crash_rnd["players"].items():
            await db_add_vrf(puid, cid, p["bet"])
        crash_rounds.pop(cid, None)
        cancelled.append("🚀 Краш (ставки возвращены)")

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
                "<h2>🎰 Слот — Результат</h2>"
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
                f"💎 +{fmt(bet)} VRF → {fmt(new_bal)} VRF</blockquote>"
            )
            slot_fb = (
                f"🏆 <b>СЛОТ</b>\n{h_name}: {h_combo} ({h_mult}×)\n"
                f"{o_name}: {o_combo} ({o_mult}×)\n\n🥇 {w_name} +{fmt(bet)} VRF"
            )
            await send_rich(context.bot, cid, html=slot_rich, fallback_html=slot_fb,
                            reply_markup=_play_again_kb("slot", cid, bet))
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

    # ── Giveaway wizard (gws:) ────────────────────────────
    if data.startswith("gws:"):
        parts = data.split(":")
        # parts[0]=gws, parts[1]=sid, parts[2]=step, parts[3+]=args
        sid   = parts[1]
        step  = parts[2]
        setup = giveaway_setups.get(sid)

        # Setup expired
        if not setup:
            await query.answer("❌ Сессия настройки истекла", show_alert=True)
            try:
                await query.edit_message_reply_markup(None)
            except TelegramError:
                pass
            return

        # Only the organizer can interact
        if who.id != setup["org_id"]:
            await query.answer("❌ Это не твой розыгрыш!", show_alert=True)
            return

        # cid неизвестен, если визард запущен через Inline-режим (setup["cid"]
        # изначально None) — как только у callback появляется query.message
        # (то есть бот реально видит этот чат), запоминаем его. Если бота в
        # чате нет вообще, query.message будет None и на шаге "go" мы честно
        # объясним, почему трекать реакции не получится.
        if setup["cid"] is None and query.message:
            setup["cid"] = query.message.chat_id
        cid_gw = setup["cid"]

        # ── Cancel ───────────────────────────────────────
        if step == "cancel":
            giveaway_setups.pop(sid, None)
            await query.answer("Отменено")
            await query.edit_message_text("❌ Розыгрыш отменён.")
            return

        # ── Step 1: Reaction selected ─────────────────────
        if step == "r":
            emoji = parts[3]
            setup["reaction"] = None if emoji == "any" else emoji
            label = "✨ Любую реакцию" if emoji == "any" else f"«{emoji}»"
            await query.answer(f"Реакция: {label}")
            await query.edit_message_text(
                f"🐻 <b>Розыгрыш медведей</b>\n\n"
                f"✅ Реакция: <b>{label}</b>\n\n"
                f"<b>Шаг 2 / 3</b> — Выбери медведей и победителей:\n"
                f"<i>Формат: 🐻 на победителя × кол-во победителей</i>",
                parse_mode=ParseMode.HTML,
                reply_markup=_gw_kb_bw(sid),
            )
            return

        # ── Step 2: Bears × Winners selected ─────────────
        if step == "bw":
            bears   = int(parts[3])
            winners = int(parts[4])
            setup["bears"]   = bears
            setup["winners"] = winners
            rl = "✨ Любую" if setup["reaction"] is None else f"«{setup['reaction']}»"
            await query.answer(f"Выбрано: {bears}🐻 × {winners}")
            await query.edit_message_text(
                f"🐻 <b>Розыгрыш медведей</b>\n\n"
                f"✅ Реакция: <b>{rl}</b>\n"
                f"✅ Приз: <b>{bears}🐻 × {winners} победителей</b>\n"
                f"   (итого: <b>{bears*winners}🐻</b> от тебя)\n\n"
                f"<b>Шаг 3 / 3</b> — На какое время?",
                parse_mode=ParseMode.HTML,
                reply_markup=_gw_kb_time(sid),
            )
            return

        # ── Step 3: Time selected ─────────────────────────
        if step == "t":
            minutes = int(parts[3])
            setup["minutes"] = minutes
            rl      = "✨ Любую" if setup["reaction"] is None else f"«{setup['reaction']}»"
            b, w, m = setup["bears"], setup["winners"], minutes
            await query.answer(f"Время: {minutes} мин")
            await query.edit_message_text(
                f"🐻 <b>Розыгрыш — Подтверждение</b>\n\n"
                f"🎯 Реакция: <b>{rl}</b>\n"
                f"🎁 Приз: <b>{b}🐻</b> каждому из <b>{w}</b> победителей\n"
                f"⏱ Время: <b>{m} мин</b>\n\n"
                f"Всё верно? Запускаем?",
                parse_mode=ParseMode.HTML,
                reply_markup=_gw_kb_confirm(sid),
            )
            return

        # ── Step 4: Launch! ───────────────────────────────
        if step == "go":
            setup = giveaway_setups.pop(sid, None)
            if not setup:
                await query.answer("❌ Сессия истекла", show_alert=True)
                return

            if not cid_gw:
                # Бот не видит этот чат вообще (запущено через Inline в чате,
                # где бота нет) — реакции физически невозможно отследить,
                # честно объясняем вместо того, чтобы тихо не заработать.
                await query.answer(
                    "❌ Бот должен быть добавлен в этот чат, чтобы считать "
                    "реакции — иначе Telegram просто не пришлёт боту эти события.",
                    show_alert=True,
                )
                try:
                    await query.edit_message_text(
                        "❌ <b>Не получилось запустить розыгрыш здесь</b>\n\n"
                        "Бот не состоит в этом чате, поэтому не сможет увидеть "
                        "реакции участников (это ограничение самого Telegram, "
                        "а не бота). Добавь бота в чат и попробуй снова.",
                        parse_mode=ParseMode.HTML,
                    )
                except TelegramError:
                    pass
                return

            await query.answer("🚀 Розыгрыш запускается!")
            await query.edit_message_text(
                f"✅ Розыгрыш запущен на <b>{setup['minutes']} мин</b>!\n"
                f"Следи за сообщением ниже 👇",
                parse_mode=ParseMode.HTML,
            )

            # Build giveaway message text
            rl       = f"«{setup['reaction']}»" if setup["reaction"] else "любую реакцию"
            gw_text  = (
                f"🐻 <b>РОЗЫГРЫШ МЕДВЕДЕЙ!</b>\n\n"
                f"🎁 Приз: <b>{setup['bears']}🐻</b> каждому из "
                f"<b>{setup['winners']}</b> победителей\n"
                f"👇 Поставь {rl} на это сообщение!\n\n"
                f"⏱ Осталось: <b>{fmt_cd(setup['minutes']*60)}</b>\n"
                f"👥 Участников: <b>0</b>\n\n"
                f"🔮 Победители выбираются случайно!"
            )
            gw_msg = await context.bot.send_message(
                cid_gw, gw_text, parse_mode=ParseMode.HTML,
            )

            key = f"{cid_gw}:{gw_msg.message_id}"
            giveaway_active[key] = {
                "sid":        sid,
                "cid":        cid_gw,
                "msg_id":     gw_msg.message_id,
                "org_id":     setup["org_id"],
                "org_name":   setup["org_name"],
                "reaction":   setup["reaction"],
                "bears":      setup["bears"],
                "winners":    setup["winners"],
                "minutes":    setup["minutes"],
                "start_time": datetime.now(),
                "participants": set(),
                "state":      "active",
            }

            # Launch timer in background
            context.application.create_task(
                _giveaway_timer(context.bot, key, sid)
            )
            return

        await query.answer()
        return

    # ── Crash 🚀 — setup wizard ───────────────────────────
    if data.startswith("crs:"):
        parts = data.split(":")
        sid   = parts[1]
        step  = parts[2]
        setup = crash_setups.get(sid)

        if not setup:
            await query.answer("❌ Сессия настройки истекла", show_alert=True)
            try:
                await query.edit_message_reply_markup(None)
            except TelegramError:
                pass
            return
        if who.id != setup["starter_id"]:
            await query.answer("❌ Это не твой раунд!", show_alert=True)
            return

        if step == "cancel":
            crash_setups.pop(sid, None)
            await query.answer("Отменено")
            await query.edit_message_text("❌ Запуск краша отменён.")
            return

        if step == "back":
            await query.answer()
            await query.edit_message_text(
                "🚀 <b>Краш</b>\n\nКак набираем игроков перед стартом ракеты?",
                parse_mode=ParseMode.HTML,
                reply_markup=_crash_setup_mode_kb(sid),
            )
            return

        if step == "mode":
            mode = parts[3]
            await query.answer("⏱ По времени" if mode == "time" else "👥 По игрокам")
            if mode == "time":
                await query.edit_message_text(
                    "🚀 <b>Краш</b>\n\n⏱ Сколько ждём перед стартом ракеты?",
                    parse_mode=ParseMode.HTML,
                    reply_markup=_crash_setup_time_kb(sid),
                )
            else:
                await query.edit_message_text(
                    "🚀 <b>Краш</b>\n\n👥 Сколько игроков ждём перед стартом?",
                    parse_mode=ParseMode.HTML,
                    reply_markup=_crash_setup_players_kb(sid),
                )
            return

        if step == "time":
            seconds = int(parts[3])
            setup   = crash_setups.pop(sid, None)
            if not setup:
                await query.answer("❌ Сессия истекла", show_alert=True)
                return
            await query.answer(f"⏱ {seconds} сек")
            await _crash_launch(context, query, setup["cid"], setup,
                                mode="time", join_seconds=seconds)
            return

        if step == "players":
            target = int(parts[3])
            setup  = crash_setups.pop(sid, None)
            if not setup:
                await query.answer("❌ Сессия истекла", show_alert=True)
                return
            await query.answer(f"👥 Ждём {target} чел.")
            await _crash_launch(context, query, setup["cid"], setup,
                                mode="players", target_players=target)
            return

        await query.answer()
        return

    # ── Start callback (кнопки под /start) ──────────────────
    if data.startswith("start:"):
        action = data.split(":", 1)[1]
        if action == "create_bot":
            await query.answer()
            # Показываем меню создания бота
            me = context.bot.username or "VerifureGameBot"
            newbot_url = f"https://t.me/newbot/{me}"
            await query.message.reply_text(
                "🤖 <b>Создай своего игрового бота!</b>\n\n"
                "Получишь <b>полный клон</b> с играми:\n"
                "🎲 Дуэль · Кубики · Слот · 💥 Краш · 🏢 Башня · 🏰 Лабиринт\n\n"
                "<b>Способы:</b>\n"
                "1️⃣ Кнопка ниже → @BotFather → создать → токен сам придёт\n"
                "2️⃣ Создай в @BotFather вручную → <code>/link_bot ТОКЕН</code>",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🤖 Создать через Telegram",
                                         url=newbot_url)],
                    [InlineKeyboardButton("🔑 Привязать токен вручную",
                                         callback_data="mb:add")],
                ]),
            )
        return

    # ── Maze 🏰 ────────────────────────────────────────────
    if data.startswith("mz:"):
        parts  = data.split(":")
        action = parts[1]

        if action == "bet":
            uid2, cid2, bet = int(parts[2]), int(parts[3]), int(parts[4])
            if who.id != uid2:
                await query.answer("Это не твоя кнопка!", show_alert=True)
                return
            await db_ensure_user(uid2, cid2, who.username or '', who.first_name)
            uu2 = await db_get_user(uid2, cid2)
            if not uu2 or uu2['vrf'] < bet:
                await query.answer(f"❌ Нужно {bet} VRF!", show_alert=True)
                return
            ok = await db_deduct_vrf(uid2, cid2, bet)
            if not ok:
                await query.answer("❌ Недостаточно VRF!", show_alert=True)
                return

            # Start game
            seed = random.randint(1, 9999999)
            grid, exit_pos, optimal = _mz_generate(seed)
            key2 = (uid2, cid2)
            game = {
                'uid': uid2, 'cid': cid2, 'bet': bet,
                'grid': grid, 'px': 1, 'py': 1, 'direction': 1,
                'hp': MAZE_HP_MAX, 'steps': 0, 'chests': 0,
                'visited': {(1,1)}, 'optimal': optimal,
                'exit_pos': exit_pos, 'state': 'playing', 'msg_id': None,
            }
            maze_games[key2] = game
            await query.answer("🏰 Удачи в лабиринте!")
            try:
                await query.message.delete()
            except TelegramError:
                pass
            await _mz_send(context.bot, game, '')
            return

        # Navigation actions
        uid2, cid2 = int(parts[2]), int(parts[3])
        if who.id != uid2:
            await query.answer("Это не твой лабиринт!", show_alert=True)
            return

        key2 = (uid2, cid2)
        game = maze_games.get(key2)

        if action == "Q":
            if not game or game['state'] != 'playing':
                await query.answer()
                return
            await query.answer("🏳 Сдался")
            maze_games.pop(key2, None)
            await db_add_xp(uid2, cid2, XP_PER_GAME)
            await db_record_game(uid2, cid2, won=False)
            try:
                await query.edit_message_caption(
                    caption="🏳 Покинул лабиринт. Ставка потеряна.",
                    parse_mode=ParseMode.HTML,
                    reply_markup=_mz_result_kb(cid2),
                )
            except TelegramError:
                pass
            return

        if not game or game['state'] != 'playing':
            await query.answer("Игра уже завершена!", show_alert=True)
            return

        await query.answer()
        await _mz_move(context.bot, game, action)
        return

    # ── Managed Bots control 🤖 ────────────────────────────
    if data.startswith("mb:"):
        parts  = data.split(":")
        action = parts[1] if len(parts) > 1 else ""

        if action == "add":
            await query.answer()
            me = context.bot.username or "VerifureGameBot"
            await query.message.reply_text(
                "🔑 <b>Привязка существующего бота</b>\n\n"
                "1. Создай бота в @BotFather: /newbot\n"
                "2. Скопируй токен (вида <code>123456:ABC...</code>)\n"
                "3. Отправь команду:\n"
                "   <code>/link_bot ТВОЙ_ТОКЕН</code>",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton(
                        "🤖 Открыть @BotFather",
                        url=f"https://t.me/newbot/{me}"
                    )
                ]]),
            )
            return

        if action == "manage" and len(parts) >= 3:
            bot_uid = int(parts[2])
            bots = await _mb_by_owner(who.id)
            if not any(row[0] == bot_uid for row in bots):
                await query.answer("Это не твой бот!", show_alert=True)
                return
            settings = await _mb_get_settings(bot_uid)
            if not settings:
                await query.answer("Бот не найден!", show_alert=True)
                return
            uname = settings.get("bot_username", "")
            name  = f"@{uname}" if uname else f"ID {bot_uid}"
            alive = bot_uid in _managed_threads and _managed_threads[bot_uid].is_alive()
            status = "🟢 работает" if alive else "🔴 остановлен"
            wtext = settings.get("welcome_text", "") or "(не задан)"
            desc  = settings.get("description", "") or "(не задан)"
            await query.answer()
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("✏️ Изменить приветствие",
                                      callback_data=f"mb:edit_welcome:{bot_uid}")],
                [InlineKeyboardButton("📝 Изменить описание",
                                      callback_data=f"mb:edit_desc:{bot_uid}")],
                [InlineKeyboardButton("🔑 Обновить токен",
                                      callback_data=f"mb:edit_token:{bot_uid}")],
                [InlineKeyboardButton("⚡ Обновить команды",
                                      callback_data=f"mb:refresh_cmds:{bot_uid}")],
                [InlineKeyboardButton("▶ Перезапустить" if not alive else "🔄 Перезапустить",
                                      callback_data=f"mb:restart:{bot_uid}")],
                [InlineKeyboardButton("🗑 Удалить бота",
                                      callback_data=f"mb:delete:{bot_uid}")],
            ])
            try:
                await query.edit_message_text(
                    f"⚙️ <b>Управление {name}</b>\n\n"
                    f"Статус: {status}\n"
                    f"Приветствие: <i>{wtext[:80]}</i>\n"
                    f"Описание: <i>{desc[:80]}</i>",
                    parse_mode=ParseMode.HTML,
                    reply_markup=kb,
                )
            except TelegramError:
                await query.message.reply_text(
                    f"⚙️ <b>Управление {name}</b>\n\nСтатус: {status}",
                    parse_mode=ParseMode.HTML, reply_markup=kb,
                )
            return

        if action == "refresh_cmds" and len(parts) >= 3:
            bot_uid = int(parts[2])
            bots = await _mb_by_owner(who.id)
            if not any(row[0] == bot_uid for row in bots):
                await query.answer("Не твой бот!", show_alert=True)
                return
            settings = await _mb_get_settings(bot_uid)
            if not settings:
                await query.answer("Бот не найден!", show_alert=True)
                return
            token = settings["bot_token"]
            await query.answer("⚡ Обновляю команды...")
            try:
                from telegram import Bot as _Bot
                tmp = _Bot(token=token)
                await _setup_child_bot(tmp, who.id)
                await tmp.close()
                await query.edit_message_text(
                    "✅ Команды обновлены! Напиши <code>/help</code> в боте.",
                    parse_mode=ParseMode.HTML,
                )
            except Exception as exc:
                await query.edit_message_text(f"❌ Ошибка: {exc}")
            return

        if action in ("edit_welcome", "edit_desc", "edit_token") and len(parts) >= 3:
            bot_uid = int(parts[2])
            bots = await _mb_by_owner(who.id)
            if not any(row[0] == bot_uid for row in bots):
                await query.answer("Не твой бот!", show_alert=True)
                return
            prompts = {
                "edit_welcome": (
                    "✏️ <b>Отправь новый текст приветствия</b>\n\n"
                    "Это сообщение пользователи увидят при /start.\n"
                    "HTML-теги поддерживаются.\n\n"
                    "Отправь текст следующим сообщением:"
                ),
                "edit_desc": (
                    "📝 <b>Отправь новое описание бота</b>\n\n"
                    "Описание отображается в профиле бота.\n"
                    "Атрибуция @VerifureGameBot добавляется автоматически.\n\n"
                    "Отправь текст следующим сообщением:"
                ),
                "edit_token": (
                    "🔑 <b>Отправь новый токен бота</b>\n\n"
                    "Получи токен у @BotFather: /mybots → Выбери бота → API Token\n\n"
                    "⚠️ Бот перезапустится после смены токена.\n"
                    "Отправь токен следующим сообщением:"
                ),
            }
            await query.answer()
            context.user_data[f"mb_edit_{action.replace('edit_', '')}"] = bot_uid
            await query.message.reply_text(
                prompts[action], parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("❌ Отмена", callback_data="mb:cancel")
                ]]),
            )
            return

        if action == "restart" and len(parts) >= 3:
            bot_uid = int(parts[2])
            # Проверяем что это бот юзера
            bots = await _mb_by_owner(who.id)
            if not any(row[0] == bot_uid for row in bots):
                await query.answer("Это не твой бот!", show_alert=True)
                return
            # Получаем токен из БД
            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute(
                    "SELECT bot_token, bot_username FROM managed_bots WHERE bot_user_id=?",
                    (bot_uid,)
                ) as cur:
                    row = await cur.fetchone()
            if not row:
                await query.answer("Бот не найден в БД!", show_alert=True)
                return
            token, uname = row
            await query.answer("▶ Перезапускаю...")
            _spawn_child(token, bot_uid)
            await asyncio.sleep(2)
            t = _managed_threads.get(bot_uid)
            alive = t and t.is_alive()
            name = f"@{uname}" if uname else f"ID {bot_uid}"
            try:
                await query.edit_message_text(
                    f"{'✅ Бот ' + name + ' запущен!' if alive else '❌ Запустить не удалось — проверь токен в @BotFather'}",
                    parse_mode=ParseMode.HTML,
                )
            except TelegramError:
                pass
            return

        if action == "delete" and len(parts) >= 3:
            bot_uid = int(parts[2])
            bots = await _mb_by_owner(who.id)
            if not any(row[0] == bot_uid for row in bots):
                await query.answer("Это не твой бот!", show_alert=True)
                return
            uname = next((row[1] for row in bots if row[0] == bot_uid), "")
            name  = f"@{uname}" if uname else f"ID {bot_uid}"
            # Confirm button
            await query.answer()
            await query.message.reply_text(
                f"⚠️ Удалить бота <b>{name}</b>?\n\n"
                "Бот будет остановлен и удалён из системы. "
                "Сам аккаунт бота в Telegram останется — "
                "управляй им через @BotFather.",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([[
                    SBtn("🗑 Да, удалить", style="danger",
                         callback_data=f"mb:confirm_delete:{bot_uid}"),
                    SBtn("Отмена", style="primary",
                         callback_data="mb:cancel"),
                ]]),
            )
            return

        if action == "confirm_delete" and len(parts) >= 3:
            bot_uid = int(parts[2])
            bots = await _mb_by_owner(who.id)
            if not any(row[0] == bot_uid for row in bots):
                await query.answer("Это не твой бот!", show_alert=True)
                return
            # Останавливаем поток (daemon — умрёт сам, но флаг снимаем)
            t = _managed_threads.pop(bot_uid, None)
            # Деактивируем в БД
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    "UPDATE managed_bots SET active=0 WHERE bot_user_id=?",
                    (bot_uid,)
                )
                await db.commit()
            await query.answer("Бот удалён из системы")
            try:
                await query.edit_message_text(
                    "✅ Бот удалён. Процесс завершится автоматически.",
                    parse_mode=ParseMode.HTML,
                )
            except TelegramError:
                pass
            return

        if action == "cancel":
            await query.answer()
            try:
                await query.message.delete()
            except TelegramError:
                pass
            return

        await query.answer()
        return

    # ── Play Again 🔄 ─────────────────────────────────────────
    if data.startswith("ra:"):
        _, game_name, rcid_s, *rest = data.split(":")
        rcid = int(rcid_s)
        bet  = int(rest[0]) if rest else 0

        await query.answer()

        if game_name == "maze":
            # Start new maze — show bet selection
            presets2 = MAZE_BET_PRESETS
            rows_m = [
                [SBtn(f"{a} VRF", style="primary",
                      callback_data=f"mz:bet:{who.id}:{rcid}:{a}")
                 for a in presets2[:3]],
                [SBtn(f"{a} VRF", style="primary",
                      callback_data=f"mz:bet:{who.id}:{rcid}:{a}")
                 for a in presets2[3:]],
            ]
            await query.message.reply_text(
                "🏰 <b>Новый лабиринт</b> — выбери ставку:",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(rows_m),
            )
            return

        if game_name in ("crash",):
            # Crash: start the wizard fresh
            await query.message.reply_text(
                "🚀 Запускай новый раунд:", parse_mode=ParseMode.HTML,
                reply_markup=_crash_setup_mode_kb(str(uuid.uuid4())[:8]),
            )
            return

        if game_name == "tower":
            # Tower: send /tower hint (can't easily call cmd_tower from callback)
            await query.message.reply_text(
                "🏢 Новая башня:",
                reply_markup=InlineKeyboardMarkup([[
                    SBtn("🏢 Начать башню", style="success",
                         callback_data=f"ra_tower:{rcid}"),
                ]]),
            )
            return

        if game_name == "slot":
            # Slot PvP: show quick bet selection
            presets = [25, 50, 100, 250, 500]
            rows = [
                [SBtn(f"{a} VRF", style="primary",
                      callback_data=f"slsp:{rcid}:{who.id}:{a}")
                 for a in presets[:3]],
                [SBtn(f"{a} VRF", style="primary",
                      callback_data=f"slsp:{rcid}:{who.id}:{a}")
                 for a in presets[3:]],
            ]
            await query.message.reply_text(
                "🎰 <b>Слот-машина</b> — выбери ставку:",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(rows),
            )
            return

        # PvP games (duel, cubes, sport): show bet picker + offer challenge
        presets   = [25, 50, 100, 250, 500]
        emoji_map = {"duel": "⚔️", "cubes": "🎲", "sport": "🏅"}
        icon      = emoji_map.get(game_name, "🎮")
        name_map  = {"duel": "Дуэль", "cubes": "Кубики", "sport": "Спорт"}
        gname     = name_map.get(game_name, "Игра")

        # Default to last bet if known, else 50
        default_bet = bet if bet > 0 else 50

        rows = [
            [SBtn(f"{a} VRF", style="primary",
                  callback_data=f"ra_pvp:{game_name}:{rcid}:{who.id}:{a}")
             for a in presets[:3]],
            [SBtn(f"{a} VRF", style="primary",
                  callback_data=f"ra_pvp:{game_name}:{rcid}:{who.id}:{a}")
             for a in presets[3:]],
        ]
        await query.message.reply_text(
            f"{icon} <b>{gname}</b> — выбери ставку:",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(rows),
        )
        return

    if data.startswith("ra_tower:"):
        # Directly start a tower game from the play-again button
        rcid = int(data.split(":")[1])
        existing = tower_games.get(rcid)
        if existing and existing["state"] != "ended":
            await query.answer("Башня уже идёт! Присоединяйся.", show_alert=True)
            return
        await query.answer("🏢 Запускаю башню...")
        # Spoof an Update-like object via context bot to call the tower logic
        await db_ensure_user(who.id, rcid, who.username or "", who.first_name)
        tower_games[rcid] = {"cid": rcid, "state": "launching"}
        max_f = random.randint(6, 10)
        bombs = [random.choice(["L", "R"]) for _ in range(max_f)]
        now   = datetime.now()
        stub  = {
            "cid": rcid, "state": "joining",
            "starter_id": who.id, "starter_name": who.first_name,
            "max_floors": max_f, "floor": 1,
            "bomb_doors": bombs, "mults": TOWER_MULTS[:max_f],
            "players": {}, "voted": {}, "history": [],
            "join_deadline": now + timedelta(seconds=TOWER_JOIN_SECS),
            "vote_deadline": None, "msg_id": None,
        }
        loop = asyncio.get_running_loop()
        img  = await loop.run_in_executor(None, _tower_image_sync, stub, "joining")
        try:
            if img:
                msg = await context.bot.send_photo(
                    chat_id=rcid, photo=io.BytesIO(img),
                    caption=_tower_join_caption(stub), parse_mode=ParseMode.HTML,
                    reply_markup=_tower_join_kb(rcid),
                )
            else:
                msg = await context.bot.send_message(
                    rcid, _tower_join_caption(stub), parse_mode=ParseMode.HTML,
                    reply_markup=_tower_join_kb(rcid),
                )
        except TelegramError:
            tower_games.pop(rcid, None)
            return
        stub["msg_id"] = msg.message_id
        tower_games[rcid] = stub
        context.application.create_task(_tower_join_loop(context.bot, rcid))
        return

    if data.startswith("ra_pvp:"):
        # PvP play-again: post a public challenge with Accept/Decline buttons
        parts     = data.split(":")
        game_name = parts[1]; rcid = int(parts[2])
        challenger_id = int(parts[3]); bet = int(parts[4])

        if who.id != challenger_id:
            await query.answer("Это не твоя кнопка!", show_alert=True)
            return

        await query.answer(f"Вызов брошен на {bet} VRF!")

        cmd_map   = {"duel": "/duel", "cubes": "/cubes", "sport": "/basket"}
        icon_map  = {"duel": "⚔️", "cubes": "🎲", "sport": "🏅"}
        name_map  = {"duel": "Дуэль", "cubes": "Кубики", "sport": "Спорт"}
        icon      = icon_map.get(game_name, "🎮")
        gname     = name_map.get(game_name, "Игра")
        game_id   = str(uuid.uuid4())[:8]

        # Store a pending challenge
        chal_key = f"ra:{game_id}"

        if game_name == "duel":
            duel_challenges[f"{rcid}:{challenger_id}:0"] = {
                "cid": rcid, "c_id": challenger_id,
                "c_name": who.first_name, "o_id": 0,
                "bet": bet, "created": datetime.now(),
            }
        # For cubes/sport the opponent needs to reply via a message; just show the invite
        await context.bot.send_message(
            rcid,
            f"{icon} <b>{gname}</b>\n\n"
            f"{mention(challenger_id, who.first_name)} ищет соперника!\n"
            f"💎 Ставка: <b>{bet} VRF</b>\n\n"
            f"<i>Ответь на это сообщение командой "
            f"<code>/{game_name if game_name != 'sport' else 'basket'} {bet}</code> "
            f"чтобы принять вызов.</i>",
            parse_mode=ParseMode.HTML,
        )
        return

    # ── Crash 🚀 ──────────────────────────────────────────
    if data.startswith("cr:"):
        parts   = data.split(":")
        action  = parts[1]
        rcid    = int(parts[2])
        rnd     = crash_rounds.get(rcid)

        if action == "join":
            amount = int(parts[3])
            ok, msg = await _crash_join_player(context, rcid, who, amount)
            await query.answer(msg, show_alert=not ok)
            return

        if action == "custom":
            if not rnd or rnd["state"] != "joining":
                await query.answer("❌ Окно ставок закрыто!", show_alert=True)
                return
            if who.id in rnd["players"]:
                await query.answer("Ты уже сделал ставку в этом раунде!", show_alert=True)
                return
            crash_custom_pending[(rcid, who.id)] = {
                "expires": datetime.now() + timedelta(seconds=60),
            }
            try:
                await context.bot.send_message(
                    rcid,
                    f"✏️ {mention(who.id, who.first_name)}, напиши сумму ставки "
                    f"(минимум <b>{MIN_BET} VRF</b>, максимум — весь твой баланс) "
                    f"ответом на это сообщение:",
                    parse_mode=ParseMode.HTML,
                    reply_to_message_id=rnd["msg_id"],
                    reply_markup=ForceReply(selective=True, input_field_placeholder="Например: 150"),
                )
            except TelegramError:
                pass
            await query.answer("✍️ Напиши сумму в чат")
            return

        if action == "cancel":
            if not rnd or rnd["state"] != "joining":
                await query.answer("❌ Раунд уже идёт или завершён", show_alert=True)
                return
            if who.id != rnd["starter_id"]:
                await query.answer("❌ Только организатор может отменить раунд", show_alert=True)
                return
            for puid, p in rnd["players"].items():
                await db_add_vrf(puid, rcid, p["bet"])
            crash_rounds.pop(rcid, None)
            await query.answer("Раунд отменён, ставки возвращены")
            try:
                await query.edit_message_caption(
                    caption="🚫 <b>Раунд отменён организатором.</b>\nВсе ставки возвращены.",
                    parse_mode=ParseMode.HTML, reply_markup=None,
                )
            except TelegramError:
                pass
            return

        if action == "cashout":
            if not rnd or rnd["state"] != "flying":
                await query.answer("❌ Раунд не активен", show_alert=True)
                return
            p = rnd["players"].get(who.id)
            if not p:
                await query.answer("❌ Ты не участвуешь в этом раунде!", show_alert=True)
                return
            if p["cashed"]:
                await query.answer(f"Ты уже забрал ×{p['mult']:.2f}!", show_alert=True)
                return

            elapsed  = (datetime.now() - rnd["flight_start"]).total_seconds()
            cur_mult = _crash_mult_at(elapsed)
            if cur_mult >= rnd["crash_point"]:
                await query.answer("💥 Поздно! Ракета уже взорвалась...", show_alert=True)
                if rnd["state"] == "flying":
                    await _crash_end(context.bot, rcid, rnd["crash_point"])
                return

            # Claim the cashout SYNCHRONOUSLY before any await — prevents
            # a double-tap delivering two payouts if Telegram retries the callback.
            p["cashed"] = True
            p["mult"]   = cur_mult
            payout      = round(p["bet"] * cur_mult)

            await db_add_vrf(who.id, rcid, payout)
            await db_add_xp(who.id, rcid, XP_PER_WIN)
            await db_record_game(who.id, rcid, won=True)
            await query.answer(f"💰 Забрал ×{cur_mult:.2f}! +{fmt(payout)} VRF")

            try:
                await query.edit_message_caption(
                    caption=_crash_flight_text(rnd, cur_mult),
                    parse_mode=ParseMode.HTML,
                    reply_markup=_crash_flight_kb(rcid),
                )
            except TelegramError:
                pass

            if all(pl["cashed"] for pl in rnd["players"].values()):
                await _crash_end(context.bot, rcid, cur_mult)
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
                [InlineKeyboardButton("🛡️ Модерация",   callback_data="ap:mod")],
                [SBtn("Закрыть", style="danger",         callback_data="ap:close")],
            ])
            await query.edit_message_text(
                f"🛡️ <b>Verifure Admin Panel</b>\n\n{E_ALERT} Выбери раздел:",
                parse_mode=ParseMode.HTML, reply_markup=kb,
            )

        elif action == "close":
            await query.answer("Закрыто")
            await query.message.delete()

        elif action == "mod":
            await query.answer()
            mutes = await db_get_mutes(cid)
            warns = await db_get_chat_warns(cid)
            m_cnt = len(mutes)
            w_cnt = sum(r["cnt"] for r in warns)
            mut_lines = ""
            if mutes:
                mut_lines = "\n<b>🔇 Замутены:</b>\n" + "\n".join(
                    "  • " + mention(m["user_id"], "id" + str(m["user_id"])) + " — " +
                    _fmt_until(datetime.fromisoformat(m["until"]) if m.get("until") else None) +
                    (f" [{m['reason']}]" if m.get("reason") else "")
                    for m in mutes[:10]
                )
            warn_lines = ""
            if warns:
                warn_lines = "\n<b>⚠️ Варны:</b>\n" + "\n".join(
                    "  • " + mention(r["user_id"], "id" + str(r["user_id"])) +
                    f" — {r['cnt']}/{_WARN_LIMIT}"
                    for r in warns[:10]
                )
            mod_kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔇 Замутить",    callback_data="ap:mod_help_mute"),
                 InlineKeyboardButton("🔊 Размутить",   callback_data="ap:mod_help_unmute")],
                [InlineKeyboardButton("⚠️ Варн",        callback_data="ap:mod_help_warn"),
                 InlineKeyboardButton("✅ Снять варн",  callback_data="ap:mod_help_unwarn")],
                [InlineKeyboardButton("👢 Кик",         callback_data="ap:mod_help_kick"),
                 InlineKeyboardButton("🚫 Бан",         callback_data="ap:mod_help_ban")],
                [SBtn("◀ Назад", style="primary",       callback_data="ap:back")],
            ])
            await query.edit_message_text(
                f"🛡️ <b>Модерация</b>\n\n"
                f"🔇 Замутено: <b>{m_cnt}</b>  ·  ⚠️ Всего варнов: <b>{w_cnt}</b>\n"
                f"{mut_lines}{warn_lines}\n\n"
                f"<b>Команды (ответом на сообщение):</b>\n"
                f"<code>/mute [10m/2h/1d/навсегда] [причина]</code>\n"
                f"<code>/unmute</code>\n"
                f"<code>/pred [причина]</code>  →  лимит {_WARN_LIMIT} → автомут 24ч\n"
                f"<code>/unpred</code>  ·  <code>/clearpred</code>\n"
                f"<code>/predlist</code>  ·  <code>/mutelist</code>\n"
                f"<code>/kick [причина]</code>\n"
                f"<code>/ban [срок] [причина]</code>  ·  <code>/unban</code>",
                parse_mode=ParseMode.HTML,
                reply_markup=mod_kb,
            )

        elif action.startswith("mod_help_"):
            await query.answer()  # no-op, info is already in the panel

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

    # ── Tower 🏢 ───────────────────────────────────────────
    if data.startswith("tw:"):
        parts  = data.split(":")
        action = parts[1]
        tcid   = int(parts[2])
        game   = tower_games.get(tcid)

        if action == "join":
            amount = int(parts[3])
            if not game or game["state"] != "joining":
                await query.answer("❌ Набор уже закрыт!", show_alert=True)
                return
            if who.id in game["players"]:
                await query.answer("Ты уже в игре!", show_alert=True)
                return
            await db_ensure_user(who.id, tcid, who.username or "", who.first_name)
            u2 = await db_get_user(who.id, tcid)
            if not u2 or u2["vrf"] < amount:
                await query.answer(f"❌ Недостаточно VRF! Нужно {amount}.", show_alert=True)
                return
            ok = await db_deduct_vrf(who.id, tcid, amount)
            if not ok:
                await query.answer("❌ Недостаточно VRF!", show_alert=True)
                return
            game["players"][who.id] = {
                "name": who.first_name, "bet": amount,
                "alive": True, "cashed": False,
                "cash_floor": 0, "cash_mult": 1.0, "payout": 0,
            }
            await query.answer(f"✅ Ставка {amount} VRF принята!")
            return

        if action == "custom":
            if not game or game["state"] != "joining":
                await query.answer("❌ Набор закрыт!", show_alert=True)
                return
            if who.id in game["players"]:
                await query.answer("Ты уже участвуешь!", show_alert=True)
                return
            tower_custom_pending[(tcid, who.id)] = {"expires": datetime.now() + timedelta(seconds=60)}
            try:
                await context.bot.send_message(
                    tcid,
                    f"✏️ {mention(who.id, who.first_name)}, напиши свою ставку "
                    f"(минимум <b>{TOWER_MIN_BET} VRF</b>) ответом на это сообщение:",
                    parse_mode=ParseMode.HTML,
                    reply_to_message_id=game["msg_id"],
                    reply_markup=ForceReply(selective=True),
                )
            except TelegramError:
                pass
            await query.answer("✍️ Напиши сумму в чат")
            return

        if action == "L" or action == "R":
            if not game or game["state"] != "voting":
                await query.answer("❌ Голосование неактивно!", show_alert=True)
                return
            if who.id not in game["players"] or game["players"][who.id]["cashed"]:
                await query.answer("❌ Ты не в игре!", show_alert=True)
                return
            prev = game["voted"].get(who.id)
            game["voted"][who.id] = action
            msg = ("✅ Голос учтён!" if not prev
                   else f"Голос изменён: {prev} → {action}")
            await query.answer(msg)
            return

        if action == "cash":
            if not game or game["state"] not in ("voting", "cashout"):
                await query.answer("Нельзя забрать сейчас!", show_alert=True)
                return
            p = game["players"].get(who.id)
            if not p:
                await query.answer("Ты не в игре!", show_alert=True)
                return
            if not p.get("alive", True):
                await query.answer("Ты уже выбыл!", show_alert=True)
                return
            if p["cashed"]:
                await query.answer(f"Уже забрал x{p['cash_mult']:.2f}!", show_alert=True)
                return
            mults   = game.get("mults", TOWER_MULTS)
            cur_f   = game["floor"]
            # During cashout window we pay the PREVIOUS floor's mult;
            # during voting we pay the CURRENT floor's mult
            if game["state"] == "cashout":
                cash_f = max(1, cur_f - 1)
            else:
                cash_f = cur_f
            mult   = mults[min(cash_f-1, len(mults)-1)]
            payout = round(p["bet"] * mult)
            # Claim synchronously before any await
            p["cashed"] = True; p["alive"] = False
            p["cash_floor"] = cash_f; p["cash_mult"] = mult; p["payout"] = payout
            await db_add_vrf(who.id, tcid, payout)
            await db_add_xp(who.id, tcid, XP_PER_WIN)
            await db_record_game(who.id, tcid, won=True)
            await query.answer(f"Забрал x{mult:.2f}! +{fmt(payout)} VRF")
            return

        await query.answer()
        return

    # ══════════════════════════════════════════════════════
    #           КЛАНЫ  🏰  callback-обработчики
    # ══════════════════════════════════════════════════════
    if data.startswith("cl:"):
        parts  = data.split(":")
        action = parts[1]

        if action == "noop":
            await query.answer()
            return

        if action == "cancel_msg":
            await query.answer("Отменено")
            try:
                await query.edit_message_reply_markup(None)
            except TelegramError:
                pass
            return

        if action == "back":
            text, kb = await _clan_hub_text(who.id, cid)
            await query.answer()
            try:
                await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
            except TelegramError:
                pass
            return

        # ── Создать клан ──────────────────────────────────
        if action == "create":
            existing = await db_get_user_clan(who.id, cid)
            if existing:
                await query.answer("❌ Ты уже состоишь в клане!", show_alert=True)
                return
            uu = await db_get_user(who.id, cid)
            if not uu or uu["vrf"] < CLAN_CREATE_COST:
                await query.answer(
                    f"❌ Нужно {fmt(CLAN_CREATE_COST)} VRF, у тебя {fmt(uu['vrf'] if uu else 0)}",
                    show_alert=True,
                )
                return
            clan_pending_input[(cid, who.id)] = {
                "kind": "clan_name", "expires": datetime.now() + timedelta(seconds=90),
            }
            await query.answer()
            try:
                await context.bot.send_message(
                    cid,
                    f"✏️ {mention(who.id, who.first_name)}, напиши название клана "
                    f"({CLAN_NAME_MIN}-{CLAN_NAME_MAX} символов) ответом на это сообщение:",
                    parse_mode=ParseMode.HTML,
                    reply_markup=ForceReply(selective=True, input_field_placeholder="Название клана"),
                )
            except TelegramError:
                pass
            return

        # ── Список кланов / вступление ────────────────────
        if action == "browse":
            clans = await db_list_clans(cid)
            if not clans:
                await query.answer("Кланов в этом чате пока нет", show_alert=True)
                return
            rows = [[SBtn(f"🏰 {c['name']} · 👥{c['member_count']} · 💰{fmt(c['treasury'])}",
                         style="primary", callback_data=f"cl:apply:{c['id']}")]
                   for c in clans[:15]]
            rows.append([SBtn("Отмена", style="danger", callback_data="cl:cancel_msg")])
            await query.answer()
            try:
                await query.edit_message_text(
                    "📋 <b>Кланы этого чата</b>\n\nВыбери, куда подать заявку:",
                    parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(rows),
                )
            except TelegramError:
                pass
            return

        if action == "apply":
            clan_id = int(parts[2])
            if await db_get_user_clan(who.id, cid):
                await query.answer("❌ Ты уже состоишь в клане!", show_alert=True)
                return
            if await db_get_application(who.id, cid):
                await query.answer("❌ Заявка уже отправлена, жди решения лидера", show_alert=True)
                return
            clan = await db_get_clan(clan_id)
            if not clan:
                await query.answer("❌ Клан не найден", show_alert=True)
                return
            ok = await db_apply_to_clan(who.id, cid, clan_id)
            if not ok:
                await query.answer("❌ Не удалось подать заявку", show_alert=True)
                return
            await query.answer("✅ Заявка отправлена!")
            try:
                await query.edit_message_text(
                    f"📨 Заявка в клан <b>{clan['name']}</b> отправлена! Жди решения лидера.",
                    parse_mode=ParseMode.HTML,
                )
            except TelegramError:
                pass
            # Уведомляем лидера эфемерно (или в личку/чат, если недоступно)
            kb_appr = InlineKeyboardMarkup([[
                SBtn("✅ Принять", style="success", callback_data=f"cl:appr:{who.id}"),
                SBtn("❌ Отклонить", style="danger", callback_data=f"cl:rej:{who.id}"),
            ]])
            notice = (
                f"📨 <b>Новая заявка в клан «{clan['name']}»</b>\n\n"
                f"{mention(who.id, who.first_name)} хочет вступить."
            )
            await send_ephemeral_or_normal(
                context.bot, cid, clan["leader_id"], notice, reply_markup=kb_appr,
            )
            return

        # ── Одобрение/отклонение заявки лидером ───────────
        if action in ("appr", "rej"):
            applicant_id = int(parts[2])
            my_clan = await db_get_user_clan(who.id, cid)
            if not my_clan or my_clan["my_role"] != "leader":
                await query.answer("❌ Решать заявки может только лидер клана", show_alert=True)
                return
            app = await db_get_application(applicant_id, cid)
            if not app or app["clan_id"] != my_clan["id"]:
                await query.answer("❌ Заявка не найдена или уже обработана", show_alert=True)
                return
            await db_remove_application(applicant_id, cid)
            app_u = await db_get_user(applicant_id, cid)
            app_name = app_u["first_name"] if app_u else "Игрок"
            if action == "appr":
                await db_add_clan_member(applicant_id, cid, my_clan["id"], "member")
                await query.answer("✅ Принят(а) в клан!")
                try:
                    await query.edit_message_text(
                        f"✅ {mention(applicant_id, app_name)} принят(а) в клан <b>{my_clan['name']}</b>!",
                        parse_mode=ParseMode.HTML,
                    )
                except TelegramError:
                    pass
                await send_ephemeral_or_normal(
                    context.bot, cid, applicant_id,
                    f"🎉 Тебя приняли в клан <b>{my_clan['name']}</b>! Добро пожаловать.",
                )
            else:
                await query.answer("Отклонено")
                try:
                    await query.edit_message_text(
                        f"❌ Заявка {mention(applicant_id, app_name)} в клан <b>{my_clan['name']}</b> отклонена.",
                        parse_mode=ParseMode.HTML,
                    )
                except TelegramError:
                    pass
                await send_ephemeral_or_normal(
                    context.bot, cid, applicant_id,
                    f"❌ Твою заявку в клан <b>{my_clan['name']}</b> отклонили.",
                )
            return

        # ── Список заявок (для лидера) ────────────────────
        if action == "apps":
            my_clan = await db_get_user_clan(who.id, cid)
            if not my_clan or my_clan["my_role"] != "leader":
                await query.answer("❌ Только для лидера", show_alert=True)
                return
            apps = await db_get_clan_applications(my_clan["id"])
            await query.answer()
            if not apps:
                try:
                    await query.edit_message_text("📨 Заявок пока нет.",
                                                  reply_markup=InlineKeyboardMarkup(
                                                      [[SBtn("← Назад", style="primary", callback_data="cl:back")]]))
                except TelegramError:
                    pass
                return
            lines = ["📨 <b>Заявки на вступление</b>\n"]
            rows = []
            for a in apps[:10]:
                label = f"@{a['username']}" if a["username"] else a["first_name"]
                lines.append(f"• {label}")
                rows.append([
                    SBtn(f"✅ {label}", style="success", callback_data=f"cl:appr:{a['user_id']}"),
                    SBtn("❌", style="danger", callback_data=f"cl:rej:{a['user_id']}"),
                ])
            rows.append([SBtn("← Назад", style="primary", callback_data="cl:back")])
            try:
                await query.edit_message_text("\n".join(lines), parse_mode=ParseMode.HTML,
                                              reply_markup=InlineKeyboardMarkup(rows))
            except TelegramError:
                pass
            return

        # ── Роли ───────────────────────────────────────────
        if action == "roles":
            my_clan = await db_get_user_clan(who.id, cid)
            if not my_clan:
                await query.answer("❌ Ты не в клане", show_alert=True)
                return
            rows = [[SBtn(f"{r['emoji']} {r['label']}" + (" ✅" if k == my_clan["my_role"] else ""),
                         style="success" if k == my_clan["my_role"] else "primary",
                         callback_data=f"cl:setrole:{k}")]
                   for k, r in CLAN_ROLES.items()]
            rows.append([SBtn("← Назад", style="primary", callback_data="cl:back")])
            descs = "\n".join(f"{r['emoji']} <b>{r['label']}</b> — {r['desc']}" for r in CLAN_ROLES.values())
            await query.answer()
            try:
                await query.edit_message_text(
                    f"🎭 <b>Выбери свою роль в клане</b>\n\n{descs}",
                    parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(rows),
                )
            except TelegramError:
                pass
            return

        if action == "setrole":
            role = parts[2]
            my_clan = await db_get_user_clan(who.id, cid)
            if not my_clan:
                await query.answer("❌ Ты не в клане", show_alert=True)
                return
            if role not in CLAN_ROLES or role == "leader":
                await query.answer("❌ Неверная роль", show_alert=True)
                return
            if my_clan["my_role"] == "leader":
                await query.answer("👑 Лидер не может сменить роль — сначала передай лидерство", show_alert=True)
                return
            await db_set_member_role(who.id, cid, role)
            r = CLAN_ROLES[role]
            await query.answer(f"✅ Теперь ты {r['emoji']} {r['label']}")
            text, kb = await _clan_hub_text(who.id, cid)
            try:
                await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
            except TelegramError:
                pass
            return

        # ── Участники ────────────────────────────────────
        if action == "members":
            my_clan = await db_get_user_clan(who.id, cid)
            if not my_clan:
                await query.answer("❌ Ты не в клане", show_alert=True)
                return
            members = await db_get_clan_members(my_clan["id"])
            lines = [f"👥 <b>Участники клана «{my_clan['name']}»</b> ({len(members)})\n"]
            for m in members:
                r = CLAN_ROLES.get(m["role"], CLAN_ROLES["member"])
                label = "👑 Лидер" if m["role"] == "leader" else f"{r['emoji']} {r['label']}"
                lines.append(f"• {mention(m['user_id'], m['first_name'])} — {label}")
            await query.answer()
            try:
                await query.edit_message_text(
                    "\n".join(lines), parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup([[SBtn("← Назад", style="primary", callback_data="cl:back")]]),
                )
            except TelegramError:
                pass
            return

        # ── Казна (карточка) ──────────────────────────────
        if action == "treasury":
            my_clan = await db_get_user_clan(who.id, cid)
            if not my_clan:
                await query.answer("❌ Ты не в клане", show_alert=True)
                return
            can_withdraw = my_clan["my_role"] in ("leader", "treasurer")
            text = (
                f"💰 <b>Казна клана «{my_clan['name']}»</b>\n\n"
                f"Баланс: <b>{fmt(my_clan['treasury'])} VRF</b>\n\n"
                f"Пополнить: напиши <code>казна +500</code>\n"
                + (f"Вывести: напиши <code>казна -200</code> (доступно тебе как {CLAN_ROLES[my_clan['my_role']]['label']})"
                   if can_withdraw else
                   "Вывод доступен только 💰 Казначею и 👑 Лидеру.")
            )
            await query.answer()
            try:
                await query.edit_message_text(
                    text, parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup([[SBtn("← Назад", style="primary", callback_data="cl:back")]]),
                )
            except TelegramError:
                pass
            return

        # ── Защита ─────────────────────────────────────────
        if action == "defense":
            my_clan = await db_get_user_clan(who.id, cid)
            if not my_clan:
                await query.answer("❌ Ты не в клане", show_alert=True)
                return
            lvl  = my_clan["defense_level"]
            cost = CLAN_DEFENSE_BASE_COST * lvl
            can_upgrade = my_clan["my_role"] in ("leader", "treasurer") and lvl < CLAN_MAX_DEFENSE_LVL
            text = (
                f"🛡 <b>Защита клана «{my_clan['name']}»</b>\n\n"
                f"Текущий уровень: <b>{lvl}</b>/{CLAN_MAX_DEFENSE_LVL}\n"
                f"Снижает шанс успеха вражеских атак и рейдов.\n\n"
            )
            rows = []
            if lvl >= CLAN_MAX_DEFENSE_LVL:
                text += "✅ Максимальный уровень достигнут!"
            else:
                text += f"Апгрейд до <b>{lvl+1}</b>: <b>{fmt(cost)} VRF</b> из казны"
                if can_upgrade:
                    rows.append([SBtn(f"🛡 Улучшить за {fmt(cost)} VRF", style="success",
                                      callback_data="cl:upgrade_def")])
            rows.append([SBtn("← Назад", style="primary", callback_data="cl:back")])
            await query.answer()
            try:
                await query.edit_message_text(text, parse_mode=ParseMode.HTML,
                                              reply_markup=InlineKeyboardMarkup(rows))
            except TelegramError:
                pass
            return

        if action == "upgrade_def":
            my_clan = await db_get_user_clan(who.id, cid)
            if not my_clan or my_clan["my_role"] not in ("leader", "treasurer"):
                await query.answer("❌ Нет прав", show_alert=True)
                return
            if my_clan["defense_level"] >= CLAN_MAX_DEFENSE_LVL:
                await query.answer("✅ Уже максимальный уровень", show_alert=True)
                return
            cost = CLAN_DEFENSE_BASE_COST * my_clan["defense_level"]
            ok = await db_clan_treasury_sub(my_clan["id"], cost)
            if not ok:
                await query.answer(f"❌ В казне недостаточно средств (нужно {fmt(cost)})", show_alert=True)
                return
            await db_clan_set_defense(my_clan["id"], my_clan["defense_level"] + 1)
            await query.answer(f"🛡 Защита улучшена до уровня {my_clan['defense_level']+1}!")
            text, kb = await _clan_hub_text(who.id, cid)
            try:
                await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
            except TelegramError:
                pass
            return

        # ── Рейд на вражескую казну ────────────────────────
        if action == "raid_list":
            my_clan = await db_get_user_clan(who.id, cid)
            if not my_clan:
                await query.answer("❌ Ты не в клане", show_alert=True)
                return
            last_raid = await db_clan_last_raid(my_clan["id"])
            if last_raid:
                elapsed = (datetime.now() - datetime.fromisoformat(last_raid)).total_seconds()
                left = CLAN_RAID_COOLDOWN_MIN * 60 - elapsed
                if left > 0:
                    await query.answer(f"⏰ Рейд будет доступен через {fmt_cd(int(left))}", show_alert=True)
                    return
            clans = await db_list_clans(cid)
            targets = [c for c in clans if c["id"] != my_clan["id"] and c["treasury"] >= CLAN_RAID_MIN_TREASURY]
            await query.answer()
            if not targets:
                try:
                    await query.edit_message_text(
                        "⚔️ Нет доступных целей для рейда (у остальных кланов слишком мало в казне).",
                        reply_markup=InlineKeyboardMarkup([[SBtn("← Назад", style="primary", callback_data="cl:back")]]),
                    )
                except TelegramError:
                    pass
                return
            try:
                await query.edit_message_text(
                    "⚔️ <b>Выбери цель для рейда</b>",
                    parse_mode=ParseMode.HTML,
                    reply_markup=_clan_kb_raid_targets(targets, my_clan["id"]),
                )
            except TelegramError:
                pass
            return

        if action == "raid":
            target_clan_id = int(parts[2])
            my_clan = await db_get_user_clan(who.id, cid)
            if not my_clan:
                await query.answer("❌ Ты не в клане", show_alert=True)
                return
            target_clan = await db_get_clan(target_clan_id)
            if not target_clan or target_clan["chat_id"] != cid:
                await query.answer("❌ Клан-цель не найден", show_alert=True)
                return
            if target_clan["treasury"] < CLAN_RAID_MIN_TREASURY:
                await query.answer("❌ У цели слишком мало в казне", show_alert=True)
                return

            chance = await calc_raid_chance(my_clan, target_clan)
            success = random.random() < chance
            await db_clan_mark_raid(my_clan["id"])
            await db_log_attack(cid, who.id, "clan", target_clan_id, success, 0)

            if success:
                steal = round(target_clan["treasury"] * CLAN_RAID_STEAL_PCT)
                await db_clan_treasury_sub(target_clan_id, steal)
                await db_clan_treasury_add(my_clan["id"], steal)
                await query.answer("💥 Рейд удался!")
                result_text = (
                    f"⚔️💥 <b>РЕЙД УДАЛСЯ!</b>\n\n"
                    f"Клан <b>{my_clan['name']}</b> атаковал казну клана "
                    f"<b>{target_clan['name']}</b> и захватил <b>{fmt(steal)} VRF</b>!\n"
                    f"(шанс был {int(chance*100)}%)"
                )
            else:
                await query.answer("🛡 Рейд отражён!")
                result_text = (
                    f"⚔️🛡 <b>РЕЙД ОТРАЖЁН!</b>\n\n"
                    f"Клан <b>{my_clan['name']}</b> попытался атаковать казну клана "
                    f"<b>{target_clan['name']}</b>, но защита устояла.\n"
                    f"(шанс был {int(chance*100)}%)"
                )
            try:
                await query.edit_message_text(result_text, parse_mode=ParseMode.HTML)
            except TelegramError:
                pass
            try:
                await context.bot.send_message(cid, result_text, parse_mode=ParseMode.HTML)
            except TelegramError:
                pass
            return

        # ── Покинуть клан ──────────────────────────────────
        if action == "leave":
            my_clan = await db_get_user_clan(who.id, cid)
            if not my_clan:
                await query.answer("❌ Ты не в клане", show_alert=True)
                return
            if my_clan["my_role"] == "leader":
                await query.answer("👑 Лидер не может просто уйти — расформируй клан или передай лидерство", show_alert=True)
                return
            await query.answer()
            try:
                await query.edit_message_text(
                    f"🚪 Точно хочешь покинуть клан <b>{my_clan['name']}</b>?",
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup([[
                        SBtn("✅ Да, покинуть", style="danger", callback_data="cl:leave_confirm"),
                        SBtn("Отмена", style="primary", callback_data="cl:back"),
                    ]]),
                )
            except TelegramError:
                pass
            return

        if action == "leave_confirm":
            my_clan = await db_get_user_clan(who.id, cid)
            if not my_clan:
                await query.answer("❌ Ты уже не в клане", show_alert=True)
                return
            await db_remove_clan_member(who.id, cid)
            await query.answer("🚪 Ты покинул(а) клан")
            try:
                await query.edit_message_text(f"🚪 Ты покинул(а) клан <b>{my_clan['name']}</b>.",
                                              parse_mode=ParseMode.HTML)
            except TelegramError:
                pass
            return

        # ── Расформировать клан (лидер) ───────────────────
        if action == "disband":
            my_clan = await db_get_user_clan(who.id, cid)
            if not my_clan or my_clan["my_role"] != "leader":
                await query.answer("❌ Только лидер может расформировать клан", show_alert=True)
                return
            await query.answer()
            try:
                await query.edit_message_text(
                    f"❌ Точно расформировать клан <b>{my_clan['name']}</b>?\n"
                    f"Казна ({fmt(my_clan['treasury'])} VRF) будет утеряна безвозвратно!",
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup([[
                        SBtn("✅ Да, расформировать", style="danger", callback_data="cl:disband_confirm"),
                        SBtn("Отмена", style="primary", callback_data="cl:back"),
                    ]]),
                )
            except TelegramError:
                pass
            return

        if action == "disband_confirm":
            my_clan = await db_get_user_clan(who.id, cid)
            if not my_clan or my_clan["my_role"] != "leader":
                await query.answer("❌ Нет прав", show_alert=True)
                return
            await db_delete_clan(my_clan["id"], cid)
            await query.answer("Клан расформирован")
            try:
                await query.edit_message_text(f"❌ Клан <b>{my_clan['name']}</b> расформирован.",
                                              parse_mode=ParseMode.HTML)
            except TelegramError:
                pass
            return

        await query.answer()
        return

    await query.answer()
    return


# ══════════════════════════════════════════════════════
#           MESSAGE HANDLER (XP from chat)
# ══════════════════════════════════════════════════════

async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return

    # ── Community events (Bot API 10.2) ───────────────────────
    # community_chat_added / community_chat_removed — сервисные сообщения
    # о том, что этот чат добавили/убрали из сообщества. Поля новые и
    # могут отсутствовать в текущей версии PTB/сервера — читаем безопасно.
    _cca = getattr(update.message, "community_chat_added", None)
    if _cca is not None:
        try:
            await update.message.reply_text(
                "🌐 Этот чат добавлен в сообщество.", parse_mode=ParseMode.HTML,
            )
        except TelegramError:
            pass
    _ccr = getattr(update.message, "community_chat_removed", None)
    if _ccr is not None:
        try:
            await update.message.reply_text("🌐 Этот чат исключён из сообщества.")
        except TelegramError:
            pass

    u    = update.effective_user
    text = (update.message.text or "").strip()

    # ── Managed bot settings editor (private chat) ────────────
    if update.effective_chat.type == "private" and text and not u.is_bot:
        ud = context.user_data

        # Edit welcome text
        if "mb_edit_welcome" in ud:
            bot_uid = ud.pop("mb_edit_welcome")
            await _mb_update_settings(bot_uid, welcome_text=text)
            await update.message.reply_text(
                "✅ Приветствие обновлено!\n\n"
                f"Теперь при /start пользователи увидят:\n<i>{text[:200]}</i>",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("← Назад к управлению",
                                         callback_data=f"mb:manage:{bot_uid}")
                ]]),
            )
            return

        # Edit description
        if "mb_edit_desc" in ud:
            bot_uid = ud.pop("mb_edit_desc")
            await _mb_update_settings(bot_uid, description=text)
            # Try to actually update bot's description via API
            settings = await _mb_get_settings(bot_uid)
            if settings:
                try:
                    from telegram import Bot as _Bot
                    tmp = _Bot(token=settings["bot_token"])
                    await tmp.set_my_description(text + "\n\n🤖 @VerifureGameBot")
                    await tmp.close()
                except Exception as exc:
                    log.warning("set_my_description failed: %s", exc)
            await update.message.reply_text(
                "✅ Описание обновлено!",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("← Назад к управлению",
                                         callback_data=f"mb:manage:{bot_uid}")
                ]]),
            )
            return

        # Edit token
        if "mb_edit_token" in ud:
            bot_uid = ud.pop("mb_edit_token")
            new_token = text.strip()
            if ":" not in new_token or len(new_token) < 20:
                await update.message.reply_text("❌ Неверный формат токена.")
                return
            # Validate token
            try:
                import aiohttp as _aio
                async with _aio.ClientSession() as s:
                    async with s.get(
                        f"https://api.telegram.org/bot{new_token}/getMe",
                        timeout=_aio.ClientTimeout(total=10)
                    ) as r:
                        d = await r.json()
            except Exception:
                await update.message.reply_text("❌ Не удалось проверить токен.")
                return
            if not d.get("ok"):
                await update.message.reply_text(
                    f"❌ Токен не принят: {d.get('description')}"
                )
                return
            # Delete token message for security
            try:
                await update.message.delete()
            except TelegramError:
                pass
            # Update DB and restart
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    "UPDATE managed_bots SET bot_token=? WHERE bot_user_id=?",
                    (new_token, bot_uid)
                )
                await db.commit()
            # Respawn
            _spawn_child(new_token, bot_uid, owner_id=u.id)
            bot_info = d["result"]
            uname = bot_info.get("username", "")
            name  = f"@{uname}" if uname else f"ID {bot_uid}"
            await update.effective_chat.send_message(
                f"✅ Токен обновлён, бот {name} перезапускается...",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("← Управление", callback_data=f"mb:manage:{bot_uid}")
                ]]),
            )
            return

    if update.effective_chat.type == "private":
        return

    cid  = update.effective_chat.id
    text = (update.message.text or "").strip()
    low  = text.lower()
    pts  = low.split()
    word = pts[0] if pts else ""
    pend_key = (cid, u.id)   # ← используется и Tower, и Crash секциями ниже

    await db_ensure_user(u.id, cid, u.username or "", u.first_name)
    await db_touch_active(u.id, cid)

    # ── Tower: custom bet reply ─────────────────────────────
    pend_tw = tower_custom_pending.get(pend_key)
    if pend_tw:
        if datetime.now() > pend_tw["expires"]:
            tower_custom_pending.pop(pend_key, None)
        else:
            digits = text.replace(" ", "")
            if digits.isdigit():
                tower_custom_pending.pop(pend_key, None)
                tw_amount = int(digits)
                if tw_amount < TOWER_MIN_BET:
                    await update.message.reply_text(
                        f"❌ Минимальная ставка {TOWER_MIN_BET} VRF")
                    return
                game = tower_games.get(cid)
                if not game or game["state"] != "joining":
                    await update.message.reply_text("❌ Набор уже закрыт!")
                    return
                if u.id in game["players"]:
                    await update.message.reply_text("Ты уже в игре!")
                    return
                uu2 = await db_get_user(u.id, cid)
                if not uu2 or uu2["vrf"] < tw_amount:
                    await update.message.reply_text(
                        f"❌ Недостаточно VRF! Есть: {fmt(uu2['vrf'] if uu2 else 0)}")
                    return
                ok = await db_deduct_vrf(u.id, cid, tw_amount)
                if not ok:
                    await update.message.reply_text("❌ Недостаточно VRF!")
                    return
                game["players"][u.id] = {
                    "name": u.first_name, "bet": tw_amount,
                    "alive": True, "cashed": False,
                    "cash_floor": 0, "cash_mult": 1.0, "payout": 0,
                }
                await update.message.reply_text(f"✅ Ставка {tw_amount} VRF принята!")
                return
            else:
                await update.message.reply_text("❌ Введи число. Попробуй ещё раз:")
                return

    # ── Crash: custom bet amount reply ─────────────────────
    if pend_key in crash_custom_pending:
        pend = crash_custom_pending[pend_key]
        if datetime.now() > pend["expires"]:
            crash_custom_pending.pop(pend_key, None)
        else:
            digits = text.replace(" ", "")
            if digits.isdigit():
                crash_custom_pending.pop(pend_key, None)
                amount  = int(digits)
                ok, msg = await _crash_join_player(context, cid, u, amount)
                await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
                return
            else:
                await update.message.reply_text(
                    f"❌ Нужно целое число от {MIN_BET} VRF. Попробуй ещё раз:",
                )
                return

    # ── Clan: name reply after "cl:create" ──────────────────
    if pend_key in clan_pending_input:
        pend = clan_pending_input[pend_key]
        if datetime.now() > pend["expires"]:
            clan_pending_input.pop(pend_key, None)
        else:
            clan_pending_input.pop(pend_key, None)
            name = text.strip()
            if not (CLAN_NAME_MIN <= len(name) <= CLAN_NAME_MAX):
                await update.message.reply_text(
                    f"❌ Название должно быть от {CLAN_NAME_MIN} до {CLAN_NAME_MAX} символов. "
                    f"Попробуй снова: напиши «клан» → «➕ Создать клан»."
                )
                return
            if await db_get_user_clan(u.id, cid):
                await update.message.reply_text("❌ Ты уже состоишь в клане!")
                return
            if await db_get_clan_by_name(cid, name):
                await update.message.reply_text("❌ Клан с таким названием уже есть в этом чате.")
                return
            uu = await db_get_user(u.id, cid)
            if not uu or uu["vrf"] < CLAN_CREATE_COST:
                await update.message.reply_text(
                    f"❌ Нужно {fmt(CLAN_CREATE_COST)} VRF, у тебя {fmt(uu['vrf'] if uu else 0)}"
                )
                return
            await db_deduct_vrf(u.id, cid, CLAN_CREATE_COST)
            clan_id = await db_create_clan(cid, name, u.id)
            if not clan_id:
                await db_add_vrf(u.id, cid, CLAN_CREATE_COST)  # откат списания
                await update.message.reply_text("❌ Не удалось создать клан, попробуй другое название.")
                return
            await update.message.reply_text(
                f"🏰 <b>Клан «{name}» создан!</b>\n\n"
                f"Ты — 👑 лидер. Приглашай участников, собирайте казну "
                f"командой <code>казна +500</code>, защищайтесь и атакуйте другие кланы!",
                parse_mode=ParseMode.HTML,
            )
            return

    # ── Text shortcuts ────────────────────────────────────
    # б / баланс → короткий приватный баланс (эфемерно, как /profile)
    if word in ("б", "баланс", "balance", "bal"):
        uu = await db_get_user(u.id, cid)
        bal = uu["vrf"] if uu else 0
        lvl = get_level(uu["experience"]) if uu else 1
        short_bal = f"💎 <b>{fmt(bal)} VRF</b>  |  🏅 Ур. {lvl}"
        result = await send_ephemeral_or_normal(
            context.bot, cid, u.id, short_bal, reply_to_id=update.message.message_id,
        )
        if isinstance(result, dict) and result.get("ephemeral_message_id"):
            try:
                await update.message.react([ReactionTypeEmoji(emoji="👀")])
            except TelegramError:
                pass
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

    # брак → карточка брака / статус (reuse cmd_marriage)
    if word in ("брак", "свадьба", "marriage"):
        context.args = []
        await cmd_marriage(update, context)
        return

    # дуэль → вызов на дуэль (обязательно ответом на сообщение соперника,
    # так же, как у команды /duel — cmd_duel сама проверит и подскажет,
    # если реплея нет)
    if word in ("дуэль", "duel", "дуэл"):
        context.args = []
        await cmd_duel(update, context)
        return

    # помощь → /help
    if word in ("помощь", "help", "хелп", "справка"):
        context.args = []
        await cmd_help(update, context)
        return

    # мины → /mines (соло-игра, реплей не нужен)
    if word in ("мины", "мина", "mines"):
        context.args = []
        await cmd_mines(update, context)
        return

    # клан → клановый хаб (создать/вступить/инфо о своём клане)
    if word in ("клан", "clan", "кланы"):
        context.args = []
        await cmd_clan(update, context)
        return

    # казна +N / казна -N / просто "казна" → баланс казны
    if word in ("казна", "treasury"):
        await handle_treasury_trigger(update, context, pts)
        return

    # атака → попытка украсть баланс у офлайн-цели (ответом на её сообщение)
    if word in ("атака", "attack", "грабёж", "ограбить"):
        await handle_attack_trigger(update, context)
        return

    # рейд → список кланов для атаки на чужую казну
    if word in ("рейд", "raid"):
        clan = await db_get_user_clan(u.id, cid)
        if not clan:
            await update.message.reply_text("❌ Ты не состоишь в клане.")
            return
        last_raid = await db_clan_last_raid(clan["id"])
        if last_raid:
            elapsed = (datetime.now() - datetime.fromisoformat(last_raid)).total_seconds()
            left = CLAN_RAID_COOLDOWN_MIN * 60 - elapsed
            if left > 0:
                await update.message.reply_text(f"⏰ Рейд будет доступен через {fmt_cd(int(left))}")
                return
        clans = await db_list_clans(cid)
        targets = [c for c in clans if c["id"] != clan["id"] and c["treasury"] >= CLAN_RAID_MIN_TREASURY]
        if not targets:
            await update.message.reply_text(
                "⚔️ Нет доступных целей для рейда (у остальных кланов слишком мало в казне)."
            )
            return
        await update.message.reply_text(
            "⚔️ <b>Выбери цель для рейда</b>", parse_mode=ParseMode.HTML,
            reply_markup=_clan_kb_raid_targets(targets, clan["id"]),
        )
        return

    # ферма / фарм → сбор ресурсов (часть уходит в казну клана)
    if word in ("ферма", "фарм", "farm"):
        await handle_farm_trigger(update, context)
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
            await db_deduct_vrf(u.id, cid, bet)
            after_u = await db_get_user(u.id, cid)
            new_bal = after_u["vrf"] if after_u else (uu["vrf"] - bet)
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
#           КЛАНЫ И АТАКИ  🏰⚔️
# ══════════════════════════════════════════════════════
# Полная механика: создание клана, заявки на вступление с одобрением
# лидером, самостоятельный выбор роли участником, общая казна (текстовый
# триггер "казна +N"/"казна -N"), апгрейд защиты казны, рейды на казну
# вражеского клана, кража баланса у офлайн-игроков, ферма ресурсов.
# Всё чувствительное (казна, роли, заявки) — эфемерно, если бот админ чата.

clan_pending_input: dict = {}   # key: (cid, uid) -> {"kind": "clan_name", "expires": datetime}


# ── Расчёт шансов ──────────────────────────────────────

async def _clan_role_count(clan_id: int, role: str) -> int:
    members = await db_get_clan_members(clan_id)
    return sum(1 for m in members if m["role"] == role)


async def calc_attack_chance(attacker: dict, attacker_clan: Optional[dict],
                             target_clan: Optional[dict]) -> float:
    chance = ATTACK_BASE_CHANCE
    if attacker_clan and attacker_clan.get("my_role") == "raider":
        chance += ATTACK_ROLE_BONUS
    if target_clan:
        chance -= target_clan["defense_level"] * ATTACK_DEFENSE_PENALTY_PER_LVL
        n_def = await _clan_role_count(target_clan["id"], "defender")
        chance -= n_def * 0.04
    return max(0.05, min(0.9, chance))


async def calc_raid_chance(attacker_clan: dict, target_clan: dict) -> float:
    n_raid = await _clan_role_count(attacker_clan["id"], "raider")
    n_def  = await _clan_role_count(target_clan["id"], "defender")
    chance = CLAN_RAID_BASE_CHANCE + n_raid * (ATTACK_ROLE_BONUS * 0.5)
    chance -= target_clan["defense_level"] * ATTACK_DEFENSE_PENALTY_PER_LVL
    chance -= n_def * 0.04
    return max(0.05, min(0.85, chance))


def _clan_kb_hub(has_clan: bool, is_leader: bool, has_apps: bool) -> InlineKeyboardMarkup:
    if not has_clan:
        return InlineKeyboardMarkup([
            [SBtn("➕ Создать клан", style="success", callback_data="cl:create")],
            [SBtn("📋 Список кланов", style="primary", callback_data="cl:browse")],
        ])
    rows = [
        [SBtn("👥 Участники", style="primary", callback_data="cl:members"),
         SBtn("🎭 Моя роль", style="primary", callback_data="cl:roles")],
        [SBtn("💰 Казна", style="primary", callback_data="cl:treasury"),
         SBtn("🛡 Защита", style="primary", callback_data="cl:defense")],
        [SBtn("⚔️ Рейд на клан", style="danger", callback_data="cl:raid_list")],
    ]
    if is_leader:
        app_label = "📨 Заявки 🔴" if has_apps else "📨 Заявки"
        rows.append([SBtn(app_label, style="primary", callback_data="cl:apps"),
                    SBtn("❌ Расформировать", style="danger", callback_data="cl:disband")])
    else:
        rows.append([SBtn("🚪 Покинуть клан", style="danger", callback_data="cl:leave")])
    return InlineKeyboardMarkup(rows)


async def _clan_hub_text(uid: int, cid: int) -> Tuple[str, InlineKeyboardMarkup]:
    clan = await db_get_user_clan(uid, cid)
    if not clan:
        text = (
            "🏰 <b>Кланы</b>\n\n"
            "Ты пока не состоишь ни в одном клане.\n\n"
            f"➕ Создать свой — <b>{fmt(CLAN_CREATE_COST)} VRF</b>\n"
            f"📋 Или вступи в существующий"
        )
        return text, _clan_kb_hub(False, False, False)

    role = CLAN_ROLES.get(clan["my_role"], CLAN_ROLES["member"])
    is_leader = clan["my_role"] == "leader"
    apps = await db_get_clan_applications(clan["id"]) if is_leader else []
    members = await db_get_clan_members(clan["id"])

    text = (
        f"🏰 <b>{clan['name']}</b>\n\n"
        f"👑 Лидер: {mention(clan['leader_id'], '')}\n"
        f"💰 Казна: <b>{fmt(clan['treasury'])} VRF</b>\n"
        f"🛡 Защита: уровень <b>{clan['defense_level']}</b>/{CLAN_MAX_DEFENSE_LVL}\n"
        f"👥 Участников: <b>{len(members)}</b>\n"
        f"🎭 Твоя роль: {role['emoji']} <b>{role['label']}</b>\n"
    )
    if is_leader and apps:
        text += f"\n📨 Заявок на вступление: <b>{len(apps)}</b>"
    return text, _clan_kb_hub(True, is_leader, bool(apps))


async def cmd_clan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    u, cid = update.effective_user, update.effective_chat.id
    await db_ensure_user(u.id, cid, u.username or "", u.first_name)
    text, kb = await _clan_hub_text(u.id, cid)
    result = await send_ephemeral_or_normal(
        context.bot, cid, u.id, text, reply_markup=kb,
        reply_to_id=update.message.message_id,
    )
    if isinstance(result, dict) and result.get("ephemeral_message_id"):
        try:
            await update.message.react([ReactionTypeEmoji(emoji="🏰")])
        except TelegramError:
            pass


# ── Текстовые триггеры: казна / атака / рейд / ферма ───

async def handle_treasury_trigger(update: Update, context: ContextTypes.DEFAULT_TYPE, pts: list) -> None:
    u, cid = update.effective_user, update.effective_chat.id
    clan = await db_get_user_clan(u.id, cid)
    if not clan:
        await update.message.reply_text("❌ Ты не состоишь в клане. Напиши «клан», чтобы вступить или создать свой.")
        return

    if len(pts) < 2:
        # просто "казна" — показать баланс приватно
        result = await send_ephemeral_or_normal(
            context.bot, cid, u.id,
            f"💰 Казна клана <b>{clan['name']}</b>: <b>{fmt(clan['treasury'])} VRF</b>",
            reply_to_id=update.message.message_id,
        )
        return

    raw = pts[1].replace(" ", "")
    sign = 1
    if raw.startswith("+"):
        raw = raw[1:]
    elif raw.startswith("-"):
        sign = -1
        raw = raw[1:]
    try:
        amount = float(raw.replace(",", "."))
    except ValueError:
        await update.message.reply_text("❌ Формат: <code>казна +500</code> или <code>казна -200</code>",
                                        parse_mode=ParseMode.HTML)
        return
    if amount <= 0:
        await update.message.reply_text("❌ Сумма должна быть больше 0")
        return

    if sign > 0:
        uu = await db_get_user(u.id, cid)
        if not uu or uu["vrf"] < amount:
            await update.message.reply_text(f"❌ Недостаточно VRF! Есть: {fmt(uu['vrf'] if uu else 0)}")
            return
        await db_deduct_vrf(u.id, cid, int(amount))
        new_treasury = await db_clan_treasury_add(clan["id"], amount)
        await update.message.reply_text(
            f"💰 {mention(u.id, u.first_name)} пополнил(а) казну клана <b>{clan['name']}</b> "
            f"на <b>{fmt(amount)} VRF</b>!\nВ казне: <b>{fmt(new_treasury)} VRF</b>",
            parse_mode=ParseMode.HTML,
        )
    else:
        if clan["my_role"] not in ("leader", "treasurer"):
            await update.message.reply_text(
                "❌ Выводить из казны может только 💰 Казначей или 👑 Лидер клана."
            )
            return
        ok = await db_clan_treasury_sub(clan["id"], amount)
        if not ok:
            await update.message.reply_text(f"❌ В казне недостаточно средств (там {fmt(clan['treasury'])} VRF)")
            return
        await db_add_vrf(u.id, cid, int(amount))
        await update.message.reply_text(
            f"💸 {mention(u.id, u.first_name)} вывел(а) из казны клана <b>{clan['name']}</b> "
            f"<b>{fmt(amount)} VRF</b> себе на баланс.",
            parse_mode=ParseMode.HTML,
        )


async def handle_attack_trigger(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    attacker = update.effective_user
    cid = update.effective_chat.id

    if not update.message.reply_to_message or update.message.reply_to_message.from_user.is_bot:
        await update.message.reply_text(
            "❌ Ответь командой «атака» на сообщение того, кого хочешь ограбить."
        )
        return
    target_u = update.message.reply_to_message.from_user
    if target_u.id == attacker.id:
        await update.message.reply_text("❌ Нельзя атаковать самого себя!")
        return

    await db_ensure_user(attacker.id, cid, attacker.username or "", attacker.first_name)
    await db_ensure_user(target_u.id, cid, target_u.username or "", target_u.first_name)

    au = await db_get_user(attacker.id, cid)
    cd_left = attack_cooldown_left(au, ATTACK_COOLDOWN_MIN)
    if cd_left > 0:
        await update.message.reply_text(f"⏰ Следующая атака через {fmt_cd(cd_left)}")
        return

    tu = await db_get_user(target_u.id, cid)
    if not tu:
        await update.message.reply_text("❌ Цель ещё не известна боту")
        return
    if not user_is_offline(tu):
        await update.message.reply_text(
            f"❌ {mention(target_u.id, target_u.first_name)} сейчас активен(на) — "
            f"грабить можно только тех, кто молчит хотя бы {ATTACK_OFFLINE_MIN} мин.",
            parse_mode=ParseMode.HTML,
        )
        return
    if tu["vrf"] < ATTACK_MIN_TARGET_VRF:
        await update.message.reply_text(
            f"❌ У цели слишком мало VRF (нужно хотя бы {ATTACK_MIN_TARGET_VRF})."
        )
        return

    attacker_clan = await db_get_user_clan(attacker.id, cid)
    target_clan   = await db_get_user_clan(target_u.id, cid)
    chance = await calc_attack_chance(au, attacker_clan, target_clan)
    success = random.random() < chance

    if success:
        steal = round(tu["vrf"] * ATTACK_STEAL_PCT)
        await db_deduct_vrf(target_u.id, cid, steal)
        await db_add_vrf(attacker.id, cid, steal)
        await db_log_attack(cid, attacker.id, "user", target_u.id, True, steal)
        await update.message.reply_text(
            f"💰 <b>Атака удалась!</b>\n\n"
            f"{mention(attacker.id, attacker.first_name)} застал(а) "
            f"{mention(target_u.id, target_u.first_name)} врасплох и украл(а) "
            f"<b>{fmt(steal)} VRF</b>! (шанс был {int(chance*100)}%)",
            parse_mode=ParseMode.HTML,
        )
    else:
        await db_log_attack(cid, attacker.id, "user", target_u.id, False, 0)
        await update.message.reply_text(
            f"🛡 <b>Атака провалилась!</b>\n\n"
            f"{mention(attacker.id, attacker.first_name)} попытался(ась) ограбить "
            f"{mention(target_u.id, target_u.first_name)}, но не вышло. (шанс был {int(chance*100)}%)",
            parse_mode=ParseMode.HTML,
        )


async def handle_farm_trigger(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    u, cid = update.effective_user, update.effective_chat.id
    await db_ensure_user(u.id, cid, u.username or "", u.first_name)
    uu = await db_get_user(u.id, cid)
    left = farm_cooldown_left(uu)
    if left > 0:
        await update.message.reply_text(f"🌾 Ферма ещё не готова — подожди {fmt_cd(left)}")
        return

    total = random.randint(FARM_BASE_MIN, FARM_BASE_MAX)
    clan = await db_get_user_clan(u.id, cid)
    clan_cut = 0
    if clan:
        clan_cut = round(total * FARM_CLAN_SHARE)
        await db_clan_treasury_add(clan["id"], clan_cut)
    personal = total - clan_cut
    await db_add_vrf(u.id, cid, personal)
    await db_touch_farm(u.id, cid)

    text = f"🌾 <b>Ферма собрана!</b>\n\n💎 Тебе: <b>+{fmt(personal)} VRF</b>"
    if clan:
        text += f"\n🏰 В казну клана «{clan['name']}»: <b>+{fmt(clan_cut)} VRF</b>"
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


def _clan_kb_raid_targets(clans: list, my_clan_id: int) -> InlineKeyboardMarkup:
    rows = []
    for c in clans:
        if c["id"] == my_clan_id:
            continue
        rows.append([SBtn(f"⚔️ {c['name']} · 💰{fmt(c['treasury'])} · 🛡{c['defense_level']}",
                          style="danger", callback_data=f"cl:raid:{c['id']}")])
    if not rows:
        rows.append([SBtn("Нет доступных целей", style="primary", callback_data="cl:noop")])
    rows.append([SBtn("Отмена", style="primary", callback_data="cl:cancel_msg")])
    return InlineKeyboardMarkup(rows)


async def on_startup(app: Application) -> None:
    await db_init()
    from telegram import BotCommand, BotCommandScopeAllGroupChats, BotCommandScopeDefault
    cmds = [
        BotCommand("start",    "🏠 Старт / Главное меню"),
        BotCommand("profile",  "👤 Мой профиль"),
        BotCommand("statsimg", "📈 График активности чата [дней]"),
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
        BotCommand("crash",    "🚀 Краш — весь чат, лови множитель!"),
        BotCommand("giveaway", "🎁 Розыгрыш медведей среди реакций"),
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

    # ── is_ephemeral (Bot API 10.2) — попытка пометить /admin как эфемерную
    # команду, чтобы сама подсказка команды в меню тоже была приватной.
    # BotCommand в установленной версии PTB может не знать про этот kwarg —
    # тогда просто соберём сырой dict и пошлём через do_api_request.
    try:
        ephemeral_cmds = [
            {"command": c.command, "description": c.description,
             **({"is_ephemeral": True} if c.command == "admin" else {})}
            for c in cmds
        ]
        await app.bot.do_api_request(
            "setMyCommands",
            api_kwargs={"commands": ephemeral_cmds, "scope": {"type": "all_group_chats"}},
        )
    except Exception as e:
        log.debug("is_ephemeral BotCommand not supported yet: %s", e)

    log.info("Verifure Game 10.1 is online!")



# ══════════════════════════════════════════════════════
#   TELEGRAM MINI APP — VRF Кликер (встроенный HTML)
# ══════════════════════════════════════════════════════
# Файл раздаётся прямо из бота по адресу /clicker.
# Установи переменную окружения WEBAPP_URL = https://your-app.up.railway.app
# и в Railway Settings → Networking включи порт 8080 (Public Networking).

_CLICKER_HTML = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>VRF Кликер</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
*{box-sizing:border-box;margin:0;padding:0;-webkit-tap-highlight-color:transparent}
body{min-height:100vh;background:#0b0e14;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;
  display:flex;flex-direction:column;align-items:center;justify-content:space-between;
  padding:16px 16px 24px;color:#fff;background-image:radial-gradient(circle at 25% 20%,#111b2e 0%,#0b0e14 70%)}
.stars{position:fixed;top:0;left:0;width:100%;height:100%;pointer-events:none;z-index:0}
.star{position:absolute;border-radius:50%;background:#fff;animation:twinkle var(--d,3s) ease-in-out infinite var(--delay,0s)}
@keyframes twinkle{0%,100%{opacity:var(--lo,.1)}50%{opacity:var(--hi,.9)}}
.content{position:relative;z-index:1;width:100%;max-width:400px;display:flex;flex-direction:column;align-items:center;gap:18px}
.user-bar{display:flex;align-items:center;gap:8px;background:rgba(255,255,255,0.05);
  border:1px solid rgba(255,255,255,0.08);border-radius:99px;padding:4px 14px 4px 4px;align-self:center}
.avatar{width:32px;height:32px;border-radius:50%;background:linear-gradient(135deg,#3b82f6,#8b5cf6);
  display:flex;align-items:center;justify-content:center;font-size:14px;font-weight:600;color:#fff;flex-shrink:0}
.user-name{font-size:13px;font-weight:500;color:rgba(255,255,255,0.8)}
.balance-card{background:rgba(0,0,0,0.35);border:1px solid rgba(255,215,0,0.15);
  border-radius:16px;padding:18px 24px;text-align:center;width:100%}
.bal-label{font-size:11px;color:rgba(255,255,255,0.35);text-transform:uppercase;letter-spacing:2px;margin-bottom:4px}
.bal-num{font-size:58px;font-weight:700;color:#ffd966;line-height:1;text-shadow:0 0 30px rgba(255,215,0,.15)}
.bal-sub{font-size:12px;color:rgba(255,255,255,0.3);margin-top:4px}
.coin-area{display:flex;flex-direction:column;align-items:center;gap:10px}
.coin{width:148px;height:148px;border-radius:50%;cursor:pointer;user-select:none;position:relative;
  background:conic-gradient(from 180deg,#ffd966,#f4b400,#e6a000,#ffd966);
  border:3px solid rgba(255,220,80,.3);transition:transform .08s;display:flex;align-items:center;justify-content:center}
.coin:active{transform:scale(.91)}
.coin-ring{position:absolute;inset:-5px;border-radius:50%;border:2px solid rgba(255,200,30,.2);animation:pulse 2.5s ease-in-out infinite}
@keyframes pulse{0%,100%{opacity:.6;transform:scale(1)}50%{opacity:.2;transform:scale(1.06)}}
.coin-text{font-size:38px;font-weight:800;color:rgba(100,55,0,.8);text-shadow:0 2px 4px rgba(255,255,255,.3)}
.tap-hint{font-size:12px;color:rgba(255,255,255,.3);letter-spacing:.5px}
.stats-grid{display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;width:100%}
.stat{background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.07);
  border-radius:10px;padding:8px 4px;text-align:center}
.stat-v{font-size:17px;font-weight:600;color:#fff}
.stat-l{font-size:10px;color:rgba(255,255,255,.35);text-transform:uppercase;letter-spacing:.8px;margin-top:1px}
.prog-wrap{width:100%}
.prog-row{display:flex;justify-content:space-between;font-size:11px;color:rgba(255,255,255,.3);margin-bottom:5px}
.prog-bar{height:5px;background:rgba(255,255,255,.07);border-radius:99px;overflow:hidden}
.prog-fill{height:100%;background:linear-gradient(90deg,#3b82f6,#8b5cf6);border-radius:99px;transition:width .4s ease}
.limit-row{font-size:11px;color:rgba(255,255,255,.3);text-align:center;width:100%}
.fly{position:fixed;pointer-events:none;z-index:9999;font-size:20px;font-weight:700;
  color:#ffd966;text-shadow:0 0 10px rgba(255,215,0,.4);animation:fup .9s ease-out forwards}
@keyframes fup{0%{opacity:1;transform:translateY(0)}100%{opacity:0;transform:translateY(-70px) scale(.5)}}
</style>
</head>
<body>
<div class="stars" id="stars"></div>
<div class="content">
  <div class="user-bar">
    <div class="avatar" id="av">?</div>
    <div class="user-name" id="uname">Загрузка...</div>
  </div>
  <div class="balance-card">
    <div class="bal-label">Накоплено</div>
    <div class="bal-num" id="bal">0</div>
    <div class="bal-sub">VRF монет</div>
  </div>
  <div class="coin-area">
    <div class="coin" id="coin" role="button" aria-label="Нажми для накопления VRF">
      <div class="coin-ring"></div>
      <div class="coin-text">VRF</div>
    </div>
    <div class="tap-hint">Нажимай для накопления</div>
  </div>
  <div class="stats-grid">
    <div class="stat"><div class="stat-v" id="s-clicks">0</div><div class="stat-l">Кликов</div></div>
    <div class="stat"><div class="stat-v" id="s-rate">0.5</div><div class="stat-l">За клик</div></div>
    <div class="stat"><div class="stat-v" id="s-sent">0</div><div class="stat-l">Отправлено</div></div>
  </div>
  <div class="prog-wrap">
    <div class="prog-row"><span>Бонус за 50 кликов</span><span id="prog-t">0/50</span></div>
    <div class="prog-bar"><div class="prog-fill" id="prog-f" style="width:0"></div></div>
  </div>
  <div class="limit-row" id="limit-row"></div>
</div>

<script>
const tg = window.Telegram.WebApp;
tg.ready();
tg.expand();

// ── Stars ──
const sc = document.getElementById('stars');
for (let i=0;i<55;i++){
  const s=document.createElement('div');
  s.className='star';
  const sz=Math.random()*1.8+.4;
  s.style.cssText=`width:${sz}px;height:${sz}px;left:${Math.random()*100}%;top:${Math.random()*100}%;
    --d:${2+Math.random()*4}s;--delay:${Math.random()*5}s;--lo:${.05+Math.random()*.1};--hi:${.5+Math.random()*.5}`;
  sc.appendChild(s);
}

// ── User ──
const u = tg.initDataUnsafe?.user;
if(u){
  document.getElementById('uname').textContent = u.first_name || u.username || 'Игрок';
  document.getElementById('av').textContent = (u.first_name||'?')[0].toUpperCase();
}

// ── State (localStorage persists between Telegram WebView sessions) ──
const SK = 'vrf_clicker_v4';
const DAILY_MAX = 500;
let S = {balance:0, clicks:0, perClick:0.5, totalSent:0, sentToday:0, lastSentDate:''};
try{
  const raw = localStorage.getItem(SK);
  if(raw) S = {...S, ...JSON.parse(raw)};
  const today = new Date().toDateString();
  if(S.lastSentDate !== today) S.sentToday = 0;
}catch(e){}

function save(){ try{localStorage.setItem(SK,JSON.stringify(S))}catch(e){} }

function render(){
  document.getElementById('bal').textContent = Math.floor(S.balance);
  document.getElementById('s-clicks').textContent = S.clicks;
  document.getElementById('s-rate').textContent = S.perClick.toFixed(1);
  document.getElementById('s-sent').textContent = S.totalSent;
  const prog = (S.clicks % 50)/50;
  document.getElementById('prog-f').style.width = (prog*100)+'%';
  document.getElementById('prog-t').textContent = (S.clicks%50)+'/50';
  const remain = Math.max(0, DAILY_MAX - S.sentToday);
  document.getElementById('limit-row').textContent = remain > 0
    ? `Доступно к отправке сегодня: ${remain} VRF`
    : 'Суточный лимит исчерпан. Возвращайся завтра!';
  updateMainBtn();
}

function updateMainBtn(){
  const can = Math.min(Math.floor(S.balance), Math.max(0, DAILY_MAX - S.sentToday));
  if(can >= 1){
    tg.MainButton.setText('Отправить '+can+' VRF в бот');
    tg.MainButton.color = '#22c55e';
    tg.MainButton.show();
  } else if(Math.floor(S.balance) < 1) {
    tg.MainButton.setText('Кликай чтобы накопить');
    tg.MainButton.color = '#374151';
    tg.MainButton.show();
  } else {
    tg.MainButton.setText('Лимит 500 VRF/сутки исчерпан');
    tg.MainButton.color = '#374151';
    tg.MainButton.show();
  }
}

// ── Click ──
document.getElementById('coin').addEventListener('click', function(e){
  if(navigator.vibrate) navigator.vibrate(12);
  S.balance = Math.round((S.balance + S.perClick)*100)/100;
  S.clicks++;
  if(S.clicks % 50 === 0) S.perClick = Math.round((S.perClick+.1)*10)/10;
  render(); save();
  const fly = document.createElement('div');
  fly.className = 'fly';
  fly.textContent = S.clicks%50===0 ? 'БОНУС x'+S.perClick.toFixed(1)+'!' : '+'+S.perClick.toFixed(1);
  fly.style.left=(e.clientX-25)+'px'; fly.style.top=(e.clientY-25)+'px';
  document.body.appendChild(fly);
  setTimeout(()=>fly.remove(),950);
});

// ── Send to bot ──
tg.MainButton.onClick(function(){
  const can = Math.min(Math.floor(S.balance), Math.max(0, DAILY_MAX - S.sentToday));
  if(can < 1){ tg.showAlert('Накопи хотя бы 1 VRF или подожди до завтра'); return; }
  tg.showConfirm('Отправить '+can+' VRF в бот?', function(ok){
    if(!ok) return;
    S.balance = Math.round((S.balance - can)*100)/100;
    S.sentToday += can;
    S.totalSent += can;
    S.lastSentDate = new Date().toDateString();
    save();
    tg.sendData(JSON.stringify({action:'clicker',amount:can}));
  });
});

render();
</script>
</body>
</html>"""


def _run_clicker_webserver() -> None:
    """
    Запускает лёгкий aiohttp-сервер в фоновом потоке.
    Railway автоматически привязывает домен если включить Public Networking → Port 8080.
    Переменные окружения: PORT (Railway задаёт автоматически), WEBAPP_URL.
    """
    import asyncio as _asyncio

    async def _serve() -> None:
        try:
            from aiohttp import web as _web
        except ImportError:
            log.warning("aiohttp not installed — Mini App web server disabled. pip install aiohttp")
            return

        async def clicker_page(request: _web.Request) -> _web.Response:
            return _web.Response(text=_CLICKER_HTML, content_type="text/html",
                                 charset="utf-8")

        async def health(request: _web.Request) -> _web.Response:
            return _web.Response(text="ok")

        web_app = _web.Application()
        web_app.router.add_get("/clicker", clicker_page)
        web_app.router.add_get("/", health)

        runner = _web.AppRunner(web_app)
        await runner.setup()
        port = int(os.getenv("PORT", "8080"))
        site = _web.TCPSite(runner, "0.0.0.0", port)
        await site.start()
        log.info("Mini App web server started on port %s  →  %s/clicker", port, WEBAPP_URL or f"http://localhost:{port}")
        await _asyncio.Event().wait()   # run forever

    _asyncio.run(_serve())


async def on_web_app_data(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle VRF clicker data sent from the Telegram Mini App via sendData()."""
    msg = update.message
    if not msg or not msg.web_app_data:
        return

    user = update.effective_user
    cid  = update.effective_chat.id
    raw  = msg.web_app_data.data

    try:
        import json as _json
        data = _json.loads(raw)
    except Exception:
        return

    if data.get("action") != "clicker":
        return

    amount = int(data.get("amount", 0))
    if amount <= 0:
        return

    CLICKER_DAILY_MAX = 500
    if amount > CLICKER_DAILY_MAX:
        amount = CLICKER_DAILY_MAX

    await db_ensure_user(user.id, cid, user.username or "", user.first_name)

    # Check daily limit
    async with aiosqlite.connect(DB_PATH) as db:
        for col in ["last_clicker_claim TEXT DEFAULT NULL",
                    "clicker_claimed_today INTEGER DEFAULT 0"]:
            try:
                await db.execute(f"ALTER TABLE users ADD COLUMN {col}")
            except Exception:
                pass
        await db.commit()

        async with db.execute(
            "SELECT last_clicker_claim, clicker_claimed_today FROM users "
            "WHERE user_id=? AND chat_id=?", (user.id, cid)
        ) as cur:
            row = await cur.fetchone()

    last_claim, claimed_today = (row or (None, 0))
    claimed_today = claimed_today or 0

    if last_claim:
        try:
            last_dt = datetime.fromisoformat(last_claim)
            if datetime.now() - last_dt < timedelta(hours=24):
                available = max(0, CLICKER_DAILY_MAX - claimed_today)
                if available <= 0:
                    await msg.reply_text(
                        "⏰ <b>Суточный лимит кликера исчерпан!</b>\n"
                        "Возвращайся через 24 часа.",
                        parse_mode=ParseMode.HTML,
                    )
                    return
                amount = min(amount, available)
            else:
                claimed_today = 0
        except ValueError:
            claimed_today = 0

    new_bal = await db_add_vrf(user.id, cid, amount)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET last_clicker_claim=?, clicker_claimed_today=? "
            "WHERE user_id=? AND chat_id=?",
            (datetime.now().isoformat(), claimed_today + amount, user.id, cid),
        )
        await db.commit()

    remain = max(0, CLICKER_DAILY_MAX - claimed_today - amount)
    await msg.reply_text(
        f"🖱 <b>Кликер — зачислено!</b>\n\n"
        f"💎 +{fmt(amount)} VRF\n"
        f"💰 Баланс: <b>{fmt(new_bal)} VRF</b>\n\n"
        f"<i>Осталось сегодня: {fmt(remain)} VRF</i>",
        parse_mode=ParseMode.HTML,
    )



# ══════════════════════════════════════════════════════
#   БАШНЯ 🏢 — этажная рулетка с голосованием
# ══════════════════════════════════════════════════════
# Логика: игроки делают ставку, каждый этаж голосуют Л/П.
# Большинство открывает дверь — за одной мина, за другой проход.
# Чем выше этаж — тем больше множитель выигрыша.
# Можно забрать ставку после любого этажа до следующего голосования.

TOWER_MIN_BET    = 10
TOWER_BET_PRESETS = [25, 50, 100, 250, 500]
TOWER_JOIN_SECS  = 28
TOWER_VOTE_SECS  = 22
TOWER_CASH_SECS  = 8     # window to cashout between floors
TOWER_TICK       = 5     # image update interval
# Multipliers per floor (up to 10 floors)
TOWER_MULTS = [1.30, 1.70, 2.20, 2.80, 3.60, 4.50, 5.80, 7.50, 9.50, 12.50]

tower_games: dict = {}   # key: cid (int)

# ── Image constants ───────────────────────────────────
_T_S_TOP  = (3, 6, 18);  _T_S_BOT = (8, 14, 32)
_T_BLDG   = (18, 26, 44); _T_BLDG2 = (14, 20, 36)
_T_F_LINE = (30, 42, 65); _T_WIN_DK = (12, 18, 36)
_T_WIN_LIT = (255, 220, 100); _T_WIN_SAF = (70, 200, 120)
_T_D_WOOD = (150, 100, 55); _T_D_FRM = (90, 58, 28)
_T_D_KNOB = (220, 180, 80); _T_GOLD = (255, 205, 50)
_T_RED = (240, 60, 40); _T_GREEN = (70, 210, 110)
_T_GROUND = (28, 38, 58); _T_CEIL = (22, 32, 52)
_T_WHITE = (230, 238, 252); _T_MUTED = (140, 155, 185)
_T_MOON = (225, 230, 255); _T_BX = 128; _T_BW = 384


def _tlerp(a, b, t):
    t = max(0.0, min(1.0, t))
    return tuple(round(a[i]+(b[i]-a[i])*t) for i in range(3))


def _tower_floor_rect(fi: int, max_f: int, y_bot: int, fh: int):
    fy_bot = y_bot - (fi-1)*fh
    return (_T_BX, fy_bot - fh, _T_BX + _T_BW, fy_bot)


def _tower_draw_door(d, x1, y1, x2, y2, color, label, fh, open_pct=0.0):
    d.rectangle([x1-2, y1-2, x2+2, y2+2], fill=_T_D_FRM)
    if open_pct > 0:
        vw = max(4, int((x2-x1)*(1-open_pct)))
        d.rectangle([x1, y1, x1+vw, y2], fill=color)
        d.rectangle([x1+vw, y1, x2, y2], fill=_T_WIN_DK)
    else:
        d.rectangle([x1, y1, x2, y2], fill=color)
        pw, ph = max(2,(x2-x1)//5), max(4,(y2-y1)//5)
        d.rectangle([x1+pw, y1+ph, x2-pw, y2-ph],
                    outline=_tlerp(color,(0,0,0),0.2), width=1)
    kx = x2-6 if label == "L" else x1+6
    ky = (y1+y2)//2
    d.ellipse([kx-3,ky-3,kx+3,ky+3], fill=_T_D_KNOB)
    if label:
        try:
            from PIL import ImageFont
            for p in ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]:
                try:
                    f = ImageFont.truetype(p, min(fh-20, 28))
                    break
                except Exception:
                    f = None
            if f:
                bbox = d.textbbox((0,0), label, font=f)
                tw, th = bbox[2]-bbox[0], bbox[3]-bbox[1]
                tx = (x1+x2)//2 - tw//2; ty = (y1+y2)//2 - th//2
                d.text((tx+1,ty+1), label, font=f, fill=(0,0,0))
                d.text((tx, ty), label, font=f, fill=_T_WHITE)
        except Exception:
            pass


def _tower_image_sync(
    game: dict,
    mode: str = "voting",     # joining|voting|cashout|safe|bomb|complete
    vote_L: int = 0, vote_R: int = 0,
    time_left: int = 0,
) -> Optional[bytes]:
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None

    W, H = 640, 900
    max_f   = game["max_floors"]
    cur_f   = game["floor"]
    history = game.get("history", [])
    mults   = game.get("mults", TOWER_MULTS)

    img = Image.new("RGB", (W, H), _T_S_TOP)
    d   = ImageDraw.Draw(img)

    # Sky gradient
    for y in range(H):
        c = _tlerp(_T_S_TOP, _T_S_BOT, y/H)
        d.line([(0,y),(W,y)], fill=c)

    # Stars (deterministic)
    rng = random.Random(7)
    for _ in range(90):
        sx, sy = rng.randint(0,W), rng.randint(0,H*2//3)
        sr = rng.uniform(0.5, 2.0); sa = rng.uniform(0.2, 0.95)
        sc = round(255*sa)
        d.ellipse([sx-sr,sy-sr,sx+sr,sy+sr], fill=(sc,sc,min(255,sc+18)))

    # Moon
    d.ellipse([565,32,610,77], fill=_T_MOON)
    d.ellipse([575,27,618,72], fill=_T_S_TOP)

    Y_GROUND = H - 60
    Y_TOP_B  = 90 + max(0, (10-max_f)*5)
    fh = (Y_GROUND - Y_TOP_B) // max_f
    BR = _T_BX + _T_BW

    # Side buildings
    d.rectangle([0, Y_GROUND-280, 115, Y_GROUND], fill=_T_BLDG2)
    d.rectangle([525, Y_GROUND-220, W, Y_GROUND], fill=_T_BLDG2)

    # Ground
    for y in range(Y_GROUND, H):
        d.line([(0,y),(W,y)], fill=_tlerp(_T_GROUND,(18,24,38),(y-Y_GROUND)/(H-Y_GROUND)))

    # Main building body
    d.rectangle([_T_BX, Y_TOP_B, BR, Y_GROUND], fill=_T_BLDG)
    d.rectangle([_T_BX, Y_TOP_B-8, BR, Y_TOP_B], fill=_tlerp(_T_BLDG,(0,0,0),0.3))

    # Draw floors
    for fi in range(1, max_f+1):
        x1, y1, x2, y2 = _tower_floor_rect(fi, max_f, Y_GROUND, fh)
        fh_real = y2 - y1
        mid = (x1+x2)//2

        # Classify floor
        if fi < cur_f:
            hist = history[fi-1] if fi-1 < len(history) else {}
            st = "safe"; vd = hist.get("voted"); bd = hist.get("bomb")
        elif fi == cur_f:
            st = mode; vd = None
            last = history[-1] if history and mode in ("safe","bomb") else {}
            if mode in ("safe","bomb"):
                vd = last.get("voted"); bd2 = last.get("bomb")
            else:
                bd2 = None
            bd = bd2 if mode in ("safe","bomb") else None
        else:
            st = "future"; vd = None; bd = None

        # Floor background
        bg = _T_BLDG if st not in ("safe",) else _tlerp(_T_BLDG, _T_WIN_SAF, 0.18)
        d.rectangle([x1,y1,x2,y2], fill=bg)
        d.rectangle([x1,y1,x2,y1+5], fill=_tlerp(_T_CEIL,(0,0,0),0.3))
        d.line([(x1,y2),(x2,y2)], fill=_T_F_LINE, width=2)

        # Door zone
        door_w = 76; door_x1 = mid - door_w//2; door_x2 = mid + door_w//2
        dh = max(24, fh_real-14); dy1 = y1+(fh_real-dh)//2+2; dy2 = dy1+dh
        win_h = max(16, fh_real-22); win_w = 28
        win_y = y1+(fh_real-win_h)//2+3

        # Windows
        wc = (_T_WIN_LIT if st == "safe"
              else _T_WIN_DK if st in ("future","joining")
              else _tlerp(_T_WIN_DK, _T_WIN_LIT, 0.55))
        for wx in [x1+10, x1+10+win_w+8, x1+10+2*(win_w+8)]:
            if wx+win_w < door_x1-4:
                d.rectangle([wx,win_y,wx+win_w,win_y+win_h], fill=wc)
        for wx in [door_x2+10, door_x2+10+win_w+8, door_x2+10+2*(win_w+8)]:
            if wx+win_w < x2-4:
                d.rectangle([wx,win_y,wx+win_w,win_y+win_h], fill=wc)

        # Doors
        lx1,lx2 = door_x1, mid-2; rx1,rx2 = mid+2, door_x2
        if st in ("voting","joining","cashout"):
            show_lbl = (st == "voting" and fi == cur_f)
            _tower_draw_door(d, lx1,dy1,lx2,dy2, _T_D_WOOD, "L" if show_lbl else None, fh_real)
            _tower_draw_door(d, rx1,dy1,rx2,dy2, _tlerp(_T_D_WOOD,(30,0,0),0.15), "R" if show_lbl else None, fh_real)
        elif st == "safe" and fi == cur_f:
            lc = _T_GREEN if vd=="L" and bd!="L" else (_T_RED if bd=="L" else _T_D_WOOD)
            rc = _T_GREEN if vd=="R" and bd!="R" else (_T_RED if bd=="R" else _T_D_WOOD)
            _tower_draw_door(d, lx1,dy1,lx2,dy2, lc, None, fh_real, 0.55 if lc==_T_GREEN else 0)
            _tower_draw_door(d, rx1,dy1,rx2,dy2, rc, None, fh_real, 0.55 if rc==_T_GREEN else 0)
        elif st == "safe":  # already-cleared floor
            _tower_draw_door(d, lx1,dy1,lx2,dy2, _tlerp(_T_WIN_SAF,_T_D_WOOD,0.5), None, fh_real)
            _tower_draw_door(d, rx1,dy1,rx2,dy2, _T_RED, None, fh_real)
        elif st == "bomb":
            bx, by = mid, (dy1+dy2)//2
            for rad in range(50,8,-10):
                d.ellipse([bx-rad,by-rad,bx+rad,by+rad], fill=_tlerp(_T_RED,_T_GOLD,(50-rad)/50))
            d.ellipse([bx-10,by-10,bx+10,by+10], fill=_T_WHITE)
            rng2 = random.Random(cur_f*7+9)
            for i in range(14):
                ang=(i/14)*2*math.pi+rng2.uniform(-0.1,0.1); ln=rng2.uniform(20,45)
                d.line([(bx+math.cos(ang)*18,by+math.sin(ang)*18),
                        (bx+math.cos(ang)*(18+ln),by+math.sin(ang)*(18+ln))],
                       fill=_T_GOLD, width=2)
        else:  # future
            d.rectangle([lx1,dy1,lx2,dy2], fill=_tlerp(_T_BLDG,_T_D_WOOD,0.18))
            d.rectangle([rx1,dy1,rx2,dy2], fill=_tlerp(_T_BLDG,_T_D_WOOD,0.15))

        # Multiplier badge (left of cleared floors)
        if fi < cur_f:
            mi = mults[fi-1]
            lbl = f"x{mi:.1f}"
            try:
                from PIL import ImageFont
                for p in ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]:
                    try: fnt = ImageFont.truetype(p, 10); break
                    except: fnt = None
                if fnt: d.text((_T_BX-48,(y1+y2)//2-6), lbl, font=fnt, fill=_T_GREEN)
            except Exception: pass

        # Floor number label (right side)
        try:
            from PIL import ImageFont
            for p in ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]:
                try: fnt = ImageFont.truetype(p, 10); break
                except: fnt = None
            if fnt: d.text((BR+8,(y1+y2)//2-6), f"F{fi}", font=fnt, fill=_T_MUTED)
        except Exception: pass

    # Active floor glow
    if mode in ("voting","cashout") and 1 <= cur_f <= max_f:
        ax1,ay1,ax2,ay2 = _tower_floor_rect(cur_f, max_f, Y_GROUND, fh)
        for i in range(5,0,-1):
            c = _tlerp(_T_BLDG, _T_GOLD, i/6 * 0.9)
            d.rectangle([ax1-i,ay1-i,ax2+i,ay2+i], outline=c, width=1)

    # Progress bar (right edge)
    pbx, pby, pbh = W-12, Y_TOP_B, Y_GROUND-Y_TOP_B
    d.rectangle([pbx,pby,pbx+6,pby+pbh], fill=_tlerp(_T_BLDG,(0,0,0),0.2))
    if cur_f > 1:
        filled = round(pbh*(cur_f-1)/max(1,max_f-1))
        d.rectangle([pbx,pby+pbh-filled,pbx+6,pby+pbh], fill=_T_GREEN)

    # Timer bar (bottom of image)
    if mode == "voting" and TOWER_VOTE_SECS > 0:
        tbx, tby, tbw = 30, Y_GROUND+18, W-60
        d.rounded_rectangle([tbx,tby,tbx+tbw,tby+6], radius=3, fill=_T_BLDG)
        pct = max(0, time_left/TOWER_VOTE_SECS)
        fw = round(tbw*pct)
        if fw > 4:
            d.rounded_rectangle([tbx,tby,tbx+fw,tby+6], radius=3,
                                 fill=_tlerp(_T_RED,_T_GOLD,pct))
    elif mode == "cashout":
        tbx, tby, tbw = 30, Y_GROUND+18, W-60
        d.rounded_rectangle([tbx,tby,tbx+tbw,tby+6], radius=3, fill=_T_BLDG)
        pct = max(0, time_left/TOWER_CASH_SECS)
        fw = round(tbw*pct)
        if fw > 4:
            d.rounded_rectangle([tbx,tby,tbx+fw,tby+6], radius=3,
                                 fill=_tlerp(_T_GREEN,_T_BLDG,pct))

    # Header: floor + multiplier (ASCII only, always renders)
    try:
        from PIL import ImageFont
        for p in ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]:
            try: fb = ImageFont.truetype(p, 38); break
            except: fb = None
        for p in ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]:
            try: fm = ImageFont.truetype(p, 18); break
            except: fm = None
        for p in ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]:
            try: fs = ImageFont.truetype(p, 13); break
            except: fs = None

        cur_mult = mults[min(cur_f-1, len(mults)-1)]

        # Floor label
        txt = f"FL {cur_f}/{max_f}"
        if fb: d.text((22,18), txt, font=fb, fill=_T_GOLD)

        # Multiplier badge
        ms = f"x{cur_mult:.2f}"
        col = (_T_RED if mode == "bomb" else
               _T_GREEN if mode in ("safe","complete") else _T_GOLD)
        if fm:
            bbox = d.textbbox((0,0), ms, font=fm)
            tw = bbox[2]-bbox[0]
            bx2 = W-tw-30
            d.rounded_rectangle([bx2-10,18,bx2+tw+10,44], radius=8,
                                 fill=_tlerp(_T_BLDG,col,0.3))
            d.text((bx2,22), ms, font=fm, fill=col)

        # Vote counts
        if mode == "voting" and fs:
            vc = f"L:{vote_L}   R:{vote_R}   ({time_left}s)"
            d.text((22,62), vc, font=fs, fill=_T_WHITE)
        elif mode == "cashout" and fs:
            d.text((22,62), f"CASHOUT! ({time_left}s)", font=fs, fill=_T_GREEN)
        elif mode == "joining" and fs:
            d.text((22,62), "JOIN! Place your bet", font=fs, fill=_T_GREEN)
        elif mode == "bomb" and fs:
            d.text((22,62), "BOOM! GAME OVER", font=fs, fill=_T_RED)
        elif mode == "complete" and fs:
            d.text((22,62), "COMPLETE! All floors cleared!", font=fs, fill=_T_GREEN)

    except Exception:
        pass

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


# ── Tower caption builders ────────────────────────────

def _tower_join_caption(game: dict) -> str:
    players = game["players"]
    total   = sum(p["bet"] for p in players.values())
    remain  = max(0, int((game["join_deadline"] - datetime.now()).total_seconds()))
    mults   = game.get("mults", TOWER_MULTS)
    max_f   = game["max_floors"]
    mult_row = " · ".join(f"x{mults[i]:.1f}" for i in range(min(max_f, len(mults))))

    plines = "\n".join(
        f"{mention(uid, p['name'])} — {fmt(p['bet'])} VRF"
        for uid, p in list(players.items())[:12]
    ) or "<i>Пока никого</i>"
    if len(players) > 12:
        plines += f"\n<i>+{len(players)-12} ещё</i>"

    return (
        f"🏢 <b>БАШНЯ</b>  ·  {max_f} этажей\n"
        f"<blockquote>{mult_row}</blockquote>\n"
        f"Банк: <b>{fmt(total)} VRF</b>\n\n"
        f"{plines}\n\n"
        f"⏱ <b>{remain} сек</b> — делай ставку!"
    )


def _tower_vote_caption(game: dict, time_left: int) -> str:
    cur_f  = game["floor"]
    mults  = game.get("mults", TOWER_MULTS)
    cur_m  = mults[min(cur_f-1, len(mults)-1)]
    votes  = game.get("voted", {})
    alive  = {uid: p for uid, p in game["players"].items() if p.get("alive", True) and not p["cashed"]}

    voted_L  = [p["name"] for uid, p in alive.items() if votes.get(uid) == "L"]
    voted_R  = [p["name"] for uid, p in alive.items() if votes.get(uid) == "R"]
    no_vote  = [p["name"] for uid, p in alive.items() if uid not in votes]
    cashed   = [p for p in game["players"].values() if p["cashed"]]

    def _nlist(names): return ", ".join(names[:5]) + (f" +{len(names)-5}" if len(names)>5 else "")

    parts = [f"🏢 <b>Этаж {cur_f}/{game['max_floors']}</b>  <code>x{cur_m:.2f}</code>  ⏱ {time_left}с\n"]

    if voted_L:  parts.append(f"🚪 Левая:  {_nlist(voted_L)}")
    if voted_R:  parts.append(f"🚪 Правая: {_nlist(voted_R)}")
    if no_vote:  parts.append(f"<i>Не выбрали: {_nlist(no_vote)}</i>")

    if cashed:
        c_lines = "  ".join(f"{p['name']} x{p['cash_mult']:.1f}" for p in cashed[:4])
        parts.append(f"\n💰 Забрали: {c_lines}")

    return "\n".join(parts)


def _tower_reveal_caption(game: dict, cur_f: int, bomb: str,
                           went_up: list, eliminated: list) -> str:
    safe_door = "Правая" if bomb == "L" else "Левая"
    bomb_door = "Левая" if bomb == "L" else "Правая"
    mults = game.get("mults", TOWER_MULTS)
    cur_m = mults[min(cur_f-1, len(mults)-1)]

    up_str  = ", ".join(n for _, n in went_up[:6])   or "—"
    out_str = ", ".join(n for _, n, _ in eliminated[:6]) or "—"
    if len(went_up) > 6:    up_str  += f" +{len(went_up)-6}"
    if len(eliminated) > 6: out_str += f" +{len(eliminated)-6}"

    next_f   = cur_f + 1
    next_m   = mults[min(next_f-1, len(mults)-1)] if next_f <= game["max_floors"] else None
    next_str = f"  ·  следующий x{next_m:.2f}" if next_m else ""

    return (
        f"✅ <b>Этаж {cur_f} — безопасная дверь: {safe_door}</b>\n\n"
        f"Продолжают:  {up_str}\n"
        f"Выбыли:      {out_str} <i>(открыли {bomb_door} 💣)</i>\n\n"
        f"<code>x{cur_m:.2f}{next_str}</code>"
    )


def _tower_cashout_caption(game: dict, time_left: int) -> str:
    cur_f  = game["floor"]
    mults  = game.get("mults", TOWER_MULTS)
    prev_m = mults[min(cur_f-2, len(mults)-1)] if cur_f > 1 else mults[0]
    next_m = mults[min(cur_f-1, len(mults)-1)]
    alive  = sum(1 for p in game["players"].values() if p.get("alive",True) and not p["cashed"])
    return (
        f"✅ <b>Этаж {cur_f-1} — пройден!</b>\n\n"
        f"Текущий:    <b>x{prev_m:.2f}</b>\n"
        f"Следующий:  <b>x{next_m:.2f}</b>\n\n"
        f"<b>{time_left}с</b> на выход · В игре: {alive}"
    )


def _tower_result_cards(game: dict, bomb_floor: int = None) -> tuple:
    mults   = game.get("mults", TOWER_MULTS)
    winners = []
    losers  = []
    for uid, p in game["players"].items():
        if p["cashed"] or (not p.get("alive", True) is False and p.get("payout", 0) > 0):
            if p.get("payout", 0) > 0:
                winners.append((p["name"], p.get("cash_mult", 1.0), p["payout"]))
            elif p["cashed"]:
                winners.append((p["name"], p.get("cash_mult", 1.0), p.get("payout", 0)))
        else:
            losers.append((p["name"], p["bet"]))

    if bomb_floor:
        h2 = f"<h2>💥 Башня — мина на этаже {bomb_floor}!</h2>"
    else:
        m = mults[min(game["floor"]-1, len(mults)-1)]
        h2 = f"<h2>🏆 Башня — {game['max_floors']} этажей пройдено! x{m:.2f}</h2>"

    rows = "".join(
        f"<tr><td>🏆 {n}</td><td><b>x{m:.2f}</b> <mark>+{fmt(py)}</mark></td></tr>"
        for n, m, py in winners
    ) + "".join(
        f"<tr><td>💥 {n}</td><td><b>-{fmt(b)} VRF</b></td></tr>"
        for n, b in losers
    ) or "<tr><td colspan='2'><i>Нет участников</i></td></tr>"

    rich_h = (
        h2 + "<table bordered striped>" + rows + "</table>"
        f"<blockquote>Участников: {len(game['players'])}  ·  "
        f"Дошли до этажа: {game['floor']}</blockquote>"
    )
    fb_h = (
        (f"💥 <b>Мина на этаже {bomb_floor}!</b>" if bomb_floor
         else "🏆 <b>Башня пройдена!</b>") + "\n\n"
        + "\n".join(f"🏆 {n} x{m:.2f} +{fmt(py)} VRF" for n,m,py in winners)
        + "\n" + "\n".join(f"💥 {n} -{fmt(b)} VRF" for n,b in losers)
        + "\n\n🏢 /tower"
    )
    return rich_h, fb_h


# ── Tower keyboards ───────────────────────────────────

def _tower_join_kb(cid: int) -> InlineKeyboardMarkup:
    row1 = [SBtn(f"{a}", style="primary", callback_data=f"tw:join:{cid}:{a}")
            for a in TOWER_BET_PRESETS[:3]]
    row2 = [SBtn(f"{a}", style="primary", callback_data=f"tw:join:{cid}:{a}")
            for a in TOWER_BET_PRESETS[3:]]
    return InlineKeyboardMarkup([
        row1, row2,
        [SBtn("✏️ Своя сумма", style="primary", callback_data=f"tw:custom:{cid}")],
    ])


def _tower_vote_kb(cid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        SBtn("🚪 Левая",  style="primary",  callback_data=f"tw:L:{cid}"),
        SBtn("🚪 Правая", style="primary",  callback_data=f"tw:R:{cid}"),
    ], [
        SBtn("💰 Забрать", style="success", callback_data=f"tw:cash:{cid}"),
    ]])


def _tower_cashout_only_kb(cid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        SBtn("💰 Забрать сейчас", style="success", callback_data=f"tw:cash:{cid}"),
    ]])


# ── Tower custom bet state ────────────────────────────
tower_custom_pending: dict = {}   # key: (cid, uid)


# ── Lifecycle functions ───────────────────────────────

async def _tower_end(bot, cid: int, bomb_floor: int = None) -> None:
    """End game, pay out survivors/cashouts, send rich result table."""
    game = tower_games.pop(cid, None)
    if not game:
        return

    mults = game.get("mults", TOWER_MULTS)

    # Complete: pay out everyone still alive
    if not bomb_floor:
        final_m = mults[min(game["floor"]-1, len(mults)-1)]
        for uid, p in game["players"].items():
            if p.get("alive", True) and not p["cashed"]:
                payout = round(p["bet"] * final_m)
                p["payout"] = payout; p["cash_mult"] = final_m
                p["cashed"] = True;   p["alive"] = False
                await db_add_vrf(uid, cid, payout)
                await db_add_xp(uid, cid, XP_PER_WIN)
                await db_record_game(uid, cid, won=True)

    mode = "bomb" if bomb_floor else "complete"
    loop = asyncio.get_running_loop()
    img  = await loop.run_in_executor(None, _tower_image_sync, game, mode)
    cap  = (f"💥 <b>Мина на этаже {bomb_floor}!</b>" if bomb_floor
            else "🏆 <b>Башня пройдена!</b>")
    try:
        if img:
            await bot.edit_message_media(
                chat_id=cid, message_id=game["msg_id"],
                media=InputMediaPhoto(media=io.BytesIO(img),
                                      caption=cap, parse_mode=ParseMode.HTML),
            )
        else:
            await bot.edit_message_caption(
                chat_id=cid, message_id=game["msg_id"],
                caption=cap, parse_mode=ParseMode.HTML, reply_markup=None,
            )
    except TelegramError:
        pass

    rich_h, fb_h = _tower_result_cards(game, bomb_floor=bomb_floor)
    await send_rich(bot, cid, html=rich_h, fallback_html=fb_h,
                    reply_markup=_play_again_kb("tower", cid))


async def _tower_floor_loop(bot, cid: int) -> None:
    """
    Run one floor:
      1. Cashout window (floor 2+)
      2. Voting window — each player votes L or R independently
      3. Reveal: players who picked the bomb door are ELIMINATED;
         players who picked the safe door advance.
      4. If survivors remain → next floor; otherwise → game over.
    """
    try:
        loop = asyncio.get_running_loop()
        game = tower_games.get(cid)
        if not game or game["state"] == "ended":
            return

        cur_f = game["floor"]
        mults = game.get("mults", TOWER_MULTS)
        max_f = game["max_floors"]

        # ── Cashout window (floor 2+) ─────────────────────────────────
        if cur_f > 1:
            game["state"] = "cashout"
            img = await loop.run_in_executor(
                None, _tower_image_sync, game, "cashout", 0, 0, TOWER_CASH_SECS)
            try:
                if img:
                    await bot.edit_message_media(
                        chat_id=cid, message_id=game["msg_id"],
                        media=InputMediaPhoto(
                            media=io.BytesIO(img),
                            caption=_tower_cashout_caption(game, TOWER_CASH_SECS),
                            parse_mode=ParseMode.HTML),
                        reply_markup=_tower_cashout_only_kb(cid),
                    )
            except TelegramError:
                pass
            await asyncio.sleep(TOWER_CASH_SECS)
            game = tower_games.get(cid)
            if not game:
                return

        # ── Voting window ─────────────────────────────────────────────
        game["state"]         = "voting"
        game["voted"]         = {}
        game["vote_deadline"] = datetime.now() + timedelta(seconds=TOWER_VOTE_SECS)

        elapsed = 0
        while elapsed < TOWER_VOTE_SECS:
            game = tower_games.get(cid)
            if not game or game["state"] != "voting":
                return
            remain = max(0, int((game["vote_deadline"] - datetime.now()).total_seconds()))
            vL = sum(1 for v in game["voted"].values() if v == "L")
            vR = sum(1 for v in game["voted"].values() if v == "R")
            img = await loop.run_in_executor(
                None, _tower_image_sync, game, "voting", vL, vR, remain)
            try:
                if img:
                    await bot.edit_message_media(
                        chat_id=cid, message_id=game["msg_id"],
                        media=InputMediaPhoto(
                            media=io.BytesIO(img),
                            caption=_tower_vote_caption(game, remain),
                            parse_mode=ParseMode.HTML),
                        reply_markup=_tower_vote_kb(cid),
                    )
            except TelegramError:
                pass
            await asyncio.sleep(TOWER_TICK)
            elapsed += TOWER_TICK

        # ── Determine individual outcomes ─────────────────────────────
        game = tower_games.get(cid)
        if not game or game["state"] != "voting":
            return

        bomb = game["bomb_doors"][cur_f - 1]
        votes = game.get("voted", {})
        alive_before = {uid: p for uid, p in game["players"].items()
                        if p.get("alive", True) and not p["cashed"]}

        went_up   = []   # (uid, name)
        eliminated = []  # (uid, name, bet)

        for uid, p in alive_before.items():
            chosen = votes.get(uid)
            if chosen is None or chosen == bomb:
                # No vote or chose bomb door → eliminated
                p["alive"] = False
                eliminated.append((uid, p["name"], p["bet"]))
                await db_add_xp(uid, cid, XP_PER_GAME)
                await db_record_game(uid, cid, won=False)
            else:
                # Picked safe door → advance
                went_up.append((uid, p["name"]))
                await db_add_xp(uid, cid, XP_PER_GAME)

        game["history"].append({
            "voted": votes, "bomb": bomb,
            "went_up": len(went_up), "eliminated": len(eliminated),
        })

        # Show reveal image
        game_snap = dict(game); game_snap["floor"] = cur_f
        img = await loop.run_in_executor(None, _tower_image_sync, game_snap, "safe")
        reveal_cap = _tower_reveal_caption(game, cur_f, bomb, went_up, eliminated)
        try:
            if img:
                await bot.edit_message_media(
                    chat_id=cid, message_id=game["msg_id"],
                    media=InputMediaPhoto(media=io.BytesIO(img),
                                         caption=reveal_cap, parse_mode=ParseMode.HTML),
                    reply_markup=None,
                )
        except TelegramError:
            pass

        await asyncio.sleep(3)

        # Check survivors
        if not went_up:
            # All eliminated — game over
            await _tower_end(bot, cid, bomb_floor=cur_f)
            return

        # Advance
        game["floor"] += 1
        if game["floor"] > max_f:
            await _tower_end(bot, cid, bomb_floor=None)
        else:
            await _tower_floor_loop(bot, cid)

    except Exception:
        log.exception("Tower floor loop error (cid=%s)", cid)
        tower_games.pop(cid, None)


async def _tower_join_loop(bot, cid: int) -> None:
    try:
        loop = asyncio.get_running_loop()
        while True:
            game = tower_games.get(cid)
            if not game or game["state"] != "joining":
                return
            remain = max(0, int((game["join_deadline"] - datetime.now()).total_seconds()))
            if remain <= 0:
                break
            await asyncio.sleep(min(TOWER_TICK, remain))
            game = tower_games.get(cid)
            if not game or game["state"] != "joining":
                return
            remain = max(0, int((game["join_deadline"] - datetime.now()).total_seconds()))
            img = await loop.run_in_executor(None, _tower_image_sync, game, "joining")
            try:
                if img:
                    await bot.edit_message_media(
                        chat_id=cid, message_id=game["msg_id"],
                        media=InputMediaPhoto(
                            media=io.BytesIO(img),
                            caption=_tower_join_caption(game),
                            parse_mode=ParseMode.HTML),
                        reply_markup=_tower_join_kb(cid),
                    )
            except TelegramError:
                pass

        game = tower_games.get(cid)
        if not game or game["state"] != "joining":
            return

        if len(game["players"]) < 2:
            tower_games.pop(cid, None)
            for uid, p in game["players"].items():
                await db_add_vrf(uid, cid, p["bet"])
            try:
                await bot.edit_message_caption(
                    chat_id=cid, message_id=game["msg_id"],
                    caption="🏢 Башня отменена — мало игроков. Ставки возвращены.",
                    parse_mode=ParseMode.HTML, reply_markup=None,
                )
            except TelegramError:
                pass
            return

        game["state"] = "voting"
        await _tower_floor_loop(bot, cid)

    except Exception:
        log.exception("Tower join loop error (cid=%s)", cid)
        tower_games.pop(cid, None)


# ── /tower command ────────────────────────────────────

@only_groups
async def cmd_tower(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    u   = update.effective_user
    cid = update.effective_chat.id

    existing = tower_games.get(cid)
    if existing and existing["state"] != "ended":
        await update.message.reply_text(
            "🏢 Башня уже идёт — присоединяйся!", parse_mode=ParseMode.HTML)
        return

    await db_ensure_user(u.id, cid, u.username or "", u.first_name)
    tower_games[cid] = {"cid": cid, "state": "launching"}

    max_f   = random.randint(6, 10)
    bombs   = [random.choice(["L", "R"]) for _ in range(max_f)]
    now     = datetime.now()
    stub    = {
        "cid": cid, "state": "joining",
        "starter_id": u.id, "starter_name": u.first_name,
        "max_floors": max_f, "floor": 1,
        "bomb_doors": bombs, "mults": TOWER_MULTS[:max_f],
        "players": {}, "voted": {}, "history": [],
        "join_deadline": now + timedelta(seconds=TOWER_JOIN_SECS),
        "vote_deadline": None, "msg_id": None,
    }

    loop = asyncio.get_running_loop()
    img  = await loop.run_in_executor(None, _tower_image_sync, stub, "joining")
    try:
        if img:
            msg = await context.bot.send_photo(
                chat_id=cid, photo=io.BytesIO(img),
                caption=_tower_join_caption(stub), parse_mode=ParseMode.HTML,
                reply_markup=_tower_join_kb(cid),
            )
        else:
            msg = await context.bot.send_message(
                cid, _tower_join_caption(stub), parse_mode=ParseMode.HTML,
                reply_markup=_tower_join_kb(cid),
            )
    except TelegramError:
        tower_games.pop(cid, None)
        return

    stub["msg_id"] = msg.message_id
    tower_games[cid] = stub
    context.application.create_task(_tower_join_loop(context.bot, cid))



# ══════════════════════════════════════════════════════
#   ЛАБИРИНТ 🏰 — first-person dungeon crawler
# ══════════════════════════════════════════════════════
# Карта 13×13, первое лицо. Навигация: ↑вперёд ↓назад ←поворот ←поворот.
# Что впереди — неизвестно до хода. Ловушки (-1♥), сундуки (+VRF), выход (победа).

MAZE_MIN_BET    = 10
MAZE_BET_PRESETS = [25, 50, 100, 250, 500]
MAZE_HP_MAX     = 3
MAZE_GRID_N     = 6       # rooms per side → grid = 2*6+1 = 13
MAZE_TRAP_PCT   = 0.12    # fraction of open cells that are traps
MAZE_CHEST_PCT  = 0.08

# Payout multipliers based on efficiency (optimal_steps / actual_steps)
MAZE_MULT = [(0.85, 2.8), (0.65, 2.2), (0.45, 1.7), (0.0, 1.2)]

maze_games: dict = {}   # key: (uid, cid)

# ── Direction system ──────────────────────────────────
_MZ_FWD  = [(0,-1),(1,0),(0,1),(-1,0)]   # N E S W — (dx, dy)
_MZ_LEFT = [(-1,0),(0,-1),(1,0),(0,1)]   # perpendicular left
_MZ_DIR_NAMES = ['СЕВЕР ↑','ВОСТОК →','ЮГ ↓','ЗАПАД ←']

def _mz_turn_left(d):  return (d + 3) % 4
def _mz_turn_right(d): return (d + 1) % 4


# ── Maze generation (recursive backtracking, 13×13 grid) ──

def _mz_generate(seed: int) -> tuple:
    """Returns (grid, exit_pos, optimal_steps). grid[y][x] = 'W'|'.'|'T'|'P'|'S'|'E'"""
    G = 2 * MAZE_GRID_N + 1
    grid = [['W'] * G for _ in range(G)]
    rng  = random.Random(seed)
    vis  = [[False]*MAZE_GRID_N for _ in range(MAZE_GRID_N)]

    def carve(cx, cy):
        gx, gy = 2*cx+1, 2*cy+1
        vis[cy][cx] = True
        grid[gy][gx] = '.'
        dirs = [(0,-1),(1,0),(0,1),(-1,0)]; rng.shuffle(dirs)
        for dx, dy in dirs:
            nx, ny = cx+dx, cy+dy
            if 0<=nx<MAZE_GRID_N and 0<=ny<MAZE_GRID_N and not vis[ny][nx]:
                grid[gy+dy][gx+dx] = '.'   # carve passage
                carve(nx, ny)

    carve(0, 0)

    # Find all open cells except start
    open_cells = [(x,y) for y in range(G) for x in range(G)
                  if grid[y][x] == '.' and (x,y) != (1,1)]
    rng.shuffle(open_cells)

    # Exit: far from start
    far = sorted(open_cells, key=lambda p: abs(p[0]-1)+abs(p[1]-1), reverse=True)
    exit_pos = far[0]
    ex, ey = exit_pos
    grid[ey][ex] = 'E'

    # BFS for optimal steps
    from collections import deque
    dist = {(1,1): 0}
    q = deque([(1,1)])
    while q:
        cx, cy = q.popleft()
        for ddx, ddy in [(0,-1),(1,0),(0,1),(-1,0)]:
            nx, ny = cx+ddx, cy+ddy
            if 0<=nx<G and 0<=ny<G and grid[ny][nx]!='W' and (nx,ny) not in dist:
                dist[(nx,ny)] = dist[(cx,cy)] + 1
                q.append((nx,ny))
    optimal = dist.get(exit_pos, 30)

    # Traps and chests (avoid start, exit, and passage-only cells)
    playable = [c for c in open_cells if c != exit_pos]
    n_trap  = max(2, int(len(playable) * MAZE_TRAP_PCT))
    n_chest = max(1, int(len(playable) * MAZE_CHEST_PCT))
    idx = 0
    for _ in range(n_trap):
        if idx < len(playable):
            x, y = playable[idx]; idx += 1
            if grid[y][x] == '.':
                grid[y][x] = rng.choice(['P','S'])
    for _ in range(n_chest):
        if idx < len(playable):
            x, y = playable[idx]; idx += 1
            if grid[y][x] == '.':
                grid[y][x] = 'T'

    return grid, exit_pos, optimal


# ── Scene computation ─────────────────────────────────

def _mz_scene(grid, px, py, direction):
    G = len(grid)
    fx, fy = _MZ_FWD[direction]
    lx, ly = _MZ_LEFT[direction]
    rx, ry = -lx, -ly

    def cell(x, y):
        if 0<=x<G and 0<=y<G: return grid[y][x]
        return 'W'

    # ahead[0..2] = cell types 1,2,3 steps forward
    ahead = [cell(px+fx*d, py+fy*d) for d in range(1,4)]
    # left[0..2] = wall to left at depth 0 (player pos), 1, 2
    left  = [cell(px+lx+fx*d, py+ly+fy*d) == 'W' for d in range(0,3)]
    right = [cell(px+rx+fx*d, py+ry+fy*d) == 'W' for d in range(0,3)]

    return {'ahead': ahead, 'left': left, 'right': right}


# ── Image renderer (first-person dungeon view) ────────

_MZ_W, _MZ_H   = 640, 560
_MZ_VT, _MZ_VB = 55, 515
_MZ_HORIZON     = (_MZ_VT + _MZ_VB) // 2   # 285

# Perspective zones: (abs_top, abs_bot, left_x, right_x)
_MZ_Z = [
    (_MZ_VT,      _MZ_VB,      0,   _MZ_W),
    (_MZ_VT+42,   _MZ_VB-42,   80,  560),
    (_MZ_VT+84,   _MZ_VB-84,  160,  480),
    (_MZ_VT+126,  _MZ_VB-126, 240,  400),
    (_MZ_VT+168,  _MZ_VB-168, 290,  350),
]
_MZ_WALL  = [(22,21,30),(44,42,56),(64,62,78),(80,77,95),(96,93,112)]
_MZ_CEIL  = [(4,4,12),(10,9,22),(14,13,28),(18,17,34),(22,21,40)]
_MZ_FLOR  = [(10,8,5),(24,19,12),(38,29,18),(50,39,26),(62,50,34)]


def _mz_poly_l(d): # left trapezoid
    t1,b1,l1,r1=_MZ_Z[d-1]; t2,b2,l2,r2=_MZ_Z[d]
    return [(l1,t1),(l2,t2),(l2,b2),(l1,b1)]
def _mz_poly_r(d): # right trapezoid
    t1,b1,l1,r1=_MZ_Z[d-1]; t2,b2,l2,r2=_MZ_Z[d]
    return [(r1,t1),(r2,t2),(r2,b2),(r1,b1)]
def _mz_poly_c(d): # ceiling
    t1,b1,l1,r1=_MZ_Z[d-1]; t2,b2,l2,r2=_MZ_Z[d]
    return [(l1,t1),(r1,t1),(r2,t2),(l2,t2)]
def _mz_poly_f(d): # floor
    t1,b1,l1,r1=_MZ_Z[d-1]; t2,b2,l2,r2=_MZ_Z[d]
    return [(l1,b1),(r1,b1),(r2,b2),(l2,b2)]


def _mz_stone_wall(d, x1, y1, x2, y2, col):
    try:
        from PIL import ImageDraw as _D
    except Exception:
        return
    _rng2 = random.Random(x1*7+y1*13+col[0])
    h = y2 - y1
    lines = []
    for _ in range(max(1, h//14)):
        lly = y1 + _rng2.randint(8, max(9,h-8))
        llx1 = x1 + _rng2.randint(0, max(1,(x2-x1)//4))
        llx2 = llx1 + _rng2.randint(max(1,(x2-x1)//5), max(2,(x2-x1)*3//4))
        lines.append((lly, llx1, llx2))
    return lines, col


def _mz_image_sync(scene: dict, player_info: dict,
                    event: str = "") -> Optional[bytes]:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return None

    W2, H2 = _MZ_W, _MZ_H
    img = Image.new("RGB", (W2, H2), (0,0,0))
    d   = ImageDraw.Draw(img)

    ahead = scene['ahead']
    left  = scene['left']
    right = scene['right']

    def is_wall(c): return c == 'W'
    def is_open(c): return c != 'W'

    # Visibility: can we see at depth d?
    vis = [True]
    for i in range(3):
        vis.append(vis[i] and is_open(ahead[i]))

    # ── Background ────────────────────────────────────
    d.rectangle([0, _MZ_VT, W2, _MZ_HORIZON], fill=_MZ_CEIL[0])
    d.rectangle([0, _MZ_HORIZON, W2, _MZ_VB],  fill=_MZ_FLOR[0])

    # ── Draw back → front ────────────────────────────
    for depth in range(3, 0, -1):
        if not vis[depth-1]:
            continue
        d.polygon(_mz_poly_c(depth), fill=_MZ_CEIL[depth])
        d.polygon(_mz_poly_f(depth), fill=_MZ_FLOR[depth])
        if left[depth-1]:
            d.polygon(_mz_poly_l(depth), fill=_MZ_WALL[depth])
        if right[depth-1]:
            d.polygon(_mz_poly_r(depth), fill=_MZ_WALL[depth])

    # ── Front walls and objects ───────────────────────
    for depth in range(1, 4):
        if not vis[depth-1]:
            break
        cell = ahead[depth-1]
        t2,b2,l2,r2 = _MZ_Z[depth]
        wc = _MZ_WALL[depth]
        cx = (l2+r2)//2

        if is_wall(cell):
            d.rectangle([l2,t2,r2,b2], fill=wc)
            # Stone texture lines
            rng2 = random.Random(l2*7+t2*13)
            h2 = b2-t2
            for _ in range(max(1, h2//14)):
                lly = t2+rng2.randint(8, max(9,h2-8))
                lx1 = l2+rng2.randint(0, max(1,(r2-l2)//4))
                lx2 = lx1+rng2.randint(max(1,(r2-l2)//5), max(2,(r2-l2)*3//4))
                d.line([(lx1,lly),(lx2,lly)],
                       fill=tuple(max(0,c2-15) for c2 in wc), width=1)
            d.line([(l2,t2),(l2,b2)], fill=tuple(min(255,c2+18) for c2 in wc), width=1)
            break

        elif cell == 'E':
            # Exit door
            dw = (r2-l2)//3; dh = (b2-t2)*2//3
            dx1=cx-dw//2; dx2=cx+dw//2
            dy1=_MZ_HORIZON-dh+dh//3; dy2=dy1+dh
            d.rectangle([l2,t2,r2,b2], fill=_MZ_CEIL[depth])  # back wall
            d.rectangle([dx1-4,dy1-4,dx2+4,dy2+4], fill=(55,38,18))   # frame
            d.rectangle([dx1,dy1,dx2,dy2], fill=(95,62,28))            # door
            for px2 in range(dx1+6, dx2-3, 10):
                d.line([(px2,dy1+4),(px2,dy2-4)], fill=(75,48,20), width=1)
            d.ellipse([cx+dw//5-3,_MZ_HORIZON-3,cx+dw//5+3,_MZ_HORIZON+3],fill=(200,165,45))
            for i in range(4,0,-1):
                g_col = (0,0,max(0,80-i*18))
                d.rectangle([dx1-i*2,dy1-i*2,dx2+i*2,dy2+i*2], outline=g_col, width=1)
            break

        elif cell == 'T':
            # Treasure chest
            cw2=(r2-l2)//4; ch2=(b2-t2)//4
            cy2=_MZ_HORIZON-ch2//2
            d.rectangle([l2,t2,r2,b2], fill=_MZ_CEIL[depth])
            d.rectangle([cx-cw2,cy2,cx+cw2,cy2+ch2], fill=(95,62,22))  # body
            d.rectangle([cx-cw2,cy2-ch2//4,cx+cw2,cy2], fill=(125,82,32))  # lid
            d.rectangle([cx-cw2,cy2-2,cx+cw2,cy2+2], fill=(175,155,45))   # band
            d.ellipse([cx-3,cy2-ch2//8-3,cx+3,cy2-ch2//8+3], fill=(200,175,55))
            # Sparkle
            for ang in [0, 90, 180, 270]:
                rad = math.radians(ang)
                sx, sy = cx+int(math.cos(rad)*8), cy2-ch2//4+int(math.sin(rad)*8)
                d.ellipse([sx-1,sy-1,sx+1,sy+1], fill=(255,240,100))
            break

        elif cell == 'P':
            # Pit
            d.rectangle([l2,t2,r2,b2], fill=_MZ_CEIL[depth])
            pw2 = (r2-l2)//3
            pts = [(cx-pw2,_MZ_HORIZON),(cx+pw2,_MZ_HORIZON),
                   (cx+pw2//2,b2-6),(cx-pw2//2,b2-6)]
            d.polygon(pts, fill=(5,3,8))
            d.polygon(pts, outline=(140,25,18), width=2)
            rng3 = random.Random(depth*77)
            for _ in range(4):
                llx = cx - pw2//2 + rng3.randint(0, pw2)
                d.line([(llx,_MZ_HORIZON),(llx-4,b2-10)], fill=(70,12,8), width=1)
            break

        elif cell == 'S':
            # Spikes
            d.rectangle([l2,t2,r2,b2], fill=_MZ_CEIL[depth])
            flo2 = b2-8
            n_sp = max(3, (r2-l2)//16)
            for si in range(n_sp):
                sx2 = l2 + (r2-l2)*si//n_sp + (r2-l2)//(2*n_sp)
                sh2 = 14 + (depth-1)*4
                d.polygon([(sx2-4,flo2),(sx2+4,flo2),(sx2,flo2-sh2)], fill=(170,170,195))
                d.line([(sx2,flo2),(sx2,flo2-sh2)], fill=(210,210,230), width=1)
            break

    # Depth-0 side walls (immediately beside player)
    if left[0]:  d.polygon(_mz_poly_l(1), fill=_MZ_WALL[1])
    if right[0]: d.polygon(_mz_poly_r(1), fill=_MZ_WALL[1])

    # ── HUD ──────────────────────────────────────────
    d.rectangle([0, 0, W2, _MZ_VT-2],    fill=(7,7,18))
    d.rectangle([0, _MZ_VB+2, W2, H2], fill=(7,7,18))
    d.line([(0,_MZ_VT-2),(W2,_MZ_VT-2)], fill=(38,36,52), width=1)
    d.line([(0,_MZ_VB+2),(W2,_MZ_VB+2)], fill=(38,36,52), width=1)

    pi = player_info or {}
    direction = pi.get('direction', 0)
    hp        = pi.get('hp', MAZE_HP_MAX)
    steps     = pi.get('steps', 0)
    chests    = pi.get('chests', 0)

    try:
        fb  = _cr_font(["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"], 16)
        fsm = _cr_font(["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"], 13)

        # Direction label
        dir_lbl = ['СЕВЕР','ВОСТОК','ЮГ','ЗАПАД'][direction]
        d.text((12, 16), dir_lbl, font=fb, fill=(190,182,225))

        # HP hearts
        for i in range(MAZE_HP_MAX):
            hc = (200,50,60) if i < hp else (48,32,48)
            d.text((W2-92+i*28, 16), 'HP' if i==0 else '', font=fsm, fill=(100,90,120))
            bbox = d.textbbox((0,0),'♥',font=fb)
            d.text((W2-72+i*28, 15), '♥', font=fb, fill=hc)

        # Bottom bar
        d.text((12, _MZ_VB+9), f'Шаг {steps}', font=fsm, fill=(140,130,165))
        if chests:
            d.text((150, _MZ_VB+9), f'Сундуков: {chests}', font=fsm, fill=(195,168,48))

        # Event overlay
        ev_map = {
            'blocked':  ('ПУТЬ ЗАКРЫТ',    (210,100,45)),
            'trap_pit': ('ЯМА! -1 ♥',      (220,55,55)),
            'trap_spk': ('ШИПЫ! -1 ♥',     (220,55,55)),
            'chest':    ('СОКРОВИЩЕ! +VRF', (195,168,48)),
            'win':      ('ВЫХОД! ПОБЕДА!',  (75,215,115)),
            'dead':     ('ВЫ ПОГИБЛИ...',   (215,38,38)),
            'back':     ('ШАГ НАЗАД',       (140,130,175)),
        }
        if event in ev_map:
            et, ec = ev_map[event]
            bbox = d.textbbox((0,0), et, font=fb)
            tw = bbox[2]-bbox[0]
            ey_pos = _MZ_HORIZON - 22
            d.rectangle([W2//2-tw//2-14, ey_pos-7, W2//2+tw//2+14, ey_pos+26],
                        fill=(0,0,0))
            d.rectangle([W2//2-tw//2-12, ey_pos-5, W2//2+tw//2+12, ey_pos+24],
                        outline=ec, width=2)
            d.text((W2//2-tw//2, ey_pos), et, font=fb, fill=ec)
    except Exception:
        pass

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


# ── Caption ───────────────────────────────────────────

def _mz_caption(game: dict, event: str = "") -> str:
    pi   = game
    hp   = pi['hp']
    step = pi['steps']
    bet  = pi['bet']
    chst = pi['chests']
    hp_s = '♥' * hp + '🖤' * (MAZE_HP_MAX - hp)
    dir_s = ['↑Север','→Восток','↓Юг','←Запад'][pi['direction']]

    ev_line = {
        'blocked':  '🧱 <b>Путь закрыт</b> — выбери другое направление',
        'trap_pit': '💀 <b>ЯМА!</b> Потеряно 1 сердце',
        'trap_spk': '⚔️ <b>ШИПЫ!</b> Потеряно 1 сердце',
        'chest':    '💎 <b>Сокровище найдено!</b> +VRF к награде',
        'back':     '↩️ Шаг назад',
        'win':      '🚪 <b>ВЫХОД НАЙДЕН!</b> Ты прошёл лабиринт!',
        'dead':     '💀 <b>ВЫ ПОГИБЛИ</b> — сердца закончились',
        '':         '🏰 Исследуй лабиринт и найди выход',
    }.get(event, '')

    return (
        f"🏰 <b>Лабиринт</b>  ·  {dir_s}  ·  {hp_s}\n"
        f"<code>Шаг {step}  ·  Ставка {fmt(bet)} VRF"
        + (f"  ·  Сундуки {chst}" if chst else "") + "</code>\n\n"
        + ev_line
    )


# ── Keyboard ──────────────────────────────────────────

def _mz_kb(uid: int, cid: int) -> InlineKeyboardMarkup:
    def b(lbl, act, style="primary"):
        return SBtn(lbl, style=style, callback_data=f"mz:{act}:{uid}:{cid}")
    return InlineKeyboardMarkup([
        [b("↑  Вперёд",  "F")],
        [b("← Повернуть","L"), b("Повернуть →","R")],
        [b("↓  Назад",   "B", "primary")],
        [b("🏳 Сдаться", "Q", "danger")],
    ])


def _mz_result_kb(cid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        SBtn("🔄 Новый лабиринт", style="success",
             callback_data=f"ra:maze:{cid}:0")
    ]])


# ── Game start / movement ─────────────────────────────

async def _mz_send(bot, game: dict, event: str = "") -> None:
    uid, cid = game['uid'], game['cid']
    scene = _mz_scene(game['grid'], game['px'], game['py'], game['direction'])
    pi = {k: game[k] for k in ('hp','steps','chests','direction')}
    loop = asyncio.get_running_loop()
    img  = await loop.run_in_executor(None, _mz_image_sync, scene, pi, event)
    cap  = _mz_caption(game, event)
    kb   = _mz_kb(uid, cid) if game['state'] == 'playing' else _mz_result_kb(cid)

    try:
        if game.get('msg_id'):
            if img:
                await bot.edit_message_media(
                    chat_id=cid, message_id=game['msg_id'],
                    media=InputMediaPhoto(media=io.BytesIO(img),
                                         caption=cap, parse_mode=ParseMode.HTML),
                    reply_markup=kb,
                )
            else:
                await bot.edit_message_caption(
                    chat_id=cid, message_id=game['msg_id'],
                    caption=cap, parse_mode=ParseMode.HTML, reply_markup=kb,
                )
        else:
            if img:
                msg = await bot.send_photo(
                    chat_id=cid, photo=io.BytesIO(img),
                    caption=cap, parse_mode=ParseMode.HTML, reply_markup=kb,
                )
            else:
                msg = await bot.send_message(
                    cid, cap, parse_mode=ParseMode.HTML, reply_markup=kb,
                )
            game['msg_id'] = msg.message_id
    except TelegramError:
        pass


async def _mz_end(bot, game: dict, won: bool) -> None:
    uid, cid = game['uid'], game['cid']
    bet      = game['bet']
    steps    = game['steps']
    chests   = game['chests']
    optimal  = game['optimal']
    key      = (uid, cid)

    if won:
        ratio = optimal / max(1, steps)
        mult  = next(m for r, m in MAZE_MULT if ratio >= r)
        chest_bonus = round(bet * MAZE_CHEST_PCT * chests)
        payout = round(bet * mult) + chest_bonus
        await db_add_vrf(uid, cid, payout)
        await db_add_xp(uid, cid, XP_PER_WIN)
        await db_record_game(uid, cid, won=True)

        rich_h = (
            f"<h2>🚪 Лабиринт — ПОБЕДА!</h2>"
            f"<table bordered striped>"
            f"<tr><td>💎 Ставка</td><td><b>{fmt(bet)} VRF</b></td></tr>"
            f"<tr><td>📍 Шагов</td><td>{steps} <i>(мин. {optimal})</i></td></tr>"
            f"<tr><td>💰 Множитель</td><td><b>x{mult:.1f}</b></td></tr>"
            f"<tr><td>🎁 Сундуков</td><td>{chests} <i>(+{fmt(chest_bonus)} VRF)</i></td></tr>"
            f"<tr><td>🏆 Итого</td><td><mark><b>+{fmt(payout)} VRF</b></mark></td></tr>"
            f"</table>"
        )
        fb_h = (
            f"🏆 <b>Лабиринт пройден!</b>\n"
            f"Шагов: {steps} · x{mult:.1f} · +{fmt(payout)} VRF"
        )
    else:
        await db_add_xp(uid, cid, XP_PER_GAME)
        await db_record_game(uid, cid, won=False)
        rich_h = (
            f"<h2>💀 Лабиринт — ПОРАЖЕНИЕ</h2>"
            f"<table bordered striped>"
            f"<tr><td>💎 Ставка</td><td><b>-{fmt(bet)} VRF</b></td></tr>"
            f"<tr><td>📍 Шагов</td><td>{steps}</td></tr>"
            f"<tr><td>🎁 Сундуков</td><td>{chests}</td></tr>"
            f"</table>"
        )
        fb_h = f"💀 <b>Погиб в лабиринте!</b>\n-{fmt(bet)} VRF"

    maze_games.pop(key, None)
    game['state'] = 'won' if won else 'dead'
    event = 'win' if won else 'dead'
    await _mz_send(bot, game, event)
    await send_rich(bot, cid, html=rich_h, fallback_html=fb_h,
                    reply_markup=_mz_result_kb(cid))


async def _mz_move(bot, game: dict, action: str) -> None:
    """Process one player action and update game state."""
    G    = len(game['grid'])
    px, py = game['px'], game['py']
    d    = game['direction']
    fx, fy = _MZ_FWD[d]
    event = ''

    if action == 'L':
        game['direction'] = _mz_turn_left(d)
        game['steps'] += 1
        event = ''

    elif action == 'R':
        game['direction'] = _mz_turn_right(d)
        game['steps'] += 1
        event = ''

    elif action == 'B':
        nx, ny = px - fx, py - fy
        if 0<=nx<G and 0<=ny<G and game['grid'][ny][nx] != 'W':
            game['px'], game['py'] = nx, ny
            game['steps'] += 1
            event = 'back'
        else:
            event = 'blocked'

    elif action == 'F':
        nx, ny = px + fx, py + fy
        if not (0<=nx<G and 0<=ny<G):
            event = 'blocked'
        else:
            cell = game['grid'][ny][nx]
            if cell == 'W':
                event = 'blocked'
            else:
                game['px'], game['py'] = nx, ny
                game['steps'] += 1
                game['visited'].add((nx, ny))

                if cell == 'E':
                    await _mz_end(bot, game, won=True)
                    return
                elif cell == 'P':
                    game['hp'] -= 1
                    game['grid'][ny][nx] = '.'   # pit remains but no respawn trap
                    event = 'trap_pit'
                elif cell == 'S':
                    game['hp'] -= 1
                    game['grid'][ny][nx] = '.'
                    event = 'trap_spk'
                elif cell == 'T':
                    game['chests'] += 1
                    game['grid'][ny][nx] = '.'
                    event = 'chest'

                if game['hp'] <= 0:
                    await _mz_end(bot, game, won=False)
                    return

    await _mz_send(bot, game, event)


# ── /maze command ─────────────────────────────────────

@only_groups
async def cmd_maze(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    u   = update.effective_user
    cid = update.effective_chat.id
    key = (u.id, cid)

    existing = maze_games.get(key)
    if existing and existing['state'] == 'playing':
        await update.message.reply_text(
            "🏰 Ты уже в лабиринте! Используй кнопки под картинкой.")
        return

    await db_ensure_user(u.id, cid, u.username or '', u.first_name)

    # Bet selection
    rows = [
        [SBtn(f"{a} VRF", style="primary",
              callback_data=f"mz:bet:{u.id}:{cid}:{a}")
         for a in MAZE_BET_PRESETS[:3]],
        [SBtn(f"{a} VRF", style="primary",
              callback_data=f"mz:bet:{u.id}:{cid}:{a}")
         for a in MAZE_BET_PRESETS[3:]],
    ]
    uu = await db_get_user(u.id, cid)
    bal = uu['vrf'] if uu else 0
    await update.message.reply_text(
        f"🏰 <b>Лабиринт</b>\n\n"
        f"Иди вперёд и выбирай путь. Впереди — мрак.\n"
        f"За каждым поворотом: ловушки, сокровища или выход.\n\n"
        f"💎 Баланс: <b>{fmt(bal)} VRF</b>\n"
        f"❤ Жизней: {MAZE_HP_MAX}\n\n"
        f"Выбери ставку:",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(rows),
    )


# ══════════════════════════════════════════════════════
#   MANAGED BOTS — клоны игрового бота для других чатов
# ══════════════════════════════════════════════════════
# Docs: Bot API 9.6 — KeyboardButtonRequestManagedBot,
#       ManagedBotCreated, getManagedBotToken
#
# Юзер пишет /create_bot → видит кнопку «Создать бота»
# → Telegram показывает диалог создания → родительский бот
# получает managed_bot_created → запрашивает токен через
# getManagedBotToken → запускает клона в отдельном потоке.

_managed_threads: dict = {}   # bot_user_id → threading.Thread
_child_bot_owners: dict = {}  # child_bot_uid → owner_user_id (for admin check)


# ── DB ────────────────────────────────────────────────

async def db_init_managed_bots() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS managed_bots (
                bot_user_id   INTEGER PRIMARY KEY,
                bot_token     TEXT    NOT NULL,
                bot_username  TEXT    DEFAULT '',
                bot_name      TEXT    DEFAULT '',
                owner_user_id INTEGER,
                welcome_text  TEXT    DEFAULT '',
                description   TEXT    DEFAULT '',
                active        INTEGER DEFAULT 1,
                created_at    TEXT
            )
        """)
        # migrate old table — add columns if missing
        for col, defval in [
            ("bot_name",     "''"),
            ("welcome_text", "''"),
            ("description",  "''"),
        ]:
            try:
                await db.execute(
                    f"ALTER TABLE managed_bots ADD COLUMN {col} TEXT DEFAULT {defval}"
                )
            except Exception:
                pass
        await db.commit()


async def _mb_save(bot_uid: int, token: str, username: str, owner_id: int,
                   bot_name: str = "") -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT OR REPLACE INTO managed_bots
               (bot_user_id, bot_token, bot_username, bot_name, owner_user_id, active, created_at)
               VALUES (?, ?, ?, ?, ?, 1, ?)""",
            (bot_uid, token, username, bot_name, owner_id, datetime.now().isoformat()),
        )
        await db.commit()
    # Make the bot owner a super-admin in the bot's admin table
    try:
        await db_add_admin(owner_id, "", "", added_by=0)
    except Exception:
        pass


async def _mb_update_settings(
    bot_uid: int,
    welcome_text: Optional[str] = None,
    description: Optional[str] = None,
    bot_name: Optional[str] = None,
) -> None:
    """Update editable fields for a managed bot."""
    fields, vals = [], []
    if welcome_text is not None:
        fields.append("welcome_text=?"); vals.append(welcome_text)
    if description is not None:
        fields.append("description=?"); vals.append(description)
    if bot_name is not None:
        fields.append("bot_name=?"); vals.append(bot_name)
    if not fields:
        return
    vals.append(bot_uid)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            f"UPDATE managed_bots SET {', '.join(fields)} WHERE bot_user_id=?",
            vals,
        )
        await db.commit()


async def _mb_get_settings(bot_uid: int) -> Optional[dict]:
    """Return all managed bot settings as dict."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM managed_bots WHERE bot_user_id=?", (bot_uid,)
        ) as cur:
            row = await cur.fetchone()
    return dict(row) if row else None


async def _mb_all() -> list:
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT bot_user_id, bot_token, bot_username, owner_user_id "
                "FROM managed_bots WHERE active=1"
            ) as cur:
                return await cur.fetchall()
    except Exception:
        return []


async def _mb_by_owner(owner_id: int) -> list:
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT bot_user_id, bot_username, created_at "
                "FROM managed_bots WHERE owner_user_id=? AND active=1",
                (owner_id,),
            ) as cur:
                return await cur.fetchall()
    except Exception:
        return []


# ── Token fetch via raw HTTP ──────────────────────────
# PTB may not yet expose getManagedBotToken as a method,
# so we call the Bot API directly.

async def _mb_get_token(bot_uid: int) -> Optional[str]:
    try:
        import aiohttp as _aio
        async with _aio.ClientSession() as s:
            async with s.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/getManagedBotToken",
                json={"user_id": bot_uid},
                timeout=_aio.ClientTimeout(total=10),
            ) as r:
                d = await r.json()
                if d.get("ok"):
                    return d["result"]
                log.warning("getManagedBotToken %s → %s", bot_uid, d.get("description"))
    except Exception:
        log.exception("getManagedBotToken failed for uid=%s", bot_uid)
    return None


# ── Handler registration (shared by parent + children) ─

def _register_handlers(app, is_child: bool = False) -> None:
    """Register all handlers on *app*. Children skip create_bot / my_bots."""

    # Global "last activity" tracker — считает и обычные сообщения, и любые
    # команды/нажатия кнопок как признак "пользователь онлайн" (нужно для
    # честной работы атак — иначе те, кто пишет только команды, всегда
    # выглядели бы офлайн). group=-1 — выполняется раньше всех остальных.
    app.add_handler(TypeHandler(Update, _touch_active_hook), group=-1)

    # Core
    app.add_handler(CommandHandler("start",    cmd_start))
    app.add_handler(CommandHandler("help",     cmd_help))
    app.add_handler(CommandHandler(["clan", "clans"], cmd_clan))

    # Profile / stats
    app.add_handler(CommandHandler("profile",  cmd_profile))
    app.add_handler(CommandHandler("statsimg", cmd_statsimg))
    app.add_handler(CommandHandler("activity", cmd_activity))
    app.add_handler(CommandHandler("top",      cmd_top))
    app.add_handler(CommandHandler(["leaderboard", "lb"], cmd_top))
    app.add_handler(CommandHandler("stats",    cmd_stats))
    app.add_handler(CommandHandler("daily",    cmd_daily))
    app.add_handler(CommandHandler("bonus",    cmd_bonus))
    app.add_handler(CommandHandler("ref",      cmd_ref))

    # Inline
    app.add_handler(InlineQueryHandler(on_inline_query))

    # Marriage
    app.add_handler(CommandHandler("marry",     cmd_marry))
    app.add_handler(CommandHandler("accept",    cmd_accept))
    app.add_handler(CommandHandler("reject",    cmd_reject))
    app.add_handler(CommandHandler("divorce",   cmd_divorce))
    app.add_handler(CommandHandler("marriage",  cmd_marriage))
    app.add_handler(CommandHandler("marriages", cmd_marriages))

    # Social
    app.add_handler(CommandHandler("gift",    cmd_gift))
    app.add_handler(CommandHandler("clicker", cmd_clicker))
    app.add_handler(CommandHandler("love",    cmd_love))

    # Games
    app.add_handler(CommandHandler("duel",      cmd_duel))
    app.add_handler(CommandHandler("cubes",     cmd_cubes))
    app.add_handler(CommandHandler("basket",    cmd_basket))
    app.add_handler(CommandHandler("football",  cmd_football))
    app.add_handler(CommandHandler("bowling",   cmd_bowling))
    app.add_handler(CommandHandler("darts",     cmd_darts))
    app.add_handler(CommandHandler("slot",      cmd_slot))
    app.add_handler(CommandHandler("mines",     cmd_mines))
    app.add_handler(CommandHandler(["tictac","ttt"], cmd_ttt))
    app.add_handler(CommandHandler("seabattle", cmd_seabattle))
    app.add_handler(CommandHandler("crash",     cmd_crash))
    app.add_handler(CommandHandler("tower",     cmd_tower))
    app.add_handler(CommandHandler("maze",      cmd_maze))
    app.add_handler(CommandHandler("giveaway",  cmd_giveaway))
    app.add_handler(CommandHandler("cancel",    cmd_cancel))

    # Admin
    app.add_handler(CommandHandler("admin",          cmd_admin))
    app.add_handler(CommandHandler("checkephemeral", cmd_checkephemeral))
    app.add_handler(CommandHandler("givevrf",      cmd_givevrf))
    app.add_handler(CommandHandler("takevrf",      cmd_takevrf))
    app.add_handler(CommandHandler("givebear",     cmd_givebear))
    app.add_handler(CommandHandler("takebear",     cmd_takebear))
    app.add_handler(CommandHandler("addadmin",     cmd_addadmin))
    app.add_handler(CommandHandler("removeadmin",  cmd_removeadmin))
    app.add_handler(CommandHandler("listadmins",   cmd_listadmins))

    # Moderation
    app.add_handler(CommandHandler(["mute",      "mut"],        cmd_mute))
    app.add_handler(CommandHandler(["unmute",    "unmut"],      cmd_unmute))
    app.add_handler(CommandHandler(["kick"],                    cmd_kick))
    app.add_handler(CommandHandler(["ban"],                     cmd_ban))
    app.add_handler(CommandHandler(["unban"],                   cmd_unban))
    app.add_handler(CommandHandler(["pred",      "warn"],       cmd_warn))
    app.add_handler(CommandHandler(["unpred",    "unwarn"],     cmd_unwarn))
    app.add_handler(CommandHandler(["clearpred", "clearwarns"], cmd_clearwarns))
    app.add_handler(CommandHandler(["predlist",  "warnlist"],   cmd_warnlist))
    app.add_handler(CommandHandler(["mutelist"],                cmd_mutelist))

    # ── Новые Bot API 10.x команды ────────────────────────
    app.add_handler(CommandHandler("chatinfo",     cmd_chatinfo))
    app.add_handler(CommandHandler("admins",       cmd_admins))
    app.add_handler(CommandHandler("clearreacts",  cmd_clearreacts))
    app.add_handler(CommandHandler("pin",          cmd_pin))
    app.add_handler(CommandHandler(["unpin", "unpinall"], cmd_unpin))
    app.add_handler(CommandHandler("setdesc",      cmd_setdesc))
    app.add_handler(CommandHandler("settitle",     cmd_settitle))
    app.add_handler(CommandHandler("react",        cmd_react))
    app.add_handler(CommandHandler("invite",       cmd_invite))
    app.add_handler(CommandHandler("botcaps",      cmd_botcaps))
    app.add_handler(CommandHandler(["fwd", "forward"], cmd_fwd))

    # Managed-bot commands (parent only — children don't spawn sub-bots)
    if not is_child:
        app.add_handler(CommandHandler("create_bot", cmd_create_bot))
        app.add_handler(CommandHandler("my_bots",    cmd_my_bots))
        app.add_handler(CommandHandler("link_bot",   cmd_link_bot))

    # Callbacks, messages & reactions
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageReactionHandler(on_reaction))
    app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, on_web_app_data))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))


# ── Child bot helpers ─────────────────────────────────

_CHILD_GAME_COMMANDS = [
    ("start",     "👋 Приветствие"),
    ("help",      "📖 Справка"),
    ("profile",   "👤 Профиль"),
    ("daily",     "⚡ Ежедневный бонус"),
    ("top",       "🏆 Топ игроков"),
    ("duel",      "⚔️ Дуэль"),
    ("cubes",     "🎲 Кубики"),
    ("slot",      "🎰 Слот"),
    ("mines",     "💣 Мины"),
    ("crash",     "🚀 Краш"),
    ("tower",     "🏢 Башня"),
    ("maze",      "🏰 Лабиринт"),
    ("basket",    "🏀 Баскетбол"),
    ("football",  "⚽ Футбол"),
    ("bowling",   "🎳 Боулинг"),
    ("darts",     "🎯 Дартс"),
    ("tictac",    "❌ Крестики-нолики"),
    ("seabattle", "🚢 Морской бой"),
    ("giveaway",  "🎁 Раздача"),
    ("marry",     "💍 Брак"),
    ("gift",      "🎀 Подарок"),
    ("ref",       "🔗 Реферальная ссылка"),
]

_CHILD_ADMIN_COMMANDS = [
    ("admin",       "🛠 Меню администратора"),
    ("addadmin",    "➕ Добавить администратора"),
    ("removeadmin", "➖ Убрать администратора"),
    ("givevrf",     "💎 Выдать VRF"),
    ("takevrf",     "💸 Забрать VRF"),
    ("mute",        "🔇 Мут"),
    ("unmute",      "🔊 Снять мут"),
    ("kick",        "👢 Кик"),
    ("ban",         "🚫 Бан"),
]


async def _setup_child_bot(bot, owner_id: int, bot_name: str = "", description: str = "") -> None:
    """Set commands, description and other profile settings for a child bot."""
    from telegram import BotCommand as _BC

    # Commands visible to all users
    user_cmds = [_BC(cmd, desc) for cmd, desc in _CHILD_GAME_COMMANDS]
    # Commands visible to admins in groups
    admin_cmds = user_cmds + [_BC(cmd, desc) for cmd, desc in _CHILD_ADMIN_COMMANDS]

    try:
        from telegram.constants import BotCommandScopeType
        from telegram import BotCommandScopeAllPrivateChats, BotCommandScopeAllGroupChats

        await bot.set_my_commands(user_cmds, scope=BotCommandScopeAllPrivateChats())
        await bot.set_my_commands(user_cmds, scope=BotCommandScopeAllGroupChats())
    except Exception:
        try:
            await bot.set_my_commands(user_cmds)
        except Exception as exc:
            log.warning("set_my_commands failed: %s", exc)

    # Set description with attribution
    me = await bot.get_me()
    parent_username = "VerifureGameBot"  # hardcoded parent username
    desc = description or (
        f"Игровой бот с VRF-валютой.\n"
        f"Создан через @{parent_username}\n\n"
        f"🎮 Дуэль · Кубики · Краш · Башня · Лабиринт · Мины · Слот"
    )
    try:
        await bot.set_my_short_description(f"Клон @{parent_username} с играми на VRF")
        await bot.set_my_description(desc)
    except Exception as exc:
        log.warning("set_my_description failed: %s", exc)

    log.info("Child bot @%s setup complete", me.username)


# ── Child bot runner ──────────────────────────────────

def _spawn_child(token: str, bot_uid: int, owner_id: int = 0) -> None:
    """Launch a cloned game-bot in a daemon thread (fire-and-forget)."""
    t = _managed_threads.get(bot_uid)
    if t and t.is_alive():
        return

    # Remember owner for admin checks
    if owner_id:
        _child_bot_owners[bot_uid] = owner_id

    def _thread() -> None:
        import asyncio as _aio
        from telegram.ext import Application as _App

        async def _run() -> None:
            try:
                child = _App.builder().token(token).post_init(on_startup).build()
                _register_handlers(child, is_child=True)
                async with child:
                    await child.start()
                    # Setup commands + description
                    oid = _child_bot_owners.get(bot_uid, owner_id)
                    settings = await _mb_get_settings(bot_uid)
                    desc = settings.get("description", "") if settings else ""
                    bname = settings.get("bot_name", "") if settings else ""
                    await _setup_child_bot(child.bot, oid, bname, desc)
                    log.info("Managed bot uid=%s online", bot_uid)
                    await child.updater.start_polling(
                        drop_pending_updates=True,
                        allowed_updates=[
                            "message", "callback_query", "inline_query",
                            "message_reaction", "chat_member", "my_chat_member",
                            "subscription",   # Bot API 10.2 — BotSubscriptionUpdated
                        ],
                    )
                    await _aio.Event().wait()
            except Exception as exc:
                log.exception("Managed bot uid=%s crashed: %s", bot_uid, exc)

        _aio.run(_run())

    t = threading.Thread(target=_thread, daemon=True, name=f"mb-{bot_uid}")
    t.start()
    _managed_threads[bot_uid] = t
    log.info("Spawned thread for managed bot uid=%s (owner=%s)", bot_uid, owner_id)


async def _spawn_child_safe(token: str, bot_uid: int, owner_id: int = 0,
                             wait: float = 4.0) -> Optional[str]:
    """Spawn child bot and wait to confirm it stays alive.
    Returns None on success, or an error string."""
    import asyncio as _aio
    _spawn_child(token, bot_uid, owner_id=owner_id)
    await _aio.sleep(wait)
    t = _managed_threads.get(bot_uid)
    if not t or not t.is_alive():
        return f"Поток завершился через {wait:.0f}с (возможно неверный токен или конфликт)"
    return None


# ── Managed-bot creation handler ──────────────────────

async def _finish_managed_bot_setup(
    bot,
    bot_uid: int,
    bot_username: str,
    owner_id: int,
    notify_chat_id: int,
) -> None:
    """Fetch token, save to DB, spawn child, notify owner."""
    token = await _mb_get_token(bot_uid)
    if not token:
        try:
            await bot.send_message(
                notify_chat_id,
                "❌ Не удалось получить токен.\n"
                "Убедись что у бота включено управление (@BotFather → Bot Settings → "
                "Allow Bots to Manage This Bot) и попробуй снова.",
                parse_mode=ParseMode.HTML,
            )
        except TelegramError:
            pass
        return

    await _mb_save(bot_uid, token, bot_username, owner_id)
    _spawn_child(token, bot_uid)

    uname_str = f"@{bot_username}" if bot_username else f"ID {bot_uid}"
    try:
        await bot.send_message(
            notify_chat_id,
            f"✅ <b>Бот запущен!</b>\n\n"
            f"🤖 {uname_str}\n\n"
            f"<b>Что делать дальше:</b>\n"
            f"1. Добавь <b>{uname_str}</b> в свою группу\n"
            f"2. Назначь его <b>администратором</b> (чтобы работала модерация)\n"
            f"3. Запускай игры: /duel /crash /tower /maze /mines и другие\n\n"
            f"Все игры, статистика и VRF — как здесь, но твои!",
            parse_mode=ParseMode.HTML,
            reply_markup=ReplyKeyboardRemove(),
        )
    except TelegramError:
        pass


async def on_managed_bot_msg(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the managed_bot_created service message (Bot API 9.6)."""
    msg = update.message
    if not msg:
        return

    owner_id = update.effective_user.id if update.effective_user else None
    chat_id  = update.effective_chat.id if update.effective_chat else owner_id

    # Try PTB attribute first; fall back to raw dict
    created = getattr(msg, "managed_bot_created", None)
    if created is not None:
        bot_info     = getattr(created, "bot", None)
        bot_uid      = getattr(bot_info, "id", None) if bot_info else None
        bot_username = getattr(bot_info, "username", "") if bot_info else ""
    else:
        raw  = update.to_dict().get("message", {})
        info = raw.get("managed_bot_created", {}).get("bot", {})
        bot_uid      = info.get("id")
        bot_username = info.get("username", "")

    if not bot_uid or not owner_id:
        return

    await context.bot.send_message(
        chat_id, "⚙️ Настраиваю бота...", parse_mode=ParseMode.HTML
    )
    await _finish_managed_bot_setup(
        context.bot, bot_uid, bot_username, owner_id, chat_id
    )


async def on_managed_bot_update(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle managed_bot Update (token replacement / owner change, Bot API 9.6)."""
    raw = update.to_dict()
    mb  = raw.get("managed_bot", {})
    if not mb:
        return

    bot_uid = mb.get("bot", {}).get("id")
    if not bot_uid:
        return

    # Token changed — re-fetch and restart child
    token = await _mb_get_token(bot_uid)
    if token:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE managed_bots SET bot_token=? WHERE bot_user_id=?",
                (token, bot_uid),
            )
            await db.commit()
        _spawn_child(token, bot_uid)
        log.info("Managed bot uid=%s token updated & respawned", bot_uid)


async def on_subscription_update(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка BotSubscriptionUpdated (Bot API 10.2) — изменение подписки
    пользователя на платные услуги бота. Поле update.subscription — новое,
    в текущей версии PTB типов может ещё не быть, поэтому читаем безопасно
    через сырой dict, как и для managed_bot выше."""
    sub = getattr(update, "subscription", None)
    if sub is None:
        raw = update.to_dict()
        sub = raw.get("subscription")
    if not sub:
        return
    try:
        log.info("BotSubscriptionUpdated: %s", sub)
    except Exception:
        pass
    # Точка расширения: здесь можно, например, начислять/снимать привилегии
    # пользователю в БД в зависимости от sub["status"] / sub["user"], когда
    # у бота появятся платные подписки.


# ── /create_bot  /my_bots ────────────────────────────

async def cmd_create_bot(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показывает меню создания клона бота с кнопками."""
    u   = update.effective_user
    msg = update.message

    existing = await _mb_by_owner(u.id)
    if existing:
        lines, kb_rows = [], []
        for uid, uname, _ in existing:
            alive  = uid in _managed_threads and _managed_threads[uid].is_alive()
            status = "🟢" if alive else "🔴"
            name   = f"@{uname}" if uname else f"ID {uid}"
            lines.append(f"{status} <b>{name}</b>")
            kb_rows.append([
                InlineKeyboardButton(
                    f"⚙️ Управлять {name}", callback_data=f"mb:manage:{uid}"
                )
            ])
        kb_rows.append([
            InlineKeyboardButton(
                "➕ Привязать ещё бота", callback_data="mb:add"
            )
        ])
        await msg.reply_text(
            "🤖 <b>Твои игровые боты:</b>\n\n" + "\n".join(lines) +
            "\n\nВыбери бота для управления или привяжи новый:",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(kb_rows),
        )
        return

    # Определяем username родительского бота
    me = context.bot.username or "VerifureGameBot"
    newbot_url = f"https://t.me/newbot/{me}"

    # Кнопки: нативный Telegram способ И ссылка на BotFather
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🤖 Создать бота через Telegram", url=newbot_url)],
        [InlineKeyboardButton("🔑 Привязать существующий бот", callback_data="mb:add")],
    ])

    # Попробуем также показать нативную Reply-кнопку (Bot API 9.6)
    try:
        from telegram import KeyboardButtonRequestManagedBot as _KBRMB
        reply_kb = ReplyKeyboardMarkup(
            [[KeyboardButton("🤖 Создать управляемый бот",
                             request_managed_bot=_KBRMB(request_id=1))]],
            resize_keyboard=True, one_time_keyboard=True,
        )
        await msg.reply_text(
            "🤖 <b>Создай своего игрового бота!</b>\n\n"
            "У тебя будет <b>полный клон</b> со всеми играми:\n"
            "🎲 Дуэль · Кубики · Спорт · Слот\n"
            "💥 Краш · 🏢 Башня · 🏰 Лабиринт · 💣 Мины\n"
            "🎁 Подарки · 💍 Браки · Статистика\n\n"
            "<b>Способы привязать бота:</b>\n\n"
            "1️⃣ Нажми кнопку «🤖 Создать управляемый бот» ниже — "
            "Telegram сам создаст бота и передаст его тебе\n\n"
            "2️⃣ Или используй инлайн-кнопку «Создать через Telegram»",
            parse_mode=ParseMode.HTML,
            reply_markup=reply_kb,
        )
        await msg.reply_text(
            "👆 Выбери способ создания или привяжи уже существующий бот:",
            reply_markup=kb,
        )
    except (ImportError, TypeError):
        # PTB без поддержки Bot API 9.6 — только URL кнопки
        await msg.reply_text(
            "🤖 <b>Создай своего игрового бота!</b>\n\n"
            "У тебя будет полный клон со всеми играми.\n\n"
            "<b>Инструкция:</b>\n"
            f"1. Нажми кнопку ниже — откроется @BotFather\n"
            f"2. Введи имя бота и @username\n"
            f"3. Скопируй токен вида <code>123456:ABC...</code>\n"
            f"4. Вставь его сюда: <code>/link_bot ТОКЕН</code>",
            parse_mode=ParseMode.HTML,
            reply_markup=kb,
        )


async def cmd_my_bots(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show the user's list of managed bots with live/dead status."""
    u    = update.effective_user
    bots = await _mb_by_owner(u.id)

    if not bots:
        await update.message.reply_text(
            "У тебя пока нет ботов.\n\n"
            "Используй /create_bot — получишь кнопку для создания бота через Telegram.\n"
            "Или привяжи готовый бот: /link_bot <b>ТОКЕН</b>",
            parse_mode=ParseMode.HTML,
        )
        return

    lines = []
    kb_rows = []
    for uid, uname, created_at in bots:
        alive  = uid in _managed_threads and _managed_threads[uid].is_alive()
        status = "🟢 работает" if alive else "🔴 остановлен"
        name   = f"@{uname}" if uname else f"ID {uid}"
        date   = created_at[:10] if created_at else "—"
        lines.append(f"• <b>{name}</b>  {status}\n  Создан: {date}")
        if not alive:
            kb_rows.append([SBtn(f"▶ Перезапустить {name}",
                                 style="primary",
                                 callback_data=f"mb:restart:{uid}")])
        kb_rows.append([SBtn(f"🗑 Удалить {name}",
                             style="danger",
                             callback_data=f"mb:delete:{uid}")])

    kb_rows.append([SBtn("➕ Привязать ещё", style="primary",
                         callback_data="mb:add")])

    await update.message.reply_text(
        "🤖 <b>Твои игровые боты:</b>\n\n" + "\n\n".join(lines) +
        "\n\nДобавь бота в группу и назначь его администратором.",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(kb_rows),
    )


async def cmd_link_bot(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Привязать бота вручную: /link_bot ТОКЕН

    Токен можно получить у @BotFather (/newbot → токен).
    Один владелец — один бот.
    """
    u   = update.effective_user
    msg = update.message

    # Проверяем: уже есть бот?
    existing = await _mb_by_owner(u.id)
    if existing:
        names = ", ".join(
            f"@{row[1]}" if row[1] else f"ID {row[0]}"
            for row in existing
        )
        await msg.reply_text(
            f"❌ У тебя уже привязан бот: {names}\n\n"
            "Используй /my_bots для управления.",
            parse_mode=ParseMode.HTML,
        )
        return

    # Извлекаем токен из аргументов
    args = context.args or []
    if not args:
        await msg.reply_text(
            "❌ Укажи токен бота.\n\n"
            "<b>Как получить токен:</b>\n"
            "1. Открой @BotFather\n"
            "2. Напиши /newbot\n"
            "3. Введи имя и @username нового бота\n"
            "4. Скопируй токен вида <code>123456:ABC...</code>\n\n"
            "Затем отправь: <code>/link_bot 123456:ABC...</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    token = args[0].strip()

    # Базовая проверка формата токена
    if ":" not in token or len(token) < 20:
        await msg.reply_text(
            "❌ Неверный формат токена.\n"
            "Токен выглядит так: <code>123456789:AAHdqTcvp...</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    # Удаляем сообщение с токеном из истории (приватность)
    try:
        await msg.delete()
    except TelegramError:
        pass

    status_msg = await update.effective_chat.send_message(
        "🔍 Проверяю токен...", parse_mode=ParseMode.HTML
    )

    # Проверяем токен через Bot API
    try:
        import aiohttp as _aio
        async with _aio.ClientSession() as s:
            async with s.get(
                f"https://api.telegram.org/bot{token}/getMe",
                timeout=_aio.ClientTimeout(total=15),
            ) as r:
                data = await r.json()
    except Exception as e:
        await status_msg.edit_text(
            f"❌ Не удалось подключиться к Telegram API: <code>{e}</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    if not data.get("ok"):
        err = data.get("description", "Unknown error")
        await status_msg.edit_text(
            f"❌ Токен не принят: <b>{err}</b>\n\n"
            "Проверь токен в @BotFather (/mybots → API Token).",
            parse_mode=ParseMode.HTML,
        )
        return

    bot_info     = data["result"]
    bot_uid      = bot_info["id"]
    bot_username = bot_info.get("username", "")
    bot_name     = bot_info.get("first_name", "")
    uname_str    = f"@{bot_username}" if bot_username else f"ID {bot_uid}"

    # Проверяем: этот бот уже в системе?
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT owner_user_id FROM managed_bots WHERE bot_user_id=? AND active=1",
            (bot_uid,)
        ) as cur:
            row = await cur.fetchone()
    if row:
        await status_msg.edit_text(
            f"❌ Бот {uname_str} уже привязан к другому аккаунту.",
            parse_mode=ParseMode.HTML,
        )
        return

    await status_msg.edit_text(
        f"✅ Токен принят: <b>{bot_name}</b> {uname_str}\n"
        "⚙️ Запускаю бота...",
        parse_mode=ParseMode.HTML,
    )

    # Сохраняем в БД и запускаем
    await _mb_save(bot_uid, token, bot_username, u.id, bot_name=bot_name)
    error = await _spawn_child_safe(token, bot_uid, owner_id=u.id)

    if error:
        await status_msg.edit_text(
            f"⚠️ Бот сохранён, но при запуске возникла ошибка:\n"
            f"<code>{error}</code>\n\n"
            f"Попробуй перезапустить через /my_bots.",
            parse_mode=ParseMode.HTML,
        )
        return

    await status_msg.edit_text(
        f"🎉 <b>Бот {uname_str} запущен!</b>\n\n"
        f"<b>Что делать дальше:</b>\n"
        f"1. Добавь <b>{uname_str}</b> в свою группу\n"
        f"2. Назначь его <b>администратором</b>\n"
        f"3. Ты <b>владелец</b> — тебе доступны /admin, /addadmin, /givevrf\n"
        f"4. Запускай: /duel /crash /tower /maze /mines /slot\n\n"
        f"📌 Атрибуция @VerifureGameBot будет в приветствии\n"
        f"⚙️ Управление — кнопка ниже или /my_bots",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton(
                f"⚙️ Управлять {uname_str}",
                callback_data=f"mb:manage:{bot_uid}"
            )
        ]]),
    )



# ══════════════════════════════════════════════════════
#   НОВЫЕ КОМАНДЫ — Bot API 10.x методы
# ══════════════════════════════════════════════════════

# ── /chatinfo — детальная инфо о чате (Rich Blocks + Community) ──

@only_groups
async def cmd_chatinfo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Детальная информация о чате (getChat + getChatMemberCount).
    Оформлена через Rich Blocks (Bot API 10.1) — структурированная таблица
    вместо HTML-разметки, плюс блок Community (Bot API 10.2), если чат
    состоит в сообществе."""
    cid = update.effective_chat.id
    try:
        chat = await context.bot.get_chat(cid)
        count = await context.bot.get_chat_member_count(cid)
    except TelegramError as e:
        await update.message.reply_text(f"❌ {e}")
        return

    rows = [
        [rich_table_cell("🆔 ID"), rich_table_cell(str(cid))],
        [rich_table_cell("👥 Участников"), rich_table_cell(str(count))],
        [rich_table_cell("📋 Тип"), rich_table_cell(chat.type)],
    ]
    if getattr(chat, "username", None):
        rows.append([rich_table_cell("🔗 Username"), rich_table_cell(f"@{chat.username}")])
    if getattr(chat, "invite_link", None):
        rows.append([rich_table_cell("🔒 Ссылка"), rich_table_cell(chat.invite_link)])
    if getattr(chat, "slow_mode_delay", None):
        rows.append([rich_table_cell("⏱ Медленный режим"), rich_table_cell(f"{chat.slow_mode_delay}с")])
    if getattr(chat, "has_aggressive_anti_spam_enabled", None):
        rows.append([rich_table_cell("🛡 Антиспам"), rich_table_cell("✅")])

    blocks = [
        rich_heading(chat.title or chat.first_name or "Чат", size=2),
        rich_table(rows, bordered=True, striped=True),
    ]
    if getattr(chat, "description", None):
        blocks.append(rich_paragraph(chat.description[:300]))

    # Community (Bot API 10.2) — несколько супергрупп/каналов/ботов под
    # одной темой. Поле может отсутствовать в старых версиях PTB/сервера,
    # поэтому читаем максимально защищённо.
    community = getattr(chat, "community", None)
    if community is not None:
        c_name = getattr(community, "title", None) or getattr(community, "name", None) or "—"
        blocks.append(rich_divider())
        blocks.append(rich_heading("🌐 Сообщество", size=3))
        blocks.append(rich_paragraph(f"Этот чат состоит в сообществе: {c_name}"))

    fb_lines = [
        f"💬 <b>{chat.title or chat.first_name or 'Чат'}</b>",
        f"🆔 ID: <code>{cid}</code>",
        f"👥 Участников: <b>{count}</b>",
        f"📋 Тип: {chat.type}",
    ]
    if getattr(chat, "username", None):
        fb_lines.append(f"🔗 @{chat.username}")
    if getattr(chat, "description", None):
        fb_lines.append(f"📝 {chat.description[:100]}")
    if community is not None:
        fb_lines.append("🌐 Состоит в сообществе")

    await send_rich(
        context.bot, cid, blocks=blocks, fallback_html="\n".join(fb_lines),
        reply_to_id=update.message.message_id,
    )



# ── /admins — список администраторов (Bot API 10.0 return_bots) ──

@only_groups
async def cmd_admins(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Список администраторов чата, включая ботов (Bot API 10.0)."""
    cid = update.effective_chat.id
    try:
        members = await context.bot.get_chat_administrators(cid, return_bots=True)
    except TypeError:
        # older PTB - no return_bots param
        members = await context.bot.get_chat_administrators(cid)
    except TelegramError as e:
        await update.message.reply_text(f"❌ {e}")
        return

    lines = ["👮 <b>Администраторы:</b>\n"]
    for m in members:
        u2 = m.user
        title = ""
        if m.status == "creator":
            title = "👑 Владелец"
        elif hasattr(m, "custom_title") and m.custom_title:
            title = f"🔹 {m.custom_title}"
        else:
            title = "🛡 Админ"
        bot_tag = " 🤖" if u2.is_bot else ""
        name = u2.first_name + (f" @{u2.username}" if u2.username else "")
        lines.append(f"{title}: <b>{name}</b>{bot_tag}")

    await update.message.reply_text(
        "\n".join(lines), parse_mode=ParseMode.HTML
    )


# ── /clearreacts — удалить все реакции (Bot API 10.0) ──

@only_groups
async def cmd_clearreacts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Удалить все реакции с указанного сообщения (ответом)."""
    if not await is_group_or_bot_admin(update):
        return
    reply = update.message.reply_to_message
    if not reply:
        await update.message.reply_text("❌ Ответь на сообщение, реакции которого нужно удалить.")
        return
    cid = update.effective_chat.id
    try:
        await context.bot.do_api_request(
            "deleteAllMessageReactions",
            api_kwargs={"chat_id": cid, "message_id": reply.message_id}
        )
        await update.message.reply_text("✅ Все реакции удалены.")
    except Exception as e:
        await update.message.reply_text(f"❌ {e}")


# ── /pin — закрепить сообщение ──────────────────────

@only_groups
async def cmd_pin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Закрепить сообщение (ответом). /pin [silent]"""
    if not await is_group_or_bot_admin(update):
        return
    reply = update.message.reply_to_message
    if not reply:
        await update.message.reply_text("❌ Ответь на сообщение, которое нужно закрепить.")
        return
    silent = bool(context.args and context.args[0].lower() == "silent")
    try:
        await context.bot.pin_chat_message(
            update.effective_chat.id,
            reply.message_id,
            disable_notification=silent,
        )
        await update.message.reply_text("📌 Закреплено!")
    except TelegramError as e:
        await update.message.reply_text(f"❌ {e}")


# ── /unpin — открепить ──────────────────────────────

@only_groups
async def cmd_unpin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Открепить последнее закреплённое сообщение. /unpinall — открепить все."""
    if not await is_group_or_bot_admin(update):
        return
    cid = update.effective_chat.id
    try:
        if context.args and context.args[0] == "all":
            await context.bot.unpin_all_chat_messages(cid)
            await update.message.reply_text("📌 Все сообщения откреплены.")
        else:
            await context.bot.unpin_chat_message(cid)
            await update.message.reply_text("📌 Откреплено.")
    except TelegramError as e:
        await update.message.reply_text(f"❌ {e}")


# ── /setdesc — изменить описание чата ──────────────

@only_groups
async def cmd_setdesc(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Изменить описание группы: /setdesc Новое описание"""
    if not await is_bot_admin(update.effective_user.id):
        return
    desc = " ".join(context.args or [])
    try:
        await context.bot.set_chat_description(update.effective_chat.id, desc or None)
        msg = "✅ Описание удалено." if not desc else f"✅ Описание обновлено:\n{desc}"
        await update.message.reply_text(msg)
    except TelegramError as e:
        await update.message.reply_text(f"❌ {e}")


# ── /settitle — изменить название чата ─────────────

@only_groups
async def cmd_settitle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Изменить название группы: /settitle Новое название"""
    if not await is_bot_admin(update.effective_user.id):
        return
    title = " ".join(context.args or [])
    if not title:
        await update.message.reply_text("❌ Укажи новое название: /settitle Название")
        return
    try:
        await context.bot.set_chat_title(update.effective_chat.id, title)
        await update.message.reply_text(f"✅ Название изменено на: <b>{title}</b>", parse_mode=ParseMode.HTML)
    except TelegramError as e:
        await update.message.reply_text(f"❌ {e}")


# ── /react — поставить реакцию на сообщение ────────

@only_groups
async def cmd_react(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Поставить реакцию ответом на сообщение: /react 👍"""
    reply = update.message.reply_to_message
    if not reply:
        await update.message.reply_text("❌ Ответь на сообщение.")
        return
    emoji = (context.args[0] if context.args else "👍").strip()
    try:
        await context.bot.set_message_reaction(
            update.effective_chat.id,
            reply.message_id,
            reaction=[{"type": "emoji", "emoji": emoji}],
        )
    except TelegramError as e:
        await update.message.reply_text(f"❌ {e}")


# ── /invite — создать пригласительную ссылку ──────

@only_groups
async def cmd_invite(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Создать новую пригласительную ссылку в чат."""
    if not await is_group_or_bot_admin(update):
        return
    cid = update.effective_chat.id
    try:
        link_obj = await context.bot.create_chat_invite_link(cid)
        await update.message.reply_text(
            f"🔗 <b>Новая ссылка для вступления:</b>\n{link_obj.invite_link}",
            parse_mode=ParseMode.HTML,
        )
    except TelegramError as e:
        await update.message.reply_text(f"❌ {e}")


# ── /botcaps — возможности бота (getMe) ─────────────

async def cmd_botcaps(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показывает возможности этого экземпляра бота."""
    me = await context.bot.get_me()
    caps = []
    if getattr(me, "can_join_groups",              False): caps.append("✅ Можно добавить в группы")
    if getattr(me, "can_read_all_group_messages",  False): caps.append("✅ Читает все сообщения")
    if getattr(me, "supports_inline_queries",       False): caps.append("✅ Инлайн-режим")
    if getattr(me, "can_connect_to_business",       False): caps.append("✅ Бизнес-аккаунты")
    if getattr(me, "has_main_web_app",              False): caps.append("✅ Главный Mini App")
    if getattr(me, "can_manage_bots",               False): caps.append("✅ Создание управляемых ботов")
    if getattr(me, "supports_guest_queries",        False): caps.append("✅ Гостевой режим (Bot API 10.0)")
    if getattr(me, "supports_join_request_queries", False): caps.append("✅ Обработка заявок вступления")

    await update.message.reply_text(
        f"🤖 <b>{me.first_name}</b> (@{me.username})\n"
        f"🆔 ID: <code>{me.id}</code>\n\n"
        "<b>Возможности:</b>\n" + ("\n".join(caps) if caps else "—"),
        parse_mode=ParseMode.HTML,
    )


# ── /forward — переслать сообщение в ЛС ────────────

@only_groups
async def cmd_fwd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Переслать ответное сообщение себе в ЛС: /fwd"""
    reply = update.message.reply_to_message
    if not reply:
        await update.message.reply_text("❌ Ответь на сообщение.")
        return
    uid = update.effective_user.id
    try:
        await context.bot.forward_message(
            chat_id=uid,
            from_chat_id=update.effective_chat.id,
            message_id=reply.message_id,
        )
        await update.message.reply_text("📨 Переслано в ЛС!")
    except TelegramError:
        await update.message.reply_text(
            "❌ Не могу переслать — сначала напиши мне в ЛС: "
            f"<a href=\"tg://user?id={uid}\">открыть ЛС</a>",
            parse_mode=ParseMode.HTML,
        )


# ── Callback: start:create_bot ──────────────────────
# Обрабатывается в on_callback через prefix "start:"


def main() -> None:
    if not BOT_TOKEN:
        log.critical("BOT_TOKEN environment variable is not set!")
        raise SystemExit(1)

    app = Application.builder().token(BOT_TOKEN).post_init(on_startup).build()

    # ── Register all handlers ──────────────────────────
    _register_handlers(app, is_child=False)

    # ── Service message: managed_bot_created ──────────
    # Filter for messages that contain managed_bot_created field.
    # PTB may not have a dedicated filter yet, so we use a custom one.
    try:
        from telegram.ext import filters as _f
        _mb_filter = _f.StatusUpdate.ALL  # broadest; handler checks inside
    except Exception:
        _mb_filter = filters.ALL

    app.add_handler(
        MessageHandler(
            _mb_filter,
            on_managed_bot_msg,
        ),
        group=99,   # low priority — runs after normal message handler
    )

    # ── Raw update for managed_bot (token change etc.) ─
    from telegram.ext import TypeHandler
    app.add_handler(TypeHandler(object, on_managed_bot_update), group=98)

    # ── Mini App web server ────────────────────────────
    if WEBAPP_URL or os.getenv("PORT"):
        t = threading.Thread(
            target=_run_clicker_webserver, daemon=True, name="webapp-server"
        )
        t.start()
        log.info("Mini App web server thread started")

    # ── Load & spawn previously-created managed bots ──
    async def _load_managed_bots(app2) -> None:
        await db_init_managed_bots()
        rows = await _mb_all()
        if rows:
            log.info("Loading %d managed bot(s)...", len(rows))
            for bot_uid, token, bot_uname, owner_id in rows:
                _child_bot_owners[bot_uid] = owner_id  # restore mapping
                _spawn_child(token, bot_uid, owner_id=owner_id)
        # Also init the table on first run
        pass

    app.post_init = _load_managed_bots   # override post_init to chain

    # Keep original on_startup:
    _orig_post_init = on_startup

    async def _combined_post_init(app2) -> None:
        await _orig_post_init(app2)
        await _load_managed_bots(app2)

    # Rebuild with combined post_init
    app2 = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(_combined_post_init)
        .build()
    )
    _register_handlers(app2, is_child=False)
    app2.add_handler(MessageHandler(_mb_filter, on_managed_bot_msg), group=99)
    app2.add_handler(TypeHandler(object, on_managed_bot_update),     group=98)
    app2.add_handler(TypeHandler(object, on_subscription_update),    group=97)

    if WEBAPP_URL or os.getenv("PORT"):
        threading.Thread(
            target=_run_clicker_webserver, daemon=True, name="webapp-server"
        ).start()

    log.info("Starting polling...")
    app2.run_polling(
        drop_pending_updates=True,
        allowed_updates=[
            "message",
            "callback_query",
            "inline_query",
            "message_reaction",
            "chat_member",
            "my_chat_member",
            "managed_bot",        # Bot API 9.6 — managed bot updates
            "subscription",       # Bot API 10.2 — BotSubscriptionUpdated
        ],
    )


if __name__ == "__main__":
    main()
