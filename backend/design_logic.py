"""
Core logic for designing a synthetic gBlock fragment from one or more
primers, placed in whatever order you specify.

You give it an ordered list of primers, each marked "forward" or "reverse".
It lays them out left to right (5'->3') exactly in that order, using each
forward primer as-is and the reverse complement of each reverse primer
(since that's the strand a reverse primer's binding site appears on, on the
top strand of the finished fragment). Between each consecutive pair of
primers, it fills in a random stretch of sequence at your target GC% - you
choose how long each of these gaps is, so e.g. two forward primers sharing
one downstream reverse primer (a common "nested primer" layout, giving you
two different amplicon sizes from one construct) works fine. A 30bp random
buffer is added at the very start and very end, beyond the outermost
primers - standard practice for gBlocks, giving synthesis and downstream
PCR/digestion some breathing room at the ends.

Example, 3 primers (forward, forward, reverse), 2 gaps:

    [30bp flank] [fwd primer 1] [gap 1] [fwd primer 2] [gap 2] [revcomp(rev primer)] [30bp flank]

The simplest case - one forward and one reverse primer with a single gap
between them - is just this same logic with a 2-primer, 1-gap list.
"""

import random
from dataclasses import dataclass, field

COMPLEMENT = str.maketrans("ACGTacgt", "TGCAtgca")

MAX_HOMOPOLYMER_RUN = 5  # regenerate random stretches that exceed this run length
MAX_GENERATION_ATTEMPTS = 200

# Thresholds used by the local complexity check (see complexity_check.py).
# Kept here too so design_logic and complexity_check agree on what "risky"
# GC% territory looks like.
GC_WINDOW_HIGH = 60.0
GC_WINDOW_LOW = 30.0
OVERALL_GC_LOW = 25.0
OVERALL_GC_HIGH = 75.0

VALID_DIRECTIONS = {"forward", "reverse"}


def reverse_complement(seq: str) -> str:
    seq = seq.strip().upper()
    return seq.translate(COMPLEMENT)[::-1]


def gc_content(seq: str) -> float:
    seq = seq.upper()
    if not seq:
        return 0.0
    gc = sum(1 for b in seq if b in "GC")
    return round(100 * gc / len(seq), 2)


def _has_long_homopolymer(seq: str, max_run: int) -> bool:
    run = 1
    for i in range(1, len(seq)):
        if seq[i] == seq[i - 1]:
            run += 1
            if run > max_run:
                return True
        else:
            run = 1
    return False


def generate_random_seq(length: int, gc_percent: float, avoid_homopolymers: bool = True) -> str:
    """Generate a random DNA sequence of the given length, targeting gc_percent GC content.

    Uses a bag-of-bases + shuffle approach so the realized GC% is as close as
    possible to the target for the given length, then (optionally) rejects
    and retries sequences with long homopolymer runs, since IDT's complexity
    screener flags those.
    """
    if length <= 0:
        return ""
    if not (0 <= gc_percent <= 100):
        raise ValueError("gc_percent must be between 0 and 100")

    gc_count = round(length * gc_percent / 100)
    at_count = length - gc_count

    for _ in range(MAX_GENERATION_ATTEMPTS):
        bases = random.choices("GC", k=gc_count) + random.choices("AT", k=at_count)
        random.shuffle(bases)
        seq = "".join(bases)
        if not avoid_homopolymers or not _has_long_homopolymer(seq, MAX_HOMOPOLYMER_RUN):
            return seq
    # Fall back to the last attempt if we couldn't avoid homopolymers after many tries
    return seq


def _validate_primers_and_gaps(primers: list, gaps: list) -> None:
    if not primers:
        raise ValueError("At least one primer is required")
    for i, p in enumerate(primers):
        if not p.get("sequence", "").strip():
            raise ValueError(f"Primer {i + 1} is missing a sequence")
        direction = p.get("direction", "").strip().lower()
        if direction not in VALID_DIRECTIONS:
            raise ValueError(f"Primer {i + 1} has an invalid direction: {p.get('direction')!r}")
    expected_gaps = max(len(primers) - 1, 0)
    if len(gaps) != expected_gaps:
        raise ValueError(f"Expected {expected_gaps} gap length(s) for {len(primers)} primer(s), got {len(gaps)}")
    for i, g in enumerate(gaps):
        if g < 0:
            raise ValueError(f"Gap {i + 1} length cannot be negative")


@dataclass
class GBlockDesign:
    primers: list
    gaps: list
    target_gc_percent: float
    flank_length: int = 30

    sequence: str = field(init=False, default="")
    segments: list = field(init=False, default_factory=list)

    def build(self) -> "GBlockDesign":
        _validate_primers_and_gaps(self.primers, self.gaps)

        segments = []
        segments.append({
            "type": "flank",
            "label": "5' flank (random)",
            "seq": generate_random_seq(self.flank_length, self.target_gc_percent),
        })

        for i, primer in enumerate(self.primers):
            direction = primer["direction"].strip().lower()
            as_typed = primer["sequence"].strip().upper()
            seg_seq = as_typed if direction == "forward" else reverse_complement(as_typed)
            label = primer.get("name") or primer.get("label") or f"Primer {i + 1} ({direction})"
            segments.append({
                "type": "primer",
                "label": label,
                "seq": seg_seq,
                "direction": direction,
                "as_typed": as_typed,
            })

            if i < len(self.primers) - 1:
                gap_len = self.gaps[i]
                segments.append({
                    "type": "gap",
                    "label": f"Gap {i + 1} (random)",
                    "seq": generate_random_seq(gap_len, self.target_gc_percent),
                })

        segments.append({
            "type": "flank",
            "label": "3' flank (random)",
            "seq": generate_random_seq(self.flank_length, self.target_gc_percent),
        })

        self.segments = segments
        self.sequence = "".join(s["seq"] for s in segments)
        return self

    def summary(self) -> dict:
        return {
            "sequence": self.sequence,
            "length": len(self.sequence),
            "overall_gc_percent": gc_content(self.sequence),
            "target_gc_percent": self.target_gc_percent,
            "segments": [
                {
                    "type": s["type"],
                    "label": s["label"],
                    "seq": s["seq"],
                    "length": len(s["seq"]),
                    **({"direction": s["direction"], "as_typed": s["as_typed"]} if s["type"] == "primer" else {}),
                }
                for s in self.segments
            ],
        }


def design_gblock(primers: list, gaps: list, gc_percent: float, flank_length: int = 30) -> dict:
    design = GBlockDesign(
        primers=primers,
        gaps=gaps,
        target_gc_percent=gc_percent,
        flank_length=flank_length,
    ).build()
    return design.summary()
