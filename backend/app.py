import os
import sys

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

sys.path.insert(0, os.path.dirname(__file__))

load_dotenv()

import design_logic  # noqa: E402
import alignment  # noqa: E402
import blast_client  # noqa: E402
import complexity_check  # noqa: E402
import refine  # noqa: E402
import layout_solver  # noqa: E402
import iupac  # noqa: E402

app = Flask(
    __name__,
    template_folder=os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates"),
    static_folder=os.path.join(os.path.dirname(os.path.dirname(__file__)), "static"),
)

# NCBI_EMAIL (optional) is read and applied inside blast_client, since
# that's where it's actually used - see that module for why.



@app.get("/")
def index():
    return render_template("index.html")


def _parse_primers_and_pairs(data):
    """Parses and validates the primers + primer-pairs input, then solves
    for every gap length automatically. Returns
    (primers, gaps, flank_length, gap_sources, degenerate_info).

    Each returned primer dict has both "sequence" (the original, as typed -
    possibly with degenerate IUPAC codes) and "resolved_sequence" (the
    fully A/C/G/T version actually used to build the gBlock).
    degenerate_info maps primer name -> list of substitutions made, for
    primers that had any degenerate bases at all.
    """
    primers_raw = data.get("primers")
    if not isinstance(primers_raw, list) or not primers_raw:
        raise ValueError("At least one primer is required")

    primers = []
    seen_names = set()
    for i, p in enumerate(primers_raw):
        if not isinstance(p, dict):
            raise ValueError(f"Primer {i + 1} is not formatted correctly")
        name = str(p.get("name", "")).strip()
        sequence = str(p.get("sequence", "")).strip()
        direction = str(p.get("direction", "")).strip().lower()
        if not name:
            raise ValueError(f"Primer {i + 1} needs a name")
        if name in seen_names:
            raise ValueError(f"Primer name '{name}' is used more than once - names must be unique")
        seen_names.add(name)
        if not sequence:
            raise ValueError(f"Primer '{name}' is missing a sequence")
        sequence = iupac.validate_primer_sequence(sequence, name)
        if direction not in ("forward", "reverse"):
            raise ValueError(f"Primer '{name}' must be marked Forward or Reverse")
        primers.append({"name": name, "sequence": sequence, "direction": direction})

    primers, degenerate_info = _resolve_degenerate_bases(primers, data)

    name_to_index = {p["name"]: i for i, p in enumerate(primers)}

    pairs_raw = data.get("pairs")
    if not isinstance(pairs_raw, list) or not pairs_raw:
        raise ValueError("At least one complete primer pair (a forward and a reverse primer) is required")

    resolved_pairs_by_name = []
    used_names = set()
    for i, pair in enumerate(pairs_raw):
        if not isinstance(pair, dict):
            raise ValueError(f"Pair {i + 1} is not formatted correctly")
        fwd_name = str(pair.get("forward_name", "")).strip()
        rev_name = str(pair.get("reverse_name", "")).strip()
        if not fwd_name or not rev_name:
            raise ValueError(f"Pair {i + 1} needs both a forward and a reverse primer selected")
        if fwd_name not in name_to_index:
            raise ValueError(f"Pair {i + 1} refers to an unknown forward primer '{fwd_name}'")
        if rev_name not in name_to_index:
            raise ValueError(f"Pair {i + 1} refers to an unknown reverse primer '{rev_name}'")
        if primers[name_to_index[fwd_name]]["direction"] != "forward":
            raise ValueError(f"Pair {i + 1}: '{fwd_name}' is not marked as a forward primer")
        if primers[name_to_index[rev_name]]["direction"] != "reverse":
            raise ValueError(f"Pair {i + 1}: '{rev_name}' is not marked as a reverse primer")
        try:
            fragment_length = int(pair.get("fragment_length"))
        except (TypeError, ValueError):
            raise ValueError(f"Pair {i + 1} needs a whole-number fragment length")
        if fragment_length <= 0:
            raise ValueError(f"Pair {i + 1}'s fragment length must be a positive number")

        used_names.add(fwd_name)
        used_names.add(rev_name)
        resolved_pairs_by_name.append((fwd_name, rev_name, fragment_length))

    unused = [p["name"] for p in primers if p["name"] not in used_names]
    if unused:
        raise ValueError(
            f"These primers aren't used in any pair: {', '.join(unused)}. "
            f"Every primer needs to be part of at least one pair."
        )

    try:
        flank_length = int(data.get("flank_length", 30))
    except (TypeError, ValueError):
        raise ValueError("Flank length must be a whole number")
    if flank_length < 0:
        raise ValueError("Flank length cannot be negative")

    # Work out the whole arrangement automatically: primers that share a
    # pair get ordered from their fragment lengths directly (no need to
    # trust the order you listed them in), and independent groups get
    # nested inside each other wherever that's physically possible, or
    # placed one after another with a fixed gap otherwise.
    final_order, gaps, gap_sources = layout_solver.solve_layout(primers, resolved_pairs_by_name)

    primers_by_name = {p["name"]: p for p in primers}
    primers = [primers_by_name[name] for name in final_order]

    return primers, gaps, flank_length, gap_sources, degenerate_info


