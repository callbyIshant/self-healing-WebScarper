/**
 * Client-Side JavaScript for Self-Healing Web Scraper Dashboard.
 * Manages WebSockets, real-time 9-layer animations, diff views, and logs.
 */

let ws = null;
let lastResults = {};
let logCount = 0;

// Initialize WebSocket connection
function connectWebSocket() {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const wsUrl = `${protocol}//${window.location.host}/ws/scrape`;

  ws = new WebSocket(wsUrl);

  ws.onopen = () => {
    addLog("system", "WebSocket connection established with scraper backend.");
    document.getElementById("pipelineStatusBadge").innerText = "Status: Connected";
    document.getElementById("pipelineStatusBadge").className = "text-xs font-mono px-2.5 py-0.5 rounded bg-emerald-950/70 text-emerald-400 border border-emerald-800";
  };

  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      handleServerEvent(data);
    } catch (e) {
      console.error("Error parsing WS event:", e);
    }
  };

  ws.onclose = () => {
    addLog("warn", "WebSocket disconnected. Reconnecting in 2s...");
    document.getElementById("pipelineStatusBadge").innerText = "Status: Disconnected";
    document.getElementById("pipelineStatusBadge").className = "text-xs font-mono px-2.5 py-0.5 rounded bg-red-950 text-red-400 border border-red-800";
    setTimeout(connectWebSocket, 2000);
  };

  ws.onerror = (err) => {
    console.error("WS Error:", err);
  };
}

// Handle real-time pipeline events
function handleServerEvent(data) {
  switch (data.type) {
    case "start":
      resetLayerCards();
      document.getElementById("healingSection").classList.add("hidden");
      document.getElementById("pipelineStatusBadge").innerText = "Status: Running...";
      document.getElementById("pipelineStatusBadge").className = "text-xs font-mono px-2.5 py-0.5 rounded bg-cyan-950 text-cyan-400 border border-cyan-800 animate-pulse";
      addLog("info", `Starting extraction for ${data.domain} on ${data.url}`);
      break;

    case "layer_event":
      updateLayerCard(data.layer, data.status, data.title, data.detail);
      addLog("info", `[Layer ${data.layer}] ${data.title}: ${data.detail}`);
      break;

    case "healing_event":
      showHealingDiff(data);
      addLog("warn", `[AI Self-Healing] Repaired locator for '${data.field}': '${data.old_selector}' -> '${data.repaired_selector}' (${(data.confidence * 100).toFixed(1)}% confidence)`);
      break;

    case "log":
      addLog(data.level, data.message);
      break;

    case "complete":
      renderExtractedData(data.fields, data.quarantined_fields);
      lastResults = data;
      document.getElementById("scrapeBtn").disabled = false;
      document.getElementById("scrapeBtn").innerHTML = `<i data-lucide="play" class="h-4 w-4 fill-current"></i><span>Execute Scrape</span>`;
      lucide.createIcons();
      document.getElementById("pipelineStatusBadge").innerText = `Complete (${data.latency_ms}ms)`;
      document.getElementById("pipelineStatusBadge").className = "text-xs font-mono px-2.5 py-0.5 rounded bg-emerald-950 text-emerald-400 border border-emerald-800";
      addLog("success", `Extraction complete in ${data.latency_ms}ms with ${Object.keys(data.fields).length} fields extracted.`);
      break;

    case "error":
      addLog("error", data.message);
      document.getElementById("scrapeBtn").disabled = false;
      document.getElementById("scrapeBtn").innerHTML = `<i data-lucide="play" class="h-4 w-4 fill-current"></i><span>Execute Scrape</span>`;
      lucide.createIcons();
      document.getElementById("pipelineStatusBadge").innerText = "Error";
      document.getElementById("pipelineStatusBadge").className = "text-xs font-mono px-2.5 py-0.5 rounded bg-red-950 text-red-400 border border-red-800";
      break;
  }
}

// Trigger Scrape Job
function triggerScrape() {
  const url = document.getElementById("targetUrl").value.trim();
  const prompt = document.getElementById("userPrompt").value.trim();
  const simulateDrift = document.getElementById("simulateDrift").checked;

  if (!url) {
    alert("Please enter a target URL.");
    return;
  }

  const btn = document.getElementById("scrapeBtn");
  btn.disabled = true;
  btn.innerHTML = `<span class="animate-spin mr-2">⏳</span><span>Extracting...</span>`;

  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({
      url: url,
      prompt: prompt || null,
      simulate_drift: simulateDrift
    }));
  } else {
    alert("Backend connection offline. Retrying...");
  }
}

// Set Preset
function setPreset(url, prompt) {
  document.getElementById("targetUrl").value = url;
  document.getElementById("userPrompt").value = prompt;
}

