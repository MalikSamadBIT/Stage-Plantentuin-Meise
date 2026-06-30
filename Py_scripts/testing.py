from Bio import Entrez
import pandas as pd
import time

# importeren van df van floralijst
df = pd.read_csv("B:\Stage\Floralijst")
# print(df.head())

Entrez.email = "samadmalikg@gmail.com"


def get_accession(species, marker):
    try:
        query = f'"{species}"[Organism] AND {marker}'

        handle = Entrez.esearch(
            db="nucleotide",
            term=query,
            retmax=5
        )
        record = Entrez.read(handle)
        handle.close()

        if not record["IdList"]:
            return None

        handle = Entrez.esummary(
            db="nucleotide",
            id=",".join(record["IdList"])
        )
        summaries = Entrez.read(handle)
        handle.close()

        # Return the first accession
        accession = summaries[0]["AccessionVersion"]

        time.sleep(0.35)

        return accession

    except Exception as e:
        print(f"{species} ({marker}): {e}")
        return None


markers = [
    "ITS",
    "rbcL",
    "matK",
    "trnL",
    "psbA-trnH"
]

test_df = df.head(3)

for marker in markers:
    test_df[marker] = test_df["Name"].apply(
        lambda species: get_accession(species, marker))

print(test_df)