def _resolve_degenerate_bases(primers, data):
    """Resolves every degenerate IUPAC base in each primer down to a single
    real base - either automatically (favouring A/T, per the default
    table) or using specific choices made for each occurrence. Returns
    (primers_with_resolved_sequence, degenerate_info), where degenerate_info
    maps primer name -> [{"position", "original_code", "chosen_base"}, ...]
    for any primer that had degenerate bases at all."""
    auto = data.get("auto_substitute_degenerate", True)
    degenerate_info = {}

    if auto:
        resolved_primers = []
        for p in primers:
            positions = iupac.find_degenerate_positions(p["sequence"])
            resolved_seq = iupac.auto_resolve(p["sequence"])
            if positions:
                degenerate_info[p["name"]] = [
                    {"position": pos, "original_code": code, "chosen_base": iupac.AUTO_SUBSTITUTION[code]}
                    for pos, code in positions
                ]
            resolved_primers.append({**p, "sequence": resolved_seq})
        return resolved_primers, degenerate_info

    subs_raw = data.get("degenerate_substitutions", [])
    if not isinstance(subs_raw, list):
        raise ValueError("degenerate_substitutions must be a list")

    subs_by_primer = {}
    for i, s in enumerate(subs_raw):
        if not isinstance(s, dict):
            raise ValueError(f"Substitution {i + 1} is not formatted correctly")
        primer_name = str(s.get("primer_name", "")).strip()
        try:
            position = int(s.get("position"))
        except (TypeError, ValueError):
            raise ValueError(f"Substitution {i + 1} needs a whole-number position")
        chosen_base = str(s.get("chosen_base", "")).strip().upper()
        if not chosen_base:
            raise ValueError(f"Substitution {i + 1} needs a chosen base")
        subs_by_primer.setdefault(primer_name, {})[position] = chosen_base

    resolved_primers = []
    for p in primers:
        positions = iupac.find_degenerate_positions(p["sequence"])
        this_primer_subs = subs_by_primer.get(p["name"], {})
        try:
            resolved_seq = iupac.apply_substitutions(p["sequence"], this_primer_subs)
        except ValueError as exc:
            raise ValueError(f"Primer '{p['name']}': {exc}")
        if positions:
            degenerate_info[p["name"]] = [
                {"position": pos, "original_code": code, "chosen_base": this_primer_subs[pos]}
                for pos, code in positions
            ]
        resolved_primers.append({**p, "sequence": resolved_seq})

    return resolved_primers, degenerate_info


def _resolve_gc_percent(data):
    """Works out the target GC% to design with. If the user pasted a
    specific target sequence, its own GC% is used (and reported back so the
    UI can show what was detected). Otherwise, falls back to whatever GC%
    they typed in manually."""
    target_sequence = str(data.get("target_sequence") or "").strip()
    if target_sequence:
        computed = design_logic.gc_content(target_sequence)
        return computed, "target_sequence"

    if "gc_percent" not in data or data.get("gc_percent") in (None, ""):
        raise ValueError("Provide a target GC%, or paste a target sequence to detect it from")
    try:
        gc_percent = float(data["gc_percent"])
    except (TypeError, ValueError):
        raise ValueError("gc_percent must be a number")
    if not (0 <= gc_percent <= 100):
        raise ValueError("gc_percent must be between 0 and 100")
    return gc_percent, "manual"


@app.post("/api/degenerate-scan")
def api_degenerate_scan():
    """Looks for degenerate (ambiguous) IUPAC bases across all your primers,
    so the app can ask you what to substitute each one with, when automatic
    substitution is turned off."""
    data = request.get_json(force=True)
    primers_raw = data.get("primers")
    if not isinstance(primers_raw, list) or not primers_raw:
        return jsonify({"error": "At least one primer is required"}), 400

    occurrences = []
    for p in primers_raw:
        name = str(p.get("name", "")).strip()
        try:
            sequence = iupac.validate_primer_sequence(str(p.get("sequence", "")), name)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

        for position, code in iupac.find_degenerate_positions(sequence):
            occurrences.append({
                "primer_name": name,
                "position": position,
                "code": code,
                "allowed_bases": sorted(iupac.IUPAC_BASES[code]),
                "suggested_base": iupac.AUTO_SUBSTITUTION[code],
            })

    return jsonify({"any_degenerate": len(occurrences) > 0, "occurrences": occurrences})


