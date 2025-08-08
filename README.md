<p align="center">
  <img src="static/img/LogSniffingTool_512x512.png" alt="Log Sniffing Tool Logo" width="512" height="512">
</p>

<h1><img src="static/img/LogSniffingTool_60x60.png" alt="Log Sniffing Tool Logo" width="60" height="60"> Log Sniffing Tool</h1>

A portable log inspection tool for developers, QA testers, and support engineers who need to work with log files (<em>JBoss log files is currently supported</em>).

This project is designed with usability and performance in mind: offering error detection with a simple AI generated summary, XML parsing, full-text search, and large file viewing through a beginner-friendly web interface.

The **Log Sniffing Tool** project is still in BETA version (<em>**Version**: `v1.0.0.BETA_RELEASE` </em>), but the core features are stable and working. Development is still in progress and expect more changes in the future.

---

## ✨ Features
This tool is designed for internal use and offline log analysis. Created to assist with:
- Fast debugging
- Issue reproduction
- SOAP service inspection

### 🧑‍💻 Built With
- Python (e.g. FastAPI, uvicorn, aiofiles, Jinja2)
- JavaScript (Vanilla JS, DOM manipulation)
- HTML5 + CSS3 (custom responsive styling)
- Bash (SCP wrapper for remote downloads)

### 📥 Seamless Log Download from AWS
- Connects via SCP to your AWS environment.
- Downloads logs into local `./logs` folder.
- Real-time download progress with ETA and abort button.
- Automatically extracts compressed `.zip`, `.tar.gz`, `.gz` files.

### 🧪 Smart Error Scanner
- Scans logs for `[FATAL]`, `[ERROR]`, and `[WARN]` entries.
- Generates a simple AI generated summary of the logs.
- Populates a table where the error occurred, including:
  - Log file name
  - Line number
  - Thread ID
  - Service class
- Summary counters and color-coded error bars.

### 🧩 SOAP XML RQ/RS Parsing
- Detects and extracts all `XML Request:` and `XML Response:` payloads.
- Displays as a searchable table with:
  - Line number
  - Thread ID
  - Service class
  - RQ/RS XML (with clickable viewer)
- Highlights XML entries containing issues with a warning icon (⚠️).
- Pretty-printed modal viewer with copy-to-clipboard.
- The generated table can be downloaded with the CSV export support.

### 🔍 Keyword Search Tool
- Scans all logs or targeted logs for specific keywords.
- Displays matching lines, context, and metadata.
- Real-time streamed progress + Abort option.
- Summary metrics: files scanned, matched, time elapsed.

### 📜 Raw Log Viewer
- Scroll through entire logs like in Notepad++.
- Line-number navigation, in-page search, previous/next match.
- "Go to line" and "Copy" options.
- Virtual scroll memory optimization for large files.

---

## 📁 Project Structure

```
logsniffingtool/
├── main.py                          # Backend logic (FastAPI)
├── ai_module.py                     # Backend AI Assistant
├── scp_wrapper.sh                   # SCP wrapper for AWS download
├── scp_actual.pid                   # Runtime SCP tracking
├── applog/
│   └── fastAPI.log                  # Server logs
├── js/
│   ├── mainFrontEnd.js              # Error summary & XML
│   ├── searchToolFrontEnd.js        # Keyword search logic
│   └── viewrawlogs.js               # Raw log viewer
├── logs/                            # Location directory of the raw logs
├── static/
│   ├── style.css                    # Global styles
│   └── img/
│       ├── favicon.ico
│       ├── LogSniffingTool_60x60.png
│       ├── LogSniffingTool_512x512.png
│       └── LogSniffingTool_logo_1024x1024.png
├── templates/
│   └── index.html                   # Main tabbed interface
```

---

## ⚙️ Installation & Setup (for WSL Ubuntu)

### 🧱 Prerequisites
- Windows with WSL + Ubuntu installed
- Python 3.8+
- Basic familiarity with Linux terminal

### ✅ 1. Update System Packages
```bash
sudo apt update && sudo apt upgrade -y
```

### ✅ 2. Install Required Dependencies
```bash
sudo apt install -y python3 python3-pip python3-venv unzip curl openssh-client
```

### ✅ 3. Extract the Project
```bash
mkdir ~/logsniffingtool
cd ~/logsniffingtool
unzip /mnt/path/to/logsniffingtool.zip -d .
```

