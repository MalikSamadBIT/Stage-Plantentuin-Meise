#Importeren van de plantensoorten in België en filteren

library("xlsx")

all_plants <- read.xlsx("All_plants.xlsx", sheetName = "list_FR6_accepted_names")

#head(all_plants)

# genus en species in een df 

species_name <- all_plants$Species.name
Family_to_Genus_Name <- all_plants$Family.to.Genus.Name

Full_Name_NA <- data.frame(Family_to_Genus_Name, species_name)

# NA uit df filteren

#sum(is.na(Full_Name_NA$Family_to_Genus_Name))
#sum(is.na(Full_Name_NA$species_name))

Full_Name <- na.omit(Full_Name_NA)

#sum(is.na(Full_Name$Family_to_Genus_Name))
#sum(is.na(Full_Name$species_name))

# genus en species samenvoegen

Taxa <- paste(Full_Name$Family_to_Genus_Name, Full_Name$species_name)
Taxa <- data.frame(Taxa)
header <- c("Name")
names(Taxa) <- header
#write.xlsx(Taxa, "Taxa.xlsx")

write.csv(Taxa, "Floralijst", row.names = F)
