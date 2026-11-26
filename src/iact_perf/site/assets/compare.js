// Comparison page of iact-perf: pick curves with the filters, overlay them.
// Data: records.json written by iact_perf.site.export. Labels come from the
// database (contributor-written): they are inserted with textContent only.

(function () {
  "use strict";

  const MAX_CURVES = 8; // categorical palette size: never cycle colours
  const MAX_LIST = 300;
  const SYMBOLS = ["circle", "square", "diamond", "triangle-up", "cross", "triangle-down", "star", "x"];
  const root = document.getElementById("iact-compare");
  if (!root) return;

  const state = {
    data: null,
    group: null,
    filters: {},
    selected: new Map(), // uid -> slot (0..7): colour follows the curve, not its rank
  };

  const el = (tag, attrs = {}, text) => {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
    if (text !== undefined) e.textContent = text;
    return e;
  };

  // Resolve a CSS colour variable to rgb(): Material defines its colours as
  // hsla(var(--md-hue), ...), which Plotly cannot parse.
  const probe = document.createElement("span");
  probe.style.display = "none";
  root.append(probe);
  const css = (name) => {
    probe.style.color = `var(${name})`;
    return getComputedStyle(probe).color;
  };
  const seriesColor = (slot) => css(`--series-${slot + 1}`);

  // ------------------------------------------------------------------ formatting

  function fmtZenith(z) {
    if (!z) return "unknown";
    return z[0] === z[1] ? `${z[0]}°` : `${z[0]}–${z[1]}°`;
  }

  // short curve name for the legend: what differs between curves, not the full label
  function shortName(r) {
    const parts = [
      `${state.data.instruments[r.instrument] || r.instrument} ${r.configuration.replace(/_/g, " ")}`,
      r.analysis,
      `zenith ${fmtZenith(r.zenith)}`,
    ];
    if (r.obs_time) parts.push(r.obs_time);
    if (r.moon && r.moon !== "dark" && r.moon !== "unknown") parts.push(`moon ${r.moon}`);
    if (r.definition) parts.push(r.definition.replace(/_/g, " "));
    return parts.join(" · ");
  }

  function fmtNum(v) {
    if (v === null || v === undefined) return "";
    const a = Math.abs(v);
    return a !== 0 && (a < 1e-3 || a >= 1e5) ? v.toExponential(3) : String(+v.toPrecision(4));
  }

  // ------------------------------------------------------------------ filters

  const FILTERS = [
    ["instrument", "Instrument", (r) => r.instrument, (v) => state.data.instruments[v] || v],
    ["analysis", "Analysis", (r) => r.analysis, (v) => state.data.analyses[v] || v],
    ["configuration", "Configuration", (r) => r.configuration, (v) => v],
    ["zenith", "Zenith", (r) => fmtZenith(r.zenith), (v) => v],
    ["obs_time", "Obs. time", (r) => r.obs_time || "n/a", (v) => v],
    ["moon", "Moon", (r) => r.moon, (v) => v],
  ];

  function groupRecords() {
    return state.data.records.filter((r) => r.group === state.group);
  }

  function matches(r, skip) {
    for (const [key, , get] of FILTERS) {
      if (key === skip) continue;
      const want = state.filters[key];
      if (want && get(r) !== want) return false;
    }
    const q = (state.filters.text || "").toLowerCase();
    if (q && !(`${r.label} ${r.source} ${r.uid}`.toLowerCase().includes(q))) return false;
    return true;
  }

  function buildControls() {
    const bar = root.querySelector(".ic-filters");
    bar.replaceChildren();

    const gsel = el("select", { "aria-label": "Quantity" });
    for (const g of state.data.groups) {
      const o = el("option", { value: g.key }, `${g.name} (${g.n})`);
      if (g.key === state.group) o.selected = true;
      gsel.append(o);
    }
    gsel.addEventListener("change", () => {
      state.group = gsel.value;
      state.filters = {};
      state.selected.clear();
      update();
    });
    bar.append(labelled("Quantity", gsel));

    const recs = groupRecords();
    for (const [key, name, get, show] of FILTERS) {
      // options available given the other filters, so that no choice gives nothing
      const values = [...new Set(recs.filter((r) => matches(r, key)).map(get))].sort(sortValues);
      if (values.length < 2 && !state.filters[key]) continue;
      const s = el("select", { "aria-label": name });
      s.append(el("option", { value: "" }, "Any"));
      for (const v of values) {
        const o = el("option", { value: v }, show(v));
        if (state.filters[key] === v) o.selected = true;
        s.append(o);
      }
      s.addEventListener("change", () => {
        state.filters[key] = s.value || undefined;
        update();
      });
      bar.append(labelled(name, s));
    }

    const t = el("input", { type: "search", placeholder: "Search labels", "aria-label": "Search" });
    t.value = state.filters.text || "";
    t.addEventListener("input", () => {
      state.filters.text = t.value;
      renderList();
    });
    bar.append(labelled("Search", t));
  }

  function sortValues(a, b) {
    const na = parseFloat(a), nb = parseFloat(b);
    if (!isNaN(na) && !isNaN(nb) && na !== nb) return na - nb;
    return String(a).localeCompare(String(b));
  }

  function labelled(text, control) {
    const l = el("label", { class: "ic-control" });
    l.append(el("span", {}, text), control);
    return l;
  }

  // ------------------------------------------------------------------ list of curves

  function renderList() {
    const box = root.querySelector(".ic-list");
    const recs = groupRecords().filter((r) => matches(r));
    box.replaceChildren();
    const head = el("p", { class: "ic-count" });
    head.textContent =
      `${recs.length} curve${recs.length === 1 ? "" : "s"} match` +
      (recs.length > MAX_LIST ? `, showing the first ${MAX_LIST}. Narrow the filters.` : ".") +
      ` ${state.selected.size}/${MAX_CURVES} selected.`;
    box.append(head);

    const list = el("ul", { class: "ic-items" });
    for (const r of recs.slice(0, MAX_LIST)) {
      const li = el("li");
      const id = `ic-${r.uid.replace(/[^a-zA-Z0-9]/g, "_")}`;
      const cb = el("input", { type: "checkbox", id });
      cb.checked = state.selected.has(r.uid);
      cb.disabled = !cb.checked && state.selected.size >= MAX_CURVES;
      cb.addEventListener("change", () => toggle(r.uid, cb.checked));
      const swatch = el("span", { class: "ic-swatch", "aria-hidden": "true" });
      if (cb.checked) swatch.style.background = seriesColor(state.selected.get(r.uid));
      const lab = el("label", { for: id });
      lab.append(el("span", { class: "ic-label" }, r.label));
      lab.append(
        el("span", { class: "ic-meta" },
          `${r.source} · ${r.configuration} · ${state.data.analyses[r.analysis] || r.analysis} · zenith ${fmtZenith(r.zenith)}` +
          (r.obs_time ? ` · ${r.obs_time}` : "") + (r.superseded ? " · superseded" : ""))
      );
      li.append(cb, swatch, lab);
      list.append(li);
    }
    box.append(list);
  }

  function toggle(uid, on) {
    if (on) {
      if (state.selected.size >= MAX_CURVES) return;
      const used = new Set(state.selected.values());
      let slot = 0;
      while (used.has(slot)) slot++;
      state.selected.set(uid, slot);
    } else {
      state.selected.delete(uid);
    }
    renderList();
    renderPlot();
    renderTable();
    writeHash();
  }

  // ------------------------------------------------------------------ plot

  function selectedRecords() {
    const byUid = new Map(state.data.records.map((r) => [r.uid, r]));
    return [...state.selected.entries()]
      .map(([uid, slot]) => ({ rec: byUid.get(uid), slot }))
      .filter((s) => s.rec);
  }

  function renderPlot() {
    const div = root.querySelector(".ic-plot");
    const group = state.data.groups.find((g) => g.key === state.group);
    const sel = selectedRecords();
    const fg = css("--ic-text"), muted = css("--ic-text-muted"), grid = css("--ic-grid");
    const traces = [];
    for (const { rec, slot } of sel) {
      const color = seriesColor(slot);
      const name = shortName(rec);
      const err = (i) => (rec.ylo ? ` (−${fmtNum(rec.ylo[i])} +${fmtNum(rec.yhi[i])})` : "");
      const bin = (i) => (rec.xlo ? `bin ${fmtNum(rec.xlo[i])}–${fmtNum(rec.xhi[i])} TeV` : `${fmtNum(rec.x[i])} TeV`);
      // Bin widths and error bars in their own trace, ignored by the tooltip
      // (in unified hover Plotly would print them in the tooltip title)
      if (rec.xlo || rec.ylo) {
        traces.push({
          x: rec.x, y: rec.y, type: "scatter", mode: "markers", hoverinfo: "skip", showlegend: false,
          marker: { opacity: 0 },
          error_x: rec.xlo ? { type: "data", symmetric: false, thickness: 1, width: 0, color,
            array: rec.xhi.map((h, i) => h - rec.x[i]), arrayminus: rec.xlo.map((l, i) => rec.x[i] - l) } : undefined,
          error_y: rec.ylo ? { type: "data", symmetric: false, thickness: 1, width: 3, color,
            array: rec.yhi, arrayminus: rec.ylo } : undefined,
        });
      }
      traces.push({
        x: rec.x,
        y: rec.y,
        type: "scatter",
        mode: "lines+markers",
        name,
        line: { color, width: 2 },
        marker: { color, size: 8, symbol: SYMBOLS[slot], line: { color: css("--ic-surface"), width: 2 } },
        customdata: rec.x.map((_, i) => [bin(i), err(i)]),
        hovertemplate: `<b>%{y:.3~g}</b>%{customdata[1]} · %{customdata[0]}<br>${name.replace(/[<>]/g, "")}<extra></extra>`,
      });
    }
    const axis = (title, type) => ({
      title: { text: title, font: { color: fg }, standoff: 14 },
      type, color: muted, gridcolor: grid, zeroline: false, linecolor: grid,
      showspikes: type === "log" && title.startsWith("Energy"), spikecolor: grid, spikethickness: 1, spikedash: "solid", spikemode: "across", spikesnap: "cursor",
      exponentformat: "power",
      dtick: type === "log" ? 1 : undefined, // one label per decade
      ticks: "outside", ticklen: 4, tickcolor: grid,
    });
    const layout = {
      paper_bgcolor: css("--ic-surface"), // a real colour: Plotly outlines spikes with it
      plot_bgcolor: css("--ic-surface"),
      font: { color: fg, family: getComputedStyle(root).fontFamily, size: 13 },
      margin: { l: 90, r: 20, t: 10, b: 50 },
      xaxis: { ...axis("Energy [TeV]", "log"), hoverformat: ".3~g" },
      yaxis: axis(group ? group.name : "", group && group.log_y ? "log" : "linear"),
      showlegend: sel.length > 0,
      legend: { orientation: "v", x: 0, y: -0.16, xanchor: "left", yanchor: "top", font: { size: 12 } },
      hovermode: "x unified",
      hoverdistance: -1, // every curve answers, even when its bin centres differ
      hoverlabel: { bgcolor: css("--ic-surface"), bordercolor: grid, font: { color: fg, family: getComputedStyle(root).fontFamily }, namelength: -1 },
    };
    if (!sel.length) {
      layout.annotations = [{ text: "Select curves in the list below", showarrow: false, font: { color: muted, size: 14 }, xref: "paper", yref: "paper", x: 0.5, y: 0.5 }];
    }
    window.Plotly.react(div, traces, layout, { responsive: true, displaylogo: false, toImageButtonOptions: { format: "svg", filename: "iact-perf-comparison" } });
  }

  // ------------------------------------------------------------------ table view and details

  function renderTable() {
    const box = root.querySelector(".ic-details");
    box.replaceChildren();
    const sel = selectedRecords();
    if (!sel.length) return;

    const cards = el("ul", { class: "ic-cards" });
    for (const { rec, slot } of sel) {
      const li = el("li");
      const key = el("span", { class: "ic-swatch", "aria-hidden": "true" });
      key.style.background = seriesColor(slot);
      const src = state.data.sources[rec.source];
      const link = el("a", { href: `../sources/${rec.source}/` }, `${src.title} (${src.year})`);
      li.append(key, el("strong", {}, rec.label), el("br"), link);
      const facts = [
        `analysis ${state.data.analyses[rec.analysis] || rec.analysis}`,
        `configuration ${rec.configuration}`,
        rec.definition && `definition ${rec.definition}`,
        rec.energy_type && `${rec.energy_type} energy`,
        rec.data_kind.replace("_", " "),
        `zenith ${fmtZenith(rec.zenith)}`,
        rec.obs_time && `time ${rec.obs_time}`,
        `moon ${rec.moon}`,
        rec.provenance,
        rec.converted,
      ].filter(Boolean);
      li.append(el("div", { class: "ic-meta" }, facts.join(" · ")));
      cards.append(li);
    }
    box.append(cards);

    const details = el("details", { class: "ic-table" });
    details.append(el("summary", {}, "Data table"));
    const table = el("table");
    const thead = el("thead");
    const hr = el("tr");
    for (const h of ["Curve", "E [TeV]", "E min", "E max", "Value", "Err −", "Err +"]) hr.append(el("th", {}, h));
    thead.append(hr);
    const tbody = el("tbody");
    for (const { rec } of sel) {
      rec.x.forEach((x, i) => {
        const tr = el("tr");
        const cells = [rec.label, x, rec.xlo && rec.xlo[i], rec.xhi && rec.xhi[i], rec.y[i], rec.ylo && rec.ylo[i], rec.yhi && rec.yhi[i]];
        cells.forEach((c, j) => tr.append(el("td", {}, j === 0 ? c : fmtNum(c))));
        tbody.append(tr);
      });
    }
    table.append(thead, tbody);
    const csv = el("button", { type: "button", class: "md-button" }, "Download CSV");
    csv.addEventListener("click", () => downloadCsv(sel));
    details.append(csv, table);
    box.append(details);
  }

  function downloadCsv(sel) {
    const group = state.data.groups.find((g) => g.key === state.group);
    const q = (s) => `"${String(s).replace(/"/g, '""')}"`;
    const rows = [["curve", "source", "energy_TeV", "energy_min_TeV", "energy_max_TeV", `value ${group.name}`, "err_low", "err_high"].map(q).join(",")];
    for (const { rec } of sel) {
      rec.x.forEach((x, i) => {
        rows.push([q(rec.label), q(rec.source), x, rec.xlo ? rec.xlo[i] : "", rec.xhi ? rec.xhi[i] : "", rec.y[i], rec.ylo ? rec.ylo[i] : "", rec.yhi ? rec.yhi[i] : ""].join(","));
      });
    }
    const blob = new Blob([rows.join("\n") + "\n"], { type: "text/csv" });
    const a = el("a", { href: URL.createObjectURL(blob), download: "iact-perf-comparison.csv" });
    document.body.append(a);
    a.click();
    a.remove();
  }

  // ------------------------------------------------------------------ shareable state

  function writeHash() {
    const ids = [...state.selected.keys()].map(encodeURIComponent).join(",");
    history.replaceState(null, "", `#g=${encodeURIComponent(state.group)}&c=${ids}`);
  }

  function readHash() {
    const p = new URLSearchParams(location.hash.slice(1));
    const g = p.get("g");
    if (!g || !state.data.groups.some((x) => x.key === g)) return false;
    state.group = g;
    for (const uid of (p.get("c") || "").split(",").filter(Boolean).map(decodeURIComponent)) {
      if (state.data.records.some((r) => r.uid === uid && r.group === g)) toggleSilently(uid);
    }
    return true;
  }

  function toggleSilently(uid) {
    if (state.selected.size >= MAX_CURVES) return;
    state.selected.set(uid, state.selected.size);
  }

  function defaultSelection() {
    const g = state.data.groups.find((x) => x.key.startsWith("sensitivity|differential"));
    state.group = (g || state.data.groups[0]).key;
    for (const uid of JSON.parse(root.dataset.defaults || "[]")) {
      if (state.data.records.some((r) => r.uid === uid && r.group === state.group)) toggleSilently(uid);
    }
  }

  function update() {
    buildControls();
    renderList();
    renderPlot();
    renderTable();
    writeHash();
  }

  // re-render on light/dark switch: the series steps differ per scheme
  new MutationObserver(() => state.data && (renderPlot(), renderList(), renderTable())).observe(document.body, {
    attributes: true,
    attributeFilter: ["data-md-color-scheme"],
  });

  fetch(root.dataset.src)
    .then((r) => r.json())
    .then((data) => {
      state.data = data;
      if (!readHash()) defaultSelection();
      root.querySelector(".ic-loading").remove();
      update();
    })
    .catch((err) => {
      root.querySelector(".ic-loading").textContent = `Could not load the data: ${err}`;
    });
})();
