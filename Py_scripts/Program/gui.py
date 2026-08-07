import customtkinter as ctk
from tkinter import filedialog
import pandas as pd
import os
import time
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

from common import (
    RateLimiter, load_config, save_config, strip_characters,
    read_csv_robust, fix_mojibake, load_presets, save_presets
)
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
from maps_tab import build_maps_tab
from gap_tab import build_gap_tab
import database

df = None
retrieval_data = None
resume_jobs = None

# how often a Fetch FASTA run re-saves its progress to disk/DB while it's
# still running - see the CHECKPOINTING block in run_search(). Module-level
# so a test can shrink it instead of waiting out a real 30s interval.
CHECKPOINT_INTERVAL_SECONDS = 30

# set by the Stop button, checked between jobs in run_search() - a
# cooperative cancel rather than an abrupt thread-kill, since Python can't
# safely force-terminate a thread mid network-call. Module-level (not
# recreated per run) so the Stop button's command doesn't need to reach
# into a specific run's local state.
cancel_event = threading.Event()


def sleep_or_cancel(total_seconds):
    # a plain time.sleep(batch_pause) can't be interrupted - BOLD's
    # inter-batch pause defaults to 30s and can be set much longer, so
    # cancelling a run shouldn't have to wait one out. Sleeps in short
    # increments instead, returning early the moment cancel_event is set.
    step = 0.5
    elapsed = 0.0
    while elapsed < total_seconds and not cancel_event.is_set():
        time.sleep(min(step, total_seconds - elapsed))
        elapsed += step


resume_baseline_summary = None

_saved_config = load_config()


# GUI SETUP---------------------------------------
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

app = ctk.CTk()
app.geometry("1250x820")
app.title("NCBI / BOLD Pipeline")

# shared across the whole program (Fetch FASTA saving, Database tab, Synonym search, Maps) backend (SQLite file or MySQL server) is chosen once in the Settings tab
db_config = database.DatabaseConfig()
db_config.backend = _saved_config.get("db_backend", "sqlite")
db_config.sqlite_path = _saved_config.get(
    "db_sqlite_path", _saved_config.get("db_path", ""))
db_config.mysql_host = _saved_config.get("db_mysql_host", "localhost")
db_config.mysql_port = _saved_config.get("db_mysql_port", 3306)
db_config.mysql_user = _saved_config.get("db_mysql_user", "")
db_config.mysql_database = _saved_config.get("db_mysql_database", "")
db_config.refresh_display()


report_items = []


shared_species = database.SpeciesList()


# TABS------------------------------------------------------------
tabs = ctk.CTkTabview(app)
tabs.pack(fill="both", expand=True, padx=10, pady=10)

Home = tabs.add("Home")
Settings = tabs.add("Settings")
Fetch_Fasta = tabs.add("Fetch FASTA")
Retrieval_Rate = tabs.add("Retrieval Rate")
Synonyms = tabs.add("Synonym search")
MSA = tabs.add("MSA")
Database_tab = tabs.add("Database")
BLAST = tabs.add("BLAST")
Maps = tabs.add("Maps")
Gap_Report = tabs.add("Gap Report")
Terminal = tabs.add("Terminal")

settings_scroll = ctk.CTkScrollableFrame(Settings)
settings_scroll.pack(fill="both", expand=True, padx=10, pady=10)

build_retrieval_rate_tab(
    Retrieval_Rate, lambda: retrieval_data, app, report_items=report_items)
build_msa_tab(MSA, app, report_items=report_items)
build_database_tab(Database_tab, app, db_config=db_config)
build_blast_tab(BLAST, app)
build_synonym_tab(
    Synonyms, app,
    get_ncbi_credentials=lambda: (
        ncbi_email_entry.get().strip(), ncbi_api_key_entry.get().strip()
    ),
    db_config=db_config,
    report_items=report_items,
    shared_species=shared_species
)
build_maps_tab(Maps, app, db_config=db_config)


def go_to_fetch_fasta():
    load_shared_species()
    tabs.set("Fetch FASTA")


build_gap_tab(
    Gap_Report, app, db_config=db_config, report_items=report_items,
    shared_species=shared_species, go_to_fetch_fasta=go_to_fetch_fasta
)


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
    df = read_csv_robust(path)


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


def compute_species_list():
    species_list = list(df["Name"]) if df is not None else []
    species_list += [
        s.strip() for s in species_textbox.get("1.0", "end").split(",")
        if s.strip()
    ]

    # repairs names that were already mojibaked before reaching this app
    # (see fix_mojibake) - independent of read_csv_robust, which only
    # covers this app's own read of the file
    species_list = [fix_mojibake(s) for s in species_list]

    if strip_chars_var.get():
        chars = strip_chars_entry.get()
        species_list = [strip_characters(s, chars) for s in species_list]

    return list(dict.fromkeys(s for s in species_list if s))


# SHARED SPECIES LIST------------------------------------------------------


shared_species_status = ctk.CTkLabel(
    scroll, textvariable=shared_species.display_var, text_color="gray"
)
shared_species_status.pack(anchor="w", pady=(0, 2))


def load_shared_species():
    global df
    df = None
    file_path.set("")
    species_textbox.delete("1.0", "end")
    species_textbox.insert("1.0", ", ".join(shared_species.names))


