# CHANGES.md

## Iteration: BASELINE files
- Date: 2025-07-28
- Time: 07:12 AM (UTC+8)

### Changes:
- Initial commits

---

## Iteration: ThreadID_Fix_RQRS_v1  
- Date: 2025-07-28  
- Time: 03:32 PM (UTC+8)  

### 🔧 Changes Applied:
- 🛠️ **main.py**:
  - Fully replaced the `parse_log_file()` function to fix incorrect `Thread ID = UNKNOWN` in the `rqrsTable`.
  - Implemented `last_timestamp_line` logic to properly capture the correct thread ID line preceding RQ/RS XML entries.
  - Removed the old `previous_line` usage to prevent misleading fallbacks.
  - Ensured changes are memory-safe and work with large files via chunked reading.

---

## Iteration: FIX_Search_Functionality  
- Date: 2025-07-30  
- Time: 09:23 PM (UTC+8)  

### 🔧 Changes Applied:
- 🛠️ **main.py**:
  - Updated the logic of `/api/search_logs_stream` endpoint
  - Remove the clear() call here - let the search loop handle clearing from `/api/abort_search` endpoint
  - Updated `searchToolFrontEnd.js` and frontend `index.html` for the Search tab functionality