import customtkinter as ctk
from tkinter import filedialog
from Bio import Entrez
import pandas as pd
import os
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed


# NCBI SETTINGS-------------------------------------------

Entrez.email = "samadmalikg@gmail.com"
Entrez.api_key = "a9543111711b0671e59f806f680529ff4607"

df = None

INVALID_CHARS = '<>:"/\\|?*'


def sanitize(name):
    name = str(name).strip()
    for ch in INVALID_CHARS:
        name = name.replace(ch, "_")
    return name


# RATE LIMITER-----------------------------------------------
# Enforces a global minimum gap between NCBI requests, shared across
# all worker threads, so concurrency can't burst past NCBI's rate cap.

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


# FETCHING FASTA FROM NCBI------------------------------------

def get_marker_columns(dataframe):
    return [c for c in dataframe.columns if c.endswith("_accession")]


def fetch_fasta(accession, rate_limiter):

    try:
        rate_limiter.wait()

        handle = Entrez.efetch(
            db="nucleotide",
            id=accession,
            rettype="fasta",
            retmode="text"
        )

        text = handle.read()
        handle.close()

        text = text.strip()

        return text + "\n" if text else None

    except Exception as e:
        print("efetch error:", accession, e)
        return None


def write_results(results, base_dir, separate_species, separate_marker):

    groups = {}

    for species, marker, text in results:
        key_parts = []

        if separate_species:
            key_parts.append(sanitize(species))

        if separate_marker:
            key_parts.append(sanitize(marker))

        if not key_parts:
            key_parts = ["all_sequences"]

        groups.setdefault(tuple(key_parts), []).append(text)

    for key_parts, texts in groups.items():

        if key_parts == ("all_sequences",):
            folder = base_dir
        else:
            folder = os.path.join(base_dir, *key_parts)

        os.makedirs(folder, exist_ok=True)

        filename = f"{key_parts[-1]}.fasta"
        path = os.path.join(folder, filename)

        with open(path, "w", encoding="utf-8") as f:
            f.write("".join(texts))


# GUI SETUP---------------------------------------
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

app = ctk.CTk()
app.geometry("1250x820")
app.title("NCBI FASTA Export")


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


def update_preview(*args):
    sep_species = separate_species_var.get()
    sep_marker = separate_marker_var.get()

    if sep_species and sep_marker:
        text = (
            "output/\n"
            "  <species>/\n"
            "    <marker>/\n"
            "      <marker>.fasta"
        )
    elif sep_species:
        text = (
            "output/\n"
            "  <species>/\n"
            "    <species>.fasta"
        )
    elif sep_marker:
        text = (
            "output/\n"
            "  <marker>/\n"
            "    <marker>.fasta"
        )
    else:
        text = (
            "output/\n"
            "  all_sequences.fasta"
        )

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

update_preview()


# SETTINGS-----------------------------------------------------------------------------

ctk.CTkLabel(scroll, text="⚙ SETTINGS", font=(
    "Arial", 16, "bold")).pack(anchor="w", pady=(10, 5))

ctk.CTkLabel(scroll, text="Min. interval between NCBI requests (s)").pack(
    anchor="w")
sleep_entry = ctk.CTkEntry(scroll)
sleep_entry.insert(0, "0.1")
sleep_entry.pack(fill="x", pady=5)

ctk.CTkLabel(scroll, text="Concurrent workers").pack(anchor="w")
workers_entry = ctk.CTkEntry(scroll)
workers_entry.insert(0, "5")
workers_entry.pack(fill="x", pady=5)


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

    try:
        max_workers = max(1, int(workers_entry.get()))
    except ValueError:
        max_workers = 5

    jobs = []
    for _, row in df.iterrows():
        species = row["Name"]

        for col in marker_cols:
            accession = row[col]

            if pd.notna(accession) and str(accession).strip():
                marker = col[: -len("_accession")]
                jobs.append((species, marker, str(accession).strip()))

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

    with ThreadPoolExecutor(max_workers=max_workers) as executor:

        future_to_job = {
            executor.submit(fetch_fasta, accession, rate_limiter): (species, marker)
            for species, marker, accession in jobs
        }

        for future in as_completed(future_to_job):
            species, marker = future_to_job[future]

            try:
                fasta_text = future.result()
            except Exception as e:
                print("job error:", e)
                fasta_text = None

            if fasta_text:
                results.append((species, marker, fasta_text))

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
        separate_marker_var.get()
    )

    app.after(
        0,
        lambda: run_button.configure(state="normal")
    )

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
