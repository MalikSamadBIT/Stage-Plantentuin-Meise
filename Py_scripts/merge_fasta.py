from Bio import SeqIO

fasta_a = r"C:\Users\Malik Samad\Desktop\NCBI+BOLD\Xanthium albinum\ITS1\ITS1.fasta"
fasta_b = r"C:\Users\Malik Samad\Desktop\NCBI+BOLD\Xanthium chinense\ITS1\ITS1.fasta"


fastas = [fasta_a, fasta_b]
new_file = []
for record in fastas:
    f = SeqIO.parse(record, "fasta")
    new_file.extend(f)

SeqIO.write(new_file, r"C:\Users\Malik Samad\Desktop\newfile.fasta", "fasta")
