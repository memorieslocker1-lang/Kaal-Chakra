# Create project files for a secure, free & open-source Telegram Natal Chart bot.
# We'll package them into a ZIP the user can download.

import os, textwrap, zipfile, json, pathlib

project_dir = "/mnt/data/natal_chart_bot_secure"
os.makedirs(project_dir, exist_ok=True)

app_py = r'''"""
Natal Chart Telegram Bot — Free & Open-Source Calculations Only
===============================================================

• Collects birth date, time, and place (city).
• Geocodes with OpenStreetMap (Nominatim) — free, no key.
• Detects time zone with timezonefinder (local lib) and converts local time → UTC.
• Computes natal chart via flatlib (Swiss Ephemeris, open-source only):
  Sun, Moon, Mercury, Venus, Mars, Jupiter, Saturn, Uranus, Neptune, Pluto,
  Ascendant (ASC), Midheaven (MC), Houses (Placidus), Major aspects.
• No paid APIs. No external astrology services.

SECURITY: Set your BOT_TOKEN as an environment variable. Do NOT hardcode it.
"""

import os
import re
from datetime import datetime
from typing import Optional, Tuple, List

import pytz
from geopy.geocoders import Nominatim
from timezonefinder import TimezoneFinder

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# Astrology libs
from flatlib.chart import Chart
from flatlib import const
from flatlib.geopos import GeoPos
from flatlib.datetime import Datetime
from flatlib.aspects import getAspect

# --------------------
# Config
# --------------------
BOT_TOKEN = os.environ.get("BOT_TOKEN")  # <-- set this in your environment
NOMINATIM_EMAIL = os.environ.get("NOMINATIM_EMAIL", "your-email@example.com")

DATE, TIME, PLACE, CONFIRM = range(4)

PLANETS = [
    const.SUN, const.MOON, const.MERCURY, const.VENUS, const.MARS,
    const.JUPITER, const.SATURN, const.URANUS, const.NEPTUNE, const.PLUTO
]
POINTS = PLANETS + [const.ASC, const.MC]
MAJOR_ASPECTS = [const.CONJUNCTION, const.SEXTILE, const.SQUARE, const.TRINE, const.OPPOSITION]
ASPECT_ORB = 6  # degrees

geocoder = Nominatim(user_agent=f"NatalChartBot/1.0 ({NOMINATIM_EMAIL})")
tf = TimezoneFinder()
geo_cache = {}  # simple memory cache

# --------------------
# Helpers
# --------------------
def parse_date(text: str) -> Optional[datetime]:
    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text.strip(), fmt)
        except Exception:
            pass
    return None

def parse_time(text: str) -> Optional[Tuple[int, int]]:
    m = re.match(r"^(\\d{1,2}):(\\d{2})$", text.strip())
    if not m:
        return None
    h, mnt = int(m.group(1)), int(m.group(2))
    if 0 <= h <= 23 and 0 <= mnt <= 59:
        return h, mnt
    return None

def geocode_place(place: str):
    key = place.lower().strip()
    if key in geo_cache:
        return geo_cache[key]
    loc = geocoder.geocode(place, timeout=12)
    if not loc:
        return None
    lat, lon, addr = float(loc.latitude), float(loc.longitude), loc.address
    tzname = tf.timezone_at(lat=lat, lng=lon) or tf.closest_timezone_at(lat=lat, lng=lon)
    if not tzname:
        return None
    geo_cache[key] = (lat, lon, addr, tzname)
    return geo_cache[key]

def to_utc_iso(date_obj: datetime, hour: int, minute: int, tzname: str) -> str:
    local = pytz.timezone(tzname)
    local_dt = local.localize(datetime(date_obj.year, date_obj.month, date_obj.day, hour, minute))
    utc_dt = local_dt.astimezone(pytz.utc)
    return utc_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

def fmt_deg(d: float) -> str:
    deg = int(d)
    minutes = int((d - deg) * 60)
    return f"{deg}°{minutes:02d}'"

def compute_chart(utc_iso: str, lat: float, lon: float) -> Chart:
    dt = datetime.fromisoformat(utc_iso.replace("Z", "+00:00"))
    flat_dt = Datetime(dt.strftime("%Y/%m/%d"), dt.strftime("%H:%M"), "UTC")
    gp = GeoPos(lat, lon)
    return Chart(flat_dt, gp, IDs=POINTS, hsys=const.HOUSES_PLACIDUS)

def summarize_points(chart: Chart) -> List[str]:
    lines = []
    for pid in POINTS:
        obj = chart.get(pid)
        sign = obj.sign.capitalize()
        degree = fmt_deg(obj.signlon)
        house = getattr(obj, 'house', None)
        hnum = getattr(house, 'num', None) if house else None
        label = pid.capitalize()
        htxt = f" — House {hnum}" if hnum else ""
        lines.append(f"• *{label}*: {sign} @ {degree}{htxt}")
    return lines

def summarize_aspects(chart: Chart) -> List[str]:
    pts = [chart.get(p) for p in PLANETS]
    out = []
    for i in range(len(pts)):
        for j in range(i+1, len(pts)):
            asp = getAspect(pts[i], pts[j])
            if asp and asp.type in MAJOR_ASPECTS and abs(asp.orb) <= ASPECT_ORB:
                out.append(f"• {pts[i].id.capitalize()} {asp.type.capitalize()} {pts[j].id.capitalize()} (orb {abs(asp.orb):.2f}°)")
    return out

# --------------------
# Bot flow
# --------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🌟 Welcome to *Natal Chart Bot*!\\n"
        "I'll build your chart using only free, open-source tools.\\n\\n"
        "Send your birth date in *DD-MM-YYYY* (e.g., 07-09-1998).",
        parse_mode=ParseMode.MARKDOWN,
    )
    return DATE

async def on_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    d = parse_date(update.message.text)
    if not d:
        await update.message.reply_text("❌ Invalid date format. Please send as DD-MM-YYYY.")
        return DATE
    context.user_data["date"] = d
    await update.message.reply_text("⏰ Now send your birth time in 24h *HH:MM* (e.g., 14:35).", parse_mode=ParseMode.MARKDOWN)
    return TIME

async def on_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t = parse_time(update.message.text)
    if not t:
        await update.message.reply_text("❌ Invalid time. Please send as HH:MM (00–23:59).")
        return TIME
    context.user_data["time"] = t
    await update.message.reply_text("📍 Finally, send your *birth place* in the form *City, Country*.", parse_mode=ParseMode.MARKDOWN)
    return PLACE

async def on_place(update: Update, context: ContextTypes.DEFAULT_TYPE):
    place = update.message.text.strip()
    geo = geocode_place(place)
    if not geo:
        await update.message.reply_text("❌ Couldn't find that place or its timezone. Try `City, Country`.", parse_mode=ParseMode.MARKDOWN)
        return PLACE
    lat, lon, addr, tzname = geo

    d: datetime = context.user_data["date"]
    h, m = context.user_data["time"]

    summary = (
        "Please confirm your details:\\n\\n"
        f"• Date: *{d.strftime('%d-%m-%Y')}*\\n"
        f"• Time: *{h:02d}:{m:02d}*\\n"
        f"• Place: *{addr}*\\n"
        f"• Time Zone: *{tzname}*\\n\\n"
        "Proceed?"
    )
    context.user_data.update({"lat": lat, "lon": lon, "addr": addr, "tz": tzname})
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Yes", callback_data="ok"), InlineKeyboardButton("✏️ Edit", callback_data="edit")]])
    await update.message.reply_text(summary, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)
    return CONFIRM

async def on_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "edit":
        await query.edit_message_text("Okay, let's start over. Send your birth *date* (DD-MM-YYYY).", parse_mode=ParseMode.MARKDOWN)
        return DATE

    d: datetime = context.user_data["date"]
    h, m = context.user_data["time"]
    lat, lon, tzname = context.user_data["lat"], context.user_data["lon"], context.user_data["tz"]

    utc_iso = to_utc_iso(d, h, m, tzname)
    chart = compute_chart(utc_iso, lat, lon)

    sun, moon, asc = chart.get(const.SUN), chart.get(const.MOON), chart.get(const.ASC)
    header = (f"✨ *Sun* in *{sun.sign.capitalize()}*  |  "
              f"🌙 *Moon* in *{moon.sign.capitalize()}*  |  "
              f"⬆️ *Rising* in *{asc.sign.capitalize()}*")

    points_block = "\\n".join(summarize_points(chart))
    aspects_list = summarize_aspects(chart)
    aspects_block = "\\n".join(aspects_list) if aspects_list else "_No major aspects within 6° orb_."

    text = (
        f"🗺️ *Your Natal Chart*\\n"
        f"{header}\\n\\n"
        f"*Planets & Points* (sign @ degree — house):\\n{points_block}\\n\\n"
        f"*Major Aspects*:\\n{aspects_block}"
    )

    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)
    return ConversationHandler.END

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Commands:\\n"
        "/start — Enter birth details and generate your chart\\n"
        "/help — This help"
    )

def main():
    if not BOT_TOKEN:
        raise SystemExit("BOT_TOKEN environment variable is not set. Please set it before running.")
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, on_date)],
            TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, on_time)],
            PLACE: [MessageHandler(filters.TEXT & ~filters.COMMAND, on_place)],
            CONFIRM: [CallbackQueryHandler(on_confirm)],
        },
        fallbacks=[CommandHandler("help", help_cmd)],
    )

    app.add_handler(conv)
    app.add_handler(CommandHandler("help", help_cmd))

    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
'''

requirements_txt = """python-telegram-bot==21.6
flatlib==0.2.9
geopy>=2.4.1
pytz>=2024.1
timezonefinder>=6.5.2
"""

