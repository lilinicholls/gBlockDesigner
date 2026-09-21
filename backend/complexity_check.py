"""
Local, offline checks that mirror the kinds of problems IDT's own gBlocks
order-entry tool screens for, based on IDT's published guidance:
https://sg.idtdna.com/pages/products/genes-and-gene-fragments/double-stranded-dna-fragments/gblocks-gene-fragments

None of this calls IDT or requires logging in - it's just re-implementing
their documented rules of thumb so you get a heads-up before you ever visit
their site. It is NOT a substitute for IDT's real screening tool, which uses
its own (undocumented, proprietary) logic - always double-check on their
site before ordering. A reminder link is included in every result.

What's checked, in plain terms:

1. Overall GC content - DNA that's almost all G/C or almost all A/T is
   harder to manufacture. IDT flags sequences below 25% or above 75% GC.

2. "Hot" 100bp windows - even if the *overall* GC% looks fine, a local
   stretch that's unusually GC-rich can still cause problems. We slide a
   100bp window along the sequence and flag any window over 60% GC (you can
   adjust this window size and threshold).

3. Homopolymer runs - the same letter repeated many times in a row (e.g.
   "AAAAAAAAAA"). IDT flags 10+ A's/T's in a row, or 6+ G's/C's in a row.

4. Repeats - the same chunk of sequence appearing more than once. Repeated
   text confuses synthesis chemistry in a similar way to how it's hard to
   proofread a paragraph that repeats itself.

5. Hairpins - a stretch of sequence that is the "mirror-image complement"
   of another nearby stretch, so the single strand can fold back and stick
   to itself, like a bobby pin (hence the name). This can block synthesis
   and PCR.
"""

import design_logic

IDT_GBLOCK_ENTRY_URL = "https://www.idtdna.com/site/order/gblockentry"
IDT_GUIDANCE_URL = (
    "https://www.idtdna.com/pages/products/genes-and-gene-fragments/"
    "double-stranded-dna-fragments/gblocks-gene-fragments"
)

COMPLEMENT = str.maketrans("ACGTacgt", "TGCAtgca")


def reverse_complement(seq: str) -> str:
    return seq.upper().translate(COMPLEMENT)[::-1]


def gc_percent(seq: str) -> float:
    seq = seq.upper()
    if not seq:
        return 0.0
    gc = sum(1 for b in seq if b in "GC")
    return round(100 * gc / len(seq), 2)


# ---------- 1 & 2: GC content, overall and in sliding windows ----------

def check_overall_gc(seq: str, low=design_logic.OVERALL_GC_LOW, high=design_logic.OVERALL_GC_HIGH) -> dict:
    pct = gc_percent(seq)
    flagged = pct < low or pct > high
    return {
        "check": "overall_gc",
        "label": "Overall GC content",
        "value": pct,
        "flagged": flagged,
        "message": (
            f"Overall GC content is {pct}%, which is outside IDT's usual "
            f"workable range of {low}-{high}%. This makes the whole "
            f"fragment harder to manufacture."
            if flagged else
            f"Overall GC content is {pct}%, within IDT's usual workable "
            f"range of {low}-{high}%."
        ),
    }


def check_gc_windows(seq: str, window: int = 100,
                      high_threshold: float = design_logic.GC_WINDOW_HIGH,
                      low_threshold: float = design_logic.GC_WINDOW_LOW) -> dict:
    """Slides a window across the sequence and flags any stretch whose GC%
    is too high (or too low) even if the sequence as a whole looks fine."""
    hits = []
    n = len(seq)
    if n < window:
        # Sequence is shorter than one window - just check the whole thing.
        pct = gc_percent(seq)
        if pct > high_threshold or pct < low_threshold:
            hits.append({"start": 0, "end": n, "gc_percent": pct})
    else:
        for start in range(0, n - window + 1):
            chunk = seq[start:start + window]
            pct = gc_percent(chunk)
            if pct > high_threshold or pct < low_threshold:
                hits.append({"start": start, "end": start + window, "gc_percent": pct})

    merged = _merge_overlapping_windows(hits)

    return {
        "check": "gc_windows",
        "label": f"{window}bp window GC content",
        "flagged": len(merged) > 0,
        "windows": merged,
        "message": (
            f"Found {len(merged)} region(s) of {window}bp or more where "
            f"local GC content goes outside {low_threshold}-{high_threshold}%, "
            f"even though the overall sequence may look fine."
            if merged else
            f"No {window}bp stretch was found with GC content outside "
            f"{low_threshold}-{high_threshold}%."
        ),
    }


def _merge_overlapping_windows(hits: list) -> list:
    """Sliding a window one base at a time produces many overlapping hits
    for the same underlying hot spot - merge them into single regions."""
    if not hits:
        return []
    hits = sorted(hits, key=lambda h: h["start"])
    merged = [dict(hits[0])]
    for h in hits[1:]:
        last = merged[-1]
        if h["start"] <= last["end"]:
            last["end"] = max(last["end"], h["end"])
            last["gc_percent"] = round((last["gc_percent"] + h["gc_percent"]) / 2, 2)
        else:
            merged.append(dict(h))
    return merged


