class LogViewer {
    constructor() {
        // Core properties
        this.currentFile = null;
        this.totalLines = 0;
        this.lineHeight = 18;
        window.rawLogLines = [];
        this.isLoading = false;
        this.searchResults = [];
        this.currentSearchIndex = -1;
        this.currentSearchTerm = '';
        this.caseSensitive = false;
        this.wholeWord = false;
        this.wrapEnabled = false;

        // Properties for virtual scrolling
        this.visibleStartLine = 0;
        this.visibleEndLine = 0;
        this.renderBuffer = 20;
        this.lastScrollTop = 0;

        // Initialize UI elements first
        this.initUIElements();
        
        // Rest of initialization
        this.setupEventListeners();
        // this.refreshFileList();
        this.setupMemoryCleanup();
    }

    initUIElements() {
        this.logContainer = document.getElementById('logview-content');
        this.fileSelect = document.getElementById('logview-file-select');
        this.refreshBtn = document.getElementById('logview-refresh-btn');
        this.loadBtn = document.getElementById('logview-load-btn');
        this.searchInput = document.getElementById('logview-search-input');
        this.searchBtn = document.getElementById('logview-search-btn');
        this.copyBtn = document.getElementById('logview-copy-btn');
        this.logViewport = document.getElementById('logview-viewport'); // This is critical
        this.statusBar = document.getElementById('logview-status');
        this.wholeWordCheckbox = document.getElementById('logview-whole-word');
    }

    setupMemoryCleanup() {
        window.addEventListener('beforeunload', () => {
            window.rawLogLines = [];
            this.searchResults = [];
            this.logContainer.textContent = '';
        });

        // Optional: Add cleanup when changing files
        document.getElementById('logview-file-select')?.addEventListener('change', () => {
            this.updateStatus(`🔄 File selection changed.`);
            this.cleanupMemory();
        });
    }

    cleanupMemory() {
        window.rawLogLines = [];
        this.searchResults = [];
        this.logContainer.textContent = '';
        // Clear DOM
        if (this.logContainer) {
            this.logContainer.textContent = '';
        }
        if (window.gc) window.gc(); // Chrome's manual GC
        console.debug('Memory cleaned up');
    }