### ✅ 4. Create and Activate Python Virtual Environment (OPTIONAL)
```bash
python3 -m venv venv
source venv/bin/activate
```

### ✅ 5. Install Python Dependencies
```bash
cat > requirements.txt <<EOF
fastapi
uvicorn
pydantic
aiofiles
jinja2
psutil
python-Levenshtein
EOF

pip install -r requirements.txt
```

### ✅ 6. Make SCP Script Executable
```bash
chmod +x scp_wrapper.sh
```

### ✅ 7. Run the Tool
```bash
python3 -m uvicorn main:app --host 0.0.0.0 --port 8001 --reload
```
Then open in your browser:
```
http://localhost:8001
```
---

## 📚 User Guide

### 1. Download Logs
- Click **📥 Download Remote Logs**.
- Enter SCP details (hostname, username, file path).
- Wait for download to finish (real-time progress shown).
<p align="left">
  <img src="static/screenshots/DownloadingLogs.jpg" alt="Downloading Logs" width="750" height="363">
</p>

### 2. Analyze Logs
- Choose **All logs** or **Specific log** from the dropdown.
- Click **🧪 Review Logs** to begin analysis.
- View the generated summary analysis of the logs (<em>if specific logs is selected</em>)
- View errors and filter by Thread or Service.
<p align="left">
  <img src="static/screenshots/AnalyzeLogs.jpg" alt="Analyze Logs" width="750" height="363">
</p>
<p align="left">
  <img src="static/screenshots/ErrorSnippet.jpg" alt="Viewing Error Snippet" width="750" height="367">
</p>

### 3. Browse SOAP XML
- Switch to the **Parsed XMLs** tab.
- Filter by Thread ID, Service, or RQ/RS tag.
- Click on any tag to view formatted XML.
<p align="left">
  <img src="static/screenshots/ParsedXMLs.jpg" alt="Parsed RQ and RS XMLs from Logs" width="750" height="367">
</p>
<p align="left">
  <img src="static/screenshots/ViewXML.jpg" alt="Viewing Parsed RQ and RS XMLs" width="750" height="367">
</p>

### 4. Search Log Content
- Go to **Search Tools** tab.
- Enter keyword and select mode (All/Targeted).
- Click **🔍 Search** — results are streamed live.
- Click snippet row to view full context.
<p align="left">
  <img src="static/screenshots/SearchTool.jpg" alt="Search Tool" width="750" height="363">
</p>
<p align="left">
  <img src="static/screenshots/SearchToolSnippet.jpg" alt="Search Tool Snippet" width="750" height="363">
</p>

### 5. View Logs Like Text Editor
- Switch to **View Raw Logs** tab.
- Choose a file, click **📁 Load File**.
- Search, navigate, and copy directly like in Notepad++.
<p align="left">
  <img src="static/screenshots/ViewLogs.jpg" alt="View Raw Logs" width="750" height="363">
</p>

---

## ❓ FAQ

### Q: How do I update the log file list?
A: Click **🔄 Refresh List** in any tab to re-fetch log files.

### Q: What happens if SCP download fails?
A: A message will appear. Double-check SSH key, file path, or permissions.

### Q: Why do I see no XML in the SOAP tab?
A: Ensure the log contains `XML Request:` or `XML Response:` blocks.

### Q: Can I use this on Windows directly?
A: The tool is designed for WSL/Ubuntu. Native Windows support is not yet available.

### Q: Where do the logs go after SCP?
A: Extracted files are moved into the `./logs/` folder.

---

## 🛠️ Troubleshooting

| Issue                        | Solution                                                                                                                                                          |
| ---------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| SCP not working              | Ensure `scp` and `ssh` are installed: `sudo apt install openssh-client`. Also ensure you are signed in using `aws sso login` before attempting to connect to AWS. |
| Port 8001 already in use     | Use a different port: `--port 8002`                                                                                                                               |
| FastAPI not found            | Activate venv: `source venv/bin/activate`                                                                                                                         |
| XML viewer not loading       | Log may not have valid RQ/RS entries or JS error; try refresh                                                                                                     |
| Large logs crash the browser | Use **View Raw Logs** tab for memory-optimized viewing                                                                                                            |
