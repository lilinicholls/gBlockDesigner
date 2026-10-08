"""
Inserts an optional probe (e.g. a qPCR/TaqMan-style probe) into an
already-built gBlock design, at a specific position within a chosen primer
pair's "between" region - the same region that pair's fragment_length
describes (see layout_solver.py for exactly what that means).

The probe's sequence must be plain A/C/G/T (no degenerate codes) and is
inserted exactly as given, replacing that stretch of the randomly
generated gap it lands in - it isn't reverse-complemented or altered,
since it's placed directly onto the top strand exactly as you typed it.

It can never land on top of a primer (including another primer nested
inside the same pair's region, if you've built a nested layout) - that,
or a probe that simply doesn't fit in the space available, raises a clear
error rather than silently corrupting anything.
"""


def insert_probe(design: dict, forward_name: str, reverse_name: str,
                  probe_sequence: str, start_position=None) -> dict:
    """design: the dict returned by design_logic.design_gblock. Returns a
    NEW dict with the probe spliced in (the original is left untouched).
    start_position: 0-indexed offset from the start of the "between"
    region for this pair (i.e. right after the forward primer ends); if
    None, the probe is centered within that region."""
    segments = design["segments"]

    absolute = []
    cursor = 0
    for seg in segments:
        absolute.append((cursor, cursor + seg["length"]))
        cursor += seg["length"]

    fwd_idx = next((i for i, s in enumerate(segments) if s["type"] == "primer" and s["label"] == forward_name), None)
    rev_idx = next((i for i, s in enumerate(segments) if s["type"] == "primer" and s["label"] == reverse_name), None)
    if fwd_idx is None:
        raise ValueError(f"Could not find a primer named '{forward_name}' in this design.")
    if rev_idx is None:
        raise ValueError(f"Could not find a primer named '{reverse_name}' in this design.")
    if fwd_idx >= rev_idx:
        raise ValueError(f"'{forward_name}' does not come before '{reverse_name}' in this design.")

    region_start = absolute[fwd_idx][1]
    region_end = absolute[rev_idx][0]
    region_length = region_end - region_start

    probe_sequence = probe_sequence.strip().upper()
    probe_length = len(probe_sequence)
    if probe_length == 0:
        raise ValueError("The probe needs a sequence.")
    if probe_length > region_length:
        raise ValueError(
            f"The probe ({probe_length}bp) is longer than the space between "
            f"'{forward_name}' and '{reverse_name}' ({region_length}bp), so it can't fit there."
        )

    if start_position is None:
        offset = (region_length - probe_length) // 2
    else:
        offset = start_position

    probe_abs_start = region_start + offset
    probe_abs_end = probe_abs_start + probe_length

    if offset < 0 or probe_abs_end > region_end:
        raise ValueError(
            f"That start position would place the probe outside the region between "
            f"'{forward_name}' and '{reverse_name}' (which is {region_length}bp long). "
            f"Choose a start position between 0 and {region_length - probe_length}."
        )

    for i, seg in enumerate(segments):
        if seg["type"] == "primer":
            seg_start, seg_end = absolute[i]
            if probe_abs_start < seg_end and probe_abs_end > seg_start:
                raise ValueError(
                    f"That position would overlap the primer '{seg['label']}', which sits "
                    f"inside this pair's region. Choose a different start position."
                )

    target_gap_idx = None
    for i, seg in enumerate(segments):
        if seg["type"] != "gap":
            continue
        seg_start, seg_end = absolute[i]
        if probe_abs_start >= seg_start and probe_abs_end <= seg_end:
            target_gap_idx = i
            break
    if target_gap_idx is None:
        raise ValueError("Couldn't place the probe there without overlapping something else - try a different start position.")

    gap_seg = segments[target_gap_idx]
    gap_start, _ = absolute[target_gap_idx]
    local_offset = probe_abs_start - gap_start

    before_seq = gap_seg["seq"][:local_offset]
    after_seq = gap_seg["seq"][local_offset + probe_length:]

    new_segments = list(segments[:target_gap_idx])
    # Preserve any extra fields already on the gap (like a "source" label
    # from the layout solver) on both halves it gets split into.
    gap_extra_fields = {k: v for k, v in gap_seg.items() if k not in ("seq", "length")}
    if before_seq:
        new_segments.append({**gap_extra_fields, "seq": before_seq, "length": len(before_seq)})
    new_segments.append({
        "type": "probe",
        "label": "Probe",
        "seq": probe_sequence,
        "length": probe_length,
        "pair": f"{forward_name} & {reverse_name}",
    })
    if after_seq:
        new_segments.append({**gap_extra_fields, "seq": after_seq, "length": len(after_seq)})
    new_segments.extend(segments[target_gap_idx + 1:])

    new_sequence = "".join(s["seq"] for s in new_segments)
    gc_count = sum(1 for b in new_sequence if b in "GC")

    new_design = dict(design)
    new_design["segments"] = new_segments
    new_design["sequence"] = new_sequence
    new_design["length"] = len(new_sequence)
    new_design["overall_gc_percent"] = round(100 * gc_count / len(new_sequence), 2) if new_sequence else 0.0
    new_design["probe_offset_used"] = offset

    return new_design
