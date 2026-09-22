let currentDesign = null;

const $ = (id) => document.getElementById(id);

function show(el) { el.classList.remove("hidden"); }
function hide(el) { el.classList.add("hidden"); }

function resetApp() {
  if (confirm("Reset the page? This clears everything you've entered and any results.")) {
    window.location.reload();
  }
}
$("reset-top").addEventListener("click", resetApp);
$("reset-bottom").addEventListener("click", resetApp);

function escapeHtml(str) {
  return String(str).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

// ---------- Primer rows (add/remove, dynamic) ----------

const ALLOWED_BASES = new Set(["A", "C", "G", "T", "R", "Y", "S", "W", "K", "M", "B", "D", "H", "V", "N"]);

// Filters a primer sequence input down to valid IUPAC characters as you
// type, so it's not possible to enter anything else - rather than letting
// something invalid through and only catching it later.
function sanitizePrimerInput(el) {
  const cursorPos = el.selectionStart;
  const original = el.value;
  const upper = original.toUpperCase();
  let filtered = "";
  let removedBeforeCursor = 0;
  for (let i = 0; i < upper.length; i++) {
    if (ALLOWED_BASES.has(upper[i])) {
      filtered += upper[i];
    } else if (i < cursorPos) {
      removedBeforeCursor++;
    }
  }
  if (filtered !== original) {
    el.value = filtered;
    const newPos = Math.max(0, cursorPos - removedBeforeCursor);
    el.setSelectionRange(newPos, newPos);
  }
}

let primerUidCounter = 0;

function addPrimerRow(defaultDirection = "forward", defaultName = "") {
  const container = $("primer-rows");
  const uid = `p${++primerUidCounter}`;
  const row = document.createElement("div");
  row.className = "primer-row";
  row.dataset.uid = uid;
  row.innerHTML = `
    <input type="text" class="primer-name" placeholder="Name (e.g. F1)" required>
    <select class="primer-direction">
      <option value="forward">Forward</option>
      <option value="reverse">Reverse</option>
    </select>
    <input type="text" class="primer-sequence" placeholder="Primer sequence (5'&rarr;3'). ACGT + IUPAC codes only" required>
    <button type="button" class="remove-primer-row" title="Remove this primer">&times;</button>
  `;
  row.querySelector(".primer-direction").value = defaultDirection;
  row.querySelector(".primer-name").value = defaultName;
  row.querySelector(".primer-direction").addEventListener("change", () => { refreshPairPrimerOptions(); resetDegenerateState(); });
  row.querySelector(".primer-name").addEventListener("input", refreshPairPrimerOptions);
  row.querySelector(".primer-sequence").addEventListener("input", (e) => { sanitizePrimerInput(e.target); resetDegenerateState(); });
  row.querySelector(".remove-primer-row").addEventListener("click", () => {
    if (document.querySelectorAll(".primer-row").length <= 1) return; // always keep at least one
    row.remove();
    refreshPairPrimerOptions();
    resetDegenerateState();
  });
  container.appendChild(row);
  refreshPairPrimerOptions();
}

$("add-primer-row").addEventListener("click", () => addPrimerRow("forward"));

function collectPrimers() {
  return Array.from(document.querySelectorAll(".primer-row")).map((row) => ({
    uid: row.dataset.uid,
    name: row.querySelector(".primer-name").value.trim(),
    sequence: row.querySelector(".primer-sequence").value.trim(),
    direction: row.querySelector(".primer-direction").value,
  }));
}

// ---------- Primer pair rows ----------

let pairUidCounter = 0;

function addPairRow(forwardUid = "", reverseUid = "", fragmentLength = "") {
  const container = $("pair-rows");
  const uid = `pair${++pairUidCounter}`;
  const row = document.createElement("div");
  row.className = "pair-row";
  row.dataset.uid = uid;
  row.innerHTML = `
    <select class="pair-forward"></select>
    <span class="pair-and">&amp;</span>
    <select class="pair-reverse"></select>
    <input type="number" class="pair-fragment-length" min="1" placeholder="Fragment length, bp" required>
    <button type="button" class="remove-pair-row" title="Remove this pair">&times;</button>
  `;
  row.querySelector(".pair-fragment-length").value = fragmentLength;
  row.querySelector(".remove-pair-row").addEventListener("click", () => {
    if (document.querySelectorAll(".pair-row").length <= 1) return; // always keep at least one pair
    row.remove();
  });
  container.appendChild(row);
  refreshPairPrimerOptions();
  if (forwardUid) row.querySelector(".pair-forward").value = forwardUid;
  if (reverseUid) row.querySelector(".pair-reverse").value = reverseUid;
}

$("add-pair-row").addEventListener("click", () => addPairRow());

function refreshPairPrimerOptions() {
  const primers = collectPrimers();
  const forwardOptions = primers.filter((p) => p.direction === "forward");
  const reverseOptions = primers.filter((p) => p.direction === "reverse");

  document.querySelectorAll(".pair-row").forEach((row) => {
    const fwdSelect = row.querySelector(".pair-forward");
    const revSelect = row.querySelector(".pair-reverse");
    const prevFwd = fwdSelect.value;
    const prevRev = revSelect.value;

    fwdSelect.innerHTML = '<option value="">Select forward primer...</option>' +
      forwardOptions.map((p) => `<option value="${p.uid}">${escapeHtml(p.name || "(unnamed)")}</option>`).join("");
    revSelect.innerHTML = '<option value="">Select reverse primer...</option>' +
      reverseOptions.map((p) => `<option value="${p.uid}">${escapeHtml(p.name || "(unnamed)")}</option>`).join("");

    if (forwardOptions.some((p) => p.uid === prevFwd)) fwdSelect.value = prevFwd;
    if (reverseOptions.some((p) => p.uid === prevRev)) revSelect.value = prevRev;
  });
}

function collectPairs() {
  const primersByUid = Object.fromEntries(collectPrimers().map((p) => [p.uid, p]));
  return Array.from(document.querySelectorAll(".pair-row")).map((row) => {
    const fwdUid = row.querySelector(".pair-forward").value;
    const revUid = row.querySelector(".pair-reverse").value;
    return {
      forward_name: primersByUid[fwdUid] ? primersByUid[fwdUid].name : "",
      reverse_name: primersByUid[revUid] ? primersByUid[revUid].name : "",
      fragment_length: row.querySelector(".pair-fragment-length").value,
    };
  });
}

// Start with the simplest common case: one forward + one reverse primer, one pair.
addPrimerRow("forward", "F1");
addPrimerRow("reverse", "R1");
addPairRow();

// ---------- Target-sequence GC mode ----------

$("use_target_sequence").addEventListener("change", (e) => {
  if (e.target.checked) {
    hide($("manual-gc-field"));
    show($("target-sequence-field"));
  } else {
    show($("manual-gc-field"));
    hide($("target-sequence-field"));
  }
});

$("target_sequence").addEventListener("input", () => {
  const cleaned = $("target_sequence").value.trim().toUpperCase().replace(/[^ACGT]/g, "");
  const preview = $("target-gc-preview");
  if (!cleaned.length) {
    preview.textContent = "";
    return;
  }
  const gcCount = (cleaned.match(/[GC]/g) || []).length;
  const pct = Math.round((gcCount / cleaned.length) * 10000) / 100;
  preview.textContent = `Detected GC content: ${pct}% (this will be used as the target automatically)`;
});

// ---------- Degenerate base handling ----------

let confirmedDegenerateSubstitutions = null; // null = not yet resolved for the current primer set

function resetDegenerateState() {
  confirmedDegenerateSubstitutions = null;
  hide($("degenerate-panel"));
}

$("auto_substitute_degenerate").addEventListener("change", resetDegenerateState);

function renderDegeneratePanel(occurrences) {
  $("degenerate-rows").innerHTML = occurrences.map((occ) => {
    const options = occ.allowed_bases.map((b) =>
      `<option value="${b}" ${b === occ.suggested_base ? "selected" : ""}>${b}</option>`).join("");
    return `
      <div class="degenerate-row" data-primer-name="${escapeHtml(occ.primer_name)}" data-position="${occ.position}">
        <span class="degenerate-info">
          <strong>${escapeHtml(occ.primer_name)}</strong>, position ${occ.position + 1} (5'&rarr;3'):
          <code>${escapeHtml(occ.code)}</code> (${occ.allowed_bases.join("/")})
        </span>
        <select class="degenerate-choice">${options}</select>
      </div>`;
  }).join("");
}

$("confirm-degenerate").addEventListener("click", async () => {
  confirmedDegenerateSubstitutions = Array.from(document.querySelectorAll(".degenerate-row")).map((row) => ({
    primer_name: row.dataset.primerName,
    position: parseInt(row.dataset.position, 10),
    chosen_base: row.querySelector(".degenerate-choice").value,
  }));
  hide($("degenerate-panel"));
  await submitDesign("/api/design");
});

/** Returns true if it's safe to proceed straight to designing; false if it
 * instead had to show the degenerate-substitution panel and stop, waiting
 * for you to confirm your choices. */
async function ensureDegenerateChoicesReady() {
  if ($("auto_substitute_degenerate").checked || confirmedDegenerateSubstitutions !== null) {
    return true;
  }
  const res = await fetch("/api/degenerate-scan", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ primers: collectPrimers() }),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || "Could not scan primers for degenerate bases");

  if (!data.any_degenerate) {
    confirmedDegenerateSubstitutions = [];
    return true;
  }
  renderDegeneratePanel(data.occurrences);
  show($("degenerate-panel"));
  return false;
}

