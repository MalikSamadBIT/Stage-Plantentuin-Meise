from Bio import Entrez
import pandas as pd
import time

# importeren van df van floralijst
df = pd.read_csv("B:\Stage\Floralijst")
# print(df.head())

Entrez.email = "samadmalikg@gmail.com"
Entrez.api_key = "a9543111711b0671e59f806f680529ff4607"


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

        return accession, title

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

test_df = df.head(5)

for marker in markers:
    test_df[[f"{marker}_accession", f"{marker}_title"]] = (
        test_df["Name"]
        .apply(lambda species: get_accession(species, marker))
        .apply(pd.Series)
    )


# test_df.to_excel("testacce.xlsx")
print(test_df)
