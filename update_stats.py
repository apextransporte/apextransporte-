import io
import json
import os
import re
import time
import urllib.parse
from collections import Counter

import numpy as np
import requests
from PIL import Image, ImageOps
from scipy import ndimage
import pytesseract

from net_worth import estimate_net_worth, find_net_worth, fmt_money
from post_joblog import send_joblog

MIN_POST_ID = 1559717373542400000
def post_once(job, message_id, state):
posted = state.setdefault("posted_ids", [])
if int(message_id) <= MIN_POST_ID:
return
if str(message_id) in posted:
return
try:
send_joblog(job)
posted.append(str(message_id))
except Exception as error:
print("Post failed:", error)
API = "https://discord.com/api/v10"
MAX_MESSAGES = 300
MAX_SECONDS = int(os.environ.get("MAX_SECONDS", "1500"))
SCHEMA = 3

# Fallback value boxes on a 1600 x 720 job result screenshot
FIXED_BOXES = {
    "distance": (698, 370, 825, 399),
    "time": (689, 408, 816, 437),
    "fuel": (680, 445, 807, 474),
    "damage": (977, 370, 1104, 399),
    "time_penalty": (969, 408, 1097, 437),
    "income": (960, 445, 1086, 473),
}
NAMES = [["distance", "time", "fuel"], ["damage", "time_penalty", "income"]]
VARIANTS = [(4, "auto"), (4, "bin135"), (6, "bin160"), (3, "auto"), (6, "auto"), (5, "bin135"),
            (3, "bin160"), (4, "bin160"), (6, "bin135")]
REACTION_OK = "\u2705"
REACTION_NO = "\u274c"
REACTION_SECONDS = 300


def request_retry(method, url, token, tries=4):
    """Calls Discord and tries again after a timeout, a network error, or a rate limit."""
    headers = {"Authorization": "Bot " + token}
    for attempt in range(tries):
        try:
            r = requests.request(method, url, headers=headers, timeout=60)
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            print("Network problem, try", attempt + 1, "of", tries, e)
            time.sleep(5 * (attempt + 1))
            continue
        if r.status_code == 429:
            try:
                wait = float(r.json().get("retry_after", 5))
            except Exception:
                wait = float(r.headers.get("Retry-After", 5))
            time.sleep(min(wait, 60) + 1)
            continue
        return r
    return None


def already_reacted(message, emoji):
    return any(x.get("me") and x["emoji"]["name"] == emoji for x in message.get("reactions", []))


def react(message, emoji, token, channel):
    """Returns False when the bot lacks permission, so the caller stops."""
    if already_reacted(message, emoji):
        return True
    url = API + "/channels/" + channel + "/messages/" + message["id"] + "/reactions/" + urllib.parse.quote(emoji) + "/@me"
    r = request_retry("PUT", url, token)
    if r is None:
        print("Reaction skipped, Discord did not answer", message["id"])
        return True
    if r.status_code == 403:
        print("Reaction blocked, give the bot Add Reactions and Read Message History")
        return False
    if r.status_code != 204:
        print("Reaction failed", message["id"], r.status_code)
    time.sleep(0.4)
    return True


def fingerprint(job):
    return (job["author"], job["km"], job["minutes"], job["income"],
            job.get("fuel", 0), job.get("damage", 0), job.get("time_penalty", 0))


def build_reaction_plan(messages, jobs, nojob_ids):
    """Check mark for a new job log, X for a repeated screenshot or an image with no job log."""
    seen, ok_msgs, dup_msgs = set(), set(), set()
    for j in sorted(jobs, key=lambda x: x.get("ts", "")):
        mid = j["id"].split("-")[0]
        fp = fingerprint(j)
        if fp in seen:
            dup_msgs.add(mid)
        else:
            seen.add(fp)
            ok_msgs.add(mid)
    plan = []
    for msg in messages:
        mid = msg["id"]
        if mid in ok_msgs:
            plan.append((msg, REACTION_OK))
        elif mid in dup_msgs or mid in nojob_ids:
            plan.append((msg, REACTION_NO))
    return plan