# ---------- 3: Homopolymer runs ----------

def check_homopolymers(seq: str, at_run_length: int = 10, gc_run_length: int = 6) -> dict:
    seq = seq.upper()
    hits = []
    i = 0
    n = len(seq)
    while i < n:
        j = i
        while j < n and seq[j] == seq[i]:
            j += 1
        run_length = j - i
        base = seq[i]
        threshold = gc_run_length if base in "GC" else at_run_length
        if run_length >= threshold:
            hits.append({"start": i, "end": j, "base": base, "length": run_length})
        i = j

    return {
        "check": "homopolymers",
        "label": "Repeated single letters (homopolymers)",
        "flagged": len(hits) > 0,
        "runs": hits,
        "message": (
            f"Found {len(hits)} run(s) of a single letter repeated enough "
            f"times to be flagged by IDT (10+ A's/T's in a row, or 6+ "
            f"G's/C's in a row)."
            if hits else
            "No overly long runs of a single repeated letter were found."
        ),
    }


# ---------- 4: Repeats ----------

def check_repeats(seq: str, min_repeat_len: int = 20) -> dict:
    """Flags any chunk of `min_repeat_len` or more bases that appears more
    than once in the sequence."""
    seq = seq.upper()
    n = len(seq)
    seen = {}
    hits = []
    if n >= min_repeat_len:
        for i in range(n - min_repeat_len + 1):
            chunk = seq[i:i + min_repeat_len]
            if chunk in seen:
                hits.append({"chunk": chunk, "first_seen_at": seen[chunk], "repeated_at": i})
            else:
                seen[chunk] = i

    return {
        "check": "repeats",
        "label": "Repeated sequence chunks",
        "flagged": len(hits) > 0,
        "repeats": hits[:20],  # cap what we show, this can otherwise get noisy
        "total_repeat_hits": len(hits),
        "message": (
            f"Found {len(hits)} spot(s) where a {min_repeat_len}+ base "
            f"chunk of sequence repeats elsewhere in the fragment."
            if hits else
            f"No repeated chunks of {min_repeat_len}+ bases were found."
        ),
    }


# ---------- 5: Hairpins ----------

def check_hairpins(seq: str, min_stem: int = 8, max_stem: int = 15,
                    min_loop: int = 3, max_loop: int = 10) -> dict:
    """Looks for a stretch of sequence whose reverse complement occurs a
    short distance downstream - the hallmark of a hairpin (stem-loop)
    structure, where a single strand of DNA folds back and pairs with
    itself.

    This is a simplified heuristic (not IDT's actual proprietary
    algorithm), tuned to flag likely candidates without drowning you in
    false positives from short, coincidental matches.
    """
    seq = seq.upper()
    n = len(seq)
    hits = []
    covered_positions = set()

    for i in range(n):
        if i in covered_positions:
            continue
        found = False
        for stem_len in range(max_stem, min_stem - 1, -1):
            if i + stem_len > n:
                continue
            stem = seq[i:i + stem_len]
            stem_rc = reverse_complement(stem)

            window_start = i + stem_len + min_loop
            window_end = min(n, i + stem_len + max_loop + stem_len)
            if window_start >= window_end:
                continue

            search_region = seq[window_start:window_end]
            idx = search_region.find(stem_rc)
            if idx != -1:
                partner_start = window_start + idx
                partner_end = partner_start + stem_len
                hits.append({
                    "stem_start": i,
                    "stem_end": i + stem_len,
                    "partner_start": partner_start,
                    "partner_end": partner_end,
                    "stem_length": stem_len,
                    "loop_length": partner_start - (i + stem_len),
                })
                for p in range(i, partner_end):
                    covered_positions.add(p)
                found = True
                break
        if found:
            continue

    return {
        "check": "hairpins",
        "label": "Possible hairpins (self-folding sequence)",
        "flagged": len(hits) > 0,
        "hairpins": hits,
        "message": (
            f"Found {len(hits)} possible hairpin(s) - spots where the "
            f"sequence could fold back and stick to itself."
            if hits else
            "No likely hairpin structures were found."
        ),
    }


# ---------- Combined report ----------

def run_local_complexity_check(sequence: str) -> dict:
    sequence = sequence.strip().upper()
    checks = [
        check_overall_gc(sequence),
        check_gc_windows(sequence),
        check_homopolymers(sequence),
        check_repeats(sequence),
        check_hairpins(sequence),
    ]
    any_flagged = any(c["flagged"] for c in checks)
    return {
        "sequence_length": len(sequence),
        "any_flagged": any_flagged,
        "checks": checks,
        "idt_entry_url": IDT_GBLOCK_ENTRY_URL,
        "idt_guidance_url": IDT_GUIDANCE_URL,
        "disclaimer": (
            "These are simplified, local versions of the checks IDT "
            "describes publicly. IDT's real screening tool may use "
            "additional or different logic - always double-check your "
            "final sequence on IDT's own site before ordering."
        ),
    }
