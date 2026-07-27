import customtkinter as ctk
from tkinter import filedialog
import pandas as pd
import os
import time
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

from common import RateLimiter, load_config, save_config, strip_hybrid_marker
from ncbi_client import search_and_fetch_ncbi, configure_entrez
from bold_client import BoldBlockedError, search_and_fetch_bold
from output import (
    write_results, write_no_matches_table, build_summary_dataframe,
    write_zero_species_csv, parse_no_matches_table,
    merge_summary_dataframe, merge_matched_set
)
from retrieval_rate_tab import build_retrieval_rate_tab
from msa_tab import build_msa_tab
from database_tab import build_database_tab
from blast_tab import build_blast_tab
from synonym_tab import build_synonym_tab
import database

df = None
retrieval_data = None
resume_jobs = None

resume_baseline_summary = None


# GUI SETUP---------------------------------------
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

app = ctk.CTk()
app.geometry("1250x820")
app.title("NCBI / BOLD Pipeline")


# TABS------------------------------------------------------------
tabs = ctk.CTkTabview(app)
tabs.pack(fill="both", expand=True, padx=10, pady=10)

Home = tabs.add("Home")
Fetch_Fasta = tabs.add("Fetch FASTA")
Settings = tabs.add("Settings")
Retrieval_Rate = tabs.add("Retrieval Rate")
Synonyms = tabs.add("Synonym search")
MSA = tabs.add("MSA")
Database_tab = tabs.add("Database")
BLAST = tabs.add("BLAST")
Terminal = tabs.add("Terminal")

settings_scroll = ctk.CTkScrollableFrame(Settings)
settings_scroll.pack(fill="both", expand=True, padx=10, pady=10)

build_retrieval_rate_tab(Retrieval_Rate, lambda: retrieval_data, app)
build_msa_tab(MSA, app)
build_database_tab(Database_tab, app)
build_blast_tab(BLAST, app)
build_synonym_tab(Synonyms, app)


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
        retry_ncbi_checkbox.pack_forget()
        batch_size_label.pack_forget()
        batch_size_entry.pack_forget()
        batch_pause_label.pack_forget()
        batch_pause_entry.pack_forget()
        sleep_entry.delete(0, "end")
        sleep_entry.insert(0, "0.1")
    elif value == "BOLD":
        workers_label.pack_forget()
        workers_entry.pack_forget()
        retry_bold_checkbox.pack_forget()
        retry_ncbi_checkbox.pack(anchor="w", pady=(0, 10))
        batch_size_label.pack(anchor="w")
        batch_size_entry.pack(fill="x", pady=5)
        batch_pause_label.pack(anchor="w")
        batch_pause_entry.pack(fill="x", pady=5)
        sleep_entry.delete(0, "end")
        sleep_entry.insert(0, "1.0")
    else:  # NCBI + BOLD
        workers_label.pack(anchor="w", after=sleep_entry)
        workers_entry.pack(fill="x", pady=5, after=workers_label)
        retry_bold_checkbox.pack_forget()
        retry_ncbi_checkbox.pack_forget()
        batch_size_label.pack(anchor="w")
        batch_size_entry.pack(fill="x", pady=5)
        batch_pause_label.pack(anchor="w")
        batch_pause_entry.pack(fill="x", pady=5)
        sleep_entry.delete(0, "end")
        sleep_entry.insert(0, "0.1")


