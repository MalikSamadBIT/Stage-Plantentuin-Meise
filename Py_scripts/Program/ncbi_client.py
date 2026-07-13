from Bio import Entrez, SeqIO

from common import detect_country_group

# NCBI SETTINGS-------------------------------------------

Entrez.email = "samadmalikg@gmail.com"
Entrez.api_key = "a9543111711b0671e59f806f680529ff4607"


# NCBI SCORING (Biopython GenBank record)-----------------------------------------------

def score_record(record, w, bad_words):

    raw = 0

    title = record.description.lower()

    if any(b in title for b in bad_words):
        raw -= 100

    length = len(record.seq)

    if 300 <= length <= 1200:
        length_score = 30
    elif 200 <= length < 300 or 1200 < length <= 2000:
        length_score = 15
    else:
        length_score = 0

    source = None
    for f in record.features:
        if f.type == "source":
            source = f.qualifiers
            break

    location_score = 0

    if source:
        location = source.get(
            "geo_loc_name",
            source.get("country", [""])
        )[0].lower()

        group = detect_country_group(location)
        location_score = w.get(group, 0)

    max_location = max(w.values()) if w else 40

    location_norm = (location_score / max_location) * 40
    length_norm = length_score
    penalty_norm = max(0, 30 - abs(raw) / 5)

    final_score = location_norm + length_norm + penalty_norm

    return round(final_score, 2)


def build_ncbi_result(gb, score):
    fasta_text = gb.format("fasta").strip() + "\n"

    geo_loc = None
    lat_lon = None
    collection_date = None
    voucher = None

    for feature in gb.features:
        if feature.type == "source":
            q = feature.qualifiers
            geo_loc = q.get("geo_loc_name", q.get("country", [None]))[0]
            lat_lon = q.get("lat_lon", [None])[0]
            collection_date = q.get("collection_date", [None])[0]
            voucher = q.get("specimen_voucher", [None])[0]
            break

    meta = {
        "source": "NCBI",
        "accession": gb.id,
        "title": gb.description,
        "length": len(gb.seq),
        "organism": gb.annotations.get("organism"),
        "geo_loc": geo_loc,
        "lat_lon": lat_lon,
        "collection_date": collection_date,
        "voucher": voucher,
        "score": score,
    }

    return fasta_text, meta


# SEARCH + SCORE + FETCH FROM NCBI------------------------------------

def search_and_fetch_ncbi(species, marker, rate_limiter, w, bad_words,
                          max_candidates=10, top_n=1, log=print):

    try:
        query = f'"{species}"[Organism] AND {marker}'
        log("Query:", query)

        rate_limiter.wait()
        handle = Entrez.esearch(
            db="nucleotide", term=query, retmax=max_candidates)
        rec = Entrez.read(handle)
        handle.close()

        if not rec["IdList"]:
            return []

        scored = []

        for uid in rec["IdList"]:
            try:
                rate_limiter.wait()
                handle = Entrez.efetch(
                    db="nucleotide",
                    id=uid,
                    rettype="gb",
                    retmode="text"
                )

                gb = SeqIO.read(handle, "genbank")
                handle.close()

                sc = score_record(gb, w, bad_words)
                scored.append((sc, gb))

            except Exception as e:
                log("efetch error:", e)
                continue

        if not scored:
            return []

        scored.sort(key=lambda pair: pair[0], reverse=True)

        return [build_ncbi_result(gb, sc) for sc, gb in scored[:top_n]]

    except Exception as e:
        log(e)
        return []
