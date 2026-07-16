import os
import subprocess
import threading
import tkinter
from tkinter import filedialog

import customtkinter as ctk
from PIL import Image
from pymsaviz import MsaViz

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

    return report_path


def build_msa_tab(parent, root=None):
    """
    parent: the CTkTabview tab frame to build the widgets into.
    root: the main app window, used as the file-dialog parent.
    """

    sub_tabs = ctk.CTkTabview(parent)
    sub_tabs.pack(fill="both", expand=True)

    MSA_run = sub_tabs.add("Run MSA")
    MSA_results = sub_tabs.add("MSA Results")

    file_path = ctk.StringVar()
    output_dir = ctk.StringVar()

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

    # RUN (background thread, so a slow MUSCLE alignment doesn't freeze
    # the rest of the app while it runs)------------------------------------

    def run_worker(input_file, out_dir, grid, count, consensus):
        try:
            report_path = run_msa(input_file, out_dir, grid, count, consensus)
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
