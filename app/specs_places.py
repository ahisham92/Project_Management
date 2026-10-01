"""Where a project is: its city and country put on the start page's map.

The site cannot look places up on the internet (PythonAnywhere only reaches a
list of allowed hosts), so the cities and countries the office works in are
kept here with their latitude and longitude. A city not on the list is put at
its country's centre; the map's page asks the browser to find it instead, so
nothing has to be typed twice.
"""

from __future__ import annotations

import re

# Country -> (latitude, longitude) of somewhere near its middle.
COUNTRIES: dict[str, tuple[float, float]] = {
    "saudi arabia": (23.9, 45.1), "united arab emirates": (23.9, 54.3), "qatar": (25.3, 51.2),
    "bahrain": (26.07, 50.55), "kuwait": (29.3, 47.7), "oman": (21.0, 57.0), "yemen": (15.6, 48.0),
    "iraq": (33.0, 43.7), "iran": (32.4, 53.7), "jordan": (31.2, 36.5), "lebanon": (33.9, 35.9),
    "syria": (35.0, 38.5), "palestine": (31.9, 35.2), "israel": (31.4, 35.0), "turkey": (39.0, 35.2),
    "egypt": (26.8, 30.8), "libya": (27.0, 17.2), "tunisia": (34.0, 9.5), "algeria": (28.0, 2.6),
    "morocco": (31.8, -7.1), "sudan": (15.6, 30.2), "south sudan": (7.0, 30.0),
    "ethiopia": (9.1, 40.5), "eritrea": (15.2, 39.8), "djibouti": (11.8, 42.6), "somalia": (5.2, 46.2),
    "kenya": (0.0, 37.9), "uganda": (1.4, 32.3), "tanzania": (-6.4, 34.9), "rwanda": (-1.9, 29.9),
    "nigeria": (9.1, 8.7), "ghana": (7.9, -1.0), "ivory coast": (7.5, -5.5), "cote d'ivoire": (7.5, -5.5),
    "senegal": (14.5, -14.5), "guinea": (9.9, -9.7), "sierra leone": (8.5, -11.8), "liberia": (6.4, -9.4),
    "togo": (8.6, 0.8), "benin": (9.3, 2.3), "cameroon": (7.4, 12.4), "gabon": (-0.8, 11.6),
    "congo": (-0.2, 15.8), "democratic republic of the congo": (-4.0, 21.8), "angola": (-11.2, 17.9),
    "namibia": (-22.9, 18.5), "south africa": (-30.6, 22.9), "mozambique": (-18.7, 35.5),
    "zambia": (-13.1, 27.8), "zimbabwe": (-19.0, 29.2), "botswana": (-22.3, 24.7),
    "madagascar": (-18.8, 46.9), "mauritius": (-20.3, 57.6), "mauritania": (21.0, -10.9),
    "mali": (17.6, -4.0), "niger": (17.6, 8.1), "chad": (15.5, 18.7),
    "united kingdom": (54.0, -2.5), "ireland": (53.4, -8.2), "france": (46.6, 2.2), "spain": (40.4, -3.7),
    "portugal": (39.4, -8.2), "italy": (42.8, 12.6), "germany": (51.2, 10.4), "netherlands": (52.1, 5.3),
    "belgium": (50.5, 4.5), "switzerland": (46.8, 8.2), "austria": (47.5, 14.6), "poland": (51.9, 19.1),
    "greece": (39.1, 21.8), "cyprus": (35.1, 33.4), "malta": (35.9, 14.4), "norway": (60.5, 8.5),
    "sweden": (60.1, 18.6), "denmark": (56.3, 9.5), "finland": (61.9, 25.7), "romania": (45.9, 25.0),
    "russia": (61.5, 105.3), "ukraine": (48.4, 31.2), "azerbaijan": (40.1, 47.6), "georgia": (42.3, 43.4),
    "kazakhstan": (48.0, 66.9), "uzbekistan": (41.4, 64.6), "pakistan": (30.4, 69.3), "india": (20.6, 78.9),
    "bangladesh": (23.7, 90.4), "sri lanka": (7.9, 80.8), "maldives": (3.2, 73.2), "china": (35.9, 104.2),
    "hong kong": (22.3, 114.2), "japan": (36.2, 138.3), "south korea": (35.9, 127.8),
    "singapore": (1.35, 103.8), "malaysia": (4.2, 101.9), "indonesia": (-0.8, 113.9),
    "thailand": (15.9, 100.99), "vietnam": (14.1, 108.3), "philippines": (12.9, 121.8),
    "australia": (-25.3, 133.8), "new zealand": (-40.9, 174.9), "united states": (37.1, -95.7),
    "canada": (56.1, -106.3), "mexico": (23.6, -102.6), "brazil": (-14.2, -51.9),
    "argentina": (-38.4, -63.6), "chile": (-35.7, -71.5), "peru": (-9.2, -75.0), "colombia": (4.6, -74.3),
    "panama": (8.5, -80.8),
}