# ---------- layout detection ----------

def find_boxes(mn, w_img, h_img):
    """Find the six light value boxes. Works for any screenshot size."""
    lab, _ = ndimage.label(mn > 205)
    cands = []
    for i, sl in enumerate(ndimage.find_objects(lab), 1):
        if sl is None:
            continue
        y1, y2, x1, x2 = sl[0].start, sl[0].stop, sl[1].start, sl[1].stop
        w, h = x2 - x1, y2 - y1
        if h <= 0 or not (3.2 <= w / h <= 5.5) or not (0.04 * w_img <= w <= 0.2 * w_img):
            continue
        if (lab[sl] == i).sum() / float(w * h) < 0.7:
            continue
        cands.append((x1, y1, x2, y2))
    best = []
    for c in cands:
        w, h = c[2] - c[0], c[3] - c[1]
        group = [d for d in cands if abs((d[2] - d[0]) - w) <= 0.06 * w and abs((d[3] - d[1]) - h) <= 0.12 * h]
        if len(group) > len(best):
            best = group
    if len(best) < 6:
        return None
    best = sorted(best, key=lambda b: (b[2] - b[0]) * (b[3] - b[1]), reverse=True)[:6]
    best.sort(key=lambda b: b[0] + b[2])
    left = sorted(best[:3], key=lambda b: b[1])
    right = sorted(best[3:], key=lambda b: b[1])
    h = np.median([b[3] - b[1] for b in best])
    for a, b in zip(left, right):
        if abs(a[1] - b[1]) > h:
            return None
    boxes = {}
    for col, names in zip((left, right), NAMES):
        for name, b in zip(names, col):
            boxes[name] = b
    return boxes


def get_layout(mn, w_img, h_img):
    boxes = find_boxes(mn, w_img, h_img)
    found = boxes is not None
    if not found:
        boxes = {k: (int(x1 / 1600 * w_img), int(y1 / 720 * h_img), int(x2 / 1600 * w_img), int(y2 / 720 * h_img))
                 for k, (x1, y1, x2, y2) in FIXED_BOXES.items()}
    h = np.median([b[3] - b[1] for b in boxes.values()])
    s = h / 29.0
    xl, top, xr = boxes["distance"][0], boxes["distance"][1], boxes["damage"][2]
    yc = top - 85 * s
    layout = {
        "boxes": boxes,
        "found": found,
        "level_a": (xl - 312 * s, yc - 17 * s, xl - 250 * s, yc + 17 * s),
        "level_b": (xr + 126 * s, yc - 17 * s, xr + 212 * s, yc + 17 * s),
    }
    return layout


# ---------- OCR helpers ----------

def prep(c, scale, mode):
    im = Image.fromarray(c.astype("uint8"))
    im = im.resize((max(1, im.width * scale), max(1, im.height * scale)), Image.LANCZOS)
    if mode == "auto":
        im = ImageOps.autocontrast(im)
    elif mode == "bin135":
        im = im.point(lambda p: 255 if p > 135 else 0)
    else:
        im = im.point(lambda p: 255 if p > 160 else 0)
    return ImageOps.expand(im, border=25, fill=255)


def inner(mn, box):
    x1, y1, x2, y2 = [int(v) for v in box]
    w, h = x2 - x1, y2 - y1
    return mn[y1 + int(0.1 * h): y2 - int(0.1 * h), x1 + int(0.2 * w): x2 - int(0.2 * w)]


def vote(c, parse, config="--psm 7"):
    """Read the same crop with several settings and keep the value most runs agree on."""
    results = []
    for scale, mode in VARIANTS:
        text = pytesseract.image_to_string(prep(c, scale, mode), config=config).strip()
        value = parse(text)
        if value is not None:
            results.append(value)
        if len(results) >= 3 and len(set(results)) == 1:
            break
    if not results:
        return None
    return Counter(results).most_common(1)[0][0]


def to_int(text):
    digits = re.sub(r"[^0-9]", "", text)
    return int(digits) if digits else None


