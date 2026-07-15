import json
import time

import requests

from common import detect_country_group

# BOLD API SETTINGS-----------------------------------------

BOLD_BASE = "https://portal.boldsystems.org/api"


# HTTP WITH RETRY / BACKOFF-----------------------------------

class BoldBlockedError(Exception):
    """Raised when BOLD keeps refusing requests (e.g. Cloudflare block)."""
    pass


def bold_request(url, params, rate_limiter, max_retries=4, timeout=30, log=print):

    delay = 5

    for attempt in range(max_retries):
        rate_limiter.wait()

        try:
            r = requests.get(url, params=params, timeout=timeout)
        except requests.RequestException as e:
            log("BOLD network error:", e)
            time.sleep(delay)
            delay *= 2
            continue

        if r.status_code == 200:
            return r

        if r.status_code in (403, 429) or r.status_code >= 500:
            log(
                f"BOLD returned {r.status_code}, "
                f"retrying in {delay}s (attempt {attempt + 1}/{max_retries})"
            )
            time.sleep(delay)
            delay *= 2
            continue

        r.raise_for_status()

    raise BoldBlockedError(
        f"BOLD kept refusing requests after {max_retries} attempts "
        "(likely rate-limited/blocked). Stopping run."
    )


# MARKER MATCHING---------------------------------------------

def marker_matches(record_marker, wanted_marker):
    if not record_marker or not wanted_marker:
        return False

    def norm(s):
        return sorted(p for p in s.strip().lower().replace(" ", "").split("-") if p)

    return norm(record_marker) == norm(wanted_marker)


# BOLD SCORING (plain dict record)-----------------------------------------------

DEFAULT_LENGTH_BANDS = {
    "full_min": 300,
    "full_max": 1200,
    "partial_min": 200,
    "partial_max": 2000,
}


def score_bold_record(record, w, bad_words, length_bands=None):

    raw = 0

    title = " ".join(filter(None, [
        record.get("identification"),
        record.get("notes"),
        record.get("short_note")
    ])).lower()

    if any(b in title for b in bad_words):
        raw -= 100

    length = record.get("nuc_basecount") or 0

    bands = length_bands or DEFAULT_LENGTH_BANDS
    full_min = bands.get("full_min", 300)
    full_max = bands.get("full_max", 1200)
    partial_min = bands.get("partial_min", 200)
    partial_max = bands.get("partial_max", 2000)

    if full_min <= length <= full_max:
        length_score = 30
    elif partial_min <= length < full_min or full_max < length <= partial_max:
        length_score = 15
    else:
        length_score = 0

    location = (record.get("country/ocean") or "").lower()

    group = detect_country_group(location)
    location_score = w.get(group, 0)

    max_location = max(w.values()) if w else 40

    location_norm = (location_score / max_location) * 40
    length_norm = length_score
    penalty_norm = max(0, 30 - abs(raw) / 5)

    final_score = location_norm + length_norm + penalty_norm

    return round(final_score, 2)


# FETCHING FROM BOLD------------------------------------------------------
# BOLD's v5 API is a 3-step token flow, and a species query returns every
# marker for that species in one go - so we fetch/cache once per species
# and reuse it across all requested markers instead of re-querying BOLD
# for each marker separately.

def fetch_bold_records(species, rate_limiter, log=print):

    try:
        pre = bold_request(
            f"{BOLD_BASE}/query/preprocessor",
            {"query": f"tax:{species}"},
            rate_limiter,
            log=log
        )

        terms = pre.json().get("successful_terms", [])
        matched = [
            t["matched"] for t in terms
            if t.get("matched", "").startswith("tax:")
        ]

        if not matched:
            return []

        q = bold_request(
            f"{BOLD_BASE}/query",
            {"query": ";".join(matched), "extent": "full"},
            rate_limiter,
            log=log
        )

        query_id = q.json().get("query_id")

        if not query_id:
            return []

        dl = bold_request(
            f"{BOLD_BASE}/documents/{query_id}/download",
            {"format": "json"},
            rate_limiter,
            log=log
        )

        records = []
        for line in dl.text.splitlines():
            line = line.strip()
            if line:
                records.append(json.loads(line))

        return records

    except BoldBlockedError:
        raise

    except Exception as e:
        log("BOLD query error:", e)
        return []


def wrap_sequence(seq, width=70):
    return "\n".join(seq[i:i + width] for i in range(0, len(seq), width))


def build_bold_result(record, score):
    nuc = record.get("nuc")

    header = f">{record.get('processid')} {record.get('identification') or ''}".strip(
    )
    fasta_text = header + "\n" + wrap_sequence(nuc) + "\n"

    coord = record.get("coord")
    lat_lon = (
        f"{coord[0]},{coord[1]}"
        if isinstance(coord, list) and len(coord) == 2
        else None
    )

    voucher = record.get("museumid") or record.get("sampleid")

    meta = {
        "source": "BOLD",
        "accession": record.get("processid"),
        "title": record.get("identification"),
        "length": record.get("nuc_basecount"),
        "organism": record.get("species"),
        "geo_loc": record.get("country/ocean"),
        "lat_lon": lat_lon,
        "collection_date": record.get("collection_date_start"),
        "voucher": voucher,
        "score": score,
    }

    return fasta_text, meta


# SEARCH + SCORE + FETCH FROM BOLD------------------------------------

def search_and_fetch_bold(species, marker, rate_limiter, w, bad_words, cache,
                          max_candidates=10, top_n=1, log=print, length_bands=None):

    try:
        if species not in cache:
            cache[species] = fetch_bold_records(species, rate_limiter, log=log)

        records = [
            r for r in cache[species]
            if marker_matches(r.get("marker_code"), marker) and r.get("nuc")
        ][:max_candidates]

        if not records:
            return []

        scored = [(score_bold_record(r, w, bad_words, length_bands), r) for r in records]
        scored.sort(key=lambda pair: pair[0], reverse=True)

        return [build_bold_result(r, sc) for sc, r in scored[:top_n]]

    except BoldBlockedError:
        raise

    except Exception as e:
        log(e)
        return []
