import subprocess
from Bio import AlignIO
from pymsaviz import MsaViz
import tkinter
import customtkinter
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

mv = MsaViz(Aligned_file, color_scheme="Clustal")
mv.savefig(r"B:\Stage\NCBI_5results\Huperzia selago\matK\msa_report.png")

MSA_img = r"B:\Stage\NCBI_5results\Huperzia selago\matK\msa_report.png"


# GUI-------------------------------------------------------------------------------

customtkinter.set_appearance_mode("dark")
customtkinter.set_default_color_theme("dark-blue")

tk = customtkinter.CTk()

tk.title("MSA_viz")
tk.geometry("400x200")

MSA_image = customtkinter.CTkImage(
    light_image=Image.open(MSA_img), dark_image=Image.open(MSA_img), size=(360, 500))

label = customtkinter.CTkLabel(tk, text="", image=MSA_image)
label.pack(pady=10)


tk.mainloop()
