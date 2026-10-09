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

  function addRuleRow() {
    if (parsedPairs.length < 2) return;
    const row = document.createElement("div");
    row.className = "rule-row";
    row.innerHTML = `
      <select class="rule-a" aria-label="First pair">${pairOptionsHtml(0)}</select>
      <select class="rule-type" aria-label="Rule type">
        <option value="together">must be on the same gBlock as</option>
        <option value="apart">cannot be on the same gBlock as</option>
      </select>
      <select class="rule-b" aria-label="Second pair">${pairOptionsHtml(1)}</select>
      <button type="button" class="remove-rule-row" title="Remove this rule">&times;</button>
    `;
    row.querySelector(".remove-rule-row").addEventListener("click", () => row.remove());
    $("bulk-rules").appendChild(row);
  }
  $("bulk-add-rule").addEventListener("click", addRuleRow);

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
      <div class="bulk-actions">
        <button type="button" class="tertiary-button ba-align">Align primers</button>
        <button type="button" class="tertiary-button ba-blast">Run BLAST</button>
        <button type="button" class="tertiary-button ba-idt">Complexity check</button>
        <button type="button" class="secondary-button ba-fix${b.flagged.length ? "" : " hidden"}">Try to fix flagged issues</button>
      </div>
      <div class="bb-status status-line hidden"></div>
      <div class="bb-result bb-align-result hidden"></div>
      <div class="bb-result bb-blast-result hidden"></div>
      <div class="bb-result bb-idt-result hidden"></div>
      <details class="bulk-details"><summary>Show segments</summary>
        <table class="segment-table">
          <colgroup><col style="width:22%"><col style="width:14%"><col style="width:64%"></colgroup>
          <tr><th>Segment</th><th>Length</th><th>Sequence</th></tr>
          ${rows}
        </table>
      </details>
    </div>`;
  }

  function renderResult(data) {
    const designed = data.blocks.filter((b) => !b.error).length;
    const failed = data.blocks.length - designed;
    const summaryBadge = failed
      ? `<span class="badge warn">${designed} of ${data.blocks.length} designed</span>`
      : `<span class="badge ok">Designed</span>`;
    const notes = (data.notes || []).length
      ? `<div class="reminder-box">${data.notes.map(escapeHtml).join("<br><br>")}</div>` : "";

    $("bulk-result").innerHTML = `
      <div class="bulk-summary-line">${summaryBadge}
        ${data.blocks.length} gBlock${data.blocks.length === 1 ? "" : "s"} from ${data.pair_count} primer pair${data.pair_count === 1 ? "" : "s"}.
        ${designed ? '<button type="button" class="tertiary-button" id="bulk-download">Download CSV</button>' : ""}
      </div>
      ${designed ? `<div class="bulk-actions bulk-actions-all">
        <span class="status-line">Run on every gBlock:</span>
        <button type="button" class="tertiary-button" id="bulk-align-all">Align all</button>
        <button type="button" class="tertiary-button" id="bulk-blast-all">BLAST all</button>
        <button type="button" class="tertiary-button" id="bulk-idt-all">Complexity check all</button>
      </div>
      <div class="status-line">BLAST searches NCBI two at a time, so a large batch can take several minutes.</div>` : ""}
      ${notes}
      <div id="bulk-blocks">${data.blocks.map(renderBlock).join("")}</div>
    `;
    show($("bulk-result"));

    const dl = $("bulk-download");
    if (dl) dl.addEventListener("click", downloadCsv);
    if ($("bulk-align-all")) {
      $("bulk-align-all").addEventListener("click", () => runAll(".ba-align", runAlign, $("bulk-align-all")));
      $("bulk-blast-all").addEventListener("click", () => runAll(".ba-blast", runBlast, $("bulk-blast-all")));
      $("bulk-idt-all").addEventListener("click", () => runAll(".ba-idt", runComplexity, $("bulk-idt-all")));
    }
  }

  // ---------- Per-gBlock actions (alignment, BLAST, complexity, fix) ----------

  function blockOf(card) { return lastResult.blocks[Number(card.dataset.index)]; }

  function setOutput(card, selector, html) {
    const out = card.querySelector(selector);
    out.innerHTML = html;
    show(out);
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

  async function runAlign(card) {
    const b = blockOf(card);
    await withButton(card.querySelector(".ba-align"), "Aligning...", async () => {
      try {
        const primers = b.primers.map((p) => ({
          name: p.name, sequence: p.sequence, direction: p.direction,
          degenerate_substitutions: p.degenerate_substitutions,
        }));
        (b.probes || []).forEach((p) => primers.push({
          name: `Probe (${p.pair_id})`, sequence: p.sequence, direction: "forward", degenerate_substitutions: [],
        }));
        const data = await postJson("/api/align", { primers, sequence: b.sequence });
        setOutput(card, ".bb-align-result", `<h4 class="bb-result-title">Primer alignment</h4>${alignmentHtml(data)}`);
      } catch (err) {
        setOutput(card, ".bb-align-result", `<span class="badge error">Error</span> ${escapeHtml(err.message)}`);
      }
    });
  }

  async function runComplexity(card) {
    const b = blockOf(card);
    await withButton(card.querySelector(".ba-idt"), "Checking...", async () => {
      try {
        const data = await postJson("/api/complexity-check", { sequence: b.sequence });
        setOutput(card, ".bb-idt-result", `<h4 class="bb-result-title">Manufacturing complexity check</h4>${complexityHtml(data)}`);
      } catch (err) {
        setOutput(card, ".bb-idt-result", `<span class="badge error">Error</span> ${escapeHtml(err.message)}`);
      }
    });
  }

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const BLAST_STATUS = {
    queued: "Queued...",
    waiting_for_slot: "Waiting for a free BLAST slot (the app runs only a couple of searches at once, to stay in NCBI's good graces)...",
    running: "Running on NCBI's servers...",
  };

  async function runBlast(card) {
    const b = blockOf(card);
    await withButton(card.querySelector(".ba-blast"), "Running...", async () => {
      const title = '<h4 class="bb-result-title">NCBI BLAST</h4>';
      try {
        setOutput(card, ".bb-blast-result", `${title}<div class="status-line">Submitting to NCBI...</div>`);
        const start = await postJson("/api/blast/start", { sequence: b.sequence });
        for (;;) {
          await sleep(4000);
          if (!card.isConnected) return; // this gBlock was re-designed or the page was re-run
          const res = await fetch(`/api/blast/status/${start.job_id}`);
          const job = await res.json();
          if (!res.ok) throw new Error(job.error || "Job lookup failed");
          if (job.status === "done") {
            setOutput(card, ".bb-blast-result", `${title}${blastHtml(job)}`);
            return;
          }
          if (job.status === "error") {
            setOutput(card, ".bb-blast-result", `${title}<span class="badge error">BLAST error</span> ${escapeHtml(job.error)}`);
            return;
          }
          setOutput(card, ".bb-blast-result", `${title}<div class="status-line">${BLAST_STATUS[job.status] || `Status: ${escapeHtml(job.status)}...`}</div>`);
        }
      } catch (err) {
        if (card.isConnected) setOutput(card, ".bb-blast-result", `${title}<span class="badge error">Error</span> ${escapeHtml(err.message)}`);
      }
    });
  }

  async function runFix(card) {
    const index = Number(card.dataset.index);
    const b = blockOf(card);
    const status = card.querySelector(".bb-status");
    await withButton(card.querySelector(".ba-fix"), "Trying...", async () => {
      status.textContent = "Re-rolling the random parts of this gBlock and re-checking...";
      show(status);
      try {
        const fresh = await postJson("/api/bulk/redesign-block", {
          csv: csvText, mode: lastSettings.mode, name: b.name, pair_ids: b.pair_ids,
          flank_length: lastSettings.flank_length, gc_percent: lastSettings.gc_percent,
        });
        lastResult.blocks[index] = fresh;
        const holder = document.createElement("div");
        holder.innerHTML = renderBlock(fresh, index);
        const newCard = holder.firstElementChild;
        card.replaceWith(newCard);
        const note = newCard.querySelector(".bb-status");
        note.textContent = fresh.error
          ? ""
          : (fresh.flagged.length
            ? "Tried again and kept the best result, but some issues remain. Alignment, BLAST and check results for this gBlock were cleared because its sequence changed."
            : "Fixed - nothing flagged now. Any earlier alignment, BLAST or check results for this gBlock were cleared because its sequence changed.");
        if (note.textContent) show(note);
      } catch (err) {
        status.textContent = `Error: ${err.message}`;
      }
    });
  }

  async function runAll(selector, runner, triggerBtn) {
    const cards = Array.from(document.querySelectorAll("#bulk-blocks .bulk-block"))
      .filter((c) => c.querySelector(selector) && !c.querySelector(selector).disabled);
    await withButton(triggerBtn, "Running...", () => Promise.all(cards.map(runner)));
  }

  $("bulk-result").addEventListener("click", (e) => {
    const card = e.target.closest(".bulk-block");
    if (!card || !lastResult) return;
    if (e.target.closest(".ba-align")) runAlign(card);
    else if (e.target.closest(".ba-blast")) runBlast(card);
    else if (e.target.closest(".ba-idt")) runComplexity(card);
    else if (e.target.closest(".ba-fix")) runFix(card);
    else if (e.target.closest(".copy-seq")) copySequence(e.target.closest(".copy-seq"), card);
  });

  // ---------- Copy + download ----------

  async function copySequence(btn, card) {
    const seq = blockOf(card).sequence;
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