def save_shared_species():
    shared_species.set(compute_species_list(), source="Fetch FASTA")


shared_species_button_frame = ctk.CTkFrame(scroll, fg_color="transparent")
shared_species_button_frame.pack(fill="x", pady=(0, 10))

ctk.CTkButton(
    shared_species_button_frame, text="Load shared species list",
    command=load_shared_species
).pack(side="left", padx=(0, 5))

ctk.CTkButton(
    shared_species_button_frame, text="Save as shared species list",
    command=save_shared_species
).pack(side="left")


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
            resume_baseline_summary = read_csv_robust(summary_path)
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

# _saved_config only has "selected_markers" once a previous session has
# actually saved one - None (vs. an empty list) distinguishes "never saved
# before" (fall back to the original all-unchecked default) from "saved
# with nothing checked" (respect that, even though it looks the same as
# never having run this app before)
_saved_markers = _saved_config.get("selected_markers")

marker_vars = {}
for m in ["ITS", "ITS1", "ITS2", "rbcL", "matK", "trnL", "psbA-trnH"]:
    checked = (m in _saved_markers) if _saved_markers is not None else False
    v = ctk.BooleanVar(value=checked)
    marker_vars[m] = v
    ctk.CTkCheckBox(markers_frame, text=m, variable=v).pack(anchor="w")

ctk.CTkLabel(markers_frame, text="Extra markers (comma separated)").pack(
    anchor="w", pady=(10, 0))
extra_markers = ctk.CTkEntry(markers_frame)
extra_markers.insert(0, _saved_config.get("extra_markers", ""))
extra_markers.pack(fill="x", pady=5)


# BAD WORDS
ctk.CTkLabel(bad_frame, text="Filters", font=(
    "Arial", 14, "bold")).pack(anchor="w")

_saved_bad_words = _saved_config.get("selected_bad_words")

bad_words_default = {
    w: ctk.BooleanVar(
        value=(w in _saved_bad_words) if _saved_bad_words is not None else True)
    for w in ["whole genome", "chromosome", "scaffold", "contig", "assembly"]
}

for w, v in bad_words_default.items():
    ctk.CTkCheckBox(bad_frame, text=w, variable=v).pack(anchor="w")

ctk.CTkLabel(bad_frame, text="Extra bad words").pack(anchor="w", pady=(10, 0))
extra_bad = ctk.CTkEntry(bad_frame)
extra_bad.insert(0, _saved_config.get("extra_bad_words", ""))
extra_bad.pack(fill="x", pady=5)


# OUTPUT OPTIONS-----------------------------------------------------------------

ctk.CTkLabel(scroll, text="🗂 OUTPUT OPTIONS", font=(
    "Arial", 16, "bold")).pack(anchor="w", pady=(10, 5))

ctk.CTkButton(scroll, text="Select Output Folder",
              command=choose_output).pack(fill="x", pady=5)
ctk.CTkLabel(scroll, textvariable=output_dir).pack(anchor="w", pady=(0, 10))

separate_species_var = ctk.BooleanVar(
    value=_saved_config.get("separate_species", True))
separate_marker_var = ctk.BooleanVar(
    value=_saved_config.get("separate_marker", True))
save_metadata_var = ctk.BooleanVar(
    value=_saved_config.get("save_metadata", True))
save_no_matches_var = ctk.BooleanVar(
    value=_saved_config.get("save_no_matches", True))
save_summary_var = ctk.BooleanVar(
    value=_saved_config.get("save_summary", True))
save_zero_species_var = ctk.BooleanVar(
    value=_saved_config.get("save_zero_species", True))


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

# a loaded separate_species=False must still disable this checkbox (and
# force separate_marker off), the same invariant on_species_toggle
# enforces live - but that also calls update_preview(), which needs
# preview_label, not created until later in this setup, so just the
# state-sync part is duplicated here rather than calling it directly
if not separate_species_var.get():
    marker_checkbox.configure(state="disabled")
    separate_marker_var.set(False)

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
# the database file itself is shared program-wide chosen once in Settings

save_database_var = ctk.BooleanVar(
    value=_saved_config.get("save_database", False))

database_checkbox = ctk.CTkCheckBox(
    scroll,
    text="Also save results to the database (SQLite or MySQL)",
    variable=save_database_var
)
database_checkbox.pack(anchor="w", pady=(10, 2))

ctk.CTkLabel(
    scroll, textvariable=db_config.display_var, text_color="gray"
).pack(anchor="w", pady=(0, 2))
ctk.CTkLabel(
    scroll, text="(choose/configure the database backend in the Settings tab)",
    text_color="gray", font=("Arial", 11)
).pack(anchor="w", pady=(0, 10))


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

ncbi_email_entry.insert(0, _saved_config.get("ncbi_email", ""))
ncbi_api_key_entry.insert(0, _saved_config.get("ncbi_api_key", ""))


# DATABASE-----------------------------------------------------------------


ctk.CTkLabel(settings_scroll, text="🗄 DATABASE", font=(
    "Arial", 16, "bold")).pack(anchor="w", pady=(15, 5))

