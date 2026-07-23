import os
import subprocess
import customtkinter as ctk
from tkinter import filedialog

BLAST_BIN = r"B:\Stage\tools\blast\bin"

db_fasta = r"B:\Stage\DB_test\DB_FASTA_Test.fasta"
query_fasta = "query.fasta"

'''
with open(query_fasta, "w") as f:
    f.write(

        "AAATGAGATATTTTATATAAATTTCTTACGAAACAGAGAATCCGTCTTAATGGACTTGACTATTCTTAGGAATAGACATCTCTTCATAGTAAAACATTATCATTGTATATTGTTTTTGATATGTGATGCAACCCAGTTGCTTTAATATCAGTAGAATTTTCATTTATGTTTCCCCCTAGGTTTTCTATATTGATATGAAACCTATTAAGTATCGAACTGATTGGTTAATGAAAAATGATTTTTACTGAACTAGTATTACATATTTCGATACGGGGGAAAGAAAAAAAAAACCCTAATTAATGTGATTTCAAATAAATAAATAAATAAATAAATAAATAAATAAATATATATATATTTATTTATTTATTTATTTATTTATTTTAATTTTGTGAGGAAAAGAAAAAAATTATTATCTTTTTCTTTTTCTAGTGGAAAGGAATCTTCCCACAATCCCGTATTGAGAATATGAGCCAAATATTAGGAATATGAGCTAAAATATAAATAAACTCAATATGAATAAGTAAATCAAGGTGGTAACTTTTATTCATAATCAACCGATCAACTCGGTATCAAAGATTGTTATCGATACAACCAAACAAATTTAATACTATTAGAATTTTATGGAAATAAATCCTTTTGCTCTTGGAGTTTCTACACTTGTCGACAGAAATGTAGGATATATCACTCAGA\n"
    )

# build a nucleotide BLAST database from the FASTA file
subprocess.run(
    [os.path.join(BLAST_BIN, "makeblastdb.exe"),
     "-in", db_fasta, "-dbtype", "nucl", "-out", "mydb"],
    check=True
)

# blastn query

result = subprocess.run(
    [os.path.join(BLAST_BIN, "blastn.exe"),
     "-query", query_fasta, "-db", "mydb", "-outfmt", "6"],
    capture_output=True, text=True, check=True
)

print(result.stdout)

'''

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

tk = ctk.CTk()
tk.geometry("1250x820")
tk.title("BLAST+ test")


tk.mainloop()