ALIASES = {
    "ksa": "saudi arabia", "kingdom of saudi arabia": "saudi arabia", "saudi": "saudi arabia",
    "uae": "united arab emirates", "emirates": "united arab emirates", "u.a.e.": "united arab emirates",
    "uk": "united kingdom", "u.k.": "united kingdom", "england": "united kingdom", "scotland": "united kingdom",
    "wales": "united kingdom", "great britain": "united kingdom", "britain": "united kingdom",
    "usa": "united states", "us": "united states", "u.s.a.": "united states",
    "united states of america": "united states", "america": "united states",
    "drc": "democratic republic of the congo", "dr congo": "democratic republic of the congo",
    "korea": "south korea", "turkiye": "turkey", "türkiye": "turkey", "holland": "netherlands",
}

# City -> (latitude, longitude, country). Cities with the same name in two
# countries are told apart by the country given with them.
CITIES: list[tuple[str, float, float, str]] = [
    ("riyadh", 24.71, 46.68, "saudi arabia"), ("jeddah", 21.49, 39.19, "saudi arabia"),
    ("mecca", 21.39, 39.86, "saudi arabia"), ("makkah", 21.39, 39.86, "saudi arabia"),
    ("medina", 24.47, 39.61, "saudi arabia"), ("madinah", 24.47, 39.61, "saudi arabia"),
    ("dammam", 26.43, 50.10, "saudi arabia"), ("khobar", 26.22, 50.20, "saudi arabia"),
    ("al khobar", 26.22, 50.20, "saudi arabia"), ("dhahran", 26.29, 50.11, "saudi arabia"),
    ("jubail", 27.01, 49.66, "saudi arabia"), ("yanbu", 24.09, 38.06, "saudi arabia"),
    ("neom", 28.00, 35.20, "saudi arabia"), ("tabuk", 28.38, 36.57, "saudi arabia"),
    ("abha", 18.22, 42.51, "saudi arabia"), ("jazan", 16.89, 42.55, "saudi arabia"),
    ("jizan", 16.89, 42.55, "saudi arabia"), ("taif", 21.27, 40.42, "saudi arabia"),
    ("buraydah", 26.33, 43.97, "saudi arabia"), ("hail", 27.52, 41.69, "saudi arabia"),
    ("al ula", 26.62, 37.92, "saudi arabia"), ("alula", 26.62, 37.92, "saudi arabia"),
    ("ras al khair", 27.55, 49.20, "saudi arabia"), ("king abdullah economic city", 22.45, 39.13, "saudi arabia"),
    ("dubai", 25.20, 55.27, "united arab emirates"), ("abu dhabi", 24.45, 54.38, "united arab emirates"),
    ("sharjah", 25.35, 55.42, "united arab emirates"), ("ajman", 25.41, 55.51, "united arab emirates"),
    ("ras al khaimah", 25.79, 55.94, "united arab emirates"), ("fujairah", 25.13, 56.33, "united arab emirates"),
    ("al ain", 24.21, 55.74, "united arab emirates"),
    ("doha", 25.29, 51.53, "qatar"), ("lusail", 25.42, 51.49, "qatar"), ("ras laffan", 25.91, 51.55, "qatar"),
    ("manama", 26.23, 50.59, "bahrain"), ("kuwait city", 29.38, 47.99, "kuwait"),
    ("muscat", 23.59, 58.41, "oman"), ("sohar", 24.36, 56.75, "oman"), ("duqm", 19.66, 57.70, "oman"),
    ("salalah", 17.02, 54.09, "oman"), ("baghdad", 33.32, 44.37, "iraq"), ("basra", 30.51, 47.81, "iraq"),
    ("erbil", 36.19, 44.01, "iraq"), ("amman", 31.95, 35.93, "jordan"), ("aqaba", 29.53, 35.01, "jordan"),
    ("beirut", 33.89, 35.50, "lebanon"), ("damascus", 33.51, 36.28, "syria"),
    ("istanbul", 41.01, 28.98, "turkey"), ("ankara", 39.93, 32.86, "turkey"),
    ("cairo", 30.04, 31.24, "egypt"), ("new cairo", 30.03, 31.47, "egypt"),
    ("new administrative capital", 30.02, 31.76, "egypt"), ("alexandria", 31.20, 29.92, "egypt"),
    ("giza", 30.01, 31.21, "egypt"), ("port said", 31.26, 32.30, "egypt"), ("suez", 29.97, 32.53, "egypt"),
    ("sokhna", 29.60, 32.35, "egypt"), ("ain sokhna", 29.60, 32.35, "egypt"),
    ("el alamein", 30.83, 28.95, "egypt"), ("new alamein", 30.83, 28.95, "egypt"),
    ("hurghada", 27.26, 33.81, "egypt"), ("sharm el sheikh", 27.92, 34.33, "egypt"),
    ("damietta", 31.42, 31.81, "egypt"), ("ismailia", 30.60, 32.27, "egypt"), ("luxor", 25.69, 32.64, "egypt"),
    ("aswan", 24.09, 32.90, "egypt"), ("tripoli", 32.89, 13.19, "libya"), ("benghazi", 32.12, 20.07, "libya"),
    ("tunis", 36.81, 10.18, "tunisia"), ("algiers", 36.75, 3.06, "algeria"),
    ("casablanca", 33.57, -7.59, "morocco"), ("rabat", 34.02, -6.83, "morocco"),
    ("tangier", 35.76, -5.83, "morocco"), ("khartoum", 15.50, 32.56, "sudan"),
    ("port sudan", 19.62, 37.22, "sudan"), ("addis ababa", 9.03, 38.74, "ethiopia"),
    ("djibouti", 11.59, 43.15, "djibouti"), ("mogadishu", 2.05, 45.32, "somalia"),
    ("berbera", 10.44, 45.01, "somalia"), ("nairobi", -1.29, 36.82, "kenya"),
    ("mombasa", -4.04, 39.67, "kenya"), ("lamu", -2.27, 40.90, "kenya"), ("kampala", 0.35, 32.58, "uganda"),
    ("dar es salaam", -6.79, 39.21, "tanzania"), ("kigali", -1.95, 30.06, "rwanda"),
    ("lagos", 6.52, 3.38, "nigeria"), ("apapa", 6.45, 3.36, "nigeria"), ("lekki", 6.44, 3.97, "nigeria"),
    ("tin can island", 6.44, 3.35, "nigeria"), ("abuja", 9.08, 7.40, "nigeria"),
    ("port harcourt", 4.82, 7.03, "nigeria"), ("onne", 4.72, 7.15, "nigeria"), ("calabar", 4.95, 8.32, "nigeria"),
    ("warri", 5.52, 5.75, "nigeria"), ("kano", 12.00, 8.59, "nigeria"), ("ibadan", 7.38, 3.95, "nigeria"),
    ("accra", 5.60, -0.19, "ghana"), ("tema", 5.67, -0.02, "ghana"), ("takoradi", 4.90, -1.76, "ghana"),
    ("abidjan", 5.36, -4.01, "ivory coast"), ("dakar", 14.72, -17.47, "senegal"),
    ("conakry", 9.64, -13.58, "guinea"), ("freetown", 8.47, -13.23, "sierra leone"),
    ("monrovia", 6.30, -10.80, "liberia"), ("lome", 6.13, 1.22, "togo"), ("lomé", 6.13, 1.22, "togo"),
    ("cotonou", 6.37, 2.39, "benin"), ("douala", 4.05, 9.77, "cameroon"), ("kribi", 2.94, 9.91, "cameroon"),
    ("libreville", 0.42, 9.47, "gabon"), ("pointe-noire", -4.78, 11.86, "congo"),
    ("kinshasa", -4.44, 15.27, "democratic republic of the congo"), ("luanda", -8.84, 13.23, "angola"),
    ("lobito", -12.35, 13.55, "angola"), ("walvis bay", -22.96, 14.51, "namibia"),
    ("windhoek", -22.56, 17.07, "namibia"), ("johannesburg", -26.20, 28.05, "south africa"),
    ("cape town", -33.92, 18.42, "south africa"), ("durban", -29.86, 31.02, "south africa"),
    ("maputo", -25.97, 32.57, "mozambique"), ("beira", -19.84, 34.84, "mozambique"),
    ("nouakchott", 18.08, -15.98, "mauritania"),
    ("london", 51.51, -0.13, "united kingdom"), ("manchester", 53.48, -2.24, "united kingdom"),
    ("birmingham", 52.49, -1.89, "united kingdom"), ("edinburgh", 55.95, -3.19, "united kingdom"),
    ("glasgow", 55.86, -4.25, "united kingdom"), ("liverpool", 53.41, -2.98, "united kingdom"),
    ("dublin", 53.35, -6.26, "ireland"), ("paris", 48.86, 2.35, "france"), ("madrid", 40.42, -3.70, "spain"),
    ("barcelona", 41.39, 2.17, "spain"), ("lisbon", 38.72, -9.14, "portugal"), ("rome", 41.90, 12.50, "italy"),
    ("milan", 45.46, 9.19, "italy"), ("berlin", 52.52, 13.40, "germany"), ("munich", 48.14, 11.58, "germany"),
    ("hamburg", 53.55, 9.99, "germany"), ("amsterdam", 52.37, 4.90, "netherlands"),
    ("rotterdam", 51.92, 4.48, "netherlands"), ("brussels", 50.85, 4.35, "belgium"),
    ("antwerp", 51.22, 4.40, "belgium"), ("zurich", 47.38, 8.54, "switzerland"),
    ("geneva", 46.20, 6.14, "switzerland"), ("vienna", 48.21, 16.37, "austria"),
    ("warsaw", 52.23, 21.01, "poland"), ("athens", 37.98, 23.73, "greece"), ("piraeus", 37.94, 23.65, "greece"),
    ("nicosia", 35.19, 33.38, "cyprus"), ("limassol", 34.71, 33.02, "cyprus"), ("oslo", 59.91, 10.75, "norway"),
    ("stockholm", 59.33, 18.07, "sweden"), ("copenhagen", 55.68, 12.57, "denmark"),
    ("baku", 40.41, 49.87, "azerbaijan"), ("tbilisi", 41.72, 44.78, "georgia"),
    ("karachi", 24.86, 67.01, "pakistan"), ("lahore", 31.52, 74.36, "pakistan"),
    ("islamabad", 33.68, 73.05, "pakistan"), ("mumbai", 19.08, 72.88, "india"),
    ("delhi", 28.70, 77.10, "india"), ("new delhi", 28.61, 77.21, "india"), ("chennai", 13.08, 80.27, "india"),
    ("bangalore", 12.97, 77.59, "india"), ("dhaka", 23.81, 90.41, "bangladesh"),
    ("chittagong", 22.36, 91.78, "bangladesh"), ("colombo", 6.93, 79.86, "sri lanka"),
    ("male", 4.18, 73.51, "maldives"), ("singapore", 1.29, 103.85, "singapore"),
    ("kuala lumpur", 3.14, 101.69, "malaysia"), ("jakarta", -6.21, 106.85, "indonesia"),
    ("bangkok", 13.76, 100.50, "thailand"), ("ho chi minh city", 10.82, 106.63, "vietnam"),
    ("hanoi", 21.03, 105.85, "vietnam"), ("manila", 14.60, 120.98, "philippines"),
    ("hong kong", 22.32, 114.17, "hong kong"), ("shanghai", 31.23, 121.47, "china"),
    ("beijing", 39.90, 116.41, "china"), ("shenzhen", 22.54, 114.06, "china"), ("tokyo", 35.68, 139.69, "japan"),
    ("seoul", 37.57, 126.98, "south korea"), ("sydney", -33.87, 151.21, "australia"),
    ("melbourne", -37.81, 144.96, "australia"), ("perth", -31.95, 115.86, "australia"),
    ("auckland", -36.85, 174.76, "new zealand"), ("new york", 40.71, -74.01, "united states"),
    ("houston", 29.76, -95.37, "united states"), ("los angeles", 34.05, -118.24, "united states"),
    ("chicago", 41.88, -87.63, "united states"), ("miami", 25.76, -80.19, "united states"),
    ("washington", 38.91, -77.04, "united states"), ("toronto", 43.65, -79.38, "canada"),
    ("vancouver", 49.28, -123.12, "canada"), ("mexico city", 19.43, -99.13, "mexico"),
    ("sao paulo", -23.55, -46.63, "brazil"), ("rio de janeiro", -22.91, -43.17, "brazil"),
    ("panama city", 8.98, -79.52, "panama"),
]

