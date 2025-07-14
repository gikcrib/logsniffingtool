/* --- 🔍 Search Tools Frontend Wiring START --- */

document.addEventListener('DOMContentLoaded', function() {
    const searchBtn = document.getElementById('searchBtn');
    const abortBtn = document.getElementById('abortBtn');
    const searchInput = document.getElementById('searchInput');
    const fileSelect = document.getElementById('fileSelect');
    const resultsTableBody = document.querySelector('#searchResults tbody');
    const progressModal = document.getElementById('progressModal');
    const detailsModal = document.getElementById('detailsModal');
    const detailsContent = document.getElementById('detailsContent');
    const copyBtn = document.getElementById('copyBtn');
    const closeBtn = document.getElementById('closeBtn');
	const refresListhSearchToolBtn = document.getElementById('refresListhSearchToolBtn');
	
	let useStreaming = true; // Set to false to use regular fetch

	// Optional: Add a UI toggle (e.g., checkbox)
	document.getElementById('streamingToggle').addEventListener('change', (e) => {
		useStreaming = e.target.checked;
	});

    // ✅ Populate the fileSelect dropdown on page load
    populateFileSelect();
	
	// ✅ Set initial state of fileSelect on page load
	if (document.querySelector('input[name="searchMode"]:checked').value === 'all') {
		fileSelect.disabled = true;
		console.log('Initial state: All Logs selected — fileSelect disabled');
	} else {
		fileSelect.disabled = false;
		console.log('Initial state: Targeted Log selected — fileSelect enabled');
	}

	// Watch searchMode radio buttons to enable/disable fileSelect dropdown
	document.querySelectorAll('input[name="searchMode"]').forEach(radio => {
		radio.addEventListener('change', () => {
			if (radio.value === 'all' && radio.checked) {
				fileSelect.disabled = true;
				console.log('All Logs selected — fileSelect disabled');
			} else if (radio.value === 'targeted' && radio.checked) {
				fileSelect.disabled = false;
				console.log('Targeted Log selected — fileSelect enabled');
			}
		});
	});

    // Search button click
	// 🔄 Updated Search Handler with Streaming Support and Progress Bar
	searchBtn.addEventListener('click', async () => {
		const searchText = searchInput.value.trim();
		const searchMode = document.querySelector('input[name="searchMode"]:checked').value;
		const targetFile = fileSelect.value || null;
		const searchStartTime = Date.now();
		
		// UI Setup
		document.getElementById('searchSummary').textContent = "Search in progress...";
		progressModal.style.display = 'flex';
		resultsTableBody.innerHTML = ''; // Clear previous results

		// 🚀 Method 1: Regular Fetch (unchanged)
		if (!useStreaming) { 
			try {
				const response = await fetch('/api/search_logs', {
					method: 'POST',
					headers: { 'Content-Type': 'application/json' },
					body: JSON.stringify({ search_text: searchText, search_mode: searchMode, target_file: targetFile })
				});
				const data = await response.json();
				
				const elapsed = ((Date.now() - searchStartTime) / 1000).toFixed(2);
				document.getElementById('searchSummary').textContent = 
					`Files Scanned: ${data.files_scanned} | ` +
					`Files with Matches: ${data.file_matches} | ` +
					`Total Occurrences: ${data.total_occurrences} | ` +
					`Time: ${elapsed}s`;
				
				populateResultsTable(data.results);
			} catch (error) {
				document.getElementById('searchSummary').textContent = "Search failed";
				alert("Search failed: " + error.message);
			} finally {
				progressModal.style.display = 'none';
			}
		}
		// 🌊 Method 2: Streaming (with progress bar)
		else {
			try {
				// Get total files count
				let totalFiles = 0;
				try {
					const fileCountResponse = await fetch('/api/list_log_files');
					if (fileCountResponse.ok) {
						const fileData = await fileCountResponse.json();
						totalFiles = (searchMode === 'all') 
							? fileData.log_files.length 
							: 1;
					}
				} catch (error) {
					console.error('File count error:', error);
				}

				// Initialize progress
				updateProgressBar(0, totalFiles, 'Starting search...');

				const response = await fetch('/api/search_logs_stream', {
					method: 'POST',
					headers: { 'Content-Type': 'application/json' },
					body: JSON.stringify({
						search_text: searchText,
						search_mode: searchMode,
						target_file: targetFile
					})
				});

				if (!response.ok) throw new Error("Streaming failed");

				const reader = response.body.getReader();
				const decoder = new TextDecoder();
				let buffer = '';
				let filesScanned = 0;
				let currentFile = '';

				while (true) {
					const { done, value } = await reader.read();
					if (done) {
						// 100% COMPLETION FIX (Step 2)
						updateProgressBar(totalFiles, totalFiles, 'Finalizing results...');
						break;
					}

					buffer += decoder.decode(value, { stream: true });
					const parts = buffer.split('\n\n');
					
					for (let i = 0; i < parts.length - 1; i++) {
						const event = parts[i].trim();
						if (!event) continue;

						if (event.startsWith('data: {')) {
							const data = JSON.parse(event.replace('data: ', ''));

							// Progress updates
							if (data.files_scanned !== undefined) {
								filesScanned = data.files_scanned;
								updateProgressBar(filesScanned, totalFiles, currentFile);
							}
							
							if (data.current_file) {
								currentFile = data.current_file;
								updateProgressBar(filesScanned, totalFiles, currentFile);
							}
							
							// Normal result
							if (data.log_file) {
								addSingleResultToTable(data);
							}
							
							// Search complete
							else if (data.status === "complete") {
								// SUMMARY REPORT FIX (Step 3)
								const elapsed = ((Date.now() - searchStartTime) / 1000).toFixed(2);
								document.getElementById('searchSummary').textContent =
									`Files Scanned: ${data.files_scanned} | ` +
									`Files with Matches: ${data.file_matches} | ` +
									`Total Occurrences: ${data.total_occurrences} | ` +
									`Time: ${elapsed}s`;
								
								// Close modal after slight delay
								setTimeout(() => {
									progressModal.style.display = 'none';
								}, 500);
							}
							
							// Error handling
							else if (data.error) {
								throw new Error(`${data.error} (Code: ${data.code || 'unknown'})`);
							}
						}
					}
					buffer = parts[parts.length - 1];
				}
			} catch (error) {
				// SUMMARY REPORT FIX (Step 3)
				document.getElementById('searchSummary').textContent = "Search failed";
				updateProgressBar(0, 0, `Failed: ${error.message}`);
				
				setTimeout(() => {
					progressModal.style.display = 'none';
				}, 1500);
				
				console.error("Search error:", error);
			}
		}
	});

    // Abort button click
	abortBtn.addEventListener('click', async () => {
		console.log('Abort button clicked');
		
		// 🌟 NEW: Visual feedback (add these 3 lines)
		const originalText = abortBtn.textContent; // Store original text
		abortBtn.textContent = "⏳ Aborting...";   // Show loading state
		abortBtn.disabled = true;                 // Prevent double-clicks

		try {
			const response = await fetch('/api/abort_search', { 
				method: 'POST',
				headers: { 'Content-Type': 'application/json' }
			});
			if (!response.ok) throw new Error("Abort failed");
			progressModal.style.display = 'none';
			resultsTableBody.innerHTML = ''; // Clear partial results
			
		} catch (error) {
			console.error('Abort error:', error);
			alert("Abort failed: " + error.message);
		} finally {
			// 🌟 NEW: Reset button (add these 2 lines)
			abortBtn.textContent = originalText; // Restore original text
			abortBtn.disabled = false;           // Re-enable button
		}
	});

	// ➕ Add Single Result to Table (For Streaming)
	function addSingleResultToTable(item) {
		const row = resultsTableBody.insertRow();
		row.insertCell().textContent = item.log_file;
		row.insertCell().textContent = item.line_number;
		row.insertCell().textContent = item.thread_id;
		row.insertCell().textContent = item.service;
		
		const detailsCell = row.insertCell();
		const showBtn = document.createElement('button');
		showBtn.textContent = '📄 Show Details';
		showBtn.addEventListener('click', () => {
			// Get the current search text
			const searchText = searchInput.value.trim();
			// Apply highlighting to the snippet
			detailsContent.innerHTML = highlightText(item.snippet, searchText);
			detailsModal.style.display = 'flex';
		});
		detailsCell.appendChild(showBtn);
	}

	// Populate results table
	function populateResultsTable(results) {
		resultsTableBody.innerHTML = '';
		if (results.length === 0) {
			const row = resultsTableBody.insertRow();
			row.insertCell().textContent = 'No Match Found';
			row.insertCell().textContent = '-';
			row.insertCell().textContent = '-';
			row.insertCell().textContent = '-';
			row.insertCell().textContent = '-';
			return;
		}
		results.forEach((item, index) => {
			const row = resultsTableBody.insertRow();
			row.insertCell().textContent = item.log_file;
			row.insertCell().textContent = item.line_number;
			row.insertCell().textContent = item.thread_id;
			row.insertCell().textContent = item.service;
			const detailsCell = row.insertCell();
			const showBtn = document.createElement('button');
			showBtn.textContent = '📄 Show Details';
			showBtn.addEventListener('click', () => {
				// Get the current search text
				const searchText = searchInput.value.trim();
				// Apply highlighting to the snippet
				detailsContent.innerHTML = highlightText(item.snippet, searchText);
				detailsModal.style.display = 'flex';
			});
			detailsCell.appendChild(showBtn);
		});
	}

    // Copy button
    copyBtn.addEventListener('click', () => {
        navigator.clipboard.writeText(detailsContent.textContent);
        console.log('Snippet copied to clipboard');
    });

    // Close button
    closeBtn.addEventListener('click', () => {
        detailsModal.style.display = 'none';
    });

    // 🌟 Press ESC to abort
    document.addEventListener('keydown', (e) => {
        // Only work when search is in progress
        if (e.key === "Escape" && progressModal.style.display === 'flex') {
            console.log("ESC pressed - aborting search");
            abortBtn.click(); // Simulate button click
        }
    });
	
	// 🌟 Refresh log list dropdown
	document.getElementById("refresListhSearchToolBtn").addEventListener("click", () => {
	  console.log("🔄 Search Tool Refresh List button clicked.");
    // ✅ Populate the fileSelect dropdown on page load
    populateFileSelect();
	});
}); // <-- This is your existing closing bracket for DOMContentLoaded