ctk.CTkLabel(
    settings_scroll,
    text="Used by \"Fetch FASTA\" (when saving to a database is enabled), "
         "the Database tab, Synonym search, and Maps. Pick a local SQLite "
         "file or a MySQL server - only one backend is active at a time.",
    justify="left", text_color="gray", wraplength=700
).pack(anchor="w", pady=(0, 5))

db_backend_var = ctk.StringVar(
    value="MySQL" if db_config.backend == "mysql" else "SQLite")

sqlite_frame = ctk.CTkFrame(settings_scroll, fg_color="transparent")
mysql_frame = ctk.CTkFrame(settings_scroll, fg_color="transparent")

db_status_label = ctk.CTkLabel(settings_scroll, text_color="gray")


def refresh_db_status():
    db_status_label.configure(
        text=f"Active: {db_config.display_var.get() or '(none)'}",
        text_color="gray"
    )


def choose_database():
    path = filedialog.asksaveasfilename(
        parent=app,
        title="Select or create a database file",
        defaultextension=".db",
        filetypes=[("SQLite database", "*.db"), ("All files", "*.*")],
        confirmoverwrite=False  # existing .db file = keep adding to it, not overwrite
    )
    if path:
        db_config.set_sqlite(path)


ctk.CTkButton(
    sqlite_frame, text="Select/Create Database File", command=choose_database
).pack(fill="x", pady=5)
ctk.CTkLabel(
    sqlite_frame, textvariable=db_config.display_var, text_color="gray"
).pack(anchor="w", pady=(0, 5))


ctk.CTkLabel(mysql_frame, text="MySQL host").pack(anchor="w")
mysql_host_entry = ctk.CTkEntry(mysql_frame)
mysql_host_entry.insert(0, db_config.mysql_host)
mysql_host_entry.pack(fill="x", pady=(0, 5))

ctk.CTkLabel(mysql_frame, text="MySQL port").pack(anchor="w")
mysql_port_entry = ctk.CTkEntry(mysql_frame)
mysql_port_entry.insert(0, str(db_config.mysql_port))
mysql_port_entry.pack(fill="x", pady=(0, 5))

ctk.CTkLabel(mysql_frame, text="MySQL user").pack(anchor="w")
mysql_user_entry = ctk.CTkEntry(mysql_frame)
mysql_user_entry.insert(0, db_config.mysql_user)
mysql_user_entry.pack(fill="x", pady=(0, 5))

ctk.CTkLabel(mysql_frame, text="MySQL password (not saved - re-enter each "
             "session)").pack(anchor="w")
mysql_password_entry = ctk.CTkEntry(mysql_frame, show="*")
mysql_password_entry.pack(fill="x", pady=(0, 5))

ctk.CTkLabel(mysql_frame, text="MySQL database name").pack(anchor="w")
mysql_database_entry = ctk.CTkEntry(mysql_frame)
mysql_database_entry.insert(0, db_config.mysql_database)
mysql_database_entry.pack(fill="x", pady=(0, 5))


def connect_mysql():
    host = mysql_host_entry.get().strip() or "localhost"
    user = mysql_user_entry.get().strip()
    password = mysql_password_entry.get()
    database_name = mysql_database_entry.get().strip()

    if not user or not database_name:
        db_status_label.configure(
            text="MySQL user and database name are required.",
            text_color="red")
        return

    try:
        port = int(mysql_port_entry.get().strip() or "3306")
    except ValueError:
        db_status_label.configure(
            text="MySQL port must be a number.", text_color="red")
        return

    # validate against a throwaway config first - a bad attempt shouldn't
    # switch the active backend out from under a working setup
    test_config = database.DatabaseConfig()
    test_config.set_mysql(host, port, user, password, database_name)

    mysql_connect_button.configure(state="disabled")
    db_status_label.configure(
        text=f"Connecting to {host}:{port}...", text_color="gray")

    def do_connect():
        try:
            conn = database.connect(test_config)
            conn.close()
        except Exception as e:
            # "as e" is deleted when the except block ends
            error_text = str(e)
            settings_scroll.after(
                0, lambda: connect_mysql_failed(error_text))
            return
        settings_scroll.after(
            0,
            lambda: connect_mysql_succeeded(
                host, port, user, password, database_name)
        )

    threading.Thread(target=do_connect, daemon=True).start()


def connect_mysql_failed(error):
    mysql_connect_button.configure(state="normal")
    db_status_label.configure(
        text=f"Connection failed: {error}", text_color="red")


def connect_mysql_succeeded(host, port, user, password, database_name):
    db_config.set_mysql(host, port, user, password, database_name)
    mysql_connect_button.configure(state="normal")
    db_status_label.configure(
        text=f"Connected - active: {db_config.display_var.get()}",
        text_color="green"
    )


mysql_connect_button = ctk.CTkButton(
    mysql_frame, text="Connect", command=connect_mysql
)
mysql_connect_button.pack(fill="x", pady=(0, 5))


def on_backend_change(choice):
    if choice == "MySQL":
        sqlite_frame.pack_forget()
        mysql_frame.pack(fill="x", pady=(5, 0), before=db_status_label)
    else:
        mysql_frame.pack_forget()
        sqlite_frame.pack(fill="x", pady=(5, 0), before=db_status_label)
        # cheap/local - reactivate immediately, unlike MySQL which needs an
        # explicit Connect to validate credentials first
        db_config.set_sqlite(db_config.sqlite_path)


