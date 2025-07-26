// Main JS scripts

 function escapeHTML(str) {
   return str.replace(/[&<>'"]/g, char => ({
	 '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
   }[char]));
 }
 
 function highlightLogLevel(log) {
   const escaped = escapeHTML(log);
   return escaped
	 .replace(/\[ERROR\]/g, `<span style="color:red;font-weight:bold;">[ERROR]</span>`)
	 .replace(/\[WARN\]/g, `<span style="color:orange;">[WARN]</span>`)
	 .replace(/\[FATAL\]/g, `<span style="background:red;color:white;">[FATAL]</span>`);
 }
 
async function fetchLogs() {
  const res = await fetch('/list_logs');
  const data = await res.json();

  const logSelect = document.getElementById('logSelect');
  logSelect.innerHTML = '<option value="">-- Select a log file --</option>';

  data.logs
	.sort((a, b) => a.localeCompare(b, undefined, { numeric: true, sensitivity: 'base' }))
	.forEach(log => {
	  const option = document.createElement('option');
	  option.value = log;
	  option.textContent = log;
	  logSelect.appendChild(option);
	});

  document.getElementById('logSelect').value = "";

  const logTableBody = document.querySelector('#logTable tbody');
  if (logTableBody) {
	logTableBody.innerHTML = "";
  }

  document.getElementById('xmlContent').style.display = "none";
  resetErrorSummary();
}      
 
async function fetchRQRS(log) {

  const res = await fetch(`/get_rqrs?log=${encodeURIComponent(log)}`);
  const data = await res.json();
  
  window.rqrsCache = data.rqrs; // ✅ Cache for XML lookups

  // 🧩 Update table
  const rqrsTableBody = document.querySelector("#rqrsTable tbody");
  rqrsTableBody.innerHTML = ""; // Clear old rows

  if (!data.rqrs || data.rqrs.length === 0) {
	const row = document.createElement("tr");
	const td = document.createElement("td");
	td.textContent = "No Data Found";
	td.colSpan = 3;
	td.style.textAlign = "center";
	row.appendChild(td);
	rqrsTableBody.appendChild(row);
	return;
  }

  data.rqrs.forEach((entry, idx) => {
	const line = entry.line ?? "??";
	const thread = entry.thread ?? "UNKNOWN";
	const tag = entry.tag ?? "???";

	// 🔗 Make tag clickable to show XML
	const tagCell = document.createElement("td");
	const tagLink = document.createElement("a");
	tagLink.href = "#";
	tagLink.textContent = tag + (entry.has_issue ? " ⚠️" : "");
	tagLink.onclick = () => {
	  fetchAndDisplayXMLForModal(log, idx, tag);
	  return false;
	};

	tagCell.appendChild(tagLink);
	if (entry.has_issue) tagCell.classList.add("rqrs-warning");

	// 📄 Build table row
	const row = document.createElement("tr");

	const lineCell = document.createElement("td");
	lineCell.textContent = line;

	const threadCell = document.createElement("td");
	threadCell.textContent = thread;

	row.appendChild(lineCell);
	row.appendChild(threadCell);
	row.appendChild(tagCell);

	rqrsTableBody.appendChild(row);
  });

  // ✅ Enable filters only if data exists
  if (data.rqrs && data.rqrs.length > 0) {
	document.querySelectorAll("#rqrsFilterControls input, #rqrsClearFiltersBtn")
	  .forEach(el => el.disabled = false);
  }
}

function openLogContextModal(logFile, lineNumber) {
  const modal = document.getElementById("logContextModal");
  const content = document.getElementById("logContextText");

  // Show loading message first (optional)
  content.textContent = "⏳ Loading log context...";
  
  fetch(`/log_context?log=${encodeURIComponent(logFile)}&line=${lineNumber}`)
	.then(res => {
	  if (!res.ok) {
		throw new Error("Log context fetch failed");
	  }
	  return res.json();
	})
	.then(data => {
	  content.textContent = data.lines.join("\n");  // Show the lines
	  modal.style.display = "flex";  // ✅ Show modal ONLY if successful
	})
	.catch(err => {
	  console.error("❌ Failed to load log context:", err);
	  alert("⚠️ Unable to fetch log context.");
	});
}

// ✅ Filter RQRS Table Rows
function applyRqrsFilters() {
  const threadVal = document.getElementById("rqrsThreadFilter").value.toLowerCase();
  const tagVal = document.getElementById("rqrsTagFilter").value.toLowerCase();  // <-- added
  const dlxChecked = document.getElementById("rqrsDlxCheckbox").checked;
  const errorChecked = document.getElementById("rqrsErrorCheckbox").checked;

  document.querySelectorAll("#rqrsTable tbody tr").forEach(row => {
	const threadText = row.children[1].textContent.toLowerCase();
	const tagText = row.children[2].textContent.toLowerCase();

	const matchThread = threadText.includes(threadVal);
	const matchTag = tagText.includes(tagVal);  // <-- added
	const matchDlx = !dlxChecked || tagText.startsWith("dlx_");
	const matchError = !errorChecked || tagText.includes("⚠️");

	row.style.display = (matchThread && matchTag && matchDlx && matchError) ? "" : "none";
  });
}

