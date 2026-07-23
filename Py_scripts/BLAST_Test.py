import os
import subprocess

BLAST_BIN = r"B:\Stage\tools\blast\bin"

db_fasta = "db.fasta"
query_fasta = "query.fasta"


with open(db_fasta, "w") as f:
    f.write(
        ">seq1 Equisetum litorale\n"
        "TGACCTCGGATCAACCAGGTTGATCTGGTAAGTGCAGATCGTCGGCTATAGCTTAGGCTA\n"
        ">seq2 Rosa canina\n"
        "CATTGGCAAGTGATCCGGATTAGCCTAGGATCGTATCGGCTTAAGGGCTAAGCTAGGCTA\n"
    )

with open(query_fasta, "w") as f:
    f.write(
        ">query1\n"
        "TGACCTCGGATCAACCAGGTTGATCTGGTAAGTGCAGATCGTCGGCTATAGCTTAGGCTA\n"
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
