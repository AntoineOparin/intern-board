"""Classify free-text listing locations as US, Canada, Remote, or other."""

import re

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

_TRAILING_CODE = re.compile(r",\s*([A-Z]{2})$")


def classify(location: str) -> set[str]:
    """Return the regions ({"US", "CA", "REMOTE"}) a single location string belongs to.

    An empty set means the location is outside the US and Canada.
    """
    raw = location.strip()
    if re.search(r"remote", raw, re.IGNORECASE):
        rest = re.sub(r"remote|\bin\b", "", raw, flags=re.IGNORECASE).strip(" ,-()")
        if not rest:
            return {"REMOTE"}  # Plain "Remote": country unknown, keep it.
        country = _country(rest)
        return {"REMOTE", country} if country else set()
    country = _country(raw)
    return {country} if country else set()


def _country(place: str) -> str | None:
    """Return "US", "CA", or None for a non-remote place name."""
    text = place.lower()
    if "canada" in text:
        return "CA"
    parts = [p.strip() for p in place.split(",")]
    last = parts[-1]
    if len(parts) >= 2 and _TRAILING_CODE.fullmatch(", " + last.upper()):
        # "City, XX" or "Area, City, XX": "CA" here is California.
        code = last.upper()
        return "US" if code in US_STATES else "CA" if code in CA_PROVINCES else None
    if len(parts) >= 2 and last.lower() in US_NAMES:  # "Santa Clara, California"
        return "US"
    if len(parts) >= 2 and last.lower() in CA_NAMES:  # "Toronto, Ontario"
        return "CA"
    if len(parts) >= 3:  # "City, Region, Country"
        return "US" if last.lower() in US_ALIASES | {"united states of america"} else None
    if text in US_ALIASES or text in US_NAMES or text.removeprefix("south ") in US_ALIASES:
        return "US"
    if text in CA_NAMES:
        return "CA"
    return None


def classify_all(locations: list[str]) -> set[str]:
    regions: set[str] = set()
    for loc in locations:
        regions |= classify(loc)
    return regions
