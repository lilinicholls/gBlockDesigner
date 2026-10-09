"""
Bulk gBlock design from a CSV of primer pairs.

HOW IT FITS TOGETHER
---------------------
1. parse_csv() reads one row per primer pair (plus an optional probe for
   that pair) and validates everything, reporting every problem it finds
   (with line numbers) in one go.

2. Pairs that share a primer are best kept on the same gBlock - their
   fragment lengths then fix each other's positions, and the shared primer
   is only used once. So by default each group of linked pairs is treated
   as one unit. But that's a preference, not a requirement: if your rules
   (or the number of gBlocks you asked for) make that impossible, the
   linked pairs are separated, and a shared primer simply appears on each
   gBlock that needs it.

3. The user's rules are applied on top: "must be on the same gBlock"
   merges units together, "cannot be on the same gBlock" is kept as a
   conflict that no gBlock may contain both sides of.

4. The units are assigned to gBlocks according to the chosen mode:
       single - everything on one gBlock, placed end to end
       nested - everything on one gBlock, with groups packed inside each
                other's gaps wherever they physically fit
       split  - divided across exactly N gBlocks (largest first, always
                into the least-full gBlock the rules allow)

5. Each gBlock is then laid out and designed with the same code the
   single-gBlock page uses, re-rolling its random sections to avoid IDT
   complexity flags, and inserting any probes.
"""

import csv
import io

import design_logic
import iupac
import layout_solver
import refine

MAX_ROWS = 500
MAX_CSV_CHARS = 1_000_000
MAX_SEARCH_NODES = 200_000
MAX_ERRORS_REPORTED = 15
INITIAL_ATTEMPTS = 12

TEMPLATE_HEADERS = [
    "pair_id", "forward_name", "forward_sequence",
    "reverse_name", "reverse_sequence", "fragment_length",
    "probe_sequence", "probe_start",
]
REQUIRED_HEADERS = ["forward_name", "forward_sequence", "reverse_name", "reverse_sequence", "fragment_length"]

TEMPLATE_ROWS = [
    ["Pair1", "Gene1_F", "ACGTTGCAAGCTTAGCCATG", "Gene1_R", "TGGCATCAGTTCAGGACTCA", "120", "CGGTTATTTCTGTCTATCAT", ""],
    ["Pair2", "Gene2_F", "GGATCCTAGGCTAACGTTCA", "Gene2_R", "CCTTAAGGCTTACGATCGGA", "95", "", ""],
    ["Pair3", "Gene3_F", "TTGACCGGTAACGTCAAGCT", "Gene3_R", "AGCTTGCAACGGTTAGCTAC", "150", "", ""],
]


class _GiveUp(Exception):
    pass


def template_csv() -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\r\n")
    writer.writerow(TEMPLATE_HEADERS)
    writer.writerows(TEMPLATE_ROWS)
    return buf.getvalue()


# ---------------------------------------------------------------- parsing

def _normalise_header(h: str) -> str:
    return (h or "").strip().lower().replace(" ", "_").replace("-", "_")


