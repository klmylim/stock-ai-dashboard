"""
Malaysian financial news sources configuration.
Add or remove sources freely — just follow the same dict structure.
"""

RSS_SOURCES = [
    # English sources
    {
        "name": "The Edge Markets",
        "url": "https://theedgemarkets.com/rss/markets",
        "language": "en",
        "category": "markets",
    },
    {
        "name": "The Edge Markets - Companies",
        "url": "https://theedgemarkets.com/rss/companies",
        "language": "en",
        "category": "companies",
    },
    {
        "name": "The Star Business",
        "url": "https://www.thestar.com.my/rss/business",
        "language": "en",
        "category": "business",
    },
    {
        "name": "The Star Markets",
        "url": "https://www.thestar.com.my/rss/business/marketwatch",
        "language": "en",
        "category": "markets",
    },
    {
        "name": "Free Malaysia Today - Business",
        "url": "https://www.freemalaysiatoday.com/feed/",
        "language": "en",
        "category": "business",
    },
    {
        "name": "Bernama Business",
        "url": "https://www.bernama.com/en/rss/business.php",
        "language": "en",
        "category": "business",
    },
    {
        "name": "Malay Mail Business",
        "url": "https://www.malaymail.com/feed/business",
        "language": "en",
        "category": "business",
    },
    {
        "name": "CodeBlue (Healthcare)",
        "url": "https://codeblue.galencentre.org/feed/",
        "language": "en",
        "category": "healthcare",
    },
    # Bahasa Malaysia sources
    {
        "name": "Berita Harian Ekonomi",
        "url": "https://www.bharian.com.my/rss/ekonomi",
        "language": "ms",
        "category": "ekonomi",
    },
    {
        "name": "Utusan Malaysia Ekonomi",
        "url": "https://www.utusan.com.my/feed/",
        "language": "ms",
        "category": "ekonomi",
    },
    {
        "name": "Sinar Harian Ekonomi",
        "url": "https://www.sinarharian.com.my/feed/",
        "language": "ms",
        "category": "ekonomi",
    },
]

# Direct scrape targets (no RSS — full-page scrape)
SCRAPE_TARGETS = [
    {
        "name": "i3investor - Latest News",
        "url": "https://klse.i3investor.com/web/blog/latest",
        "language": "en",
        "category": "retail_sentiment",
        "type": "forum",
    },
    {
        "name": "Bursa Malaysia Announcements",
        "url": "https://www.bursamalaysia.com/market_information/announcements/company_announcement",
        "language": "en",
        "category": "announcements",
        "type": "announcements",
    },
]

# Bursa sector codes for tagging
BURSA_SECTORS = {
    "BANK": ["MAYBANK", "CIMB", "PUBLIC", "HLBANK", "RHBBANK", "AMBANK", "AFFIN"],
    "TELCO": ["TM", "MAXIS", "DIGI", "AXIATA", "TIME"],
    "ENERGY": ["PETGRAN", "DIALOG", "HIBISCS", "SAPNRG", "UZMA"],
    "PLANTATION": ["IOICORP", "SIMEPLT", "KLKK", "FGV", "TAANN"],
    "PROPERTY": ["SPSETIA", "IOIPROP", "UEMS", "SUNWAY", "ECOWLD"],
    "TECH": ["INARI", "KESM", "UNISEM", "MPI", "VITROX"],
    "CONSUMER": ["NESTLE", "DLADY", "QL", "PARKSON", "PADINI"],
    "HEALTHCARE": ["IHH", "KPJ", "PHARMANIAGA", "APEX"],
    "CONSTRUCTION": ["GAMUDA", "IJM", "WCT", "MUHIBAH", "PINTARAS"],
    "UTILITIES": ["TENAGA", "YTLPOWR", "MALAKOF", "RANHILL"],
}
