class LogViewer {
    constructor() {
		// DOM elements
		this.logContainer = document.getElementById('logview-content');
        // Core properties
        this.currentFile = null;
        this.totalLines = 0;
        this.lineHeight = 18; // px
        this.allLines = []; // Stores all lines of the loaded file
        this.isLoading = false;
        this.searchResults = [];
        this.currentSearchIndex = -1;
		this.currentSearchTerm = '';
		this.caseSensitive = false;
		this.wholeWord = false;
		
        
        // UI elements
        this.fileSelect = document.getElementById('logview-file-select');
        this.refreshBtn = document.getElementById('logview-refresh-btn');
        this.loadBtn = document.getElementById('logview-load-btn');
        this.searchInput = document.getElementById('logview-search-input');
        this.searchBtn = document.getElementById('logview-search-btn');
        this.copyBtn = document.getElementById('logview-copy-btn');
        this.logContainer = document.getElementById('logview-content');
        this.logViewport = document.getElementById('logview-viewport');
        this.statusBar = document.getElementById('logview-status');
        
        // Initialize
        // Initialize whole word checkbox
        this.wholeWordCheckbox = document.getElementById('logview-whole-word');
        this.wholeWordCheckbox.addEventListener('change', (e) => {
            this.wholeWord = e.target.checked;
            if (this.searchResults.length > 0) {
                this.navigateToCurrentResult(); // Re-highlight with new setting
            }
        });
        // Call setup methods
        this.setupEventListeners();
        this.refreshFileList(); // Populate dropdown on load
        this.setupMemoryCleanup();
    }

    setupMemoryCleanup() {
        window.addEventListener('beforeunload', () => {
            this.allLines = [];
            this.searchResults = [];
            this.logContainer.textContent = '';
        });

        // Optional: Add cleanup when changing files
        document.getElementById('logview-file-select')?.addEventListener('change', () => {
            this.cleanupMemory();
        });
    }

