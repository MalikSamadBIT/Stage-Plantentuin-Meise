from Bio import Entrez
import pandas as pd
import time
from Bio import Entrez, SeqIO

# importeren van df van floralijst
df = pd.read_csv("B:\Stage\Floralijst")
# print(df.head())

Entrez.email = "samadmalikg@gmail.com"
Entrez.api_key = "a9543111711b0671e59f806f680529ff4607"


def get_accession(species, marker):
    try:
        query = f'"{species}"[Organism] AND {marker}'

        # Search NCBI
        handle = Entrez.esearch(
            db="nucleotide",
            term=query,
            retmax=1
        )
        search_record = Entrez.read(handle)
        handle.close()

        if not search_record["IdList"]:
            return (None, None, None, None, None, None, None, None)

        uid = search_record["IdList"][0]

        # Fetch the GenBank record
        handle = Entrez.efetch(
            db="nucleotide",
            id=uid,
            rettype="gb",
            retmode="text"
        )

        gb_record = SeqIO.read(handle, "genbank")
        handle.close()

        accession = gb_record.id
        title = gb_record.description
        length = len(gb_record.seq)
        organism = gb_record.annotations.get("organism")

        # Default values
        geo_loc = None
        lat_lon = None
        collection_date = None
        voucher = None

        # Read metadata from the SOURCE feature
        for feature in gb_record.features:

            if feature.type != "source":
                continue

            qualifiers = feature.qualifiers

            # Geographic location
            if "geo_loc_name" in qualifiers:
                geo_loc = qualifiers["geo_loc_name"][0]
            elif "country" in qualifiers:
                geo_loc = qualifiers["country"][0]

            # Latitude / Longitude
            if "lat_lon" in qualifiers:
                lat_lon = qualifiers["lat_lon"][0]

            # Collection date
            if "collection_date" in qualifiers:
                collection_date = qualifiers["collection_date"][0]

            # Voucher specimen
            if "specimen_voucher" in qualifiers:
                voucher = qualifiers["specimen_voucher"][0]

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
        )

    except Exception as e:
        print(f"{species} ({marker}): {e}")

        return (None, None, None, None, None, None, None, None)


markers = [
    "rbcL",
    "matK",
    "trnL",
    "psbA-trnH"
]

test_df = df.head(3)

for marker in markers:

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
    ]

    test_df = pd.concat([test_df, results], axis=1)

print(test_df)
test_df.to_csv("testacce.csv")