def parse_km(text):
    m = re.search(r"(\d+)\s*[kK]", text)
    return int(m.group(1)) if m else to_int(text)


def parse_time(text):
    hours = re.search(r"(\d+)\s*h", text)
    mins = re.search(r"(\d+)\s*m", text)
    if not hours and not mins:
        return None
    return (int(hours.group(1)) if hours else 0) * 60 + (int(mins.group(1)) if mins else 0)


def parse_fuel(text):
    # The unit letter l is often read as 1, I, ! or |. Remove it before counting digits.
    t = text.strip()
    if t and t[-1] in "lLiI|!":
        return to_int(t[:-1])
    digits = re.sub(r"[^0-9]", "", t)
    if len(digits) >= 3 and t.endswith("1"):
        digits = digits[:-1]
    return int(digits) if digits else None


def parse_money(text):
    m = re.search(r"\u20ac\s*(\d[\d,\.]*)", text)
    if m:
        return to_int(m.group(1))
    tokens = re.findall(r"\d[\d,\.]*", text)
    return to_int(tokens[-1]) if tokens else None


def read_penalty(arr, box):
    """Red penalty text is read from two colour channels and several settings, then voted."""
    x1, y1, x2, y2 = [int(v) for v in box]
    w, h = x2 - x1, y2 - y1
    c = arr[y1 + int(0.08 * h): y2 - int(0.08 * h), x1 + int(0.15 * w): x2 - int(0.15 * w)].astype(int)
    # An empty penalty shows a grey dash, so there is no red in the box
    if ((c[:, :, 0] - np.minimum(c[:, :, 1], c[:, :, 2])) > 70).mean() < 0.004:
        return 0
    results = []
    for chan in (c.min(axis=2), c[:, :, 1]):
        chan = chan.astype("uint8")
        for scale in (4, 5, 6):
            for thr in (115, 128, 140):
                im = Image.fromarray(chan).resize((chan.shape[1] * scale, chan.shape[0] * scale), Image.LANCZOS)
                im = im.point(lambda p, t=thr: 255 if p > t else 0)
                text = pytesseract.image_to_string(ImageOps.expand(im, border=25, fill=255), config="--psm 7")
                value = parse_money(text)
                if value:
                    results.append(value)
    return Counter(results).most_common(1)[0][0] if results else 0


def read_level_number(gray, box):
    x1, y1, x2, y2 = [max(0, int(v)) for v in box]
    c = gray.crop((x1, y1, x2, y2))
    c = c.resize((c.width * 6, c.height * 6), Image.BICUBIC)
    c = ImageOps.autocontrast(c)
    results = []
    for t in (130, 150, 170):
        b = ImageOps.invert(c.point(lambda p, t=t: 255 if p > t else 0))
        b = ImageOps.expand(b, border=30, fill=255)
        text = pytesseract.image_to_string(b, config="--psm 7 -c tessedit_char_whitelist=0123456789")
        digits = re.sub(r"[^0-9]", "", text)
        if digits:
            results.append(int(digits))
    return Counter(results).most_common(1)[0][0] if results else None


def swaps(n):
    """Every reading of n where the digits 1 and 7 are swapped, with the number of swaps."""
    out = {int(n): 0}
    digits = str(n)
    for mask in range(1, 2 ** len(digits)):
        d, count, ok = list(digits), 0, True
        for i in range(len(d)):
            if mask >> i & 1:
                if d[i] == "1":
                    d[i] = "7"
                elif d[i] == "7":
                    d[i] = "1"
                else:
                    ok = False
                    break
                count += 1
        if ok:
            v = int("".join(d))
            out[v] = min(out.get(v, 99), count)
    return out


