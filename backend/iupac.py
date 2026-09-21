"""
Handles IUPAC ambiguity codes in primer sequences: validating that a primer
only contains real IUPAC letters, finding where degenerate (ambiguous)
positions are, substituting them down to a single real base for gBlock
synthesis (since a physical gBlock has to be one exact sequence - it can't
actually contain a "wobble" position the way a primer order can), and
IUPAC-aware matching for the alignment step, so a degenerate primer is
correctly shown as binding wherever the gBlock's chosen base is one of the
bases that code allows - not flagged as a mismatch just because the
literal characters differ.
"""

# What each IUPAC code actually represents.
IUPAC_BASES = {
    "A": {"A"}, "C": {"C"}, "G": {"G"}, "T": {"T"},
    "R": {"A", "G"},
    "Y": {"C", "T"},
    "S": {"G", "C"},
    "W": {"A", "T"},
    "K": {"G", "T"},
    "M": {"A", "C"},
    "B": {"C", "G", "T"},
    "D": {"A", "G", "T"},
    "H": {"A", "C", "T"},
    "V": {"A", "C", "G"},
    "N": {"A", "C", "G", "T"},
}

VALID_CHARACTERS = set(IUPAC_BASES.keys())
DEGENERATE_CODES = VALID_CHARACTERS - {"A", "C", "G", "T"}

# The default substitution used when "automatically substitute degenerate
# bases" is left on - favours A/T over G/C, per your reference table.
AUTO_SUBSTITUTION = {
    "R": "A", "Y": "T", "S": "G", "W": "A", "K": "T", "M": "A",
    "B": "T", "D": "A", "H": "A", "V": "A", "N": "A",
}

# IUPAC-correct complement, including the degenerate codes (e.g. R = A-or-G,
# so its complement is Y = T-or-C). Needed to correctly reverse-complement
# a reverse primer that still has degenerate bases in it.
IUPAC_COMPLEMENT = {
    "A": "T", "T": "A", "C": "G", "G": "C",
    "R": "Y", "Y": "R", "S": "S", "W": "W", "K": "M", "M": "K",
    "B": "V", "V": "B", "D": "H", "H": "D", "N": "N",
}


def reverse_complement_iupac(sequence: str) -> str:
    """Reverse-complements a sequence that may still contain degenerate
    IUPAC codes, keeping each code's meaning correct (not just A/C/G/T)."""
    return "".join(IUPAC_COMPLEMENT[ch] for ch in sequence.upper())[::-1]


def validate_primer_sequence(sequence: str, primer_label: str = "") -> str:
    """Checks every character is a real IUPAC code (A/C/G/T or a degenerate
    code). Returns the sequence, uppercased. Raises ValueError naming the
    offending characters if not."""
    upper = sequence.strip().upper()
    invalid = sorted({ch for ch in upper if ch not in VALID_CHARACTERS})
    if invalid:
        label = f"Primer '{primer_label}'" if primer_label else "A primer"
        raise ValueError(
            f"{label} contains character(s) that aren't valid IUPAC bases: "
            f"{', '.join(invalid)}. Only A, C, T, G and the degenerate codes "
            f"R, Y, S, W, K, M, B, D, H, V, N are allowed."
        )
    return upper


def find_degenerate_positions(sequence: str) -> list:
    """Returns [(position, code), ...] for every degenerate (non-ACGT)
    base in the sequence, position is 0-indexed."""
    return [(i, ch) for i, ch in enumerate(sequence.upper()) if ch in DEGENERATE_CODES]


def auto_resolve(sequence: str) -> str:
    """Replaces every degenerate base with its default A/T-favouring
    substitution."""
    return "".join(AUTO_SUBSTITUTION.get(ch, ch) for ch in sequence.upper())


def apply_substitutions(sequence: str, substitutions: dict) -> str:
    """Replaces specific positions with specific chosen bases.
    substitutions: {position (int): chosen_base (str)}. Every degenerate
    position in the sequence must have an entry, and every chosen base
    must be one the original code actually allows (e.g. you can't resolve
    an R to a C, since R only ever means A or G)."""
    sequence = sequence.upper()
    chars = list(sequence)
    for i, ch in enumerate(sequence):
        if ch in DEGENERATE_CODES:
            if i not in substitutions:
                raise ValueError(
                    f"Missing a chosen base for the degenerate position at "
                    f"index {i} ({ch})."
                )
            chosen = substitutions[i].strip().upper()
            if chosen not in IUPAC_BASES[ch]:
                allowed = "/".join(sorted(IUPAC_BASES[ch]))
                raise ValueError(
                    f"'{chosen}' isn't a valid substitution for {ch} at "
                    f"position {i} - {ch} can only mean {allowed}."
                )
            chars[i] = chosen
    return "".join(chars)


def bases_compatible(primer_base: str, target_base: str) -> bool:
    """True if target_base is one of the real bases primer_base's IUPAC
    code could mean (used for alignment - a degenerate primer correctly
    "matches" any base its code allows, not just an identical character)."""
    primer_base = primer_base.upper()
    target_base = target_base.upper()
    return target_base in IUPAC_BASES.get(primer_base, {primer_base})