ctk.CTkSegmentedButton(
    settings_scroll, values=["SQLite", "MySQL"], variable=db_backend_var,
    command=on_backend_change
).pack(fill="x", pady=(0, 10))

db_status_label.pack(anchor="w", pady=(5, 10))

if db_config.backend == "mysql":
    mysql_frame.pack(fill="x", pady=(5, 0), before=db_status_label)
else:
    sqlite_frame.pack(fill="x", pady=(5, 0), before=db_status_label)

refresh_db_status()
db_config.trace_add("write", lambda *_: refresh_db_status())


ctk.CTkLabel(settings_scroll, text="⚙ SETTINGS", font=(
    "Arial", 16, "bold")).pack(anchor="w", pady=(10, 5))

ctk.CTkLabel(settings_scroll, text="Strip characters from species names").pack(
    anchor="w", pady=(0, 2))
ctk.CTkLabel(
    settings_scroll,
    text="Some datasets include characters GenBank/BOLD records don't "
         "consistently match on - e.g. botanical hybrid names use a × "
         "sign, as in \"Equisetum ×litorale\". Each character typed below "
         "is removed independently wherever it appears (not as a single "
         "combined phrase), e.g. \"×?*\" would strip all three of those "
         "characters.",
    justify="left", text_color="gray", wraplength=700, font=("Arial", 11)
).pack(anchor="w", pady=(0, 5))

strip_chars_var = ctk.BooleanVar(
    value=_saved_config.get("strip_chars_enabled", False))
ctk.CTkCheckBox(
    settings_scroll, text="Strip these characters:", variable=strip_chars_var
).pack(anchor="w", pady=(0, 2))

strip_chars_entry = ctk.CTkEntry(settings_scroll, placeholder_text="e.g. ×")
strip_chars_entry.insert(0, _saved_config.get("strip_chars", "×"))
strip_chars_entry.pack(fill="x", pady=(0, 10))

ctk.CTkLabel(settings_scroll, text="Min. interval between requests (s)").pack(
    anchor="w")
sleep_entry = ctk.CTkEntry(settings_scroll)
sleep_entry.insert(0, _saved_config.get("sleep_interval", "0.1"))
sleep_entry.pack(fill="x", pady=5)

workers_label = ctk.CTkLabel(
    settings_scroll, text="Concurrent workers (NCBI only)")
workers_label.pack(anchor="w")
workers_entry = ctk.CTkEntry(settings_scroll)
workers_entry.insert(0, _saved_config.get("workers", "5"))
workers_entry.pack(fill="x", pady=5)

ctk.CTkLabel(settings_scroll, text="Candidates to score per search (top N)").pack(
    anchor="w")
candidates_entry = ctk.CTkEntry(settings_scroll)
candidates_entry.insert(0, _saved_config.get("candidates", "10"))
candidates_entry.pack(fill="x", pady=5)

ctk.CTkLabel(settings_scroll, text="Results to save per marker (top N)").pack(
    anchor="w")
top_n_entry = ctk.CTkEntry(settings_scroll)
top_n_entry.insert(0, _saved_config.get("top_n", "1"))
top_n_entry.pack(fill="x", pady=5)


# LENGTH BANDS (bp)------------------------------------------------------
# Full score band: sequence length gets the full length score.
# Partial score band: extends past the full band on either side and

ctk.CTkLabel(settings_scroll, text="Default full score length band (bp)").pack(
    anchor="w", pady=(10, 0))

length_full_frame = ctk.CTkFrame(settings_scroll, fg_color="transparent")
length_full_frame.pack(fill="x", pady=5)

length_full_min_entry = ctk.CTkEntry(length_full_frame, placeholder_text="min")
length_full_min_entry.insert(0, _saved_config.get("length_full_min", "300"))
length_full_min_entry.pack(side="left", fill="x", expand=True, padx=(0, 5))

length_full_max_entry = ctk.CTkEntry(length_full_frame, placeholder_text="max")
length_full_max_entry.insert(0, _saved_config.get("length_full_max", "1200"))
length_full_max_entry.pack(side="left", fill="x", expand=True)

ctk.CTkLabel(settings_scroll, text="Default partial score length band (bp)").pack(
    anchor="w")

length_partial_frame = ctk.CTkFrame(settings_scroll, fg_color="transparent")
length_partial_frame.pack(fill="x", pady=5)

length_partial_min_entry = ctk.CTkEntry(
    length_partial_frame, placeholder_text="min")
length_partial_min_entry.insert(
    0, _saved_config.get("length_partial_min", "200"))
length_partial_min_entry.pack(side="left", fill="x", expand=True, padx=(0, 5))

length_partial_max_entry = ctk.CTkEntry(
    length_partial_frame, placeholder_text="max")
length_partial_max_entry.insert(
    0, _saved_config.get("length_partial_max", "2000"))
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
marker_bands_textbox.insert(
    "1.0", _saved_config.get("marker_length_bands_text", ""))
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
batch_size_entry.insert(0, _saved_config.get("batch_size", "10"))

batch_pause_label = ctk.CTkLabel(
    settings_scroll, text="Pause between batches, s (BOLD searches)")
