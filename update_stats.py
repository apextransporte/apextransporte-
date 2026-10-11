import os
import json
import requests

token = os.environ["DISCORD_BOT_TOKEN"]
channel = os.environ["DISCORD_STATS_CHANNEL_ID"]

url = "https://discord.com/api/v10/channels/" + channel + "/messages?limit=20"
headers = {"Authorization": "Bot " + token}

r = requests.get(url, headers=headers, timeout=30)
print("Status:", r.status_code)
print(r.text[:300])
r.raise_for_status()
messages = r.json()
print("Messages found:", len(messages))

try:
    with open("data.json", encoding="utf-8") as f:
        data = json.load(f)
except Exception:
    data = {}

for key in ["networth", "drivers", "hours", "distance", "runs", "latest_job"]:
    data.setdefault(key, "")

if messages:
    first = messages[0]
    text = first.get("content", "")
    if not text and first.get("attachments"):
        text = "Screenshot posted"
    data["latest_job"] = text

with open("data.json", "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False)

print("Saved:", data)