// ---------- Step 1: Design ----------

function buildDesignPayload() {
  const payload = {
    primers: collectPrimers().map(({ name, sequence, direction }) => ({ name, sequence, direction })),
    pairs: collectPairs(),
    flank_length: $("flank_length").value,
    auto_substitute_degenerate: $("auto_substitute_degenerate").checked,
  };
  if (!payload.auto_substitute_degenerate && confirmedDegenerateSubstitutions) {
    payload.degenerate_substitutions = confirmedDegenerateSubstitutions;
  }
  if ($("use_target_sequence").checked) {
    payload.target_sequence = $("target_sequence").value.trim();
  } else {
    payload.gc_percent = $("gc_percent").value;
  }
  return payload;
}

$("design-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const btn = e.target.querySelector("button[type=submit]");
  btn.disabled = true;
  btn.textContent = "Designing...";
  try {
    const ready = await ensureDegenerateChoicesReady();
    if (ready) await submitDesign("/api/design");
  } catch (err) {
    $("design-result").innerHTML = `<span class="badge error">Error</span> ${escapeHtml(err.message)}`;
    show($("design-result"));
  } finally {
    btn.disabled = false;
    btn.textContent = "Design gBlock";
  }
});

let activeBlastPollInterval = null;

function cancelActiveBlastPoll() {
  if (activeBlastPollInterval) {
    clearInterval(activeBlastPollInterval);
    activeBlastPollInterval = null;
  }
}