batch_pause_entry = ctk.CTkEntry(settings_scroll)
batch_pause_entry.insert(0, _saved_config.get("batch_pause", "30"))
# not packed here - only shown when BOLD or "NCBI + BOLD" is selected


# SETTINGS PRESETS-----------------------------------------------------------

ctk.CTkLabel(settings_scroll, text="💾 SETTINGS PRESETS", font=(
    "Arial", 16, "bold")).pack(anchor="w", pady=(15, 5))
ctk.CTkLabel(
    settings_scroll,
    text="Save the scoring/markers/filters/output settings above (not "
         "NCBI credentials or the database connection) as a named preset, "
         "and switch between presets later.",
    justify="left", text_color="gray", wraplength=700, font=("Arial", 11)
).pack(anchor="w", pady=(0, 5))

_saved_presets = load_presets()

preset_row = ctk.CTkFrame(settings_scroll, fg_color="transparent")
preset_row.pack(fill="x", pady=(0, 5))

preset_var = ctk.StringVar()
preset_menu = ctk.CTkOptionMenu(
    preset_row, variable=preset_var, values=["(none saved)"])
preset_menu.pack(side="left", fill="x", expand=True, padx=(0, 5))

preset_status_label = ctk.CTkLabel(settings_scroll, text="", text_color="gray")


def refresh_preset_menu(select=None):
    names = sorted(_saved_presets.keys())
    preset_menu.configure(values=names or ["(none saved)"])
    if select in names:
        preset_var.set(select)
    elif names:
        preset_var.set(names[0])
    else:
        preset_var.set("(none saved)")


def load_selected_preset():
    name = preset_var.get()
    if name not in _saved_presets:
        preset_status_label.configure(
            text="No preset selected.", text_color="red")
        return
    apply_settings(_saved_presets[name])
    preset_status_label.configure(
        text=f"Loaded preset \"{name}\".", text_color="white")


def delete_selected_preset():
    name = preset_var.get()
    if name not in _saved_presets:
        return
    del _saved_presets[name]
    save_presets(_saved_presets)
    refresh_preset_menu()
    preset_status_label.configure(
        text=f"Deleted preset \"{name}\".", text_color="white")


ctk.CTkButton(
    preset_row, text="Load", width=70, command=load_selected_preset
).pack(side="left", padx=(0, 5))
ctk.CTkButton(
    preset_row, text="Delete", width=70, command=delete_selected_preset
).pack(side="left")

new_preset_row = ctk.CTkFrame(settings_scroll, fg_color="transparent")
new_preset_row.pack(fill="x", pady=(0, 5))

new_preset_name_entry = ctk.CTkEntry(
    new_preset_row, placeholder_text="Preset name")
new_preset_name_entry.pack(side="left", fill="x", expand=True, padx=(0, 5))


def save_current_as_preset():
    name = new_preset_name_entry.get().strip()
    if not name:
        preset_status_label.configure(
            text="Type a name for the preset first.", text_color="red")
        return
    verb = "Updated" if name in _saved_presets else "Saved"
    _saved_presets[name] = collect_current_settings()
    save_presets(_saved_presets)
    refresh_preset_menu(select=name)
    new_preset_name_entry.delete(0, "end")
    preset_status_label.configure(
        text=f"{verb} preset \"{name}\".", text_color="white")


ctk.CTkButton(
    new_preset_row, text="Save as new preset", command=save_current_as_preset
).pack(side="left")

preset_status_label.pack(anchor="w", pady=(0, 10))

refresh_preset_menu()


# SCORING SLIDERS (right panel)----------------------------------------------------------------------------

ctk.CTkLabel(right, text="📊 SCORING", font=("Arial", 18, "bold")).pack(pady=10)


def slider(label, config_key, default):
    default = int(_saved_config.get(config_key, default))

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

    # apply_settings() (used by preset loading) needs to update this
    # label too when it moves the slider programmatically - s.set()
    # doesn't fire the command callback above, so nothing else keeps it
    # in sync
    s.value_label = value

    return s


