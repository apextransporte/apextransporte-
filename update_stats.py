import base64
import json
import os
import time
import urllib.error
import urllib.request

API = "https://discord.com/api/v10"
MODEL = "gemini-2.5-flash-lite"
AI_URL = "https://generativelanguage.googleapis.com/v1beta/models/" + MODEL + ":generateContent"
MAX_NEW = 20
UA = "ApexStatsBot (https://github.com, 1.0)"

PROMPT = (
    "This is a Truckers of Europe 3 job result screen. "
    "Reply with JSON only and no other text. "
    "Keys: distance_km, minutes, fuel_l, damage_penalty, income. "
    "All values are integers with no currency signs. "
    "minutes is the Time Taken converted to minutes. "
    "damage_penalty is a positive number, use 0 for a dash. "
    "Add the key valid set to true. "
    "If the image is not a job result screen, reply {\"valid\": false}."
)


def discord_get(path, token):
    req = urllib.request.Request(
        API + path,
        headers={"Authorization": "Bot " + token, "User-Agent": UA},
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)


def read_image(url, mime, key):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read()
    body = json.dumps({
        "contents": [{
            "parts": [
                {"inline_data": {"mime_type": mime, "data": base64.b64encode(raw).decode()}},
                {"text": PROMPT},
            ]
        }],
        "generationConfig": {"responseMimeType": "application/json"},
    }).encode()
    ai = urllib.request.Request(
        AI_URL,
        data=body,
        headers={"x-goog-api-key": key, "content-type": "application/json"},
    )
    with urllib.request.urlopen(ai, timeout=60) as r:
        reply = json.load(r)
    text = reply["candidates"][0]["content"]["parts"][0]["text"]
    text = text.replace("```json", "").replace("```", "").strip()
    return json.loads(text)


def image_info(msg):
    for a in msg.get("attachments", []):
        kind = a.get("content_type") or ""
        if kind.startswith("image"):
            return a["url"], kind
    return None


def main():
    token = os.environ.get("DISCORD_BOT_TOKEN")
    channel_id = os.environ.get("DISCORD_STATS_CHANNEL_ID")
    key = os.environ.get("GEMINI_API_KEY")
    path = os.path.join(os.path.dirname(__file__), "data.json")

    if not token or not channel_id or not key:
        print("Missing a secret, leaving data.json unchanged.")
        return

    try:
        with open(path) as f:
            data = json.load(f)
    except Exception:
        data = {}

    jobs = data.get("jobs", [])
    skipped = data.get("skipped", [])
    done = set(j["id"] for j in jobs) | set(skipped)

    messages = []
    before = None
    try:
        for _ in range(10):
            url = "/channels/" + channel_id + "/messages?limit=100"
            if before:
                url += "&before=" + before
            batch = discord_get(url, token)
            if not batch:
                break
            messages += batch
            before = batch[-1]["id"]
            if len(batch) < 100:
                break
    except Exception as e:
        print("Could not reach Discord: " + str(e))
        return

    todo = [m for m in messages if m["id"] not in done and image_info(m)]
    for m in todo[:MAX_NEW]:
        url, mime = image_info(m)
        try:
            info = read_image(url, mime, key)
        except urllib.error.HTTPError as e:
            print("Gemini error " + str(e.code) + " on " + m["id"])
            if e.code == 429:
                break
            continue
        except Exception as e:
            print("Could not read " + m["id"] + ": " + str(e))
            continue
        time.sleep(6)
        if not info.get("valid"):
            skipped.append(m["id"])
            continue
        author = m["author"]
        jobs.append({
            "id": m["id"],
            "driver": author.get("global_name") or author["username"],
            "driver_id": author["id"],
            "date": m["timestamp"],
            "km": int(info.get("distance_km") or 0),
            "minutes": int(info.get("minutes") or 0),
            "fuel": int(info.get("fuel_l") or 0),
            "damage": int(info.get("damage_penalty") or 0),
            "income": int(info.get("income") or 0),
        })

    jobs.sort(key=lambda j: j["date"], reverse=True)
    total_km = sum(j["km"] for j in jobs)
    total_min = sum(j["minutes"] for j in jobs)

    data["jobs"] = jobs
    data["skipped"] = skipped
    data["runs"] = str(len(jobs))
    data["drivers"] = str(len(set(j["driver_id"] for j in jobs)))
    data["distance"] = "{:,} km".format(total_km)
    data["hours"] = str(total_min // 60) + "h"
    data["income_total"] = sum(j["income"] for j in jobs)
    if jobs:
        data["latest_job"] = jobs[0]["date"]

    with open(path, "w") as f:
        json.dump(data, f)
    print("Saved " + str(len(jobs)) + " jobs.")


main()