    cleanupMemory() {
        this.allLines = [];
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
		
		// Navigation
		this.logViewport.addEventListener('scroll', () => {
			// Can add scroll position tracking here if needed
			// Example: this.currentScrollPosition = this.logViewport.scrollTop;
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
		try {
			const response = await fetch('/api/logs/list');
			const data = await response.json();
			
			// Clear dropdown
			this.fileSelect.innerHTML = '<option value="">-- Select Target File --</option>';
			
			// Sort files by date (newest first) then by name
			const sortedFiles = data.files.sort((a, b) => {
				// Try to extract dates from filenames (common log patterns)
				const getDate = (filename) => {
					// Match patterns like: 
					// - server.log.2023-12-31
					// - error_20231231.log
					// - 2023-12-31_app.log
					const dateMatch = filename.match(/(\d{4})[-_]?(\d{2})[-_]?(\d{2})/);
					return dateMatch ? new Date(`${dateMatch[1]}-${dateMatch[2]}-${dateMatch[3]}`) : new Date(0);
				};
				
				const dateA = getDate(a.name);
				const dateB = getDate(b.name);
				
				// Sort by date descending (newest first)
				if (dateB - dateA !== 0) return dateB - dateA;
				
				// If dates are equal, sort alphabetically
				return a.name.localeCompare(b.name);
			});

			// Add grouped options (recent files first)
			const today = new Date();
			const recentCutoff = new Date();
			recentCutoff.setDate(today.getDate() - 7); // Files from last 7 days
			
			let addedRecentHeader = false;
			let addedOlderHeader = false;

			sortedFiles.forEach(file => {
				const fileDate = file.name.match(/(\d{4})[-_]?(\d{2})[-_]?(\d{2})/)
					? new Date(file.name.replace(/(\d{4})[-_]?(\d{2})[-_]?(\d{2})/, '$1-$2-$3'))
					: null;

				// Add section header for recent files
				if (fileDate && fileDate >= recentCutoff && !addedRecentHeader) {
					this.addDropdownSectionHeader('── Recent Files ──');
					addedRecentHeader = true;
				}
				// Add section header for older files
				else if ((!fileDate || fileDate < recentCutoff) && !addedOlderHeader && addedRecentHeader) {
					this.addDropdownSectionHeader('── Older Files ──');
					addedOlderHeader = true;
				}

				// Create file option
				const option = document.createElement('option');
				option.value = file.name;
				
				// Enhanced display text
				let displayText = file.name;
				if (fileDate) {
					displayText += ` (${fileDate.toLocaleDateString()})`;
				}
				displayText += ` - ${this.formatFileSize(file.size)}`;
				
				option.textContent = displayText;
				this.fileSelect.appendChild(option);
			});

			this.showToast(`Loaded ${sortedFiles.length} log files`);
		} catch (error) {
			this.showModal('Error', `Failed to refresh files: ${error.message}`);
		}
	}
    
	async loadSelectedFile() {
		const selectedFile = this.fileSelect.value;
		if (!selectedFile) {
			this.showModal('Warning', 'Please select a file first');
			return;
		}

		try {
			// Reset state
			this.currentFile = selectedFile;
			this.allLines = [];
			this.totalLines = 0;
			this.searchResults = [];
			this.currentSearchIndex = -1;
			
			// Show loading state directly in the container
			this.logContainer.innerHTML = '<div class="logview-loading">Loading file...<div class="loading-spinner"></div></div>';
			
			// Load file
			const response = await fetch(`/api/logs/stream?filename=${encodeURIComponent(selectedFile)}`);
			const data = await response.json();
			
			this.allLines = data.lines;
			this.totalLines = data.total_lines;
			
			// Render all lines at once
			this.renderAllLines();
			this.updateStatus(`Loaded ${selectedFile} - ${this.totalLines.toLocaleString()} lines`);
		} catch (error) {
			this.showModal('Error', `Failed to load file: ${error.message}`);
		}
	}

    renderAllLines() {
        // Create document fragment for better performance
        const fragment = document.createDocumentFragment();
        const container = document.createElement('div');
        
        // Build all lines
        this.allLines.forEach((line, index) => {
            const lineNumber = index + 1;
            const lineElement = document.createElement('div');
            lineElement.className = 'logview-line';
            lineElement.dataset.line = lineNumber;
            
            lineElement.innerHTML = `
                <span class="logview-line-number">${lineNumber}</span>
                <span class="logview-line-content">${this.escapeHtml(line)}</span>
            `;
            
            // Highlight if this line is in search results
            if (this.searchResults.includes(lineNumber)) {
                lineElement.classList.add('logview-line-highlight');
            }
            
            container.appendChild(lineElement);
        });
        
        fragment.appendChild(container);
        this.logContainer.innerHTML = '';
        this.logContainer.appendChild(fragment);
        
        // Set container height based on line count
        this.logContainer.style.height = `${this.totalLines * this.lineHeight}px`;
    }

    performSearch() {
        const query = this.searchInput.value.trim();
        if (!query) {
            this.showModal('Warning', 'Please enter a search term');
            return;
        }

        this.currentSearchTerm = query;
        this.searchResults = [];
        const searchTerm = query.toLowerCase();
        
        // Clear previous highlights
        this.clearSearchHighlights();

        // Find all matches
        this.allLines.forEach((line, index) => {
            if (line.toLowerCase().includes(searchTerm)) {
                this.searchResults.push(index + 1); // Store line numbers
            }
        });

        if (this.searchResults.length === 0) {
            this.showModal('Not Found', `"${query}" was not found in the file.`);
            return;
        }

        this.currentSearchIndex = 0;
        this.updateStatus(`Found ${this.searchResults.length} matches`);
        this.navigateToCurrentResult();
		
		if (this.searchResults.length > 0) {
			this.searchInput.classList.add('has-results');
		} else {
			this.searchInput.classList.remove('has-results');
		}

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
        this.highlightCurrentSearchResult();
        this.updateStatus(`Match ${this.currentSearchIndex + 1} of ${this.searchResults.length}`);
    }

	highlightCurrentSearchResult() {
		// Remove previous highlights
		document.querySelectorAll('.logview-line-current, .search-match').forEach(el => {
			el.classList.remove('logview-line-current');
			if (el.classList.contains('search-match')) {
				const parent = el.parentNode;
				if (parent) {
					parent.textContent = parent.textContent; // Reset content
				}
			}
		});

		const lineElement = document.querySelector(
			`.logview-line[data-line="${this.searchResults[this.currentSearchIndex]}"]`
		);
		
		if (lineElement) {
			// Highlight the entire line
			lineElement.classList.add('logview-line-current');
			
			// Highlight the matched text - SAFELY
			const contentSpan = lineElement.querySelector('.logview-line-content');
			if (contentSpan) {
				const searchTerm = this.currentSearchTerm;
				const textContent = contentSpan.textContent;
				let escapedTerm = this.escapeRegex(searchTerm);
				
				// Add whole word boundaries if enabled
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
        const lineElement = document.querySelector(`.logview-line[data-line="${lineNumber}"]`);
        if (lineElement) {
            lineElement.scrollIntoView({
                behavior: 'smooth',
                block: 'center'
            });
        }
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

    // Helper methods

	// Helper method for dropdown sections
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
        if (selection.toString().length > 0) {
            navigator.clipboard.writeText(selection.toString())
                .then(() => this.showToast('Text copied to clipboard'))
                .catch(err => this.showModal('Error', 'Failed to copy text: ' + err));
        } else {
            this.showModal('Warning', 'Please select some text to copy first');
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