import os
from tkinter import filedialog

import customtkinter as ctk
import pandas as pd

from output import parse_no_matches_table


def build_synonym_tab(parent, root=None):
    """
    parent: the tab frame to build the widgets into.
    root: the main app window, used as the file-dialog parent.
    """

    csv_path = ctk.StringVar()
    no_matches_path = ctk.StringVar()

    # INPUT SECTION----------------------------------------------------------

    ctk.CTkLabel(parent, text="🔤 SYNONYM SEARCH INPUT", font=(
        "Arial", 16, "bold")).pack(anchor="w", padx=10, pady=(10, 2))

    ctk.CTkLabel(
        parent,
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
        parent, text="Select CSV File (with 'Name' column)", command=choose_csv
    ).pack(fill="x", padx=10, pady=5)
    ctk.CTkLabel(parent, textvariable=csv_path, text_color="gray").pack(
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
        parent, text="Select no_matches.txt", command=choose_no_matches
    ).pack(fill="x", padx=10, pady=5)
    ctk.CTkLabel(parent, textvariable=no_matches_path, text_color="gray").pack(
        anchor="w", padx=10, pady=(0, 10))

    ctk.CTkLabel(parent, text="Or type species names (comma separated)").pack(
        anchor="w", padx=10)
    species_textbox = ctk.CTkTextbox(parent, height=80)
    species_textbox.pack(fill="x", padx=10, pady=(0, 10))

    status_label = ctk.CTkLabel(parent, text="No species loaded yet.")
    status_label.pack(anchor="w", padx=10, pady=(0, 5))

    species_preview = ctk.CTkTextbox(parent, height=200)
    species_preview.pack(fill="both", expand=True, padx=10, pady=(0, 10))
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

    ctk.CTkButton(
        parent, text="Load Species", command=load_species
    ).pack(fill="x", padx=10, pady=(0, 10))

    return get_species_list