document.addEventListener("DOMContentLoaded", () => {
  const threadFilter = document.getElementById("rqrsThreadFilter");
  const tagFilter = document.getElementById("rqrsTagFilter");
  const dlxCheckbox = document.getElementById("rqrsDlxCheckbox");
  const errorCheckbox = document.getElementById("rqrsErrorCheckbox");
  const clearBtn = document.getElementById("rqrsClearFiltersBtn");

  function applyRqrsFilters() {
	const threadVal = threadFilter?.value?.toLowerCase() || "";
	const tagVal = tagFilter?.value?.toLowerCase() || "";
	const dlxOnly = dlxCheckbox?.checked;
	const errorOnly = errorCheckbox?.checked;

	document.querySelectorAll("#rqrsTable tbody tr").forEach(row => {
	  const thread = row.children[1].textContent.toLowerCase();
	  const tag = row.children[2].textContent.toLowerCase();

	  const matchThread = thread.includes(threadVal);
	  const matchTag = tag.includes(tagVal);
	  const matchDlx = !dlxOnly || tag.startsWith("dlx_");
	  const matchError = !errorOnly || tag.includes("⚠️");

	  row.style.display = (matchThread && matchTag && matchDlx && matchError) ? "" : "none";
	});
  }

  if (threadFilter) threadFilter.addEventListener("input", applyRqrsFilters);
  if (tagFilter) tagFilter.addEventListener("input", applyRqrsFilters);
  if (dlxCheckbox) dlxCheckbox.addEventListener("change", applyRqrsFilters);
  if (errorCheckbox) errorCheckbox.addEventListener("change", applyRqrsFilters);

  if (clearBtn) {
	clearBtn.addEventListener("click", () => {
	  if (threadFilter) threadFilter.value = "";
	  if (tagFilter) tagFilter.value = "";
	  if (dlxCheckbox) dlxCheckbox.checked = false;
	  if (errorCheckbox) errorCheckbox.checked = false;
	  applyRqrsFilters();
	});
  }
});

async function analyzeLogs() {
  const mode = document.querySelector('input[name="analyzeMode"]:checked').value;
  const logSelect = document.getElementById("logSelect");
  const selectedLog = logSelect ? logSelect.value : null;

	// ✅ Check if the log list dropdown is empty (i.e., no logs available)
	const logSelectOptions = logSelect ? Array.from(logSelect.options) : [];
	const hasLogFiles = logSelectOptions.length > 0;

	// ✅ Show modal if NO log files exist — applies to both "specific" and "all" modes
	if (!hasLogFiles) {
	  showNoLogsModal();  // This function will open the new modal we created
	  console.warn("🚫 No logs to analyze.");
	  return;
	}


	// 🔒 Block invalid request and show modal if no logs are found
	if (mode === "specific" && (!selectedLog || selectedLog === "")) {
	  console.warn("🚫 Skipping analysis: no file selected.");
	  showNoLogsModal(); // 👈 NEW MODAL
	  return; // 🛑 Prevent accidental analysis
	}

  console.log("🧪 Sending analysis request:", { mode, log: selectedLog });
  document.getElementById("analysisOverlay").style.display = "flex";

  // ✅ Ensure rqrsPromise is visible in finally block
  let rqrsPromise = Promise.resolve();

  try {
	const res = await fetch("/analyze_logs", {
	  method: "POST",
	  headers: { "Content-Type": "application/json" },
	  body: JSON.stringify({ mode: mode, log: selectedLog })
	});

	let result;
	try {
	  result = await res.json();
	} catch (jsonErr) {
	  throw new Error("Server returned invalid JSON: " + jsonErr.message);
	}

	console.log("✅ Analysis result:", result);
	
	// ✅ Handle edge case: "All Logs" mode returns empty results (no log files exist)
	if (
	  mode === "all" &&
	  (!result.counts || (
		(result.counts.FATAL || 0) === 0 &&
		(result.counts.ERROR || 0) === 0 &&
		(result.counts.WARN || 0) === 0
	  ))
	) {
	  showNoLogsModal(); // Show no errors found modal
	  console.warn("🚫 No errors found from the logs to analyze (All Logs mode).");
	  return;
	}


	// ✅ Show error modal if backend sent an error message
	if (result.error) {
	  showAnalysisErrorModal(result.error);
	  return;
	}

	if (!res.ok || !result || !result.counts) {
	  showAnalysisErrorModal("Failed to analyze logs.");
	  return;
	}

	const counts = result.counts || {};
	document.getElementById("fatalCount").textContent = counts.FATAL || 0;
	document.getElementById("errorCount").textContent = counts.ERROR || 0;
	document.getElementById("warnCount").textContent = counts.WARN || 0;

	const total = (counts.FATAL || 0) + (counts.ERROR || 0) + (counts.WARN || 0);
	const toPercent = (val) => total > 0 ? (val / total * 100) + "%" : "0%";
	document.getElementById("fatalBar").style.width = toPercent(counts.FATAL || 0);
	document.getElementById("errorBar").style.width = toPercent(counts.ERROR || 0);
	document.getElementById("warnBar").style.width = toPercent(counts.WARN || 0);

	const tableBody = document.querySelector("#errorDetailsTable tbody");
	tableBody.innerHTML = "";

	// 🔄 Clear filters when resetting table
	document.getElementById("threadFilter").value = "";
	document.getElementById("serviceFilter").value = "";
	applyFilters();

	// ✅ Handle case where there are no error rows
	if ((result.errors || []).length === 0) {
	  const tr = document.createElement("tr");
	  const td = document.createElement("td");
	  td.textContent = "No Data Found";
	  td.colSpan = 5;
	  td.style.textAlign = "center";
	  tr.appendChild(td);
	  tableBody.appendChild(tr);
	} else {
	  (result.errors || []).forEach((entry) => {
		const row = document.createElement("tr");

		const createCell = (text) => {
		  const cell = document.createElement("td");
		  cell.textContent = text;
		  return cell;
		};

		const lineCell = document.createElement("td");
		const lineLink = document.createElement("a");
		lineLink.href = "#";
		lineLink.textContent = entry.line_number;
		lineLink.onclick = () => {
		  openLogContextModal(entry.log_file, entry.line_number);
		  return false; // prevent default jump
		};
		lineCell.appendChild(lineLink);

		row.appendChild(createCell(entry.log_file));
		row.appendChild(lineCell);
		row.appendChild(createCell(entry.thread_id));
		row.appendChild(createCell(entry.service));

		const errorMsgCell = document.createElement("td");
		errorMsgCell.innerHTML = highlightLogLevel(entry.error_message);
		row.appendChild(errorMsgCell);

		tableBody.appendChild(row);
	  });
	}

	// ✅ After error summary is updated, populate RQRS (only for specific mode)
	if (mode === "specific" && selectedLog) {
	  rqrsPromise = fetchRQRS(selectedLog);
	} else {
	  // 🧩 Update table
	  const rqrsTableBody = document.querySelector("#rqrsTable tbody");
	  rqrsTableBody.innerHTML = ""; // Clear old rows
	}

	// ✅ Enable/Disable Filters + Clear Button Dynamically
	const hasData = (result.errors || []).length > 0;
	document.getElementById("threadFilter").disabled = !hasData;
	document.getElementById("serviceFilter").disabled = !hasData;
	document.getElementById("clearFiltersBtn").disabled = !hasData;

	// ✅ Enable/disable thread & service filters based on table rows
	const threadInput = document.getElementById("threadFilter");
	const serviceInput = document.getElementById("serviceFilter");
	const hasRows = tableBody.rows.length > 0;
	threadInput.disabled = !hasRows;
	serviceInput.disabled = !hasRows;

  } catch (err) {
	console.error("Error analyzing logs:", err);
	showAnalysisErrorModal("Unexpected error occurred while analyzing logs.");
  } finally {
	rqrsPromise.finally(() => {
	  document.getElementById("analysisOverlay").style.display = "none";
	});
  }
}

