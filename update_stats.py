import io
import json
import os
import re

import requests
from PIL import Image, ImageOps
import pytesseract

API = "https://discord.com/api/v10"
MAX_MESSAGES = 500

# Value boxes on the job result screen, measured on a 1600 x 720 screenshot
BOXES = {
    "distance": (700, 368, 825, 402),
    "time": (692, 405, 815, 439),
    "income": (960, 443, 1087, 477),
    "damage": (980, 368, 1105, 402),
}


def read_box(img, box):
    w, h = img.size
    x1, y1, x2, y2 = box
    c = img.crop((int(x1 / 1600 * w), int(y1 / 720 * h), int(x2 / 1600 * w), int(y2 / 720 * h)))
    c = c.resize((c.width * 4, c.height * 4), Image.LANCZOS)
    c = ImageOps.autocontrast(c)
    c = ImageOps.expand(c, border=20, fill=255)
    return pytesseract.image_to_string(c, config="--psm 7").strip()


def to_int(text):
    digits = re.sub(r"[^0-9]", "", text)
    return int(digits) if digits else None


def parse_time(text):
    hours = re.search(r"(\d+)\s*h", text)
    mins = re.search(r"(\d+)\s*m", text)
    if not hours and not mins:
        return None
    return (int(hours.group(1)) if hours else 0) * 60 + (int(mins.group(1)) if mins else 0)


def parse_job(image_bytes):
    img = Image.open(io.BytesIO(image_bytes)).convert("L")
    raw = {k: read_box(img, b) for k, b in BOXES.items()}
    print("OCR:", raw)
    km = to_int(raw["distance"])
    minutes = parse_time(raw["time"])
    income = to_int(raw["income"])
    if km is None or minutes is None or income is None:
        return None
    return {"km": km, "minutes": minutes, "income": income}


def fetch_messages(token, channel):
    headers = {"Authorization": "Bot " + token}
    messages = []
    before = None
    while len(messages) < MAX_MESSAGES:
        url = API + "/channels/" + channel + "/messages?limit=100"
        if before:
            url += "&before=" + before
        r = requests.get(url, headers=headers, timeout=30)
        print("Status:", r.status_code)
        r.raise_for_status()
        batch = r.json()
        if not batch:
            break
        messages.extend(batch)
        before = batch[-1]["id"]
    return messages


def is_image(att):
    ctype = att.get("content_type") or ""
    name = (att.get("filename") or "").lower()
    return ctype.startswith("image/") or name.endswith((".png", ".jpg", ".jpeg", ".webp"))


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def main():
    token = os.environ["DISCORD_BOT_TOKEN"]
    channel = os.environ["DISCORD_STATS_CHANNEL_ID"]

    messages = fetch_messages(token, channel)
    print("Messages found:", len(messages))

    jobs = load_json("jobs.json", [])
    seen = {j["id"] for j in jobs}

    # Oldest first so the newest job ends up last
    for msg in reversed(messages):
        for att in msg.get("attachments", []):
            job_id = msg["id"] + "-" + str(att.get("id"))
            if job_id in seen or not is_image(att):
                continue
            try:
                img_bytes = requests.get(att["url"], timeout=60).content
                job = parse_job(img_bytes)
            except Exception as e:
                print("Could not read", job_id, e)
                continue
            if job is None:
                print("No numbers found in", job_id)
                continue
            job["id"] = job_id
            job["author"] = msg["author"]["id"]
            jobs.append(job)
            seen.add(job_id)
            print("Added job:", job)

    data = load_json("data.json", {})
    for key in ["networth", "drivers", "hours", "distance", "runs", "income", "latest_job"]:
        data.setdefault(key, "")

    total_km = sum(j["km"] for j in jobs)
    total_min = sum(j["minutes"] for j in jobs)
    total_income = sum(j["income"] for j in jobs)

    data["runs"] = str(len(jobs))
    data["drivers"] = str(len({j["author"] for j in jobs}))
    data["distance"] = "{:,} km".format(total_km)
    data["hours"] = "{}h {}m".format(total_min // 60, total_min % 60)
    data["income"] = "EUR {:,}".format(total_income)
    if jobs:
        last = jobs[-1]
        data["latest_job"] = "{} km, {}h {}m, EUR {:,}".format(
            last["km"], last["minutes"] // 60, last["minutes"] % 60, last["income"]
        )

    with open("jobs.json", "w", encoding="utf-8") as f:
        json.dump(jobs, f, ensure_ascii=False)
    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)

    print("Saved:", data)


if __name__ == "__main__":
    main()
