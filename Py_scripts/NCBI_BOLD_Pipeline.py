import customtkinter as ctk
from tkinter import filedialog
from Bio import Entrez, SeqIO
import requests
import json
import pandas as pd
import os
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

# NCBI AND BOLD SETTINGS-------------------------------------------

Entrez.email = "samadmalikg@gmail.com"
Entrez.api_key = "a9543111711b0671e59f806f680529ff4607"

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


# HTTP WITH RETRY / BACKOFF (BOLD only)-----------------------------------

class BoldBlockedError(Exception):
    """Raised when BOLD keeps refusing requests (e.g. Cloudflare block)."""
    pass


def bold_request(url, params, rate_limiter, max_retries=4, timeout=30):

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


# MARKER MATCHING (BOLD only)---------------------------------------------

def marker_matches(record_marker, wanted_marker):
    if not record_marker or not wanted_marker:
        return False

    def norm(s):
        return sorted(p for p in s.strip().lower().replace(" ", "").split("-") if p)

    return norm(record_marker) == norm(wanted_marker)


# NCBI SCORING (Biopython GenBank record)-----------------------------------------------

def score_record(record, w, bad_words):

    raw = 0

    title = record.description.lower()

    if any(b in title for b in bad_words):
        raw -= 100

    length = len(record.seq)

    if 300 <= length <= 1200:
        length_score = 30
    elif 200 <= length < 300 or 1200 < length <= 2000:
        length_score = 15
    else:
        length_score = 0

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

    max_location = max(w.values()) if w else 40

    location_norm = (location_score / max_location) * 40
    length_norm = length_score
    penalty_norm = max(0, 30 - abs(raw) / 5)

    final_score = location_norm + length_norm + penalty_norm

    return round(final_score, 2)


# BOLD SCORING (plain dict record)-----------------------------------------------

def score_bold_record(record, w, bad_words):

    raw = 0

    title = " ".join(filter(None, [
        record.get("identification"),
        record.get("notes"),
        record.get("short_note")
    ])).lower()

    if any(b in title for b in bad_words):
        raw -= 100

    length = record.get("nuc_basecount") or 0

    if 300 <= length <= 1200:
        length_score = 30
    elif 200 <= length < 300 or 1200 < length <= 2000:
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


# SEARCH + SCORE + FETCH FROM NCBI------------------------------------

def search_and_fetch_ncbi(species, marker, rate_limiter, w, bad_words):

    try:
        query = f'"{species}"[Organism] AND {marker}'
        log("Query:", query)

        rate_limiter.wait()
        handle = Entrez.esearch(db="nucleotide", term=query, retmax=10)
        rec = Entrez.read(handle)
        handle.close()

        if not rec["IdList"]:
            return None

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
                log("efetch error:", e)
                continue

        if best is None:
            return None

        fasta_text = best.format("fasta").strip() + "\n"

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

        meta = {
            "source": "NCBI",
            "accession": best.id,
            "title": best.description,
            "length": len(best.seq),
            "organism": best.annotations.get("organism"),
            "geo_loc": geo_loc,
            "lat_lon": lat_lon,
            "collection_date": collection_date,
            "voucher": voucher,
            "score": best_score,
        }

        return fasta_text, meta

    except Exception as e:
        log(e)
        return None


# FETCHING FROM BOLD------------------------------------------------------
# BOLD's v5 API is a 3-step token flow, and a species query returns every
# marker for that species in one go - so we fetch/cache once per species
# and reuse it across all requested markers instead of re-querying BOLD
# for each marker separately.