    setupEventListeners() {
        // Core functionality listeners
        this.refreshBtn.addEventListener('click', () => this.refreshFileList());
        this.loadBtn.addEventListener('click', () => this.loadSelectedFile());
        this.searchBtn.addEventListener('click', () => this.performSearch());
        this.copyBtn.addEventListener('click', () => this.copySelectedText());

        // Keyboard support
        this.searchInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') this.performSearch();
        });

        // Viewport scroll listener
        this.logViewport.addEventListener('scroll', () => {
            const scrollTop = this.logViewport.scrollTop;
            
            // Only re-render if we've scrolled at least one line height
            if (Math.abs(scrollTop - this.lastScrollTop) > this.lineHeight) {
                this.renderVisibleLines();
                this.lastScrollTop = scrollTop;
            }
            
            // If you had any other scroll-related logic, keep it here
        });

        // Line navigation
        document.getElementById('logview-goto-btn').addEventListener('click', () => this.goToLine());
        document.getElementById('logview-goto-input').addEventListener('keypress', (e) => {
            if (e.key === 'Enter') this.goToLine();
        });

        // Optional: Add window resize handler if needed for responsive layout
        window.addEventListener('resize', () => {
            // Example: this.handleLayoutAdjustments();
        });

        document.getElementById('logview-next-btn').addEventListener(
            'click',
            () => this.navigateToNextResult()
        );

        document.getElementById('logview-prev-btn').addEventListener(
            'click',
            () => this.navigateToPrevResult()
        );

        // Keyboard shortcuts
        document.addEventListener('keydown', (e) => {
            if (e.key === 'F3') {
                e.preventDefault();
                this.navigateToNextResult();
            }
            if (e.key === 'F4') {
                e.preventDefault();
                this.navigateToPrevResult();
            }
            if (e.key === 'F5') {
                e.preventDefault();
                this.cleanupMemory();
            }
        });

    }

    async refreshFileList() {
        // Updating Status
        this.updateStatus(`⏳ Please wait, scanning files and reloading the list...`);
        try {
            const response = await fetch('/api/logs/list');
            const data = await response.json();

            // Clear dropdown
            this.fileSelect.innerHTML = '<option value="">-- Select Target File --</option>';

            // Sort files using numeric-aware comparison
            const sortedFiles = data.files.sort((a, b) =>
                a.name.localeCompare(b.name, undefined, {
                    numeric: true,
                    sensitivity: 'base'
                })
            );

            // Add files to dropdown with size information
            sortedFiles.forEach(file => {
                const option = document.createElement('option');
                option.value = file.name;
                option.textContent = `${file.name} - ${this.formatFileSize(file.size)}`;
                this.fileSelect.appendChild(option);
            });

            this.updateStatus(`✅ Log listing is completed, select a file now.`);
            this.showToast(`✅ Loaded ${sortedFiles.length} log files`);
        } catch (error) {
            this.showModal('Error', `🔴 Failed to refresh files: ${error.message}`);
        }
    }

 async loadSelectedFile() {
    const selectedFile = this.fileSelect.value;
    if (!selectedFile) {
        this.showModal('Warning', '🟠 Please select a file first');
        return;
    }

    try {
        this.updateStatus(`✅ File selected, please wait while the file is being loaded...`);
        // Reset state
        this.currentFile = selectedFile;
        window.rawLogLines = [];
        this.totalLines = 0;
        this.searchResults = [];
        this.currentSearchIndex = -1;
        
        // Show loading state
        this.logContainer.innerHTML = '<div class="logview-loading">⏳ Please wait, loading file...<div class="loading-spinner"></div></div>';
        this.logContainer.style.opacity = '1'; // Force visibility
        this.logContainer.offsetHeight;

        // Force a synchronous layout/render before continuing
        await new Promise(resolve => {
            requestAnimationFrame(() => {
                requestAnimationFrame(resolve);
            });
        });
        
        // Load file
        const response = await fetch(`/api/logs/stream?filename=${encodeURIComponent(selectedFile)}`);
        
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        
        // Rest of your streaming logic...
        // Handle NDJSON stream
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let result = '';
        let isFirstChunk = true;
        
        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            
            result += decoder.decode(value, { stream: true });
            
            // Process complete JSON chunks (separated by \n\n)
            const chunks = result.split('\n\n');
            result = chunks.pop() || ''; // Keep incomplete chunk
            
            for (const chunk of chunks) {
                try {
                    const data = JSON.parse(chunk);
                    
                    if (data.type === "metadata") {
                        // Handle metadata if needed
                        continue;
                    }
                    
                    if (data.lines) {
                        // Append new lines instead of replacing
                        window.rawLogLines.push(...data.lines);
                        this.totalLines = data.total_lines;
                        
                        // Only render periodically for performance
                        if (isFirstChunk || window.rawLogLines.length % 100000 === 0) {
                            this.renderVisibleLines();
                            this.updateStatus(`⏳ Please wait, loading file... ${selectedFile} - ${this.totalLines.toLocaleString()} lines loaded`);
                            isFirstChunk = false;
                        }
                    }
                } catch (e) {
                    console.error('Error parsing JSON chunk:', e);
                }
            }
        }
        
        // Final render with all lines
        this.renderVisibleLines();
        this.updateStatus(`💯 100% Loaded ${selectedFile} - ${this.totalLines.toLocaleString()} lines`);
 
        // ✅ Log to backend AI logger that the file was opened in Raw Logs viewer
        try {
          await fetch("/ai/log_action", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              action: "view_raw_log",
              details: {
                log_file: selectedFile
              }
            })
          });
        } catch (e) {
          console.warn("📜 AI Logging failed for raw log view:", e);
        }
        
    } catch (error) {
        this.showModal('🔴 Error', `Failed to load file: ${error.message}`);
        // Ensure loading state is cleared on error
        this.logContainer.innerHTML = '';
    }
}

