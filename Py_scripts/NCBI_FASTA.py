import pandas as pd
from Bio import Entrez

# NCBI SETTINGS-------------------------------------------

Entrez.email = "samadmalikg@gmail.com"
Entrez.api_key = "a9543111711b0671e59f806f680529ff4607"

# importing accesion numbers-------------------------------------------------------

df = pd.read_csv("B:\Stage\\test_result.csv")
# print(df.head())

# filtering for the accesion numbers only in new df--------------------------------

headers = list(df.columns.values)
# print(headers)

markers = list(filter(lambda m: 'accession' in m, headers))
# print(markers)
name_and_markers = markers.copy()
name_and_markers.insert(0, 'Name')
df_accessions = df.filter(name_and_markers, axis=1)
# print(df_accessions)

# the loop for the indeviduel accession number to get the fasta----------------------------------------
df_fasta = pd.DataFrame()

for i, row in df_accessions.iterrows():
    for marker in markers:
        if pd.notna(row[marker]):
            handle = Entrez.efetch(
                db="nucleotide", id=row[marker], rettype='fasta')
            # print(handle.read())