def read_level(gray, layout):
    """The bar runs from the current level (left) to the next level (right)."""
    a = read_level_number(gray, layout["level_a"])
    b = read_level_number(gray, layout["level_b"])
    if a is None and b is None:
        return None
    if a is None:
        return b - 1, b
    if b is None:
        return a, a + 1
    best = None
    for x, cx in swaps(a).items():
        for y, cy in swaps(b).items():
            if y == x + 1:
                cost = cx + cy + (0 if y == b else 0.1)
                if best is None or cost < best[0]:
                    best = (cost, x, y)
    if best:
        return best[1], best[2]
    return b - 1, b  # the right number is the clearer one


# ---------- sanity fixes ----------

def speed(km, minutes):
    return km / (minutes / 60.0) if minutes else 0


def fix_km(km, minutes, fuel=None):
    """Remove a stray digit read next to the distance when the speed is not believable.
    When the fuel is known, it picks the distance that also matches the fuel use."""
    if minutes and 15 <= speed(km, minutes) <= 150 and km <= 3000:
        return km, False
    s = str(km)
    cands = []
    for cand in (s[1:], s[:-1], s[2:], s[:-2], s[1:-1]):
        if cand and int(cand) > 0 and 15 <= speed(int(cand), minutes) <= 150:
            cands.append(int(cand))
    if not cands:
        return km, False
    if fuel:
        both = [v for v in cands if 0.15 <= fuel / v <= 1.2]
        if both:
            return min(both, key=lambda v: abs(fuel / v - 0.5)), True
    return min(cands, key=lambda v: abs(speed(v, minutes) - 60)), True


def edits(n):
    """Readings of n with a stray first or last digit removed, or 1 and 7 swapped."""
    d = str(n)
    out = {int(v): 1 for v in (d[1:], d[:-1]) if v and int(v) > 0}
    for v, cost in swaps(n).items():
        if v != n:
            out[v] = min(out.get(v, 99), cost)
    return out


def fix_fuel(fuel, km):
    """A truck burns about 0.15 to 1.2 litres per km. Repair a bad reading or return None."""
    if not km or fuel is None:
        return fuel
    if 0.15 <= fuel / km <= 1.2:
        return fuel
    options = [(cost, abs(v / km - 0.5), v) for v, cost in edits(fuel).items() if 0.15 <= v / km <= 1.2]
    return min(options)[2] if options else None


def fix_income(income, km):
    """Jobs pay roughly 4 to 120 euro per km. Repair a stray digit when the value is far outside."""
    if not km or 4 <= income / km <= 120:
        return income
    options = [(cost, abs(v / km - 18), v) for v, cost in edits(income).items() if 4 <= v / km <= 120]
    return min(options)[2] if options else income


def sanitize(job):
    """Run on every saved job, so older bad reads are cleaned too. Safe to run many times."""
    raw = job.get("km_raw", job["km"])
    km, changed = fix_km(raw, job["minutes"], job.get("fuel"))
    if changed:
        job["km_raw"] = raw
        job["km"] = km
    else:
        job["km"] = raw
        job.pop("km_raw", None)
    inc = fix_income(job["income"], job["km"])
    if inc != job["income"]:
        job.setdefault("income_raw", job["income"])
        job["income"] = inc
    if "fuel" in job:
        fixed = fix_fuel(job["fuel"], job["km"])
        if fixed is None:
            job.pop("fuel", None)  # unreadable, so the table stays blank instead of showing a wrong number
            job["check"] = True
        else:
            job["fuel"] = fixed
    if not 15 <= speed(job["km"], job["minutes"]) <= 140 or job["km"] and not 4 <= job["income"] / job["km"] <= 120:
        job["check"] = True
    else:
        job.pop("check", None)


def parse_job(image_bytes):
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    arr = np.asarray(img).astype(np.uint8)
    mn = arr.min(axis=2)
    gray = img.convert("L")
    layout = get_layout(mn, img.width, img.height)
    b = layout["boxes"]

    km = vote(inner(mn, b["distance"]), parse_km)
    minutes = vote(inner(mn, b["time"]), parse_time)
    income = vote(inner(mn, b["income"]), parse_money)
    print("OCR:", {"km": km, "minutes": minutes, "income": income, "layout_found": layout["found"]})
    if km is None or minutes is None or income is None:
        return None

    job = {"km": km, "minutes": minutes, "income": income}
    job["fuel"] = vote(inner(mn, b["fuel"]), parse_fuel) or 0
    job["damage"] = read_penalty(arr, b["damage"])
    job["time_penalty"] = read_penalty(arr, b["time_penalty"])

    level = read_level(gray, layout)
    if level:
        job["level"] = "{} to {}".format(level[0], level[1])
        job["level_now"] = level[0]
    sanitize(job)
    return job


