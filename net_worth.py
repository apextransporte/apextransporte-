import json
from datetime import datetime

def load_base(path="net_worth_base.json"):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data["base_date"], data["base"]

def parse_date(value):
    return datetime.fromisoformat(str(value)[:10]).date()

def estimate_net_worth(jobs, path="net_worth_base.json"):
    """jobs: list of dicts with keys driver, date (YYYY-MM-DD), income (number).
    Returns {driver: base + income of every job logged after the base date}."""
    base_date, base = load_base(path)
    start = parse_date(base_date)
    totals = dict(base)
    for job in jobs:
        name = job.get("driver")
        if name not in totals:
            continue
        try:
            if parse_date(job["date"]) > start:
                totals[name] += float(job.get("income") or 0)
        except (KeyError, ValueError):
            continue
    return totals
