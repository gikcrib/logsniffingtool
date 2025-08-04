# 📘 Log Sniffer Tool

A simple and easy-to-use web tool for scanning log files. 
This tool is designed for non-technical users to quickly inspect logs from local or remote servers using a clean web interface — all within a WSL Ubuntu environment.

---

## ✨ Features (Updated)

- ✅ Web-based interface built with FastAPI
- 🪵 Automatically saves console and application logs to `applog/fastAPI.log`
- 🔁 Log rotation enabled (up to 100MB per file, keeps 5 backups)
- 💻 (Optional) Fetch logs from a remote server using `scp_wrapper.sh`
- 🎛️ Simple interface with HTML templates and static CSS styling

---

## 📁 Folder Structure

```
jbossQuickLogScanner/
├── main.py                 # FastAPI backend with logging setup
├── scp_wrapper.sh          # (External) Bash script for SCP log fetching
├── templates/
│   └── index.html          # Web interface (Jinja2 template)
├── static/
│   └── style.css           # CSS styling
├── applog/
│   └── fastAPI.log         # Rotating log file (generated automatically)
├── scp_actual.pid          # (Optional) PID tracker for SCP background process
├── README.md               # Project documentation (this file)
```

---

## 🛠️ Setup Instructions (for WSL Ubuntu)

### 🔹 1. Install Required System Packages

```bash
sudo apt update
sudo apt install -y python3 python3-pip openssh-client unzip
```

---

### 🔹 2. (Optional) Create a Python Virtual Environment

```bash
sudo apt install -y python3-venv
cd ~
mkdir jbossQuickLogScanner
cd jbossQuickLogScanner
python3 -m venv venv
source venv/bin/activate
```

To deactivate when finished:
```bash
deactivate
```

---

### 🔹 3. Install Python Dependencies

```bash
pip install fastapi uvicorn jinja2 python-multipart psutil
```

---

### 🔹 4. Unzip the Project Files

```bash
cd ~
mkdir jbossQuickLogScanner
cd jbossQuickLogScanner
unzip /path/to/jbossQuickLogScanner.zip
```

---

## 🚀 Running the App

Start the FastAPI server:
```bash
uvicorn main:app --reload
```

Open your browser and navigate to:
```
http://127.0.0.1:8000
```

---

## 🪵 Logging Behavior

- **All app and console logs** are written to:
  ```
  applog/fastAPI.log
  ```

- **Log rotation settings:**
  - Max file size: 100MB
  - Backup files: 5

- **Log entry format:**
  ```
  [YYYY-MM-DD HH:MM:SS] [LEVEL] Message
  ```

Example:
```
[2025-07-09 12:34:56] [INFO] Application started
```

---

## 🔧 Optional: Remote Log Fetching

The project includes optional tools:
- `scp_wrapper.sh`: Bash script to securely copy logs from a remote server using `scp`
- `scp_actual.pid`: Tracks the SCP process if run in the background

**Note:** These are currently manual tools. There’s no UI integration for remote fetch in the web interface.

---

## ✅ Future Ideas / To-Do

- Add log filtering or search in the web UI
- Provide status or progress bar for remote log fetch
- Dockerize for easier deployment and portability

---

## 🧑‍💻 Author

Created as a personal utility project to simplify JBoss log inspection and management.

---
