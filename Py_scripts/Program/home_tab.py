import os

import customtkinter as ctk


LOGO_PATH = os.path.join(
    os.path.dirname(__file__), "assets", "Meise_Botanic_Garden_logo.png")

# (tab title, one-line description, jump-to name understood by tabview.set())
TAB_OVERVIEW = [
    ("Settings",
     "NCBI credentials, the database backend (SQLite or MySQL), scoring "
     "weights, target/neighbor country groups, and saved presets."),
    ("Fetch FASTA",
     "The main pipeline - load a species list and markers, then search "
     "NCBI and/or BOLD and save the best-scoring sequences."),
    ("Retrieval Rate",
     "Charts showing how much sequence coverage you have per species and "
     "marker after a run."),
    ("Synonym search",
     "Looks up alternate/vernacular names for a species so searches aren't "
     "limited to its canonical Latin name."),
    ("MSA",
     "Multiple sequence alignment and scoring for a chosen species/marker."),
    ("Database",
     "Browse, filter, export, query, and transfer (SQLite -> MySQL) the "
     "sequence database."),
    ("BLAST",
     "Build a local BLAST database from your sequences and search it with "
     "one query or a batch FASTA file."),
    ("Maps",
     "View species occurrence records on a map and cross-check them "
     "against what's already in the database."),
    ("Gap Report",
     "Finds species/markers with missing or thin coverage, and assembles "
     "a Word/PDF report from snapshots pushed by the other tabs."),
    ("Terminal",
     "Live log output while a Fetch FASTA run is in progress."),
]


def build_home_tab(parent, root=None, tabview=None):
    """
    parent: the tab frame to build the widgets into.
    root: the main app window (unused here, kept for consistency with the
        other build_*_tab functions).
    tabview: the shared ctk.CTkTabview - lets the tab-overview rows below
        jump straight to that tab via tabview.set(name). The Home tab
        works fine without it (the buttons just won't be shown).
    """

    scroll = ctk.CTkScrollableFrame(parent)
    scroll.pack(fill="both", expand=True)

    # HEADER / LOGO----------------------------------------------------------

    header = ctk.CTkFrame(scroll, fg_color="transparent")
    header.pack(fill="x", padx=20, pady=(20, 10))

    if os.path.isfile(LOGO_PATH):
        from PIL import Image
        logo_img = Image.open(LOGO_PATH)
        logo = ctk.CTkImage(
            light_image=logo_img, dark_image=logo_img, size=(181, 110))
        ctk.CTkLabel(header, image=logo, text="").pack(
            side="left", padx=(0, 20))
    else:
        # placeholder until the real logo is dropped in at LOGO_PATH
        ctk.CTkLabel(header, text="🌿", font=("Arial", 60)).pack(
            side="left", padx=(0, 20))

    title_box = ctk.CTkFrame(header, fg_color="transparent")
    title_box.pack(side="left", fill="both", expand=True)

    ctk.CTkLabel(
        title_box, text="Flora Fetch",
        font=("Arial", 26, "bold")
    ).pack(anchor="w")
    ctk.CTkLabel(
        title_box,
        text="NCBI / BOLD DNA barcode pipeline - developed during an "
             "internship at Plantentuin Meise (Meise Botanic Garden)",
        font=("Arial", 14), text_color="gray"
    ).pack(anchor="w", pady=(2, 0))

    # INTRODUCTION-------------------------------------------------------

    ctk.CTkLabel(
        scroll, text="What this program does", font=("Arial", 18, "bold")
    ).pack(anchor="w", padx=20, pady=(20, 5))

    ctk.CTkLabel(
        scroll,
        text="This program searches NCBI GenBank and BOLD Systems for DNA "
             "barcode sequences (ITS, rbcL, matK, and other markers) for a "
             "list of plant species, scores and ranks the candidates it "
             "finds (by geographic origin, sequence length, and quality), "
             "and builds a reference database you can browse, query, "
             "export, and BLAST against - built to help assemble and "
             "maintain a DNA barcode reference collection for the Belgian "
             "flora.",
        justify="left", wraplength=1000
    ).pack(anchor="w", padx=20, pady=(0, 15))

    # GETTING STARTED------------------------------------------------------

    ctk.CTkLabel(
        scroll, text="Getting started", font=("Arial", 18, "bold")
    ).pack(anchor="w", padx=20, pady=(10, 5))

    steps = [
        "Settings - enter your NCBI email/API key, and choose or create "
        "the database that fetched sequences will be saved to.",
        "Fetch FASTA - load a species list (CSV or typed) and pick "
        "markers, then run the pipeline to search and score sequences.",
        "Retrieval Rate / Gap Report - see which species/markers still "
        "need coverage.",
        "Database / BLAST / Maps - browse what's been collected, search "
        "it, and cross-check it against occurrence records.",
    ]
    for i, step in enumerate(steps, start=1):
        ctk.CTkLabel(
            scroll, text=f"{i}.  {step}",
            justify="left", wraplength=1000, anchor="w"
        ).pack(anchor="w", padx=20, pady=(0, 4))

    # TAB OVERVIEW---------------------------------------------------------

    ctk.CTkLabel(
        scroll, text="Tabs at a glance", font=("Arial", 18, "bold")
    ).pack(anchor="w", padx=20, pady=(20, 5))

    overview_frame = ctk.CTkFrame(scroll, fg_color="transparent")
    overview_frame.pack(fill="x", padx=20, pady=(0, 20))

    for name, description in TAB_OVERVIEW:
        row = ctk.CTkFrame(overview_frame, fg_color="transparent")
        row.pack(fill="x", pady=4)

        if tabview is not None:
            ctk.CTkButton(
                row, text=name, width=140,
                command=lambda n=name: tabview.set(n)
            ).pack(side="left", padx=(0, 10))
        else:
            ctk.CTkLabel(
                row, text=name, width=140, font=("Arial", 13, "bold"),
                anchor="w"
            ).pack(side="left", padx=(0, 10))

        ctk.CTkLabel(
            row, text=description, justify="left", wraplength=820,
            text_color="gray", anchor="w"
        ).pack(side="left", fill="x", expand=True)