# ---------- Discord ----------

def fetch_messages(token, channel):
    messages = []
    before = None
    while len(messages) < MAX_MESSAGES:
        url = API + "/channels/" + channel + "/messages?limit=100"
        if before:
            url += "&before=" + before
        r = request_retry("GET", url, token, tries=8)
        if r is None:
            print("Discord did not answer, using the", len(messages), "messages loaded so far")
            break
        print("Status:", r.status_code)
        r.raise_for_status()
        batch = r.json()
        if not batch:
            break
        messages.extend(batch)
        before = batch[-1]["id"]
        time.sleep(1)  # stay under the Discord rate limit
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


def level_from_text(text):
    m = re.match(r"^(\d+) to (\d+)$", text or "")
    return int(m.group(1)) if m and int(m.group(2)) == int(m.group(1)) + 1 else None


def fill_levels(jobs):
    """Jobs with an unreadable level take the level of the same driver's nearest earlier job."""
    for j in jobs:
        if not j.get("level_now") and level_from_text(j.get("level")):
            j["level_now"] = level_from_text(j["level"])
    by_author = {}
    for j in sorted(jobs, key=lambda x: x.get("ts", "")):
        by_author.setdefault(j["author"], []).append(j)
    for items in by_author.values():
        known = [j["level_now"] for j in items if j.get("level_now")]
        for i, j in enumerate(items):
            if j.get("level_now"):
                j.pop("level_est", None)
                continue
            before = [k["level_now"] for k in items[:i] if k.get("level_now")]
            after = [k["level_now"] for k in items[i + 1:] if k.get("level_now")]
            guess = before[-1] if before else (after[0] if after else None)
            if guess:
                j["level_now"] = guess
                j["level_est"] = True


