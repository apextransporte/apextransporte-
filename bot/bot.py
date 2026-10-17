import datetime
import os
import re
import time
import unicodedata

import aiohttp
import discord
from aiohttp import web
from discord import app_commands
from discord.ext import tasks

TOKEN = os.getenv("TOKEN") or os.environ["DISCORD_BOT_TOKEN"]
DATA_URL = os.getenv(
    "APEX_DATA_URL",
    "https://apextransporte.github.io/data.json",
)
CACHE_SECONDS = 60
FETCH_TIMEOUT = 8

# If your apex_drivers.json uses other field names, change them here.
FIELDS = {
    "name": ["name", "driver", "username"],
    "level": ["level", "lvl"],
    "net_worth": ["net_worth", "networth", "netWorth"],
    "distance": ["distance", "distance_km", "distanceKm", "total_distance"],
    "income": ["income", "total_income"],
    "time": ["time", "driving_time", "total_time"],
    "jobs": ["jobs", "job_count", "job_log"],
}

RED = discord.Color.from_rgb(200, 16, 46)
LEADERBOARD_CHANNEL_ID = int(os.getenv("LEADERBOARD_CHANNEL_ID", "0"))

# Paste your direct logo link here, or set LOGO_URL in Render Environment.
LOGO_URL = os.getenv("LOGO_URL", "")
FOOTER = "Managed by Apex Transporte \u2022 For viewing global leaderboards, please use bot commands."

_cache = {"data": None, "time": 0.0}


def words(text):
    """Lower case words of a name, without Apex tags and symbols."""
    text = unicodedata.normalize("NFKC", str(text)).lower()
    found = re.split(r"[^\w]+", text)
    return [w for w in found if w and w not in ("apex", "the") and w != "_"]


def find_driver(drivers, query):
    """Find a driver by exact name, part of a name, or the words of a Discord name like Apex | keem."""
    q = str(query).strip().lower().lstrip("@")
    for d in drivers:
        if str(get(d, "name", "")).lower() == q:
            return d
    for d in drivers:
        if q and q in str(get(d, "name", "")).lower():
            return d
    qw = words(q)
    if qw:
        for d in drivers:
            dw = words(get(d, "name", ""))
            if dw and (all(w in dw for w in qw) or all(w in qw for w in dw)):
                return d
    return None


def get(driver, field, default=0):
    for key in FIELDS[field]:
        if key in driver and driver[key] not in (None, ""):
            return driver[key]
    return default


def num(value):
    if isinstance(value, (int, float)):
        return float(value)
    try:
        text = str(value).lower()
        for junk in (",", "km", "$", "\u20ac", " "):
            text = text.replace(junk, "")
        if text.endswith("m"):
            return float(text[:-1]) * 1_000_000
        if text.endswith("k"):
            return float(text[:-1]) * 1_000
        return float(text)
    except ValueError:
        return 0.0


def fmt(value):
    return f"{num(value):,.0f}"


def short(value):
    n = num(value)
    return f"{n / 1000:.1f}k" if n >= 1000 else f"{n:,.0f}"


def hours(value):
    """Turn 13918h 41m, 971 or 1.1k into hours as a number."""
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).lower()
    match = re.search(r"(\d[\d,]*)\s*h(?:\D+(\d+)\s*m)?", text)
    if match:
        return float(match.group(1).replace(",", "")) + float(match.group(2) or 0) / 60
    return num(value)


def fmt_time(total_hours):
    whole = int(total_hours)
    minutes = int(round((total_hours - whole) * 60))
    return f"{whole}h {minutes}m"


def job_count(value):
    if isinstance(value, list):
        return len(value)
    return int(num(value))


def style(embed):
    if LOGO_URL:
        embed.set_thumbnail(url=LOGO_URL)
    embed.set_footer(text=FOOTER)
    return embed


def board_embed(title, emoji, drivers, key, unit, daily=False):
    getter = (lambda d: hours(get(d, key))) if key == "time" else (lambda d: num(get(d, key)))
    ranked = sorted(drivers, key=getter, reverse=True)[:10]
    lines = [
        f"**#{i} {get(d, 'name', 'Unknown')}**\n{short(getter(d))} {unit}".rstrip()
        for i, d in enumerate(ranked, start=1)
    ]
    embed = discord.Embed(
        title=f"{emoji} {title}",
        description="\n\n".join(lines) or "No data yet.",
        color=RED,
    )
    embed.set_footer(text=FOOTER)
    return embed


async def load_drivers():
    """Return driver data. Uses a 60 second cache and falls back to old data on errors."""
    now = time.time()
    if _cache["data"] is not None and now - _cache["time"] < CACHE_SECONDS:
        return _cache["data"]

    # The changing query value skips the GitHub Pages cache so new job logs show up sooner.
    url = f"{DATA_URL}?t={int(now)}"
    try:
        timeout = aiohttp.ClientTimeout(total=FETCH_TIMEOUT)
        async with bot.session.get(url, timeout=timeout) as response:
            response.raise_for_status()
            data = await response.json(content_type=None)
    except Exception:
        if _cache["data"] is not None:
            return _cache["data"]
        raise

    if isinstance(data, dict):
        found = []
        for key in ("members", "drivers"):  # data.json also has a text field named drivers, so only a list counts
            if isinstance(data.get(key), list):
                found = data[key]
                break
        data = found
    data = [d for d in data if isinstance(d, dict)]
    _cache["data"] = data
    _cache["time"] = now
    return data


