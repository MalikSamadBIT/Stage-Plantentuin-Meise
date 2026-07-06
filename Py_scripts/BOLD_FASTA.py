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


# FETCHING FASTA + METADATA FROM BOLD------------------------------------

def get_marker_columns(dataframe):
    return [c for c in dataframe.columns if c.endswith("_accession")]


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


# GUI SETUP---------------------------------------
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

app = ctk.CTk()
app.geometry("1250x820")
app.title("BOLD FASTA Export")


# LEFT PANEL--------------------------------------------------------

left_container = ctk.CTkFrame(app)
left_container.pack(side="left", fill="both", expand=True, padx=10, pady=10)

scroll = ctk.CTkScrollableFrame(left_container)
scroll.pack(fill="both", expand=True)


# RIGHT PANEL (output structure preview)------------------------------

right = ctk.CTkFrame(app, width=320)
right.pack(side="right", fill="y", padx=10, pady=10)

ctk.CTkLabel(right, text="📂 OUTPUT STRUCTURE", font=(
    "Arial", 18, "bold")).pack(pady=10)

preview_label = ctk.CTkLabel(
    right,
    text="",
    justify="left",
    anchor="w",
    font=("Consolas", 13)
)
preview_label.pack(fill="x", padx=10, pady=10, anchor="w")


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


ctk.CTkButton(scroll, text="Select CSV File (with *_accession columns)",
              command=load).pack(fill="x", pady=5)
ctk.CTkLabel(scroll, textvariable=file_path).pack(anchor="w", pady=(0, 10))

ctk.CTkButton(scroll, text="Select Output Folder",
              command=choose_output).pack(fill="x", pady=5)
ctk.CTkLabel(scroll, textvariable=output_dir).pack(anchor="w", pady=(0, 10))


# OUTPUT OPTIONS-----------------------------------------------------------------

ctk.CTkLabel(scroll, text="🗂 OUTPUT OPTIONS", font=(
    "Arial", 16, "bold")).pack(anchor="w", pady=(10, 5))

separate_species_var = ctk.BooleanVar(value=True)
separate_marker_var = ctk.BooleanVar(value=True)
save_metadata_var = ctk.BooleanVar(value=True)


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
    text="Save sequence metadata from BOLD (.txt), matching the FASTA grouping",
    variable=save_metadata_var,
    command=update_preview
)
metadata_checkbox.pack(anchor="w", pady=2)

update_preview()


# SETTINGS-----------------------------------------------------------------------------


ctk.CTkLabel(scroll, text="⚙ SETTINGS", font=(
    "Arial", 16, "bold")).pack(anchor="w", pady=(10, 5))

ctk.CTkLabel(scroll, text="Min. interval between BOLD requests (s)").pack(
    anchor="w")
sleep_entry = ctk.CTkEntry(scroll)
sleep_entry.insert(0, "1.0")
sleep_entry.pack(fill="x", pady=5)


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

    app.after(
        0,
        lambda: run_button.configure(state="disabled")
    )

    app.after(
        0,
        lambda: status_label.configure(text="Fetching...")
    )

    global df

    if df is None or not output_dir.get():
        app.after(
            0,
            lambda: status_label.configure(
                text="Select an input file and output folder first!"
            )
        )
        app.after(
            0,
            lambda: run_button.configure(state="normal")
        )
        return

    marker_cols = get_marker_columns(df)

    if not marker_cols:
        app.after(
            0,
            lambda: status_label.configure(
                text="No '*_accession' columns found in the input file!"
            )
        )
        app.after(
            0,
            lambda: run_button.configure(state="normal")
        )
        return

    rate_limiter = RateLimiter(float(sleep_entry.get()))

    jobs = []
    for _, row in df.iterrows():
        species = row["Name"]

        for col in marker_cols:
            accession = row[col]

            if pd.notna(accession) and str(accession).strip():
                marker = col[: -len("_accession")]
                accession = str(accession).strip()

                jobs.append((species, marker, accession))

    total_jobs = len(jobs)

    if total_jobs == 0:
        app.after(
            0,
            lambda: status_label.configure(
                text="No accession numbers found to fetch!"
            )
        )
        app.after(
            0,
            lambda: run_button.configure(state="normal")
        )
        return

    completed = 0
    start_time = time.time()

    results = []
    blocked = False

    for species, marker, accession in jobs:

        try:
            record = fetch_bold_record(accession, rate_limiter)
        except BoldBlockedError as e:
            print(e)
            blocked = True
            break

        if record:
            fasta_text, meta = record
            meta = {"species": species, "marker": marker, **meta}
            results.append((species, marker, fasta_text, meta))

        completed += 1

        elapsed = time.time() - start_time

        avg_time = elapsed / completed

        remaining = avg_time * (total_jobs - completed)

        mins = int(remaining // 60)
        secs = int(remaining % 60)

        app.after(
            0,
            lambda p=completed / total_jobs: progress.set(p)
        )

        app.after(
            0,
            lambda c=completed: progress_label.configure(
                text=f"{c}/{total_jobs} completed"
            )
        )

        app.after(
            0,
            lambda m=mins, s=secs: time_label.configure(
                text=f"Estimated time per sample: {m}m {s}s"
            )
        )

    write_results(
        results,
        output_dir.get(),
        separate_species_var.get(),
        separate_marker_var.get(),
        save_metadata_var.get()
    )

    app.after(
        0,
        lambda: run_button.configure(state="normal")
    )

    if blocked:
        app.after(
            0,
            lambda: status_label.configure(
                text="BOLD blocked the requests - stopped early. "
                     "Partial results saved. Try again later with a "
                     "longer request interval."
            )
        )
    else:
        app.after(
            0,
            lambda: status_label.configure(
                text=f"Finished! {len(results)}/{total_jobs} sequences saved."
            )
        )
        app.after(
            0,
            lambda: progress.set(1)
        )
        app.after(
            0,
            lambda: time_label.configure(
                text="Estimated time per sample: 0s"
            )
        )


def start_run():

    thread = threading.Thread(
        target=run_search,
        daemon=True
    )

    thread.start()


run_button = ctk.CTkButton(
    scroll,
    text="▶ FETCH FASTA",
    command=start_run
)

run_button.pack(fill="x", pady=10)


app.mainloop()