async function submitDesign(endpoint) {
  try {
    const res = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(buildDesignPayload()),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Design failed");

    const isFreshDesign = !endpoint.endsWith("/fix");
    currentDesign = isFreshDesign ? data : data.design;
    renderDesign(currentDesign);
    show($("design-result"));
    show($("alignment-panel"));
    show($("blast-panel"));
    show($("idt-panel"));

    // Any previous results downstream of this one no longer apply to the
    // (possibly new) sequence - clear them out rather than leaving stale
    // results on screen next to a design they no longer describe.
    cancelActiveBlastPoll();
    hide($("alignment-result"));
    $("alignment-result").innerHTML = "";
    hide($("blast-result"));
    $("blast-result").innerHTML = "";
    if (isFreshDesign) {
      hide($("complexity-result"));
      $("complexity-result").innerHTML = "";
      hide($("fix-issues"));
      hide($("fix-status"));
      $("fix-status").innerHTML = "";
    }

    return data;
  } catch (err) {
    $("design-result").innerHTML = `<span class="badge error">Error</span> ${escapeHtml(err.message)}`;
    show($("design-result"));
    return null;
  }
}

function renderDesign(data) {
  const rows = data.segments.map((s) => {
    const tag = s.type === "primer" ? ` <span class="tag tag-${s.direction}">${s.direction}</span>` : "";
    return `<tr>
      <td>${escapeHtml(s.label)}${tag}</td>
      <td>${s.length} bp</td>
      <td><code>${escapeHtml(s.seq)}</code></td>
    </tr>`;
  }).join("");

  const gcSourceNote = data.gc_percent_source === "target_sequence"
    ? " (auto-detected from your target sequence)"
    : "";

  $("design-result").innerHTML = `
    <div><span class="badge ok">Designed</span> ${data.length} bp total &middot; overall GC ${data.overall_gc_percent}% (target ${data.target_gc_percent}%${gcSourceNote})</div>
    <div class="seq-block">${escapeHtml(data.sequence)}</div>
    ${renderDiagram(data.segments)}
    <table class="segment-table">
      <colgroup><col style="width:22%"><col style="width:14%"><col style="width:64%"></colgroup>
      <tr><th>Segment</th><th>Length</th><th>Sequence</th></tr>
      ${rows}
    </table>
  `;
}

