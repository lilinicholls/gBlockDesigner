"""
Works out the entire layout of a gBlock automatically from named primer
pairs and their fragment lengths - including deciding, on its own, whether
independent groups of primers should be nested inside each other or placed
one after another.

THE BASIC MATHS (primers that share a pair)
---------------------------------------------
A pair's fragment length means the sequence strictly between that pair's
own forward and reverse primers - not including those two primers' own
length, but including any OTHER primer that happens to sit between them.
If two pairs share a primer (e.g. two forward primers sharing one
downstream reverse primer), their fragment lengths pin down each other's
relative position exactly - there's only one arrangement the numbers can
mean, and this module works that out directly rather than trusting the
order you happened to list your primers in.

DECIDING WHETHER TO NEST (primers that share NO pair)
---------------------------------------------------------
If two groups of primers share no primer at all - e.g. a completely
separate pair - there's no equation linking them, so nothing in the maths
says how they should relate to each other. Two honest options exist:

    1. Nest one group inside a gap of the other (if it physically fits,
       with at least MIN_NEST_GAP on either side of it).
    2. Place them one after another, separated by a fixed SEQUENTIAL_GAP.

This module checks, for every such independent group, whether it can
physically fit inside any gap of any other group (largest groups placed
first, smallest gap that still fits preferred, so bigger gaps stay
available for anything bigger that still needs a home). If it fits, it
nests it there. If nothing fits anywhere, it's placed alongside the other
groups with a fixed gap between them.
"""

MIN_NEST_GAP = 5      # minimum bp required on each side of a nested group
SEQUENTIAL_GAP = 30   # fixed gap used between groups that can't be nested


class _WeightedUnionFind:
    """Standard weighted/offset union-find: tracks, for each node, its value
    relative to its component's root, so we can merge components that are
    known to differ by a fixed amount (here, a fixed number of base pairs)."""

    def __init__(self, n):
        self.parent = list(range(n))
        self.offset = [0.0] * n  # value(i) - value(parent[i]), pre-compression

    def find(self, x):
        if self.parent[x] != x:
            root = self.find(self.parent[x])
            self.offset[x] += self.offset[self.parent[x]]
            self.parent[x] = root
        return self.parent[x]

    def union(self, a, b, diff):
        """Records that value(b) - value(a) == diff. Raises ValueError if
        this contradicts something already known."""
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            implied_diff = self.offset[b] - self.offset[a]
            if abs(implied_diff - diff) > 1e-6:
                raise ValueError(
                    "Two of your primer pairs give conflicting fragment "
                    "lengths for primers that overlap or share a primer - "
                    "double check the fragment lengths you entered."
                )
            return
        self.parent[ra] = rb
        self.offset[ra] = self.offset[b] - self.offset[a] - diff


def _solve_components(primer_names: list, primer_lengths: dict, pairs: list) -> list:
    """Groups primers into connected components (primers linked, directly
    or indirectly, by sharing a pair), and fully solves each component's
    own internal left-to-right order and gap lengths - which is always
    possible with zero ambiguity for primers that share a pair with each
    other.

    Returns a list of blocks: {"primer_order": [names...], "gaps": [ints...]}
    """
    n = len(primer_names)
    index_of = {name: i for i, name in enumerate(primer_names)}

    uf = _WeightedUnionFind(n)
    for fwd_name, rev_name, fragment_length in pairs:
        a, b = index_of[fwd_name], index_of[rev_name]
        # S_b - S_a = fragment_length + len(forward primer) - derived from
        # fragment_length = S_b - (S_a + len(a)).
        diff = fragment_length + primer_lengths[fwd_name]
        uf.union(a, b, diff)

    for i in range(n):
        uf.find(i)  # path-compress so uf.offset[i] is root-relative

    groups = {}
    for i in range(n):
        groups.setdefault(uf.find(i), []).append(i)

    blocks = []
    for members in groups.values():
        members_sorted = sorted(members, key=lambda i: uf.offset[i])
        primer_order = [primer_names[i] for i in members_sorted]
        gaps = []
        for k in range(len(members_sorted) - 1):
            cur, nxt = members_sorted[k], members_sorted[k + 1]
            gap = round(uf.offset[nxt] - uf.offset[cur]) - primer_lengths[primer_order[k]]
            if gap < 0:
                raise ValueError(
                    "Some of your fragment lengths are geometrically impossible "
                    "for the primers involved - double check them against your "
                    "primer sizes and against each other."
                )
            gaps.append(gap)
        blocks.append({"primer_order": primer_order, "gaps": gaps})

    return blocks


def _block_span(block: dict, primer_lengths: dict) -> int:
    return sum(primer_lengths[n] for n in block["primer_order"]) + sum(block["gaps"])


def solve_layout(primers: list, pairs: list) -> tuple:
    """
    primers: list of {"name": str, "sequence": str, "direction": "forward"|"reverse"}
    pairs: list of (forward_name, reverse_name, fragment_length) tuples

    Returns (primer_order, gaps, gap_sources):
        primer_order: primer names, left to right, in the arrangement this
            function decided on.
        gaps: gap length in bp before each subsequent primer (length =
            len(primer_order) - 1).
        gap_sources: parallel list of strings describing how each gap was
            decided - "computed" (pinned down exactly by fragment lengths),
            "nested" (a group was fitted inside another, with any leftover
            space split evenly on both sides, min 5bp each), or
            "sequential" (two groups couldn't be nested, so a fixed 30bp
            gap was used).
    """
    primer_lengths = {p["name"]: len(p["sequence"]) for p in primers}
    primer_names = [p["name"] for p in primers]

    blocks = _solve_components(primer_names, primer_lengths, pairs)
    # Track the source of every gap by tagging each block's own gap list
    # with parallel labels, so labels move together whenever we splice.
    for block in blocks:
        block["gap_sources"] = ["computed"] * len(block["gaps"])

    # Largest blocks first, so smaller ones get a chance to nest into them;
    # smallest-sufficient-gap preferred at each step (see _try_nest).
    blocks.sort(key=lambda b: -_block_span(b, primer_lengths))

    top_level = []
    for block in blocks:
        placed = False
        for host in top_level:
            guest_span = _block_span(block, primer_lengths)
            needed = guest_span + 2 * MIN_NEST_GAP
            candidates = [(i, g) for i, g in enumerate(host["gaps"]) if g >= needed]
            if not candidates:
                continue
            idx, gap_len = min(candidates, key=lambda pair: pair[1])
            leftover = gap_len - guest_span
            leading = leftover // 2
            trailing = leftover - leading

            insertion_point = idx + 1
            host["primer_order"][insertion_point:insertion_point] = block["primer_order"]
            host["gaps"][idx:idx + 1] = [leading] + block["gaps"] + [trailing]
            host["gap_sources"][idx:idx + 1] = ["nested"] + block["gap_sources"] + ["nested"]
            placed = True
            break
        if not placed:
            top_level.append(block)

    final_primer_order = []
    final_gaps = []
    final_gap_sources = []
    for i, block in enumerate(top_level):
        final_primer_order.extend(block["primer_order"])
        final_gaps.extend(block["gaps"])
        final_gap_sources.extend(block["gap_sources"])
        if i < len(top_level) - 1:
            final_gaps.append(SEQUENTIAL_GAP)
            final_gap_sources.append("sequential")

    return final_primer_order, final_gaps, final_gap_sources