belgium_s = slider("Belgium boost", "score_belgium", 40)
neighbor_s = slider("Neighbor boost", "score_neighbor", 20)
europe_s = slider("Europe fallback", "score_europe", 5)
length_s = slider("Length bonus", "score_length_bonus", 10)
bad_penalty_s = slider("Bad penalty", "score_bad_penalty", 100)


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
        species_list = compute_species_list()

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

    # CHECKPOINTING-----------------------------------------------------
    # Without this, everything fetched during a run only ever hits disk/DB
    # once, at the very end of run_search() - so closing the app mid-run
    # (on_closing() force-kills with os._exit(0) specifically because
    # in-flight NCBI/BOLD calls would otherwise hang shutdown) or any crash
    # loses every sequence fetched so far, no matter how far the run got.
    # write_results/write_no_matches_table/summary.to_csv all overwrite
    # their output files each call, so re-running them against whatever
    # `results` holds so far is always safe to repeat, not just additive -
    # that makes "periodically re-run the final-write logic against partial
    # results" a correct, low-risk checkpoint. The output is exactly what a
    # completed run "up to this point" would have produced, so a killed run
    # is immediately resumable via the existing "Load no_matches.txt to
    # resume" flow with no new resume logic needed.

    checkpoint_conn = None
    checkpoint_run_id = None
    if save_database_var.get() and db_config.is_configured():
        try:
            checkpoint_conn = database.connect(db_config)
            checkpoint_run_id = database.create_run(
                checkpoint_conn, output_dir.get(), source)
        except Exception as e:
            log(f"Could not open database for incremental saving: {e}")
            checkpoint_conn = None

    db_pending = []
    last_checkpoint_time = time.time()

    def checkpoint():
        nonlocal last_checkpoint_time

        write_results(
            results, output_dir.get(), separate_species_var.get(),
            separate_marker_var.get(), save_metadata_var.get()
        )

        if resume_jobs is not None and resume_baseline_summary is not None:
            current_data = merge_summary_dataframe(
                resume_baseline_summary, results)
            current_matched = merge_matched_set(
                resume_baseline_summary, results)
            current_species_list = list(current_data["Species"])
            current_markers = [
                c[:-len("_count")] for c in current_data.columns
                if c.endswith("_count") and c not in
                {"NCBI_count", "BOLD_count", "Total_count"}
            ]
        else:
            current_matched = {(sp, mk) for sp, mk, _, _ in results}
            current_data = build_summary_dataframe(
                results, species_list, markers)
            current_species_list = species_list
            current_markers = markers

        if save_no_matches_var.get():
            write_no_matches_table(
                os.path.join(output_dir.get(), "no_matches.txt"),
                current_species_list, current_markers, current_matched
            )

        if save_summary_var.get():
            current_data.to_csv(
                os.path.join(output_dir.get(), "summary.csv"), index=False)

        if save_zero_species_var.get():
            write_zero_species_csv(
                os.path.join(output_dir.get(), "zero_species.csv"), current_data)

        if checkpoint_conn is not None and db_pending:
            try:
                database.insert_sequences(
                    checkpoint_conn, checkpoint_run_id, db_pending)
                db_pending.clear()
            except Exception as e:
                log(f"Database checkpoint save failed: {e}")

        last_checkpoint_time = time.time()
        return current_data

    def maybe_checkpoint():
        # time-based, not job-count-based: NCBI (fast, concurrent) and BOLD
        # (slow, rate-limited/batched) complete jobs at very different
        # rates, so a fixed job count would checkpoint far too often on one
        # source and far too rarely on the other
        if time.time() - last_checkpoint_time >= CHECKPOINT_INTERVAL_SECONDS:
            try:
                checkpoint()
                log(f"Checkpoint saved ({len(results)} sequence(s) so far).")
            except Exception as e:
                # a transient write failure (e.g. disk unavailable) during a
                # checkpoint shouldn't abort the whole run - it just means
                # this particular checkpoint didn't land, and results
                # already fetched stay in memory for the next attempt or
                # the final write
                log(f"Checkpoint failed (will retry next interval): {e}")

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
                if cancel_event.is_set():
                    # can't recall calls already in flight, but this stops
                    # any not-yet-started ones and returns as soon as
                    # whatever's currently running finishes, rather than
                    # waiting on the full remaining job list
                    executor.shutdown(wait=False, cancel_futures=True)
                    break

                species, marker = future_to_job[future]

                try:
                    records = future.result()
                except Exception as e:
                    log("job error:", e)
                    records = []

                for fasta_text, meta in records:
                    meta = {"species": species, "marker": marker, **meta}
                    record = (species, marker, fasta_text, meta)
                    results.append(record)
                    db_pending.append(record)

                completed += 1
                report_progress(completed, total_jobs, start_time)
                maybe_checkpoint()

        if retry_bold_var.get() and not cancel_event.is_set():
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

                    if cancel_event.is_set():
                        break

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
                        record = (species, marker, fasta_text, meta)
                        results.append(record)
                        db_pending.append(record)

                    retry_completed += 1
                    report_progress(
                        retry_completed, retry_total, retry_start, label="BOLD retry: "
                    )
                    maybe_checkpoint()

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

            if cancel_event.is_set():
                break

            for species in species_batch:

                for marker in jobs_by_species[species]:

                    if cancel_event.is_set():
                        break

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
                        record = (species, marker, fasta_text, meta)
                        results.append(record)
                        db_pending.append(record)

                    completed += 1
                    report_progress(completed, total_jobs, start_time)
                    maybe_checkpoint()

                if blocked or cancel_event.is_set():
                    break

            if blocked or cancel_event.is_set():
                break

            is_last_batch = batch_index == len(species_batches) - 1
            if batch_pause > 0 and not is_last_batch:
                log(f"Pausing {batch_pause}s before next batch...")
                sleep_or_cancel(batch_pause)

        if retry_ncbi_var.get() and not cancel_event.is_set():
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
                        if cancel_event.is_set():
                            executor.shutdown(wait=False, cancel_futures=True)
                            break

                        species, marker = future_to_job[future]

                        try:
                            records = future.result()
                        except Exception as e:
                            log("job error:", e)
                            records = []

                        for fasta_text, meta in records:
                            meta = {"species": species,
                                    "marker": marker, **meta}
                            record = (species, marker, fasta_text, meta)
                            results.append(record)
                            db_pending.append(record)

                        retry_completed += 1
                        report_progress(
                            retry_completed, retry_total, retry_start, label="NCBI retry: "
                        )
                        maybe_checkpoint()

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

        cache = {}

        ncbi_completed = 0
        bold_completed = 0
        bold_start = time.time()

        for batch_index, species_batch in enumerate(species_batches):

            if cancel_event.is_set():
                break

            batch_jobs = [
                (species, marker)
                for species in species_batch
                for marker in jobs_by_species[species]
            ]

            # per-batch, not accumulated across the whole run - the merge
            # below happens once per batch specifically so a checkpoint
            # partway through a long run has something real to save (see
            # the merge step right after the BOLD portion, below)
            ncbi_results = {}
            bold_results = {}

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
                    if cancel_event.is_set():
                        executor.shutdown(wait=False, cancel_futures=True)
                        break

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

                if cancel_event.is_set():
                    break

                for marker in jobs_by_species[species]:

                    if cancel_event.is_set():
                        break

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

                if blocked or cancel_event.is_set():
                    break

            # merge: pool both sources for this batch - done per-batch
            # (rather than once for the whole run) specifically so results
            # land in `results`/db_pending, and therefore in a checkpoint,
            # well before the entire run finishes
            batch_seen_jobs = set(ncbi_results.keys()) | set(
                bold_results.keys())

            for job in batch_seen_jobs:
                species, marker = job
                pool = ncbi_results.get(job, []) + bold_results.get(job, [])
                pool.sort(key=lambda record: record[1]["score"], reverse=True)

                for fasta_text, meta in pool[:top_n]:
                    meta = {"species": species, "marker": marker, **meta}
                    record = (species, marker, fasta_text, meta)
                    results.append(record)
                    db_pending.append(record)

            maybe_checkpoint()

            if blocked or cancel_event.is_set():
                break

            is_last_batch = batch_index == len(species_batches) - 1
            if batch_pause > 0 and not is_last_batch:
                log(f"Pausing {batch_pause}s before next batch...")
                sleep_or_cancel(batch_pause)

    # final checkpoint - same write logic that ran periodically during the
    # run (see maybe_checkpoint above), just guaranteed to run once more
    # now so the last partial interval isn't left unsaved
    # resuming only re-searches pairs that previously had zero matches, merge into the previous run's summary.csv
    try:
        retrieval_data = checkpoint()
    except Exception as e:
        log(f"Final checkpoint failed: {e} - most recent periodic "
            "checkpoint (if any) is still on disk/DB.")
        retrieval_data = build_summary_dataframe(
            results, species_list, markers)

    if checkpoint_conn is not None:
        checkpoint_conn.close()
        log(f"Database saving complete: {db_config.display_var.get()}")

    Fetch_Fasta.after(0, lambda: run_button.configure(state="normal"))
    Fetch_Fasta.after(
        0, lambda: stop_button.configure(state="disabled", text="⏹ Stop"))

    if cancel_event.is_set():
        update_status(
            f"Cancelled - {len(results)}/{total_jobs} sequences saved "
            "before stopping."
        )
    elif blocked:
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
    cancel_event.clear()
    stop_button.configure(state="normal", text="⏹ Stop")

    thread = threading.Thread(
        target=run_search,
        daemon=True
    )

    thread.start()