// Update 9-Layer Visual Card
function updateLayerCard(layerNum, status, title, detail) {
  const card = document.getElementById(`layerCard${layerNum}`);
  if (!card) return;

  const statusEl = card.querySelector(".layer-status");
  const detailEl = card.querySelector(".layer-detail");
  const iconEl = card.querySelector(".layer-icon");

  card.className = "layer-card p-3.5 rounded-xl bg-dark-card border transition-all flex flex-col justify-between";

  if (status === "active") {
    card.classList.add("layer-active");
    statusEl.innerText = "Processing...";
    statusEl.className = "mt-3 text-[10px] font-mono text-cyan-400 font-bold";
    iconEl.className = "h-4 w-4 text-cyan-400 layer-icon animate-pulse";
  } else if (status === "healing") {
    card.classList.add("layer-healing");
    statusEl.innerText = "Healed ✓";
    statusEl.className = "mt-3 text-[10px] font-mono text-amber-400 font-bold";
    iconEl.className = "h-4 w-4 text-amber-400 layer-icon";
  } else if (status === "success") {
    card.classList.add("layer-success");
    statusEl.innerText = "Passed ✓";
    statusEl.className = "mt-3 text-[10px] font-mono text-emerald-400 font-semibold";
    iconEl.className = "h-4 w-4 text-emerald-400 layer-icon";
  } else if (status === "idle") {
    card.style.borderColor = "#1e293b";
    statusEl.innerText = "Skipped";
    statusEl.className = "mt-3 text-[10px] font-mono text-slate-600";
    iconEl.className = "h-4 w-4 text-slate-600 layer-icon";
  }

  if (detail) detailEl.innerText = detail;
}

// Reset all layer cards
function resetLayerCards() {
  for (let i = 1; i <= 9; i++) {
    const card = document.getElementById(`layerCard${i}`);
    if (card) {
      card.className = "layer-card p-3.5 rounded-xl bg-dark-card border border-dark-border transition-all flex flex-col justify-between";
      card.querySelector(".layer-status").innerText = "Idle";
      card.querySelector(".layer-status").className = "mt-3 text-[10px] font-mono text-slate-500 layer-status";
      card.querySelector(".layer-icon").className = "h-4 w-4 text-slate-500 layer-icon";
    }
  }
}

// Show AI Self-Healing Diff Inspector
function showHealingDiff(data) {
  const section = document.getElementById("healingSection");
  section.classList.remove("hidden");

  document.getElementById("diffOldSelector").innerText = data.old_selector;
  document.getElementById("diffNewSelector").innerText = data.repaired_selector;
}

// Render Extracted Records in Table
function renderExtractedData(fields, quarantined) {
  const tbody = document.getElementById("extractedDataTable");
  tbody.innerHTML = "";

  if (!fields || Object.keys(fields).length === 0) {
    tbody.innerHTML = `<tr><td colspan="3" class="py-8 text-center text-slate-500">No data extracted.</td></tr>`;
    return;
  }

  for (const [key, value] of Object.entries(fields)) {
    const isQuarantined = quarantined && quarantined.includes(key);
    const tr = document.createElement("tr");
    tr.className = "hover:bg-dark-surface/60 transition";

    const statusBadge = isQuarantined || value === null
      ? `<span class="px-2 py-0.5 text-[10px] font-bold rounded bg-red-950 text-red-400 border border-red-800">QUARANTINED</span>`
      : `<span class="px-2 py-0.5 text-[10px] font-bold rounded bg-emerald-950 text-emerald-400 border border-emerald-800">SUCCESS</span>`;

    const valDisplay = isQuarantined || value === null
      ? `<span class="text-slate-500 italic">Quarantined (Pending Review)</span>`
      : `<span class="text-slate-100 font-mono">${escapeHtml(String(value))}</span>`;

    tr.innerHTML = `
      <td class="py-3 px-4 font-semibold text-cyan-300 font-mono">${key}</td>
      <td class="py-3 px-4">${valDisplay}</td>
      <td class="py-3 px-4">${statusBadge}</td>
    `;
    tbody.appendChild(tr);
  }
}

// Append Terminal Log
function addLog(level, message) {
  const terminal = document.getElementById("terminalLogs");
  const row = document.createElement("div");
  const time = new Date().toLocaleTimeString();

  let color = "text-slate-400";
  let prefix = "[info]";

  if (level === "warn") {
    color = "text-amber-400";
    prefix = "[heal]";
  } else if (level === "error") {
    color = "text-red-400";
    prefix = "[error]";
  } else if (level === "success") {
    color = "text-emerald-400";
    prefix = "[success]";
  } else if (level === "system") {
    color = "text-cyan-400";
    prefix = "[system]";
  }

  row.className = `${color} flex items-start space-x-2 leading-relaxed`;
  row.innerHTML = `<span class="text-slate-600 select-none">${time}</span><span class="font-bold select-none">${prefix}</span><span>${escapeHtml(message)}</span>`;

  terminal.appendChild(row);
  terminal.scrollTop = terminal.scrollHeight;

  logCount++;
  document.getElementById("logCounter").innerText = `${logCount} events`;
}

function escapeHtml(str) {
  return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function copyResultsJSON() {
  if (!lastResults.fields) {
    alert("No records to copy yet.");
    return;
  }
  navigator.clipboard.writeText(JSON.stringify(lastResults, null, 2));
  alert("Extracted JSON copied to clipboard!");
}

function downloadResultsJSON() {
  if (!lastResults.fields) {
    alert("No records to download yet.");
    return;
  }
  const blob = new Blob([JSON.stringify(lastResults, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `extracted_${lastResults.domain || 'data'}_${Date.now()}.json`;
  a.click();
}

// Connect on load
window.addEventListener("DOMContentLoaded", () => {
  connectWebSocket();
});
