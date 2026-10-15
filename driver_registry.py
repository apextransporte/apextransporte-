"""
driver_registry.py
Drop this file next to update_stats.py.

What it fixes:
1. Names like "APEX | Kretek" now match the plain name "Kretek".
2. Drivers are matched by Discord user ID first, so nickname edits never break a row.
3. Any official member with no row gets a new row automatically.
4. Fixed net worth values are never overwritten by empty data.
5. Members without the official role are removed from the list.
"""

import json
import re
import unicodedata

DRIVERS_FILE = "apex_drivers.json"

# Fields a job screenshot may fill. Keys are the names used in apex_drivers.json.
# Change a key here if your file uses a different name.
JOB_FIELDS = [
    "level", "xp", "distance_km", "time", "fuel",
    "damage_penalty", "time_penalty", "income",
]
FIXED_FIELDS = ["net_worth"]  # typed by hand, never overwritten by the bot


def clean_name(name):
    """Turn 'APEX | Kretek' or '[APEX] Kretek 🇹🇷' into 'kretek'."""
    if not name:
        return ""
    text = unicodedata.normalize("NFKD", str(name))
    # remove tags in brackets or before a separator, for example "APEX |" or "[APEX]"
    text = re.sub(r"^\s*[\[\(]?\s*apex\s*[\]\)]?\s*[|:\-<>/]*\s*", "", text, flags=re.I)
    text = re.sub(r"[\[\(]\s*apex\s*[\]\)]", "", text, flags=re.I)
    # keep letters and numbers only
    text = re.sub(r"[^A-Za-z0-9]", "", text)
    return text.lower()


def load_drivers(path=DRIVERS_FILE):
    """Return a list of driver dicts. Accepts a list or a dict keyed by name or ID."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []
    if isinstance(data, dict):
        data = data.get("drivers", list(data.values()))
    if isinstance(data, dict):
        data = list(data.values())
    return [d for d in data if isinstance(d, dict)]


def save_drivers(drivers, path=DRIVERS_FILE):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(drivers, f, ensure_ascii=False, indent=2)


def new_driver(user_id, display_name):
    row = {"discord_id": str(user_id), "name": clean_display(display_name)}
    for field in JOB_FIELDS + FIXED_FIELDS:
        row[field] = None
    return row


def clean_display(name):
    """Readable name without the APEX tag, original casing kept."""
    text = re.sub(r"^\s*[\[\(]?\s*apex\s*[\]\)]?\s*[|:\-<>/]*\s*", "", str(name or ""), flags=re.I)
    return text.strip() or str(name or "").strip()


def find_driver(drivers, user_id, display_name):
    """
    Match order:
    1. Discord user ID
    2. Cleaned name (then attach the ID so step 1 works next time)
    3. Create a new row
    """
    uid = str(user_id)
    for d in drivers:
        if str(d.get("discord_id", "")) == uid:
            return d

    key = clean_name(display_name)
    for d in drivers:
        if not d.get("discord_id") and clean_name(d.get("name")) == key and key:
            d["discord_id"] = uid
            return d

    row = new_driver(uid, display_name)
    drivers.append(row)
    return row


def apply_job(driver, job):
    """Write only values the screenshot actually read. Empty values never erase data."""
    for field in JOB_FIELDS:
        value = job.get(field)
        if value not in (None, "", "-"):
            driver[field] = value
    return driver


def sync_members(drivers, members, official_role_id):
    """
    members: list of (user_id, display_name, [role_ids]) for the whole server.
    Keeps official role holders, adds missing ones, removes everyone else.
    """
    official = {}
    for user_id, display_name, role_ids in members:
        if int(official_role_id) in [int(r) for r in role_ids]:
            official[str(user_id)] = display_name

    for user_id, display_name in official.items():
        row = find_driver(drivers, user_id, display_name)
        row["name"] = clean_display(display_name)

    return [d for d in drivers if str(d.get("discord_id", "")) in official]


# ---------------------------------------------------------------
# How to use it inside update_stats.py
#
#   from driver_registry import load_drivers, save_drivers, find_driver, apply_job, sync_members
#
#   drivers = load_drivers()
#   drivers = sync_members(drivers, members, OFFICIAL_ROLE_ID)   # once per run
#
#   for message in job_log_messages:
#       job = read_screenshot(message)                           # your existing reader
#       driver = find_driver(drivers, message.author.id, message.author.display_name)
#       apply_job(driver, job)
#
#   save_drivers(drivers)
# ---------------------------------------------------------------

if __name__ == "__main__":
    # Quick self test
    drivers = [{"name": "Kretek", "net_worth": "6.1M"}]
    assert clean_name("APEX | Kretek") == "kretek"
    assert clean_name("[APEX] Kretek 🇹🇷") == "kretek"
    row = find_driver(drivers, 111, "APEX | Kretek")
    assert row["discord_id"] == "111" and row["net_worth"] == "6.1M"
    row2 = find_driver(drivers, 222, "APEX | NewGuy")
    assert row2["name"] == "NewGuy" and len(drivers) == 2
    apply_job(row, {"level": 18, "distance_km": 186, "time": "7h 31m", "income": 3469, "fuel": None})
    assert row["level"] == 18 and row["net_worth"] == "6.1M"
    left = sync_members(drivers, [(111, "APEX | Kretek", [5]), (333, "Visitor", [9])], 5)
    assert len(left) == 1 and left[0]["name"] == "Kretek"
    print("All tests passed")