// ✅ Clear both filters and reapply table filtering
document.getElementById("clearFiltersBtn").addEventListener("click", () => {
  const threadInput = document.getElementById("threadFilter");
  const serviceInput = document.getElementById("serviceFilter");

  threadInput.value = "";
  serviceInput.value = "";

  applyFilters(); // ← this should already exist and do the actual table filtering
});

// ✅ Show the "No Logs Found" modal
function showNoLogsModal() {
  const modal = document.getElementById("noLogsModal");
  if (modal) {
	modal.style.display = "flex";
  }
}

// ✅ Hide the "No Logs Found" modal
function closeNoLogsModal() {
  const modal = document.getElementById("noLogsModal");
  if (modal) {
	modal.style.display = "none";
  }
}

function closeLogContextModal() {
  const modal = document.getElementById("logContextModal");
  const content = document.getElementById("logContextText");
  modal.style.display = "none";
  content.textContent = "";
}

//////////////////////////////////

function showAnalysisErrorModal(message) {
  document.getElementById("analysisErrorMessage").textContent = message || "Unknown error occurred.";
  const modal = document.getElementById("analysisErrorModal");
  modal.classList.add("show");
}

function closeAnalysisErrorModal() {
  const modal = document.getElementById("analysisErrorModal");
  modal.classList.remove("show");
}

function updateSummary(data) {
  const fatalCount = document.getElementById("fatalCount");
  const errorCount = document.getElementById("errorCount");
  const warnCount = document.getElementById("warnCount");

  const fatalBar = document.getElementById("fatalBar");
  const errorBar = document.getElementById("errorBar");
  const warnBar = document.getElementById("warnBar");

  let totalFatal = 0, totalError = 0, totalWarn = 0;

  for (const counts of Object.values(data.errors || {})) {
	totalFatal += counts.fatal;
	totalError += counts.error;
	totalWarn += counts.warn;
  }

  const total = totalFatal + totalError + totalWarn;

  fatalCount.textContent = totalFatal;
  errorCount.textContent = totalError;
  warnCount.textContent = totalWarn;

  // Set bar widths proportionally
  fatalBar.style.width = total ? `${(totalFatal / total) * 100}%` : "0%";
  errorBar.style.width = total ? `${(totalError / total) * 100}%` : "0%";
  warnBar.style.width = total ? `${(totalWarn / total) * 100}%` : "0%";
}
 
 function resetErrorSummary() {
   document.getElementById('fatalCount').textContent = '0';
   document.getElementById('errorCount').textContent = '0';
   document.getElementById('warnCount').textContent = '0';
   document.getElementById('fatalBar').style.width = '0%';
   document.getElementById('errorBar').style.width = '0%';
   document.getElementById('warnBar').style.width = '0%';
 }
 
 function showToast(message) {
   const toast = document.getElementById('toast');
   toast.textContent = message;
   toast.style.display = 'block';
   setTimeout(() => {
	 toast.style.display = 'none';
   }, 2000);
 }
 
function resetDownloadModal() {
  scpParams = {};
  document.getElementById("scpHost").value = "";
  document.getElementById("scpUser").value = "remotedeploy";
  document.getElementById("scpDir").value = "/datalex/logs/";
  document.getElementById("scpPattern").value = "matrixtdp4.log*";
  const downloadBtn = document.getElementById("downloadLogsBtn");
  const cancelBtn = document.getElementById("cancelDownloadBtn");
  const spinner = downloadBtn.querySelector(".spinner");
  const btnText = downloadBtn.querySelector(".btn-text");
  downloadBtn.disabled = false;
  cancelBtn.disabled = false;
  cancelBtn.textContent = "Close Window";
  spinner.style.display = "none";
  btnText.textContent = "Download Logs";
  document.getElementById("downloadSpinner").style.display = "none";
  document.getElementById("downloadModal").dataset.state = "idle";
  document.getElementById("progressText").textContent = "";
  document.querySelector(".progress-fill").style.width = "0%";
  document.getElementById("downloadProgressWrapper").style.display = "none";
}
 
