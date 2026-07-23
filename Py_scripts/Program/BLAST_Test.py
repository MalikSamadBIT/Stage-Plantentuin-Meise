import os
import subprocess
import customtkinter as ctk
from tkinter import filedialog
import pandas as pd
import database


BLAST_BIN = r"B:\Stage\tools\blast\bin"

# db_fasta = r"B:\Stage\DB_test\DB_FASTA_Test.fasta"
query_fasta = "query.fasta"

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

tk = ctk.CTk()
tk.geometry("1250x820")
tk.title("BLAST+ test")


def build_database_tab(parent, root=None):
    """
    parent: the tab frame to build the widgets into.
    root: the main app window, used as the file-dialog parent.
    """
    db_path = ctk.StringVar()
    full_df = None
    view_df = None
    sort_state = {}

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
        top_bar, text="Select Database File...", command=choose_database
    ).pack(side="left", padx=(0, 5))

    ctk.CTkButton(
        top_bar, text="Reload", command=lambda: load_data()
    ).pack(side="left", padx=(0, 5))

    ctk.CTkButton(
        top_bar, text="Run BLAST", command=lambda: run_blast()
    ).pack(side="left", padx=(0, 5))

    query_bar = ctk.CTkFrame(parent, fg_color="transparent")
    query_bar.pack(fill="x", padx=10, pady=(0, 5))

    query_entry = ctk.CTkEntry(query_bar, placeholder_text="Enter the query sequence",
                               font=("Courier New", 18),
                               width=500)
    query_entry.pack(side="left", pady=10)

    ctk.CTkLabel(parent, textvariable=db_path, text_color="gray").pack(
        anchor="w", padx=10, pady=10)

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
        nonlocal full_df, view_df

        if not db_path.get():
            status_label.configure(text="Select a database file first.")
            return

        try:
            conn = database.connect(db_path.get())
            full_df = pd.read_sql_query(
                f"SELECT * FROM sequences", conn
            )
            conn.close()
        except Exception as e:
            status_label.configure(text=f"Failed to load database: {e}")
            return

    def run_blast():
        if full_df is None or full_df.empty:
            status_label.configure(
                text="Load a database first.")
            return

        query_seq = query_entry.get().strip()
        if not query_seq:
            status_label.configure(text="Enter a query sequence first.")
            return

        with open(query_fasta, "w") as f:
            f.write(f">query\n{query_seq}\n")

        path = filedialog.asksaveasfilename(
            parent=root,
            title="Run BLAST",
        )
        if not path:
            return

        accessions = [a for a in full_df["accession"].tolist() if a]

        try:
            conn = database.connect(db_path.get())
            placeholders = ",".join("?" for _ in accessions)
            rows = conn.execute(
                f"SELECT species, marker, accession, sequence FROM sequences "
                f"WHERE accession IN ({placeholders})",
                accessions
            ).fetchall()
            conn.close()
        except Exception as e:
            status_label.configure(text=f"Export failed: {e}")
            return

        with open(path, "w", encoding="utf-8") as f:
            for row in rows:
                header = f">{row['accession']} {row['species']} {row['marker']}"
                f.write(header + "\n" + row["sequence"] + "\n")

        status_label.configure(
            text=f"Exported {len(rows)} sequence(s) to {os.path.basename(path)}.")

        db_fasta = path

        try:
            # build a nucleotide BLAST database from the FASTA file
            subprocess.run(
                [os.path.join(BLAST_BIN, "makeblastdb.exe"),
                 "-in", db_fasta, "-dbtype", "nucl", "-out", "mydb"],
                check=True
            )

            # blastn query
            result = subprocess.run(
                [os.path.join(BLAST_BIN, "blastn.exe"),
                 "-query", query_fasta, "-db", "mydb", "-outfmt", "0"],
                capture_output=True, text=True, check=True
            )
        except subprocess.CalledProcessError as e:
            status_label.configure(text="BLAST run failed.")
            set_output(e.stderr or str(e))
            return

        set_output(result.stdout)
        status_label.configure(
            text=f"Exported {len(rows)} sequence(s) to {os.path.basename(path)}. BLAST complete.")


tabs = ctk.CTkTabview(tk)
tabs.pack(fill="both", expand=True, padx=10, pady=10)


Database_tab = tabs.add("Database")

build_database_tab(Database_tab, tk)

tk.mainloop()
