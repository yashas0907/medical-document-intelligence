"""Shared query processing: abbreviation-aware expansion used by retrieval
AND sentence ranking so both legs see the same vocabulary space."""


def _load_maps():
    from app.ml.extraction.entities import ABBREVIATIONS

    full_to_abbr: dict[str, list[str]] = {}
    for a, full in ABBREVIATIONS.items():
        if len(full.split()) <= 4:
            full_to_abbr.setdefault(full, []).append(a)
    return ABBREVIATIONS, full_to_abbr


def expand_query(query: str) -> str:
    """'blood pressure' → also 'bp'; 'bp' → also 'blood pressure'."""
    import re

    abbrs, full_to_abbr = _load_maps()
    toks = re.findall(r"[A-Za-z0-9]+", query)
    extra: list[str] = []
    for i, t in enumerate(toks):
        tl = t.lower()
        if tl in abbrs:
            extra.append(abbrs[tl])
        for j in range(i + 1, min(i + 4, len(toks))):
            phrase = " ".join(x.lower() for x in toks[i : j + 1])
            if phrase in full_to_abbr:
                extra.extend(full_to_abbr[phrase])
    if extra:
        seen: dict[str, None] = {}
        for e in extra:
            seen.setdefault(e, None)
        return query + " " + " ".join(seen.keys())
    return query
