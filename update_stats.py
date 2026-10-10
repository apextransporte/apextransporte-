"""
Pulls the latest Apex Transporte stats from the Discord channel the
stats bot posts to, and writes data.json.

Reads two values from the environment (set as GitHub Actions secrets,
never hard-coded here):
  DISCORD_BOT_TOKEN
  DISCORD_STATS_CHANNEL_ID

It looks at the most recent messages in that channel, finds the
newest one with a "Net Worth" embed (the "[Apex] Apex Transporte"
card), and pulls the numbers out of its embed fields/description.
"""

import json
import os
import re
import sys
import datetime
import urllib.request

API = "https://discord.com/api/v10"


def discord_get(path, token):
    req = urllib.request.Request(
        API + path,
        headers={
            "Authorization": "Bot " + token,
            "User-Agent": "ApexStatsBot (https://github.com, 1.0)",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)


def grab(pattern, text):
    m = re.search(pattern, text)
    return m.group(1).strip() if m else None


def extract_stats(text):
    hours = grab(r"Time\s*:?\s*\*{0,2}([\d.,]+k?\s*Hours)", text)
    distance = grab(r"Distance\s*:?\s*\*{0,2}([\d.,]+k?\s*KMs)", text)
    return {
        "networth": grab(r"Net Worth\s*:?\s*\*{0,2}(\$[\d.,]+[MkK]?)", text),
        "drivers": grab(r"Drivers\s*:?\s*\*{0,2}(\d+)", text),
        "hours": hours.replace("Hours", "h").strip() if hours else None,
        "distance": distance.replace("KMs", "km").strip() if distance else None,
        "runs": grab(r"Runs\s*:?\s*\*{0,2}([\d,]+)", text),
        "latest_job": grab(r"Latest Job\s*[•·]?\s*([\d/]+,?\s*[\d:APM\s]+)", text),
    }


def main():
    token = os.environ.get("DISCORD_BOT_TOKEN")
    channel_id = os.environ.get("DISCORD_STATS_CHANNEL_ID")
    path = os.path.join(os.path.dirname(__file__), "data.json")

    if not token or not channel_id:
        print("Missing DISCORD_BOT_TOKEN or DISCORD_STATS_CHANNEL_ID, leaving data.json unchanged.")
        return

    try:
        messages = discord_get(f"/channels/{channel_id}/messages?limit=20", token)
    except Exception as e:
        print(f"Could not reach Discord: {e}")
        sys.exit(0)  # don't fail the whole workflow run over a hiccup

    stats = None
    for msg in messages:
        chunks = []
        for embed in msg.get("embeds", []):
            if embed.get("title"):
                chunks.append(embed["title"])
            if embed.get("description"):
                chunks.append(embed["description"])
            for f in embed.get("fields", []):
                chunks.append(f.get("name", "") + " " + f.get("value", ""))
        text = "\n".join(chunks) or msg.get("content", "")
        if "Net Worth" in text:
            stats = extract_stats(text)
            break

    if not stats or not any(stats.values()):
        print("No stats embed found in the last 20 messages, leaving data.json unchanged.")
        return

    existing = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            existing = json.load(f)

    merged = {**existing, **{k: v for k, v in stats.items() if v}}
    merged["checked"] = datetime.datetime.utcnow().strftime("%-d %B %Y")

    with open(path, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2)
        f.write("\n")

    print("data.json updated:", merged)


if __name__ == "__main__":
    main()
