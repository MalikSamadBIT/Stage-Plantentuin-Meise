import pandas as pd

# importing accesion numbers-------------------------------------------------------

df = pd.read_csv("B:\Stage\\test_result.csv")
# print(df.head())

# filtering for the accesion numbers only in new df--------------------------------

headers = list(df.columns.values)
# print(headers)

markers = list(filter(lambda m: 'accession' in m, headers))
# print(markers)

markers.insert(0, 'Name')
df_accessions = df.filter(markers, axis=1)
# print(df_accessions)

# the loop for the indeviduel accession numbers----------------------------------------

print(df_accessions)
