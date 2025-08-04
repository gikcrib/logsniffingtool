// Main Frontend JS - Reorganized for Beginners

// =============================================
// 1. GLOBAL VARIABLES AND UTILITY FUNCTIONS
// =============================================

// Global state variables
let isDownloading = false;
let abortRequested = false;
let controller = null;
let scpParams = {};
let scpProgressSource = null;
let scpSource = null;
let pollingInterval = null;

// Utility functions
function escapeHTML(str) {
    return str.replace(/[&<>'"]/g, char => ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        "'": '&#39;',
        '"': '&quot;'
    }[char]));
}

function highlightLogLevel(log) {
    const escaped = escapeHTML(log);
    return escaped
        .replace(/\[ERROR\]/g, `<span style="color:red;font-weight:bold;">[ERROR]</span>`)
        .replace(/\[WARN\]/g, `<span style="color:orange;">[WARN]</span>`)
        .replace(/\[FATAL\]/g, `<span style="background:red;color:white;">[FATAL]</span>`);
}

function showToast(message) {
    const toast = document.getElementById('toast');
    toast.textContent = message;
    toast.style.display = 'block';
    setTimeout(() => {
        toast.style.display = 'none';
    }, 2000);
}

function formatXML(xml) {
    const PADDING = '  ';
    const reg = /(>)(<)(\/*)/g;
    let formatted = '',
        pad = 0;
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

// =============================================
// 2. MEMORY MANAGEMENT AND RESET FUNCTIONS
// =============================================

function resetMemoryState_MainFrontEnd() {
    // Clear RQRS table and cache
    const rqrsTableBody = document.querySelector("#rqrsTable tbody");
    if (rqrsTableBody) rqrsTableBody.innerHTML = "";
    window.rqrsCache = [];

    // Clear error summary table
    const errorDetailsTableBody = document.querySelector("#errorDetailsTable tbody");
    if (errorDetailsTableBody) errorDetailsTableBody.innerHTML = "";

    // Reset count bars
    resetErrorSummary();

    // Reset filters
    document.getElementById("threadFilter").value = "";
    document.getElementById("serviceFilter").value = "";
    document.getElementById("rqrsThreadFilter").value = "";
    document.getElementById("rqrsTagFilter").value = "";
    document.getElementById("rqrsDlxCheckbox").checked = false;
    document.getElementById("rqrsErrorCheckbox").checked = false;

    // Disable filter controls
    ["threadFilter", "serviceFilter", "rqrsThreadFilter", "rqrsTagFilter", "rqrsDlxCheckbox", "rqrsErrorCheckbox", "rqrsClearFiltersBtn", "clearFiltersBtn"]
    .forEach(id => {
        const el = document.getElementById(id);
        if (el) el.disabled = true;
    });

    console.log("🧼 MainFrontEnd memory state cleaned up");
}

function resetErrorSummary() {
    document.getElementById('fatalCount').textContent = '0';
    document.getElementById('errorCount').textContent = '0';
    document.getElementById('warnCount').textContent = '0';
    document.getElementById('fatalBar').style.width = '0%';
    document.getElementById('errorBar').style.width = '0%';
    document.getElementById('warnBar').style.width = '0%';
}

// =============================================
// 3. LOG FILE MANAGEMENT
// =============================================

async function fetchLogs() {
    const res = await fetch('/list_logs');
    const data = await res.json();

    const logSelect = document.getElementById('logSelect');
    logSelect.innerHTML = '<option value="">-- Select a log file --</option>';

    data.logs
        .sort((a, b) => a.localeCompare(b, undefined, {
            numeric: true,
            sensitivity: 'base'
        }))
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

// =============================================
// 4. ERROR ANALYSIS FUNCTIONS
// =============================================

async function analyzeLogs() {
    const mode = document.querySelector('input[name="analyzeMode"]:checked').value;
    const logSelect = document.getElementById("logSelect");
    const selectedLog = logSelect ? logSelect.value : null;

    // Check if the log list dropdown is empty
    const logSelectOptions = logSelect ? Array.from(logSelect.options) : [];
    const hasLogFiles = logSelectOptions.length > 0;

    if (!hasLogFiles) {
        showNoLogsModal();
        console.warn("🚫 No logs to analyze.");
        return;
    }

    if (mode === "specific" && (!selectedLog || selectedLog === "")) {
        console.warn("🚫 Skipping analysis: no file selected.");
        showNoLogsModal();
        return;
    }

    console.log("🧪 Sending analysis request:", { mode, log: selectedLog });
    document.getElementById("analysisOverlay").style.display = "flex";

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

        if (mode === "all" && (!result.counts || (
            (result.counts.FATAL || 0) === 0 &&
            (result.counts.ERROR || 0) === 0 &&
            (result.counts.WARN || 0) === 0
        ))) {
            showNoLogsModal();
            console.warn("🚫 No errors found from the logs to analyze (All Logs mode).");
            return;
        }

        if (result.error) {
            showAnalysisErrorModal(result.error);
            return;
        }

        if (!res.ok || !result || !result.counts) {
            showAnalysisErrorModal("Failed to analyze logs.");
            return;
        }

        // Update error counts and bars
        const counts = result.counts || {};
        document.getElementById("fatalCount").textContent = counts.FATAL || 0;
        document.getElementById("errorCount").textContent = counts.ERROR || 0;
        document.getElementById("warnCount").textContent = counts.WARN || 0;

        const total = (counts.FATAL || 0) + (counts.ERROR || 0) + (counts.WARN || 0);
        const toPercent = (val) => total > 0 ? (val / total * 100) + "%" : "0%";
        document.getElementById("fatalBar").style.width = toPercent(counts.FATAL || 0);
        document.getElementById("errorBar").style.width = toPercent(counts.ERROR || 0);
        document.getElementById("warnBar").style.width = toPercent(counts.WARN || 0);

        // Update error details table
        const tableBody = document.querySelector("#errorDetailsTable tbody");
        tableBody.innerHTML = "";

        document.getElementById("threadFilter").value = "";
        document.getElementById("serviceFilter").value = "";
        applyFilters();

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
                    return false;
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

        // After error summary is updated, populate RQRS (only for specific mode)
        if (mode === "specific" && selectedLog) {
            rqrsPromise = fetchRQRS(selectedLog);
        } else {
            const rqrsTableBody = document.querySelector("#rqrsTable tbody");
            rqrsTableBody.innerHTML = "";
        }

        // Enable/Disable Filters + Clear Button Dynamically
        const hasData = (result.errors || []).length > 0;
        document.getElementById("threadFilter").disabled = !hasData;
        document.getElementById("serviceFilter").disabled = !hasData;
        document.getElementById("clearFiltersBtn").disabled = !hasData;

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

// =============================================
// 5. FILTER FUNCTIONS
// =============================================

function applyFilters() {
    const threadVal = document.getElementById('threadFilter').value.toLowerCase();
    const serviceVal = document.getElementById('serviceFilter').value.toLowerCase();
    document.querySelectorAll('#errorDetailsTable tbody tr').forEach(row => {
        const thread = row.children[2].textContent.toLowerCase();
        const service = row.children[3].textContent.toLowerCase();
        row.style.display = (thread.includes(threadVal) && service.includes(serviceVal)) ? '' : 'none';
    });
}

function clearFilters() {
    document.getElementById('threadFilter').value = "";
    document.getElementById('serviceFilter').value = "";
    applyFilters();
}

function applyRqrsFilters() {
    // Get filter values
    const threadFilter = document.getElementById("rqrsThreadFilter").value.toLowerCase();
    const serviceFilter = document.getElementById("rqrsServiceFilter").value.toLowerCase();
    const tagFilter = document.getElementById("rqrsTagFilter").value.toLowerCase();
    const dlxChecked = document.getElementById("rqrsDlxCheckbox").checked;
    const errorChecked = document.getElementById("rqrsErrorCheckbox").checked;

    // Get all table rows
    const rows = document.querySelectorAll("#rqrsTable tbody tr");
    
    rows.forEach(row => {
        // Get cell values (note the column indexes)
        const threadText = row.cells[1].textContent.toLowerCase(); // Thread ID (column 1)
        const serviceText = row.cells[2].textContent.toLowerCase(); // Service (column 2)
        const tagText = row.cells[3].textContent.toLowerCase(); // RQ/RS (column 3)

        // Apply all filter conditions
        const matchesThread = threadText.includes(threadFilter);
        const matchesService = serviceText.includes(serviceFilter);
        const matchesTag = tagText.includes(tagFilter);
        const matchesDlx = !dlxChecked || tagText.startsWith("dlx_");
        const matchesError = !errorChecked || tagText.includes("⚠️");

        // Show/hide row based on all conditions
        row.style.display = (matchesThread && matchesService && matchesTag && matchesDlx && matchesError) 
            ? "" 
            : "none";
    });
}

// =============================================
// 6. RQRS (Request/Response) FUNCTIONS
// =============================================

async function fetchRQRS(log) {
    const rqrsTableBody = document.querySelector("#rqrsTable tbody");
    rqrsTableBody.innerHTML = "<tr><td colspan='4' style='text-align: center;'>⏳ Loading RQ/RS data...</td></tr>";

    try {
        // 1. Make the API request
        const response = await fetch(`/get_rqrs?log=${encodeURIComponent(log)}`);
        
        // 2. Check if request failed
        if (!response.ok) {
            const errorData = await response.json().catch(() => null);
            throw new Error(errorData?.error || `Server returned ${response.status} ${response.statusText}`);
        }
        
        // 3. Parse JSON data
        const data = await response.json();
        
        // 4. Handle both response formats
        const rqrsData = Array.isArray(data.rqrs) ? data.rqrs : 
                        Array.isArray(data.entries) ? data.entries : 
                        [];
        
        // 5. Store data in cache for later use
        window.rqrsCache = rqrsData;
        
        // 6. Clear existing rows
        rqrsTableBody.innerHTML = "";
        
        // 7. Handle empty results
        if (rqrsData.length === 0) {
            const emptyRow = document.createElement("tr");
            emptyRow.innerHTML = `
                <td colspan="4" style="text-align: center; color: #666;">
                    No RQ/RS entries found in this log file
                </td>
            `;
            rqrsTableBody.appendChild(emptyRow);
            return;
        }
        
        // 8. Create table rows for each entry
        rqrsData.forEach((entry, index) => {
            const row = document.createElement("tr");
            
            // Normalize entry data (handle both formats)
            const normalizedEntry = {
                line: entry.line || entry.line_number || "??",
                thread: entry.thread || entry.thread_id || "UNKNOWN",
                service: entry.service || "UNKNOWN",
                tag: entry.tag || "???",
                has_issue: entry.has_issue || false
            };

            // Line Number column
            const lineCell = document.createElement("td");
            lineCell.textContent = normalizedEntry.line;
            lineCell.style.textAlign = "center";
            
            // Thread ID column
            const threadCell = document.createElement("td");
            threadCell.textContent = normalizedEntry.thread;
            
            // Service column
            const serviceCell = document.createElement("td");
            serviceCell.textContent = normalizedEntry.service;
            
            // XML Tag column (with clickable link)
            const tagCell = document.createElement("td");
            const tagLink = document.createElement("a");
            tagLink.href = "#";
            tagLink.textContent = normalizedEntry.tag + (normalizedEntry.has_issue ? " ⚠️" : "");
            tagLink.style.color = normalizedEntry.has_issue ? "#d32f2f" : "#1976d2";
            tagLink.onclick = (e) => {
                e.preventDefault();
                fetchAndDisplayXMLForModal(log, index, normalizedEntry.tag);
            };
            tagCell.appendChild(tagLink);
            
            // Add all cells to the row
            row.appendChild(lineCell);
            row.appendChild(threadCell);
            row.appendChild(serviceCell);
            row.appendChild(tagCell);
            
            // Add row to table
            rqrsTableBody.appendChild(row);
        });
        
        // 9. Enable filter controls if we have data
        const filterControls = document.querySelectorAll(
            "#rqrsFilterControls input, #rqrsClearFiltersBtn"
        );
        filterControls.forEach(control => {
            control.disabled = false;
        });
        
    } catch (error) {
        console.error("Error loading RQ/RS data:", error);
        
        // Show error message in the table
        rqrsTableBody.innerHTML = `
            <tr>
                <td colspan="4" style="color: red; text-align: center; padding: 20px;">
                    Failed to load RQ/RS data: ${error.message}
                    <br><small>Try refreshing the page or selecting a different log file</small>
                </td>
            </tr>
        `;
        
        // Ensure filters stay disabled on error
        document.querySelectorAll("#rqrsFilterControls input, #rqrsClearFiltersBtn")
            .forEach(el => el.disabled = true);
            
        // Clear cache on error
        window.rqrsCache = [];
    }
}

// Helper function to extract service name from thread ID
function extractServiceFromThread(thread) {
    if (!thread) return "UNKNOWN";
    
    // This matches the backend's service extraction logic
    const bracketedParts = thread.match(/\[([^\]]+)\]/g);
    if (bracketedParts) {
        for (let i = bracketedParts.length - 1; i >= 0; i--) {
            const part = bracketedParts[i].slice(1, -1); // Remove brackets
            if (part.includes('.')) {
                return part.split('.').pop(); // Get last part after dot
            }
        }
    }
    return "UNKNOWN";
}

// =============================================
// 7. XML HANDLING FUNCTIONS
// =============================================

async function fetchAndDisplayXMLForModal(log, index, tag) {
    const entry = window.rqrsCache[index];
    console.log("DEBUG - Entry being requested:", {
        log,
        index,
        tag,
        entryLine: entry.line,
        entryThread: entry.thread,
        entryService: entry.service
    });
    
    if (!entry) {
        showToast("❌ No data found for this entry");
        return;
    }

    console.log("📨 Requesting XML content for:", { log, lineNumber: entry.line, tag });
    showLoadingXmlModal();

    try {
        const response = await fetch(
            `/get_rqrs_content?log=${encodeURIComponent(log)}&line_number=${entry.line}&tag=${encodeURIComponent(tag)}`
        );

        if (!response.ok) {
            const errorData = await response.json().catch(() => null);
            throw new Error(errorData?.error || `Server returned ${response.status}`);
        }

        const data = await response.json();
        console.log("📦 Response data:", data);

        if (data.error && data.raw_xml) {
            // Show raw XML if parsing failed but we have content
            displayXmlContent(tag, data.raw_xml, "Raw XML (Parser Error)");
            showToast("⚠️ Showing raw XML due to parser error");
        } else if (data.pretty_xml) {
            displayXmlContent(tag, data.pretty_xml, "Formatted XML");
        } else {
            throw new Error("No XML content in response");
        }
    } catch (err) {
        console.error("❌ Error displaying XML:", err);
        showToast(`❌ Failed to load XML: ${err.message}`);
    } finally {
        hideLoadingXmlModal(500);
    }
}

function displayXmlContent(tag, xmlContent, titleSuffix) {
    const modal = document.getElementById("customXmlModal");
    const title = document.getElementById("customModalTitle");
    const content = document.getElementById("xmlContent");
    const container = modal.querySelector(".custom-xml-container");

    if (!modal || !title || !content || !container) {
        throw new Error("Modal elements not found");
    }

    title.textContent = `📄 ${tag} (${titleSuffix})`;
    content.textContent = xmlContent;
    modal.style.display = "flex";
    content.style.display = "block";

    if (window.hljs) {
        hljs.highlightElement(content);
    }
}

function copyXmlContent() {
    const xmlContent = document.getElementById('xmlContent');
    const range = document.createRange();
    range.selectNode(xmlContent);
    window.getSelection().removeAllRanges();
    window.getSelection().addRange(range);

    try {
        const successful = document.execCommand('copy');
        if (successful) {
            const copyBtn = document.querySelector('.custom-xml-copy-btn');
            const originalText = copyBtn.textContent;
            copyBtn.textContent = '✓ Copied!';
            setTimeout(() => {
                copyBtn.textContent = originalText;
            }, 2000);
        }
    } catch (err) {
        console.error('Failed to copy: ', err);
    }

    window.getSelection().removeAllRanges();
}

function closeXmlModal() {
    const modal = document.getElementById("customXmlModal");
    const content = document.getElementById("xmlContent");

    if (modal && content) {
        modal.style.display = "none";
        content.style.display = "none";
        console.log("❎ Modal closed successfully");
    } else {
        console.warn("⚠️ Could not close modal — elements not found.");
    }
}

function openXmlModal(tag, formattedXml) {
    const modal = document.getElementById("customXmlModal");
    const title = document.getElementById("customModalTitle");
    const content = document.getElementById("xmlContent");
    const container = modal.querySelector(".custom-xml-container");

    if (!modal || !title || !content || !container) {
        console.error("❌ openXmlModal: Modal DOM elements not found.");
        return;
    }

    title.textContent = `📄 ${tag}`;
    content.innerText = formattedXml;
    modal.style.display = "flex";
    content.style.display = "block";

    console.log("📦 openXmlModal() triggered");
}

function showLoadingXmlModal() {
    const modal = document.getElementById("loadingXmlModal");
    if (modal) {
        modal.style.display = "flex";
        console.log("⏳ Showing loading XML modal...");
    }
}

function hideLoadingXmlModal(afterMs = 10) {
    setTimeout(() => {
        const modal = document.getElementById("loadingXmlModal");
        if (modal) {
            modal.style.display = "none";
            console.log("✅ Loading XML modal closed.");
        }
    }, afterMs);
}

// =============================================
// 8. LOG CONTEXT FUNCTIONS
// =============================================

function openLogContextModal(logFile, lineNumber) {
    const modal = document.getElementById("logContextModal");
    const content = document.getElementById("logContextText");

    content.textContent = "⏳ Loading log context...";

    fetch(`/log_context?log=${encodeURIComponent(logFile)}&line=${lineNumber}`)
        .then(res => {
            if (!res.ok) {
                throw new Error("Log context fetch failed");
            }
            return res.json();
        })
        .then(data => {
            content.textContent = data.lines.join("\n");
            modal.style.display = "flex";
        })
        .catch(err => {
            console.error("❌ Failed to load log context:", err);
            alert("⚠️ Unable to fetch log context.");
        });
}

function closeLogContextModal() {
    const modal = document.getElementById("logContextModal");
    const content = document.getElementById("logContextText");
    modal.style.display = "none";
    content.textContent = "";
}

// =============================================
// 9. REMOTE DOWNLOAD FUNCTIONS
// =============================================

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
        if (scpProgressSource) scpProgressSource.close();
        scpProgressSource = new EventSource("/scp_progress");

        scpProgressSource.onmessage = (event) => {
            const data = JSON.parse(event.data);
            const percent = Math.min(100, Math.round(data.percent || 0));
            const eta = data.eta && data.eta > 0 ?
                `ETA: ${Math.floor(data.eta / 60)}m ${data.eta % 60}s` :
                "";
            progressText.textContent = `${percent}% ${eta}`;
            progressFill.style.width = `${percent}%`;
        };

        const res = await fetch("/download_remote_logs", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                host,
                username,
                remote_path: path,
                pattern,
                clear_existing: clearExisting
            }),
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

// =============================================
// 10. MODAL FUNCTIONS
// =============================================

function showNoLogsModal() {
    const modal = document.getElementById("noLogsModal");
    if (modal) {
        modal.style.display = "flex";
    }
}

function closeNoLogsModal() {
    const modal = document.getElementById("noLogsModal");
    if (modal) {
        modal.style.display = "none";
    }
}

function showAnalysisErrorModal(message) {
    document.getElementById("analysisErrorMessage").textContent = message || "Unknown error occurred.";
    const modal = document.getElementById("analysisErrorModal");
    modal.classList.add("show");
}

function closeAnalysisErrorModal() {
    const modal = document.getElementById("analysisErrorModal");
    modal.classList.remove("show");
}

function showAbortModal() {
    document.getElementById("abortConfirmModal").style.display = "block";
}

function hideAbortModal() {
    document.getElementById("abortConfirmModal").style.display = "none";
}

// =============================================
// 11. EVENT LISTENERS AND INITIALIZATION
// =============================================

document.addEventListener("DOMContentLoaded", () => {
    // Tab switch memory reset
    const tabButtons = document.querySelectorAll('.tab-button');
    tabButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            const activeTabId = btn.getAttribute('data-tab');
            if (activeTabId !== 'error-tab' && activeTabId !== 'soap-tab') {
                resetMemoryState_MainFrontEnd();
            }
        });
    });

    // Download modal controls
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
                controller.abort();
                abortRequested = true;
            }

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

    document.getElementById("confirmFinalDeleteYes").addEventListener("click", () => {
        document.getElementById("finalDeleteConfirmModal").style.display = "none";
        document.getElementById("downloadModal").style.display = "flex";
        proceedWithDownload(true);
    });

    document.getElementById("confirmFinalDeleteNo").addEventListener("click", () => {
        document.getElementById("finalDeleteConfirmModal").style.display = "none";
        document.getElementById("downloadModal").style.display = "none";
    });

    // Log analysis controls
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

    modeRadios.forEach(radio => {
        radio.addEventListener("change", updateLogSelectState);
    });

    updateLogSelectState();

    document.getElementById("startAnalysisBtn").addEventListener("click", analyzeLogs);
    document.getElementById("logContextCloseBtn").addEventListener("click", closeLogContextModal);
    document.getElementById("refreshBtn").addEventListener("click", () => {
        console.log("🔄 Refresh button clicked.");
        fetchLogs();
    });

    // Table sorting
    document.querySelectorAll("#errorDetailsTable th.sortable").forEach((th, index) => {
        let ascending = true;

        th.addEventListener("click", () => {
            const table = th.closest("table");
            const tbody = table.querySelector("tbody");
            const rows = Array.from(tbody.querySelectorAll("tr"));

            table.querySelectorAll("th.sortable").forEach(header => {
                if (header !== th) header.classList.remove("asc", "desc");
            });

            rows.sort((a, b) => {
                let valA = a.children[index].textContent.trim();
                let valB = b.children[index].textContent.trim();

                if (index === 4) {
                    const timestampPattern = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2},\d+\s+/;
                    valA = valA.replace(timestampPattern, "");
                    valB = valB.replace(timestampPattern, "");
                }

                const numA = parseFloat(valA);
                const numB = parseFloat(valB);

                if (!isNaN(numA) && !isNaN(numB)) {
                    return ascending ? numA - numB : numB - numA;
                }

                return ascending ?
                    valA.localeCompare(valB, undefined, {
                        numeric: true,
                        sensitivity: "base"
                    }) :
                    valB.localeCompare(valA, undefined, {
                        numeric: true,
                        sensitivity: "base"
                    });
            });

            tbody.innerHTML = "";
            rows.forEach(row => tbody.appendChild(row));

            th.classList.toggle("asc", ascending);
            th.classList.toggle("desc", !ascending);
            ascending = !ascending;
        });
    });

    // RQRS filters
    const threadFilter = document.getElementById("rqrsThreadFilter");
    const serviceFilter = document.getElementById("rqrsServiceFilter");
    const tagFilter = document.getElementById("rqrsTagFilter");
    const dlxFilter = document.getElementById("rqrsDlxCheckbox");  // Note: changed from rqrsDlxFilter
    const errorFilter = document.getElementById("rqrsErrorCheckbox"); // Note: changed from rqrsErrorFilter
    const clearBtn = document.getElementById("rqrsClearFiltersBtn");

    if (threadFilter && serviceFilter && tagFilter && dlxFilter && errorFilter && clearBtn) {
        threadFilter.addEventListener("input", applyRqrsFilters);
        serviceFilter.addEventListener("input", applyRqrsFilters);
        tagFilter.addEventListener("input", applyRqrsFilters);
        dlxFilter.addEventListener("change", applyRqrsFilters);
        errorFilter.addEventListener("change", applyRqrsFilters);

        clearBtn.addEventListener("click", () => {
            threadFilter.value = "";
            serviceFilter.value = "";
            tagFilter.value = "";
            dlxFilter.checked = false;
            errorFilter.checked = false;
            applyRqrsFilters();
        });
    }

    // Regular filters
    document.getElementById('threadFilter').addEventListener('input', applyFilters);
    document.getElementById('serviceFilter').addEventListener('input', applyFilters);
    document.getElementById("clearFiltersBtn").addEventListener("click", clearFilters);

    // Initial fetch
    setTimeout(fetchLogs, 0);
});