"""Classify free-text listing locations as US, Canada, Remote, or other."""

import re
import unicodedata

US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa",
    "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi",
    "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire",
    "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York", "NC": "North Carolina",
    "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania",
    "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee",
    "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
    "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming", "DC": "District of Columbia",
    "PR": "Puerto Rico",
}
CA_PROVINCES = {
    "ON": "Ontario", "QC": "Quebec", "BC": "British Columbia", "AB": "Alberta",
    "MB": "Manitoba", "SK": "Saskatchewan", "NS": "Nova Scotia", "NB": "New Brunswick",
    "NL": "Newfoundland and Labrador", "PE": "Prince Edward Island",
    "YT": "Yukon", "NT": "Northwest Territories", "NU": "Nunavut",
}
US_ALIASES = {"nyc", "sf", "la", "dc", "bay area", "silicon valley", "united states", "usa", "us", "u.s."}
US_NAMES = {n.lower() for n in US_STATES.values()}
CA_NAMES = {n.lower() for n in CA_PROVINCES.values()} | {"canada"}
# Company boards often give only a city. These names mean one country in tech job posts; ambiguous
# ones (London, Waterloo, Cambridge, Victoria, Hamilton) are left out.
CA_CITIES = {
    "montreal", "toronto", "vancouver", "ottawa", "calgary", "edmonton", "winnipeg", "halifax",
    "mississauga", "markham", "kitchener", "laval", "gatineau", "longueuil", "sherbrooke", "saskatoon",
    "regina", "brampton", "burnaby", "quebec city", "ville de quebec", "trois-rivieres", "levis",
    "boucherville", "brossard", "dorval", "pointe-claire", "saint-laurent", "terrebonne", "kanata",
    "oakville", "vaughan", "richmond hill", "north york", "scarborough", "etobicoke",
}
US_CITIES = {
    "new york city", "san francisco", "seattle", "boston", "chicago", "austin", "los angeles", "san jose",
    "palo alto", "mountain view", "menlo park", "sunnyvale", "redmond", "cupertino", "santa clara",
    "san diego", "atlanta", "denver", "dallas", "houston", "pittsburgh", "philadelphia", "miami",
    "phoenix", "detroit", "minneapolis", "nashville", "raleigh", "salt lake city", "brooklyn",
    "manhattan", "jersey city", "boulder", "ann arbor", "portland", "san mateo", "redwood city",
    "irvine", "bellevue", "kirkland", "plano", "chandler", "durham", "charlotte", "baltimore",
}

_TRAILING_CODE = re.compile(r",\s*([A-Z]{2})$")
_REMOTE = re.compile(r"remote|t[ée]l[ée]travail|[àa] distance", re.IGNORECASE)
# "(Hybrid)", "(St. Laurent)", " - Hybride", ", On-site": how people work there, not where.
_PARENS = re.compile(r"\s*\([^)]*\)")
_WORK_MODE = re.compile(r"\s*[-–,/|]\s*(hybrid|hybride|on-?site|in-?office|in office|sur place|en personne"
                        r"|office|bureau|head ?office|headquarters|hq)\b.*$", re.IGNORECASE)
_WORK_MODE_LEAD = re.compile(r"^(hybrid|hybride|on-?site|sur place)\s*[-–:,]\s*", re.IGNORECASE)
_AREA_WORDS = re.compile(r"\b(greater|grand|area|metropolitan|metro|region|r[ée]gion|downtown|centre-ville)\b",
                         re.IGNORECASE)


def fold(text: str) -> str:
    """Lower case without accents: "Montréal, Québec" -> "montreal, quebec"."""
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)).lower()


def classify(location: str) -> set[str]:
    """Return the regions ({"US", "CA", "REMOTE"}) a single location string belongs to.

    An empty set means the location is outside the US and Canada.
    """
    raw = location.strip()
    if _REMOTE.search(raw):
        rest = re.sub(rf"{_REMOTE.pattern}|\bin\b|\bau\b|\ben\b", "", raw, flags=re.IGNORECASE).strip(" ,-–()")
        if not rest:
            return {"REMOTE"}  # Plain "Remote": country unknown, keep it.
        country = _country(rest)
        return {"REMOTE", country} if country else set()
    country = _country(raw)
    return {country} if country else set()


def _country(place: str) -> str | None:
    """Return "US", "CA", or None for a non-remote place name."""
    place = _WORK_MODE_LEAD.sub("", _WORK_MODE.sub("", _PARENS.sub("", place))).strip(" ,-–") or place
    text = fold(place)
    if "canada" in text:
        return "CA"
    parts = [p.strip() for p in place.split(",")]
    last = parts[-1]
    if len(parts) >= 2 and _TRAILING_CODE.fullmatch(", " + last.upper()):
        # "City, XX" or "Area, City, XX": "CA" here is California, unless the city is Canadian.
        code = last.upper()
        if code == "CA" and (_city(parts[-2]) == "CA" or parts[-2].strip().upper() in CA_PROVINCES):
            return "CA"  # "Montreal, CA", "Toronto, ON, CA"
        return "US" if code in US_STATES else "CA" if code in CA_PROVINCES else None
    last = fold(last)
    if len(parts) >= 2 and last in US_NAMES:  # "Santa Clara, California"
        return "US"
    if len(parts) >= 2 and last in CA_NAMES:  # "Toronto, Ontario", "Montréal, Québec"
        return "CA"
    if len(parts) >= 3:  # "City, Region, Country"
        return "US" if last in US_ALIASES | {"united states of america"} else "CA" if last == "can" else None
    if text in US_ALIASES or text in US_NAMES or text.removeprefix("south ") in US_ALIASES:
        return "US"
    if text in CA_NAMES:
        return "CA"
    return _city(parts[0]) if len(parts) == 1 else None


def _city(name: str) -> str | None:
    """"Montreal", "Greater Toronto Area", "Montréal": the country of a well-known city."""
    text = re.sub(r"\s+", " ", _AREA_WORDS.sub("", fold(name))).strip(" -")
    return "CA" if text in CA_CITIES else "US" if text in US_CITIES else None


def classify_all(locations: list[str]) -> set[str]:
    regions: set[str] = set()
    for loc in locations:
        regions |= classify(loc)
    return regions
