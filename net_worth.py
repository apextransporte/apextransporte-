import json
from datetime import datetime


def load_base(path="net_worth_base.json"):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data["base_date"], data["base"]


def parse_date(value):
    return datetime.fromisoformat(str(value)[:10]).date()


def norm(name):
    return str(name or "").strip().lower()


def estimate_net_worth(jobs, path="net_worth_base.json"):
    """jobs: list of dicts with keys driver, date (YYYY-MM-DD or ISO time), income (number).
    Returns {driver: base + income of every job logged after the base date}."""
    base_date, base = load_base(path)
    start = parse_date(base_date)
    totals = dict(base)
    lookup = {norm(k): k for k in totals}
    for job in jobs:
        key = lookup.get(norm(job.get("driver")))
        if key is None:
            continue
        try:
            if parse_date(job["date"]) > start:
                totals[key] += float(job.get("income") or 0)
        except (KeyError, ValueError):
            continue
    return totals


def find_net_worth(totals, name):
    """Returns the estimated net worth for a Discord name, or None when the name has no base."""
    for k, v in totals.items():
        if norm(k) == norm(name):
            return v
    return None


def fmt_money(value):
    if value is None:
        return ""
    if value >= 1_000_000:
        return "${:.1f}M".format(value / 1_000_000)
    if value >= 1_000:
        return "${:.1f}k".format(value / 1_000)
    return "${:,.0f}".format(value)
