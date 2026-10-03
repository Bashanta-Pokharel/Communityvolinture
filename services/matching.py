"""The project's only matching algorithm: Jaccard similarity.

Formula:
    J(A, B) = |A ∩ B| / |A ∪ B|

A and B are sets of unique terms.  ∩ means terms common to both sets,
∪ means every unique term from either set, and | | means set size.
"""


def terms(text):
    """Convert comma-separated text into normalized unique terms."""
    return {item.strip().lower() for item in (text or "").split(",") if item.strip()}


def jaccard_similarity(first_text, second_text):
    """Return score plus both sets, their intersection, and their union."""
    first_set = terms(first_text)
    second_set = terms(second_text)
    intersection = first_set & second_set
    union = first_set | second_set
    score = len(intersection) / len(union) if union else 0
    return score, first_set, second_set, intersection, union