def main():
    started = time.time()
    token = os.environ["DISCORD_BOT_TOKEN"]
    channel = os.environ["DISCORD_STATS_CHANNEL_ID"]

    messages = fetch_messages(token, channel)
    print("Messages found:", len(messages))

    # Jobs from an older version stay in the file until they are read again with the new fields
    jobs = load_json("jobs.json", [])
    index = {j["id"]: i for i, j in enumerate(jobs)}
    current = {j["id"] for j in jobs if j.get("v") == SCHEMA}
    nojob_ids = set()
    out_of_time = False
    # Oldest first so the newest job ends up last
    for msg in reversed(messages):
        if out_of_time:
            break
        for att in msg.get("attachments", []):
            job_id = msg["id"] + "-" + str(att.get("id"))
            if job_id in current or not is_image(att):
                continue
            if time.time() - started > MAX_SECONDS:
                print("Time limit reached, the next run continues from here")
                out_of_time = True
                break
            try:
                img_bytes = requests.get(att["url"], timeout=60).content
                job = parse_job(img_bytes)
            except Exception as e:
                print("Could not read", job_id, e)
                continue
            if job is None:
                print("No numbers found in", job_id)
                nojob_ids.add(msg["id"])
                continue
            job["id"] = job_id
            job["v"] = SCHEMA
            job["author"] = msg["author"]["id"]
            job["name"] = msg["author"].get("global_name") or msg["author"].get("username") or msg["author"]["id"]
            job["ts"] = msg.get("timestamp", "")
            if job_id in index:
                jobs[index[job_id]] = job
            else:
                index[job_id] = len(jobs)
                jobs.append(job)
            current.add(job_id)
            print("Saved job:", job)

    # Every saved job gets the sanity fixes, including jobs saved by earlier runs
    for j in jobs:
        sanitize(j)
    jobs.sort(key=lambda j: j.get("ts", ""))
    fill_levels(jobs)

    # Reactions: check mark for new job logs, X for repeats and for images with no job log
    reaction_start = time.time()
    plan = build_reaction_plan(messages, jobs, nojob_ids)
    done = 0
    for msg, emoji in plan:
        if time.time() - reaction_start > REACTION_SECONDS:
            print("Reaction time limit reached, the next run continues from here")
            break
        if not react(msg, emoji, token, channel):
            break
        done += 1
    print("Reactions handled:", done, "of", len(plan))

    data = load_json("data.json", {})
    for key in ["networth", "drivers", "hours", "distance", "runs", "income", "latest_job"]:
        data.setdefault(key, "")

    total_km = sum(j["km"] for j in jobs)
    total_min = sum(j["minutes"] for j in jobs)
    total_income = sum(j["income"] for j in jobs)
    total_fuel = sum(j.get("fuel", 0) for j in jobs)
    total_damage = sum(j.get("damage", 0) for j in jobs)
    total_time_penalty = sum(j.get("time_penalty", 0) for j in jobs)
    for key in ("income_total", "skipped"):
        data.pop(key, None)

    data["runs"] = str(len(jobs))
    data["drivers"] = str(len({j["author"] for j in jobs}))
    data["distance"] = "{:,} km".format(total_km)
    data["hours"] = "{}h {}m".format(total_min // 60, total_min % 60)
    data["income"] = "\u20ac{:,}".format(total_income)
    data["fuel"] = "{:,} l".format(total_fuel)
    data["damage"] = "\u20ac{:,}".format(total_damage)
    data["time_penalty"] = "\u20ac{:,}".format(total_time_penalty)
    if jobs:
        last = jobs[-1]
        data["latest_job"] = "{} km, {}, \u20ac{:,}".format(last["km"], fmt_time(last["minutes"]), last["income"])
        data["latest_date"] = last.get("ts", "")

    # Net worth starts from the saved base values and grows with every new job income
    job_rows = [{"driver": j["name"], "date": j.get("ts", ""), "income": j["income"]} for j in jobs]
    net_worth = estimate_net_worth(job_rows)
    data["networth"] = fmt_money(sum(net_worth.values()))
    with open("net_worth.json", "w", encoding="utf-8") as f:
        json.dump({k: round(v) for k, v in net_worth.items()}, f, ensure_ascii=False)

    members = {}
    for j in jobs:
        m = members.setdefault(
            j["author"],
            {"name": j["name"], "runs": 0, "km": 0, "minutes": 0, "income": 0,
             "fuel": 0, "damage": 0, "time_penalty": 0, "read": 0, "last": None},
        )
        m["name"] = j["name"]
        m["runs"] += 1
        m["km"] += j["km"]
        m["minutes"] += j["minutes"]
        m["income"] += j["income"]
        m["fuel"] += j.get("fuel", 0)
        m["damage"] += j.get("damage", 0)
        m["time_penalty"] += j.get("time_penalty", 0)
        m["read"] += 1 if "fuel" in j else 0
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
                "fuel": "{:,} l".format(m["fuel"]) if m["read"] else "",
                "damage": "\u20ac{:,}".format(m["damage"]) if m["read"] else "",
                "time_penalty": "\u20ac{:,}".format(m["time_penalty"]) if m["read"] else "",
                "networth": fmt_money(find_net_worth(net_worth, m["name"])),
                "last_km": "{} km".format(last["km"]),
                "last_time": fmt_time(last["minutes"]),
                "last_income": "\u20ac{:,}".format(last["income"]),
                "last_fuel": "{} l".format(last["fuel"]) if "fuel" in last else "",
                "last_damage": "\u20ac{:,}".format(last["damage"]) if "damage" in last else "",
                "last_time_penalty": "\u20ac{:,}".format(last["time_penalty"]) if "time_penalty" in last else "",
                "level": last.get("level_now", ""),
                "level_estimated": bool(last.get("level_est")),
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