function renderDiagram(segments) {
  const chips = segments.map((s) => {
    if (s.type === "flank") return `<span class="diagram-chip diagram-flank">Flanking (${s.length}bp)</span>`;
    if (s.type === "primer") return `<span class="diagram-chip diagram-primer diagram-${s.direction}">${escapeHtml(s.label)}</span>`;
    return `<span class="diagram-chip diagram-gap">${s.length}</span>`;
  });
  return `<div class="diagram-row">${chips.join('<span class="diagram-sep">|</span>')}</div>`;
}

// ---------- Step 2: Alignment ----------

$("run-alignment").addEventListener("click", async () => {
  if (!currentDesign) return;
  const btn = $("run-alignment");
  btn.disabled = true;
  btn.textContent = "Aligning...";

  try {
    const res = await fetch("/api/align", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        primers: collectPrimers().map((p) => ({
          name: p.name,
          sequence: p.sequence,
          direction: p.direction,
          degenerate_substitutions: (currentDesign.degenerate_info || {})[p.name] || [],
        })),
        sequence: currentDesign.sequence,
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Alignment failed");
    renderAlignment(data);
    show($("alignment-result"));
  } catch (err) {
    $("alignment-result").innerHTML = `<span class="badge error">Error</span> ${escapeHtml(err.message)}`;
    show($("alignment-result"));
  } finally {
    btn.disabled = false;
    btn.textContent = "Align primers to designed sequence";
  }
});

// Fixed-width labels so "Sequence" and "Primer" line up, and the match-bar
// line sits directly under the right spot regardless of which label it is.
const ALIGN_LABEL_WIDTH = "Sequence".length;

function padLabel(label) {
  return label + " ".repeat(Math.max(0, ALIGN_LABEL_WIDTH - label.length));
}

function renderAlignment(results) {
  const prefixSpaces = " ".repeat(ALIGN_LABEL_WIDTH + "  5'-".length);

  const blocks = results.map((r) => {
    if (r.error) {
      return `<div class="hit-row"><strong>${escapeHtml(r.primer_label)}</strong><div class="status-line">${escapeHtml(r.error)}</div></div>`;
    }

    const statusBadge = r.full_length_match
      ? '<span class="badge ok">Exact match</span>'
      : `<span class="badge warn">${r.mismatches} mismatch(es)</span>`;

    const seqLine = `<span class="align-label">${padLabel("Sequence")}</span>  5'-<span class="align-target-text">${escapeHtml(r.target_region)}</span>-3'  <span class="align-position">(positions ${r.start}&ndash;${r.end})</span>`;
    const barLine = `${prefixSpaces}<span class="align-bar-text">${escapeHtml(r.match_line)}</span>`;
    const primerLine = `<span class="align-label">${padLabel("Primer")}</span>  5'-<span class="align-primer-text">${escapeHtml(r.primer)}</span>-3'`;

    const substitutionNotes = (r.substitution_notes && r.substitution_notes.length)
      ? `<div class="degeneracy-note">${r.substitution_notes.map(escapeHtml).join("<br>")}</div>`
      : "";

    const secondaryWarning = (r.secondary_matches && r.secondary_matches.length)
      ? `<div class="secondary-match-warning">
          <strong>&#9888; Possible off-target binding:</strong> this primer could also plausibly bind elsewhere in the gBlock, not just where it's meant to:
          <ul class="detail-list">${r.secondary_matches.map((m) =>
            `<li>Position ${m.start}&ndash;${m.end}: ${m.percent_identity}% identity (${m.mismatches} mismatch${m.mismatches === 1 ? "" : "es"})</li>`).join("")}</ul>
        </div>`
      : "";

    return `
      <div class="hit-row">
        <strong>${escapeHtml(r.primer_label)}</strong>
        <span class="tag tag-${r.direction}">${r.direction}</span>
        ${statusBadge}
        <div class="status-line">${r.percent_identity}% identity${r.primer_direction_note ? " &mdash; " + escapeHtml(r.primer_direction_note) : ""}</div>
        <pre class="align-block">${seqLine}
${barLine}
${primerLine}</pre>
        ${substitutionNotes}
        ${secondaryWarning}
      </div>`;
  }).join("");

  $("alignment-result").innerHTML = blocks;
}

// ---------- Step 3: BLAST ----------

$("run-blast").addEventListener("click", async () => {
  if (!currentDesign) return;
  const btn = $("run-blast");
  btn.disabled = true;
  btn.textContent = "Submitting to NCBI...";
  $("blast-result").innerHTML = `<div class="status-line">Submitted. Waiting on NCBI (this can take a while)...</div>`;
  show($("blast-result"));

  try {
    const startRes = await fetch("/api/blast/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sequence: currentDesign.sequence }),
    });
    const startData = await startRes.json();
    if (!startRes.ok) throw new Error(startData.error || "Could not start BLAST job");

    btn.textContent = "Running...";
    await pollBlast(startData.job_id);
  } catch (err) {
    $("blast-result").innerHTML = `<span class="badge error">Error</span> ${escapeHtml(err.message)}`;
  } finally {
    btn.disabled = false;
    btn.textContent = "Run BLAST";
  }
});

