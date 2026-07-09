import subprocess
from Bio import AlignIO

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
