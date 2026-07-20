import os
from collections import defaultdict

import pandas as pd

from common import sanitize

METADATA_FIELDS = [
    ("Species", "species"),
    ("Marker", "marker"),
    ("Source", "source"),
    ("Accession", "accession"),
    ("Organism", "organism"),
    ("Title", "title"),
    ("Length", "length"),
    ("Geo location", "geo_loc"),
    ("Lat/Lon", "lat_lon"),
    ("Collection date", "collection_date"),
    ("Voucher", "voucher"),
    ("Score", "score"),
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


def write_no_matches_table(path, species_list, markers, matched_set):

    rows = []
    for species in species_list:
        statuses = [
            "Yes" if (species, marker) in matched_set else "No"
            for marker in markers
        ]
        if "No" in statuses:
            rows.append((species, statuses))

    if not rows:
        return

    species_width = max([len("Species")] + [len(species) for species, _ in rows])
    col_widths = [max(len(marker), 3) for marker in markers]

    header = "Species".ljust(species_width) + " | " + " | ".join(
        marker.ljust(w) for marker, w in zip(markers, col_widths)
    )
    separator = "-" * species_width + "-+-" + \
        "-+-".join("-" * w for w in col_widths)

    lines = [header, separator]

    for species, statuses in rows:
        line = species.ljust(species_width) + " | " + " | ".join(
            status.ljust(w) for status, w in zip(statuses, col_widths)
        )
        lines.append(line)

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def parse_no_matches_table(path):
    # inverse of write_no_matches_table: reconstructs the exact
    # (species, marker) pairs marked "No", for resuming a partial run
    with open(path, "r", encoding="utf-8") as f:
        lines = [line.rstrip("\n") for line in f if line.strip()]

    if len(lines) < 3:
        return []

    header, _separator, *data_lines = lines

    markers = [part.strip() for part in header.split("|")[1:]]

    pending = []
    for line in data_lines:
        parts = [part.strip() for part in line.split("|")]
        species = parts[0]
        statuses = parts[1:]
        for marker, status in zip(markers, statuses):
            if status == "No":
                pending.append((species, marker))

    return pending


def build_summary_dataframe(results, species_list, markers):
    # one pass over results, tallying counts per species instead of
    # re-scanning the whole list once per species
    marker_counts = defaultdict(lambda: defaultdict(int))
    source_counts = defaultdict(lambda: defaultdict(int))

    for species, marker, _, meta in results:
        marker_counts[species][marker] += 1
        source = meta.get("source") or "Unknown"
        source_counts[species][source] += 1

    rows = []

    for species in species_list:
        row = {"Species": species}

        for marker in markers:
            row[f"{marker}_count"] = marker_counts[species].get(marker, 0)

        row["NCBI_count"] = source_counts[species].get("NCBI", 0)
        row["BOLD_count"] = source_counts[species].get("BOLD", 0)
        row["Total_count"] = sum(marker_counts[species].values())

        rows.append(row)

    columns = ["Species"] + [f"{marker}_count" for marker in markers] + \
        ["NCBI_count", "BOLD_count", "Total_count"]

    return pd.DataFrame(rows, columns=columns)


NON_MARKER_COUNT_COLUMNS = {"NCBI_count", "BOLD_count", "Total_count"}


def merge_summary_dataframe(baseline_df, results):
    # Resuming only re-searches (species, marker) pairs that had zero
    # matches in the previous run (see parse_no_matches_table), so every
    # count `results` contributes here is additive against the baseline -
    # no existing non-zero cell is ever touched or overwritten.
    df = baseline_df.set_index("Species")

    marker_deltas = defaultdict(lambda: defaultdict(int))
    source_deltas = defaultdict(lambda: defaultdict(int))

    for species, marker, _, meta in results:
        marker_deltas[species][marker] += 1
        source = meta.get("source") or "Unknown"
        source_deltas[species][source] += 1

    for species, marker_counts in marker_deltas.items():
        if species not in df.index:
            df.loc[species] = 0

        for marker, count in marker_counts.items():
            col = f"{marker}_count"
            if col not in df.columns:
                df[col] = 0
            df.loc[species, col] = count

        df.loc[species, "Total_count"] += sum(marker_counts.values())

        for source, count in source_deltas[species].items():
            col = f"{source}_count"
            if col in df.columns:
                df.loc[species, col] += count

    count_cols = [c for c in df.columns if c.endswith("_count")]
    df[count_cols] = df[count_cols].fillna(0).astype(int)

    return df.reset_index()


def merge_matched_set(baseline_df, results):
    # Reconstructs the full (species, marker) matched set - every pair
    # with a non-zero count in the previous run's summary, unioned with
    # whatever this resumed run just found.
    marker_columns = [
        c for c in baseline_df.columns
        if c.endswith("_count") and c not in NON_MARKER_COUNT_COLUMNS
    ]

    matched = set()
    for _, row in baseline_df.iterrows():
        for col in marker_columns:
            if row[col] > 0:
                matched.add((row["Species"], col[:-len("_count")]))

    for species, marker, _, _ in results:
        matched.add((species, marker))

    return matched


def write_summary_csv(path, results, species_list, markers):
    df = build_summary_dataframe(results, species_list, markers)
    df.to_csv(path, index=False)


def write_zero_species_csv(path, retrieval_data):
    # species that returned zero sequences across every marker/source -
    # a plain single-column list, easy to paste back into the species
    # textbox for a follow-up retry run
    zero_df = retrieval_data.loc[retrieval_data["Total_count"] == 0, ["Species"]]
    zero_df.to_csv(path, index=False)


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
