"""
Malaysian-name normalization for cross-system identity matching.

Shared by absence_detector (scan<->roster) and roster_manager (portal/Excel
upsert keying), so it lives here to avoid a circular import between them.

See IDENTITY_RESOLUTION_DESIGN.md §7. Deliberately CONSERVATIVE: token ORDER is
preserved (no token-set sort) because sorting risks collapsing two distinct
students onto one key — a false *present*, which is worse than a false absent.
"""

import re

# bin/binti connector tokens (the "son of" / "daughter of" particle). These
# drift heavily between systems (BIN/B./BN, BINTI/BT/BTE) so they are
# canonicalised to one form each. Kept DISTINCT (BIN != BINTI) to avoid
# collapsing two genuinely different students onto one key.
_BIN_TOKENS = {"BIN", "B", "BN", "IBN"}
_BINTI_TOKENS = {"BINTI", "BT", "BTE", "BTI", "BINTE"}

_BRACKETED = re.compile(r"[\(\[][^\)\]]*[\)\]]")


def normalize_name(name: str) -> str:
    """
    Canonicalise a name for comparison:

    - Uppercase + strip + collapse internal whitespace.
    - Drop parenthetical / bracketed extras: ``(KETUA)``, ``(KP)``, ``[..]``.
    - Canonicalise the bin/binti connector family (``B.``/``BN`` -> ``BIN``,
      ``BT``/``BTE``/``BTI`` -> ``BINTI``) — but ONLY when the token is *between*
      other tokens, so a leading/trailing initial like ``B`` isn't read as "bin".
    - Normalise spacing around ``@`` aliases so ``X@Y`` == ``X @ Y`` (both sides
      retained verbatim — we don't guess which side another system used).
    """
    if not name:
        return ""

    n = name.upper().strip()
    n = _BRACKETED.sub(" ", n)        # drop (KETUA), (KP), [..]
    n = n.replace("@", " @ ")         # make '@' a standalone token
    raw = n.replace(".", " ").split()  # '.' as separator: "B." -> "B"

    tokens = []
    last = len(raw) - 1
    for i, t in enumerate(raw):
        medial = 0 < i < last  # connector particles are never first/last
        if medial and t in _BIN_TOKENS:
            tokens.append("BIN")
        elif medial and t in _BINTI_TOKENS:
            tokens.append("BINTI")
        else:
            tokens.append(t)

    return " ".join(tokens)