def request_cancel():
    # cooperative - run_search checks cancel_event between jobs and finishes
    # up (final checkpoint, status update) on its own rather than being torn
    # down here, so whatever's already in flight gets to complete cleanly
    cancel_event.set()
    stop_button.configure(state="disabled", text="Stopping...")
    update_status(
        "Cancelling - finishing in-flight requests, then saving partial "
        "results..."
    )


run_button_row = ctk.CTkFrame(scroll, fg_color="transparent")
run_button_row.pack(fill="x", pady=10)

run_button = ctk.CTkButton(
    run_button_row,
    text="▶ RUN PIPELINE",
    command=start_run
)
run_button.pack(side="left", fill="x", expand=True, padx=(0, 5))

stop_button = ctk.CTkButton(
    run_button_row,
    text="⏹ Stop",
    command=request_cancel,
    state="disabled",
    fg_color="#b91c1c",
    hover_color="#7f1616",
    width=90,
)
stop_button.pack(side="left")


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


def collect_current_settings():
    """
    The "tuning" subset of the app's settings - scoring, markers/filters,
    output options, character stripping - as opposed to credentials or the
    database connection. This is the shape both config.json's per-session
    auto-save and named presets (see apply_settings/save_presets) use, so
    a preset is exactly "everything on_closing() would otherwise silently
    carry over to next session," just named and switchable on demand.
    """
    return {
        # request/search tuning (Settings tab)
        "sleep_interval": sleep_entry.get(),
        "workers": workers_entry.get(),
        "candidates": candidates_entry.get(),
        "top_n": top_n_entry.get(),
        "batch_size": batch_size_entry.get(),
        "batch_pause": batch_pause_entry.get(),

        # length bands
        "length_full_min": length_full_min_entry.get(),
        "length_full_max": length_full_max_entry.get(),
        "length_partial_min": length_partial_min_entry.get(),
        "length_partial_max": length_partial_max_entry.get(),
        "marker_length_bands_text": marker_bands_textbox.get("1.0", "end").strip(),

        # scoring sliders
        "score_belgium": belgium_s.get(),
        "score_neighbor": neighbor_s.get(),
        "score_europe": europe_s.get(),
        "score_length_bonus": length_s.get(),
        "score_bad_penalty": bad_penalty_s.get(),

        # default marker/bad-word selections (Fetch FASTA tab)
        "selected_markers": [m for m, v in marker_vars.items() if v.get()],
        "extra_markers": extra_markers.get(),
        "selected_bad_words": [w for w, v in bad_words_default.items() if v.get()],
        "extra_bad_words": extra_bad.get(),

        # output options
        "separate_species": separate_species_var.get(),
        "separate_marker": separate_marker_var.get(),
        "save_metadata": save_metadata_var.get(),
        "save_no_matches": save_no_matches_var.get(),
        "save_summary": save_summary_var.get(),
        "save_zero_species": save_zero_species_var.get(),
        "save_database": save_database_var.get(),

        # character stripping (e.g. hybrid × marker)
        "strip_chars_enabled": strip_chars_var.get(),
        "strip_chars": strip_chars_entry.get(),
    }


