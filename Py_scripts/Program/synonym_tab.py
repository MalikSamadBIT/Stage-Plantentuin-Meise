import csv
import os
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from tkinter import filedialog

import customtkinter as ctk
import pandas as pd

import database
from common import RateLimiter
from ncbi_client import search_and_fetch_ncbi, configure_entrez
from output import parse_no_matches_table
from synonym_client import search_synonyms

# Not exposed on this tab (kept simple) - same defaults as the Fetch FASTA
# tab's sliders/checkboxes/length bands.
DEFAULT_WEIGHTS = {
    "belgium": 40, "neighbor": 20, "europe": 5, "unknown": 0,
    "length_bonus": 10, "bad_title_penalty": 100,
}
DEFAULT_BAD_WORDS = [
    "whole genome", "chromosome", "scaffold", "contig", "assembly"
]
DEFAULT_LENGTH_BANDS = {
    "full_min": 300, "full_max": 1200, "partial_min": 200, "partial_max": 2000,
}
MAX_CANDIDATES = 10
TOP_N = 1


def build_synonym_tab(parent, root=None, get_ncbi_credentials=None, db_config=None):
    """
    parent: the tab frame to build the widgets into.
    root: the main app window, used as the file-dialog parent.
    get_ncbi_credentials: callable -> (email, api_key), read from the
        Settings tab at search time (NCBI sequence search needs it).
    db_config: shared database.DatabaseConfig chosen in the Settings tab.
        Falls back to a private (unconfigured) one if this tab is ever used
        standalone.
    """

    csv_path = ctk.StringVar()
    no_matches_path = ctk.StringVar()
    if db_config is None:
        db_config = database.DatabaseConfig()

    last_synonym_results = {}
    last_sequence_results = []
    selection_vars = {}

    # the tab frame itself doesn't scroll, and this page is taller than the
    # window - everything below goes into a scrollable frame instead so the
    # sequence-search/add-to-database controls at the bottom stay reachable.
    scroll = ctk.CTkScrollableFrame(parent)
    scroll.pack(fill="both", expand=True)

    # SPECIES INPUT SECTION---------------------------------------------------

    ctk.CTkLabel(scroll, text="🔤 SYNONYM SEARCH INPUT", font=(
        "Arial", 16, "bold")).pack(anchor="w", padx=10, pady=(10, 2))

    ctk.CTkLabel(
        scroll,
        text="Species come from a CSV, a no_matches.txt file, and/or typed "
             "names below - any combination is combined and de-duplicated, "
             "except a loaded no_matches.txt replaces the CSV/typed names.",
        justify="left", text_color="gray", wraplength=700
    ).pack(anchor="w", padx=10, pady=(0, 10))

    def choose_csv():
        path = filedialog.askopenfilename(
            parent=root,
            title="Select a CSV file with a 'Name' column",
            filetypes=[("CSV", "*.csv")]
        )
        if path:
            csv_path.set(path)
            no_matches_path.set("")

    ctk.CTkButton(
        scroll, text="Select CSV File (with 'Name' column)", command=choose_csv
    ).pack(fill="x", padx=10, pady=5)
    ctk.CTkLabel(scroll, textvariable=csv_path, text_color="gray").pack(
        anchor="w", padx=10, pady=(0, 10))

    def choose_no_matches():
        path = filedialog.askopenfilename(
            parent=root,
            title="Select a no_matches.txt file",
            filetypes=[("Text files", "*.txt")]
        )
        if path:
            no_matches_path.set(path)
            csv_path.set("")

    ctk.CTkButton(
        scroll, text="Select no_matches.txt", command=choose_no_matches
    ).pack(fill="x", padx=10, pady=5)
    ctk.CTkLabel(scroll, textvariable=no_matches_path, text_color="gray").pack(
        anchor="w", padx=10, pady=(0, 10))

    ctk.CTkLabel(scroll, text="Or type species names (comma separated)").pack(
        anchor="w", padx=10)
    species_textbox = ctk.CTkTextbox(scroll, height=80)
    species_textbox.pack(fill="x", padx=10, pady=(0, 10))

    status_label = ctk.CTkLabel(scroll, text="No species loaded yet.")
    status_label.pack(anchor="w", padx=10, pady=(0, 5))

    species_preview = ctk.CTkTextbox(scroll, height=80)
    species_preview.pack(fill="x", padx=10, pady=(0, 10))
    species_preview.configure(state="disabled")

    def get_species_list():
        if no_matches_path.get():
            try:
                pending = parse_no_matches_table(no_matches_path.get())
            except Exception as e:
                status_label.configure(
                    text=f"Failed to read no_matches.txt: {e}", text_color="red")
                return []
            return list(dict.fromkeys(species for species, _marker in pending))

        species_list = []

        if csv_path.get():
            try:
                df = pd.read_csv(csv_path.get())
                species_list += list(df["Name"])
            except Exception as e:
                status_label.configure(
                    text=f"Failed to read CSV: {e}", text_color="red")
                return []

        species_list += [
            s.strip() for s in species_textbox.get("1.0", "end").split(",")
            if s.strip()
        ]

        return list(dict.fromkeys(s for s in species_list if s))

    def load_species():
        species_list = get_species_list()

        species_preview.configure(state="normal")
        species_preview.delete("1.0", "end")
        species_preview.insert("1.0", "\n".join(species_list))
        species_preview.configure(state="disabled")

        if species_list:
            status_label.configure(
                text=f"{len(species_list)} species loaded.", text_color="white")
        else:
            status_label.configure(
                text="No species loaded yet - select a CSV/no_matches.txt "
                     "or type some names.",
                text_color="white"
            )

    synonym_button_row = ctk.CTkFrame(scroll, fg_color="transparent")
    synonym_button_row.pack(fill="x", padx=10, pady=(0, 10))

    ctk.CTkButton(
        synonym_button_row, text="Load Species", command=load_species
    ).pack(side="left", padx=(0, 5))

    ctk.CTkLabel(synonym_button_row, text="waarnemingen.be interval (s)").pack(
        side="left", padx=(10, 5))
    interval_entry = ctk.CTkEntry(synonym_button_row, width=60)
    interval_entry.insert(0, "1.0")
    interval_entry.pack(side="left", padx=(0, 10))

    synonym_search_button = ctk.CTkButton(
        synonym_button_row, text="Search Synonyms")
    synonym_search_button.pack(side="left")

    # SYNONYM SELECTION CHECKLIST---------------------------------------------
    # populated after "Search Synonyms" - one row per species (canonical name)
    # plus one row per distinct synonym name found, all pre-checked; uncheck
    # any name you don't want spent on an NCBI search.

    ctk.CTkLabel(scroll, text="🧬 SELECT NAMES TO SEARCH FOR SEQUENCES", font=(
        "Arial", 16, "bold")).pack(anchor="w", padx=10, pady=(5, 2))

    checklist_frame = ctk.CTkScrollableFrame(scroll, height=220)
    checklist_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    def build_checklist(synonym_results):
        for widget in checklist_frame.winfo_children():
            widget.destroy()
        selection_vars.clear()

        for species, synonyms in synonym_results.items():
            ctk.CTkLabel(
                checklist_frame, text=species, font=("Arial", 13, "bold")
            ).pack(anchor="w", pady=(8, 0))

            canonical_var = ctk.BooleanVar(value=True)
            selection_vars[(species, species)] = canonical_var
            ctk.CTkCheckBox(
                checklist_frame, text=f"{species} (canonical name)",
                variable=canonical_var
            ).pack(anchor="w", padx=20)

            name_to_languages = defaultdict(list)
            for language, name in synonyms.items():
                if name:
                    name_to_languages[name].append(language)

            for name, languages in name_to_languages.items():
                var = ctk.BooleanVar(value=True)
                selection_vars[(species, name)] = var
                ctk.CTkCheckBox(
                    checklist_frame,
                    text=f"{name} ({', '.join(languages)})",
                    variable=var
                ).pack(anchor="w", padx=20)

    def get_selected_names():
        # [(canonical_species, name_to_query), ...]
        return [key for key, var in selection_vars.items() if var.get()]

    def run_synonym_search():
        nonlocal last_synonym_results

        species_list = get_species_list()

        if not species_list:
            status_label.configure(
                text="No species to search - select a CSV/no_matches.txt "
                     "or type some names.",
                text_color="red"
            )
            return

        try:
            interval = max(0.0, float(interval_entry.get()))
        except ValueError:
            interval = 1.0

        rate_limiter = RateLimiter(interval)

        parent.after(
            0, lambda: synonym_search_button.configure(state="disabled"))
        parent.after(
            0,
            lambda: status_label.configure(
                text=f"Searching 0/{len(species_list)} species...",
                text_color="white"
            )
        )

        def progress(completed, total, species):
            parent.after(
                0,
                lambda: status_label.configure(
                    text=f"Searching {completed}/{total} species... "
                         f"(last: {species})",
                    text_color="white"
                )
            )

        results = search_synonyms(
            species_list, rate_limiter, log=print, progress=progress)

        last_synonym_results = results

        parent.after(0, lambda: build_checklist(results))
        parent.after(
            0,
            lambda: status_label.configure(
                text=f"Done - looked up {len(results)} species. "
                     "All names are pre-checked - uncheck any you don't "
                     "want searched below.",
                text_color="white"
            )
        )
        parent.after(
            0, lambda: synonym_search_button.configure(state="normal"))

    def start_synonym_search():
        threading.Thread(target=run_synonym_search, daemon=True).start()

    synonym_search_button.configure(command=start_synonym_search)

    # DATABASE-----------------------------------------------------------
    # the database file itself is chosen once in the Settings tab and shared
    # across the whole program - this just saves into whatever's configured.

    ctk.CTkLabel(scroll, text="🗄 DATABASE", font=(
        "Arial", 16, "bold")).pack(anchor="w", padx=10, pady=(5, 2))

    db_row = ctk.CTkFrame(scroll, fg_color="transparent")
    db_row.pack(fill="x", padx=10, pady=(0, 5))

    save_synonyms_button = ctk.CTkButton(
        db_row, text="Save Synonyms to Database")
    save_synonyms_button.pack(side="left")

    ctk.CTkLabel(
        scroll, textvariable=db_config.display_var, text_color="gray"
    ).pack(anchor="w", padx=10, pady=(0, 10))

    def save_synonyms_to_database():
        if not last_synonym_results:
            status_label.configure(
                text="No synonym search results to save yet - run a "
                     "synonym search first.",
                text_color="red"
            )
            return

        if not db_config.is_configured():
            status_label.configure(
                text="Select a database in the Settings tab first.", text_color="red")
            return

        try:
            conn = database.connect(db_config)
            synonym_count = 0
            for species, synonyms in last_synonym_results.items():
                database.add_synonyms(conn, species, synonyms)
                synonym_count += sum(1 for name in synonyms.values() if name)
            conn.close()
        except Exception as e:
            status_label.configure(
                text=f"Database save failed: {e}", text_color="red")
            return

        status_label.configure(
            text=f"Saved {len(last_synonym_results)} species and "
                 f"{synonym_count} synonym name(s), linked to their "
                 f"canonical species, to {db_config.display_var.get()}.",
            text_color="white"
        )

    save_synonyms_button.configure(command=save_synonyms_to_database)

    # MARKERS-------------------------------------------------------------

    ctk.CTkLabel(scroll, text="Markers", font=(
        "Arial", 14, "bold")).pack(anchor="w", padx=10, pady=(5, 0))

    marker_row = ctk.CTkFrame(scroll, fg_color="transparent")
    marker_row.pack(fill="x", padx=10, pady=(0, 5))

    marker_vars = {}
    for m in ["ITS", "ITS1", "ITS2", "rbcL", "matK", "trnL", "psbA-trnH"]:
        v = ctk.BooleanVar()
        marker_vars[m] = v
        ctk.CTkCheckBox(marker_row, text=m, variable=v).pack(
            side="left", padx=(0, 8))

    ctk.CTkLabel(scroll, text="Extra markers (comma separated)").pack(
        anchor="w", padx=10)
    extra_markers = ctk.CTkEntry(scroll)
    extra_markers.pack(fill="x", padx=10, pady=(0, 10))

    # SEQUENCE SEARCH-------------------------------------------------------

    seq_button_row = ctk.CTkFrame(scroll, fg_color="transparent")
    seq_button_row.pack(fill="x", padx=10, pady=(0, 5))

    ctk.CTkLabel(seq_button_row, text="NCBI interval (s)").pack(
        side="left", padx=(0, 5))
    ncbi_interval_entry = ctk.CTkEntry(seq_button_row, width=60)
    ncbi_interval_entry.insert(0, "0.1")
    ncbi_interval_entry.pack(side="left", padx=(0, 10))

    ctk.CTkLabel(seq_button_row, text="Workers").pack(
        side="left", padx=(0, 5))
    workers_entry = ctk.CTkEntry(seq_button_row, width=50)
    workers_entry.insert(0, "5")
    workers_entry.pack(side="left", padx=(0, 10))

    seq_search_button = ctk.CTkButton(
        seq_button_row, text="Search Sequences for Selected Names")
    seq_search_button.pack(side="left")

    seq_status_label = ctk.CTkLabel(scroll, text="No sequence search run yet.")
    seq_status_label.pack(anchor="w", padx=10, pady=(0, 5))

    seq_results_box = ctk.CTkTextbox(scroll, height=160)
    seq_results_box.pack(fill="both", expand=True, padx=10, pady=(0, 10))
    seq_results_box.configure(state="disabled")

    def set_seq_results_text(text):
        seq_results_box.configure(state="normal")
        seq_results_box.delete("1.0", "end")
        seq_results_box.insert("1.0", text)
        seq_results_box.configure(state="disabled")

    def run_sequence_search():
        nonlocal last_sequence_results

        selected = get_selected_names()

        markers = [m for m, v in marker_vars.items() if v.get()]
        markers += [m.strip()
                    for m in extra_markers.get().split(",") if m.strip()]
        markers = list(dict.fromkeys(markers))

        if not selected:
            seq_status_label.configure(
                text="No names selected - run a synonym search and check "
                     "at least one name above.",
                text_color="red"
            )
            return

        if not markers:
            seq_status_label.configure(
                text="Select at least one marker!", text_color="red")
            return

        if get_ncbi_credentials:
            email, api_key = get_ncbi_credentials()
        else:
            email, api_key = "", ""

        if not email:
            seq_status_label.configure(
                text="Enter your NCBI email in the Settings tab first!",
                text_color="red"
            )
            return

        configure_entrez(email, api_key)

        try:
            interval = max(0.0, float(ncbi_interval_entry.get()))
        except ValueError:
            interval = 0.1

        try:
            max_workers = max(1, int(workers_entry.get()))
        except ValueError:
            max_workers = 5

        rate_limiter = RateLimiter(interval)

        jobs = [
            (canonical_species, queried_name, marker)
            for canonical_species, queried_name in selected
            for marker in markers
        ]
        total_jobs = len(jobs)

        parent.after(
            0, lambda: seq_search_button.configure(state="disabled"))
        parent.after(
            0,
            lambda: seq_status_label.configure(
                text=f"Searching 0/{total_jobs} name/marker combinations...",
                text_color="white"
            )
        )

        results = []
        completed = 0

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_job = {
                executor.submit(
                    search_and_fetch_ncbi, queried_name, marker, rate_limiter,
                    DEFAULT_WEIGHTS, DEFAULT_BAD_WORDS, MAX_CANDIDATES, TOP_N,
                    print, DEFAULT_LENGTH_BANDS
                ): (canonical_species, queried_name, marker)
                for canonical_species, queried_name, marker in jobs
            }

            for future in as_completed(future_to_job):
                canonical_species, queried_name, marker = future_to_job[future]

                try:
                    records = future.result()
                except Exception as e:
                    print("job error:", e)
                    records = []

                queried_as = None if queried_name == canonical_species else queried_name

                for fasta_text, meta in records:
                    meta = {
                        "species": canonical_species, "marker": marker,
                        "queried_as": queried_as, **meta
                    }
                    results.append(
                        (canonical_species, marker, fasta_text, meta))

                completed += 1
                parent.after(
                    0,
                    lambda c=completed: seq_status_label.configure(
                        text=f"Searching {c}/{total_jobs} name/marker "
                             "combinations...",
                        text_color="white"
                    )
                )

        last_sequence_results = results

        lines = [
            f"{species} | {marker} | {meta.get('accession')} | "
            f"queried as: {meta.get('queried_as') or '(canonical)'} | "
            f"score {meta.get('score')}"
            for species, marker, _fasta, meta in results
        ]
        parent.after(0, lambda: set_seq_results_text(
            "\n".join(lines) or "No sequences found for the selected names."))
        parent.after(
            0,
            lambda: seq_status_label.configure(
                text=f"Done - {len(results)} sequence(s) found across "
                     f"{total_jobs} name/marker combination(s).",
                text_color="white"
            )
        )
        parent.after(0, lambda: seq_search_button.configure(state="normal"))
        parent.after(
            0,
            lambda: db_save_button.configure(
                state="normal" if results else "disabled")
        )

    def start_sequence_search():
        threading.Thread(target=run_sequence_search, daemon=True).start()

    seq_search_button.configure(command=start_sequence_search)

    # ADD SEQUENCE RESULTS TO DATABASE-----------------------------------
    # reuses the database picked above - saves the sequence results (and,
    # again, the synonyms, in case synonyms weren't saved separately yet).

    db_save_button = ctk.CTkButton(
        scroll, text="Add Sequence Results to Database", state="disabled")
    db_save_button.pack(fill="x", padx=10, pady=(0, 10))

    def save_to_database():
        if not last_sequence_results:
            seq_status_label.configure(
                text="No sequence search results to save yet.",
                text_color="red"
            )
            return

        if not db_config.is_configured():
            seq_status_label.configure(
                text="Select a database in the Settings tab first.", text_color="red")
            return

        try:
            conn = database.connect(db_config)
            run_id = database.create_run(
                conn, output_dir="", source="Synonym search")

            for species, synonyms in last_synonym_results.items():
                database.add_synonyms(conn, species, synonyms)

            inserted = database.insert_sequences(
                conn, run_id, last_sequence_results)
            conn.close()
        except Exception as e:
            seq_status_label.configure(
                text=f"Database save failed: {e}", text_color="red")
            return

        seq_status_label.configure(
            text=f"Saved {inserted} new sequence(s) (and synonyms) to "
                 f"{db_config.display_var.get()}.",
            text_color="white"
        )

    db_save_button.configure(command=save_to_database)

    return get_species_list
