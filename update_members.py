import json
import os
import sys
import time

import requests

API = "https://discord.com/api/v10"

TOKEN = os.environ.get("DISCORD_BOT_TOKEN")
GUILD_ID = os.environ.get("DISCORD_GUILD_ID")
OFFICIAL_ROLE_ID = os.environ.get("OFFICIAL_ROLE_ID")
VISITOR_ROLE_ID = os.environ.get("VISITOR_ROLE_ID")

missing = [
    name
    for name, value in [
        ("DISCORD_BOT_TOKEN", TOKEN),
        ("DISCORD_GUILD_ID", GUILD_ID),
        ("OFFICIAL_ROLE_ID", OFFICIAL_ROLE_ID),
        ("VISITOR_ROLE_ID", VISITOR_ROLE_ID),
    ]
    if not value
]
if missing:
    sys.exit("Missing secrets: " + ", ".join(missing))

HEADERS = {"Authorization": "Bot " + TOKEN}


def get_json(url, params=None):
    for _ in range(5):
        r = requests.get(url, headers=HEADERS, params=params, timeout=30)
        if r.status_code == 429:
            wait = float(r.json().get("retry_after", 1))
            time.sleep(wait + 0.5)
            continue
        if r.status_code == 403:
            sys.exit(
                "403 from Discord. Turn on Server Members Intent in the "
                "Developer Portal and check the bot is in the server."
            )
        r.raise_for_status()
        return r.json()
    sys.exit("Discord rate limit did not clear. Try again later.")


def fetch_all_members():
    members = []
    after = "0"
    while True:
        batch = get_json(
            f"{API}/guilds/{GUILD_ID}/members",
            params={"limit": 1000, "after": after},
        )
        if not batch:
            break
        members.extend(batch)
        after = batch[-1]["user"]["id"]
        if len(batch) < 1000:
            break
    return members


def display_name(m):
    user = m["user"]
    return m.get("nick") or user.get("global_name") or user["username"]


def avatar_url(m):
    user = m["user"]
    if user.get("avatar"):
        return f"https://cdn.discordapp.com/avatars/{user['id']}/{user['avatar']}.png?size=128"
    return None


def main():
    official = []
    visitors = []

    for m in fetch_all_members():
        if m["user"].get("bot"):
            continue
        entry = {
            "id": m["user"]["id"],
            "name": display_name(m),
            "avatar": avatar_url(m),
            "joined": m.get("joined_at"),
        }
        roles = m["roles"]
        if OFFICIAL_ROLE_ID in roles:
            official.append(entry)
        elif VISITOR_ROLE_ID in roles:
            visitors.append(entry)

    official.sort(key=lambda e: e["name"].lower())
    visitors.sort(key=lambda e: e["name"].lower())

    data = {
        "member_count": len(official),
        "visitor_count": len(visitors),
        "members": official,
        "visitors": visitors,
    }

    with open("members.json", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"Official members: {len(official)}")
    print(f"Visitors: {len(visitors)}")


if __name__ == "__main__":
    main()
