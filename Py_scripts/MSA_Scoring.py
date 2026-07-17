from pymsa import MSA, Entropy, PercentageOfNonGaps, PercentageOfTotallyConservedColumns, Star, SumOfPairs
from pymsa import PAM250, Blosum62, FileMatrix
from pymsa.util.fasta import print_alignment, read_fasta_file_as_list_of_pairs


def run_all_scores(sequences: list) -> None:
    aligned_sequences = list(pair[1] for pair in sequences)
    sequences_id = list(pair[0] for pair in sequences)

    msa = MSA(aligned_sequences, sequences_id)
    print_alignment(msa)

    # Percentage of non-gaps and totally conserved columns
    non_gaps = PercentageOfNonGaps(msa)
    totally_conserved_columns = PercentageOfTotallyConservedColumns(msa)

    percentage = non_gaps.compute()
    print("Percentage of non-gaps: {0} %".format(percentage))

    conserved = totally_conserved_columns.compute()
    print("Percentage of totally conserved columns: {0}".format(conserved))

    # Entropy
    value = Entropy(msa).compute()
    print("Entropy score: {0}".format(value))

    # Sum of pairs
    value = SumOfPairs(msa, Blosum62()).compute()
    print("Sum of Pairs score (Blosum62): {0}".format(value))

    value = SumOfPairs(msa, PAM250()).compute()
    print("Sum of Pairs score (PAM250): {0}".format(value))

    # value = SumOfPairs(msa, FileMatrix('PAM380.txt')).compute()
    # print("Sum of Pairs score (PAM380): {0}".format(value))

    # Star
    value = Star(msa, Blosum62()).compute()
    print("Star score (Blosum62): {0}".format(value))

    value = Star(msa, PAM250()).compute()
    print("Star score (PAM250): {0}".format(value))


fasta_path = r"C:\Users\Malik Samad\Desktop\NCBI+BOLD\psbA-trnH.fasta_aligned.fasta"
aligned_sequences = read_fasta_file_as_list_of_pairs(fasta_path)
run_all_scores(aligned_sequences)
