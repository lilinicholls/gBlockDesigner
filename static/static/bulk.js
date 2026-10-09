// Bulk design (CSV upload). Loaded after script.js, which provides the
// shared helpers $, show, hide, escapeHtml and renderDiagram.
(function () {
  let csvText = null;
  let parsedPairs = [];
  let lastResult = null;
  let lastSettings = null;

  // ---------- Single / Bulk tabs ----------

  function setTab(which) {
    const bulk = which === "bulk";
    $("single-mode").classList.toggle("hidden", bulk);
    $("bulk-mode").classList.toggle("hidden", !bulk);
    $("tab-single").classList.toggle("active", !bulk);
    $("tab-bulk").classList.toggle("active", bulk);
    $("tab-single").setAttribute("aria-selected", String(!bulk));
    $("tab-bulk").setAttribute("aria-selected", String(bulk));
  }
  $("tab-single").addEventListener("click", () => setTab("single"));
  $("tab-bulk").addEventListener("click", () => setTab("bulk"));

  // ---------- Upload + parse ----------

  function showParseStatus(html, isError) {
    const el = $("bulk-parse-status");
    el.innerHTML = html;
    el.classList.toggle("status-error", !!isError);
    show(el);
  }

  function resetBulkState() {
    csvText = null;
    parsedPairs = [];
    lastResult = null;
    hide($("bulk-options"));
    hide($("bulk-result"));
    $("bulk-rules").innerHTML = "";
  }

  $("bulk-file").addEventListener("change", async (e) => {
    resetBulkState();
    const file = e.target.files[0];
    if (!file) { hide($("bulk-parse-status")); return; }
    if (file.size > 1000000) {
      showParseStatus('<span class="badge error">Error</span> That file is too large (limit is about 1 MB).', true);
      return;
    }
    showParseStatus("Reading your file...", false);
    try {
      const text = await file.text();
      const res = await fetch("/api/bulk/parse", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ csv: text }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Could not read that file");
      csvText = text;
      parsedPairs = data.pairs;
      renderParsed(data);
      hide($("bulk-parse-status"));
    } catch (err) {
      const lines = String(err.message).split("\n").map(escapeHtml).join("<br>");
      showParseStatus(`<span class="badge error">Error</span> ${lines}`, true);
    }
  });

  function renderParsed(data) {
    const linked = data.linked_groups.length
      ? `<br>These pairs share a primer: ${data.linked_groups.map((g) => escapeHtml(g.join(" + "))).join("; ")}. ` +
        `They're kept on the same gBlock whenever your rules allow it; if a rule keeps them apart, the shared primer is simply repeated on each gBlock that needs it.`
      : "";
    const probes = data.probe_count
      ? `<br>${data.probe_count} pair${data.probe_count === 1 ? " has" : "s have"} a probe.`
      : "";
    $("bulk-summary").innerHTML =
      `&#10003; Read <strong>${data.pairs.length}</strong> primer pair${data.pairs.length === 1 ? "" : "s"} ` +
      `using <strong>${data.primer_count}</strong> primer${data.primer_count === 1 ? "" : "s"}.${linked}${probes}`;
    $("bulk-add-rule").disabled = data.pairs.length < 2;
    show($("bulk-options"));
  }

  // ---------- Layout choice ----------

  function selectedLayout() {
    return document.querySelector('input[name="bulk-layout"]:checked').value;
  }
  document.querySelectorAll('input[name="bulk-layout"]').forEach((r) =>
    r.addEventListener("change", () => {
      if (selectedLayout() === "split") show($("bulk-split-field")); else hide($("bulk-split-field"));
    }));

  // ---------- Rules ----------

  function pairOptionsHtml(selectedIndex) {
    return parsedPairs.map((p, i) =>
      `<option value="${escapeHtml(p.id)}"${i === selectedIndex ? " selected" : ""}>${escapeHtml(p.id)}</option>`).join("");
  }

  function addRuleRow(preset) {
    if (parsedPairs.length < 2) return;
    const p = preset && preset.a ? preset : null;
    const aIndex = p ? Math.max(parsedPairs.findIndex((x) => x.id === p.a), 0) : 0;
    const bIndex = p ? Math.max(parsedPairs.findIndex((x) => x.id === p.b), 0) : 1;
    const row = document.createElement("div");
    row.className = "rule-row";
    row.innerHTML = `
      <select class="rule-a" aria-label="First pair">${pairOptionsHtml(aIndex)}</select>
      <select class="rule-type" aria-label="Rule type">
        <option value="together">must be on the same gBlock as</option>
        <option value="apart">cannot be on the same gBlock as</option>
      </select>
      <select class="rule-b" aria-label="Second pair">${pairOptionsHtml(bIndex)}</select>
      <button type="button" class="remove-rule-row" title="Remove this rule">&times;</button>
    `;
    if (p && p.type) row.querySelector(".rule-type").value = p.type;
    row.querySelector(".remove-rule-row").addEventListener("click", () => row.remove());
    $("bulk-rules").appendChild(row);
  }
  $("bulk-add-rule").addEventListener("click", () => addRuleRow());

  function collectRules() {
    return Array.from(document.querySelectorAll("#bulk-rules .rule-row")).map((row) => ({
      a: row.querySelector(".rule-a").value,
      type: row.querySelector(".rule-type").value,
      b: row.querySelector(".rule-b").value,
    }));
  }

  // ---------- Design ----------

  $("bulk-design-btn").addEventListener("click", async () => {
    if (!csvText) return;
    const rules = collectRules();
    if (rules.some((r) => r.a === r.b)) {
      renderError("A rule needs two different pairs - check each rule's two dropdowns.");
      return;
    }

    const btn = $("bulk-design-btn");
    btn.disabled = true;
    btn.textContent = "Designing...";
    try {
      const res = await fetch("/api/bulk/design", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          csv: csvText,
          mode: selectedLayout(),
          num_blocks: $("bulk-num-blocks").value,
          rules,
          flank_length: $("bulk-flank").value,
          gc_percent: $("bulk-gc").value,
          avoid_flags: $("bulk-avoid-flags").checked,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Design failed");
      lastResult = data;
      lastSettings = {
        mode: selectedLayout(),
        flank_length: $("bulk-flank").value,
        gc_percent: $("bulk-gc").value,
      };
      renderResult(data);
    } catch (err) {
      renderError(err.message);
    } finally {
      btn.disabled = false;
      btn.textContent = "Design gBlocks";
    }
  });

  function renderError(message) {
    $("bulk-result").innerHTML = `<span class="badge error">Error</span> ${escapeHtml(message)}`;
    show($("bulk-result"));
  }

  function renderBlock(b, index) {
    const pairTags = b.pair_ids.map((id) => `<span class="tag tag-pair">${escapeHtml(id)}</span>`).join(" ");
    const head = `<div class="bulk-block-head"><strong>${escapeHtml(b.name)}</strong>`;

    if (b.error) {
      return `<div class="bulk-block" data-index="${index}">${head} <span class="badge error">Could not design</span></div>
        <div class="status-line">Pairs: ${pairTags}</div>
        <div class="status-line">${escapeHtml(b.error)}</div></div>`;
    }

    const flagBadge = b.flagged.length
      ? `<span class="badge warn">Flagged: ${escapeHtml(b.flagged.join(", "))}</span>`
      : `<span class="badge ok">No complexity flags</span>`;
    const flankNote = b.flank_length_note
      ? `<div class="reminder-box">&#8505; ${escapeHtml(b.flank_length_note)}</div>` : "";
    const degenNames = Object.keys(b.degenerate_info || {});
    const degenNote = degenNames.length
      ? `<div class="status-line">Degenerate bases were substituted automatically in: ${degenNames.map(escapeHtml).join(", ")}.</div>` : "";
    const probeNote = (b.probes || []).length
      ? `<div class="status-line">Probe${b.probes.length === 1 ? "" : "s"} for: ${b.probes.map((p) => escapeHtml(p.pair_id)).join(", ")}.</div>` : "";

    const rows = b.segments.map((s) => {
      const tag = s.type === "primer" ? ` <span class="tag tag-${s.direction}">${s.direction}</span>`
        : s.type === "probe" ? ` <span class="tag tag-probe">probe</span>` : "";
      return `<tr><td>${escapeHtml(s.label)}${tag}</td><td>${s.length} bp</td><td><code>${escapeHtml(s.seq)}</code></td></tr>`;
    }).join("");

    return `<div class="bulk-block" data-index="${index}">
      ${head} <span class="badge ok">${b.length} bp</span> <span class="badge ok">GC ${b.overall_gc_percent}%</span> ${flagBadge}</div>
      <div class="status-line">Pairs: ${pairTags}</div>
      ${flankNote}${degenNote}${probeNote}
      <div class="seq-block">${escapeHtml(b.sequence)}</div>
      <button type="button" class="tertiary-button copy-seq">Copy sequence</button>
      ${renderDiagram(b.segments)}
      <div class="bulk-actions${b.flagged.length ? "" : " hidden"}">
        <button type="button" class="secondary-button ba-fix">Try to fix flagged issues</button>
      </div>
      <div class="bb-status status-line hidden"></div>
      <details class="bulk-details"><summary>Show segments</summary>
        <table class="segment-table">
          <colgroup><col style="width:22%"><col style="width:14%"><col style="width:64%"></colgroup>
          <tr><th>Segment</th><th>Length</th><th>Sequence</th></tr>
          ${rows}
        </table>
      </details>
    </div>`;
  }

  // ---------- Next steps (below the gBlocks, like the single-gBlock page) ----------

  const STEPS = {
    align: {
      title: "Primer alignment",
      hint: "Checks that every primer binds where it should in its gBlock, and flags anywhere else it could also bind.",
      button: "Align primers on all gBlocks",
      busy: "Aligning...",
    },
    blast: {
      title: "NCBI BLAST",
      hint: "Searches NCBI's public database for existing sequences that match each designed gBlock. NCBI is searched two gBlocks at a time, so a large batch can take several minutes.",
      button: "Run BLAST on all gBlocks",
      busy: "Running...",
    },
    idt: {
      title: "Manufacturing complexity check",
      hint: "Checks each gBlock for the same kinds of problems IDT's ordering tool looks for: unusual GC content, repeated letters, repeated chunks, and hairpins. Always paste your final sequences into IDT's own tool before ordering.",
      button: "Run complexity check on all gBlocks",
      busy: "Checking...",
    },
  };
  let stepResults = { align: {}, blast: {}, idt: {} };

  function stepSectionHtml(step) {
    const t = STEPS[step];
    return `<div class="bulk-step" id="bulk-step-${step}">
      <h3 class="subsection-title">${t.title}</h3>
      <p class="hint">${t.hint}</p>
      <button type="button" class="step-run" data-step="${step}">${t.button}</button>
      <div class="bulk-step-results hidden" id="bulk-results-${step}"></div>
    </div>`;
  }

  function renderStep(step) {
    const container = $(`bulk-results-${step}`);
    if (!container || !lastResult) return;
    const items = Object.keys(stepResults[step]).map(Number).sort((a, b) => a - b).map((i) => {
      const b = lastResult.blocks[i];
      const rerun = `<button type="button" class="tertiary-button step-rerun" data-step="${step}" data-index="${i}">Re-run</button>`;
      return `<div class="step-item" data-index="${i}">
        <div class="step-item-head"><strong>${escapeHtml(b.name)}</strong> ${rerun}</div>
        ${stepResults[step][i]}
      </div>`;
    });
    container.innerHTML = items.join("");
    if (items.length) show(container); else hide(container);
  }

  function setStepItem(step, index, html) {
    stepResults[step][index] = html;
    renderStep(step);
  }

  function scrollToStep(step) {
    const el = $(`bulk-step-${step}`);
    if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function renderResult(data) {
    const designed = data.blocks.filter((b) => !b.error).length;
    const failed = data.blocks.length - designed;
    const summaryBadge = failed
      ? `<span class="badge warn">${designed} of ${data.blocks.length} designed</span>`
      : `<span class="badge ok">Designed</span>`;
    const notes = (data.notes || []).length
      ? `<div class="reminder-box">${data.notes.map(escapeHtml).join("<br><br>")}</div>` : "";

    stepResults = { align: {}, blast: {}, idt: {} };
    $("bulk-result").innerHTML = `
      <div class="bulk-summary-line">${summaryBadge}
        ${data.blocks.length} gBlock${data.blocks.length === 1 ? "" : "s"} from ${data.pair_count} primer pair${data.pair_count === 1 ? "" : "s"}.
        ${designed ? '<button type="button" class="tertiary-button" id="bulk-download">Download CSV</button>' : ""}
      </div>
      ${notes}
      <div id="bulk-blocks">${data.blocks.map(renderBlock).join("")}</div>
      ${designed ? ["align", "blast", "idt"].map(stepSectionHtml).join("") : ""}
    `;
    show($("bulk-result"));

    const dl = $("bulk-download");
    if (dl) dl.addEventListener("click", downloadCsv);
  }

  // ---------- Running the steps ----------

  function designedIndexes() {
    return lastResult.blocks.map((b, i) => (b.error ? null : i)).filter((i) => i !== null);
  }

  async function postJson(url, body) {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Request failed");
    return data;
  }

  async function withButton(btn, busyLabel, fn) {
    const label = btn.textContent;
    btn.disabled = true;
    btn.textContent = busyLabel;
    try { await fn(); } finally {
      btn.disabled = false;
      btn.textContent = label;
    }
  }

  const errorHtml = (message) => `<span class="badge error">Error</span> ${escapeHtml(message)}`;

  // Where each primer and probe sits in a gBlock, labelled the same way the
  // alignment request labels them.
  function spansFor(block) {
    return primerSpans(block.segments, (seg) => {
      if (seg.type !== "probe") return seg.label;
      const pair = parsedPairs.find((p) => `${p.forward_name} & ${p.reverse_name}` === seg.pair);
      return `Probe (${pair ? pair.id : seg.pair})`;
    });
  }

  function pairsOfLabel(label, block) {
    const probe = label.match(/^Probe \((.+)\)$/);
    if (probe) return [probe[1]];
    return block.pair_ids.filter((id) => {
      const p = parsedPairs.find((x) => x.id === id);
      return p && (p.forward_name === label || p.reverse_name === label);
    });
  }

  function adviceFor(block) {
    return (result, otherLabels) => otherLabels.map((other) => {
      const mine = pairsOfLabel(result.primer_label, block);
      const theirs = pairsOfLabel(other, block);
      if (mine.some((id) => theirs.includes(id))) {
        return `<div class="status-line"><strong>${escapeHtml(result.primer_label)}</strong> and <strong>${escapeHtml(other)}</strong> belong to the same pair, so they can't be moved onto different gBlocks &mdash; the two primers are very similar to each other, which is worth a look.</div>`;
      }
      const a = mine[0];
      const b = theirs[0];
      const button = a && b
        ? ` <button type="button" class="tertiary-button add-rule-btn" data-a="${escapeHtml(a)}" data-b="${escapeHtml(b)}">Add rule: ${escapeHtml(a)} cannot be with ${escapeHtml(b)}</button>`
        : "";
      return `<div class="status-line">This is because of another primer (<strong>${escapeHtml(other)}</strong>), not the random sequence. ` +
        `Putting ${a ? `pair ${escapeHtml(a)}` : escapeHtml(result.primer_label)} and ${b ? `pair ${escapeHtml(b)}` : escapeHtml(other)} on different gBlocks would avoid it.${button}</div>`;
    }).join("");
  }

  async function alignBlock(i) {
    const b = lastResult.blocks[i];
    try {
      const spans = spansFor(b);
      const startOf = (label) => (spans.find((sp) => sp.label === label) || {}).start;
      const primers = b.primers.map((p) => ({
        name: p.name, sequence: p.sequence, direction: p.direction,
        degenerate_substitutions: p.degenerate_substitutions, expected_start: startOf(p.name),
      }));
      (b.probes || []).forEach((p) => {
        const name = `Probe (${p.pair_id})`;
        primers.push({ name, sequence: p.sequence, direction: "forward", degenerate_substitutions: [], expected_start: startOf(name) });
      });
      const data = await postJson("/api/align", { primers, sequence: b.sequence });
      setStepItem("align", i, alignmentHtml(data, { spans, suggest: adviceFor(b) }));
    } catch (err) {
      setStepItem("align", i, errorHtml(err.message));
    }
  }

  async function complexityBlock(i) {
    const b = lastResult.blocks[i];
    try {
      const data = await postJson("/api/complexity-check", { sequence: b.sequence });
      const fix = data.any_flagged
        ? '<button type="button" class="secondary-button ba-fix">Try to fix flagged issues</button><div class="status-line fix-note hidden"></div>'
        : "";
      setStepItem("idt", i, `${complexityHtml(data)}${fix}`);
    } catch (err) {
      setStepItem("idt", i, errorHtml(err.message));
    }
  }

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const BLAST_STATUS = {
    queued: "Queued...",
    waiting_for_slot: "Waiting for a free BLAST slot (the app runs only a couple of searches at once, to stay in NCBI's good graces)...",
    running: "Running on NCBI's servers...",
  };

  async function blastBlock(i) {
    const b = lastResult.blocks[i];
    const stillCurrent = () => lastResult && lastResult.blocks[i] === b && $("bulk-results-blast");
    try {
      setStepItem("blast", i, '<div class="status-line">Submitting to NCBI...</div>');
      const start = await postJson("/api/blast/start", { sequence: b.sequence });
      for (;;) {
        await sleep(4000);
        if (!stillCurrent()) return; // this gBlock was re-designed or the page was re-run
        const res = await fetch(`/api/blast/status/${start.job_id}`);
        const job = await res.json();
        if (!res.ok) throw new Error(job.error || "Job lookup failed");
        if (job.status === "done") { setStepItem("blast", i, blastHtml(job)); return; }
        if (job.status === "error") {
          setStepItem("blast", i, `<span class="badge error">BLAST error</span> ${escapeHtml(job.error)}`);
          return;
        }
        setStepItem("blast", i, `<div class="status-line">${BLAST_STATUS[job.status] || `Status: ${escapeHtml(job.status)}...`}</div>`);
      }
    } catch (err) {
      if (stillCurrent()) setStepItem("blast", i, errorHtml(err.message));
    }
  }

  const STEP_RUNNERS = { align: alignBlock, blast: blastBlock, idt: complexityBlock };

  async function runStep(step, btn) {
    if (!lastResult) return;
    const indexes = designedIndexes();
    await withButton(btn, STEPS[step].busy, async () => {
      // Show a placeholder per gBlock straight away, so progress is visible.
      indexes.forEach((i) => { stepResults[step][i] = '<div class="status-line">Working...</div>'; });
      renderStep(step);
      scrollToStep(step);
      await Promise.all(indexes.map((i) => STEP_RUNNERS[step](i)));
    });
    scrollToStep(step); // finished - jump back to the results, wherever you've scrolled to meanwhile
  }

  async function rerunOne(step, index, btn) {
    await withButton(btn, "Running...", () => STEP_RUNNERS[step](index));
    const item = document.querySelector(`#bulk-results-${step} .step-item[data-index="${index}"]`);
    if (item) item.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  async function runFix(index, btn, fromStep) {
    const b = lastResult.blocks[index];
    const cardStatus = () => document.querySelector(`#bulk-blocks .bulk-block[data-index="${index}"] .bb-status`);
    await withButton(btn, "Trying...", async () => {
      try {
        const fresh = await postJson("/api/bulk/redesign-block", {
          csv: csvText, mode: lastSettings.mode, name: b.name, pair_ids: b.pair_ids,
          flank_length: lastSettings.flank_length, gc_percent: lastSettings.gc_percent,
        });
        lastResult.blocks[index] = fresh;
        const card = document.querySelector(`#bulk-blocks .bulk-block[data-index="${index}"]`);
        const holder = document.createElement("div");
        holder.innerHTML = renderBlock(fresh, index);
        card.replaceWith(holder.firstElementChild);

        // Anything already run for the old sequence no longer applies.
        ["align", "blast", "idt"].forEach((st) => { delete stepResults[st][index]; });
        const message = fresh.error
          ? fresh.error
          : (fresh.flagged.length
            ? "Tried again and kept the best result, but some issues remain. Run the steps again to see results for the new sequence."
            : "Fixed - nothing flagged now. Run the steps again to see results for the new sequence.");
        if (fromStep) stepResults[fromStep][index] = `<div class="status-line">${escapeHtml(message)}</div>`;
        ["align", "blast", "idt"].forEach(renderStep);
        const note = cardStatus();
        if (note) { note.textContent = message; show(note); }
      } catch (err) {
        const note = cardStatus();
        if (note) { note.textContent = `Error: ${err.message}`; show(note); }
      }
    });
  }

  function addSuggestedRule(btn) {
    const a = btn.dataset.a;
    const b = btn.dataset.b;
    const exists = collectRules().some((r) => r.type === "apart" && ((r.a === a && r.b === b) || (r.a === b && r.b === a)));
    if (!exists) addRuleRow({ a, b, type: "apart" });

    let extra = "";
    if (selectedLayout() !== "split") {
      document.querySelector('input[name="bulk-layout"][value="split"]').checked = true;
      show($("bulk-split-field"));
      $("bulk-num-blocks").value = Math.max(2, lastResult ? lastResult.blocks.length : 2);
      extra = ` (layout set to split across ${$("bulk-num-blocks").value} gBlocks)`;
    }
    btn.disabled = true;
    btn.textContent = `Rule added${extra} - press Design gBlocks to apply it`;
    $("bulk-design-btn").scrollIntoView({ behavior: "smooth", block: "center" });
  }

  $("bulk-result").addEventListener("click", (e) => {
    if (!lastResult) return;
    const t = e.target;
    const run = t.closest(".step-run");
    const rerun = t.closest(".step-rerun");
    const fix = t.closest(".ba-fix");
    const copy = t.closest(".copy-seq");
    const addRule = t.closest(".add-rule-btn");
    if (run) runStep(run.dataset.step, run);
    else if (rerun) rerunOne(rerun.dataset.step, Number(rerun.dataset.index), rerun);
    else if (fix) {
      const item = fix.closest(".step-item");
      const card = fix.closest(".bulk-block");
      runFix(Number((item || card).dataset.index), fix, item ? "idt" : null);
    } else if (addRule) addSuggestedRule(addRule);
    else if (copy) copySequence(copy, copy.closest(".bulk-block"));
  });

  // ---------- Copy + download ----------

  async function copySequence(btn, card) {
    const seq = lastResult.blocks[Number(card.dataset.index)].sequence;
    try {
      await navigator.clipboard.writeText(seq);
      btn.textContent = "Copied";
    } catch (e) {
      btn.textContent = "Copy failed - select the sequence above instead";
    }
    setTimeout(() => { btn.textContent = "Copy sequence"; }, 2000);
  }

  function csvField(value) {
    const s = String(value);
    return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  }

  function downloadCsv() {
    if (!lastResult) return;
    const lines = [["Name", "Sequence", "Length (bp)", "GC (%)", "Pairs", "Primers"].join(",")];
    lastResult.blocks.filter((b) => !b.error).forEach((b) => {
      lines.push([
        b.name, b.sequence, b.length, b.overall_gc_percent,
        b.pair_ids.join(" "), b.primer_names.join(" "),
      ].map(csvField).join(","));
    });
    const blob = new Blob([lines.join("\r\n") + "\r\n"], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "gblocks.csv";
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }
})();
