// ✅ aiAssistant.js — Handles AI Assistant Tab

document.addEventListener('DOMContentLoaded', () => {
  const logSelect = document.getElementById("ai-log-select");
  const output = document.getElementById("ai-output");

  async function loadLogList() {
    logSelect.innerHTML = '<option>Loading...</option>';
    try {
      const res = await fetch('/list_logs');
      const data = await res.json();
      logSelect.innerHTML = '<option value="">-- Select Target File --</option>';
      data.logs.forEach(log => {
        const opt = document.createElement('option');
        opt.value = log;
        opt.textContent = log;
        logSelect.appendChild(opt);
      });
    } catch (e) {
      logSelect.innerHTML = '<option value="">(Failed to load logs)</option>';
    }
  }

  document.getElementById("ai-refresh-btn").addEventListener("click", loadLogList);

  document.getElementById("ai-analyze-btn").addEventListener("click", async () => {
    const log = logSelect.value;
    if (!log) return alert("Please select a log file.");

    output.innerHTML = "🧠 Analyzing log file... Please wait.";

    try {
      const res = await fetch("/ai/inspect_log", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ log })
      });
      const data = await res.json();

    output.innerHTML = `
      <h3>📄 Summary</h3>
      <pre>${data.summary}</pre>
      <h3>🔝 Top Threads</h3>
      <ul>${data.top_threads.map(t => `<li>${t[0]} — ${t[1]} lines</li>`).join('')}</ul>
      <h3>🔝 Top Services</h3>
      <ul>${data.top_services.map(s => `<li>${s[0]} — ${s[1]} lines</li>`).join('')}</ul>
      <h3>🚨 Anomalies</h3>
      <ul>${data.anomalies.length ? data.anomalies.map(a => `<li>${a}</li>`).join('') : '<li>None detected</li>'}</ul>
      ${data.failing_services && data.failing_services.length ? `
        <h3 style="margin-top:1rem; color:#c0392b;">🛠️ Services With Most Errors</h3>
        <ul style="padding-left: 1rem; color: #e74c3c; font-weight: bold;">
          ${data.failing_services.map(s => `<li>❌ ${s}</li>`).join('')}
        </ul>
      ` : ''}
      <h3>🧠 Recommendations</h3>
      <ul>${data.recommendations.map(r => `<li>${r}</li>`).join('')}</ul>
    `;
    } catch (e) {
      output.innerHTML = `❌ Failed to analyze log: ${e.message}`;
    }
  });

  // Auto-load on tab open
  loadLogList();
});