def apply_settings(settings):
    """
    Inverse of collect_current_settings() - pushes a settings dict onto
    the live widgets, at runtime (not just at startup). Used by preset
    loading; startup restore uses the same _saved_config.get(key, default)
    values each widget was already created with, so this only needs to
    *change* widgets from whatever they currently show, not initialize them.
    """
    def set_entry(entry, key, default):
        entry.delete(0, "end")
        entry.insert(0, settings.get(key, default))

    set_entry(sleep_entry, "sleep_interval", "0.1")
    set_entry(workers_entry, "workers", "5")
    set_entry(candidates_entry, "candidates", "10")
    set_entry(top_n_entry, "top_n", "1")
    set_entry(batch_size_entry, "batch_size", "10")
    set_entry(batch_pause_entry, "batch_pause", "30")
    set_entry(length_full_min_entry, "length_full_min", "300")
    set_entry(length_full_max_entry, "length_full_max", "1200")
    set_entry(length_partial_min_entry, "length_partial_min", "200")
    set_entry(length_partial_max_entry, "length_partial_max", "2000")

    marker_bands_textbox.delete("1.0", "end")
    marker_bands_textbox.insert(
        "1.0", settings.get("marker_length_bands_text", ""))

    def set_slider(s, key, default):
        v = int(settings.get(key, default))
        s.set(v)
        # s.set() doesn't fire s's command
        s.value_label.configure(text=str(v))

    set_slider(belgium_s, "score_belgium", 40)
    set_slider(neighbor_s, "score_neighbor", 20)
    set_slider(europe_s, "score_europe", 5)
    set_slider(length_s, "score_length_bonus", 10)
    set_slider(bad_penalty_s, "score_bad_penalty", 100)

    saved_markers = settings.get("selected_markers")
    for m, v in marker_vars.items():
        v.set((m in saved_markers) if saved_markers is not None else False)
    set_entry(extra_markers, "extra_markers", "")

    saved_bad_words = settings.get("selected_bad_words")
    for w, v in bad_words_default.items():
        v.set((w in saved_bad_words) if saved_bad_words is not None else True)
    set_entry(extra_bad, "extra_bad_words", "")

    separate_species_var.set(settings.get("separate_species", True))
    separate_marker_var.set(settings.get("separate_marker", True))
    save_metadata_var.set(settings.get("save_metadata", True))
    save_no_matches_var.set(settings.get("save_no_matches", True))
    save_summary_var.set(settings.get("save_summary", True))
    save_zero_species_var.set(settings.get("save_zero_species", True))
    save_database_var.set(settings.get("save_database", False))

    strip_chars_var.set(settings.get("strip_chars_enabled", False))
    set_entry(strip_chars_entry, "strip_chars", "×")

    # re-enforce the same separate_species/separate_marker invariant
    # on_species_toggle keeps in sync for live toggling
    if not separate_species_var.get():
        marker_checkbox.configure(state="disabled")
        separate_marker_var.set(False)
    else:
        marker_checkbox.configure(state="normal")

    update_preview()


def on_closing():
    save_config({
        "ncbi_email": ncbi_email_entry.get().strip(),
        "ncbi_api_key": ncbi_api_key_entry.get().strip(),
        # MySQL password is intentionally never saved - re-entered each session
        "db_backend": db_config.backend,
        "db_sqlite_path": db_config.sqlite_path,
        "db_mysql_host": db_config.mysql_host,
        "db_mysql_port": db_config.mysql_port,
        "db_mysql_user": db_config.mysql_user,
        "db_mysql_database": db_config.mysql_database,

        # deliberately NOT saved: species list/CSV path, output directory,
        # resume state, and the NCBI/BOLD source choice + retry checkboxes
        # - these are per-run choices, not standing settings, and
        # auto-restoring them (especially output_dir or an old species
        # list) on every launch would be surprising rather than convenient
        **collect_current_settings(),
    })

    # ThreadPoolExecutor workers spawned by run_search() are non-daemon, so a plain exit would hang until any in-flight NCBI/BOLD calls finish. Force-kill the process instead.
    app.destroy()
    os._exit(0)


app.protocol("WM_DELETE_WINDOW", on_closing)

app.mainloop()