_CITY = {}
for _name, _lat, _lng, _country in CITIES:
    _CITY.setdefault(_name, []).append((_lat, _lng, _country))


def _key(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower().replace("-", " ")).strip(" .,")


def country_key(country: str) -> str:
    """The country as the table knows it ('' when it does not)."""
    k = _key(country)
    k = ALIASES.get(k, k)
    if k.startswith("the "):
        k = k[4:]
    return k if k in COUNTRIES else ""


def locate(city: str, country: str) -> tuple[float, float, str] | None:
    """(latitude, longitude, how) for a project's city and country: ``how`` is
    'city' when the city itself was found, 'country' when only its country
    was. None when neither is known."""
    ck = country_key(country)
    found = _CITY.get(_key(city)) or _CITY.get(_key(city).replace(" city", ""))
    if found:
        same = [f for f in found if f[2] == ck] if ck else found
        if same:
            return same[0][0], same[0][1], "city"
    if ck:
        lat, lng = COUNTRIES[ck]
        return lat, lng, "country"
    return None


def split_location(text: str) -> tuple[str, str]:
    """An older project's one-line location ("Jeddah, Saudi Arabia") as its
    city and country: the last part is the country when it is one."""
    parts = [p.strip() for p in (text or "").split(",") if p.strip()]
    if not parts:
        return "", ""
    if len(parts) == 1:
        return ("", parts[0]) if country_key(parts[0]) else (parts[0], "")
    return ", ".join(parts[:-1]), parts[-1]


def join_location(city: str, country: str) -> str:
    """The one line the sections are written with."""
    return ", ".join(p for p in (city.strip(), country.strip()) if p)


def country_names() -> list[str]:
    """For the new-project page's list to pick from."""
    return sorted(n.title().replace("'S", "'s").replace(" Of ", " of ").replace(" The ", " the ")
                  for n in COUNTRIES if n != "cote d'ivoire")