def fetch_bold_records(species, rate_limiter):

    try:
        pre = bold_request(
            f"{BOLD_BASE}/query/preprocessor",
            {"query": f"tax:{species}"},
            rate_limiter
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
            rate_limiter
        )

        query_id = q.json().get("query_id")

        if not query_id:
            return []

        dl = bold_request(
            f"{BOLD_BASE}/documents/{query_id}/download",
            {"format": "json"},
            rate_limiter
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


# SEARCH + SCORE + FETCH FROM BOLD------------------------------------
# One cached fetch per species, scored per marker - the winning record
# already has the sequence ("nuc"), so FASTA is built straight from it,
# no second fetch needed for the accession that wins.

def search_and_fetch_bold(species, marker, rate_limiter, w, bad_words, cache):

    try:
        if species not in cache:
            cache[species] = fetch_bold_records(species, rate_limiter)

        records = [
            r for r in cache[species]
            if marker_matches(r.get("marker_code"), marker) and r.get("nuc")
        ]

        if not records:
            return None

        best = None
        best_score = -999

        for r in records:
            sc = score_bold_record(r, w, bad_words)

            if sc > best_score:
                best_score = sc
                best = r

        if best is None:
            return None

        nuc = best.get("nuc")

        header = f">{best.get('processid')} {best.get('identification') or ''}".strip()
        fasta_text = header + "\n" + wrap_sequence(nuc) + "\n"

        coord = best.get("coord")
        lat_lon = (
            f"{coord[0]},{coord[1]}"
            if isinstance(coord, list) and len(coord) == 2
            else None
        )

        voucher = best.get("museumid") or best.get("sampleid")

        meta = {
            "source": "BOLD",
            "accession": best.get("processid"),
            "title": best.get("identification"),
            "length": best.get("nuc_basecount"),
            "organism": best.get("species"),
            "geo_loc": best.get("country/ocean"),
            "lat_lon": lat_lon,
            "collection_date": best.get("collection_date_start"),
            "voucher": voucher,
            "score": best_score,
        }

        return fasta_text, meta

    except BoldBlockedError:
        raise

    except Exception as e:
        log(e)
        return None


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


# GUI SETUP---------------------------------------
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

app = ctk.CTk()
app.geometry("1250x820")
app.title("NCBI / BOLD Pipeline")


# TABS------------------------------------------------------------
tabs = ctk.CTkTabview(app)
tabs.pack(fill="both", expand=True, padx=10, pady=10)

Fetch_Fasta = tabs.add("Fetch FASTA")
Terminal = tabs.add("Terminal")


# LEFT PANEL--------------------------------------------------------

left_container = ctk.CTkFrame(Fetch_Fasta)
left_container.pack(side="left", fill="both", expand=True, padx=10, pady=10)

scroll = ctk.CTkScrollableFrame(left_container)
scroll.pack(fill="both", expand=True)


# RIGHT PANEL (scoring + output structure preview)----------------------

right = ctk.CTkFrame(Fetch_Fasta, width=320)
right.pack(side="right", fill="y", padx=10, pady=10)


# SOURCE SELECTION---------------------------------------------------------

ctk.CTkLabel(scroll, text="🔬 DATA SOURCE", font=(
    "Arial", 16, "bold")).pack(anchor="w", pady=(5, 2))

source_var = ctk.StringVar(value="NCBI")


def on_source_change(value):
    if value == "NCBI":
        workers_label.pack(anchor="w", after=sleep_entry)
        workers_entry.pack(fill="x", pady=5, after=workers_label)
        retry_bold_checkbox.pack(anchor="w", pady=(0, 10))
        sleep_entry.delete(0, "end")
        sleep_entry.insert(0, "0.1")
    else:
        workers_label.pack_forget()
        workers_entry.pack_forget()
        retry_bold_checkbox.pack_forget()
        sleep_entry.delete(0, "end")
        sleep_entry.insert(0, "1.0")


source_selector = ctk.CTkSegmentedButton(
    scroll,
    values=["NCBI", "BOLD"],
    variable=source_var,
    command=on_source_change
)
source_selector.pack(fill="x", pady=(0, 10))

retry_bold_var = ctk.BooleanVar(value=False)

retry_bold_checkbox = ctk.CTkCheckBox(
    scroll,
    text="Retry NCBI no-matches with BOLD",
    variable=retry_bold_var
)
retry_bold_checkbox.pack(anchor="w", pady=(0, 10))


# FILE SECTION----------------------------------------------------------

ctk.CTkLabel(scroll, text="📁 FILE INPUT", font=(
    "Arial", 16, "bold")).pack(anchor="w", pady=(5, 2))

file_path = ctk.StringVar()
output_dir = ctk.StringVar()


def load():
    global df
    path = filedialog.askopenfilename(filetypes=[("CSV", "*.csv")])
    file_path.set(path)
    df = pd.read_csv(path)


def choose_output():
    path = filedialog.askdirectory()
    output_dir.set(path)


ctk.CTkButton(scroll, text="Select CSV File (with 'Name' column)",
              command=load).pack(fill="x", pady=5)
ctk.CTkLabel(scroll, textvariable=file_path).pack(anchor="w", pady=(0, 10))

ctk.CTkLabel(scroll, text="Or enter species names (comma separated)").pack(
    anchor="w")
species_textbox = ctk.CTkTextbox(scroll, height=80)
species_textbox.pack(fill="x", pady=(0, 10))


# MARKERS + BAD WORDS-----------------------------------------------------------------

input_frame = ctk.CTkFrame(scroll)
input_frame.pack(fill="x", pady=10)

markers_frame = ctk.CTkFrame(input_frame)
markers_frame.pack(side="left", fill="both", expand=True, padx=5, pady=5)

bad_frame = ctk.CTkFrame(input_frame)
bad_frame.pack(side="right", fill="both", expand=True, padx=5, pady=5)


# MARKERS
ctk.CTkLabel(markers_frame, text="Markers", font=(
    "Arial", 14, "bold")).pack(anchor="w")

marker_vars = {}
for m in ["ITS", "ITS1", "ITS2", "rbcL", "matK", "trnL", "psbA-trnH"]:
    v = ctk.BooleanVar()
    marker_vars[m] = v
    ctk.CTkCheckBox(markers_frame, text=m, variable=v).pack(anchor="w")

ctk.CTkLabel(markers_frame, text="Extra markers (comma separated)").pack(
    anchor="w", pady=(10, 0))
extra_markers = ctk.CTkEntry(markers_frame)
extra_markers.pack(fill="x", pady=5)


# BAD WORDS
ctk.CTkLabel(bad_frame, text="Filters", font=(
    "Arial", 14, "bold")).pack(anchor="w")

bad_words_default = {
    "whole genome": ctk.BooleanVar(value=True),
    "chromosome": ctk.BooleanVar(value=True),
    "scaffold": ctk.BooleanVar(value=True),
    "contig": ctk.BooleanVar(value=True),
    "assembly": ctk.BooleanVar(value=True),
}

for w, v in bad_words_default.items():
    ctk.CTkCheckBox(bad_frame, text=w, variable=v).pack(anchor="w")

ctk.CTkLabel(bad_frame, text="Extra bad words").pack(anchor="w", pady=(10, 0))
extra_bad = ctk.CTkEntry(bad_frame)
extra_bad.pack(fill="x", pady=5)


# OUTPUT OPTIONS-----------------------------------------------------------------

ctk.CTkLabel(scroll, text="🗂 OUTPUT OPTIONS", font=(
    "Arial", 16, "bold")).pack(anchor="w", pady=(10, 5))

ctk.CTkButton(scroll, text="Select Output Folder",
              command=choose_output).pack(fill="x", pady=5)
ctk.CTkLabel(scroll, textvariable=output_dir).pack(anchor="w", pady=(0, 10))

separate_species_var = ctk.BooleanVar(value=True)
separate_marker_var = ctk.BooleanVar(value=True)
save_metadata_var = ctk.BooleanVar(value=True)
save_no_matches_var = ctk.BooleanVar(value=True)


def update_preview(*args):
    sep_species = separate_species_var.get()
    sep_marker = separate_marker_var.get()
    meta = save_metadata_var.get()

    if sep_species and sep_marker:
        base = "output/\n  <species>/\n    <marker>/\n      <marker>.fasta"
        meta_line = "\n      <marker>_metadata.txt"
    elif sep_species:
        base = "output/\n  <species>/\n    <species>.fasta"
        meta_line = "\n    <species>_metadata.txt"
    elif sep_marker:
        base = "output/\n  <marker>/\n    <marker>.fasta"
        meta_line = "\n    <marker>_metadata.txt"
    else:
        base = "output/\n  all_sequences.fasta"
        meta_line = "\n  all_sequences_metadata.txt"

    text = base + (meta_line if meta else "")

    if save_no_matches_var.get():
        text += "\n  no_matches.txt"

    preview_label.configure(text=text)


def on_species_toggle():
    if separate_species_var.get():
        marker_checkbox.configure(state="normal")
    else:
        marker_checkbox.configure(state="disabled")
        separate_marker_var.set(False)

    update_preview()


species_checkbox = ctk.CTkCheckBox(
    scroll,
    text="Separate FASTA per species (own folder)",
    variable=separate_species_var,
    command=on_species_toggle
)
species_checkbox.pack(anchor="w", pady=2)

marker_checkbox = ctk.CTkCheckBox(
    scroll,
    text="Separate FASTA per marker (subfolder within species)",
    variable=separate_marker_var,
    command=update_preview
)
marker_checkbox.pack(anchor="w", pady=2)

metadata_checkbox = ctk.CTkCheckBox(
    scroll,
    text="Save sequence metadata (.txt), matching the FASTA grouping",
    variable=save_metadata_var,
    command=update_preview
)
metadata_checkbox.pack(anchor="w", pady=2)

no_matches_checkbox = ctk.CTkCheckBox(
    scroll,
    text="Save species x marker match table for incomplete species (no_matches.txt)",
    variable=save_no_matches_var,
    command=update_preview
)
no_matches_checkbox.pack(anchor="w", pady=2)


# SETTINGS-----------------------------------------------------------------------------
# "Concurrent workers" only applies to NCBI. BOLD sits behind Cloudflare
# and blocks aggressively on concurrent/sustained traffic, so the BOLD
# path always fetches one species at a time (see BOLD_ID.py/BOLD_pipeline.py)
# and this control is hidden whenever BOLD is selected.

ctk.CTkLabel(scroll, text="⚙ SETTINGS", font=(
    "Arial", 16, "bold")).pack(anchor="w", pady=(10, 5))

ctk.CTkLabel(scroll, text="Min. interval between requests (s)").pack(
    anchor="w")
sleep_entry = ctk.CTkEntry(scroll)
sleep_entry.insert(0, "0.1")
sleep_entry.pack(fill="x", pady=5)

workers_label = ctk.CTkLabel(scroll, text="Concurrent workers (NCBI only)")
workers_label.pack(anchor="w")
workers_entry = ctk.CTkEntry(scroll)
workers_entry.insert(0, "5")
workers_entry.pack(fill="x", pady=5)


# SCORING SLIDERS (right panel)----------------------------------------------------------------------------

ctk.CTkLabel(right, text="📊 SCORING", font=("Arial", 18, "bold")).pack(pady=10)


def slider(label, default):
    frame = ctk.CTkFrame(right)
    frame.pack(fill="x", pady=8, padx=10)

    ctk.CTkLabel(frame, text=label).pack(anchor="w")

    value = ctk.CTkLabel(frame, text=str(default))
    value.pack(anchor="w")

    s = ctk.CTkSlider(frame, from_=0, to=100)
    s.set(default)

    def update(v):
        value.configure(text=str(int(float(v))))

    s.configure(command=update)
    s.pack(fill="x")

    return s


belgium_s = slider("Belgium boost", 40)
neighbor_s = slider("Neighbor boost", 20)
europe_s = slider("Europe fallback", 5)
length_s = slider("Length bonus", 10)
bad_penalty_s = slider("Bad penalty", 100)


# OUTPUT STRUCTURE PREVIEW (right panel)------------------------------

ctk.CTkLabel(right, text="📂 OUTPUT STRUCTURE", font=(
    "Arial", 18, "bold")).pack(pady=(20, 10))

preview_label = ctk.CTkLabel(
    right,
    text="",
    justify="left",
    anchor="w",
    font=("Consolas", 13)
)
preview_label.pack(fill="x", padx=10, pady=10, anchor="w")

update_preview()


# PROGRESS BAR-------------------------------------------------------------------------------
status_label = ctk.CTkLabel(
    scroll,
    text="Idle"
)
status_label.pack(fill="x", pady=(15, 5))

progress_label = ctk.CTkLabel(
    scroll,
    text="Ready"
)
progress_label.pack(fill="x", pady=(15, 5))

time_label = ctk.CTkLabel(
    scroll,
    text="Estimated time per sample: --"
)
time_label.pack(fill="x")

progress = ctk.CTkProgressBar(scroll)
progress.pack(fill="x", pady=10)

progress.set(0)


# RUN----------------------------------------------------------------------------------

def run_search():

    Fetch_Fasta.after(
        0,
        lambda: run_button.configure(state="disabled")
    )

    update_status("Searching...")

    global df

    species_list = list(df["Name"]) if df is not None else []
    species_list += [
        s.strip() for s in species_textbox.get("1.0", "end").split(",")
        if s.strip()
    ]
    species_list = list(dict.fromkeys(species_list))

    if not species_list or not output_dir.get():
        update_status("Select a species CSV/textbox and an output folder first!")
        Fetch_Fasta.after(0, lambda: run_button.configure(state="normal"))
        return

    markers = [m for m, v in marker_vars.items() if v.get()]
    markers += [m.strip() for m in extra_markers.get().split(",") if m.strip()]
    markers = list(dict.fromkeys(markers))

    if not markers:
        update_status("Select at least one marker!")
        Fetch_Fasta.after(0, lambda: run_button.configure(state="normal"))
        return

    bad_words = [w for w, v in bad_words_default.items() if v.get()]
    bad_words += [w.strip() for w in extra_bad.get().split(",") if w.strip()]
    bad_words = [w.lower() for w in bad_words if w]

    w = {
        "belgium": belgium_s.get(),
        "neighbor": neighbor_s.get(),
        "europe": europe_s.get(),
        "unknown": 0,
        "length_bonus": length_s.get(),
        "bad_title_penalty": bad_penalty_s.get()
    }

    rate_limiter = RateLimiter(float(sleep_entry.get()))

    source = source_var.get()

    all_jobs = [
        (species, marker)
        for marker in markers
        for species in species_list
    ]

    total_jobs = len(all_jobs)

    if total_jobs == 0:
        update_status("No species/marker combinations to search!")
        Fetch_Fasta.after(0, lambda: run_button.configure(state="normal"))
        return

    results = []
    blocked = False

    def report_progress(completed, total, start_time, label=""):
        elapsed = time.time() - start_time
        avg_time = elapsed / completed
        remaining = avg_time * (total - completed)
        mins = int(remaining // 60)
        secs = int(remaining % 60)

        Fetch_Fasta.after(0, lambda p=completed / total: progress.set(p))
        Fetch_Fasta.after(
            0,
            lambda c=completed: progress_label.configure(
                text=f"{label}{c}/{total} completed"
            )
        )
        Fetch_Fasta.after(
            0,
            lambda m=mins, s=secs: time_label.configure(
                text=f"Estimated time per sample: {m}m {s}s"
            )
        )

    start_time = time.time()

    if source == "NCBI":

        try:
            max_workers = max(1, int(workers_entry.get()))
        except ValueError:
            max_workers = 5

        completed = 0

        with ThreadPoolExecutor(max_workers=max_workers) as executor:

            future_to_job = {
                executor.submit(
                    search_and_fetch_ncbi, species, marker, rate_limiter, w, bad_words
                ): (species, marker)
                for species, marker in all_jobs
            }

            for future in as_completed(future_to_job):
                species, marker = future_to_job[future]

                try:
                    record = future.result()
                except Exception as e:
                    log("job error:", e)
                    record = None

                if record:
                    fasta_text, meta = record
                    meta = {"species": species, "marker": marker, **meta}
                    results.append((species, marker, fasta_text, meta))

                completed += 1
                report_progress(completed, total_jobs, start_time)

        if retry_bold_var.get():
            matched_so_far = {(species, marker) for species, marker, _, _ in results}
            retry_jobs = [job for job in all_jobs if job not in matched_so_far]

            if retry_jobs:
                update_status(f"Retrying {len(retry_jobs)} NCBI no-matches with BOLD...")

                # BOLD needs a much gentler pace than NCBI - the "Min. interval"
                # field is tuned for whichever source is currently selected, so
                # reusing it here (likely ~0.1s, set for NCBI) would hammer BOLD
                # and risk an immediate Cloudflare block. Enforce a safe floor
                # instead of trusting the NCBI-tuned value.
                retry_rate_limiter = RateLimiter(max(float(sleep_entry.get()), 1.0))

                cache = {}
                retry_total = len(retry_jobs)
                retry_completed = 0
                retry_start = time.time()

                for species, marker in retry_jobs:

                    log(f"Retrying {species} ({marker}) on BOLD...")

                    try:
                        record = search_and_fetch_bold(
                            species, marker, retry_rate_limiter, w, bad_words, cache
                        )
                    except BoldBlockedError as e:
                        log(e)
                        blocked = True
                        break

                    if record:
                        fasta_text, meta = record
                        meta = {"species": species, "marker": marker, **meta}
                        results.append((species, marker, fasta_text, meta))

                    retry_completed += 1
                    report_progress(
                        retry_completed, retry_total, retry_start, label="BOLD retry: "
                    )

    else:  # BOLD - serial, per-species cache, circuit breaker on blocks

        cache = {}
        completed = 0

        for species in species_list:

            for marker in markers:

                log(f"Searching {species} ({marker}) on BOLD...")

                try:
                    record = search_and_fetch_bold(
                        species, marker, rate_limiter, w, bad_words, cache
                    )
                except BoldBlockedError as e:
                    log(e)
                    blocked = True
                    break

                if record:
                    fasta_text, meta = record
                    meta = {"species": species, "marker": marker, **meta}
                    results.append((species, marker, fasta_text, meta))

                completed += 1
                report_progress(completed, total_jobs, start_time)

            if blocked:
                break

    write_results(
        results,
        output_dir.get(),
        separate_species_var.get(),
        separate_marker_var.get(),
        save_metadata_var.get()
    )

    if save_no_matches_var.get():
        matched_set = {(species, marker) for species, marker, _, _ in results}
        no_matches_path = os.path.join(output_dir.get(), "no_matches.txt")
        write_no_matches_table(no_matches_path, species_list, markers, matched_set)

    Fetch_Fasta.after(0, lambda: run_button.configure(state="normal"))

    if blocked:
        update_status(
            "BOLD blocked the requests - stopped early. "
            "Partial results saved. Try again later with a "
            "longer request interval."
        )
    else:
        update_status(f"Finished! {len(results)}/{total_jobs} sequences saved.")
        Fetch_Fasta.after(0, lambda: progress.set(1))
        Fetch_Fasta.after(
            0,
            lambda: time_label.configure(text="Estimated time per sample: 0s")
        )


def start_run():

    thread = threading.Thread(
        target=run_search,
        daemon=True
    )

    thread.start()


run_button = ctk.CTkButton(
    scroll,
    text="▶ RUN PIPELINE",
    command=start_run
)

run_button.pack(fill="x", pady=10)


# TERMINAL TAB-------------------------------------------------

top_container = ctk.CTkFrame(Terminal)
top_container.pack(side="top", fill="both", expand=True, padx=10, pady=10)

terminal_status_label = ctk.CTkLabel(top_container, text="Idle", anchor="w")
terminal_status_label.pack(fill="x", pady=(0, 10))

log_box = ctk.CTkTextbox(top_container, state="disabled", font=("Consolas", 12))
log_box.pack(fill="both", expand=True)


def write_log(message):
    def append():
        log_box.configure(state="normal")
        log_box.insert("end", message + "\n")
        log_box.see("end")
        log_box.configure(state="disabled")

    Terminal.after(0, append)


def log(*args):
    message = " ".join(str(a) for a in args)
    print(message)
    write_log(message)


def update_status(text):
    Fetch_Fasta.after(0, lambda: status_label.configure(text=text))
    Terminal.after(0, lambda: terminal_status_label.configure(text=text))


app.mainloop()
