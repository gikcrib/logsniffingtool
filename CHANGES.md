# CHANGES.md

## Iteration: BackendAPI_AbortFix
- Date: 2025-07-12
- Time: 11:30 PM (UTC+8)

### Changes:
- Fixed abort mechanism using threading.Event().
- Removed misuse of BackgroundTasks internal _tasks.
- Added /api/abort_search endpoint.
- Added /api/debug_search_status endpoint.
- Updated /api/search_logs to report active status, matches, files scanned.
- Provided detailed beginner-friendly comments.


## Iteration: BackendAPI_RealSearch
- Date: 2025-07-12
- Time: 11:50 PM (UTC+8)

### Changes:
- Replaced dummy loop with real file search logic.
- Streamed .log files line by line, skipping compressed files.
- Added case-insensitive search matching.
- Extracted thread ID and service per match.
- Captured snippet (inline or multi-line section).
- Maintained abort mechanism via threading.Event.
- Kept debug endpoint for status monitoring.
- Added beginner-friendly code comments.


## Iteration: BackendAPI_CleanupFix
- Date: 2025-07-12
- Time: 11:59 PM (UTC+8)

### Changes:
- Removed duplicated background task function.
- Kept only FastAPI handler for search.
- Switched to line-by-line reading for large file efficiency.
- Used helper functions consistently (is_compressed_file, extract_thread_id, extract_service).
- Maintained abort mechanism with threading.Event.
- Added detailed beginner-friendly comments for clarity.
- Prepared clean and safe code drop-in version.


## Iteration: FrontendWiring
- Date: 2025-07-13
- Time: 12:20 AM (UTC+8)

### Changes:
- Added JavaScript to handle search button, abort button, and show details modal.
- Connected backend API (/api/search_logs, /api/abort_search).
- Populates search results table dynamically.
- Logs actions to DevTools console for debugging.
- Includes copy-to-clipboard and modal close logic.


## Iteration: FrontendHTMLIntegration_Adjusted
- Date: 2025-07-13
- Time: [your confirmed integration time here]

### Changes:
- Adjusted 🔍 Search Tools HTML block as implemented by user:
  - Added “🔍 Select Option” label before radio buttons.
  - Rearranged element spacing using inline style.
  - Confirmed all required element IDs.
- Linked searchToolFrontEnd.js at end of <body>.
- Confirmed snapshot baseline alignment for next iterations.


## Iteration: FileListEndpointExpanded
- Date: 2025-07-13
- Time: 01:40 AM (UTC+8)

### Changes:
- Updated /api/list_log_files endpoint to include all non-compressed files, 
  not just .log files, in ./logs directory.
- Ensures fileSelect dropdown shows files like .log, .log.1, .txt, .md, etc.
- Kept code beginner-friendly with clear comments.


## Iteration: FrontendFileDropdown_Sorted
- Date: 2025-07-13
- Time: 02:10 AM (UTC+8)

### Changes:
- Updated populateFileSelect() function in searchToolFrontEnd.js.
- Added alphabetical (case-insensitive) sorting to file list before populating the target file dropdown.
- Added extra console log for before and after sort (for debugging).


## Iteration: FrontendFileSelect_DisableOnAllLogs
- Date: 2025-07-13
- Time: 02:30 AM (UTC+8)

### Changes:
- Added JS listener to disable fileSelect dropdown when "All Logs" is selected.
- Re-enables fileSelect when "Targeted Log" is selected.
- Logs state changes to DevTools console for clarity.

## Iteration: FrontendHTML_AbortButtonCleanup
- Date: 2025-07-13
- Time: 03:00 AM (UTC+8)

### Changes:
- Removed unnecessary Abort Search button from main search-filter-row section.
- Kept Abort button only inside the modal window where it belongs.
- Cleaned up UI to avoid duplicate Abort buttons.

## Iteration: FrontendModal_UniqueCSSFix
- Date: 2025-07-13
- Time: 03:30 AM (UTC+8)

### Changes:
- Updated modal HTML markup to use unique classes (search-modal, search-modal-content, search-spinner) for Search Tool modals.
- Added new dedicated CSS block in style.css to style Search Tool overlays without conflicting with baseline styles.
- Ensured modal windows now appear as proper overlays centered over the main page.

## Iteration: FrontendModalPlacement_Fix
- Date: 2025-07-13
- Time: 04:25 AM (UTC+8)

### Changes:
- Moved Search Tool modal HTML blocks to the bottom of index.html, right before </body>.
- Ensured modals are direct children of <body> for proper overlay behavior.
- Fixed issue where modals were nested under table containers, breaking layout.
