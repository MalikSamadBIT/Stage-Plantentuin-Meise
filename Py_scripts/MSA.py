import os
import subprocess
from pymsaviz import MsaViz
import tkinter
import customtkinter
from tkinter import filedialog
from PIL import Image


def run_MSA(input_file, output_dir):

    aligned_file = os.path.join(
        output_dir, os.path.basename(input_file) + "_aligned.fasta")
    subprocess.run([r"B:\Stage\tools\muscle.exe", "-align", input_file,
                    "-output", aligned_file], check=True)

    mv = MsaViz(aligned_file, color_scheme="Clustal",
                show_grid=True, show_count=True, show_consensus=True)
    report_path = os.path.join(output_dir, "msa_report.png")
    mv.savefig(report_path)

    return report_path


# GUI-------------------------------------------------------------------------------
customtkinter.set_appearance_mode("dark")
customtkinter.set_default_color_theme("dark-blue")

tk = customtkinter.CTk()

tk.title("MSA_viz")
tk.geometry("800x400")

# TABS-------------------------------------------------------------
tabs = customtkinter.CTkTabview(tk)
tabs.pack(fill="both", expand=True, padx=10, pady=10)

MSA_run = tabs.add("Run MSA")
MSA_results = tabs.add("MSA Results")

# FILE SELECTION-------------------------------------------------------------

customtkinter.CTkLabel(MSA_run, text="📁 FILE INPUT", font=(
    "Arial", 16, "bold")).pack(anchor="w", pady=(5, 2))

file_path = customtkinter.StringVar()
output_dir = customtkinter.StringVar()


def load():
    path = filedialog.askopenfilename(filetypes=[("FASTA", "*.fasta")])
    file_path.set(path)


def choose_output():
    path = filedialog.askdirectory()
    output_dir.set(path)


customtkinter.CTkButton(MSA_run, text="Select FASTA File for MSA",
                        command=load).pack(fill="x", pady=5)
customtkinter.CTkLabel(MSA_run, textvariable=file_path).pack(
    anchor="w", pady=(0, 10))

customtkinter.CTkButton(MSA_run, text="Select Output Folder",
                        command=choose_output).pack(fill="x", pady=5)
customtkinter.CTkLabel(MSA_run, textvariable=output_dir).pack(
    anchor="w", pady=(0, 10))

status_label = customtkinter.CTkLabel(MSA_run, text="")
status_label.pack(anchor="w", pady=(10, 0))


def show_results(image_path):
    img = Image.open(image_path)
    x, y = img.size

    for widget in MSA_results.winfo_children():
        widget.destroy()

    frame = customtkinter.CTkScrollableFrame(
        MSA_results,
        width=700, height=y + 20,
        orientation="horizontal"
    )
    frame.place(anchor="c", relx=.5, rely=.5)

    MSA_image = customtkinter.CTkImage(
        light_image=img, dark_image=img, size=(x, y))

    customtkinter.CTkLabel(frame, text="", image=MSA_image).pack(pady=10)


def run_and_show():
    if not file_path.get() or not output_dir.get():
        status_label.configure(
            text="Select a FASTA file and an output folder first.")
        return

    status_label.configure(text="Running MSA...")
    tk.update_idletasks()
    try:
        report_path = run_MSA(file_path.get(), output_dir.get())
    except subprocess.CalledProcessError as e:
        status_label.configure(text=f"MSA failed: {e}")
        return

    status_label.configure(text="Done.")
    show_results(report_path)
    tabs.set("MSA Results")


customtkinter.CTkButton(MSA_run, text="Run MSA",
                        command=run_and_show).pack(fill="x", pady=5)

customtkinter.CTkLabel(MSA_results, text="No results yet — run an MSA first.").place(
    anchor="c", relx=.5, rely=.5)


tk.mainloop()
