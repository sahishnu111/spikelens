"use strict";
const $ = (s) => document.querySelector(s);
let current = null; // {values, timestamps, labels}
let chart = null;

function setStatus(t) { $("#status").textContent = t; }

function body() {
  return JSON.stringify({ ...current, detector: $("#detector").value, sensitivity: +$("#sens").value });
}

async function analyze() {
  if (!current) return;
  setStatus("Analyzing…");
  const r = await fetch("/api/analyze", { method: "POST", headers: { "content-type": "application/json" }, body: body() });
  if (!r.ok) { setStatus("Error: " + (await r.text())); return; }
  render(await r.json());
}

function render(res) {
  const labels = res.timestamps ? res.timestamps.map((t) => t.replace("T", " ").slice(5, 16)) : res.values.map((_, i) => i);
  const anomalyPts = res.values.map(() => null);
  res.anomalies.forEach((a) => (anomalyPts[a.index] = a.value));
  const truth = current && current.labels ? res.values.map((v, i) => (current.labels[i] ? v : null)) : null;
  const ds = [
    { label: "value", data: res.values, borderColor: "#4f8cff", borderWidth: 1, pointRadius: 0, tension: 0 },
    { label: "flagged anomaly", data: anomalyPts, borderColor: "#ff5470", backgroundColor: "#ff5470", showLine: false, pointRadius: 5, pointStyle: "circle" },
  ];
  if (truth) ds.push({ label: "ground-truth label", data: truth, borderColor: "#ffc857", showLine: false, pointRadius: 8, pointStyle: "crossRot", borderWidth: 1.5 });
  if (chart) chart.destroy();
  chart = new Chart($("#chart"), {
    type: "line", data: { labels, datasets: ds },
    options: { animation: false, maintainAspectRatio: false, interaction: { mode: "nearest", intersect: true },
      scales: { x: { ticks: { color: "#8a93a6", maxTicksLimit: 12 } }, y: { ticks: { color: "#8a93a6" } } },
      plugins: { legend: { labels: { color: "#e6e9ef" } },
        tooltip: { callbacks: { afterBody: (items) => { const a = res.anomalies.find((x) => x.index === items[0].dataIndex); return a ? a.reason : ""; } } } } },
  });
  const m = res.metrics;
  const s = [`<div><b>${res.n_points}</b>points</div>`, `<div><b>${res.anomalies.length}</b>flagged</div>`,
    `<div><b>${res.params.auto_selected || res.detector}</b>detector</div>`,
    `<div><b>${res.detected_period ?? "none"}</b>detected period</div>`];
  if (m) s.push(`<div><b>${m.precision.toFixed(2)}</b>precision</div><div><b>${m.recall.toFixed(2)}</b>recall</div><div><b>${m.f1.toFixed(2)}</b>F1 (±2 pts)</div>`);
  $("#summary").innerHTML = s.join("");
  const tb = $("#tbl tbody");
  tb.innerHTML = "";
  res.anomalies.slice(0, 500).forEach((a) => {
    const tr = document.createElement("tr");
    [a.index, a.timestamp ?? "", a.value.toFixed(3), a.score.toFixed(2), a.reason].forEach((v) => { const td = document.createElement("td"); td.textContent = v; tr.appendChild(td); });
    tb.appendChild(tr);
  });
  setStatus(`Done: ${res.anomalies.length} anomalies by ${res.params.auto_selected || res.detector}.`);
}

async function loadDemo(kind) {
  setStatus("Loading demo…");
  const d = await (await fetch("/api/demo?kind=" + kind)).json();
  current = { values: d.values, timestamps: d.timestamps, labels: d.labels };
  setStatus(d.description);
  await analyze();
}

async function upload(file) {
  const fd = new FormData();
  fd.append("file", file); fd.append("detector", $("#detector").value);
  fd.append("sensitivity", $("#sens").value); fd.append("log_metric", $("#logmetric").value);
  setStatus("Uploading " + file.name + "…");
  const r = await fetch("/api/upload", { method: "POST", body: fd });
  if (!r.ok) { setStatus("Error: " + (await r.text())); return; }
  const res = await r.json();
  current = { values: res.values, timestamps: res.timestamps, labels: null };
  render(res);
}

async function exportAs(fmt) {
  if (!current) return;
  const r = await fetch("/api/export?format=" + fmt, { method: "POST", headers: { "content-type": "application/json" }, body: body() });
  const blob = await r.blob();
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob); a.download = "anomalies." + fmt; a.click();
}

document.querySelectorAll("[data-demo]").forEach((b) => b.addEventListener("click", () => loadDemo(b.dataset.demo)));
$("#file").addEventListener("change", (e) => e.target.files[0] && upload(e.target.files[0]));
$("#detector").addEventListener("change", analyze);
$("#sens").addEventListener("input", () => ($("#sensv").textContent = (+$("#sens").value).toFixed(1)));
$("#sens").addEventListener("change", analyze);
$("#exportcsv").addEventListener("click", () => exportAs("csv"));
$("#exportjson").addEventListener("click", () => exportAs("json"));
