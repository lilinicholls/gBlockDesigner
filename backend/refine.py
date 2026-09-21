"""
"Fix issues" logic: the flagged problems (hot GC spots, homopolymer runs,
repeats, hairpins) only ever come from the randomly generated parts of the
sequence (the flanks and the infill) - never from the primers, which are
always used exactly as given.

So the most reliable fix is simple: keep everything the same (same primers,
same fragment length, same target GC%) and re-roll the random regions,
checking each attempt, until one comes back with nothing flagged - or we
run out of attempts, in which case we hand back whichever attempt had the
fewest problems.

One important limit this module is honest about: if the *target* GC% you
asked for is itself close to or past the 100bp-window threshold the
complexity check uses, no amount of re-rolling can fix that. Rolling dice
doesn't help if every side of the die is a losing number - if you ask for
random sequence that averages 65% GC, virtually every stretch of it will
also be around 65% GC, which will keep tripping a "no window over 60%" rule
no matter how many times you try again. In that case the only real fix is
to lower (or raise) the target GC% itself, so this module detects that
situation up front and says so plainly, rather than silently retrying and
quietly failing.
"""

import design_logic
import complexity_check

DEFAULT_MAX_ATTEMPTS = 30
REDUCED_ATTEMPTS_WHEN_STRUCTURALLY_LIMITED = 6

# How close to a threshold counts as "cutting it close enough that
# regeneration might need a lot of luck" (percentage points).
MARGIN = 5.0


def _count_flags(report: dict) -> int:
    return sum(1 for c in report["checks"] if c["flagged"])


def diagnose_structural_limits(gc_percent: float) -> list:
    """Checks whether the requested target GC% is itself incompatible with
    the complexity check's thresholds, regardless of how the random bases
    happen to land. Returns a list of plain-language notes (empty if fine).
    """
    notes = []
    high, low = design_logic.GC_WINDOW_HIGH, design_logic.GC_WINDOW_LOW
    overall_high, overall_low = design_logic.OVERALL_GC_HIGH, design_logic.OVERALL_GC_LOW

    if gc_percent >= high:
        notes.append(
            f"Your target GC% ({gc_percent}%) is at or above the {high}% "
            f"limit used for the 100bp-window check. Since the random "
            f"sequence is generated to average your target GC%, essentially "
            f"every 100bp stretch of it will also land around {gc_percent}% "
            f"- above the limit. Re-rolling the random sequence won't fix "
            f"this; lowering your target GC% will."
        )
    elif gc_percent >= high - MARGIN:
        notes.append(
            f"Your target GC% ({gc_percent}%) is close to the {high}% "
            f"window limit, so it may take many attempts (or may not "
            f"succeed at all) to get every 100bp stretch under it."
        )

    if gc_percent <= low:
        notes.append(
            f"Your target GC% ({gc_percent}%) is at or below the {low}% "
            f"low-GC window limit, for the same reason in reverse - "
            f"lowering isn't the fix here, raising your target GC% is."
        )
    elif gc_percent <= low + MARGIN:
        notes.append(
            f"Your target GC% ({gc_percent}%) is close to the {low}% "
            f"low-GC window limit, so regeneration may struggle here too."
        )

    if gc_percent >= overall_high or gc_percent <= overall_low:
        notes.append(
            f"Your target GC% is also outside IDT's overall workable range "
            f"({overall_low}-{overall_high}%) - adjusting your target GC% "
            f"is the only real fix for that."
        )

    return notes


def find_clean_design(primers: list, gaps: list, gc_percent: float, flank_length: int = 30,
                       max_attempts=None) -> dict:
    structural_notes = diagnose_structural_limits(gc_percent)

    if max_attempts is None:
        max_attempts = REDUCED_ATTEMPTS_WHEN_STRUCTURALLY_LIMITED if structural_notes else DEFAULT_MAX_ATTEMPTS

    best_design = None
    best_report = None
    best_flag_count = None

    for attempt in range(1, max_attempts + 1):
        design = design_logic.design_gblock(primers, gaps, gc_percent, flank_length)
        report = complexity_check.run_local_complexity_check(design["sequence"])
        flag_count = _count_flags(report)

        if best_flag_count is None or flag_count < best_flag_count:
            best_design, best_report, best_flag_count = design, report, flag_count

        if flag_count == 0:
            return {
                "design": design,
                "complexity": report,
                "attempts": attempt,
                "fully_resolved": True,
                "structural_notes": structural_notes,
            }

    return {
        "design": best_design,
        "complexity": best_report,
        "attempts": max_attempts,
        "fully_resolved": False,
        "structural_notes": structural_notes,
    }
