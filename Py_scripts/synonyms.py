from urllib.request import urlopen
from bs4 import BeautifulSoup
import re

test_list = ["Huperzia selago", "Lycopodiella inundata", "Lycopodium clavatum"]

url = "https://waarnemingen.be/search/?q="

for name in test_list:
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
        print(name_page['href'])
