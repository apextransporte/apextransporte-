import io
import json
import os
import re

import requests
from PIL import Image, ImageOps
import pytesseract

API = "https://discord.com/api/v10"
MAX_MESSAGES = 500
SCHEMA = 2

# Value boxes on the job result screen, measured on a 1600 x 720 screenshot
BOXES = {
    "distance": (700, 368, 825, 402),
    "time": (692, 405, 815, 439),
    "income": (960, 443, 1087, 477),
}
LEVEL_BOXES = ((396, 270, 444, 300), (1234, 268, 1306, 302))


def crop_box(img, box):
    w, h = img.size
    x1, y1, x2, y2 = box
    return img.crop((int(x1 / 1600 * w), int(y1 / 720 * h), int(x2 / 1600 * w), int(y2 / 720 * h)))


def read_box(img, box):
    c = crop_box(img, box)
    c = c.resize((c.width * 4, c.height * 4), Image.LANCZOS)
    c = ImageOps.autocontrast(c)
    c = ImageOps.expand(c, border=20, fill=255)
    return pytesseract.image_to_string(c, config="--psm 7").strip()


def read_level_number(img, box):
    c = crop_box(img, box)
    c = c.resize((c.width * 6, c.height * 6), Image.BICUBIC)
    c = ImageOps.autocontrast(c)
    b = ImageOps.invert(c.point(lambda p: 255 if p > 150 else 0))
    b = ImageOps.expand(b, border=30, fill=255)
    text = pytesseract.image_to_string(b, config="--psm 7 -c tessedit_char_whitelist=0123456789")
    digits = re.sub(r"[^0-9]", "", text)
    return int(digits) if digits else None


def read_level(img):
    a = read_level_number(img, LEVEL_BOXES[0])
    b = read_level_number(img, LEVEL_BOXES[1])
    if a is None or b is None or b < a or b - a > 5:
        return None
    return "{} to {}".format(a, b)


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
    job = {"km": km, "minutes": minutes, "income": income}
    level = read_level(img)
    if level:
        job["level"] = level
    return job


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


def fmt_time(minutes):
    return "{} h {} m".format(minutes // 60, minutes % 60)


def main():
    token = os.environ["DISCORD_BOT_TOKEN"]
    channel = os.environ["DISCORD_STATS_CHANNEL_ID"]

    messages = fetch_messages(token, channel)
    print("Messages found:", len(messages))

    # Jobs saved by an older version are read again so they gain the new fields
    jobs = [j for j in load_json("jobs.json", []) if j.get("v") == SCHEMA]
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
            job["v"] = SCHEMA
            job["author"] = msg["author"]["id"]
            job["name"] = msg["author"].get("global_name") or msg["author"].get("username") or msg["author"]["id"]
            job["ts"] = msg.get("timestamp", "")
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
    data["income"] = "\u20ac{:,}".format(total_income)
    if jobs:
        last = jobs[-1]
        data["latest_job"] = "{} km, {}, \u20ac{:,}".format(last["km"], fmt_time(last["minutes"]), last["income"])
        data["latest_date"] = last.get("ts", "")

    members = {}
    for j in jobs:
        m = members.setdefault(
            j["author"], {"name": j["name"], "runs": 0, "km": 0, "minutes": 0, "income": 0, "last": None}
        )
        m["name"] = j["name"]
        m["runs"] += 1
        m["km"] += j["km"]
        m["minutes"] += j["minutes"]
        m["income"] += j["income"]
        m["last"] = j
    table = []
    for m in sorted(members.values(), key=lambda x: x["km"], reverse=True):
        last = m["last"]
        table.append(
            {
                "name": m["name"],
                "runs": str(m["runs"]),
                "distance": "{:,} km".format(m["km"]),
                "hours": fmt_time(m["minutes"]),
                "income": "\u20ac{:,}".format(m["income"]),
                "networth": "",
                "last_km": "{} km".format(last["km"]),
                "last_time": fmt_time(last["minutes"]),
                "last_income": "\u20ac{:,}".format(last["income"]),
                "last_level": last.get("level", ""),
                "last_date": last.get("ts", ""),
            }
        )
    data["members"] = table

    with open("jobs.json", "w", encoding="utf-8") as f:
        json.dump(jobs, f, ensure_ascii=False)
    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)

    print("Saved:", data)


if __name__ == "__main__":
    main()
