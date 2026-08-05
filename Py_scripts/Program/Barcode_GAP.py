from Bio.Align import PairwiseAligner


def _default_aligner():
    aligner = PairwiseAligner()
    aligner.mode = "global"
    aligner.match_score = 1
    aligner.mismatch_score = 0
    aligner.gap_score = -1
    return aligner


def p_distance(seq1, seq2, aligner=None):
    """
    Returns (distance, n_sites): distance is the fraction of aligned,
    non-gap columns that differ; n_sites is how many such columns there
    were. Returns (None, 0) if there were no comparable columns.
    """
    seq1 = "".join(seq1.split())
    seq2 = "".join(seq2.split())

    aligner = aligner or _default_aligner()
    alignment = aligner.align(seq1, seq2)[0]
    a1, a2 = str(alignment[0]), str(alignment[1])

    n_sites = 0
    n_diff = 0
    for c1, c2 in zip(a1, a2):
        if c1 == "-" or c2 == "-":
            continue
        n_sites += 1
        if c1 != c2:
            n_diff += 1

    if n_sites == 0:
        return None, 0
    return n_diff / n_sites, n_sites


seq1 = """TCGAAACCTGCCTAGCAGAACGACCCGCGAACCCGTTTCATCATCGGGGGGGAGCACGGG
TGCGAGAGCCTCGTGGTCCTCCTCCGCAGTCGGATCGACGGCGCTTGCGCCCTCTCTCCG
TCGGCACAATAACGAACCCCGGCGCGGACCGCGCCAAGGAAACTTAACAAGAGAGCGTGC
CCTTGCCTCCCCGGAAACGGTGTGTGCGCTTGTAGCATCGCCTTCTCTCACTATTTAAAA
CGACTCTCGGCAACGGATATCTCGGCTCTCGCATCGATGAAGAACGTAGCGAAATGCGAT
ACTTGGTGTGAATTGCAGAATCCCGTGAACCATCGAGTCTTTGAACGCAAGTTGCGCCCC
AAGCCGTTAGGCCGAGGGCACGCCTGCCTGGGTGTCACGCATCGTTGCCCCTCCCCCAAA
CCCCTCTCGACGAGGGGACTTGGCCGTGGGCGGATATTGGCCTCCCGTGCGCCGAAGGGC
TCGCGGTTGGCCTAAATACGAGTCGTCGACGGTGGACGTCGTGACGTTCGGTGGTCAAAC
AAACCTCGAGCTCCCGTCGCGCGTACGTCGTCGGTACAAACAAGGCTCACCGACCCTGAA
GCGTTGTCAACAACAGCGCACGCATCGCG"""

seq2 = """AACCTGCGGAAGGATCATTGTCGAAACCTGCCTAGCAGAACGACCCGCGAACCCGTTTCA
TCATCGGGGGGGAGCACGGGTGCGAGAGCCTCGTGGTCCCCCTCTGCAGTCGGATCGACG
GCGCCTGCGCCCTCGCTCCGTCGGCACAATAACGAACCCCGGCGCGGACCGCGCCAAGGA
AACTTAACAACAGAGCGTGCCCTTGCCTCCCCGGAAACGGTGTGTGCGCTTGTGGCATCG
CCTTCTCTCACTATTTAAAACGACTCTCGGCAACGGATATCTCGGCTCTCGCATCGATGA
AGAACGTAGCGAAATGCGATACTTGGTGTGAATTGCAGAATCCCGTGAACCATCGAGTCT
TTGAACGCAAGTTGCGCCCCAAGCCGTTAGGCCGAGGGCACGCCTGCCTGGGTGTCACGC
ATCGTTGCCCCTTCCCCGAACCCCCTCCCTTCCTTGAAAGAGGGAGACGAGGGGACTTCG
CCGTGGGCGGATATTGGCCTCCCGTGCGCCGAAGGGCTCGCGGTTGGCCTAAATACGAGT
CGTCGACGGTGGACGTCGTGACGTTCGGTGGTCAAACAAACCTCCAGCTCCCGTCGCGCG
TACGTCGTCGGTACAACAAGGCTCACCGACCCTGAAGCGTTGTCAACAGCGCACGCATC"""

if __name__ == "__main__":
    distance, n_sites = p_distance(seq1, seq2)
    print(f"seq1 vs seq2: distance={distance:.4f}, n_sites={n_sites}")

    identical_dist, identical_sites = p_distance(seq1, seq1)
    print(f"seq1 vs itself: distance={identical_dist}, n_sites={identical_sites}")

    one_diff_dist, one_diff_sites = p_distance("ACGTACGTAC", "ACGTACGTAG")
    print(f"1 diff / 10 sites: distance={one_diff_dist}, n_sites={one_diff_sites}")

    # one base deleted from the middle -> aligner should introduce a gap;
    # the gap column should be excluded, leaving distance 0 over 9 sites
    gap_dist, gap_sites = p_distance("ACGTACGTAC", "ACGTCGTAC")
    print(f"one deletion: distance={gap_dist}, n_sites={gap_sites}")
