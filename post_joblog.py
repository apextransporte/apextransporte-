import os
import requests

API = "https://discord.com/api/v10"


def send_joblog(job):
    token = os.environ["DISCORD_BOT_TOKEN"]
    channel_id = os.environ["DISCORD_OUTPUT_CHANNEL_ID"]

    lines = [
        f"👤: {job['driver']}",
        f"🏢: [{job['company']}]",
        f"📅: {job['date']}",
        "",
        f"🛣️: {job['distance']} km",
        f"⏱️: {job['time']}",
        f"💶: {job['income']}",
        f"🏆: {job['level']}",
        f"DmgP: {job['dmg']}",
        f"TmP: {job['tmp']}",
    ]
    if job.get("xp") is not None:
        lines.append(f"XP: {job['xp']}")
    lines += ["", "✅ Accepted"]

    embed = {
        "description": "\n".join(lines),
        "color": 0xE53935,
    }
    if job.get("image_url"):
        embed["image"] = {"url": job["image_url"]}

    response = requests.post(
        f"{API}/channels/{channel_id}/messages",
        headers={"Authorization": f"Bot {token}"},
        json={"embeds": [embed]},
        timeout=20,
    )
    response.raise_for_status()
    return response.json()["id"]


if __name__ == "__main__":
    example = {
        "driver": "Apex | keem",
        "company": "Apex",
        "date": "October 12 13:56",
        "distance": 182,
        "time": "2h 14m",
        "income": 3088,
        "level": 381,
        "dmg": 162,
        "tmp": 0,
        "xp": 1109599,
        "image_url": "",
    }
    print(send_joblog(example))
