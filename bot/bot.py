import os
import time

import aiohttp
import discord
from aiohttp import web
from discord import app_commands
import datetime
from discord.ext import tasks

TOKEN = os.getenv("TOKEN") or os.environ["DISCORD_BOT_TOKEN"]
DATA_URL = os.getenv(
    "APEX_DATA_URL",
    "https://apextransporte.github.io/apextransporte-/apex_drivers.json",
)
CACHE_SECONDS = 60
FETCH_TIMEOUT = 8

# If your apex_drivers.json uses other field names, change them here.
FIELDS = {
    "name": ["name", "driver", "username"],
    "level": ["level", "lvl"],
    "net_worth": ["net_worth", "networth", "netWorth"],
    "distance": ["distance", "distance_km", "total_distance"],
    "income": ["income", "total_income"],
    "time": ["time", "driving_time", "total_time"],
    "jobs": ["jobs", "job_count", "job_log"],
}

RED = discord.Color.from_rgb(200, 16, 46)
LEADERBOARD_CHANNEL_ID = int(os.getenv("LEADERBOARD_CHANNEL_ID", "0"))

_cache = {"data": None, "time": 0.0}


def get(driver, field, default=0):
    for key in FIELDS[field]:
        if key in driver and driver[key] not in (None, ""):
            return driver[key]
    return default


def num(value):
    if isinstance(value, (int, float)):
        return float(value)
    try:
        text = str(value).lower().replace(",", "").replace("km", "").strip()
