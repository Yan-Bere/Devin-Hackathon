"""Verbatim-evidence checks for Devin extractions.

Every value Devin marks as coming from the document carries a short quote. These
helpers verify, deterministically, that the quote really occurs in the document and
that the reported number occurs in the quote. They are used both by the parser's
validation (to trigger the single repair request) and by the prompt-eval harness.
"""

from __future__ import annotations

import math
import re
import unicodedata

_MARKDOWN = re.compile(r"[*_`|#>]")
_SPACE = re.compile(r"\s+")
_DIGIT_COMMA = re.compile(r"(?<=\d),(?=\d{3}\b)")
_SCI = re.compile(r"(\d+(?:\.\d+)?)\s*(?:×|x|\*)\s*10\s*\^?\s*(-?\d+)")
_NUM = re.compile(r"-?\d+(?:\.\d+)?(?:e-?\d+)?")


def normalize_text(text: str) -> str:
    """NFKC, unify dashes/minus, drop markdown emphasis/table characters, collapse whitespace, lowercase."""
    s = unicodedata.normalize("NFKC", text)
    s = s.replace("\u2212", "-").replace("\u2013", "-").replace("\u2014", "-").replace("\u00a0", " ")
    s = _MARKDOWN.sub(" ", s)
    s = _SPACE.sub(" ", s)
    return s.strip().lower()


def evidence_found(evidence: str | None, document: str) -> bool:
    """True if the normalized quote is a substring of the normalized document."""
    if not evidence:
        return False
    quote = normalize_text(evidence)
    return len(quote) >= 2 and quote in normalize_text(document)


def numbers_in(text: str) -> list[float]:
    """All numbers in a quote, including 'a × 10⁻ⁿ' scientific notation."""
    s = _DIGIT_COMMA.sub("", normalize_text(text))
    found = [float(m) * 10.0 ** int(e) for m, e in _SCI.findall(s)]
    found.extend(float(tok) for tok in _NUM.findall(_SCI.sub(" ", s)))
    return found


def value_in_evidence(value: float | None, evidence: str | None, rel_tol: float = 1e-4) -> bool:
    """True if ``value`` (as written, unconverted) appears as a number in the quote.

    Signs are ignored because ranges such as '0.1-0.5' tokenize the second bound as negative.
    """
    if value is None or not evidence:
        return False
    return any(math.isclose(abs(value), abs(n), rel_tol=rel_tol, abs_tol=1e-9) for n in numbers_in(evidence))
