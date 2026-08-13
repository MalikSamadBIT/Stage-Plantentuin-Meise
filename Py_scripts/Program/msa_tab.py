import os
import subprocess
import sys
import threading
import tkinter
from tkinter import filedialog

import customtkinter as ctk
from PIL import Image
from Bio import SeqIO
from pymsaviz import MsaViz
from pymsa import (
    MSA, Entropy, PercentageOfNonGaps, PercentageOfTotallyConservedColumns,
    Star, SumOfPairs, PAM250, Blosum62
)
from pymsa.util.fasta import read_fasta_file_as_list_of_pairs


if getattr(sys, "frozen", False):
    MUSCLE_EXE = os.path.join(sys._MEIPASS, "tools", "muscle.exe")
else:
    MUSCLE_EXE = r"B:\Stage\tools\muscle.exe"


def merge_fasta_files(input_paths, output_path):
    records = []
    for path in input_paths:
        records.extend(SeqIO.parse(path, "fasta"))
    SeqIO.write(records, output_path, "fasta")
    return len(records)


def run_msa(input_file, output_dir, show_grid, show_count, show_consensus,
            revcomp_ids=None):
    muscle_input = input_file

    if revcomp_ids:
        muscle_input = os.path.join(
            output_dir, os.path.basename(input_file) + "_revcomp.fasta")
        records = list(SeqIO.parse(input_file, "fasta"))
        for record in records:
            if record.id in revcomp_ids:
                record.seq = record.seq.reverse_complement()
        SeqIO.write(records, muscle_input, "fasta")

    aligned_file = os.path.join(
        output_dir, os.path.basename(input_file) + "_aligned.fasta")

    subprocess.run(
        [MUSCLE_EXE, "-align", muscle_input, "-output", aligned_file],
        check=True
    )

    mv = MsaViz(
        aligned_file, color_scheme="Clustal",
        show_grid=show_grid, show_count=show_count, show_consensus=show_consensus
    )
    report_path = os.path.join(output_dir, "msa_report.png")
    mv.savefig(report_path)

    return report_path, aligned_file


def _max_possible_sum_of_pairs(msa, substitution_matrix):

    best_self_score = max(
        value for (a, b), value in substitution_matrix.get_distance_matrix().items()
        if a == b
    )
    num_sequences = msa.number_of_sequences
    num_pairs_per_column = num_sequences * (num_sequences - 1) / 2

    return len(msa) * num_pairs_per_column * best_self_score


def _percent_of_max_sum_of_pairs(msa, substitution_matrix, sp_score):
    max_possible = _max_possible_sum_of_pairs(msa, substitution_matrix)
    return (sp_score / max_possible) * 100 if max_possible else 0.0


# (option key, checkbox label) - order here is the order scores are shown in
SCORE_OPTIONS = [
    ("non_gaps", "Percentage of non-gaps"),
    ("conserved_columns", "Percentage of totally conserved columns"),
    ("entropy", "Entropy"),
    ("sop_blosum62", "Sum of Pairs (Blosum62)"),
    ("sop_pam250", "Sum of Pairs (PAM250)"),
    ("star_blosum62", "Star (Blosum62)"),
    ("star_pam250", "Star (PAM250)"),
]