async function proceedWithDownload(clearExisting) {
  const overlay = document.getElementById("downloadModal");
  const spinner = document.getElementById("downloadSpinner");
  const progressWrapper = document.getElementById("downloadProgressWrapper");
  const progressFill = document.querySelector(".progress-fill");
  const progressText = document.getElementById("progressText");

  isDownloading = true;
  abortRequested = false;
  controller = new AbortController();
  const signal = controller.signal;

  overlay.dataset.state = "loading";
  spinner.style.display = "block";
  spinner.innerHTML = "⏳";
  progressWrapper.style.display = "block";
  progressFill.style.width = "0%";
  progressText.textContent = "0% | Starting...";

  document.querySelectorAll("#downloadModal button").forEach(btn => {
	if (btn.id !== "cancelDownloadBtn") btn.disabled = true;
  });

  const cancelBtn = document.getElementById("cancelDownloadBtn");
  cancelBtn.disabled = false;
  cancelBtn.textContent = "Abort Download";

  const { host, username, path, pattern } = scpParams;

  try {
	// Start progress listener
	if (scpProgressSource) scpProgressSource.close();
	scpProgressSource = new EventSource("/scp_progress");

	scpProgressSource.onmessage = (event) => {
	  const data = JSON.parse(event.data);
	  const percent = Math.min(100, Math.round(data.percent || 0));
	  const eta = data.eta && data.eta > 0
		? `ETA: ${Math.floor(data.eta / 60)}m ${data.eta % 60}s`
		: "";
	  progressText.textContent = `${percent}% ${eta}`;
	  progressFill.style.width = `${percent}%`;
	};

	const res = await fetch("/download_remote_logs", {
	  method: "POST",
	  headers: { "Content-Type": "application/json" },
	  body: JSON.stringify({ host, username, remote_path: path, pattern, clear_existing: clearExisting }),
	  signal
	});

	const result = await res.json();
	if (result.status === "success") {
	  showResultModal("✅ Logs downloaded and processed successfully.");
	  await fetchLogs();
	} else if (result.status === "partial") {
	  showResultModal("⚠️ Some logs were downloaded, but decompression failed.");
	} else {
	  showResultModal(`❌ Download failed: ${result.message}`);
	}
  } catch (err) {
	if (abortRequested) {
	  showToast("❌ Download aborted.");
	} else {
	  showToast("❌ Network error during download.");
	}
  } finally {
	if (scpProgressSource) {
	  scpProgressSource.close();
	  scpProgressSource = null;
	}

	progressText.textContent = "Finalizing...";
	progressFill.style.width = "100%";

	setTimeout(() => {
	  progressWrapper.style.display = "none";
	  progressText.textContent = "";
	  progressFill.style.width = "0%";
	  spinner.innerHTML = "";
	  spinner.style.display = "none";
	  overlay.style.display = "none";
	  document.querySelectorAll("#downloadModal button").forEach(btn => btn.disabled = false);
	  isDownloading = false;
	  abortRequested = false;
	  controller = null;
	}, 1000);
  }
}
 
 async function handleRemoteLogDownload() {
   const host = document.getElementById("scpHost").value.trim();
   const username = document.getElementById("scpUser").value.trim() || "remotedeploy";
   const path = document.getElementById("scpDir").value.trim() || "/datalex/logs/jboss";
   const pattern = document.getElementById("scpPattern").value.trim() || "matrixtdp4.log*";
   const modal = document.getElementById("downloadModal");
   const downloadBtn = document.getElementById("downloadLogsBtn");
   const cancelBtn = document.getElementById("cancelDownloadBtn");
   const spinner = downloadBtn.querySelector(".spinner");
   const btnText = downloadBtn.querySelector(".btn-text");
   scpParams = { host, username, path, pattern };
 
   if (!host) {
	 showToast("❌ Remote host alias is required.");
	 return;
   }
   if (!path) {
	 showToast("❌ Remote log directory is required.");
	 return;
   }
 
   downloadBtn.disabled = true;
   cancelBtn.disabled = true;
   spinner.style.display = "inline-block";
   btnText.textContent = "⏳ Downloading...";
 
   try {
	 const response = await fetch("/list_logs");
	 const data = await response.json();
	 const existingFiles = data.logs || [];
	 if (existingFiles.length > 0) {
	   document.getElementById("overwriteConfirmModal").style.display = "flex";
	   document.getElementById("keepLogsBtn").onclick = () => {
		 document.getElementById("overwriteConfirmModal").style.display = "none";
		 proceedWithDownload(false);
	   };
	   document.getElementById("deleteLogsBtn").onclick = () => {
		 document.getElementById("overwriteConfirmModal").style.display = "none";
		 document.getElementById("finalDeleteConfirmModal").style.display = "flex";
	   };
	   return;
	 }
   } catch (e) {
	 showToast("⚠️ Could not check existing files.");
   }
 
   await proceedWithDownload(false);
 }
 
 function showResultModal(message) {
   const resultModal = document.getElementById("downloadResultModal");
   const resultMessage = document.getElementById("resultMessage");
   const resultCountdown = document.getElementById("resultCountdown");
   const closeBtn = document.getElementById("closeResultBtn");
   const progressWrapper = document.getElementById("downloadProgressWrapper");
   const progressText = document.getElementById("progressText");
   const progressFill = document.querySelector(".progress-fill");
 
   resultMessage.innerHTML = message;
   resultModal.style.display = "flex";
 
   let seconds = 10;
   resultCountdown.textContent = `The download window will close in ${seconds}s if no response from the user.`;
 
   const interval = setInterval(() => {
	 seconds -= 1;
	 resultCountdown.textContent = `The download window will close in ${seconds}s if no response from the user.`;
	 if (seconds === 0) {
	   clearInterval(interval);
	   resultModal.style.display = "none";
	   document.getElementById("downloadModal").style.display = "none";
	   resetDownloadModal();
	 }
   }, 1000);
 
   closeBtn.onclick = () => {
	 clearInterval(interval);
	 progressWrapper.style.display = "none";
	 progressText.textContent = "";
	 progressFill.style.width = "0%";
	 resultModal.style.display = "none";
	 document.getElementById("downloadModal").style.display = "none";
	 resetDownloadModal();
   };
 }
 
 window.addEventListener("DOMContentLoaded", () => {
   const themeBtn = document.getElementById("themeToggleBtn");
   if (themeBtn) {
	 themeBtn.addEventListener("click", () => {
	   const currentTheme = document.documentElement.getAttribute("data-theme");
	   const newTheme = currentTheme === "dark" ? "light" : "dark";
	   document.documentElement.setAttribute("data-theme", newTheme);
	 });
   }
 
   const openBtn = document.getElementById("openDownloadModalBtn");
   if (openBtn) {
	 openBtn.addEventListener("click", () => {
	   resetDownloadModal();
	   document.getElementById("downloadModal").style.display = "flex";
	 });
   }
 
	const cancelBtn = document.getElementById("cancelDownloadBtn");
	if (cancelBtn) {
	  cancelBtn.addEventListener("click", () => {
		const modalState = document.getElementById("downloadModal").dataset.state;
		if (modalState === "loading") {
		  document.getElementById("abortConfirmModal").style.display = "flex";
		} else {
		  document.getElementById("downloadModal").style.display = "none";
		}
	  });
	}
 
   const abortYes = document.getElementById("confirmAbortYes");
   if (abortYes) {
	abortYes.addEventListener("click", () => {
	  if (controller) {
		controller.abort(); // Cancels fetch
		abortRequested = true;
	  }

	  // 🛠 This tells backend to kill the SCP subprocess
	  fetch("/abort_download", { method: "POST" })
		.then(res => res.json())
		.then(data => {
		  console.log("✅ Abort response from backend:", data);
		  showToast("❌ Download aborted.");
		})
		.catch(err => {
		  console.error("❌ Error calling /abort_download:", err);
		  showToast("❌ Abort failed.");
		});

	  scpParams = {};
	  document.getElementById("abortConfirmModal").style.display = "none";
	  document.getElementById("downloadModal").style.display = "none";
	  document.getElementById("overwriteConfirmModal").style.display = "none";
	  document.getElementById("downloadSpinner").style.display = "none";
	  document.getElementById("downloadProgressWrapper").style.display = "none";
	  document.getElementById("downloadModal").dataset.state = "idle";
	  document.getElementById("cancelDownloadBtn").textContent = "Close Window";
	});
   }
 
   const abortNo = document.getElementById("confirmAbortNo");
   if (abortNo) {
	 abortNo.addEventListener("click", () => {
	   document.getElementById("abortConfirmModal").style.display = "none";
	 });
   }
 

   // fetchLogs();


	document.getElementById("confirmFinalDeleteYes").addEventListener("click", () => {
	  document.getElementById("finalDeleteConfirmModal").style.display = "none";
	  document.getElementById("downloadModal").style.display = "flex";
	  proceedWithDownload(true);
	});

	document.getElementById("confirmFinalDeleteNo").addEventListener("click", () => {
	  document.getElementById("finalDeleteConfirmModal").style.display = "none";
	  document.getElementById("downloadModal").style.display = "none";
	});

 });

 async function fetchAndDisplayXML(log, index) {
   try {
	 const res = await fetch(`/get_rqrs_content?log=${encodeURIComponent(log)}&entry=${index}`);
	 if (!res.ok) throw new Error("Failed to fetch XML");
 
	 const raw = await res.text();
	 if (!raw.trim()) {
	   console.log("⚠️ XML response is empty.");
	   throw new Error("Empty XML");
	 }
 
	 const match = raw.match(/<([a-zA-Z0-9:_-]+)(\s|>)/);
	 if (!match) {
	   console.log("❌ No valid XML root tag found.");
	   throw new Error("Malformed XML");
	 }
 
	 const rawXML = raw.slice(raw.indexOf(match[0])).trim();
	 const formatted = formatXML(rawXML);
 
	 const xmlDisplay = document.getElementById("xmlDisplay");
	 const xmlContainer = document.getElementById("xmlContent");
 
	 xmlDisplay.textContent = formatted;
	 xmlDisplay.style.display = "block";
	 xmlContainer.style.display = "block";
 
	 hljs.highlightElement(xmlDisplay);
	 console.log("✅ XML displayed in UI.");
   } catch (err) {
	 showToast("❌ Failed to load XML.");
   }
 }
 
	function formatXML(xml) {
	  const PADDING = '  ';
	  const reg = /(>)(<)(\/*)/g;
	  let formatted = '', pad = 0;
	  xml = xml.replace(reg, '$1\r\n$2$3');
	  xml.split('\r\n').forEach(node => {
		let indent = 0;
		if (node.match(/.+<\/\w[^>]*>$/)) indent = 0;
		else if (node.match(/^<\/\w/)) pad = pad > 0 ? pad - 1 : 0;
		else if (node.match(/^<\w([^>]*[^/])?>.*$/)) indent = 1;
		formatted += PADDING.repeat(pad) + node + '\r\n';
		pad += indent;
	  });
	  return formatted;
	}
		 
	document.getElementById('threadFilter').addEventListener('input', applyFilters);
	document.getElementById('serviceFilter').addEventListener('input', applyFilters);
 
	function applyFilters() {
	  const threadVal = document.getElementById('threadFilter').value.toLowerCase();
	  const serviceVal = document.getElementById('serviceFilter').value.toLowerCase();
	  document.querySelectorAll('#errorDetailsTable tbody tr').forEach(row => {
		const thread = row.children[2].textContent.toLowerCase();
		const service = row.children[3].textContent.toLowerCase();
		row.style.display = (thread.includes(threadVal) && service.includes(serviceVal)) ? '' : 'none';
	  });
	}
	
	// 🧹 Clears both filter inputs and resets table
	function clearFilters() {
	  document.getElementById('threadFilter').value = "";
	  document.getElementById('serviceFilter').value = "";
	  applyFilters();
	}

  ////////////////////////////////////////////
  // SCP functions - Progress bar
  ////////////////////////////////////////////
  function startScpProgressPolling() {
	scpSource = new EventSource("/scp_progress");
	scpSource.onmessage = function(event) {
	  const progress = JSON.parse(event.data);
	  const percent = progress.percent;
	  const eta = progress.eta;
	  $("#scp-progress-bar").css("width", percent + "%").attr("aria-valuenow", percent);
	  $("#scp-progress-text").text(`${percent}% | ETA: ${eta}s`);
	  if (percent >= 100 && scpSource) {
		scpSource.close();
		$("#scp-modal").modal("hide");
		alert("✅ Download complete.");
	  }
	};
  }

  ////////////////////////////////////////////
  // SCP functions - Downloading files
  ////////////////////////////////////////////
  function downloadLogs() {
	const host = $("#scp-host").val();
	const pattern = $("#scp-pattern").val() || "matrixtdp4.log*";
	const clearExisting = $("#scp-clear-existing").is(":checked");

	$("#scp-progress-bar").css("width", "0%").attr("aria-valuenow", 0);
	$("#scp-progress-text").text("0% | ETA: ∞");
	$("#scp-modal").modal("show");

	fetch("/download_remote_logs", {
	  method: "POST",
	  headers: {"Content-Type": "application/json"},
	  body: JSON.stringify({host, pattern, clear_existing: clearExisting})
	})
	.then(res => res.json())
	.then(data => {
	  if (data.status === "error") {
		$("#scp-modal").modal("hide");
		alert("❌ Download failed: " + data.message);
	  } else {
		console.log("✅ Download request accepted.");
	  }
	});

	startScpProgressPolling();
  }

  ////////////////////////////////////////////
  // SCP functions - Aborting download
  ////////////////////////////////////////////
  function abortDownload() {
	console.log("⚠️ UI: Sending abort_download fetch...");
	fetch("/abort_download", {method: "POST"})
	  .then(res => res.json())
	  .then(data => {
		alert("🚫 Abort sent.");
		if (scpSource) {
		  scpSource.close();
		}
		$("#scp-modal").modal("hide");
	  });
  }

	document.addEventListener("DOMContentLoaded", () => {
	  const scpModal = document.getElementById('scp-modal');
	  if (!scpModal) return;

	  const observer = new MutationObserver(() => {
		const isHidden = scpModal.classList.contains("hidden") || scpModal.style.display === "none";
		if (isHidden) {
		  console.log("🔁 SCP modal closed. Reloading page...");
		  location.reload(true); // Force hard reload
		}
	  });

	  observer.observe(scpModal, { attributes: true, attributeFilter: ['class', 'style'] });
	});
  
  // Show or hide the Abort modal
  function showAbortModal() {
	document.getElementById("abortConfirmModal").style.display = "block";
  }

  function hideAbortModal() {
	document.getElementById("abortConfirmModal").style.display = "none";
  }

  // Bind YES button (user confirmed abort)
	document.addEventListener("DOMContentLoaded", () => {
	  const confirmAbortYesBtn = document.getElementById("confirmAbortYes");
	  if (!confirmAbortYesBtn) {
		console.warn("⚠️ confirmAbortYes button not found in DOM.");
		return;
	  }

	  confirmAbortYesBtn.addEventListener("click", async function () {
		console.log("⚠️ UI: User confirmed abort. Sending /abort_download to backend…");

		try {
		  const res = await fetch("/abort_download", { method: "POST" });
		  const data = await res.json();

		  console.log("✅ Backend response:", data);
		  showToast("🚫 Download aborted.");
		} catch (err) {
		  console.error("❌ Failed to abort download:", err);
		  showToast("❌ Failed to abort SCP.");
		}

		// Cleanup UI
		hideAbortModal();
		document.getElementById("downloadModal").style.display = "none";
		document.getElementById("downloadProgressWrapper").style.display = "none";
		document.getElementById("downloadSpinner").style.display = "none";
		document.getElementById("downloadModal").dataset.state = "idle";
		document.getElementById("cancelDownloadBtn").textContent = "Close Window";

		if (scpProgressSource) {
		  scpProgressSource.close();
		  scpProgressSource = null;
		}

		if (scpSource) {
		  scpSource.close();
		  scpSource = null;
		}

		isDownloading = false;
		abortRequested = true;
		controller = null;
	  });
	});

  // Bind NO button (user canceled abort)
	document.addEventListener("DOMContentLoaded", () => {
	  const abortNoBtn = document.getElementById("confirmAbortNo");
	  if (!abortNoBtn) {
		console.warn("⚠️ confirmAbortNo button not found.");
		return;
	  }

	  abortNoBtn.addEventListener("click", function () {
		hideAbortModal();
	  });
	});
  ////////////////////////////////////////////
  // SCP functions - Aborting download (END)
  ////////////////////////////////////////////

document.addEventListener("DOMContentLoaded", () => {
  const logSelect = document.getElementById("logSelect");
  const modeRadios = document.getElementsByName("analyzeMode");
  const analyzeBtn = document.getElementById("startAnalysisBtn");

  function updateLogSelectState() {
	const selectedMode = Array.from(modeRadios).find(r => r.checked)?.value;
	if (selectedMode === "all") {
	  logSelect.setAttribute("disabled", "disabled");
	} else {
	  logSelect.removeAttribute("disabled");
	}
  }

  // Bind mode change to toggle the dropdown state
  modeRadios.forEach(radio => {
	radio.addEventListener("change", updateLogSelectState);
  });

  // Set correct initial state
  updateLogSelectState();

document.getElementById("startAnalysisBtn").addEventListener("click", analyzeLogs);
document.getElementById("logContextCloseBtn").addEventListener("click", closeLogContextModal);
document.getElementById("refreshBtn").addEventListener("click", () => {
  console.log("🔄 Refresh button clicked.");
fetchLogs();
});

// Start of table sorting logic under Detailed Error Breakdown
document.querySelectorAll("#errorDetailsTable th.sortable").forEach((th, index) => {
  let ascending = true;

  th.addEventListener("click", () => {
	const table = th.closest("table");
	const tbody = table.querySelector("tbody");
	const rows = Array.from(tbody.querySelectorAll("tr"));

	// Reset other columns' arrows
	table.querySelectorAll("th.sortable").forEach(header => {
	  if (header !== th) header.classList.remove("asc", "desc");
	});

	rows.sort((a, b) => {
	  let valA = a.children[index].textContent.trim();
	  let valB = b.children[index].textContent.trim();

	  // 🧠 If sorting the Error Message column (index 4), remove timestamp
	  if (index === 4) {
		const timestampPattern = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2},\d+\s+/;
		valA = valA.replace(timestampPattern, "");
		valB = valB.replace(timestampPattern, "");
	  }

	  const numA = parseFloat(valA);
	  const numB = parseFloat(valB);

	  // 🧮 Sort numbers if both are numbers
	  if (!isNaN(numA) && !isNaN(numB)) {
		return ascending ? numA - numB : numB - numA;
	  }

	  // 🔤 Fallback to text sort
	  return ascending
		? valA.localeCompare(valB, undefined, { numeric: true, sensitivity: "base" })
		: valB.localeCompare(valA, undefined, { numeric: true, sensitivity: "base" });
	});

	tbody.innerHTML = "";
	rows.forEach(row => tbody.appendChild(row));

	th.classList.toggle("asc", ascending);
	th.classList.toggle("desc", !ascending);
	ascending = !ascending;
  });
});
// END of table sorting logic under Detailed Error Breakdown

document.addEventListener("DOMContentLoaded", () => {
  const threadFilter = document.getElementById("rqrsThreadFilter");
  const dlxFilter = document.getElementById("rqrsDlxFilter");
  const errorFilter = document.getElementById("rqrsErrorFilter");
  const clearBtn = document.getElementById("rqrsClearFiltersBtn");

  if (threadFilter && dlxFilter && errorFilter && clearBtn) {
	threadFilter.addEventListener("input", applyRqrsFilters);
	dlxFilter.addEventListener("change", applyRqrsFilters);
	errorFilter.addEventListener("change", applyRqrsFilters);

	clearBtn.addEventListener("click", () => {
	  threadFilter.value = "";
	  dlxFilter.checked = false;
	  errorFilter.checked = false;
	  applyRqrsFilters();
	});
  }
});

setTimeout(fetchLogs, 0);
});
///////////////////////////////////////////
// RQ RS clickable
//////////////////////////////////////////
function openRqrsXmlModal(tagName, xmlContent) {
  const modal = document.getElementById("rqrsXmlModal");
  const title = document.getElementById("rqrsXmlTitle");
  const content = document.getElementById("rqrsXmlContent");

  title.textContent = `🧩 ${tagName}`;
  content.textContent = xmlContent;
  modal.style.display = "flex";
}

function closeRqrsXmlModal() {
  document.getElementById("rqrsXmlModal").style.display = "none";
}

// ✅ Fetches XML from backend and opens the custom-styled modal
async function fetchAndDisplayXMLForModal(log, index, tag) {
  // 📨 Step 1: Show in console what request is being made
  console.log("📨 Requesting XML content for:", { log, index, tag });

  // 🕐 Step 2: Show loading modal while waiting for backend response
  showLoadingXmlModal();

  try {
	// 🌐 Step 3: Send GET request to backend with log name, index, and XML tag
	const response = await fetch(`/get_rqrs_content?log=${encodeURIComponent(log)}&index=${index}&tag=${encodeURIComponent(tag)}`);

	// ❌ Step 4: Handle any error response (like 404 or 500)
	if (!response.ok) {
	  console.error("❌ Failed to load XML:", await response.text());
	  hideLoadingXmlModal(0); // hide immediately if failed
	  return;
	}

	// 📦 Step 5: Read the XML content from backend response as text
	const rawXml = await response.text();
	console.log("📦 Raw XML string received from backend:\n", rawXml);

	// 🔍 Step 6: Get modal elements from the DOM
	const modal = document.getElementById("customXmlModal");        // background/modal container
	const title = document.getElementById("customModalTitle");      // modal heading
	const content = document.getElementById("xmlContent");          // <pre> block for XML
	const container = modal.querySelector(".custom-xml-container"); // inner wrapper

	// ❌ Step 7: Check if all modal elements are available
	if (!modal || !title || !content || !container) {
	  console.error("❌ Modal DOM elements not found.");
	  hideLoadingXmlModal(0); // hide immediately on failure
	  return;
	}

	// 🖊️ Step 8: Populate the modal with the XML content
	title.textContent = `Tag: ${tag}`;        // set modal title text
	content.textContent = rawXml.trim();      // display raw XML text (trimmed)
	modal.style.display = "flex";             // make modal visible
	content.style.display = "block";          // ensure XML content block is visible

	// 🐞 Step 9: Debug logging — confirm modal is open and show raw size
	console.log("✅ XML rendered in modal:", rawXml.length, "chars");

	// 🐞 Step 10: Log the CSS class names used on each element
	console.log("[DEBUG] Modal element class:", modal.className);
	console.log("[DEBUG] Container element class:", container.className);
	console.log("[DEBUG] Title element class:", title.className);
	console.log("[DEBUG] Content element class:", content.className);

	// 🐞 Step 11: Log the active computed styles (for visual debugging)
	console.log("[DEBUG] Modal background:", getComputedStyle(modal).backgroundColor);
	console.log("[DEBUG] Container box shadow:", getComputedStyle(container).boxShadow);
	console.log("[DEBUG] Content font:", getComputedStyle(content).fontFamily, getComputedStyle(content).fontSize);

  } catch (err) {
	console.error("❌ Exception while fetching/displaying XML:", err);
  } finally {
	// ✅ Step 12: Always hide the loading modal after a delay
	hideLoadingXmlModal(1000); // auto-close after 1 second
  }
}

// ✅ Closes the custom XML modal window safely
function closeXmlModal() {
  // 🔍 Get the modal element by its ID (this is the dark background wrapper)
  const modal = document.getElementById("customXmlModal");

  // 🔍 Get the content element where the XML text is shown
  const content = document.getElementById("xmlContent");

  // ✅ Make sure both elements exist before changing anything
  if (modal && content) {
	// 🚫 Hide the modal by setting its display style to "none"
	modal.style.display = "none";

	// 🚫 Also hide the XML content area
	content.style.display = "none";

	// 🐞 Show a debug message to confirm it closed successfully
	console.log("❎ Modal closed successfully");
  } else {
	// ⚠️ If something went wrong (e.g. element not found), log a warning
	console.warn("⚠️ Could not close modal — elements not found.");
  }
}


// ✅ Opens the new custom XML modal (called by fetchAndDisplayXMLForModal or manually)
function openXmlModal(tag, formattedXml) {
  // 🔍 Get the outer modal container (dark background)
  const modal = document.getElementById("customXmlModal");

  // 🔍 Get the title element inside the modal
  const title = document.getElementById("customModalTitle");

  // 🔍 Get the <pre> element where the XML will be shown
  const content = document.getElementById("xmlContent");

  // 🔍 Get the inner container div (holds title, button, content)
  const container = modal.querySelector(".custom-xml-container");

  // ✅ Make sure all elements are found before continuing
  if (!modal || !title || !content || !container) {
	// ❌ Show error if any part of the modal is missing
	console.error("❌ openXmlModal: Modal DOM elements not found.");
	return;
  }

  // ✅ Set the title text at the top of the modal (e.g. 📄 DLX_AirAvailSvRQ)
  title.textContent = `📄 ${tag}`;

  // ✅ Display the XML content inside the <pre> tag as plain text
  content.innerText = formattedXml;

  // ✅ Show the modal by setting its style to flex (was hidden by default)
  modal.style.display = "flex";

  // ✅ Ensure the content block inside the modal is also visible
  content.style.display = "block";

  // 🐞 DEBUG LOGGING — Confirm modal is opening and show classes used
  console.log("📦 openXmlModal() triggered");
  console.log("[DEBUG] Modal element class:", modal.className);
  console.log("[DEBUG] Container element class:", container.className);
  console.log("[DEBUG] Title element class:", title.className);
  console.log("[DEBUG] Content element class:", content.className);

  // 🐞 DEBUG LOGGING — Show active styles for modal and content
  console.log("[DEBUG] Modal display:", getComputedStyle(modal).display);
  console.log("[DEBUG] Modal background:", getComputedStyle(modal).backgroundColor);
  console.log("[DEBUG] Container box shadow:", getComputedStyle(container).boxShadow);
  console.log("[DEBUG] XML Content font:", getComputedStyle(content).fontFamily);
  console.log("[DEBUG] XML Content font size:", getComputedStyle(content).fontSize);
}

// 🕐 Show the loading modal while fetching SOAP XML
function showLoadingXmlModal() {
  const modal = document.getElementById("loadingXmlModal");
  if (modal) {
	modal.style.display = "flex";
	console.log("⏳ Showing loading XML modal...");
  }
}

// ✅ Hide the loading modal after a delay
function hideLoadingXmlModal(afterMs = 10) {
  setTimeout(() => {
	const modal = document.getElementById("loadingXmlModal");
	if (modal) {
	  modal.style.display = "none";
	  console.log("✅ Loading XML modal closed.");
	}
  }, afterMs);
}

// ✅ Wait for the full HTML page to finish loading before attaching any event listeners
document.addEventListener("DOMContentLoaded", function () {
// 🔄 Get the "Refresh" button by its ID
const refreshBtn = document.getElementById("refreshPageBtn");
const confirmBtn = document.getElementById("confirmRefreshBtn");
const cancelBtn = document.getElementById("cancelRefreshBtn");
const modal = document.getElementById("refreshConfirmModal");

// ✅ Check if all required elements exist before setting up event handlers
if (refreshBtn && modal) {
  // When the user clicks the Refresh icon button
  refreshBtn.addEventListener("click", () => {
	modal.style.display = "flex"; // Show the confirmation modal
  });
} else {
  console.warn("⚠️ Refresh button or modal not found in the DOM.");
}

// 🔄 If user confirms "Yes, refresh"
if (confirmBtn) {
  confirmBtn.addEventListener("click", () => {
	location.reload(); // ✅ Reload the entire page
  });
} else {
  console.warn("⚠️ Confirm button not found in the DOM.");
}

// ❌ If user cancels
if (cancelBtn) {
  cancelBtn.addEventListener("click", () => {
	if (modal) {
	  modal.style.display = "none"; // ✅ Hide the modal if cancel is clicked
	}
  });
} else {
  console.warn("⚠️ Cancel button not found in the DOM.");
}
});