// ✅ Function to dynamically populate fileSelect dropdown
async function populateFileSelect() {
	try {
		const response = await fetch('/api/list_log_files');
		const data = await response.json();
		console.log('Available log files (before sort):', data.log_files);
		const fileSelect = document.getElementById('fileSelect');
		fileSelect.innerHTML = '<option value="">-- Select Target File --</option>';
		
		// ✅ Sort filenames alphabetically, case-insensitive
		const sortedFiles = data.log_files.sort((a, b) => a.toLowerCase().localeCompare(b.toLowerCase()));

		sortedFiles.forEach(file => {
			const option = document.createElement('option');
			option.value = file;
			option.textContent = file;
			fileSelect.appendChild(option);
		});

		console.log('Available log files (after sort):', sortedFiles);
	} catch (error) {
		console.error('Failed to load log files:', error);
	}
}

// ✅ Highlight text helper function
function highlightText(text, searchTerm) {
	if (!searchTerm) return text; // No highlighting if empty search
	
	// Escape special regex characters
	const escapedTerm = searchTerm.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
	const regex = new RegExp(`(${escapedTerm})`, 'gi');
	
	return text.replace(regex, '<span class="search-highlight">$1</span>');
}

/**
 * Updates progress bar in modal
 * @param {number} filesScanned - Files processed
 * @param {number} totalFiles - Total files to scan
 * @param {string} [currentFile] - Current file being scanned
 */
