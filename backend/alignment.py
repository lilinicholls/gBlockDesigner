"""
Lines up each primer against the designed gBlock sequence and shows where it
matches, in the same simple style Primer3 uses to show primer dimers:

    5'-ATGGCTAGCAAAGGAGAAG-3'
       |||||||||||||||||||
    5'-ATGGCTAGCAAAGGAGAAG-3'

Rather than running a general-purpose alignment algorithm, this takes
advantage of something we already know: we built the sequence ourselves, so
we know exactly where each primer is *supposed* to sit. We just look there
directly - first for a fully-compatible match, and if that's not found
(e.g. you edited the sequence afterwards), we fall back to scanning the
whole sequence for the window with the fewest mismatches.

Matching is IUPAC-aware: if your primer has a degenerate base like R (A or
G), it's shown as correctly binding wherever the gBlock's actual base is
either A or G - not flagged as a mismatch just because the letters differ.
This uses your ORIGINAL primer (with its degenerate codes intact), even
though the gBlock itself was built using one specific resolved base at
that position - the two are related but separate things, and this module
also reports which substitutions were made so you can see both.
"""

import iupac

COMPLEMENT = str.maketrans("ACGTacgt", "TGCAtgca")


def reverse_complement(seq: str) -> str:
    return seq.upper().translate(COMPLEMENT)[::-1]


def _best_match(primer: str, sequence: str) -> dict:
    """Finds where `primer` best lines up against `sequence`, using
    IUPAC-aware compatibility rather than exact character matching."""
    primer = primer.strip().upper()
    sequence = sequence.strip().upper()
    primer_len = len(primer)
    seq_len = len(sequence)

    if primer_len == 0 or seq_len < primer_len:
        return {
            "start": None, "end": None, "mismatches": None,
            "target_region": "", "found": False,
        }

    best_start = 0
    best_mismatches = primer_len + 1
    best_window = sequence[0:primer_len]
    for i in range(seq_len - primer_len + 1):
        window = sequence[i:i + primer_len]
        mismatches = sum(1 for p, t in zip(primer, window) if not iupac.bases_compatible(p, t))
        if mismatches < best_mismatches:
            best_start, best_mismatches, best_window = i, mismatches, window
            if mismatches == 0:
                break

    return {
        "start": best_start,
        "end": best_start + primer_len,
        "mismatches": best_mismatches,
        "target_region": best_window,
        "found": True,
    }


def _find_secondary_matches(primer: str, sequence: str, primary_start: int, primary_end: int,
                             identity_threshold: float = 80.0, max_results: int = 5) -> list:
    """Scans the WHOLE sequence (not just around the intended binding site)
    for any other spot this primer could plausibly also bind - a real risk
    for off-target priming within the same gBlock. Returns positions other
    than the primary match with at least `identity_threshold`% identity,
    picking the best match in each region and skipping near-duplicates of
    a hit already found (a repeat region would otherwise report the same
    near-miss many times, once per 1bp shift)."""
    primer_len = len(primer)
    seq_len = len(sequence)
    if primer_len == 0 or seq_len < primer_len:
        return []

    candidates = []
    for i in range(seq_len - primer_len + 1):
        if i < primary_end and i + primer_len > primary_start:
            continue  # overlaps the primary match - not a separate site
        window = sequence[i:i + primer_len]
        mismatches = sum(1 for p, t in zip(primer, window) if not iupac.bases_compatible(p, t))
        percent_identity = round(100 * (primer_len - mismatches) / primer_len, 2)
        if percent_identity >= identity_threshold:
            candidates.append({"start": i, "end": i + primer_len, "mismatches": mismatches, "percent_identity": percent_identity})

    candidates.sort(key=lambda c: -c["percent_identity"])

    picked = []
    covered = []
    for c in candidates:
        if any(c["start"] < end and c["end"] > start for start, end in covered):
            continue  # near-duplicate of an already-picked hit
        picked.append(c)
        covered.append((c["start"], c["end"]))
        if len(picked) >= max_results:
            break

    return picked


def build_substitution_notes(original_primer: str, substitutions: dict) -> list:
    """Plain-language notes on which degenerate positions in this primer
    (numbered from its own 5' end, as you'd read it) were resolved to
    which base for the gBlock. substitutions: {position (int): base}."""
    notes = []
    for i, code in enumerate(original_primer.upper()):
        if code in iupac.DEGENERATE_CODES:
            chosen = substitutions.get(i)
            if chosen:
                allowed = "/".join(sorted(iupac.IUPAC_BASES[code]))
                notes.append(
                    f"Position {i + 1} (5'\u21923'): {code} ({allowed}) was set to {chosen} for this gBlock."
                )
    return notes


def align_primer_to_sequence(original_primer: str, sequence: str, primer_label: str,
                              primer_direction_note: str = "", substitutions: dict = None,
                              is_reverse: bool = False) -> dict:
    original_primer = original_primer.strip().upper()
    substitutions = substitutions or {}

    # The primer as it actually appears on the top strand of the gBlock -
    # reverse-complemented (IUPAC-aware) for reverse primers, unchanged
    # for forward ones. Degenerate codes are kept as-is here so matching
    # stays IUPAC-aware; substitution notes are built separately from the
    # primer's own original 5'->3' orientation, regardless of direction.
    display_primer = iupac.reverse_complement_iupac(original_primer) if is_reverse else original_primer

    match = _best_match(display_primer, sequence)

    if not match["found"]:
        return {
            "primer_label": primer_label,
            "primer": display_primer,
            "error": "Primer is longer than the designed sequence, or the sequence is empty.",
        }

    target_region = match["target_region"]
    match_line = "".join(
        "|" if iupac.bases_compatible(p, t) else " " for p, t in zip(display_primer, target_region)
    )
    mismatches = match["mismatches"]
    percent_identity = round(100 * (len(display_primer) - mismatches) / len(display_primer), 2) if display_primer else 0.0

    secondary_matches = _find_secondary_matches(display_primer, sequence, match["start"], match["end"])

    return {
        "primer_label": primer_label,
        "primer_direction_note": primer_direction_note,
        "primer": display_primer,
        "start": match["start"],
        "end": match["end"],
        "mismatches": mismatches,
        "percent_identity": percent_identity,
        "full_length_match": mismatches == 0,
        "target_region": target_region,
        "match_line": match_line,
        "substitution_notes": build_substitution_notes(original_primer, substitutions),
        "secondary_matches": secondary_matches,
    }


def align_primers(primers: list, sequence: str) -> list:
    """Aligns every primer in the list against the sequence. Forward
    primers are aligned as typed; reverse primers are aligned via their
    reverse complement (since that's the strand they appear on in the
    designed top-strand sequence).

    Each primer dict may include "substitutions": {position: chosen_base}
    describing degenerate bases that were resolved for the gBlock, so the
    result can note them alongside the alignment."""
    results = []
    for i, primer in enumerate(primers):
        direction = primer["direction"].strip().lower()
        as_typed = primer["sequence"].strip().upper()
        label = primer.get("label") or f"Primer {i + 1} ({direction})"
        substitutions = primer.get("substitutions") or {}

        is_reverse = direction == "reverse"
        note = (
            "(shown as its reverse complement - that's the strand it binds on the designed sequence)"
            if is_reverse else ""
        )

        result = align_primer_to_sequence(
            as_typed, sequence, label, primer_direction_note=note,
            substitutions=substitutions, is_reverse=is_reverse,
        )
        result["direction"] = direction
        results.append(result)

    return results