def parse_csv(text: str) -> dict:
    """Returns {"primers": {name: {...}}, "pairs": [{...}]}. Raises
    ValueError (message lists every problem found, one per line)."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("The CSV file is empty.")
    if len(text) > MAX_CSV_CHARS:
        raise ValueError("The CSV file is too large (limit is about 1 MB).")

    text = text.lstrip("﻿")
    first_line = text.splitlines()[0]
    delimiter = ","
    for candidate in (";", "\t"):
        if first_line.count(candidate) > first_line.count(delimiter):
            delimiter = candidate

    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    try:
        header_row = next(reader)
    except StopIteration:
        raise ValueError("The CSV file is empty.")
    headers = [_normalise_header(h) for h in header_row]

    missing = [h for h in REQUIRED_HEADERS if h not in headers]
    if missing:
        raise ValueError(
            "The CSV is missing these column(s): " + ", ".join(missing)
            + ". Download the template to see the expected columns."
        )
    col = {h: headers.index(h) for h in headers if h}

    def cell(row, name):
        i = col.get(name)
        return row[i].strip() if i is not None and i < len(row) else ""

    errors = []
    primers = {}
    pairs = []
    seen_ids = {}

    for row in reader:
        line = reader.line_num
        if not any(c.strip() for c in row):
            continue
        if len(pairs) >= MAX_ROWS:
            errors.append(f"Too many rows - the limit is {MAX_ROWS} pairs.")
            break

        row_errors = []
        fwd_name = cell(row, "forward_name")
        rev_name = cell(row, "reverse_name")
        fwd_seq = cell(row, "forward_sequence")
        rev_seq = cell(row, "reverse_sequence")
        frag_raw = cell(row, "fragment_length")
        pair_id = cell(row, "pair_id") or f"Pair{len(pairs) + 1}"
        probe_seq = cell(row, "probe_sequence").upper()
        probe_start_raw = cell(row, "probe_start")

        if not fwd_name:
            row_errors.append("forward_name is empty")
        if not rev_name:
            row_errors.append("reverse_name is empty")
        if fwd_name and fwd_name == rev_name:
            row_errors.append("forward and reverse primers can't have the same name")
        if pair_id in seen_ids:
            row_errors.append(f"pair_id '{pair_id}' is already used on line {seen_ids[pair_id]}")

        try:
            as_float = float(frag_raw)
            fragment_length = int(as_float) if as_float == int(as_float) else None
        except (ValueError, OverflowError):
            fragment_length = None
        if fragment_length is None or fragment_length <= 0:
            row_errors.append("fragment_length must be a positive whole number")

        probe = None
        if probe_seq:
            bad = sorted({ch for ch in probe_seq if ch not in "ACGT"})
            if bad:
                row_errors.append(
                    f"probe_sequence has character(s) that aren't plain A/C/G/T: {', '.join(bad)}"
                )
            probe_start = None
            if probe_start_raw:
                try:
                    f = float(probe_start_raw)
                    probe_start = int(f) if f == int(f) and f >= 0 else None
                except (ValueError, OverflowError):
                    probe_start = None
                if probe_start is None:
                    row_errors.append("probe_start must be a whole number, 0 or more (or left blank to centre the probe)")
            probe = {"sequence": probe_seq, "start": probe_start}
        elif probe_start_raw:
            row_errors.append("probe_start is set but probe_sequence is empty")

        checked = {}
        for name, seq, direction in ((fwd_name, fwd_seq, "forward"), (rev_name, rev_seq, "reverse")):
            if not name:
                continue
            if not seq:
                row_errors.append(f"{direction}_sequence is empty")
                continue
            try:
                seq = iupac.validate_primer_sequence(seq, name)
            except ValueError as exc:
                row_errors.append(str(exc))
                continue
            known = primers.get(name)
            if known:
                if known["direction"] != direction:
                    row_errors.append(
                        f"primer '{name}' is used as {direction} here but as {known['direction']} on line {known['line']}"
                    )
                elif known["sequence"] != seq:
                    row_errors.append(
                        f"primer '{name}' has a different sequence than on line {known['line']} - "
                        f"each primer name must always have the same sequence"
                    )
            else:
                checked[name] = {"name": name, "sequence": seq, "direction": direction, "line": line}

        if row_errors:
            errors.append(f"Line {line}: " + "; ".join(row_errors))
            continue

        primers.update(checked)
        seen_ids[pair_id] = line
        pairs.append({
            "id": pair_id, "forward_name": fwd_name, "reverse_name": rev_name,
            "fragment_length": fragment_length, "probe": probe, "line": line,
        })

    if errors:
        shown = errors[:MAX_ERRORS_REPORTED]
        extra = len(errors) - len(shown)
        if extra > 0:
            shown.append(f"...and {extra} more problem(s).")
        raise ValueError("\n".join(shown))
    if not pairs:
        raise ValueError("The CSV has no primer pairs in it.")

    return {"primers": primers, "pairs": pairs}


# ------------------------------------------------------------ grouping

class _UnionFind:
    def __init__(self, n):
        self.p = list(range(n))

    def find(self, x):
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[rb] = ra


def _resolve_primers(primers: dict) -> dict:
    """Fully A/C/G/T versions of every primer (degenerate bases substituted
    automatically, favouring A/T) plus a note of what was substituted."""
    resolved = {}
    for name, p in primers.items():
        positions = iupac.find_degenerate_positions(p["sequence"])
        info = [
            {"position": pos, "original_code": code, "chosen_base": iupac.AUTO_SUBSTITUTION[code]}
            for pos, code in positions
        ]
        resolved[name] = {
            "name": name,
            "direction": p["direction"],
            "original_sequence": p["sequence"],
            "sequence": iupac.auto_resolve(p["sequence"]),
            "degenerate": info,
        }
    return resolved


def link_groups(pairs: list) -> list:
    """Groups of pair indexes that share a primer, directly or indirectly."""
    owner = {}
    uf = _UnionFind(len(pairs))
    for i, pair in enumerate(pairs):
        for name in (pair["forward_name"], pair["reverse_name"]):
            if name in owner:
                uf.union(owner[name], i)
            else:
                owner[name] = i
    groups = {}
    for i in range(len(pairs)):
        groups.setdefault(uf.find(i), []).append(i)
    return sorted(groups.values(), key=lambda m: m[0])


def _estimate_span(pairs_in_atom: list, resolved: dict) -> int:
    """Length of the core (primers + gaps, no flanks) of these pairs laid
    out together. Exact when the layout can be solved; otherwise a rough
    upper bound just good enough for balancing gBlock sizes."""
    names = []
    for p in pairs_in_atom:
        for n in (p["forward_name"], p["reverse_name"]):
            if n not in names:
                names.append(n)
    tuples = [(p["forward_name"], p["reverse_name"], p["fragment_length"]) for p in pairs_in_atom]
    try:
        order, gaps, _ = layout_solver.solve_layout([resolved[n] for n in names], tuples)
        return sum(len(resolved[n]["sequence"]) for n in order) + sum(gaps)
    except ValueError:
        return sum(
            len(resolved[p["forward_name"]]["sequence"]) + len(resolved[p["reverse_name"]]["sequence"])
            + p["fragment_length"] for p in pairs_in_atom
        )


def _make_atoms(pairs: list, resolved: dict, keep_linked_together: bool) -> list:
    """The indivisible chunks that get assigned to gBlocks."""
    atoms = []
    for link_id, members in enumerate(link_groups(pairs)):
        groups = [members] if keep_linked_together else [[i] for i in members]
        for g in groups:
            ps = [pairs[i] for i in g]
            atoms.append({
                "pair_ids": [p["id"] for p in ps],
                "span": _estimate_span(ps, resolved),
                "link": link_id,
            })
    return atoms


# ------------------------------------------------------------ assignment

def _validate_rules(rules, pair_ids: set) -> list:
    if rules in (None, ""):
        return []
    if not isinstance(rules, list):
        raise ValueError("Rules must be a list.")
    clean = []
    for i, r in enumerate(rules):
        if not isinstance(r, dict):
            raise ValueError(f"Rule {i + 1} is not formatted correctly.")
        kind = str(r.get("type", "")).strip().lower()
        a = str(r.get("a", "")).strip()
        b = str(r.get("b", "")).strip()
        if kind not in ("together", "apart"):
            raise ValueError(f"Rule {i + 1} must be 'together' or 'apart'.")
        if a not in pair_ids or b not in pair_ids:
            raise ValueError(f"Rule {i + 1} refers to a pair that isn't in your CSV.")
        if a == b:
            raise ValueError(f"Rule {i + 1} needs two different pairs.")
        clean.append({"type": kind, "a": a, "b": b})
    return clean


def _assign(atoms: list, rules: list, mode: str, num_blocks, prefer_links: bool = False) -> list:
    """Returns a list of gBlocks, each a sorted list of atom indexes.
    prefer_links: when choosing a gBlock for an atom, favour one that
    already holds an atom sharing a primer with it (only matters when
    linked pairs have been split into separate atoms)."""
    atom_of_pair = {pid: a for a, atom in enumerate(atoms) for pid in atom["pair_ids"]}

    uf = _UnionFind(len(atoms))
    for r in rules:
        if r["type"] == "together":
            uf.union(atom_of_pair[r["a"]], atom_of_pair[r["b"]])

    conflicts = {}   # super-unit root -> set of conflicting roots
    for r in rules:
        if r["type"] != "apart":
            continue
        ua, ub = atom_of_pair[r["a"]], atom_of_pair[r["b"]]
        ra, rb = uf.find(ua), uf.find(ub)
        if ra == rb:
            if ua == ub:
                why = "they share a primer, so they have to stay on the same gBlock"
            else:
                why = "other 'must be on the same gBlock' rules link them together"
            raise ValueError(f"'{r['a']}' and '{r['b']}' can't be kept apart: {why}.")
        conflicts.setdefault(ra, set()).add(rb)
        conflicts.setdefault(rb, set()).add(ra)

    supers = {}
    for u in range(len(atoms)):
        supers.setdefault(uf.find(u), []).append(u)
    roots = list(supers)

    if mode in ("single", "nested"):
        if conflicts:
            a = next(r for r in rules if r["type"] == "apart")
            raise ValueError(
                f"Everything is going on one gBlock, but you've said '{a['a']}' and '{a['b']}' "
                f"can't share one. Use 'Split across gBlocks' instead, or remove the rule."
            )
        return [sorted(range(len(atoms)))]

    # ---- split across exactly N gBlocks
    try:
        k = int(num_blocks)
    except (TypeError, ValueError):
        raise ValueError("Number of gBlocks must be a whole number.")
    if k < 1:
        raise ValueError("Number of gBlocks must be at least 1.")
    n = len(roots)
    if k > n:
        raise ValueError(
            f"You asked for {k} gBlocks, but you only have {n} separable group(s) of pairs "
            f"(pairs you've said must go together count as one)."
        )

    load = {r: sum(atoms[u]["span"] for u in supers[r]) + layout_solver.SEQUENTIAL_GAP * (len(supers[r]) - 1)
            for r in roots}
    links = {r: {atoms[u]["link"] for u in supers[r]} for r in roots}
    order = sorted(roots, key=lambda r: (-load[r], -len(conflicts.get(r, ())), r))

    bins = [[] for _ in range(k)]
    loads = [0] * k
    bin_links = [set() for _ in range(k)]
    nodes = 0

    def feasible(r, b):
        bad = conflicts.get(r)
        return not bad or not any(x in bad for x in bins[b])

    def dfs(i):
        nonlocal nodes
        nodes += 1
        if nodes > MAX_SEARCH_NODES:
            raise _GiveUp()
        if i == n:
            return all(bins)
        if sum(1 for b in bins if not b) > n - i:
            return False
        r = order[i]

        def key(b):
            shares = 0 if (prefer_links and bin_links[b] & links[r]) else 1
            return (shares, loads[b], b)

        tried_empty = False
        for b in sorted((b for b in range(k) if feasible(r, b)), key=key):
            if not bins[b]:
                if tried_empty:
                    continue
                tried_empty = True
            added = links[r] - bin_links[b]
            bins[b].append(r)
            loads[b] += load[r]
            bin_links[b] |= added
            if dfs(i + 1):
                return True
            bins[b].pop()
            loads[b] -= load[r]
            bin_links[b] -= added
        return False

    try:
        found = dfs(0)
    except _GiveUp:
        found = False
    if not found:
        raise ValueError(
            f"Couldn't arrange your pairs into exactly {k} gBlocks while following all your rules. "
            f"Try a different number of gBlocks, or loosen a 'cannot be on the same gBlock' rule."
        )

    blocks = [sorted(u for r in b for u in supers[r]) for b in bins]
    blocks.sort(key=lambda b: b[0])
    return blocks


# ----------------------------------------------------------------- design

def _validate_settings(flank_length, gc_percent):
    try:
        flank_length = int(flank_length)
    except (TypeError, ValueError):
        raise ValueError("Flank length must be a whole number.")
    if flank_length < 0:
        raise ValueError("Flank length cannot be negative.")
    try:
        gc_percent = float(gc_percent)
    except (TypeError, ValueError):
        raise ValueError("GC content must be a number.")
    if not (0 <= gc_percent <= 100):
        raise ValueError("GC content must be between 0 and 100.")
    return flank_length, gc_percent


def _design_block(name: str, pair_ids: list, ctx: dict, attempts: int) -> dict:
    pair_by_id = ctx["pair_by_id"]
    resolved = ctx["resolved"]
    mode = ctx["mode"]

    names = []
    for pid in pair_ids:
        for n in (pair_by_id[pid]["forward_name"], pair_by_id[pid]["reverse_name"]):
            if n not in names:
                names.append(n)

    block = {
        "name": name,
        "pair_ids": list(pair_ids),
        "primer_names": names,
        "primers": [
            {
                "name": n,
                "sequence": resolved[n]["original_sequence"],
                "direction": resolved[n]["direction"],
                "degenerate_substitutions": resolved[n]["degenerate"],
            }
            for n in names
        ],
        "probes": [
            {"pair_id": pid, "sequence": pair_by_id[pid]["probe"]["sequence"]}
            for pid in pair_ids if pair_by_id[pid]["probe"]
        ],
        "error": None,
    }
    try:
        tuples = [(pair_by_id[p]["forward_name"], pair_by_id[p]["reverse_name"],
                   pair_by_id[p]["fragment_length"]) for p in pair_ids]
        order, gaps, gap_sources = layout_solver.solve_layout(
            [resolved[n] for n in names], tuples, allow_nesting=(mode != "single")
        )
        probe_configs = [
            {
                "forward_name": pair_by_id[pid]["forward_name"],
                "reverse_name": pair_by_id[pid]["reverse_name"],
                "probe_sequence": pair_by_id[pid]["probe"]["sequence"],
                "start_position": pair_by_id[pid]["probe"]["start"],
                "flexible": True,
            }
            for pid in pair_ids if pair_by_id[pid]["probe"]
        ]
        result = refine.find_clean_design(
            [resolved[n] for n in order], gaps, ctx["gc_percent"], ctx["flank_length"],
            max_attempts=attempts, gap_sources=gap_sources,
            probe_config=probe_configs or None,
        )
        design = result["design"]
        block.update({
            "sequence": design["sequence"],
            "length": design["length"],
            "overall_gc_percent": design["overall_gc_percent"],
            "segments": design["segments"],
            "flank_length_note": design.get("flank_length_note"),
            "flagged": [c["label"] for c in result["complexity"]["checks"] if c["flagged"]],
            "attempts": result["attempts"],
            "degenerate_info": {n: resolved[n]["degenerate"] for n in names if resolved[n]["degenerate"]},
        })
    except ValueError as exc:
        block["error"] = str(exc)
        if mode != "split" and "3000" in block["error"]:
            block["error"] += " Try 'Split across gBlocks' instead, to divide the pairs over several gBlocks."
    return block


def _prepare(text: str, mode, flank_length, gc_percent) -> dict:
    mode = str(mode or "").strip().lower()
    if mode not in ("single", "nested", "split"):
        raise ValueError("Choose a layout: single, nested, or split.")
    flank_length, gc_percent = _validate_settings(flank_length, gc_percent)
    parsed = parse_csv(text)
    return {
        "mode": mode,
        "flank_length": flank_length,
        "gc_percent": gc_percent,
        "pairs": parsed["pairs"],
        "pair_by_id": {p["id"]: p for p in parsed["pairs"]},
        "resolved": _resolve_primers(parsed["primers"]),
    }


def design_bulk(text: str, mode: str, num_blocks=None, rules=None, flank_length=30,
                gc_percent=50, avoid_flags=True) -> dict:
    ctx = _prepare(text, mode, flank_length, gc_percent)
    pairs, resolved = ctx["pairs"], ctx["resolved"]
    clean_rules = _validate_rules(rules, set(ctx["pair_by_id"]))

    # Prefer keeping pairs that share a primer together; only separate them
    # if the rules (or the number of gBlocks asked for) leave no other way.
    atoms = _make_atoms(pairs, resolved, keep_linked_together=True)
    try:
        assignment = _assign(atoms, clean_rules, ctx["mode"], num_blocks)
    except ValueError:
        if ctx["mode"] != "split":
            raise
        atoms = _make_atoms(pairs, resolved, keep_linked_together=False)
        assignment = _assign(atoms, clean_rules, ctx["mode"], num_blocks, prefer_links=True)

    attempts = INITIAL_ATTEMPTS if avoid_flags else 1
    blocks = []
    for number, atom_indexes in enumerate(assignment, start=1):
        pair_ids = [pid for a in atom_indexes for pid in atoms[a]["pair_ids"]]
        blocks.append(_design_block(f"gBlock_{number}", pair_ids, ctx, attempts))

    # Say so plainly whenever a primer ended up on more than one gBlock.
    notes = list(refine.diagnose_structural_limits(ctx["gc_percent"]))
    homes = {}
    for b in blocks:
        for n in b["primer_names"]:
            homes.setdefault(n, []).append(b["name"])
    for n, where in homes.items():
        if len(where) > 1:
            notes.append(
                f"Primer {n} is used on more than one gBlock ({', '.join(where)}) because the pairs "
                f"that share it had to be placed apart."
            )

    return {"mode": ctx["mode"], "blocks": blocks, "notes": notes, "pair_count": len(pairs)}


def redesign_block(text: str, mode: str, name: str, pair_ids: list, flank_length=30, gc_percent=50) -> dict:
    """Re-rolls one gBlock's random sections (more attempts than the first
    pass), keeping exactly the same pairs on it."""
    ctx = _prepare(text, mode, flank_length, gc_percent)
    if not isinstance(pair_ids, list) or not pair_ids or any(p not in ctx["pair_by_id"] for p in pair_ids):
        raise ValueError("That gBlock refers to pairs that aren't in your CSV.")
    return _design_block(str(name), pair_ids, ctx, refine.DEFAULT_MAX_ATTEMPTS)
