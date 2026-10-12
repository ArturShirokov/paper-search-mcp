from .biorxiv import BioRxivSearcher


class MedRxivSearcher(BioRxivSearcher):
    """Searcher for medRxiv papers (same API as bioRxiv, different server)."""

    SERVER = "medrxiv"
    LABEL = "medRxiv"
    BASE_URL = "https://api.biorxiv.org/details/medrxiv"
    SITE_URL = "https://www.medrxiv.org"
    # As the API spells them (e.g. "hiv aids", plain "endocrinology").
    CATEGORIES = frozenset({
        "addiction medicine", "allergy and immunology", "anesthesia",
        "cardiovascular medicine", "dentistry and oral medicine", "dermatology",
        "emergency medicine", "endocrinology", "epidemiology",
        "forensic medicine", "gastroenterology", "genetic and genomic medicine",
        "geriatric medicine", "health economics", "health informatics",
        "health policy", "health systems and quality improvement", "hematology",
        "hiv aids", "infectious diseases",
        "intensive care and critical care medicine", "medical education",
        "medical ethics", "nephrology", "neurology", "nursing", "nutrition",
        "obstetrics and gynecology", "occupational and environmental health",
        "oncology", "ophthalmology", "orthopedics", "otolaryngology",
        "pain medicine", "palliative medicine", "pathology", "pediatrics",
        "pharmacology and therapeutics", "primary care research",
        "psychiatry and clinical psychology", "public and global health",
        "radiology and imaging", "rehabilitation medicine and physical therapy",
        "respiratory medicine", "rheumatology", "sexual and reproductive health",
        "sports medicine", "surgery", "toxicology", "transplantation", "urology",
    })
