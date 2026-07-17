import os
import subprocess
import threading
import tkinter
from tkinter import filedialog

import customtkinter as ctk
from PIL import Image
from pymsaviz import MsaViz
from pymsa import (
    MSA, Entropy, PercentageOfNonGaps, PercentageOfTotallyConservedColumns,
    Star, SumOfPairs, PAM250, Blosum62
)
from pymsa.util.fasta import read_fasta_file_as_list_of_pairs

MUSCLE_EXE = r"B:\Stage\tools\muscle.exe"


def run_msa(input_file, output_dir, show_grid, show_count, show_consensus):
    aligned_file = os.path.join(
        output_dir, os.path.basename(input_file) + "_aligned.fasta")

    subprocess.run(
        [MUSCLE_EXE, "-align", input_file, "-output", aligned_file],
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
    # Best case for a column: every pair of sequences shares whichever
    # character scores highest against itself in the matrix (e.g. W-W in
    # Blosum62/PAM250) - that's the ceiling a real column's score is
    # compared against.
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
    # fasta_path must already be aligned (equal-length sequences) - i.e.
    # the *_aligned.fasta MUSCLE produces, not the raw input FASTA
    # selected: set of SCORE_OPTIONS keys to compute - None/omitted means
    # compute everything, and skipping unselected ones also saves time on
    # larger alignments (Sum of Pairs/Star are the slowest of the bunch)
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


def build_msa_tab(parent, root=None):
    """
    parent: the CTkTabview tab frame to build the widgets into.
    root: the main app window, used as the file-dialog parent.
    """

    sub_tabs = ctk.CTkTabview(parent)
    sub_tabs.pack(fill="both", expand=True)

    MSA_run = sub_tabs.add("Run MSA")
    MSA_results = sub_tabs.add("MSA Results")
    MSA_score = sub_tabs.add("MSA Score")

    file_path = ctk.StringVar()
    output_dir = ctk.StringVar()
    score_file_path = ctk.StringVar()

    def load():
        path = filedialog.askopenfilename(
            parent=root, filetypes=[("FASTA", "*.fasta")])
        if path:
            file_path.set(path)

    def choose_output():
        path = filedialog.askdirectory(parent=root)
        if path:
            output_dir.set(path)

    # FILE SELECTION-------------------------------------------------------------

    ctk.CTkLabel(MSA_run, text="📁 FILE INPUT", font=(
        "Arial", 16, "bold")).pack(anchor="w", pady=(5, 2))

    ctk.CTkButton(MSA_run, text="Select FASTA File for MSA",
                  command=load).pack(fill="x", pady=5)
    ctk.CTkLabel(MSA_run, textvariable=file_path).pack(
        anchor="w", pady=(0, 10))

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

    def run_worker(input_file, out_dir, grid, count, consensus):
        try:
            report_path, aligned_file = run_msa(
                input_file, out_dir, grid, count, consensus)
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

        thread = threading.Thread(
            target=run_worker,
            args=(file_path.get(), output_dir.get(),
                  grid_var.get(), count_var.get(), consensus_var.get()),
            daemon=True
        )
        thread.start()

    run_button.configure(command=run_and_show)