def compute_msa_scores(fasta_path, selected=None):
    # fasta_path must already be aligned
    if selected is None:
        selected = {key for key, _ in SCORE_OPTIONS}

    sequences = read_fasta_file_as_list_of_pairs(fasta_path)
    aligned_sequences = [pair[1] for pair in sequences]
    sequences_id = [pair[0] for pair in sequences]

    msa = MSA(aligned_sequences, sequences_id)

    scores = {}

    if "non_gaps" in selected:
        scores["Percentage of non-gaps"] = PercentageOfNonGaps(msa).compute()

    if "conserved_columns" in selected:
        scores["Percentage of totally conserved columns"] = \
            PercentageOfTotallyConservedColumns(msa).compute()

    if "entropy" in selected:
        scores["Entropy"] = Entropy(msa).compute()

    if "sop_blosum62" in selected:
        blosum62 = Blosum62()
        sp_score = SumOfPairs(msa, blosum62).compute()
        scores["Sum of Pairs (Blosum62)"] = sp_score
        scores["Sum of Pairs (Blosum62) - % of max possible"] = \
            _percent_of_max_sum_of_pairs(msa, blosum62, sp_score)

    if "sop_pam250" in selected:
        pam250 = PAM250()
        sp_score = SumOfPairs(msa, pam250).compute()
        scores["Sum of Pairs (PAM250)"] = sp_score
        scores["Sum of Pairs (PAM250) - % of max possible"] = \
            _percent_of_max_sum_of_pairs(msa, pam250, sp_score)

    if "star_blosum62" in selected:
        scores["Star (Blosum62)"] = Star(msa, Blosum62()).compute()

    if "star_pam250" in selected:
        scores["Star (PAM250)"] = Star(msa, PAM250()).compute()

    return scores


