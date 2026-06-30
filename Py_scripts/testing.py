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

        handle = Entrez.esearch(db="nucleotide", term=query, retmax=5)
        record = Entrez.read(handle)
        handle.close()

        if not record["IdList"]:
            return None, None

        handle = Entrez.esummary(
            db="nucleotide", id=",".join(record["IdList"]))
        summaries = Entrez.read(handle)
        handle.close()

        accession = summaries[0]["AccessionVersion"]
        title = summaries[0]["Title"]

        time.sleep(0.35)

        return summaries

    except Exception as e:
        print(f"{species} ({marker}): {e}")
        return None, None


markers = [
    "ITS",
    "rbcL",
    "matK",
    "trnL",
    "psbA-trnH"
]

test_df = df.head(1)

for marker in markers:
    test = (
        test_df["Name"]
        .apply(lambda species: get_accession(species, marker))
    )

test.to_clipboard("testt.txt")
