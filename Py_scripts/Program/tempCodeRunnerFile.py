tabs = ctk.CTkTabview(app)
tabs.pack(fill="both", expand=True, padx=10, pady=10)

Fetch_Fasta = tabs.add("Fetch FASTA")
Settings = tabs.add("Settings")
Retrieval_Rate = tabs.add("Retrieval Rate")
MSA = tabs.add("MSA")
Database_tab = tabs.add("Database")