def build_msa_tab(parent, root=None, report_items=None):
    """
    parent: the CTkTabview tab frame to build the widgets into.
    root: the main app window, used as the file-dialog parent.
    report_items: shared list the Gap Report tab reads from - "Add to
        Report" (on the MSA Results tab) pushes the currently shown
        alignment image plus its scores (if computed) here. Falls back to
        a private (unread) one if this tab is ever used standalone.
    """

    if report_items is None:
        report_items = []

    sub_tabs = ctk.CTkTabview(parent)
    sub_tabs.pack(fill="both", expand=True)

    MSA_merge = sub_tabs.add("Merge FASTA")
    MSA_run = sub_tabs.add("Run MSA")
    MSA_results = sub_tabs.add("MSA Results")
    MSA_score = sub_tabs.add("MSA Score")

    file_path = ctk.StringVar()
    output_dir = ctk.StringVar()
    score_file_path = ctk.StringVar()
    merge_output_path = ctk.StringVar()
    merge_input_paths = []
    last_scores = None  # set by "Compute Scores" - read by "Add to Report"

    def load():
        path = filedialog.askopenfilename(
            parent=root, filetypes=[("FASTA", "*.fasta")])
        if path:
            file_path.set(path)
            show_seq_ids(path)

    def choose_output():
        path = filedialog.askdirectory(parent=root)
        if path:
            output_dir.set(path)

    # MERGE FASTA----------------------------------------------------------------

    ctk.CTkLabel(MSA_merge, text="📁 FASTA FILES TO MERGE", font=(
        "Arial", 16, "bold")).pack(anchor="w", pady=(5, 2))

    merge_button_row = ctk.CTkFrame(MSA_merge, fg_color="transparent")
    merge_button_row.pack(fill="x", pady=(0, 5))

    merge_file_list_frame = ctk.CTkScrollableFrame(MSA_merge, height=250)

    def refresh_merge_file_list():
        for widget in merge_file_list_frame.winfo_children():
            widget.destroy()

        if not merge_input_paths:
            ctk.CTkLabel(
                merge_file_list_frame, text="No files selected yet.",
                text_color="gray"
            ).pack(anchor="w", pady=5)
            return

        for path in merge_input_paths:
            row = ctk.CTkFrame(merge_file_list_frame, fg_color="transparent")
            row.pack(fill="x", pady=2)

            ctk.CTkLabel(row, text=os.path.basename(path), anchor="w").pack(
                side="left", fill="x", expand=True)

            ctk.CTkButton(
                row, text="✕", width=28,
                command=lambda p=path: remove_merge_file(p)
            ).pack(side="right")

    def add_merge_files():
        paths = filedialog.askopenfilenames(
            parent=root,
            title="Select FASTA files to merge",
            filetypes=[("FASTA", "*.fasta *.fa *.fna"), ("All files", "*.*")]
        )
        for path in paths:
            if path not in merge_input_paths:
                merge_input_paths.append(path)
        refresh_merge_file_list()

    def remove_merge_file(path):
        merge_input_paths.remove(path)
        refresh_merge_file_list()

    def clear_merge_files():
        merge_input_paths.clear()
        refresh_merge_file_list()

    ctk.CTkButton(
        merge_button_row, text="Add FASTA Files...", command=add_merge_files
    ).pack(side="left", padx=(0, 5))

    ctk.CTkButton(
        merge_button_row, text="Clear All", command=clear_merge_files, width=80
    ).pack(side="left")

    merge_file_list_frame.pack(fill="both", expand=True, pady=(0, 10))

    ctk.CTkLabel(MSA_merge, text="💾 OUTPUT FILE", font=(
        "Arial", 16, "bold")).pack(anchor="w", pady=(0, 2))

    def choose_merge_output():
        path = filedialog.asksaveasfilename(
            parent=root,
            title="Save merged FASTA as",
            defaultextension=".fasta",
            filetypes=[("FASTA", "*.fasta"), ("All files", "*.*")]
        )
        if path:
            merge_output_path.set(path)

    ctk.CTkButton(
        MSA_merge, text="Choose Output File...", command=choose_merge_output
    ).pack(fill="x", pady=5)

    ctk.CTkLabel(
        MSA_merge, textvariable=merge_output_path, text_color="gray"
    ).pack(anchor="w", pady=(0, 10))

    merge_status_label = ctk.CTkLabel(MSA_merge, text="")
    merge_status_label.pack(anchor="w", pady=(0, 5))

    merge_button = ctk.CTkButton(MSA_merge, text="▶ Merge")
    merge_button.pack(fill="x", pady=(0, 10))

    def merge_worker(input_paths, output_path):
        try:
            count = merge_fasta_files(input_paths, output_path)
        except Exception as e:
            parent.after(0, lambda: merge_status_label.configure(
                text=f"Merge failed: {e}"))
            parent.after(0, lambda: merge_button.configure(state="normal"))
            return

        def finish():
            merge_status_label.configure(
                text=f"Done - {count} sequences written to "
                f"{os.path.basename(output_path)}.")
            merge_button.configure(state="normal")

        parent.after(0, finish)

    def start_merge():
        if len(merge_input_paths) < 2:
            merge_status_label.configure(
                text="Select at least two FASTA files.")
            return

        if not merge_output_path.get():
            merge_status_label.configure(text="Choose an output file first.")
            return

        merge_status_label.configure(text="Merging...")
        merge_button.configure(state="disabled")

        thread = threading.Thread(
            target=merge_worker,
            args=(list(merge_input_paths), merge_output_path.get()),
            daemon=True
        )
        thread.start()

    merge_button.configure(command=start_merge)

    refresh_merge_file_list()

    # FILE SELECTION-------------------------------------------------------------

    ctk.CTkLabel(MSA_run, text="📁 FILE INPUT", font=(
        "Arial", 16, "bold")).pack(anchor="w", pady=(5, 2))

    ctk.CTkButton(MSA_run, text="Select FASTA File for MSA",
                  command=load).pack(fill="x", pady=5)
    ctk.CTkLabel(MSA_run, textvariable=file_path).pack(
        anchor="w", pady=(0, 10))

    ctk.CTkLabel(
        MSA_run,
        text="Sequence IDs in file (check to use reverse complement)",
        font=("Arial", 14, "bold")
    ).pack(anchor="w", pady=(0, 2))

    seq_ids_frame = ctk.CTkScrollableFrame(MSA_run, height=100)
    seq_ids_frame.pack(fill="x", pady=(0, 10))

    revcomp_vars = {}  # sequence id -> BooleanVar, rebuilt on each file load

    def show_seq_ids(path):
        for widget in seq_ids_frame.winfo_children():
            widget.destroy()
        revcomp_vars.clear()

        try:
            records = list(SeqIO.parse(path, "fasta"))
        except Exception as e:
            ctk.CTkLabel(
                seq_ids_frame, text=f"Could not read sequence IDs: {e}"
            ).pack(anchor="w")
            return

        if not records:
            ctk.CTkLabel(
                seq_ids_frame, text="No sequences found in file."
            ).pack(anchor="w")
            return

        for record in records:
            var = ctk.BooleanVar(value=False)
            revcomp_vars[record.id] = var
            ctk.CTkCheckBox(
                seq_ids_frame, text=record.id, variable=var
            ).pack(anchor="w", pady=1)

    ctk.CTkButton(MSA_run, text="Select Output Folder",
                  command=choose_output).pack(fill="x", pady=5)
    ctk.CTkLabel(MSA_run, textvariable=output_dir).pack(
        anchor="w", pady=(0, 10))

    grid_var = ctk.BooleanVar(value=True)
    count_var = ctk.BooleanVar(value=True)
    consensus_var = ctk.BooleanVar(value=True)

    ctk.CTkCheckBox(
        MSA_run, text="Show a grid on the MSA results", variable=grid_var
    ).pack(anchor="w", pady=2)

    ctk.CTkCheckBox(
        MSA_run, text="Show the count on the MSA results", variable=count_var
    ).pack(anchor="w", pady=2)

    ctk.CTkCheckBox(
        MSA_run, text="Show the consensus on the MSA results", variable=consensus_var
    ).pack(anchor="w", pady=2)

    status_label = ctk.CTkLabel(MSA_run, text="")
    status_label.pack(anchor="w", pady=(10, 0))

    run_button = ctk.CTkButton(MSA_run, text="Run MSA")
    run_button.pack(fill="x", pady=5)

    # RESULTS----------------------------------------------------------------

    results_placeholder = ctk.CTkLabel(
        MSA_results, text="No results yet — run an MSA first.")
    results_placeholder.place(anchor="c", relx=.5, rely=.5)

    def show_results(image_path):
        for widget in MSA_results.winfo_children():
            widget.destroy()

        img = Image.open(image_path)
        x, y = img.size

        frame = ctk.CTkScrollableFrame(
            MSA_results, width=700, height=y + 20, orientation="horizontal"
        )
        frame.place(anchor="c", relx=.5, rely=.5)

        msa_image = ctk.CTkImage(
            light_image=img, dark_image=img, size=(x, y))

        ctk.CTkLabel(frame, text="", image=msa_image).pack(pady=10)

        top_bar = ctk.CTkFrame(MSA_results, fg_color="transparent")
        top_bar.place(relx=0.5, rely=0.02, anchor="n")

        results_status_label = ctk.CTkLabel(
            top_bar, text="", text_color="gray")

        def add_to_report():
            title_source = file_path.get() or score_file_path.get()
            title = f"MSA - {os.path.basename(title_source)}" \
                if title_source else "MSA result"

            with open(image_path, "rb") as f:
                image_bytes = f.read()

            report_items.append({
                "type": "msa",
                "title": title,
                "subtitle": "Added from MSA tab",
                "image_bytes": image_bytes,
                "scores": dict(last_scores) if last_scores else None,
            })
            results_status_label.configure(text="Added to report.")

        ctk.CTkButton(
            top_bar, text="Add to Report", command=add_to_report
        ).pack(side="left", padx=(0, 8))
        results_status_label.pack(side="left")

    # SCORE--------------------------------------------------------------

    def load_score_file():
        path = filedialog.askopenfilename(
            parent=root, filetypes=[("FASTA", "*.fasta")])
        if path:
            score_file_path.set(path)

    ctk.CTkLabel(MSA_score, text="📁 ALIGNED FASTA FILE", font=(
        "Arial", 16, "bold")).pack(anchor="w", pady=(5, 2))

    ctk.CTkButton(
        MSA_score, text="Select Aligned FASTA File", command=load_score_file
    ).pack(fill="x", pady=5)
    ctk.CTkLabel(MSA_score, textvariable=score_file_path).pack(
        anchor="w", pady=(0, 10))

    ctk.CTkLabel(MSA_score, text="Scores to compute", font=(
        "Arial", 14, "bold")).pack(anchor="w", pady=(5, 2))

    score_option_vars = {
        key: ctk.BooleanVar(value=True) for key, _ in SCORE_OPTIONS
    }

    for key, label in SCORE_OPTIONS:
        ctk.CTkCheckBox(
            MSA_score, text=label, variable=score_option_vars[key]
        ).pack(anchor="w", pady=1)

    score_status_label = ctk.CTkLabel(MSA_score, text="")
    score_status_label.pack(anchor="w", pady=(0, 5))

    score_button = ctk.CTkButton(MSA_score, text="Compute Scores")
    score_button.pack(fill="x", pady=5)

    score_results_box = ctk.CTkTextbox(
        MSA_score, height=250, font=("Consolas", 16))
    score_results_box.pack(fill="both", expand=True, pady=(10, 0))
    score_results_box.configure(state="disabled")

    def show_scores(scores):
        score_results_box.configure(state="normal")
        score_results_box.delete("1.0", "end")
        for label, value in scores.items():
            if "% of max possible" in label:
                formatted = f"{value:.2f}%"
            elif isinstance(value, float):
                formatted = f"{value:.4f}"
            else:
                formatted = str(value)
            score_results_box.insert("end", f"{label}: {formatted}\n")
        score_results_box.configure(state="disabled")

    def score_worker(fasta_path, selected):
        try:
            scores = compute_msa_scores(fasta_path, selected)
        except Exception as e:
            parent.after(0, lambda: score_status_label.configure(
                text=f"Scoring failed: {e}"))
            parent.after(0, lambda: score_button.configure(state="normal"))
            return

        def finish():
            nonlocal last_scores
            last_scores = scores
            score_status_label.configure(text="Done.")
            score_button.configure(state="normal")
            show_scores(scores)

        parent.after(0, finish)

    def compute_and_show():
        if not score_file_path.get():
            score_status_label.configure(
                text="Select an aligned FASTA file first.")
            return

        selected = {key for key, var in score_option_vars.items() if var.get()}

        if not selected:
            score_status_label.configure(
                text="Select at least one score to compute.")
            return

        score_status_label.configure(text="Computing scores...")
        score_button.configure(state="disabled")

        thread = threading.Thread(
            target=score_worker,
            args=(score_file_path.get(), selected),
            daemon=True
        )
        thread.start()

    score_button.configure(command=compute_and_show)

    # RUN (background thread, so a slow MUSCLE alignment doesn't freeze
    # the rest of the app while it runs)------------------------------------

    def run_worker(input_file, out_dir, grid, count, consensus, revcomp_ids):
        try:
            report_path, aligned_file = run_msa(
                input_file, out_dir, grid, count, consensus, revcomp_ids)
        except subprocess.CalledProcessError as e:
            parent.after(0, lambda: status_label.configure(
                text=f"MSA failed: {e}"))
            parent.after(0, lambda: run_button.configure(state="normal"))
            return
        except Exception as e:
            parent.after(0, lambda: status_label.configure(
                text=f"MSA failed: {e}"))
            parent.after(0, lambda: run_button.configure(state="normal"))
            return

        def finish():
            status_label.configure(text="Done.")
            run_button.configure(state="normal")
            show_results(report_path)
            score_file_path.set(aligned_file)
            sub_tabs.set("MSA Results")

        parent.after(0, finish)

    def run_and_show():
        if not file_path.get() or not output_dir.get():
            status_label.configure(
                text="Select a FASTA file and an output folder first.")
            return

        status_label.configure(text="Running MSA...")
        run_button.configure(state="disabled")

        revcomp_ids = {
            seq_id for seq_id, var in revcomp_vars.items() if var.get()}

        thread = threading.Thread(
            target=run_worker,
            args=(file_path.get(), output_dir.get(),
                  grid_var.get(), count_var.get(), consensus_var.get(),
                  revcomp_ids),
            daemon=True
        )
        thread.start()

    run_button.configure(command=run_and_show)