@app.post("/api/design")
def api_design():
    data = request.get_json(force=True)
    try:
        primers, gaps, flank_length, gap_sources, degenerate_info = _parse_primers_and_pairs(data)
        gc_percent, gc_percent_source = _resolve_gc_percent(data)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    try:
        result = design_logic.design_gblock(primers, gaps, gc_percent, flank_length)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    result["gc_percent_source"] = gc_percent_source
    result["degenerate_info"] = degenerate_info
    # Attach a "source" (computed / nested / sequential) to each gap segment,
    # so the UI can be upfront about which gaps were pinned down exactly by
    # your fragment lengths versus estimated.
    gap_i = 0
    for segment in result["segments"]:
        if segment["type"] == "gap":
            segment["source"] = gap_sources[gap_i]
            gap_i += 1

    return jsonify(result)


@app.post("/api/align")
def api_align():
    data = request.get_json(force=True)
    primers_raw = data.get("primers")
    sequence = data.get("sequence")
    if not isinstance(primers_raw, list) or not primers_raw:
        return jsonify({"error": "At least one primer is required"}), 400
    if not sequence:
        return jsonify({"error": "sequence is required"}), 400

    primers = []
    for i, p in enumerate(primers_raw):
        name = str(p.get("name", "")).strip()
        direction = str(p.get("direction", "")).strip().lower()
        try:
            sequence_field = iupac.validate_primer_sequence(str(p.get("sequence", "")), name)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        if not sequence_field or direction not in ("forward", "reverse"):
            return jsonify({"error": f"Primer {i + 1} is missing a sequence or direction"}), 400

        # degenerate_info entries use {"position","original_code","chosen_base"};
        # alignment wants {position: chosen_base}.
        substitutions = {
            entry["position"]: entry["chosen_base"]
            for entry in (p.get("degenerate_substitutions") or [])
        }
        primers.append({
            "sequence": sequence_field, "direction": direction, "label": name,
            "substitutions": substitutions,
        })

    result = alignment.align_primers(primers, sequence)
    return jsonify(result)


@app.post("/api/blast/start")
def api_blast_start():
    data = request.get_json(force=True)
    sequence = data.get("sequence", "").strip()
    if not sequence:
        return jsonify({"error": "sequence is required"}), 400

    program = data.get("program", "blastn")
    database = data.get("database", "nt")
    job_id = blast_client.start_blast_job(sequence, program, database)
    return jsonify({"job_id": job_id, "status": "queued"})


@app.get("/api/blast/status/<job_id>")
def api_blast_status(job_id):
    job = blast_client.get_job(job_id)
    if job is None:
        return jsonify({"error": "Unknown job_id"}), 404
    return jsonify(job)


@app.post("/api/complexity-check")
def api_complexity_check():
    data = request.get_json(force=True)
    sequence = data.get("sequence", "").strip()
    if not sequence:
        return jsonify({"error": "sequence is required"}), 400

    result = complexity_check.run_local_complexity_check(sequence)
    return jsonify(result)


@app.post("/api/design/fix")
def api_design_fix():
    data = request.get_json(force=True)
    try:
        primers, gaps, flank_length, gap_sources, degenerate_info = _parse_primers_and_pairs(data)
        gc_percent, gc_percent_source = _resolve_gc_percent(data)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    # Gap lengths only depend on primer lengths and your fragment lengths -
    # not on the random sequence content - so they're fixed for every retry;
    # only the random flanks/infills get re-rolled each attempt.
    result = refine.find_clean_design(primers, gaps, gc_percent, flank_length)
    result["design"]["gc_percent_source"] = gc_percent_source
    result["design"]["degenerate_info"] = degenerate_info
    gap_i = 0
    for segment in result["design"]["segments"]:
        if segment["type"] == "gap":
            segment["source"] = gap_sources[gap_i]
            gap_i += 1

    return jsonify(result)


if __name__ == "__main__":
    # debug mode must NEVER be on for a publicly-reachable deployment - its
    # interactive debugger can let anyone who triggers an error run code on
    # the server. It defaults off; set FLASK_DEBUG=1 locally if you want it.
    # host 0.0.0.0 and the PORT env var are what hosting platforms expect;
    # for local-only use they're harmless (still reachable at 127.0.0.1).
    debug_mode = os.environ.get("FLASK_DEBUG", "0") == "1"
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=debug_mode, host="0.0.0.0", port=port)