renderVisibleLines() {
    // Clear existing highlights
    document.querySelectorAll('.logview-line-current, .search-match').forEach(el => {
        el.classList.remove('logview-line-current');
        if (el.classList.contains('search-match')) {
            const parent = el.parentNode;
            if (parent) parent.textContent = parent.textContent;
        }
    });

    if (!this.logViewport || window.rawLogLines.length === 0) return;
    
    // Calculate visible lines with buffer
    const scrollTop = this.logViewport.scrollTop;
    const viewportHeight = this.logViewport.clientHeight;
    const linesInViewport = Math.ceil(viewportHeight / this.lineHeight);
    
    this.visibleStartLine = Math.max(0, 
        Math.floor(scrollTop / this.lineHeight) - this.renderBuffer
    );
    
    this.visibleEndLine = Math.min(
        window.rawLogLines.length,
        this.visibleStartLine + linesInViewport + (this.renderBuffer * 2)
    );
    
    // Create document fragment for efficient DOM updates
    const fragment = document.createDocumentFragment();
    const container = document.createElement('div');
    container.className = 'logview-line-container';
    
    // Calculate top offset for the container
    const containerTop = this.visibleStartLine * this.lineHeight;
    container.style.position = 'absolute';
    container.style.top = `${containerTop}px`;
    container.style.width = '100%';
    
    // Track maximum line width for horizontal scrolling
    let maxLineWidth = 0;
    
    // Render visible lines
    for (let i = this.visibleStartLine; i < this.visibleEndLine; i++) {
        const lineNumber = i + 1;
        const lineElement = document.createElement('div');
        lineElement.className = 'logview-line';
        lineElement.dataset.line = lineNumber;
        lineElement.dataset.index = i;
        
        const cleanedLine = window.rawLogLines[i].replace(/\t/g, '    ').trimEnd();
        const safeLineContent = this.escapeHtml(cleanedLine);
        
        lineElement.innerHTML = `
            <span class="logview-line-number">${lineNumber}</span>
            <span class="logview-line-content">${safeLineContent}</span>
        `;
        
        // Calculate line width for horizontal scrolling
        const tempContainer = document.createElement('div');
        tempContainer.style.position = 'absolute';
        tempContainer.style.visibility = 'hidden';
        tempContainer.style.whiteSpace = 'nowrap';
        tempContainer.innerHTML = lineElement.innerHTML;
        document.body.appendChild(tempContainer);
        maxLineWidth = Math.max(maxLineWidth, tempContainer.scrollWidth);
        document.body.removeChild(tempContainer);
        
        if (this.searchResults.includes(lineNumber)) {
            lineElement.classList.add('logview-line-highlight');
        }
        
        container.appendChild(lineElement);
    }
    
    // Update the DOM
    this.logContainer.innerHTML = '';
    this.logContainer.appendChild(container);
    
    // Set total height for proper scrolling
    this.logContainer.style.height = `${window.rawLogLines.length * this.lineHeight}px`;
    
    // Set width based on the longest line
    this.logContainer.style.width = `${maxLineWidth + 80}px`; // Add padding for line numbers
    
    // Handle search highlights if needed
    if (this.currentSearchIndex >= 0 && this.searchResults.length > 0) {
        this.highlightCurrentSearchResult();
    }
}

    performSearch() {
        const query = this.searchInput.value.trim();
        if (!query) {
            this.showModal('Warning', 'Please enter a search term');
            return;
        }

        this.currentSearchTerm = query;
        this.searchResults = [];
        
        // Search through ALL lines (still stored in memory)
        window.rawLogLines.forEach((line, index) => {
            if (line.toLowerCase().includes(query.toLowerCase())) {
                this.searchResults.push(index + 1); // Store line numbers
            }
        });

        if (this.searchResults.length === 0) {
            this.showModal('No results', 'No matches found');
            return;
        }

        this.currentSearchIndex = 0;
        this.navigateToCurrentResult();
    }

    clearSearchHighlights() {
        // Remove all search highlights
        document.querySelectorAll('.logview-search-match').forEach(el => {
            const parent = el.parentNode;
            if (parent) {
                parent.textContent = parent.textContent; // Reset content
            }
        });
    }

    navigateToNextResult() {
        if (this.searchResults.length === 0) return;

        this.currentSearchIndex = (this.currentSearchIndex + 1) % this.searchResults.length;
        this.navigateToCurrentResult();
    }

    navigateToPrevResult() {
        if (this.searchResults.length === 0) return;

        this.currentSearchIndex = (this.currentSearchIndex - 1 + this.searchResults.length) % this.searchResults.length;
        this.navigateToCurrentResult();
    }

    navigateToCurrentResult() {
        if (this.currentSearchIndex < 0 || this.currentSearchIndex >= this.searchResults.length) return;

        const lineNumber = this.searchResults[this.currentSearchIndex];
        this.scrollToLine(lineNumber);
        setTimeout(() => this.highlightCurrentSearchResult(), 50);
        this.updateStatus(`Match ${this.currentSearchIndex + 1} of ${this.searchResults.length}`);
    }

    highlightCurrentSearchResult() {
        if (this.currentSearchIndex < 0 || this.currentSearchIndex >= this.searchResults.length) return;

        // 1. Get current match info
        const currentLineNumber = this.searchResults[this.currentSearchIndex];
        const lineIndex = currentLineNumber - 1;
        
        // 2. Check if this line is currently visible
        const isLineVisible = lineIndex >= this.visibleStartLine && lineIndex <= this.visibleEndLine;
        
        // 3. Only proceed if line is visible (or will be after scrolling)
        if (isLineVisible) {
            // Remove previous highlights from currently visible lines
            document.querySelectorAll('.logview-line-current').forEach(el => {
                el.classList.remove('logview-line-current');
            });
            
            // Find the line element (it exists because it's visible)
            const lineElement = document.querySelector(
                `.logview-line[data-line="${currentLineNumber}"]`
            );
            
            if (lineElement) {
                // Highlight the entire line
                lineElement.classList.add('logview-line-current');
                
                // Highlight the matched text (keep your existing logic)
                const contentSpan = lineElement.querySelector('.logview-line-content');
                if (contentSpan) {
                    const searchTerm = this.currentSearchTerm;
                    const textContent = contentSpan.textContent;
                    let escapedTerm = this.escapeRegex(searchTerm);
                    
                    if (this.wholeWord) {
                        escapedTerm = `\\b${escapedTerm}\\b`;
                    }
                    
                    const regex = new RegExp(escapedTerm, this.caseSensitive ? 'g' : 'gi');
                    
                    // Create document fragment to safely build our highlighted content
                    const fragment = document.createDocumentFragment();
                    let lastIndex = 0;
                    let match;
                    
                    while ((match = regex.exec(textContent)) !== null) {
                        // Add text before match
                        if (match.index > lastIndex) {
                            fragment.appendChild(document.createTextNode(
                                textContent.substring(lastIndex, match.index)
                            ));
                        }
                        
                        // Add highlighted match
                        const highlight = document.createElement('span');
                        highlight.className = 'search-match';
                        highlight.textContent = match[0];
                        fragment.appendChild(highlight);
                        
                        lastIndex = regex.lastIndex;
                        
                        // Prevent infinite loops for zero-length matches
                        if (match.index === regex.lastIndex) {
                            regex.lastIndex++;
                        }
                    }
                    
                    // Add remaining text
                    if (lastIndex < textContent.length) {
                        fragment.appendChild(document.createTextNode(
                            textContent.substring(lastIndex)
                        ));
                    }
                    
                    // Replace content safely
                    contentSpan.innerHTML = '';
                    contentSpan.appendChild(fragment);
                }
            }
        }
        
        // 4. Update the status (keep your existing status update)
        this.updateStatus(`🎯 Match found! [RESULT]: ${this.currentSearchIndex + 1} of ${this.searchResults.length}. Click Next or Prev.`);
    }

    highlightSearchResults() {
        document.querySelectorAll('.logview-line').forEach(line => {
            const lineNumber = parseInt(line.dataset.line);
            line.classList.toggle(
                'logview-line-highlight',
                this.searchResults.includes(lineNumber)
            );
        });
    }

    scrollToLine(lineNumber) {
        const lineIndex = lineNumber - 1;
        const scrollPosition = lineIndex * this.lineHeight;
        
        // Scroll to the line
        this.logViewport.scrollTo({
            top: scrollPosition - (this.logViewport.clientHeight / 3), // Center the line
            behavior: 'smooth'
        });
        
        // This will trigger the scroll event which calls renderVisibleLines()
        // The line will be highlighted when it's rendered
    }

    highlightLine(lineNumber) {
        // Remove previous highlight
        const prevHighlight = document.querySelector('.logview-line-current');
        if (prevHighlight) {
            prevHighlight.classList.remove('logview-line-current');
        }

        // Add new highlight
        const lineElement = document.querySelector(`.logview-line[data-line="${lineNumber}"]`);
        if (lineElement) {
            lineElement.classList.add('logview-line-current');

            // Auto-remove highlight after 3 seconds
            setTimeout(() => {
                lineElement.classList.remove('logview-line-current');
            }, 3000);
        }
    }

    async goToLine() {
        const input = document.getElementById('logview-goto-input');
        const lineNumber = parseInt(input.value);

        if (isNaN(lineNumber)) {
            this.showModal('Error', 'Please enter a valid line number');
            return;
        }

        if (lineNumber < 1 || lineNumber > this.totalLines) {
            this.showModal('Error', `Line number must be between 1 and ${this.totalLines}`);
            return;
        }

        this.scrollToLine(lineNumber);
    }

    adjustScrollAfterWrap() {
        // Small delay to ensure DOM updates
        setTimeout(() => {
            const currentScroll = this.logViewport.scrollTop;
            
            // Temporarily nudge scroll position to force reflow
            this.logViewport.scrollTop = currentScroll + 1;
            
            // Return to original position after reflow
            setTimeout(() => {
                this.logViewport.scrollTop = currentScroll;
                
                // One more check after everything settles
                setTimeout(() => {
                    if (this.wrapEnabled) {
                        this.logContainer.style.height = 'auto';
                    }
                }, 50);
            }, 10);
        }, 50);
    }

    addDropdownSectionHeader(text) {
        const header = document.createElement('option');
        header.disabled = true;
        header.textContent = text;
        header.style = `
            font-weight: bold;
            background: #f0f0f0;
            color: #333;
            padding: 4px 8px;
        `;
        this.fileSelect.appendChild(header);
    }

    copySelectedText() {
        const selection = window.getSelection();
        if (!selection || selection.toString().length === 0) {
            this.showModal('Warning', 'Please select some text to copy first');
            return;
        }

        try {
            let logText = "";
            const range = selection.getRangeAt(0);
            const lineElements = this.logContainer.querySelectorAll('.logview-line');

            lineElements.forEach(line => {
                if (selection.containsNode(line, true)) {
                    const lineContent = line.querySelector('.logview-line-content');
                    if (lineContent) {
                        // Trim whitespace and add clean newline
                        const cleanLine = lineContent.textContent.trim();
                        if (cleanLine) {
                            if (logText) logText += "\n";
                            logText += cleanLine;
                        }
                    }
                }
            });

            if (logText) {
                navigator.clipboard.writeText(logText)
                    .then(() => this.showToast('✅ Log text copied to clipboard'))
                    .catch(err => console.error('Copy failed:', err));
            } else {
                this.showModal('Warning', 'No log content selected');
            }
        } catch (error) {
            console.error('Copy error:', error);
            this.showModal('Error', 'Failed to copy text');
        }
    }

    updateStatus(message) {
        this.statusBar.textContent = message;
    }

    showToast(message, duration = 3000) {
        const toast = document.createElement('div');
        toast.className = 'logview-toast';
        toast.textContent = message;
        document.body.appendChild(toast);

        setTimeout(() => {
            toast.classList.add('logview-toast-fadeout');
            setTimeout(() => toast.remove(), 500);
        }, duration);
    }

    showModal(title, message) {
        let modal = document.getElementById('logview-modal');
        if (!modal) {
            modal = document.createElement('div');
            modal.id = 'logview-modal';
            modal.className = 'logview-modal';
            modal.innerHTML = `
                <div class="logview-modal-content">
                    <h3 class="logview-modal-title"></h3>
                    <p class="logview-modal-message"></p>
                    <button class="logview-modal-close">OK</button>
                </div>
            `;
            document.body.appendChild(modal);

            modal.querySelector('.logview-modal-close').addEventListener('click', () => {
                modal.style.display = 'none';
            });
        }

        modal.querySelector('.logview-modal-title').textContent = title;
        modal.querySelector('.logview-modal-message').textContent = message;
        modal.style.display = 'flex';
    }

    formatFileSize(bytes) {
        if (bytes < 1024) return `${bytes} B`;
        if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
        if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
        return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
    }

    escapeHtml(unsafe) {
        if (!unsafe) return ''; // Safety check
        return unsafe
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }

    // Helper function to escape regex special characters
    escapeRegex(string) {
        return string.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    }

}

    // ✅ Memory cleanup function for View Raw Logs tab
    function resetRawLogsMemory() {
      // Clear cached lines from global memory (if defined)
      if (window.rawLogLines) window.rawLogLines = [];

      // Reset number of lines loaded
      if (window.loadedLineCount !== undefined) window.loadedLineCount = 0;

      // Clear log content from DOM
      const content = document.getElementById('logview-content');
      if (content) content.innerHTML = '';

      // Reset the status text
      const status = document.getElementById('logview-status');
      if (status) status.textContent = '🟢 Ready and waiting...';

      console.debug('🧹 Raw Logs memory cleaned.');
    }
    
// Initialize when page loads
document.addEventListener('DOMContentLoaded', () => {
    try {
        window.logViewer = new LogViewer();
    } catch (error) {
        console.error('Initialization failed:', error);
        // Fallback UI error handling
        document.getElementById('logview-status').textContent = 'Initialization error - please refresh';
    }
});