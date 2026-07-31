import datetime
import os
import threading
import tkinter
from tkinter import filedialog, ttk

import customtkinter as ctk
import pandas as pd
from tkcalendar import DateEntry

import database
import gap_analysis
from geoloc_client import SITES, fetch_observation_counts_batch
from output import parse_no_matches_table

DEFAULT_MARKERS = ["ITS", "ITS1", "ITS2", "rbcL", "matK", "trnL", "psbA-trnH"]

STATUS_COLORS = {
    "no_sequences": "#e35d5d",
    "partial": "#eda100",
    "complete": "#4caf50",
    "no_data": "#9a9a9a",
}


def build_gap_tab(parent, root=None, db_config=None, report_items=None):
    """
    parent: the tab frame to build the widgets into.
    root: the main app window, used as the file-dialog parent.
    db_config: shared database.DatabaseConfig chosen in the Settings tab.
        Falls back to a private (unconfigured) one if this tab is ever used
        standalone.
    report_items: shared list that Retrieval Rate/MSA/Synonym search push
        "add to report" snapshots into (see their build_*_tab functions) -
        this tab lists and manages them, and (eventually) assembles the
        final report from them. Falls back to a private (empty) one if
        this tab is ever used standalone.
    """

    if db_config is None:
        db_config = database.DatabaseConfig()
    if report_items is None:
        report_items = []

    sub_tabs = ctk.CTkTabview(parent)
    sub_tabs.pack(fill="both", expand=True)

    analysis_tab = sub_tabs.add("Gap Analysis")
    contents_tab = sub_tabs.add("Report Contents")

    csv_path = ctk.StringVar()
    no_matches_path = ctk.StringVar()
    last_rows = []
    last_target_markers = []

    # SPECIES INPUT-----------------------------------------------------

    ctk.CTkLabel(analysis_tab, text="🎯 SPECIES TO CHECK", font=(
        "Arial", 16, "bold")).pack(anchor="w", padx=10, pady=(10, 2))

    input_button_row = ctk.CTkFrame(analysis_tab, fg_color="transparent")
    input_button_row.pack(fill="x", padx=10, pady=(0, 2))

    def choose_csv():
        path = filedialog.askopenfilename(
            parent=root, title="Select a CSV file with a 'Name' column",
            filetypes=[("CSV", "*.csv")]
        )
        if path:
            csv_path.set(path)
            no_matches_path.set("")

    def choose_no_matches():
        path = filedialog.askopenfilename(
            parent=root, title="Select a no_matches.txt file",
            filetypes=[("Text files", "*.txt")]
        )
        if path:
            no_matches_path.set(path)
            csv_path.set("")

    ctk.CTkButton(
        input_button_row, text="Select CSV File (with 'Name' column)",
        command=choose_csv
    ).pack(side="left", padx=(0, 5), fill="x", expand=True)

    ctk.CTkButton(
        input_button_row, text="Select no_matches.txt", command=choose_no_matches
    ).pack(side="left", fill="x", expand=True)

    input_path_label = ctk.CTkLabel(analysis_tab, text="", text_color="gray")
    input_path_label.pack(anchor="w", padx=10, pady=(0, 5))

    def _update_input_path_label(*_):
        input_path_label.configure(text=csv_path.get() or no_matches_path.get())

    csv_path.trace_add("write", _update_input_path_label)
    no_matches_path.trace_add("write", _update_input_path_label)

    ctk.CTkLabel(analysis_tab, text="Or type species names (comma separated)").pack(
        anchor="w", padx=10)
    species_textbox = ctk.CTkTextbox(analysis_tab, height=50)
    species_textbox.pack(fill="x", padx=10, pady=(0, 10))

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
                csv_df = pd.read_csv(csv_path.get())
                species_list += list(csv_df["Name"])
            except Exception as e:
                status_label.configure(
                    text=f"Failed to read CSV: {e}", text_color="red")
                return []

        species_list += [
            s.strip() for s in species_textbox.get("1.0", "end").split(",")
            if s.strip()
        ]

        return list(dict.fromkeys(s for s in species_list if s))

    # OPTIONS-------------------------------------------------------------

    ctk.CTkLabel(analysis_tab, text="⚙ OPTIONS", font=(
        "Arial", 16, "bold")).pack(anchor="w", padx=10, pady=(5, 2))

    options_row = ctk.CTkFrame(analysis_tab, fg_color="transparent")
    options_row.pack(fill="x", padx=10, pady=(0, 5))

    ctk.CTkLabel(options_row, text="Site:").pack(side="left", padx=(0, 4))
    site_var = ctk.StringVar(value=list(SITES.keys())[0])
    ctk.CTkSegmentedButton(
        options_row, values=list(SITES.keys()), variable=site_var
    ).pack(side="left", padx=(0, 12))

    ctk.CTkLabel(options_row, text="Start date:").pack(side="left", padx=(0, 4))
    start_date_entry = DateEntry(options_row, date_pattern="yyyy-mm-dd")
    start_date_entry.pack(side="left", padx=(0, 12))
    start_date_entry.set_date("2016-02-29")

    ctk.CTkLabel(options_row, text="End date:").pack(side="left", padx=(0, 4))
    end_date_entry = DateEntry(options_row, date_pattern="yyyy-mm-dd")
    end_date_entry.pack(side="left", padx=(0, 12))
    end_date_entry.set_date(datetime.date.today())

    ctk.CTkLabel(analysis_tab, text="Target markers", font=(
        "Arial", 14, "bold")).pack(anchor="w", padx=10, pady=(5, 0))

    marker_row = ctk.CTkFrame(analysis_tab, fg_color="transparent")
    marker_row.pack(fill="x", padx=10, pady=(0, 5))

    marker_vars = {}
    for m in DEFAULT_MARKERS:
        v = ctk.BooleanVar()
        marker_vars[m] = v
        ctk.CTkCheckBox(marker_row, text=m, variable=v).pack(
            side="left", padx=(0, 8))

    extra_markers_row = ctk.CTkFrame(analysis_tab, fg_color="transparent")
    extra_markers_row.pack(fill="x", padx=10, pady=(0, 5))

    ctk.CTkLabel(extra_markers_row, text="Extra markers (comma separated):").pack(
        side="left", padx=(0, 5))
    extra_markers_entry = ctk.CTkEntry(extra_markers_row)
    extra_markers_entry.pack(side="left", fill="x", expand=True)

    run_button = ctk.CTkButton(analysis_tab, text="Run Gap Analysis")
    run_button.pack(fill="x", padx=10, pady=(5, 2))

    status_label = ctk.CTkLabel(analysis_tab, text="", text_color="gray")
    status_label.pack(anchor="w", padx=10, pady=(0, 5))

    # RESULTS TABLE---------------------------------------------------------

    table_top_bar = ctk.CTkFrame(analysis_tab, fg_color="transparent")
    table_top_bar.pack(fill="x", padx=10, pady=(5, 5))

    ctk.CTkButton(
        table_top_bar, text="Export to CSV...", command=lambda: export_csv()
    ).pack(side="left")

    table_style = ttk.Style()
    table_style.theme_use("clam")
    table_style.configure(
        "Treeview",
        background="#2b2b2b", fieldbackground="#2b2b2b",
        foreground="white", rowheight=28,
        font=("Arial", 12)
    )
    table_style.configure(
        "Treeview.Heading",
        background="#3a3a3a", foreground="white",
        font=("Arial", 12, "bold")
    )

    table_frame = tkinter.Frame(analysis_tab)
    table_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    table_vsb = ttk.Scrollbar(table_frame, orient="vertical")
    table_hsb = ttk.Scrollbar(table_frame, orient="horizontal")

    tree = ttk.Treeview(
        table_frame, show="headings",
        yscrollcommand=table_vsb.set,
        xscrollcommand=table_hsb.set
    )

    for status, color in STATUS_COLORS.items():
        tree.tag_configure(status, foreground=color)

    table_vsb.configure(command=tree.yview)
    table_hsb.configure(command=tree.xview)

    table_vsb.pack(side=tkinter.RIGHT, fill=tkinter.Y)
    table_hsb.pack(side=tkinter.BOTTOM, fill=tkinter.X)
    tree.pack(side=tkinter.TOP, fill=tkinter.BOTH, expand=True)

    # RUN / POPULATE----------------------------------------------------

    COLUMN_HEADERS = {"species": "Species", "observations": "Observations",
                       "status_label": "Status"}

    def populate_tree(rows, target_markers):
        tree.delete(*tree.get_children())
        columns = ["species", "observations"] + target_markers + ["status_label"]
        tree["columns"] = columns

        for col in columns:
            tree.heading(col, text=COLUMN_HEADERS.get(col, col))
            tree.column(
                col, width=160 if col == "species" else 100,
                anchor="w" if col == "species" else "center"
            )

        for row in rows:
            values = [
                row["species"],
                "-" if row["observations"] is None else row["observations"],
            ]
            for marker in target_markers:
                values.append("-" if row[marker] is None else row[marker])
            values.append(row["status_label"])
            tree.insert("", "end", values=values, tags=(row["status"],))

    def run_worker(species_list, site_key, start_date, end_date, target_markers):
        site = SITES[site_key]

        def progress(completed, total, name):
            parent.after(
                0,
                lambda: status_label.configure(
                    text=f"Checking observations... {completed}/{total} ({name})",
                    text_color="white"
                )
            )

        observation_counts = fetch_observation_counts_batch(
            site["base_url"], species_list, start_date, end_date,
            site["map_type"], progress=progress
        )

        rows = gap_analysis.build_gap_rows(
            species_list, observation_counts, db_config, target_markers)

        def finish():
            nonlocal last_rows, last_target_markers
            last_rows = rows
            last_target_markers = target_markers
            populate_tree(rows, target_markers)
            run_button.configure(state="normal", text="Run Gap Analysis")

            note = ""
            if not db_config.is_configured():
                note = (
                    " (no database configured in Settings - sequence "
                    "counts shown as 0/\"No sequences\" rather than "
                    "actually checked)"
                )
            status_label.configure(
                text=f"Done - {len(rows)} species checked.{note}",
                text_color="white"
            )
            refresh_items_list()

        parent.after(0, finish)

    def start_run():
        species_list = get_species_list()
        if not species_list:
            status_label.configure(
                text="No species to check - select a CSV/no_matches.txt "
                     "or type some names.",
                text_color="red"
            )
            return

        target_markers = [m for m, v in marker_vars.items() if v.get()]
        target_markers += [
            m.strip() for m in extra_markers_entry.get().split(",") if m.strip()
        ]
        target_markers = list(dict.fromkeys(target_markers))

        if not target_markers:
            status_label.configure(
                text="Select at least one target marker.", text_color="red")
            return

        start_date = start_date_entry.get_date()
        end_date = end_date_entry.get_date()
        if start_date >= end_date:
            status_label.configure(
                text="Start date must be before end date.", text_color="red")
            return

        site_key = site_var.get()

        run_button.configure(state="disabled", text="Running...")
        status_label.configure(
            text=f"Checking observations... 0/{len(species_list)}",
            text_color="white"
        )

        threading.Thread(
            target=run_worker,
            args=(species_list, site_key, start_date, end_date, target_markers),
            daemon=True
        ).start()

    run_button.configure(command=start_run)

    # EXPORT----------------------------------------------------------------

    def export_csv():
        if not last_rows:
            status_label.configure(
                text="Nothing to export - run a gap analysis first.",
                text_color="red"
            )
            return

        path = filedialog.asksaveasfilename(
            parent=root, title="Export gap analysis to CSV",
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv"), ("All files", "*.*")]
        )
        if not path:
            return

        columns = ["species", "observations"] + last_target_markers + ["status_label"]
        pd.DataFrame(last_rows)[columns].to_csv(path, index=False)

        status_label.configure(
            text=f"Exported {len(last_rows)} row(s) to {os.path.basename(path)}.",
            text_color="white"
        )

    # REPORT CONTENTS TAB----------------------------------------------------
    # Lists whatever's been added from the Retrieval Rate/MSA/Synonym search
    # tabs' "Add to Report" buttons, plus the gap analysis table above
    # (always included, not removable). Assembling these into an actual
    # exported report is a later step - this just manages what's queued up.

    ctk.CTkLabel(contents_tab, text="📎 REPORT CONTENTS", font=(
        "Arial", 16, "bold")).pack(anchor="w", padx=10, pady=(10, 2))

    ctk.CTkLabel(
        contents_tab,
        text="The gap analysis table is always included. Add optional "
             "sections from the Retrieval Rate, MSA, and Synonym search "
             "tabs using their \"Add to Report\" buttons - they'll show up "
             "here.",
        justify="left", text_color="gray", wraplength=700
    ).pack(anchor="w", padx=10, pady=(0, 10))

    items_frame = ctk.CTkScrollableFrame(contents_tab)
    items_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    def remove_item(index):
        report_items.pop(index)
        refresh_items_list()

    def refresh_items_list():
        for widget in items_frame.winfo_children():
            widget.destroy()

        gap_row = ctk.CTkFrame(items_frame)
        gap_row.pack(fill="x", pady=(0, 5))
        ctk.CTkLabel(
            gap_row, text="Gap analysis", font=("Arial", 13, "bold")
        ).pack(side="left", padx=10, pady=8)
        ctk.CTkLabel(
            gap_row,
            text=f"{len(last_rows)} species checked" if last_rows else "Not run yet",
            text_color="gray"
        ).pack(side="left", padx=(0, 10))
        ctk.CTkLabel(
            gap_row, text="Always included", text_color="gray"
        ).pack(side="right", padx=10)

        if not report_items:
            ctk.CTkLabel(
                items_frame, text="No optional sections added yet.",
                text_color="gray"
            ).pack(anchor="w", pady=10)
            return

        for i, item in enumerate(report_items):
            row = ctk.CTkFrame(items_frame)
            row.pack(fill="x", pady=5)

            text_col = ctk.CTkFrame(row, fg_color="transparent")
            text_col.pack(side="left", fill="x", expand=True, padx=10, pady=8)
            ctk.CTkLabel(
                text_col, text=item["title"], font=("Arial", 13, "bold")
            ).pack(anchor="w")
            ctk.CTkLabel(
                text_col, text=item.get("subtitle", ""), text_color="gray"
            ).pack(anchor="w")

            ctk.CTkButton(
                row, text="Remove", width=80,
                command=lambda i=i: remove_item(i)
            ).pack(side="right", padx=10)

    # report_items is shared and mutated by other tabs, so re-scan it every
    # time this sub-tab is switched to, not just once at startup
    sub_tabs.configure(
        command=lambda: refresh_items_list()
        if sub_tabs.get() == "Report Contents" else None
    )

    refresh_items_list()
