"""Posts the daily Top 10 drivers by distance to the Discord leaderboard channel.

The webhook address comes from the LEADERBOARD_WEBHOOK secret. Without it the
script only prints the message, so it is safe to test.
"""
import datetime
import json
import os
import re
import sys
import time

import requests

DATA_FILE = "data.json"
RED = 0xC8102E


def num(value):
    """Turn text like '198,301 km' or '$6.2M' into a number."""
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).lower()
    for junk in (",", "km", "$", "\u20ac", " "):
        text = text.replace(junk, "")
    try:
        if text.endswith("m"):
            return float(text[:-1]) * 1_000_000
        if text.endswith("k"):
            return float(text[:-1]) * 1_000
        return float(text)
    except ValueError:
        return 0.0


def clean_name(name):
    name = re.sub(r"^\s*apex\s*[|\u2503]\s*", "", str(name), flags=re.IGNORECASE)
    return name.strip() or "Unknown"


def build_message():
    with open(DATA_FILE, encoding="utf-8") as f:
        members = json.load(f).get("members", [])
    members = [m for m in members if isinstance(m, dict)]
    ranked = sorted(members, key=lambda m: num(m.get("distance")), reverse=True)
    ranked = [m for m in ranked if num(m.get("distance")) > 0][:10]
    if not ranked:
        sys.exit("No driver data found. Nothing was posted.")
    medals = {1: "\U0001F947", 2: "\U0001F948", 3: "\U0001F949"}
    lines = []
    for i, m in enumerate(ranked, start=1):
        lines.append(
            "{} {} - {:,.0f} km".format(medals.get(i, f"{i}."), clean_name(m.get("name")), num(m.get("distance")))
        )
    today = datetime.datetime.now(datetime.timezone.utc).strftime("%d %b %Y")
    return {
        "username": "Apex Data",
        "embeds": [
            {
                "title": "Daily Top 10 by Distance",
                "description": "\n".join(lines),
                "color": RED,
                "footer": {"text": f"Apex Transporte - {today}"},
            }
        ],
    }


def main():
    message = build_message()
    url = os.getenv("LEADERBOARD_WEBHOOK", "").strip()
    if not url:
        print("LEADERBOARD_WEBHOOK is not set. Message preview:")
        print(message["embeds"][0]["description"])
        return
    for attempt in range(3):
        response = requests.post(url, json=message, timeout=20)
        if response.status_code == 429:
            wait = 5
            try:
                wait = float(response.json().get("retry_after", 5))
            except Exception:
                pass
            time.sleep(min(wait, 30))
            continue
        if response.status_code in (200, 204):
            print("Leaderboard posted.")
            return
        sys.exit(f"Discord refused the post. Status {response.status_code}.")
    sys.exit("Discord kept rate limiting the post. Try again later.")


if __name__ == "__main__":
    main()