source_selector = ctk.CTkSegmentedButton(
    scroll,
    values=["NCBI", "BOLD", "NCBI + BOLD"],
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

retry_ncbi_var = ctk.BooleanVar(value=False)

retry_ncbi_checkbox = ctk.CTkCheckBox(
    scroll,
    text="Retry BOLD no-matches with NCBI",
    variable=retry_ncbi_var
)
# only shown when BOLD is the selected source


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


# RESUME FROM A PARTIAL RUN-----------------------------------------------------------
# overrides the species textbox/CSV and marker checkboxes

ctk.CTkLabel(scroll, text="🔁 RESUME", font=(
    "Arial", 16, "bold")).pack(anchor="w", pady=(5, 2))

resume_status_label = ctk.CTkLabel(
    scroll, text="Not resuming - using species/markers above.", text_color="gray"
)
resume_status_label.pack(anchor="w", pady=(0, 5))


def load_resume_file():
    global resume_jobs, resume_baseline_summary

    path = filedialog.askopenfilename(
        title="Select a previous run's no_matches.txt",
        filetypes=[("Text files", "*.txt")]
    )

    if not path:
        return

    try:
        pending = parse_no_matches_table(path)
    except Exception as e:
        resume_status_label.configure(
            text=f"Failed to read that file: {e}", text_color="red"
        )
        return

    if not pending:
        resume_status_label.configure(
            text="That file has no missing species/marker combinations "
                 "to resume (or isn't a no_matches.txt file).",
            text_color="red"
        )
        return

    resume_jobs = pending

    # no_matches.txt/summary.csv get merged back into the full dataset instead of being replaced by just this batch's results
    run_folder = os.path.dirname(path)
    summary_path = os.path.join(run_folder, "summary.csv")

    baseline_note = ""
    if os.path.exists(summary_path):
        try:
            resume_baseline_summary = pd.read_csv(summary_path)
        except Exception as e:
            resume_baseline_summary = None
            baseline_note = f" (couldn't read summary.csv alongside it: {e})"
    else:
        resume_baseline_summary = None
        baseline_note = (
            " (no summary.csv found alongside it - no_matches.txt/summary.csv "
            "from this run will only reflect the resumed batch, not the full "
            "dataset)"
        )

    if not output_dir.get():
        output_dir.set(run_folder)

    resume_status_label.configure(
        text=f"Resuming {len(resume_jobs)} missing species/marker "
        f"combination(s) from {os.path.basename(path)}.{baseline_note}",
        text_color="orange" if not baseline_note else "red"
    )


def clear_resume():
    global resume_jobs, resume_baseline_summary
    resume_jobs = None
    resume_baseline_summary = None
    resume_status_label.configure(
        text="Not resuming - using species/markers above.", text_color="gray"
    )


resume_button_frame = ctk.CTkFrame(scroll, fg_color="transparent")
resume_button_frame.pack(fill="x", pady=(0, 10))

ctk.CTkButton(
    resume_button_frame, text="Load no_matches.txt to resume",
    command=load_resume_file
).pack(side="left", padx=(0, 5))

ctk.CTkButton(
    resume_button_frame, text="Clear", command=clear_resume, width=60
).pack(side="left")


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
save_summary_var = ctk.BooleanVar(value=True)
save_zero_species_var = ctk.BooleanVar(value=True)


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

    if save_summary_var.get():
        text += "\n  summary.csv"

    if save_zero_species_var.get():
        text += "\n  zero_species.csv"

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

summary_checkbox = ctk.CTkCheckBox(
    scroll,
    text="Save per-species sequence count summary (summary.csv)",
    variable=save_summary_var,
    command=update_preview
)
summary_checkbox.pack(anchor="w", pady=2)

zero_species_checkbox = ctk.CTkCheckBox(
    scroll,
    text="Save list of species with zero sequences (zero_species.csv)",
    variable=save_zero_species_var,
    command=update_preview
)
zero_species_checkbox.pack(anchor="w", pady=2)


# DATABASE (alongside the file outputs)---------------------------------------------------------

save_database_var = ctk.BooleanVar(value=False)
db_path = ctk.StringVar()


def choose_database():
    path = filedialog.asksaveasfilename(
        title="Select or create a database file",
        defaultextension=".db",
        filetypes=[("SQLite database", "*.db"), ("All files", "*.*")],
        confirmoverwrite=False  # existing .db file = keep adding to it, not overwrite
    )
    if path:
        db_path.set(path)


database_checkbox = ctk.CTkCheckBox(
    scroll,
    text="Also save results to a local database (SQLite)",
    variable=save_database_var
)
database_checkbox.pack(anchor="w", pady=(10, 2))

ctk.CTkButton(scroll, text="Select/Create Database File",
              command=choose_database).pack(fill="x", pady=5)
ctk.CTkLabel(scroll, textvariable=db_path).pack(anchor="w", pady=(0, 10))


# SETTINGS-----------------------------------------------------------------------------

# NCBI CREDENTIALS-----------------------------------------------------------------
ctk.CTkLabel(settings_scroll, text="🔑 NCBI CREDENTIALS", font=(
    "Arial", 16, "bold")).pack(anchor="w", pady=(5, 5))

ctk.CTkLabel(settings_scroll, text="NCBI email (required)").pack(anchor="w")
ncbi_email_entry = ctk.CTkEntry(
    settings_scroll, placeholder_text="you@example.com")
ncbi_email_entry.pack(fill="x", pady=5)

ctk.CTkLabel(settings_scroll, text="NCBI API key (optional - raises the rate limit "
             "from 3 to 10 requests/s)").pack(anchor="w")
ncbi_api_key_entry = ctk.CTkEntry(
    settings_scroll, placeholder_text="API key", show="*")
ncbi_api_key_entry.pack(fill="x", pady=5)

_saved_config = load_config()
ncbi_email_entry.insert(0, _saved_config.get("ncbi_email", ""))
ncbi_api_key_entry.insert(0, _saved_config.get("ncbi_api_key", ""))


ctk.CTkLabel(settings_scroll, text="⚙ SETTINGS", font=(
    "Arial", 16, "bold")).pack(anchor="w", pady=(10, 5))

strip_hybrid_var = ctk.BooleanVar(value=False)

ctk.CTkCheckBox(
    settings_scroll,
    text="Strip hybrid marker (×) from species names before searching, "
         "e.g. \"Equisetum ×litorale\" -> \"Equisetum litorale\"",
    variable=strip_hybrid_var
).pack(anchor="w", pady=(0, 10))

ctk.CTkLabel(settings_scroll, text="Min. interval between requests (s)").pack(
    anchor="w")
sleep_entry = ctk.CTkEntry(settings_scroll)
sleep_entry.insert(0, "0.1")
sleep_entry.pack(fill="x", pady=5)

workers_label = ctk.CTkLabel(
    settings_scroll, text="Concurrent workers (NCBI only)")
workers_label.pack(anchor="w")
workers_entry = ctk.CTkEntry(settings_scroll)
workers_entry.insert(0, "5")
workers_entry.pack(fill="x", pady=5)

ctk.CTkLabel(settings_scroll, text="Candidates to score per search (top N)").pack(
    anchor="w")
candidates_entry = ctk.CTkEntry(settings_scroll)
candidates_entry.insert(0, "10")
candidates_entry.pack(fill="x", pady=5)

ctk.CTkLabel(settings_scroll, text="Results to save per marker (top N)").pack(
    anchor="w")
top_n_entry = ctk.CTkEntry(settings_scroll)
top_n_entry.insert(0, "1")
top_n_entry.pack(fill="x", pady=5)


# LENGTH BANDS (bp)------------------------------------------------------
# Full score band: sequence length gets the full length score.
# Partial score band: extends past the full band on either side and

ctk.CTkLabel(settings_scroll, text="Default full score length band (bp)").pack(
    anchor="w", pady=(10, 0))

length_full_frame = ctk.CTkFrame(settings_scroll, fg_color="transparent")
length_full_frame.pack(fill="x", pady=5)

length_full_min_entry = ctk.CTkEntry(length_full_frame, placeholder_text="min")
length_full_min_entry.insert(0, "300")
length_full_min_entry.pack(side="left", fill="x", expand=True, padx=(0, 5))

length_full_max_entry = ctk.CTkEntry(length_full_frame, placeholder_text="max")
length_full_max_entry.insert(0, "1200")
length_full_max_entry.pack(side="left", fill="x", expand=True)

ctk.CTkLabel(settings_scroll, text="Default partial score length band (bp)").pack(
    anchor="w")

length_partial_frame = ctk.CTkFrame(settings_scroll, fg_color="transparent")
length_partial_frame.pack(fill="x", pady=5)

length_partial_min_entry = ctk.CTkEntry(
    length_partial_frame, placeholder_text="min")
length_partial_min_entry.insert(0, "200")
length_partial_min_entry.pack(side="left", fill="x", expand=True, padx=(0, 5))

length_partial_max_entry = ctk.CTkEntry(
    length_partial_frame, placeholder_text="max")
length_partial_max_entry.insert(0, "2000")
length_partial_max_entry.pack(side="left", fill="x", expand=True)

ctk.CTkLabel(settings_scroll, text="Per-marker overrides (optional)").pack(
    anchor="w", pady=(10, 0))
ctk.CTkLabel(
    settings_scroll,
    text="One per line: MARKER full_min-full_max partial_min-partial_max\n"
         "e.g.  ITS 500-1800 400-2200",
    justify="left",
    text_color="gray",
    font=("Arial", 11)
).pack(anchor="w")

marker_bands_textbox = ctk.CTkTextbox(settings_scroll, height=90)
marker_bands_textbox.pack(fill="x", pady=5)


def parse_marker_length_bands(text):
    overrides = {}

    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        parts = line.split()
        if len(parts) != 3:
            log(f"Skipping malformed length band line: {line!r}")
            continue

        marker, full_range, partial_range = parts

        try:
            full_min, full_max = (int(x) for x in full_range.split("-"))
            partial_min, partial_max = (int(x)
                                        for x in partial_range.split("-"))
        except ValueError:
            log(f"Skipping malformed length band line: {line!r}")
            continue

        overrides[marker.lower()] = {
            "full_min": full_min,
            "full_max": full_max,
            "partial_min": partial_min,
            "partial_max": partial_max,
        }

    return overrides


batch_size_label = ctk.CTkLabel(
    settings_scroll, text="Species per batch (BOLD searches)")
batch_size_entry = ctk.CTkEntry(settings_scroll)
batch_size_entry.insert(0, "10")

batch_pause_label = ctk.CTkLabel(
    settings_scroll, text="Pause between batches, s (BOLD searches)")
batch_pause_entry = ctk.CTkEntry(settings_scroll)
batch_pause_entry.insert(0, "30")
# not packed here - only shown when BOLD or "NCBI + BOLD" is selected


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

    global df, retrieval_data

    if resume_jobs is not None:
        # resume mode: the exact (species, marker) pairs come from a loaded no_matches.txt
        all_jobs = list(resume_jobs)
        species_list = list(dict.fromkeys(
            species for species, marker in all_jobs))
        markers = list(dict.fromkeys(marker for species, marker in all_jobs))

        if not output_dir.get():
            update_status("Select an output folder first!")
            Fetch_Fasta.after(0, lambda: run_button.configure(state="normal"))
            return
    else:
        species_list = list(df["Name"]) if df is not None else []
        species_list += [
            s.strip() for s in species_textbox.get("1.0", "end").split(",")
            if s.strip()
        ]

        if strip_hybrid_var.get():
            species_list = [strip_hybrid_marker(s) for s in species_list]

        species_list = list(dict.fromkeys(s for s in species_list if s))

        if not species_list or not output_dir.get():
            update_status(
                "Select a species CSV/textbox and an output folder first!")
            Fetch_Fasta.after(0, lambda: run_button.configure(state="normal"))
            return

        markers = [m for m, v in marker_vars.items() if v.get()]
        markers += [m.strip()
                    for m in extra_markers.get().split(",") if m.strip()]
        markers = list(dict.fromkeys(markers))

        if not markers:
            update_status("Select at least one marker!")
            Fetch_Fasta.after(0, lambda: run_button.configure(state="normal"))
            return

        all_jobs = [
            (species, marker)
            for marker in markers
            for species in species_list
        ]

    bad_words = [w for w, v in bad_words_default.items() if v.get()]
    bad_words += [w.strip() for w in extra_bad.get().split(",") if w.strip()]
    bad_words = [w.lower() for w in bad_words if w]

    try:
        length_full_min = int(length_full_min_entry.get())
    except ValueError:
        length_full_min = 300

    try:
        length_full_max = int(length_full_max_entry.get())
    except ValueError:
        length_full_max = 1200

    try:
        length_partial_min = int(length_partial_min_entry.get())
    except ValueError:
        length_partial_min = 200

    try:
        length_partial_max = int(length_partial_max_entry.get())
    except ValueError:
        length_partial_max = 2000

    w = {
        "belgium": belgium_s.get(),
        "neighbor": neighbor_s.get(),
        "europe": europe_s.get(),
        "unknown": 0,
        "length_bonus": length_s.get(),
        "bad_title_penalty": bad_penalty_s.get(),
    }

    default_length_bands = {
        "full_min": length_full_min,
        "full_max": length_full_max,
        "partial_min": length_partial_min,
        "partial_max": length_partial_max,
    }

    marker_length_bands = parse_marker_length_bands(
        marker_bands_textbox.get("1.0", "end"))

    def length_bands_for(marker):
        return marker_length_bands.get(marker.lower(), default_length_bands)

    rate_limiter = RateLimiter(float(sleep_entry.get()))

    try:
        max_candidates = max(1, int(candidates_entry.get()))
    except ValueError:
        max_candidates = 10

    try:
        top_n = max(1, int(top_n_entry.get()))
    except ValueError:
        top_n = 1

    source = source_var.get()

    needs_ncbi = source in ("NCBI", "NCBI + BOLD") or (
        source == "BOLD" and retry_ncbi_var.get())

    ncbi_email = ncbi_email_entry.get().strip()
    ncbi_api_key = ncbi_api_key_entry.get().strip()

    if needs_ncbi and not ncbi_email:
        update_status("Enter your NCBI email in the Settings tab first!")
        Fetch_Fasta.after(0, lambda: run_button.configure(state="normal"))
        return

    if needs_ncbi:
        configure_entrez(ncbi_email, ncbi_api_key)

    total_jobs = len(all_jobs)

    if total_jobs == 0:
        update_status("No species/marker combinations to search!")
        Fetch_Fasta.after(0, lambda: run_button.configure(state="normal"))
        return

    # which markers to actually search for a given species

    jobs_by_species = defaultdict(list)
    for species, marker in all_jobs:
        jobs_by_species[species].append(marker)

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
                    search_and_fetch_ncbi, species, marker, rate_limiter, w, bad_words,
                    max_candidates, top_n, log, length_bands_for(marker)
                ): (species, marker)
                for species, marker in all_jobs
            }

            for future in as_completed(future_to_job):
                species, marker = future_to_job[future]

                try:
                    records = future.result()
                except Exception as e:
                    log("job error:", e)
                    records = []

                for fasta_text, meta in records:
                    meta = {"species": species, "marker": marker, **meta}
                    results.append((species, marker, fasta_text, meta))

                completed += 1
                report_progress(completed, total_jobs, start_time)

        if retry_bold_var.get():
            matched_so_far = {(species, marker)
                              for species, marker, _, _ in results}
            retry_jobs = [job for job in all_jobs if job not in matched_so_far]

            if retry_jobs:
                update_status(
                    f"Retrying {len(retry_jobs)} NCBI no-matches with BOLD...")

                # BOLD needs a much slower pace than NCBI
                retry_rate_limiter = RateLimiter(
                    max(float(sleep_entry.get()), 1.0))

                cache = {}
                retry_total = len(retry_jobs)
                retry_completed = 0
                retry_start = time.time()

                for species, marker in retry_jobs:

                    log(f"Retrying {species} ({marker}) on BOLD...")

                    try:
                        records = search_and_fetch_bold(
                            species, marker, retry_rate_limiter, w, bad_words, cache,
                            max_candidates, top_n, log=log,
                            length_bands=length_bands_for(marker)
                        )
                    except BoldBlockedError as e:
                        log(e)
                        blocked = True
                        break

                    for fasta_text, meta in records:
                        meta = {"species": species, "marker": marker, **meta}
                        results.append((species, marker, fasta_text, meta))

                    retry_completed += 1
                    report_progress(
                        retry_completed, retry_total, retry_start, label="BOLD retry: "
                    )

    elif source == "BOLD":

        try:
            batch_size = max(1, int(batch_size_entry.get()))
        except ValueError:
            batch_size = 20

        try:
            batch_pause = max(0.0, float(batch_pause_entry.get()))
        except ValueError:
            batch_pause = 30.0

        species_batches = [
            species_list[i:i + batch_size]
            for i in range(0, len(species_list), batch_size)
        ]

        cache = {}
        completed = 0

        for batch_index, species_batch in enumerate(species_batches):

            for species in species_batch:

                for marker in jobs_by_species[species]:

                    log(
                        f"Searching {species} ({marker}) on BOLD "
                        f"(batch {batch_index + 1}/{len(species_batches)})..."
                    )

                    try:
                        records = search_and_fetch_bold(
                            species, marker, rate_limiter, w, bad_words, cache,
                            max_candidates, top_n, log=log,
                            length_bands=length_bands_for(marker)
                        )
                    except BoldBlockedError as e:
                        log(e)
                        blocked = True
                        break

                    for fasta_text, meta in records:
                        meta = {"species": species, "marker": marker, **meta}
                        results.append((species, marker, fasta_text, meta))

                    completed += 1
                    report_progress(completed, total_jobs, start_time)

                if blocked:
                    break

            if blocked:
                break

            is_last_batch = batch_index == len(species_batches) - 1
            if batch_pause > 0 and not is_last_batch:
                log(f"Pausing {batch_pause}s before next batch...")
                time.sleep(batch_pause)

        if retry_ncbi_var.get():
            matched_so_far = {(species, marker)
                              for species, marker, _, _ in results}
            retry_jobs = [job for job in all_jobs if job not in matched_so_far]

            if retry_jobs:
                update_status(
                    f"Retrying {len(retry_jobs)} BOLD no-matches with NCBI...")

                # NCBI's rate cap
                retry_rate_limiter = RateLimiter(
                    min(float(sleep_entry.get()), 0.1))

                try:
                    retry_max_workers = max(1, int(workers_entry.get()))
                except ValueError:
                    retry_max_workers = 5

                retry_total = len(retry_jobs)
                retry_completed = 0
                retry_start = time.time()

                with ThreadPoolExecutor(max_workers=retry_max_workers) as executor:

                    future_to_job = {
                        executor.submit(
                            search_and_fetch_ncbi, species, marker, retry_rate_limiter, w,
                            bad_words, max_candidates, top_n, log, length_bands_for(
                                marker)
                        ): (species, marker)
                        for species, marker in retry_jobs
                    }

                    for future in as_completed(future_to_job):
                        species, marker = future_to_job[future]

                        try:
                            records = future.result()
                        except Exception as e:
                            log("job error:", e)
                            records = []

                        for fasta_text, meta in records:
                            meta = {"species": species,
                                    "marker": marker, **meta}
                            results.append((species, marker, fasta_text, meta))

                        retry_completed += 1
                        report_progress(
                            retry_completed, retry_total, retry_start, label="NCBI retry: "
                        )

    else:  # NCBI + BOLD

        try:
            max_workers = max(1, int(workers_entry.get()))
        except ValueError:
            max_workers = 5

        try:
            batch_size = max(1, int(batch_size_entry.get()))
        except ValueError:
            batch_size = 20

        try:
            batch_pause = max(0.0, float(batch_pause_entry.get()))
        except ValueError:
            batch_pause = 30.0

        ncbi_rate_limiter = RateLimiter(float(sleep_entry.get()))
        bold_rate_limiter = RateLimiter(max(float(sleep_entry.get()), 2.0))

        species_batches = [
            species_list[i:i + batch_size]
            for i in range(0, len(species_list), batch_size)
        ]

        ncbi_results = {}
        bold_results = {}
        cache = {}

        ncbi_completed = 0
        bold_completed = 0
        bold_start = time.time()

        for batch_index, species_batch in enumerate(species_batches):

            batch_jobs = [
                (species, marker)
                for species in species_batch
                for marker in jobs_by_species[species]
            ]

            # NCBI portion of this batch (concurrent)
            with ThreadPoolExecutor(max_workers=max_workers) as executor:

                future_to_job = {
                    executor.submit(
                        search_and_fetch_ncbi, species, marker, ncbi_rate_limiter, w,
                        bad_words, max_candidates, top_n, log, length_bands_for(
                            marker)
                    ): (species, marker)
                    for species, marker in batch_jobs
                }

                for future in as_completed(future_to_job):
                    job = future_to_job[future]

                    try:
                        records = future.result()
                    except Exception as e:
                        log("job error:", e)
                        records = []

                    if records:
                        ncbi_results[job] = records

                    ncbi_completed += 1
                    report_progress(ncbi_completed, total_jobs,
                                    start_time, label="NCBI: ")

            # BOLD portion of this batch (serial, cached, circuit breaker)
            for species in species_batch:

                for marker in jobs_by_species[species]:

                    log(
                        f"Searching {species} ({marker}) on BOLD "
                        f"(batch {batch_index + 1}/{len(species_batches)})..."
                    )

                    try:
                        records = search_and_fetch_bold(
                            species, marker, bold_rate_limiter, w, bad_words, cache,
                            max_candidates, top_n, log=log,
                            length_bands=length_bands_for(marker)
                        )
                    except BoldBlockedError as e:
                        log(e)
                        blocked = True
                        break

                    if records:
                        bold_results[(species, marker)] = records

                    bold_completed += 1
                    report_progress(bold_completed, total_jobs,
                                    bold_start, label="BOLD: ")

                if blocked:
                    break

            if blocked:
                break

            is_last_batch = batch_index == len(species_batches) - 1
            if batch_pause > 0 and not is_last_batch:
                log(f"Pausing {batch_pause}s before next batch...")
                time.sleep(batch_pause)

        # merge: pool both sources

        all_seen_jobs = set(ncbi_results.keys()) | set(bold_results.keys())

        for job in all_seen_jobs:
            species, marker = job
            pool = ncbi_results.get(job, []) + bold_results.get(job, [])
            pool.sort(key=lambda record: record[1]["score"], reverse=True)

            for fasta_text, meta in pool[:top_n]:
                meta = {"species": species, "marker": marker, **meta}
                results.append((species, marker, fasta_text, meta))

    write_results(
        results,
        output_dir.get(),
        separate_species_var.get(),
        separate_marker_var.get(),
        save_metadata_var.get()
    )

    # resuming only re-searches pairs that previously had zero matches, merge into the previous run's summary.csv

    if resume_jobs is not None and resume_baseline_summary is not None:
        retrieval_data = merge_summary_dataframe(
            resume_baseline_summary, results)
        matched_set = merge_matched_set(resume_baseline_summary, results)
        full_species_list = list(retrieval_data["Species"])
        full_markers = [
            c[:-len("_count")] for c in retrieval_data.columns
            if c.endswith("_count") and c not in
            {"NCBI_count", "BOLD_count", "Total_count"}
        ]
    else:
        matched_set = {(species, marker) for species, marker, _, _ in results}
        # built regardless of the "Save summary.csv" checkbox, so the Retrieval Rate tab always has something to display after a run
        retrieval_data = build_summary_dataframe(
            results, species_list, markers)
        full_species_list = species_list
        full_markers = markers

    if save_no_matches_var.get():
        no_matches_path = os.path.join(output_dir.get(), "no_matches.txt")
        write_no_matches_table(
            no_matches_path, full_species_list, full_markers, matched_set)

    if save_summary_var.get():
        summary_path = os.path.join(output_dir.get(), "summary.csv")
        retrieval_data.to_csv(summary_path, index=False)

    if save_zero_species_var.get():
        zero_species_path = os.path.join(output_dir.get(), "zero_species.csv")
        write_zero_species_csv(zero_species_path, retrieval_data)

    if save_database_var.get() and db_path.get():
        try:
            conn = database.connect(db_path.get())
            run_id = database.create_run(conn, output_dir.get(), source)
            inserted = database.insert_sequences(conn, run_id, results)
            conn.close()
            log(f"Saved {inserted} new sequence(s) to database: {db_path.get()}")
        except Exception as e:
            log(f"Database save failed: {e}")

    Fetch_Fasta.after(0, lambda: run_button.configure(state="normal"))

    if blocked:
        update_status(
            "BOLD blocked the requests - stopped early. "
            "Partial results saved. Try again later with a "
            "longer request interval."
        )
    else:
        update_status(
            f"Finished! {len(results)}/{total_jobs} sequences saved.")
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

log_box = ctk.CTkTextbox(
    top_container, state="disabled", font=("Consolas", 12))
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


def on_closing():
    save_config({
        "ncbi_email": ncbi_email_entry.get().strip(),
        "ncbi_api_key": ncbi_api_key_entry.get().strip(),
    })

    # ThreadPoolExecutor workers spawned by run_search() are non-daemon, so a plain exit would hang until any in-flight NCBI/BOLD calls finish. Force-kill the process instead.
    app.destroy()
    os._exit(0)


app.protocol("WM_DELETE_WINDOW", on_closing)

app.mainloop()
