import customtkinter as ctk
from tkinter import filedialog
from Bio import Entrez, SeqIO
import pandas as pd
import os
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

# NCBI SETTINGS-------------------------------------------

Entrez.email = "samadmalikg@gmail.com"
Entrez.api_key = "a9543111711b0671e59f806f680529ff4607"

df = None

INVALID_CHARS = '<>:"/\\|?*'

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


# SCORING-----------------------------------------------

def score_record(record, w, bad_words):

    raw = 0

    title = record.description.lower()

    # 1.TITLE FILTER

    if any(b in title for b in bad_words):
        raw -= 100

    # 2.LENGTH

    length = len(record.seq)

    if 300 <= length <= 1200:
        length_score = 30
    elif 200 <= length < 300 or 1200 < length <= 2000:
        length_score = 15
    else:
        length_score = 0

    # 3.LOCATION

    source = None
    for f in record.features:
        if f.type == "source":
            source = f.qualifiers
            break

    location_score = 0

    if source:
        location = source.get(
            "geo_loc_name",
            source.get("country", [""])
        )[0].lower()

        group = detect_country_group(location)
        location_score = w.get(group, 0)

    # 4 NORMALISE score

    max_location = max(w.values()) if w else 40

    location_norm = (location_score / max_location) * 40
    length_norm = length_score
    penalty_norm = max(0, 30 - abs(raw) / 5)

    final_score = location_norm + length_norm + penalty_norm

    return round(final_score, 2)

# FETCHIGN FROM NCBI------------------------------------


def get_accession(species, marker, rate_limiter, w, bad_words):

    try:
        query = f'"{species}"[Organism] AND {marker}'
        print("Query:", query)

        rate_limiter.wait()
        handle = Entrez.esearch(db="nucleotide", term=query, retmax=10)
        rec = Entrez.read(handle)
        handle.close()

        if not rec["IdList"]:
            return (None,) * 9

        best = None
        best_score = -999

        for uid in rec["IdList"]:
            try:
                rate_limiter.wait()
                handle = Entrez.efetch(
                    db="nucleotide",
                    id=uid,
                    rettype="gb",
                    retmode="text"
                )

                gb = SeqIO.read(handle, "genbank")
                handle.close()

                sc = score_record(gb, w, bad_words)

                if sc > best_score:
                    best_score = sc
                    best = gb

            except Exception as e:
                print("efetch error:", e)
                continue

        if best is None:
            return (None,) * 9

        organism = best.annotations.get("organism")

        geo_loc = None
        lat_lon = None
        collection_date = None
        voucher = None

        for feature in best.features:
            if feature.type == "source":
                q = feature.qualifiers
                geo_loc = q.get("geo_loc_name", q.get("country", [None]))[0]
                lat_lon = q.get("lat_lon", [None])[0]
                collection_date = q.get("collection_date", [None])[0]
                voucher = q.get("specimen_voucher", [None])[0]
                break

        return (
            best.id,
            best.description,
            len(best.seq),
            organism,
            geo_loc,
            lat_lon,
            collection_date,
            voucher,
            best_score
        )

    except Exception as e:
        print(e)
        return (None,) * 9


def fetch_record(accession, rate_limiter):

    try:
        rate_limiter.wait()

        handle = Entrez.efetch(
            db="nucleotide",
            id=accession,
            rettype="gb",
            retmode="text"
        )

        gb = SeqIO.read(handle, "genbank")
        handle.close()

        fasta_text = gb.format("fasta").strip() + "\n"

        geo_loc = None
        lat_lon = None
        collection_date = None
        voucher = None

        for feature in gb.features:
            if feature.type == "source":
                q = feature.qualifiers
                geo_loc = q.get("geo_loc_name", q.get("country", [None]))[0]
                lat_lon = q.get("lat_lon", [None])[0]
                collection_date = q.get("collection_date", [None])[0]
                voucher = q.get("specimen_voucher", [None])[0]
                break

        meta = {
            "accession": gb.id,
            "title": gb.description,
            "length": len(gb.seq),
            "organism": gb.annotations.get("organism"),
            "geo_loc": geo_loc,
            "lat_lon": lat_lon,
            "collection_date": collection_date,
            "voucher": voucher,
        }

        return fasta_text, meta

    except Exception as e:
        print("efetch error:", accession, e)
        return None


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