async def start_web_server():
    """Small web page so Render sees an open port. Ping it every 5 minutes to stop sleep."""
    app = web.Application()

    async def health(request):
        return web.Response(text="ok")

    app.router.add_get("/", health)
    app.router.add_get("/health", health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", int(os.getenv("PORT", "10000")))
    await site.start()


class ApexBot(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)
        self.session = None

    async def setup_hook(self):
        self.session = aiohttp.ClientSession()
        await start_web_server()
        await self.tree.sync()

    async def close(self):
        if self.session:
            await self.session.close()
        await super().close()


bot = ApexBot()

DATA_ERROR = "Apex data is not available right now. Try again in a minute."


@bot.tree.command(name="stats", description="Show Apex Transporte team stats")
async def stats(interaction: discord.Interaction):
    await interaction.response.defer()
    try:
        drivers = await load_drivers()
    except Exception:
        await interaction.followup.send(DATA_ERROR)
        return
    total_distance = sum(num(get(d, "distance")) for d in drivers)
    total_worth = sum(num(get(d, "net_worth")) for d in drivers)
    total_income = sum(num(get(d, "income")) for d in drivers)
    total_time = sum(hours(get(d, "time")) for d in drivers)
    total_jobs = sum(job_count(get(d, "jobs")) for d in drivers)

    embed = discord.Embed(title="\U0001F3E2 Apex Transporte", color=RED)
    rows = [
        ("\U0001F464 Active Drivers", f"{len(drivers):,}"),
        ("\U0001F4B0 Net Worth", f"${total_worth:,.0f}"),
        ("\U0001F4B5 Total Income", f"${total_income:,.0f}"),
        ("\U0001F6E3\uFE0F Total Distance", f"{total_distance:,.0f} km"),
        ("\u23F1\uFE0F Driving Time", fmt_time(total_time)),
        ("\U0001F69A Total Runs", f"{total_jobs:,}"),
    ]
    for name, value in rows:
        embed.add_field(name=name, value=value, inline=False)
    await interaction.followup.send(embed=style(embed))


@bot.tree.command(name="joblog", description="Show the job log for one driver")
@app_commands.describe(driver="Driver name")
async def joblog(interaction: discord.Interaction, driver: str):
    await interaction.response.defer()
    try:
        drivers = await load_drivers()
    except Exception:
        await interaction.followup.send(DATA_ERROR)
        return
    match = find_driver(drivers, driver)
    if match is None:
        await interaction.followup.send(f"No driver found named {driver}.")
        return

    embed = discord.Embed(title=str(get(match, "name", driver)), color=RED)
    embed.add_field(name="Level", value=fmt(get(match, "level")))
    embed.add_field(name="Net worth", value=fmt(get(match, "net_worth")))
    embed.add_field(name="Distance", value=f"{fmt(get(match, 'distance'))} km")
    embed.add_field(name="Income", value=fmt(get(match, "income")))
    embed.add_field(name="Driving time", value=str(get(match, "time", "n/a")))
    embed.add_field(name="Jobs", value=str(get(match, "jobs", "n/a")))
    await interaction.followup.send(embed=embed)


@bot.tree.command(name="leaderboard", description="Show the top 10 Apex drivers")
@app_commands.describe(category="What to rank by")
@app_commands.choices(
    category=[
        app_commands.Choice(name="Distance", value="distance"),
        app_commands.Choice(name="Level", value="level"),
        app_commands.Choice(name="Net worth", value="net_worth"),
        app_commands.Choice(name="Income", value="income"),
        app_commands.Choice(name="Driving time", value="time"),
    ]
)
async def leaderboard(
    interaction: discord.Interaction,
    category: app_commands.Choice[str] = None,
):
    await interaction.response.defer()
    key = category.value if category else "distance"
    label = category.name if category else "Distance"
    try:
        drivers = await load_drivers()
    except Exception:
        await interaction.followup.send(DATA_ERROR)
        return
    emojis = {"distance": "\U0001F6E3\uFE0F", "level": "\u2B50", "net_worth": "\U0001F4B0",
              "income": "\U0001F4B5", "time": "\u23F1\uFE0F"}
    units = {"distance": "KMs", "level": "", "net_worth": "", "income": "", "time": "Hours"}
    embed = board_embed(f"{label} Leaderboard [Apex]", emojis[key], drivers, key, units[key])
    await interaction.followup.send(embed=embed)


@tasks.loop(time=datetime.time(hour=22, minute=25, tzinfo=datetime.timezone.utc))
async def post_leaderboard():
    channel = bot.get_channel(LEADERBOARD_CHANNEL_ID)
    if channel is None:
        return
    try:
        drivers = await load_drivers()
    except Exception:
        return
    embed = board_embed("Distance Leaderboard [Apex]", "\U0001F6E3\uFE0F", drivers, "distance", "KMs")
    await channel.send(embed=embed)


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error):
    """Always answer the user, and write the real error to the Render logs."""
    print(f"Command error: {error!r}", flush=True)
    message = "Something went wrong. Please try again in a minute."
    try:
        if interaction.response.is_done():
            await interaction.followup.send(message)
        else:
            await interaction.response.send_message(message)
    except Exception:
        pass


@bot.event
async def on_ready():
    if not post_leaderboard.is_running():
        post_leaderboard.start()


bot.run(TOKEN)
