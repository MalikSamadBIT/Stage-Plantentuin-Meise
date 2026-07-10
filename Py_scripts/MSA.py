import subprocess
from Bio import AlignIO
from pymsaviz import MsaViz
import tkinter
import customtkinter
from tkinter import filedialog
from PIL import Image


Fasta_file = r"B:\Stage\NCBI_5results\Huperzia selago\matK\matK.fasta"
Aligned_file = r"B:\Stage\NCBI_5results\Huperzia selago\matK\matK_aligned.fasta"

subprocess.run([r"B:\Stage\tools\muscle.exe", "-align", Fasta_file,
               "-output", Aligned_file], check=True)
alignment = AlignIO.read(Aligned_file, "fasta")

num_seq = len(alignment)
print(num_seq)
alignment_length = alignment.get_alignment_length()
print(alignment_length)

for record in alignment:
    print(record)
    print("-"*60)

mv = MsaViz(Aligned_file, color_scheme="Clustal",
            show_grid=True, show_count=True, show_consensus=True)
mv.savefig(r"B:\Stage\NCBI_5results\Huperzia selago\matK\msa_report.png")


# Image----------------------------------------------------------------------------------

MSA_img = r"B:\Stage\NCBI_5results\Huperzia selago\matK\msa_report.png"

img = Image.open(MSA_img)
x, y = img.size
# print(x, y)

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

frame = customtkinter.CTkScrollableFrame(
    MSA_results,
    width=700, height=y+20,
    orientation="horizontal"
)

frame.place(anchor="c", relx=.5, rely=.5)

MSA_image = customtkinter.CTkImage(
    light_image=Image.open(MSA_img), dark_image=Image.open(MSA_img), size=(x, y))

label = customtkinter.CTkLabel(frame, text="", image=MSA_image)
label.pack(pady=10)


tk.mainloop()
