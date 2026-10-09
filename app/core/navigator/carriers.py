"""Which insurer a policy belongs to, and what the handover knows about it.

The handover keyed every carrier rule on ``meta.carrier.upper()`` — ``AXA``,
``GNP``, ``METLIFE``, ``SMNYL`` — and relied on the parser answering with exactly
that name. A parser that writes "MetLife México, S.A. de C.V." matched nothing
and every carrier rule was skipped without a word, so the name is mapped onto
the handover's spelling once, here, before any rule reads it.
"""

import os
import re
import unicodedata
from functools import lru_cache
from typing import Optional

# The spellings the handover's rules and prompts use.
CARRIERS = ("AXA", "GNP", "MetLife", "SMNYL")

# Name fragments, folded (no accents, lowercase, single spaces). SMNYL first, so
# "Seguros Monterrey New York Life" is not read as anything shorter.
_CARRIER_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("SMNYL", re.compile(r"\b(smnyl|monterrey new york life|seguros monterrey|monterrey nyl)\b")),
    ("MetLife", re.compile(r"\bmet ?life\b")),
    ("GNP", re.compile(r"\b(gnp|grupo nacional provincial)\b")),
    ("AXA", re.compile(r"\baxa\b")),
)

_KNOWLEDGE_DIR = os.path.join(os.path.dirname(__file__), "knowledge")

# The NotebookLM digests of each carrier's condiciones generales (Notebook A).
# None was produced for SMNYL.
_CG_DIGESTS = {
    "AXA": "carrier_axa.md",
    "GNP": "carrier_gnp.md",
    "MetLife": "carrier_metlife.md",
}


def _fold(text: str) -> str:
    """Strip accents and punctuation for name matching.

    Args:
        text: A carrier name as written.

    Returns:
        str: The folded form.
    """
    decomposed = unicodedata.normalize("NFKD", text)
    without_accents = "".join(char for char in decomposed if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", without_accents.lower()).strip()


def normalize_carrier(name: Optional[str]) -> Optional[str]:
    """Map an insurer name onto the handover's spelling.

    Args:
        name: The name as the parser or the operator wrote it.

    Returns:
        Optional[str]: ``AXA``, ``GNP``, ``MetLife`` or ``SMNYL``; the name
        unchanged when it is none of them; None when there is no name.
    """
    if not name or not name.strip():
        return None
    folded = _fold(name)
    for carrier, pattern in _CARRIER_PATTERNS:
        if pattern.search(folded):
            return carrier
    return name.strip()


@lru_cache(maxsize=4)
def carrier_cg_digest(carrier: str) -> Optional[str]:
    """The carrier's condiciones generales digest, when the handover has one.

    Args:
        carrier: The handover's carrier spelling.

    Returns:
        Optional[str]: The digest text, or None.
    """
    filename = _CG_DIGESTS.get(carrier)
    if filename is None:
        return None
    with open(os.path.join(_KNOWLEDGE_DIR, filename), encoding="utf-8") as handle:
        return handle.read()
