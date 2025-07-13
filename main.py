
from fastapi import FastAPI, Request, Query, HTTPException, Response, BackgroundTasks
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse, PlainTextResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from subprocess import Popen, PIPE
from pathlib import Path
import shutil, asyncio, os, re, difflib, json, time, subprocess, math, logging, sys, aiofiles, threading
from threading import Thread
import psutil
import subprocess
import signal
import zipfile
import tarfile
import gzip
import traceback
from xml.dom import minidom
from logging.handlers import RotatingFileHandler
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Dict, Any, Optional

# Initialize logging - Optimizing FastAPI Log Processing Application
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize FastAPI
app = FastAPI()

# Dictionary to store metrics - for psutil memory monitor
endpoint_metrics = {}

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount the /js and /static directory as static
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/js", StaticFiles(directory="js"), name="js")

templates = Jinja2Templates(directory="templates")

LOG_DIR = "./logs"
RQRS_CACHE = {}
LOG_CACHE_META = {}

SCP_PROGRESS = {"percent": 0, "eta": 0}
SCP_PROC = None
SCP_ABORTED = False

ERROR_PATTERNS = re.compile(r"\[(ERROR|WARN|FATAL)\]")
SERVICE_PATTERN = re.compile(r"\[(com\.datalex\..+?)\]")

# --- Backend Search API Implementation START ---
# Global abort event
abort_event = threading.Event()

# Debug status store
status = {
    "search_active": False,
    "matches_found": 0,
    "files_scanned": 0
}

# Request model
class SearchRequest(BaseModel):
    search_text: str
    search_mode: str
    target_file: Optional[str] = None

# Log directory
LOG_DIR = './logs/'

# Regex patterns
TIMESTAMP_PATTERN = re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2},\d{3}')
THREAD_ID_PATTERN = re.compile(r'\[(\d{13}_\d{4}|NDC|REST)\]')

# --- Helper functions ---

def is_compressed_file(filename):
    """Check if file is compressed by extension."""
    return filename.endswith(('.zip', '.tar', '.tar.gz', '.gz', '.7z', '.Z'))

def extract_thread_id(line):
    """Extract thread ID from line."""
    match = THREAD_ID_PATTERN.search(line)
    return match.group(1) if match else 'N/A'

def extract_service(line):
    """Extract service name from line (simple demo logic)."""
    match = re.search(r'\[([a-zA-Z0-9\.]+)\]', line)
    return match.group(1) if match else 'UnknownService'
# --- Backend Search API Implementation END ---


################################
# Logger - Start
################################
# === Logging Setup ===
LOG_OUTPUT_DIR = "./applog"
os.makedirs(LOG_OUTPUT_DIR, exist_ok=True)
log_file_path = os.path.join(LOG_OUTPUT_DIR, "fastAPI.log")

# Create logger
logger = logging.getLogger("fastapi_logger")
logger.setLevel(logging.DEBUG)

# File handler with rotation (100MB, keep last 5 logs)
file_handler = RotatingFileHandler(
    log_file_path,
    maxBytes=100 * 1024 * 1024,  # 100 MB
    backupCount=5,
    encoding='utf-8'
)

# Console handler
console_handler = logging.StreamHandler()

# Formatter
formatter = logging.Formatter('[%(asctime)s] [%(levelname)s] %(message)s')
file_handler.setFormatter(formatter)
console_handler.setFormatter(formatter)

# Attach handlers
logger.addHandler(file_handler)
logger.addHandler(console_handler)

# === printf() utility ===
def printf(msg: str, level: str = "info"):
    level = level.lower()
    if level == "info":
        logger.info(msg)
    elif level == "error":
        logger.error(msg)
    elif level in ("warn", "warning"):
        logger.warning(msg)
    elif level == "debug":
        logger.debug(msg)
    else:
        logger.info(msg)

# Optional: override print() to behave like printf
print = lambda *args, **kwargs: printf(" ".join(str(a) for a in args), level="info")
################################
# Logger - END
################################

class SCPDownloadRequest(BaseModel):
    host: str
    username: str = "remotedeploy"
    remote_path: str = "/datalex/logs/jboss"
    pattern: str = "matrixtdp4.log*"
    clear_existing: bool = False

def extract_compressed_files():
    for file in os.listdir(LOG_DIR):
        file_path = os.path.join(LOG_DIR, file)
        try:
            if file.endswith(".zip"):
                with zipfile.ZipFile(file_path, 'r') as zip_ref:
                    zip_ref.extractall(LOG_DIR)
                    print(f"🗂️ Extracted {file} as ZIP")
                os.remove(file_path)
                print(f"🗑️ Deleted ZIP file: {file}")

            elif file.endswith((".tar.gz", ".tgz", ".tar")):
                with tarfile.open(file_path, 'r:*') as tar_ref:
                    tar_ref.extractall(LOG_DIR)
                    print(f"🗂️ Extracted {file} as TAR")
                os.remove(file_path)
                print(f"🗑️ Deleted TAR file: {file}")

            elif file.endswith(".gz") and not file.endswith((".tar.gz", ".tgz")):
                out_path = os.path.splitext(file_path)[0]
                with gzip.open(file_path, 'rb') as f_in:
                    with open(out_path, 'wb') as f_out:
                        shutil.copyfileobj(f_in, f_out)
                        print(f"🗂️ Extracted {file} as GZ → {os.path.basename(out_path)}")
                os.remove(file_path)
                print(f"🗑️ Deleted GZ file: {file}")

        except Exception as e:
            print(f"❌ Failed to extract {file}: {e}")

    # ✅ Move all discovered .log files from subdirectories to ./logs
    for root, dirs, files in os.walk(LOG_DIR):
        for file in files:
            if file.endswith(".log"):
                full_path = os.path.join(root, file)
                if os.path.abspath(root) != os.path.abspath(LOG_DIR):
                    target_path = os.path.join(LOG_DIR, file)
                    try:
                        shutil.move(full_path, target_path)
                        print(f"📂 Moved extracted {file} → {target_path}")
                    except Exception as move_err:
                        print(f"❌ Failed to move {file}: {move_err}")


def similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()

def extract_service(line: str) -> str:
    matches = SERVICE_PATTERN.findall(line)
    if matches:
        return matches[-1].split(".")[-1]
    return "UNKNOWN"

def smart_preload_rqrs():
    global RQRS_CACHE, LOG_CACHE_META
    updated_cache, updated_meta = {}, {}

    for file in os.listdir(LOG_DIR):
        full_path = os.path.join(LOG_DIR, file)
        if not os.path.isfile(full_path):
            continue
        try:
            mtime = os.path.getmtime(full_path)
        except Exception:
            continue
        updated_meta[file] = mtime
        if file not in LOG_CACHE_META or LOG_CACHE_META[file] != mtime:
            with open(full_path, encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
            entries = []
            for idx in range(1, len(lines)):
                current = lines[idx].strip()
                match = re.search(r'<([a-zA-Z_][\w]*?(RQ|RS))[\s>]', current)
                if match:
                    is_inline_xml = bool(re.match(r'^\d{4}-\d{2}-\d{2}', current))
                    line_number = idx + 1
                    source_line = current if is_inline_xml else lines[idx - 1].strip()

                    # ✅ Match known thread ID formats
                    thread_match = re.search(r'\[(NDC_[^\]]+?)\]', source_line) or \
                                   re.search(r'\[NA\] \[([^\]]+?)\] \[NA\]', source_line)

                    if thread_match:
                        thread_id = thread_match.group(1)
                    else:
                        # ✅ Fallback: Match pattern like 1751502945348_9656 inside any [bracket]
                        bracketed = re.findall(r'\[([^\[\]]+)\]', source_line)
                        thread_id = next((x for x in bracketed if re.match(r'\d{13}_\d{4,}', x)), "UNKNOWN")

                    # 🪵 Debugging aid
                    # print(f"[🧩 RQRS] smart_preload → source_line: {source_line}")
                    # print(f"[🧩 RQRS] smart_preload → thread_id: {thread_id}")

                    root_tag = match.group(1)
                    entries.append({
                        "line": line_number,
                        "thread": thread_id,
                        "tag": root_tag,
                        "raw": current
                    })
            updated_cache[file] = entries
        else:
            updated_cache[file] = RQRS_CACHE.get(file, [])

    RQRS_CACHE = updated_cache
    LOG_CACHE_META = updated_meta

@app.on_event("startup")
async def startup_event():
    smart_preload_rqrs()

@app.get("/", response_class=HTMLResponse)
async def serve_ui(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

################################
# psutil memory monitoring - Start
################################

@app.middleware("http")
async def memory_middleware(request: Request, call_next):
    process = psutil.Process()
    system_mem = psutil.virtual_memory()
    
    # --- Memory Protection Check (NEW) ---
    if system_mem.percent > 90 or system_mem.available < 100 * 1024 * 1024:  # 100MB threshold
        error_msg = {
            "error": "Server memory constrained",
            "detail": {
                "system_memory_percent": system_mem.percent,
                "available_mb": round(system_mem.available/1024/1024, 1),
                "suggestion": "Try again later or use smaller files"
            }
        }
        print(f"🚨 MEMORY PROTECTION TRIGGERED: {error_msg}")
        return JSONResponse(error_msg, status_code=503)
    
    # --- Before request ---
    mem_before = process.memory_info().rss / 1024 / 1024  # MB
    start_time = time.time()
    
    try:
        # --- Process request ---
        response = await call_next(request)
        
    except Exception as e:
        # --- Error Handling ---
        elapsed = time.time() - start_time
        print(f"❌ Error in {request.url.path}: {str(e)} [{elapsed:.2f}s]")
        raise
    
    # --- After request ---
    mem_after = process.memory_info().rss / 1024 / 1024
    elapsed = time.time() - start_time
    memory_used = mem_after - mem_before
    
    # --- System Memory Check ---
    if system_mem.percent > 80:
        print(f"🚨 WARNING: System memory at {system_mem.percent}%")
        print(f"    Available: {system_mem.available/1024/1024:.1f}MB")
        print(f"    Used by Python: {mem_after:.1f}MB")
        print(f"    Request consumed: {memory_used:.1f}MB")
    
    # --- Per-Request Metrics ---
    endpoint_metrics[request.url.path] = {
        "memory_used_mb": round(memory_used, 2),
        "system_memory_percent": system_mem.percent,
        "time_sec": round(elapsed, 2),
        "timestamp": datetime.now().isoformat()  # NEW: Added timestamp
    }
    
    # --- Request Timing Log ---
    status_code = getattr(response, "status_code", 500)
    print(f"{request.method} {request.url.path} ({status_code}) {elapsed:.2f}s | +{memory_used:.1f}MB")  # Enhanced logging
    
    return response
# Your regular endpoints (no decorators needed)
@app.get("/light")
async def light_endpoint():
    return {"message": "Light endpoint"}

@app.get("/heavy")
async def heavy_endpoint():
    big_list = [i for i in range(1_000_000)]  # ~40MB
    return {"message": "Heavy endpoint"}

@app.get("/metrics")
async def show_metrics():
    return endpoint_metrics
################################
# psutil memory monitoring - END
################################

@app.get("/list_logs")
async def list_logs():
    return {"logs": sorted(f for f in os.listdir(LOG_DIR) if os.path.isfile(os.path.join(LOG_DIR, f)))}

@app.get("/scp_progress")
async def scp_progress():
    async def event_stream():
        last_sent = None
        while True:
            if last_sent != SCP_PROGRESS:
                yield f"data: {json.dumps(SCP_PROGRESS)}\n\n"
                last_sent = SCP_PROGRESS.copy()
            if SCP_PROGRESS["percent"] >= 100:
                break
            await asyncio.sleep(0.5)
    return StreamingResponse(event_stream(), media_type="text/event-stream")

def format_bytes(size):
    for unit in ['B', 'k', 'M', 'G', 'T']:
        if size < 1024:
            return f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}P"

@app.post("/download_remote_logs")
async def download_remote_logs(request: Request, req: SCPDownloadRequest):
    global SCP_PROGRESS, SCP_PROC, SCP_ABORTED
    SCP_PROGRESS = {"percent": 0, "eta": 0}
    SCP_ABORTED = False
    start_time = time.time()

    if req.clear_existing:
        for f in os.listdir(LOG_DIR):
            fp = os.path.join(LOG_DIR, f)
            if os.path.isfile(fp):
                os.remove(fp)

    remote = f"{req.username}@{req.host}:{req.remote_path}/{req.pattern}"
    scp_cmd = ["bash", "./scp_wrapper.sh", "-p", remote, LOG_DIR]
    print(f"📥 Running SCP command: {' '.join(scp_cmd)}")

    try:
        ssh_cmd = ["ssh", f"{req.username}@{req.host}", f"du -cb {req.remote_path}/{req.pattern} | tail -1 | cut -f1"]
        stdout = subprocess.check_output(ssh_cmd, stderr=subprocess.DEVNULL, text=True).strip()
        total_bytes = int(stdout) if stdout.isdigit() else 0
        print(f"📦 Remote file size: {total_bytes} bytes")
    except Exception as e:
        print(f"⚠️ Failed to get remote file size: {e}")
        total_bytes = 0

    scp_status = {"done": False, "error": None}

    def format_eta(seconds):
        if seconds < 0:
            return "unknown"
        minutes, secs = divmod(seconds, 60)
        if minutes > 0:
            return f"{minutes}m {secs}s"
        return f"{secs}s"

    def run_scp():
        global SCP_PROGRESS, SCP_PROC, SCP_ABORTED
        try:
            SCP_PROC = Popen(
                scp_cmd,
                stdout=PIPE,
                stderr=PIPE,
                text=True,
                start_new_session=True
            )

            while SCP_PROC.poll() is None:
                if SCP_ABORTED:
                    print("🛑 Aborting SCP from UI...")
                    try:
                        print(f"🔍 SCP_PROC PID: {SCP_PROC.pid}")
                        parent = psutil.Process(SCP_PROC.pid)
                        print(f"🔍 Parent cmdline: {parent.cmdline()}")
                        for child in parent.children(recursive=True):
                            print(f"🔍 Killing child PID: {child.pid} cmdline: {child.cmdline()}")

                        for _ in range(10):
                            if SCP_PROC.poll() is not None:
                                break
                            print("⌛ Waiting for SCP to terminate...")
                            time.sleep(0.5)
                    except Exception as e:
                        print(f"❌ Error during abort: {e}")

                    SCP_PROGRESS = {"percent": 0, "eta": 0}
                    scp_status["error"] = "Download aborted by user."
                    break

                current_size = sum(
                    os.path.getsize(os.path.join(LOG_DIR, f))
                    for f in os.listdir(LOG_DIR)
                    if os.path.isfile(os.path.join(LOG_DIR, f))
                )
                elapsed = time.time() - start_time
                rate = current_size / elapsed if elapsed > 0 else 0
                percent = int(current_size / total_bytes * 100) if total_bytes else 0
                eta = int((total_bytes - current_size) / rate) if rate > 0 else -1
                SCP_PROGRESS = {
                    "percent": percent,
                    "eta": eta,
                    "eta_str": format_eta(eta)  # 🆕 added nicely formatted ETA
                }
                print(f"📊 SCP Progress → {percent}% | ETA: {eta}s | File Size: {format_bytes(current_size)}/{format_bytes(total_bytes)}")
                time.sleep(1)

            if not SCP_ABORTED:
                stdout, stderr = SCP_PROC.communicate()
                print(f"📦 SCP return code: {SCP_PROC.returncode}")
                print("📤 SCP stdout:", stdout.strip())
                print("📛 SCP stderr:", stderr.strip())

                if SCP_PROC.returncode == 0:
                    print("✅ SCP completed successfully.")
                    extract_compressed_files()  # 🆕 Extract logs after SCP
                    smart_preload_rqrs()
                else:
                    # Allow empty stderr if returncode is still 0
                    if stderr.strip() == "":
                        print("⚠️ SCP ended with no error output but returned a non-zero exit code.")
                        smart_preload_rqrs()
                    else:
                        scp_status["error"] = f"SCP failed: {stderr.strip()}"
            else:
                print("🚫 SCP was aborted. Skipping output handling.")

        except Exception as e:
            scp_status["error"] = str(e)
        finally:
            SCP_PROGRESS = {"percent": 100, "eta": 0}
            scp_status["done"] = True
            SCP_PROC = None
            SCP_ABORTED = False

    Thread(target=run_scp, daemon=True).start()

    while not scp_status["done"]:
        await asyncio.sleep(1)

    if scp_status["error"]:
        return {"status": "error", "message": scp_status["error"]}
    return {"status": "success", "message": "Logs downloaded and processed successfully."}

@app.post("/abort_download")
async def abort_download():
    global SCP_ABORTED
    SCP_ABORTED = True
    print("🚫 Abort requested.")

    try:
        with open("scp_actual.pid") as f:
            pid = int(f.read().strip())
        print(f"🧨 Killing SCP PID {pid}")
        os.kill(pid, signal.SIGKILL)
        print(f"✅ Sent SIGKILL to PID {pid}")
    except Exception as e:
        print(f"❌ Failed to abort SCP: {e}")

    return {"status": "ok", "message": "Abort signal sent."}


@app.post("/abort_scp")
def abort_scp():
    global SCP_ABORTED
    SCP_ABORTED = True
    return {"status": "Abort requested"}

@app.post("/analyze_logs")
async def analyze_logs(request: Request):
    try:
        data = await request.json()
        mode = data.get("mode")
        specific_log = data.get("log")
        
        log_dir = Path("./logs")
        error_counts = {"FATAL": 0, "ERROR": 0, "WARN": 0}
        error_details = []

        # Define compressed extensions to exclude
        compressed_exts = (".zip", ".tar", ".tar.gz", ".gz", ".7z", ".rar")

        # Helper to determine if a file is text-based log
        def is_readable_log(file: Path):
            return file.is_file() and not any(str(file).lower().endswith(ext) for ext in compressed_exts)

        # Choose files
        if mode == "all":
            log_files = [f for f in log_dir.iterdir() if is_readable_log(f)]
        else:
            if not specific_log:
                return JSONResponse({"error": "No log file specified."}, status_code=400)
            specific_path = log_dir / specific_log
            if not specific_path.exists():
                return JSONResponse({"error": f"File '{specific_log}' not found."}, status_code=400)
            log_files = [specific_path]

        for file_path in log_files:
            try:
                with file_path.open("r", encoding="utf-8", errors="ignore") as f:
                    for line_number, line in enumerate(f, 1):
                        if any(x in line for x in ["[FATAL]", "[ERROR]", "[WARN]"]):
                            # Determine level
                            level = None
                            for lvl in ["FATAL", "ERROR", "WARN"]:
                                if f"[{lvl}]" in line:
                                    level = lvl
                                    error_counts[level] += 1
                                    break

                            # Extract Thread ID (first [xxx] after timestamp, usually 2nd group)
                            thread_match = re.findall(r"\[([^\[\]]*)\]", line)
                            thread_id = thread_match[1] if len(thread_match) > 1 else "N/A"

                            # Extract Service (look for bracketed full class name, use last segment)
                            service = "N/A"
                            for val in thread_match:
                                if "." in val:
                                    service = val.split(".")[-1]
                                    break

                            error_details.append({
                                "log_file": file_path.name,
                                "line_number": line_number,
                                "thread_id": thread_id,
                                "service": service,
                                "error_message": line.strip()
                            })
            except Exception as file_error:
                print(f"[WARN] Failed to scan {file_path.name}: {file_error}")
                traceback.print_exc()
                continue

        return {
            "counts": error_counts,
            "errors": error_details
        }

    except Exception as top_level_error:
        print(f"[❌ ERROR] analyze_logs failed: {top_level_error}")
        traceback.print_exc()
        return JSONResponse({"error": "Internal Server Error"}, status_code=500)
 
################################################
# Improved processing the get_rqrs endpoint
# when capturing RQ/RS XMLs - START
################################################
# Pre-compiled regex patterns (optimized)
RX_RQRS = re.compile(r'<([a-zA-Z_][\w]*?(RQ|RS))[\s>]')
RX_DATE = re.compile(r'^\d{4}-\d{2}-\d{2}')
RX_THREAD = re.compile(r'\[(NDC_[^\]]+?)\]')
RX_ALT_THREAD = re.compile(r'\[NA\] \[([^\]]+?)\] \[NA\]')
RX_BRACKETED = re.compile(r'\[([^\[\]]+)\]')
RX_THREAD_FALLBACK = re.compile(r'\d{13}_\d{4,}')
RX_ERRORS = re.compile(r'<(ns1:)?Errors>|<.*Error.*>|ErrorCode|WarningCode', re.IGNORECASE)

# Constants
# LOG_DIR = "./logs"  # Configure your log directory - already declared on top
MAX_WORKERS = 2  # Reduced thread pool size (better for memory)
PROGRESS_INTERVAL = 10000  # Increased interval for less frequent updates
BATCH_SIZE = 500  # Smaller batch size for better memory control
MAX_CACHE_SIZE = 10  # Limit cache to 10 most recent files

################################################
# Manual Async LRU Cache Implementation - START
################################################
class AsyncLRUCache:
    def __init__(self, maxsize: int = 128):
        self.maxsize = maxsize
        self.cache: Dict[str, Any] = {}
        self.lock = asyncio.Lock()
        self.order = []

    async def get(self, key: str) -> Optional[Any]:
        async with self.lock:
            if key in self.cache:
                # Move to end to mark as recently used
                self.order.remove(key)
                self.order.append(key)
                return self.cache[key]
            return None

    async def set(self, key: str, value: Any) -> None:
        async with self.lock:
            if key in self.cache:
                # Update existing and move to end
                self.cache[key] = value
                self.order.remove(key)
                self.order.append(key)
            elif len(self.cache) >= self.maxsize:
                # Evict oldest if cache is full
                oldest = self.order.pop(0)
                logger.info(f"[🗑️] Evicting oldest cache entry: {oldest}")
                del self.cache[oldest]
                self.cache[key] = value
                self.order.append(key)
            else:
                # Add new entry (cache not full)
                self.cache[key] = value
                self.order.append(key)

# Global cache instance
LOG_CACHE = AsyncLRUCache(maxsize=MAX_CACHE_SIZE)
################################################
# Manual Async LRU Cache Implementation - END
################################################

def format_time(seconds: float) -> str:
    """Convert seconds to HH:MM:SS format"""
    return str(timedelta(seconds=seconds))

def memory_safe(min_mb=100) -> bool:
    """Check if system has sufficient memory"""
    return psutil.virtual_memory().available > min_mb * 1024 * 1024

def process_line(line_number: int, current: str, previous: str):
    """
    Optimized line processor with early returns
    Returns None if line doesn't contain RQ/RS
    """
    if not (match := RX_RQRS.search(current)):
        return None
        
    is_inline_xml = bool(RX_DATE.match(current))
    source_line = current if is_inline_xml else previous
    
    # Thread ID extraction with fallbacks
    thread_match = (RX_THREAD.search(source_line) or 
                   RX_ALT_THREAD.search(source_line))
    
    thread_id = thread_match.group(1) if thread_match else None
    if not thread_id:
        bracketed = RX_BRACKETED.findall(source_line)
        thread_id = next((x for x in bracketed if RX_THREAD_FALLBACK.match(x)), "UNKNOWN")
    
    return {
        "line": line_number,
        "thread": thread_id,
        "tag": match.group(1),
        "raw": current[:512],  # Further reduced truncation
        "has_issue": bool(RX_ERRORS.search(current))
    }

async def parse_log_file(log: str):
    """Optimized main log parsing function with enhanced progress tracking"""
    # Cache check remains first (unchanged)
    cached_result = await LOG_CACHE.get(log)
    if cached_result is not None:
        logger.info(f"[♻️] Cache HIT for {log}")
        return cached_result
    
    logger.info(f"[🔄] Cache MISS for {log}, processing...")
    start_time = time.time()
    last_progress_log = start_time
    last_match_time = start_time
    
    if not memory_safe():
        raise HTTPException(503, detail="Server memory constrained")

    filepath = os.path.join(LOG_DIR, log)
    entries = []
    previous_line = ""
    line_count = 0
    total_lines = 0  # We'll count this first for accurate progress

    # First pass: count total lines (for accurate progress %)
    try:
        async with aiofiles.open(filepath, mode='r', encoding='utf-8', errors='ignore') as f:
            async for _ in f:
                total_lines += 1
    except FileNotFoundError:
        raise HTTPException(404, detail=f"Log file not found: {log}")

    # Second pass: actual processing
    try:
        async with aiofiles.open(filepath, mode='r', encoding='utf-8', errors='ignore') as f:
            async for line in f:
                line_count += 1
                if line_count == 1:  # Skip header
                    continue
                    
                stripped = line.strip()
                
                # Process line
                if "<" in stripped:  # Quick pre-check
                    line_start_time = time.time()
                    result = process_line(line_count, stripped, previous_line)
                    
                    if result:
                        match_time = time.time() - line_start_time
                        entries.append(result)
                        
                        # Enhanced match logging
                        logger.info(
                            f"[⚡] Found {result['tag']} at line {line_count} "
                            f"(Thread: {result['thread']}) "
                            f"in {match_time*1000:.1f}ms"
                        )
                        last_match_time = time.time()
                
                previous_line = stripped
                
                # Progress tracking (every 1% or 1 second, whichever comes first)
                progress_percent = (line_count / total_lines) * 100
                if (time.time() - last_progress_log > 1.0) or (line_count % max(1, total_lines//100) == 0):
                    elapsed = time.time() - start_time
                    remaining_estimate = (elapsed / line_count) * (total_lines - line_count)
                    
                    logger.info(
                        f"[📈] Progress: {progress_percent:.1f}% | "
                        f"Lines: {line_count:,}/{total_lines:,} | "
                        f"Matches: {len(entries):,} | "
                        f"Elapsed: {format_time(elapsed)} | "
                        f"ETA: {format_time(remaining_estimate)}"
                    )
                    last_progress_log = time.time()
                
                # Cooperative multitasking point
                if line_count % 100 == 0:
                    await asyncio.sleep(0)

    except Exception as e:
        logger.error(f"Error processing {log}: {str(e)}", exc_info=True)
        raise HTTPException(500, detail="Internal server error")

    # Final statistics
    elapsed_time = time.time() - start_time
    lines_per_sec = line_count / elapsed_time if elapsed_time > 0 else 0
    
    logger.info(f"[✅] Completed Parsing RQ/RS from {log}")
    logger.info(f"[📊] Final Stats:")
    logger.info(f"  Lines Processed: {line_count:,} ({lines_per_sec:,.1f} lines/sec)")
    logger.info(f"  RQ/RS Entries Found: {len(entries):,}")
    logger.info(f"  Time Elapsed: {format_time(elapsed_time)}")
    logger.info(f"  Last Match Found at: {format_time(last_match_time - start_time)} into processing")
    
    result = {
        "metadata": {
            "lines_processed": line_count,
            "total_lines": total_lines,
            "entries_found": len(entries),
            "elapsed_seconds": round(elapsed_time, 2),
            "processing_rate": round(lines_per_sec, 1),
            "last_match_at": round(last_match_time - start_time, 2)
        },
        "rqrs": entries
    }
    
    await LOG_CACHE.set(log, result)
    return result
    
@app.get("/get_rqrs")
async def get_rqrs(log: str):
    """Endpoint that uses the optimized parser"""
    return await parse_log_file(log)
    
### Debugging cached parsed XMLs
@app.get("/debug_cache")
async def debug_cache():
    return {
        "cache_contents": LOG_CACHE.cache,
        "cache_order": LOG_CACHE.order
    }

# To get the cached parsed XML's status - http://127.0.0.1:8000/cache_status 
@app.get("/cache_status")
async def cache_status():
    logger.info(f"[✅] Checking cached parsed RQ/RS XMLs...")
    return {
        "cached_logs": list(LOG_CACHE.cache.keys()),
        "cache_size": f"{len(LOG_CACHE.cache)}/{MAX_CACHE_SIZE}",
        "next_to_evict": LOG_CACHE.order[0] if LOG_CACHE.order else None
    }

# To flush the cached parsed XML's - http://127.0.0.1:8000/clear_cache
@app.post("/clear_cache")
async def clear_cache():
    logger.info(f"[✅] Flushing cached parsed RQ/RS XMLs...")
    LOG_CACHE.cache.clear()
    LOG_CACHE.order.clear()
    return {"status": "Cache cleared"}
################################################
# Improved processing the get_rqrs endpoint
# when capturing RQ/RS XMLs - END
################################################

@app.get("/get_log_context")
async def get_log_context(log_file: str, line_number: int):
    log_path = Path("./logs") / log_file

    if not log_path.exists():
        return JSONResponse(status_code=404, content={"error": "Log file not found."})

    try:
        line_number = int(line_number)
        start = max(0, line_number - 11)
        end = line_number + 10

        lines = []
        with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
            for i, line in enumerate(f):
                if i < start:
                    continue
                if i > end:
                    break
                prefix = f"{i+1:>6}: "
                lines.append(prefix + line.rstrip())

        return PlainTextResponse("\n".join(lines))

    except Exception as e:
        print(f"[ERROR] Failed to get log context: {e}")
        return JSONResponse(status_code=500, content={"error": "Failed to fetch context."})
        
@app.get("/log_context")
async def get_log_context(log: str, line: int):
    log_path = Path("logs") / log

    if not log_path.exists() or not log_path.is_file():
        raise HTTPException(status_code=404, detail="Log file not found")

    context_lines = []

    try:
        with log_path.open("r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()

        start_index = max(0, line - 1)  # line numbers are 1-based

        # Find start of block
        while start_index > 0:
            if re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2},", lines[start_index]):
                break
            start_index -= 1

        context_lines.append(lines[start_index].rstrip())

        for i in range(start_index + 1, len(lines)):
            if re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2},", lines[i]):
                break  # stop at next timestamp
            context_lines.append(lines[i].rstrip())

        return {"lines": context_lines}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
  
@app.get("/get_rqrs_content")
def get_rqrs_content(log: str, index: int, tag: str):
    import os
    from xml.dom import minidom
    from fastapi.responses import Response

    log_path = os.path.join(LOG_DIR, log)
    if not os.path.exists(log_path):
        return Response("Log file not found", status_code=404)

    with open(log_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    if index < 0 or index >= len(lines):
        return Response("Invalid index", status_code=400)

    open_tag = f"<{tag}"
    close_tag = f"</{tag}>"
    captured = []
    inside_xml = False
    found_open = False

    for i in range(index, len(lines)):
        line = lines[i].strip()

        # Case 1: Inline XML
        if not inside_xml and open_tag in line:
            start = line.find(open_tag)
            captured.append(line[start:])
            inside_xml = True
            found_open = True

        # Case 2: Line mentions XML and the next line contains the XML (next-line XML)
        elif not inside_xml and ("XML Request" in line or "XML Object is" in line):
            # Look ahead for the actual XML opening tag
            if i + 1 < len(lines):
                next_line = lines[i + 1].strip()
                if open_tag in next_line:
                    captured.append(next_line)
                    inside_xml = True
                    found_open = True
                    i += 1  # skip next line (already used)
                    continue  # go to next iteration

        # Case 3: Continuing XML capture
        elif inside_xml:
            captured.append(line)
            if close_tag in line:
                break

    if not found_open:
        return Response("No recognizable XML starting point.", status_code=400)

    snippet = '\n'.join(captured).strip()

    print("\n===== [🪵 DEBUG] Extracted XML Fragment =====")
    print(snippet)
    print("===== [END XML FRAGMENT] =====\n")

    snippet = '\n'.join(captured).strip()

    # ✅ Trim to only the first closing tag, to prevent duplicate XML roots
    closing_tag = f"</{tag}>"
    closing_index = snippet.find(closing_tag)
    if closing_index != -1:
        snippet = snippet[:closing_index + len(closing_tag)]

    print("\n===== [🪵 DEBUG] Extracted XML Fragment =====")
    print(snippet)
    print("===== [END XML FRAGMENT] =====\n")

    # ✅ Full try-except block restored
    try:
        parsed = minidom.parseString(snippet.encode("utf-8"))
        pretty_xml = parsed.toprettyxml(indent="  ")
        # Remove blank lines that minidom adds
        pretty_xml = '\n'.join(line for line in pretty_xml.splitlines() if line.strip())
        return Response(pretty_xml, media_type="text/plain")

    except Exception as e:
        print(f"[❌ XML Pretty-Print Error] {e}")
        return Response(snippet, media_type="text/plain")

# --- Backend Search API Implementation endpoints START --- 
# --- FastAPI endpoint ---

@app.post("/api/search_logs")
async def search_logs(req: SearchRequest):
    abort_event.clear()
    search_text = req.search_text
    search_mode = req.search_mode
    target_file = req.target_file

    start_time = time.time()
    status['search_active'] = True
    status['matches_found'] = 0  # This actually counts occurrences
    status['files_scanned'] = 0

    results = []
    files_with_matches = set()
    
    try:
        if search_mode == 'all':
            files_to_search = [f for f in os.listdir(LOG_DIR) if f.endswith('.log') and not is_compressed_file(f)]
        elif search_mode == 'targeted' and target_file:
            files_to_search = [target_file]
        else:
            return {"status": "error", "message": "Invalid search mode or missing target file."}

        print(f"[Search Started] {time.ctime(start_time)} | Files: {files_to_search}")

        for fname in files_to_search:
            if abort_event.is_set():
                print("[Search Aborted by user]")
                break

            fpath = os.path.join(LOG_DIR, fname)
            if not os.path.isfile(fpath):
                continue

            status['files_scanned'] += 1
            file_has_matches = False
            section_buffer = []
            last_timestamp_idx = -1

            with open(fpath, 'r', encoding='utf-8', errors='ignore') as f:
                for idx, line in enumerate(f):
                    line = line.rstrip('\n')
                    if TIMESTAMP_PATTERN.match(line):
                        last_timestamp_idx = idx
                        section_buffer = [line]
                    else:
                        section_buffer.append(line)

                    if re.search(re.escape(search_text), line, re.IGNORECASE):
                        if not file_has_matches:
                            files_with_matches.add(fname)
                            file_has_matches = True
                            
                        snippet = line if TIMESTAMP_PATTERN.match(line) else '\n'.join(section_buffer)
                        match_info = {
                            'log_file': fname,
                            'line_number': idx + 1,
                            'thread_id': extract_thread_id(line),
                            'service': extract_service(line),
                            'snippet': snippet
                        }
                        results.append(match_info)
                        status['matches_found'] += 1
                        print(f"[Match Found] {fname}:{idx + 1}")

        elapsed = time.time() - start_time
        print(f"[Search Completed] Files Scanned: {status['files_scanned']} | " +
              f"Files with Matches: {len(files_with_matches)} | " +
              f"Total Occurrences: {len(results)} | " +
              f"Time: {elapsed:.2f}s")

        return {
            "status": "aborted" if abort_event.is_set() else "completed",
            "files_scanned": status['files_scanned'],  # Use actual scanned count
            "file_matches": len(files_with_matches),
            "total_occurrences": len(results),
            "results": results,
            "elapsed_time": elapsed
        }
    finally:
        status['search_active'] = False
        abort_event.clear()

@app.post("/api/search_logs_stream")
async def search_logs_stream(req: SearchRequest):
    """Streaming search endpoint optimized for large log files"""
    abort_event.clear()  # Reset abort flag at start
    
    async def generate():
        # Setup variables
        search_text = req.search_text
        search_mode = req.search_mode
        target_file = req.target_file
        start_time = time.time()
        files_with_matches = set()  # Tracks files containing matches
        total_files_scanned = 0     # Counts processed files
        total_occurrences = 0       # Counts total matching lines
        
        # Log search start
        start_time_str = time.strftime("%H:%M:%S", time.localtime(start_time))
        print(f"\n[Search Started] {start_time_str} | Pattern: '{search_text}' | Mode: {search_mode}")

        # Determine files to search
        try:
            if search_mode == 'all':
                files_to_search = [f for f in os.listdir(LOG_DIR) 
                                 if f.endswith('.log') and not is_compressed_file(f)]
            elif search_mode == 'targeted' and target_file:
                files_to_search = [target_file]
            else:
                error_msg = "Invalid search mode or missing target file"
                print(f"[Search Failed] {error_msg}")
                yield 'data: {"error": "Invalid search mode or missing target file", "code": 400}\n\n'
                return

            # File processing loop
            for fname in files_to_search:
                yield f'data: {{"current_file": "{fname}"}}\n\n'
                if abort_event.is_set():
                    print(f"[Search Aborted] User requested abort")
                    yield 'data: {"status": "aborted", "code": 499}\n\n'
                    break

                fpath = os.path.join(LOG_DIR, fname)
                if not os.path.isfile(fpath):
                    continue

                # Update scan count and send progress update
                total_files_scanned += 1
                
                # Track if current file has matches
                file_has_matches = False  
                section_buffer = []
                last_timestamp_idx = -1

                # Process file line by line
                with open(fpath, 'r', encoding='utf-8', errors='ignore') as f:
                    for line_idx, line in enumerate(f):
                        line = line.rstrip('\n')
                        
                        # Cooperative multitasking - prevents blocking
                        if line_idx % 100 == 0:  # Yield every 100 lines
                            await asyncio.sleep(0)  
                        
                        # Handle log line structure
                        if TIMESTAMP_PATTERN.match(line):
                            last_timestamp_idx = line_idx
                            section_buffer = [line]
                        else:
                            section_buffer.append(line)

                        # Check for matches
                        if re.search(re.escape(search_text), line, re.IGNORECASE):
                            if not file_has_matches:
                                files_with_matches.add(fname)
                                file_has_matches = True
                                print(f"[Match Found] File: {fname}")

                            total_occurrences += 1
                            snippet = line if TIMESTAMP_PATTERN.match(line) else '\n'.join(section_buffer)
                            
                            # Send match immediately
                            data = {
                                "log_file": fname,
                                "line_number": line_idx + 1,
                                "thread_id": extract_thread_id(line),
                                "service": extract_service(line),
                                "snippet": snippet
                            }
                            yield f'data: {json.dumps(data)}\n\n'
                            
            yield f'data: {{"files_scanned": {total_files_scanned}}}\n\n'
            # Final status report
            elapsed = time.time() - start_time
            print(f"\n[Search Completed] {time.strftime('%H:%M:%S', time.localtime())}")
            print(f"  Files scanned: {total_files_scanned}")
            print(f"  Files with matches: {len(files_with_matches)}")
            print(f"  Total occurrences: {total_occurrences}")
            print(f"  Elapsed time: {elapsed:.2f} seconds")

            data = {
                "status": "complete",
                "code": 200,
                "files_scanned": total_files_scanned,
                "file_matches": len(files_with_matches),
                "total_occurrences": total_occurrences,
                "elapsed_time": round(elapsed, 2)
            }
            yield f'data: {json.dumps(data)}\n\n'      

        except Exception as e:
            print(f"[Search Error] {str(e)}")
            yield 'data: {"error": "Search processing failed", "code": 500}\n\n'

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "X-Streaming-Status": "active",
            "Cache-Control": "no-cache"
        }
    )
    
@app.post("/api/abort_search")
async def abort_search():
    abort_event.set()
    # Immediately clear the event so future searches can run
    abort_event.clear()  # 👈 This is the key fix
    return {"status": "abort signal sent and reset"}
    
@app.get("/api/debug_search_status")
async def debug_search_status():
    return status


    
# --- END CLEANED BACKEND SEARCH API ---

# --- START: List Log Files API (non-compressed files) ---
@app.get("/api/list_log_files")
async def list_log_files():
    """
    Return a list of all non-compressed files in ./logs directory.
    Includes files like .log, .log.1, .txt, .md, etc.
    Excludes compressed files (.zip, .tar, .gz, .7z, .Z) and subdirectories.
    """
    try:
        log_files = [
            f for f in os.listdir(LOG_DIR)
            if os.path.isfile(os.path.join(LOG_DIR, f)) and not is_compressed_file(f)
        ]
        return {"log_files": log_files}
    except Exception as e:
        print(f"[Error] Failed to list log files: {e}")
        return {"log_files": []}
# --- END: List Log Files API ---

    
# --- Backend Search API Implementation endpoints END ---    

#### Memory and resources monitoring
#### http://127.0.0.1:8000/monitor
@app.get("/memory-stream")
async def memory_stream():
    """Stream memory usage in real-time (system + Python process)"""
    async def event_generator():
        current_process = psutil.Process(os.getpid())  # Track current Python process
        while True:
            # System-wide memory
            sys_mem = psutil.virtual_memory()
            # Python process memory
            py_mem = current_process.memory_info()
            
            data = {
                "system": {
                    "total": sys_mem.total,
                    "available": sys_mem.available,
                    "used": sys_mem.used,
                    "free": sys_mem.free,
                    "percent": sys_mem.percent
                },
                "python": {
                    "rss": py_mem.rss,  # Resident Set Size (actual RAM used)
                    "vms": py_mem.vms,   # Virtual Memory Size
                    "percent": current_process.memory_percent()
                }
            }
            # Yield the data as SSE formatted string
            yield f"data: {json.dumps(data)}\n\n"
            await asyncio.sleep(1)  # Update every second
    
    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.get("/monitor", response_class=HTMLResponse)
async def monitor_page():
    """Serve a monitoring page with both system and Python memory stats"""
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Memory Monitor (System + Python)</title>
        <style>
            body { font-family: Arial, sans-serif; margin: 20px; }
            .metric { margin-bottom: 10px; }
            .progress-container {
                width: 100%;
                background-color: #f1f1f1;
                border-radius: 5px;
                margin-bottom: 15px;
            }
            .progress-bar {
                height: 20px;
                border-radius: 5px;
                text-align: center;
                line-height: 20px;
                color: white;
            }
            .metric-value {
                font-weight: bold;
                color: #333;
            }
            .section {
                margin-bottom: 30px;
                padding: 15px;
                border: 1px solid #ddd;
                border-radius: 5px;
            }
            h2 { color: #444; border-bottom: 1px solid #eee; padding-bottom: 5px; }
            #system-bar { background-color: #4CAF50; }
            #python-bar { background-color: #2196F3; }
        </style>
    </head>
    <body>
        <h1>Real-Time Memory Monitor</h1>
        
        <div class="section">
            <h2>System Memory</h2>
            <div class="progress-container">
                <div id="system-bar" class="progress-bar" style="width: 0%">0%</div>
            </div>
            <div class="metric">Total Memory: <span id="sys-total" class="metric-value">0</span> MB</div>
            <div class="metric">Available: <span id="sys-available" class="metric-value">0</span> MB</div>
            <div class="metric">Used: <span id="sys-used" class="metric-value">0</span> MB</div>
            <div class="metric">Free: <span id="sys-free" class="metric-value">0</span> MB</div>
        </div>
        
        <div class="section">
            <h2>Python Process Memory</h2>
            <div class="progress-container">
                <div id="python-bar" class="progress-bar" style="width: 0%">0%</div>
            </div>
            <div class="metric">RSS (Resident Memory): <span id="py-rss" class="metric-value">0</span> MB</div>
            <div class="metric">VMS (Virtual Memory): <span id="py-vms" class="metric-value">0</span> MB</div>
            <div class="metric">Memory %: <span id="py-percent" class="metric-value">0</span>%</div>
        </div>
        
        <script>
            const eventSource = new EventSource('/memory-stream');
            
            eventSource.onmessage = function(event) {
                const data = JSON.parse(event.data);
                
                // Update System Memory
                const sysPercent = data.system.percent;
                document.getElementById('system-bar').style.width = `${sysPercent}%`;
                document.getElementById('system-bar').textContent = `${sysPercent.toFixed(1)}%`;
                
                document.getElementById('sys-total').textContent = (data.system.total / 1024 / 1024).toFixed(1);
                document.getElementById('sys-available').textContent = (data.system.available / 1024 / 1024).toFixed(1);
                document.getElementById('sys-used').textContent = (data.system.used / 1024 / 1024).toFixed(1);
                document.getElementById('sys-free').textContent = (data.system.free / 1024 / 1024).toFixed(1);
                
                // Update Python Memory
                const pyPercent = data.python.percent;
                document.getElementById('python-bar').style.width = `${pyPercent}%`;
                document.getElementById('python-bar').textContent = `${pyPercent.toFixed(1)}%`;
                
                document.getElementById('py-rss').textContent = (data.python.rss / 1024 / 1024).toFixed(1);
                document.getElementById('py-vms').textContent = (data.python.vms / 1024 / 1024).toFixed(1);
                document.getElementById('py-percent').textContent = pyPercent.toFixed(1);
            };
            
            // Handle errors
            eventSource.onerror = function() {
                console.error("EventSource failed.");
                setTimeout(() => location.reload(), 2000);
            };
        </script>
    </body>
    </html>
    """
