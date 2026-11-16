"""Read the ClusterInfo EU project. Only grouped counts leave PostHog by default."""
import json
import os
from pathlib import Path
import re
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import UUID

URL = "https://eu.posthog.com/api/projects/155394/query/"
COHORT = Path(__file__).with_name("cohort.sql").read_text()
COUNTS = """
SELECT arrival_month, score, count() AS ids,
       countIf(help_yes AND NOT help_no) AS intent_yes,
       countIf(help_no AND NOT help_yes) AS intent_no,
       countIf(help_yes AND help_no) AS intent_conflict,
       countIf(help_yes AND NOT help_no AND guide_yes AND NOT guide_no) AS actionable_yes,
       countIf(help_yes AND NOT help_no AND guide_no AND NOT guide_yes) AS actionable_no,
       countIf(help_yes AND NOT help_no AND guide_yes AND guide_no) AS actionable_conflict
FROM visitors
GROUP BY arrival_month, score
ORDER BY arrival_month, score
LIMIT 10000
"""
COLUMNS = ("arrival_month", "score", "ids", "intent_yes", "intent_no", "intent_conflict",
           "actionable_yes", "actionable_no", "actionable_conflict")
ID_COLUMNS = ("visitor_id", "arrival_month", "score", "help_yes", "help_no", "guide_yes", "guide_no")


def query(sql):
    key = os.environ.get("POSTHOG_READONLY_KEY")
    if not key:
        raise ValueError("Set POSTHOG_READONLY_KEY to a read-only EU project key.")
    body = json.dumps({"query": {"kind": "HogQLQuery", "query": sql}}).encode()
    request = Request(URL, data=body, headers={"Authorization": "Bearer " + key,
                                               "Content-Type": "application/json"})
    for attempt in range(4):
        try:
            with urlopen(request, timeout=150) as response:
                data = json.load(response)
            break
        except HTTPError as error:
            if error.code not in (429, 500, 502, 503, 504) or attempt == 3:
                detail = error.read().decode(errors="replace")[:800]
                raise RuntimeError(f"PostHog HTTP {error.code}: {detail}") from None
            retry = error.headers.get("Retry-After", "")
            time.sleep(min(60, int(retry)) if retry.isdigit() else 2 ** attempt)
        except (URLError, TimeoutError):
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)
    if data.get("error") or not isinstance(data.get("results"), list):
        raise RuntimeError(f"PostHog did not return complete results: {data.get('error')}")
    return data


def checked_rows(data, columns):
    if data.get("columns") != list(columns) or any(len(r) != len(columns) for r in data["results"]):
        raise ValueError("Unexpected PostHog result schema.")
    return [dict(zip(columns, row)) for row in data["results"]]


def cohort_sql(start, end):
    return COHORT.replace("{start}", start.strftime("%Y-%m-%d %H:%M:%S")).replace(
        "{end}", end.strftime("%Y-%m-%d %H:%M:%S"))


def fetch_counts(prefix):
    data = query(prefix + COUNTS)
    if data.get("hasMore") or len(data["results"]) >= 10000:
        raise ValueError("Incomplete aggregate result.")
    rows = checked_rows(data, COLUMNS)
    for row in rows:
        if row["arrival_month"] != "returning" and not re.fullmatch(r"[0-9]{4}-(0[1-9]|1[0-2])", row["arrival_month"]):
            raise ValueError("Unexpected arrival month.")
        if any(type(row[key]) is not int or row[key] < 0 for key in COLUMNS[1:]):
            raise ValueError("Invalid count or engagement score.")
        if (row["score"] > 3 or row["ids"] == 0
                or row["intent_yes"] + row["intent_no"] + row["intent_conflict"] > row["ids"]
                or row["actionable_yes"] + row["actionable_no"] + row["actionable_conflict"] > row["intent_yes"]):
            raise ValueError("Inconsistent poll counts.")
    return rows


def visitor_rows(prefix):
    """Seek by unique ID so an export is not limited to the first results page."""
    cursor = ""
    while True:
        page = query(prefix + f"""
SELECT toString(person_id) AS visitor_id, arrival_month, score, help_yes, help_no, guide_yes, guide_no
FROM visitors
WHERE arrival_month != 'returning' AND toString(person_id) > '{cursor}'
ORDER BY visitor_id LIMIT 2000
""")
        rows = checked_rows(page, ID_COLUMNS)
        for row in rows:
            value = str(UUID(row["visitor_id"]))
            if value != row["visitor_id"] or value <= cursor:
                raise ValueError("Unexpected or repeated visitor ID.")
            cursor = value
            yield row
        if len(rows) < 2000 and not page.get("hasMore"):
            return
        if not rows:
            raise ValueError("Empty PostHog page with more results.")