function pollBlast(jobId) {
  return new Promise((resolve, reject) => {
    const interval = setInterval(async () => {
      try {
        const res = await fetch(`/api/blast/status/${jobId}`);
        const job = await res.json();
        if (!res.ok) throw new Error(job.error || "Job lookup failed");

        if (job.status === "done") {
          clearInterval(interval);
          activeBlastPollInterval = null;
          renderBlast(job);
          resolve();
        } else if (job.status === "error") {
          clearInterval(interval);
          activeBlastPollInterval = null;
          $("blast-result").innerHTML = `<span class="badge error">BLAST error</span> ${escapeHtml(job.error)}`;
          resolve();
        } else {
          const statusLabels = {
            queued: "Queued...",
            waiting_for_slot: "Waiting for a free BLAST slot (this app limits how many searches run at once, to stay in NCBI's good graces)...",
            running: "Running on NCBI's servers...",
          };
          $("blast-result").innerHTML = `<div class="status-line">${statusLabels[job.status] || `Status: ${job.status}...`}</div>`;
        }
      } catch (err) {
        clearInterval(interval);
        activeBlastPollInterval = null;
        reject(err);
      }
    }, 4000);
    activeBlastPollInterval = interval;
  });
}

function renderBlast(job) {
  if (job.no_significant_hits) {
    $("blast-result").innerHTML = `<span class="badge ok">No significant hits</span> Your designed sequence does not appear to match any existing known sequence in NCBI's database.`;
    return;
  }
  const rows = job.hits.map((h) => `
    <div class="hit-row">
      <strong>${escapeHtml(h.title)}</strong>
      <div class="status-line">
        Accession ${escapeHtml(h.accession)} &middot; E-value ${h.e_value} &middot;
        ${h.percent_identity}% identity &middot; ${h.query_coverage_percent}% query coverage
        (query bases ${h.query_start}-${h.query_end})
      </div>
    </div>`).join("");
  const countLabel = job.total_hits_found > job.hits.length
    ? `${job.total_hits_found} hit(s) found &mdash; showing top ${job.hits.length}`
    : `${job.total_hits_found} hit(s) found`;
  $("blast-result").innerHTML = `<span class="badge warn">${countLabel}</span>${rows}`;
}

// ---------- Step 4: Local complexity check ----------

