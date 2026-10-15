import os

import aiohttp
import discord
from discord import app_commands

TOKEN = os.environ["DISCORD_BOT_TOKEN"]
DATA_URL = os.getenv(
    "APEX_DATA_URL",
    "https://apextransporte.github.io/apextransporte-/apex_drivers.json",
)

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
        if text.endswith("m"):
            return float(text[:-1]) * 1_000_000
        if text.endswith("k"):
            return float(text[:-1]) * 1_000
        return float(text)
    except ValueError:
        return 0.0


def fmt(value):
    return f"{num(value):,.0f}"


async def load_drivers():
    async with aiohttp.ClientSession() as session:
        async with session.get(DATA_URL) as response:
            response.raise_for_status()
            data = await response.json(content_type=None)
    if isinstance(data, dict):
        data = data.get("drivers") or data.get("members") or []
    return data


class ApexBot(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        await self.tree.sync()


bot = ApexBot()


@bot.tree.command(name="stats", description="Show Apex Transporte team stats")
async def stats(interaction: discord.Interaction):
    await interaction.response.defer()
    drivers = await load_drivers()
    total_distance = sum(num(get(d, "distance")) for d in drivers)
    total_worth = sum(num(get(d, "net_worth")) for d in drivers)
    top = max(drivers, key=lambda d: num(get(d, "distance")), default=None)

    embed = discord.Embed(title="Apex Transporte Stats", color=RED)
    embed.add_field(name="Drivers", value=str(len(drivers)))
    embed.add_field(name="Total distance", value=f"{total_distance:,.0f} km")
    embed.add_field(name="Total net worth", value=f"{total_worth:,.0f}")
    if top:
        embed.add_field(
            name="Top driver by distance",
            value=f"{get(top, 'name', 'Unknown')} ({fmt(get(top, 'distance'))} km)",
            inline=False,
        )
    await interaction.followup.send(embed=embed)


@bot.tree.command(name="joblog", description="Show the job log for one driver")
@app_commands.describe(driver="Driver name")
async def joblog(interaction: discord.Interaction, driver: str):
    await interaction.response.defer()
    drivers = await load_drivers()
    match = next(
        (d for d in drivers if str(get(d, "name", "")).lower() == driver.lower()),
        None,
    )
    if match is None:
        match = next(
            (d for d in drivers if driver.lower() in str(get(d, "name", "")).lower()),
            None,
        )
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
    ]
)
async def leaderboard(
    interaction: discord.Interaction,
    category: app_commands.Choice[str] = None,
):
    await interaction.response.defer()
    key = category.value if category else "distance"
    label = category.name if category else "Distance"
    drivers = await load_drivers()
    ranked = sorted(drivers, key=lambda d: num(get(d, key)), reverse=True)[:10]

    lines = [
        f"{i}. {get(d, 'name', 'Unknown')} - {fmt(get(d, key))}"
        for i, d in enumerate(ranked, start=1)
    ]
    embed = discord.Embed(
        title=f"Top 10 by {label}",
        description="\n".join(lines) or "No data yet.",
        color=RED,
    )
    await interaction.followup.send(embed=embed)


bot.run(TOKEN)
