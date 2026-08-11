import ctypes
import os
import subprocess
import sys
import tempfile
import threading
from tkinter import filedialog

import customtkinter as ctk
import pandas as pd

import database

# Same frozen-vs-dev resolution as MUSCLE_EXE in msa_tab.py - see that file
# for why sys._MEIPASS covers both PyInstaller packaging modes.
if getattr(sys, "frozen", False):
    BLAST_BIN = os.path.join(sys._MEIPASS, "tools", "blast", "bin")
else:
    BLAST_BIN = r"B:\Stage\tools\blast\bin"


def _blast_safe_path(path):

    directory, name = os.path.split(path)
    if " " not in directory or not os.path.isdir(directory):
        return path

    buf = ctypes.create_unicode_buffer(260)
    if ctypes.windll.kernel32.GetShortPathNameW(directory, buf, 260):
        return os.path.join(buf.value, name)

    return path


def build_blast_tab(parent, root=None):
    """
    parent: the tab frame to build the widgets into.
    root: the main app window, used as the file-dialog/dialog parent.
    """

    # a real temp path, not a bare relative filename - a frozen build's
    # working directory isn't guaranteed to be writable (or predictable)
    query_fasta = os.path.join(tempfile.gettempdir(), "flora_fetch_query.fasta")

    db_path = ctk.StringVar()
    blast_db_path = ctk.StringVar()
    full_df = None

    # TOP BAR----------------------------------------------------------------

    top_bar = ctk.CTkFrame(parent, fg_color="transparent")
    top_bar.pack(fill="x", padx=10, pady=(10, 5))

    def choose_database():
        path = filedialog.askopenfilename(
            parent=root,
            title="Select a database file",
            filetypes=[("SQLite database", "*.db"), ("All files", "*.*")]
        )
        if path:
            db_path.set(path)
            load_data()

    ctk.CTkButton(
        top_bar, text="Select Database", command=choose_database
    ).pack(side="left", padx=(0, 5))

    ctk.CTkButton(
        top_bar, text="Reload", command=lambda: load_data()
    ).pack(side="left", padx=(0, 5))

    ctk.CTkButton(
        top_bar, text="Select/Create BLAST Database",
        command=lambda: open_blast_db_dialog()
    ).pack(side="left", padx=(0, 5))

    query_bar = ctk.CTkFrame(parent, fg_color="transparent")
    query_bar.pack(fill="x", padx=10, pady=(0, 5))

    query_entry = ctk.CTkEntry(
        query_bar, placeholder_text="Enter the query sequence",
        font=("Courier New", 18), width=500
    )
    query_entry.pack(side="left", pady=10)

    # BATCH QUERY (FASTA FILE)-----------------------------------------

    query_file_path = ctk.StringVar()

    def choose_query_file():
        path = filedialog.askopenfilename(
            parent=root,
            title="Select a FASTA file with one or more query sequences",
            filetypes=[("FASTA", "*.fasta *.fa *.fna"), ("All files", "*.*")]
        )
        if path:
            query_file_path.set(path)

    def clear_query_file():
        query_file_path.set("")

    query_file_bar = ctk.CTkFrame(parent, fg_color="transparent")
    query_file_bar.pack(fill="x", padx=10, pady=(0, 5))

    ctk.CTkButton(
        query_file_bar, text="Load Query FASTA File...",
        command=choose_query_file
    ).pack(side="left", padx=(0, 5))

    ctk.CTkButton(
        query_file_bar, text="Clear", command=clear_query_file, width=60
    ).pack(side="left")

    ctk.CTkLabel(
        parent, textvariable=query_file_path, text_color="gray"
    ).pack(anchor="w", padx=10, pady=(0, 2))

    ctk.CTkLabel(
        parent,
        text="A loaded FASTA file BLASTs every sequence in it and takes "
             "priority over the single query above - use Clear to go back "
             "to typing one sequence.",
        text_color="gray", font=("Arial", 11)
    ).pack(anchor="w", padx=10, pady=(0, 5))

    blast_type_var = ctk.StringVar(value="blastn")

    run_bar = ctk.CTkFrame(parent, fg_color="transparent")
    run_bar.pack(fill="x", padx=10, pady=(0, 5))

    ctk.CTkLabel(run_bar, text="BLAST type:").pack(side="left", padx=(0, 5))

    ctk.CTkOptionMenu(
        run_bar, variable=blast_type_var,
        values=["blastn", "blastp", "blastx", "tblastn", "tblastx"]
    ).pack(side="left", padx=(0, 10))

    run_button = ctk.CTkButton(
        run_bar, text="Run BLAST", command=lambda: run_blast()
    )
    run_button.pack(side="left", padx=(0, 5))

    ctk.CTkLabel(parent, textvariable=db_path, text_color="gray").pack(
        anchor="w", padx=10, pady=10)

    ctk.CTkLabel(parent, textvariable=blast_db_path, text_color="gray").pack(
        anchor="w", padx=10, pady=(0, 5))

    status_label = ctk.CTkLabel(
        parent, text="No database loaded yet.", text_color="gray")
    status_label.pack(anchor="w", padx=10, pady=(0, 5))

    output_box = ctk.CTkTextbox(parent, font=("Courier New", 18))
    output_box.pack(fill="both", expand=True, padx=10, pady=(0, 10))
    output_box.configure(state="disabled")

    def set_output(text):
        output_box.configure(state="normal")
        output_box.delete("1.0", "end")
        output_box.insert("1.0", text)
        output_box.configure(state="disabled")

    # DATA LOADING----------------------------------------

    def load_data():
        nonlocal full_df

        if not db_path.get():
            status_label.configure(text="Select a database file first.")
            return

        try:
            conn = database.connect(db_path.get())
            full_df = database.query_df(conn, "SELECT * FROM sequences_view")
            conn.close()
        except Exception as e:
            status_label.configure(text=f"Failed to load database: {e}")
            return

    # BLAST DATABASE SELECTION / CREATION----------------------------------

    def open_blast_db_dialog():
        dialog = ctk.CTkToplevel(root)
        dialog.title("Select/Create BLAST Database")
        dialog.geometry("420x150")
        dialog.transient(root)
        dialog.grab_set()

        ctk.CTkLabel(
            dialog, text="Create a new BLAST database or select an existing one:"
        ).pack(padx=20, pady=(20, 10))

        def do_create():
            dialog.destroy()
            create_blast_db()

        def do_select():
            dialog.destroy()
            select_blast_db()

        btn_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        btn_frame.pack(pady=10)

        ctk.CTkButton(
            btn_frame, text="Create New Database", command=do_create
        ).pack(side="left", padx=10)

        ctk.CTkButton(
            btn_frame, text="Select Existing Database", command=do_select
        ).pack(side="left", padx=10)

    def create_blast_db():
        if full_df is None or full_df.empty:
            status_label.configure(text="Load a database first.")
            return

        path = filedialog.asksaveasfilename(
            parent=root,
            title="Export sequences and create BLAST database",
        )
        if not path:
            return

        accessions = [a for a in full_df["accession"].tolist() if a]

        try:
            conn = database.connect(db_path.get())
            rows = database.fetch_by_accessions(conn, accessions)
            conn.close()
        except Exception as e:
            status_label.configure(text=f"Export failed: {e}")
            return

        with open(path, "w", encoding="utf-8") as f:
            for row in rows:
                header = f">{row['accession']} {row['species']} {row['marker']}"
                f.write(header + "\n" + row["sequence"] + "\n")

        db_out = os.path.splitext(path)[0]

        try:
            # build a nucleotide BLAST database from the FASTA file
            subprocess.run(
                [os.path.join(BLAST_BIN, "makeblastdb.exe"),
                 "-in", _blast_safe_path(path), "-dbtype", "nucl",
                 "-out", _blast_safe_path(db_out)],
                capture_output=True, text=True, check=True
            )
        except subprocess.CalledProcessError as e:
            status_label.configure(text="Failed to create BLAST database.")
            set_output(e.stderr or str(e))
            return

        blast_db_path.set(db_out)
        status_label.configure(
            text=f"Exported {len(rows)} sequence(s) and created BLAST database "
            f"'{os.path.basename(db_out)}'.")

    def select_blast_db():
        path = filedialog.askopenfilename(
            parent=root,
            title="Select an existing BLAST database",
            filetypes=[("BLAST nucleotide index", "*.nin"),
                       ("All files", "*.*")]
        )
        if not path:
            return

        blast_db_path.set(os.path.splitext(path)[0])
        status_label.configure(
            text=f"Using existing BLAST database "
            f"'{os.path.basename(blast_db_path.get())}'.")

    def run_blast():
        if not blast_db_path.get():
            status_label.configure(
                text="Select or create a BLAST database first.")
            return

        loaded_file = query_file_path.get()

        if loaded_file:
            if not os.path.isfile(loaded_file):
                status_label.configure(
                    text="The loaded query FASTA file no longer exists.")
                return

            query_arg = _blast_safe_path(os.path.abspath(loaded_file))

            with open(loaded_file, encoding="utf-8", errors="ignore") as f:
                query_count = f.read().count(">")

            batch_note = (
                f" (batch of {query_count} "
                f"quer{'y' if query_count == 1 else 'ies'})"
            )
        else:
            query_seq = query_entry.get().strip()
            if not query_seq:
                status_label.configure(
                    text="Enter a query sequence or load a query FASTA "
                         "file first.")
                return

            with open(query_fasta, "w") as f:
                f.write(f">query\n{query_seq}\n")

            query_arg = _blast_safe_path(os.path.abspath(query_fasta))
            batch_note = ""

        blast_program = blast_type_var.get()
        db_arg = _blast_safe_path(blast_db_path.get())

        run_button.configure(state="disabled")
        status_label.configure(
            text=f"Running {blast_program}...", text_color="gray")

        def do_run():
            try:
                result = subprocess.run(
                    [os.path.join(BLAST_BIN, f"{blast_program}.exe"),
                     "-query", query_arg, "-db", db_arg, "-outfmt", "0"],
                    capture_output=True, text=True, check=True
                )
            except subprocess.CalledProcessError as e:
                error_text = e.stderr or str(e)
                parent.after(0, lambda: blast_failed(error_text))
                return
            parent.after(
                0, lambda: blast_succeeded(
                    result.stdout, blast_program, batch_note))

        threading.Thread(target=do_run, daemon=True).start()

    def blast_failed(error_text):
        status_label.configure(text="BLAST run failed.", text_color="red")
        set_output(error_text)
        run_button.configure(state="normal")

    def blast_succeeded(stdout, blast_program, batch_note):
        set_output(stdout)
        status_label.configure(
            text=f"{blast_program} complete.{batch_note}", text_color="white")
        run_button.configure(state="normal")