$("run-complexity").addEventListener("click", async () => {
  if (!currentDesign) return;
  const btn = $("run-complexity");
  btn.disabled = true;
  btn.textContent = "Checking...";

  try {
    const res = await fetch("/api/complexity-check", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sequence: currentDesign.sequence }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Check failed");
    renderComplexity(data);
    show($("complexity-result"));
  } catch (err) {
    $("complexity-result").innerHTML = `<span class="badge error">Error</span> ${escapeHtml(err.message)}`;
    show($("complexity-result"));
  } finally {
    btn.disabled = false;
    btn.textContent = "Run complexity check";
  }
});

function renderComplexity(data) {
  const overallBadge = data.any_flagged
    ? '<span class="badge warn">Some things worth a look</span>'
    : '<span class="badge ok">Nothing flagged</span>';

  const items = data.checks.map((c) => {
    const badge = c.flagged ? '<span class="badge warn">Flagged</span>' : '<span class="badge ok">OK</span>';
    let details = "";

    if (c.check === "gc_windows" && c.windows && c.windows.length) {
      details = "<ul class='detail-list'>" + c.windows.map((w) =>
        `<li>Bases ${w.start}&ndash;${w.end}: ${w.gc_percent}% GC</li>`).join("") + "</ul>";
    } else if (c.check === "homopolymers" && c.runs && c.runs.length) {
      details = "<ul class='detail-list'>" + c.runs.map((r) =>
        `<li>Bases ${r.start}&ndash;${r.end}: "${escapeHtml(r.base)}" repeated ${r.length} times in a row</li>`).join("") + "</ul>";
    } else if (c.check === "repeats" && c.repeats && c.repeats.length) {
      details = "<ul class='detail-list'>" + c.repeats.slice(0, 8).map((r) =>
        `<li>Chunk at position ${r.first_seen_at} repeats again at position ${r.repeated_at}: <code>${escapeHtml(r.chunk)}</code></li>`).join("")
        + (c.total_repeat_hits > 8 ? `<li>...and ${c.total_repeat_hits - 8} more</li>` : "") + "</ul>";
    } else if (c.check === "hairpins" && c.hairpins && c.hairpins.length) {
      details = "<ul class='detail-list'>" + c.hairpins.map((h) =>
        `<li>Bases ${h.stem_start}&ndash;${h.stem_end} could fold back and pair with bases ${h.partner_start}&ndash;${h.partner_end} (a ${h.loop_length}-base loop in between)</li>`).join("") + "</ul>";
    }

    return `<div class="check-item">${badge} <strong>${escapeHtml(c.label)}</strong>
      <div class="status-line">${escapeHtml(c.message)}</div>
      ${details}</div>`;
  }).join("");

  $("complexity-result").innerHTML = `${overallBadge}${items}`;

  const fixBtn = $("fix-issues");
  if (data.any_flagged) {
    show(fixBtn);
  } else {
    hide(fixBtn);
    hide($("fix-status"));
  }
}

// ---------- "Fix issues" ----------

$("fix-issues").addEventListener("click", async () => {
  const btn = $("fix-issues");
  btn.disabled = true;
  btn.textContent = "Trying...";
  $("fix-status").textContent = "Re-rolling the random parts of the sequence and re-checking...";
  show($("fix-status"));

  try {
    const ready = await ensureDegenerateChoicesReady();
    if (!ready) {
      $("fix-status").textContent = "Choose your degenerate base substitutions above, then try again.";
      return;
    }
    const data = await submitDesign("/api/design/fix");
    if (!data) {
      $("fix-status").textContent = "Could not fix the design - see the error above.";
      return;
    }

    renderComplexity(data.complexity);

    const notesHtml = (data.structural_notes && data.structural_notes.length)
      ? `<div class="reminder-box">${data.structural_notes.map(escapeHtml).join("<br><br>")}</div>`
      : "";

    const outcomeLine = data.fully_resolved
      ? `Fixed after ${data.attempts} attempt(s) \u2014 nothing flagged now.`
      : `Tried ${data.attempts} time(s) and kept the best result, but some issues remain \u2014 see above.`;

    $("fix-status").innerHTML = `${escapeHtml(outcomeLine)}${notesHtml}`;
  } catch (err) {
    $("fix-status").textContent = `Error: ${err.message}`;
  } finally {
    btn.disabled = false;
    btn.textContent = "Try to fix flagged issues";
  }
});
