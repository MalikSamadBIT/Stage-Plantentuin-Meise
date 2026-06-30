from Bio import Entrez
import pandas as pd
import time
from Bio import Entrez, SeqIO

# importeren van df van floralijst
df = pd.read_csv("B:\Stage\Floralijst")
# print(df.head())

Entrez.email = "samadmalikg@gmail.com"
Entrez.api_key = "a9543111711b0671e59f806f680529ff4607"

# scoring ------------------------------------------------------------------------------------------


def score_record(record):

    score = 0

    title = record.description.lower()

    # Reject obvious genome assemblies
    bad_words = [
        "whole genome",
        "chromosome",
        "scaffold",
        "contig",
        "assembly"
    ]

    if any(word in title for word in bad_words):
        score -= 100

    # Sequence length
    length = len(record.seq)

    if 300 <= length <= 1200:
        score += 10

    # SOURCE metadata
    source = None

    for feature in record.features:
        if feature.type == "source":
            source = feature.qualifiers
            break

    if source:
        # Geographic location
        location = source.get(
            "geo_loc_name",
            source.get("country", [""])
        )[0].lower()

        location_scores = {
            "belgium": 40,
            "belgië": 40,
            "belgique": 40,

            "netherlands": 20,
            "nederland": 20,

            "germany": 20,
            "deutschland": 20,

            "france": 20,
            "frankrijk": 20,

            "luxembourg": 20,
            "luxemburg": 20,
        }

        matched = False

        for keyword, points in location_scores.items():
            if keyword in location:
                score += points
                matched = True
                break

        if not matched and location != "":
            score += 5

    return score

# search -------------------------------------------------------------------------------------------


def get_accession(species, marker):

    try:

        query = f'"{species}"[Organism] AND {marker}'

        handle = Entrez.esearch(
            db="nucleotide",
            term=query,
            retmax=10
        )

        search_record = Entrez.read(handle)
        handle.close()

        if not search_record["IdList"]:
            return (None, None, None, None, None, None, None, None, 0)

        best_record = None
        best_score = -999

        for uid in search_record["IdList"]:

            try:

                handle = Entrez.efetch(
                    db="nucleotide",
                    id=uid,
                    rettype="gb",
                    retmode="text"
                )

                gb_record = SeqIO.read(handle, "genbank")
                handle.close()

                score = score_record(gb_record)

                if score > best_score:
                    best_score = score
                    best_record = gb_record

            except Exception:
                continue

        if best_record is None:
            return (None, None, None, None, None, None, None, None, 0)

        accession = best_record.id
        title = best_record.description
        length = len(best_record.seq)
        organism = best_record.annotations.get("organism")

        geo_loc = None
        lat_lon = None
        collection_date = None
        voucher = None

        for feature in best_record.features:

            if feature.type != "source":
                continue

            qualifiers = feature.qualifiers

            geo_loc = qualifiers.get(
                "geo_loc_name",
                qualifiers.get("country", [None])
            )[0]

            lat_lon = qualifiers.get("lat_lon", [None])[0]

            collection_date = qualifiers.get(
                "collection_date",
                [None]
            )[0]

            voucher = qualifiers.get(
                "specimen_voucher",
                [None]
            )[0]

        time.sleep(0.35)

        return (
            accession,
            title,
            length,
            organism,
            geo_loc,
            lat_lon,
            collection_date,
            voucher,
            best_score
        )

    except Exception as e:

        print(f"{species} ({marker}): {e}")

        return (None, None, None, None, None, None, None, None, 0)


markers = [
    "ITS1",
    "ITS2",
    "rbcL",
    "matK",
    "trnL",
    "psbA-trnH"
]

test_df = df.head(3)

for marker in markers:

    print(f"Searching {marker}...")

    results = (
        test_df["Name"]
        .apply(lambda species: get_accession(species, marker))
        .apply(pd.Series)
    )

    results.columns = [
        f"{marker}_accession",
        f"{marker}_title",
        f"{marker}_length",
        f"{marker}_organism",
        f"{marker}_geo_loc",
        f"{marker}_lat_lon",
        f"{marker}_collection_date",
        f"{marker}_voucher",
        f"{marker}_score"
    ]

    test_df = pd.concat([test_df, results], axis=1)

print(test_df)
test_df.to_csv("testacce.csv")