function updateProgressBar(filesScanned, totalFiles, currentFile = '') {
	// Calculate percentage (ensure 100% when complete)
	const percent = totalFiles > 0 
		? Math.min(100, Math.round((filesScanned / totalFiles) * 100))
		: 0;

	// Get or create progress elements INSIDE MODAL
	const modalContent = document.querySelector('.searchtool-modal-content');
	let container = document.getElementById('search-progress-container');
	
	if (!container) {
		container = document.createElement('div');
		container.id = 'search-progress-container';
		container.style.margin = '15px 0';
		container.style.width = '100%';
		
		const progressBar = document.createElement('div');
		progressBar.id = 'search-progress-bar';
		progressBar.style.height = '8px';
		progressBar.style.backgroundColor = '#4CAF50';
		progressBar.style.borderRadius = '4px';
		progressBar.style.width = '0%';
		progressBar.style.transition = 'width 0.3s';
		
		const progressText = document.createElement('div');
		progressText.id = 'search-progress-text';
		progressText.style.marginTop = '5px';
		progressText.style.fontSize = '12px';
		progressText.style.color = '#666';
		
		container.appendChild(progressBar);
		container.appendChild(progressText);
		
		// Insert after spinner but before abort button
		const spinner = document.querySelector('.searchtool-spinner');
		if (spinner) {
			spinner.insertAdjacentElement('afterend', container);
		} else {
			modalContent.insertBefore(container, document.getElementById('abortBtn'));
		}
	}

	// Update elements
	const progressBar = document.getElementById('search-progress-bar');
	const progressText = document.getElementById('search-progress-text');
	
	progressBar.style.width = `${percent}%`;
	progressText.textContent = currentFile 
		? `Scanning: ${filesScanned}/${totalFiles} files (${currentFile})`
		: `Processed: ${filesScanned}/${totalFiles} files`;
}

/* --- 🔍 Search Tools Frontend Wiring END --- */
