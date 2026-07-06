import customtkinter as ctk
from tkinter import filedialog
import requests
import json
import pandas as pd
import os
import time
import threading

# BOLD API SETTINGS-----------------------------------------

BOLD_BASE = "https://portal.boldsystems.org/api"

df = None

INVALID_CHARS = '<>:"/\\|?*'


def sanitize(name):
    name = str(name).strip()
    for ch in INVALID_CHARS:
        name = name.replace(ch, "_")
    return name

# RATE LIMITER-----------------------------------------------


class RateLimiter:

    def __init__(self, min_interval):
        self.min_interval = min_interval
        self.lock = threading.Lock()
        self.last_call = 0.0

    def wait(self):
        with self.lock:
            now = time.time()
            sleep_for = self.min_interval - (now - self.last_call)

            if sleep_for > 0:
                time.sleep(sleep_for)

            self.last_call = time.time()


# HTTP WITH RETRY / BACKOFF-----------------------------------

class BoldBlockedError(Exception):
    """Raised when BOLD keeps refusing requests (e.g. Cloudflare block)."""
    pass


def bold_request(url, params, max_retries=4, timeout=30):

    delay = 5

    for attempt in range(max_retries):
        try:
            r = requests.get(url, params=params, timeout=timeout)
        except requests.RequestException as e:
            print("BOLD network error:", e)
            time.sleep(delay)
            delay *= 2
            continue

        if r.status_code == 200:
            return r

        if r.status_code in (403, 429) or r.status_code >= 500:
            print(
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

# COUNTRY GROUPING-----------------------------------------


def detect_country_group(location: str):
    location = (location or "").lower()

    if any(x in location for x in ["belgium", "belgië", "belgique"]):
        return "belgium"

    if any(x in location for x in [
        "netherlands", "nederland",
        "germany", "deutschland",
        "france", "frankrijk",
        "luxembourg", "luxemburg"
    ]):
        return "neighbor"

    if location:
        return "europe"

    return "unknown"


# MARKER MATCHING---------------------------------------------

def marker_matches(record_marker, wanted_marker):
    if not record_marker or not wanted_marker:
        return False

    def norm(s):
        return sorted(p for p in s.strip().lower().replace(" ", "").split("-") if p)

    return norm(record_marker) == norm(wanted_marker)


# SCORING-----------------------------------------------

def score_record(record, w, bad_words):

    raw = 0

    title = " ".join(filter(None, [
        record.get("identification"),
        record.get("notes"),
        record.get("short_note")
    ])).lower()

    # 1.TITLE FILTER

    if any(b in title for b in bad_words):
        raw -= 100

    # 2.LENGTH

    length = record.get("nuc_basecount") or 0

    if 300 <= length <= 1200:
        length_score = 30
    elif 200 <= length < 300 or 1200 < length <= 2000:
        length_score = 15
    else:
        length_score = 0

    # 3.LOCATION

    location = (record.get("country/ocean") or "").lower()

    group = detect_country_group(location)
    location_score = w.get(group, 0)

    # 4 NORMALISE score

    max_location = max(w.values()) if w else 40

    location_norm = (location_score / max_location) * 40
    length_norm = length_score
    penalty_norm = max(0, 30 - abs(raw) / 5)

    final_score = location_norm + length_norm + penalty_norm

    return round(final_score, 2)


def bold_request(url, params, rate_limiter, max_retries=4, timeout=30):

    delay = 5

    for attempt in range(max_retries):
        rate_limiter.wait()

        try:
            r = requests.get(url, params=params, timeout=timeout)
        except requests.RequestException as e:
            print("BOLD network error:", e)
            time.sleep(delay)
            delay *= 2
            continue

        if r.status_code == 200:
            return r

        if r.status_code in (403, 429) or r.status_code >= 500:
            print(
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


def fetch_bold_records(species):

    try:
        pre = bold_request(
            f"{BOLD_BASE}/query/preprocessor",
            {"query": f"tax:{species}"}
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
            {"query": ";".join(matched), "extent": "full"}
        )

        query_id = q.json().get("query_id")

        if not query_id:
            return []

        dl = bold_request(
            f"{BOLD_BASE}/documents/{query_id}/download",
            {"format": "json"}
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
        print("BOLD query error:", e)
        return []

# FETCHING------------------------------------------------------------------------------------


def get_accession(species, marker, sleep_time, w, bad_words, cache):

    try:
        if species not in cache:
            cache[species] = fetch_bold_records(species)
            time.sleep(sleep_time)

        records = [
            r for r in cache[species]
            if marker_matches(r.get("marker_code"), marker)
        ]

        if not records:
            return (None,) * 9

        best = None
        best_score = -999

        for r in records:
            sc = score_record(r, w, bad_words)

            if sc > best_score:
                best_score = sc
                best = r

        if best is None:
            return (None,) * 9

        coord = best.get("coord")
        lat_lon = (
            f"{coord[0]},{coord[1]}"
            if isinstance(coord, list) and len(coord) == 2
            else None
        )

        voucher = best.get("museumid") or best.get("sampleid")

        return (
            best.get("processid"),
            best.get("identification"),
            best.get("nuc_basecount"),
            best.get("species"),
            best.get("country/ocean"),
            lat_lon,
            best.get("collection_date_start"),
            voucher,
            best_score
        )

    except BoldBlockedError:
        raise

    except Exception as e:
        print(e)
        return (None,) * 9


def wrap_sequence(seq, width=70):
    return "\n".join(seq[i:i + width] for i in range(0, len(seq), width))


def fetch_bold_record(processid, rate_limiter):

    try:
        # step 1: validate/resolve the search term
        pre = bold_request(
            f"{BOLD_BASE}/query/preprocessor",
            {"query": f"ids:processid:{processid}"},
            rate_limiter
        )

        terms = pre.json().get("successful_terms", [])
        matched = [t["matched"] for t in terms if t.get("matched")]

        if not matched:
            return None

        # step 2: exchange the resolved term for a query_id token
        q = bold_request(
            f"{BOLD_BASE}/query",
            {"query": ";".join(matched), "extent": "full"},
            rate_limiter
        )

        query_id = q.json().get("query_id")

        if not query_id:
            return None

        # step 3: redeem the token for the actual record(s), as JSONL
        dl = bold_request(
            f"{BOLD_BASE}/documents/{query_id}/download",
            {"format": "json"},
            rate_limiter
        )

        records = [
            json.loads(line) for line in dl.text.splitlines() if line.strip()
        ]

        if not records:
            return None

        rec = next(
            (r for r in records if r.get("processid") == processid),
            records[0]
        )

        nuc = rec.get("nuc")

        if not nuc:
            return None

        header = f">{rec.get('processid')} {rec.get('identification') or ''}".strip(
        )
        fasta_text = header + "\n" + wrap_sequence(nuc) + "\n"

        coord = rec.get("coord")
        lat_lon = (
            f"{coord[0]},{coord[1]}"
            if isinstance(coord, list) and len(coord) == 2
            else None
        )

        voucher = rec.get("museumid") or rec.get("sampleid")

        meta = {
            "accession": rec.get("processid"),
            "title": rec.get("identification"),
            "length": rec.get("nuc_basecount"),
            "organism": rec.get("species"),
            "geo_loc": rec.get("country/ocean"),
            "lat_lon": lat_lon,
            "collection_date": rec.get("collection_date_start"),
            "voucher": voucher,
        }

        return fasta_text, meta

    except BoldBlockedError:
        raise

    except Exception as e:
        print("BOLD fetch error:", processid, e)
        return None


# METADATA FORMATTING (same layout as NCBI_FASTA_GUI.py)------------------

METADATA_FIELDS = [
    ("Species", "species"),
    ("Marker", "marker"),
    ("Accession", "accession"),
    ("Organism", "organism"),
    ("Title", "title"),
    ("Length", "length"),
    ("Geo location", "geo_loc"),
    ("Lat/Lon", "lat_lon"),
    ("Collection date", "collection_date"),
    ("Voucher", "voucher"),
]


def format_metadata_block(meta):
    header = f"{meta.get('species')} - {meta.get('marker')}"
    lines = [header, "=" * len(header)]

    for label, key in METADATA_FIELDS:
        value = meta.get(key)
        lines.append(
            f"{label:<16}: {value if value not in (None, '') else '-'}")

    return "\n".join(lines)


def write_metadata_txt(path, meta_list):
    blocks = [format_metadata_block(meta) for meta in meta_list]

    with open(path, "w", encoding="utf-8") as f:
        f.write(("\n\n" + ("-" * 40) + "\n\n").join(blocks) + "\n")


def write_results(results, base_dir, separate_species, separate_marker, save_metadata):

    groups = {}

    for species, marker, text, meta in results:
        key_parts = []

        if separate_species:
            key_parts.append(sanitize(species))

        if separate_marker:
            key_parts.append(sanitize(marker))

        if not key_parts:
            key_parts = ["all_sequences"]

        key = tuple(key_parts)
        group = groups.setdefault(key, {"fasta": [], "meta": []})
        group["fasta"].append(text)
        group["meta"].append(meta)

    for key_parts, group in groups.items():

        if key_parts == ("all_sequences",):
            folder = base_dir
        else:
            folder = os.path.join(base_dir, *key_parts)

        os.makedirs(folder, exist_ok=True)

        base_name = key_parts[-1]

        fasta_path = os.path.join(folder, f"{base_name}.fasta")
        with open(fasta_path, "w", encoding="utf-8") as f:
            f.write("".join(group["fasta"]))

        if save_metadata:
            meta_path = os.path.join(folder, f"{base_name}_metadata.txt")
            write_metadata_txt(meta_path, group["meta"])
