"""Geographic reference data and saved research areas.

Reference lists are public administrative facts (countries, Indian states and union territories). Districts,
cities and industrial areas/clusters are added by users as saved research areas (optionally with a source
URL such as the state industrial development corporation's estate list); nothing is pre-seeded or guessed.
`comtrade` is the UN Comtrade reporter/partner code (UN M49; Comtrade uses 699 for India, 842 for the USA,
251 for France). Countries without a listed code can still be queried by entering the numeric code.
"""
from __future__ import annotations

COUNTRIES: list[dict] = [
    {"name": n, "code": c, "comtrade": m} for n, c, m in [
        ("India", "IN", 699), ("United Arab Emirates", "AE", 784), ("Saudi Arabia", "SA", 682), ("Qatar", "QA", 634),
        ("Oman", "OM", 512), ("Kuwait", "KW", 414), ("Bahrain", "BH", 48), ("Bangladesh", "BD", 50), ("Nepal", "NP", 524),
        ("Sri Lanka", "LK", 144), ("Singapore", "SG", 702), ("Malaysia", "MY", 458), ("Indonesia", "ID", 360),
        ("Vietnam", "VN", 704), ("Thailand", "TH", 764), ("China", "CN", 156), ("Japan", "JP", 392),
        ("South Korea", "KR", 410), ("Australia", "AU", 36), ("Kenya", "KE", 404), ("Nigeria", "NG", 566),
        ("South Africa", "ZA", 710), ("Egypt", "EG", 818), ("Turkey", "TR", 792), ("Germany", "DE", 276),
        ("France", "FR", 251), ("Italy", "IT", 380), ("Spain", "ES", 724), ("Netherlands", "NL", 528),
        ("United Kingdom", "GB", 826), ("United States", "US", 842), ("Canada", "CA", 124), ("Mexico", "MX", 484),
        ("Brazil", "BR", 76),
    ]
]

INDIA_STATES = [
    "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh", "Goa", "Gujarat", "Haryana",
    "Himachal Pradesh", "Jharkhand", "Karnataka", "Kerala", "Madhya Pradesh", "Maharashtra", "Manipur", "Meghalaya",
    "Mizoram", "Nagaland", "Odisha", "Punjab", "Rajasthan", "Sikkim", "Tamil Nadu", "Telangana", "Tripura",
    "Uttar Pradesh", "Uttarakhand", "West Bengal",
]
INDIA_UTS = [
    "Andaman and Nicobar Islands", "Chandigarh", "Dadra and Nagar Haveli and Daman and Diu", "Delhi",
    "Jammu and Kashmir", "Ladakh", "Lakshadweep", "Puducherry",
]

LEVEL_PARENT = {"country": ("global",), "state": ("country",), "district": ("state",),
                "city": ("district", "state"), "industrial_area": ("city", "district", "state")}


def reference() -> dict:
    return {"levels": ["global", "country", "state", "district", "city", "industrial_area"],
            "countries": COUNTRIES,
            "india": {"states": INDIA_STATES, "union_territories": INDIA_UTS,
                      "note": "Districts, cities and industrial clusters are added as saved research areas. "
                              "India's Local Government Directory (lgdirectory.gov.in) is the official district list."},
            "sources": [{"name": "UN Comtrade", "url": "https://comtradeplus.un.org/"},
                        {"name": "Local Government Directory (India)", "url": "https://lgdirectory.gov.in/"}]}


def comtrade_code(country: str | None) -> int | None:
    if not country:
        return None
    c = country.strip().lower()
    if c in ("world", "all"):
        return 0
    if c.isdigit():
        return int(c)
    for x in COUNTRIES:
        if c in (x["name"].lower(), x["code"].lower()):
            return x["comtrade"]
    return None


def country_name(code: str | None) -> str | None:
    if not code:
        return None
    return next((x["name"] for x in COUNTRIES if x["code"] == code.upper()), None)
