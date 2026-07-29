from urllib.request import urlopen
from bs4 import BeautifulSoup
import re

test_list = ["Huperzia selago", "Lycopodiella inundata", "Lycopodium clavatum"]
all_synonyms = {}

url = "https://waarnemingen.be/search/?q="
url2 = "https://waarnemingen.be"
for name in test_list:
    species_synonyms = {}
    name_split = name.split()

    genus = name_split[0]
    species = name_split[1]
    # print(genus + "-" + species)
    name_url = url + genus + "+" + species
    # print(name_url)

    page = urlopen(name_url)
    html = page.read().decode("utf-8")
    soup = BeautifulSoup(html, "html.parser")

    name_page = soup.find('a', {'href': re.compile(r'^/species/\d+/$')})
    # print(name_page)
    if name_page:
        # print(name_page['href'])
        species_url = url2 + name_page['href'] + "names/"
        # print(species_url)

        page2 = urlopen(species_url)
        html2 = page2.read().decode("utf-8")
        soup2 = BeautifulSoup(html2, "html.parser")

        synonyms_list = []

        synonyms = soup2.find_all(
            'div', class_=re.compile(r'col-sm-2 col-xs-5'))
        for synonym in synonyms:
            strong = synonym.find('strong')
            if strong:
                # print(strong.get_text(strip=True))
                synonyms_list.append(strong.get_text(strip=True))

        synonyms_languages_list = []

        synonyms_languages = soup2.find_all(
            'div', class_=re.compile(r'col-sm-3 col-xs-7'))
        for language in synonyms_languages:
            synonyms_languages_list.append(language.get_text(strip=True))
            # print(language.get_text(strip=True))

        language_counter = 0
        for l in synonyms_languages_list:
            species_synonyms[l] = synonyms_list[language_counter]
            language_counter += 1

    all_synonyms[name] = species_synonyms

print(all_synonyms)
