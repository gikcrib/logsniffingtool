
# Import modules
from fastapi import FastAPI, Request, Query, HTTPException, Response, BackgroundTasks
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse, PlainTextResponse, Response, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from subprocess import Popen, PIPE
from pathlib import Path
from threading import Thread
from xml.dom import minidom
from logging.handlers import RotatingFileHandler
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from enum import Enum, IntEnum
from typing import Dict, Any, Optional
import uvicorn, shutil, asyncio, os, re, difflib, json, time, subprocess, math, logging, sys, aiofiles, threading, psutil, signal, traceback, zipfile, tarfile, gzip


# Initialize logging - Optimizing FastAPI Log Processing Application
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Add handler only if no handlers exist
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s'
    ))
    logger.addHandler(handler)
    logger.propagate = False  # Prevent duplicate logs from root logger

# Initialize FastAPI
app = FastAPI()

if __name__ == "__main__":
    uvicorn.run("main:app", port=8001, reload=True)  # Only runs with `python main.py`

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

# Configuration
LOG_DIR = "./logs"
MAX_CACHE_SIZE = 10
PRELOAD_ENABLED = True  # Set to False to disable startup preloading
PRELOAD_LARGE_FILES = True  # Set to False to disable large file preloading

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


# Regex patterns
TIMESTAMP_PATTERN = re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2},\d{3}')
THREAD_ID_PATTERN = re.compile(r'\[(\d{13}_\d{4}|NDC|REST)\]')

# Exclude these compressed file extensions - view raw logs
EXCLUDED_EXTENSIONS = {'.zip', '.tar', '.gz', '.7z', '.Z', '.bz2', '.rar', '.xz'}


# --- Helper functions ---

# View raw logs start 
def is_compressed_file(filename):
    """Check if file has a compressed extension"""
    return any(filename.lower().endswith(ext) for ext in EXCLUDED_EXTENSIONS)

def get_file_metadata(filepath):
    """Get file metadata with performance logging"""
    start_time = datetime.now()
    size = filepath.stat().st_size
    lines = 0
    
    # Count lines efficiently for the report
    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
        lines = sum(1 for _ in f)
    
    duration = (datetime.now() - start_time).total_seconds()
    return {
        'size': size,
        'lines': lines,
        'processing_time': duration
    }
# View raw logs end 

def is_compressed_file(filename):
    """Check if file is compressed by extension."""
    return filename.endswith(('.zip', '.tar', '.tar.gz', '.gz', '.7z', '.Z'))

def extract_thread_id(source_line: str) -> str:
    """Helper function for thread ID extraction with logging"""
    try:
        thread_match = (RX_THREAD.search(source_line) or 
                      RX_ALT_THREAD.search(source_line))
        if thread_match:
            return thread_match.group(1)
        
        bracketed = RX_BRACKETED.findall(source_line)
        fallback = next((x for x in bracketed if RX_THREAD_FALLBACK.match(x)), "UNKNOWN")
        
        if fallback == "UNKNOWN":
            logger.debug(f"⚠️ Couldn't extract thread ID from: {source_line[:200]}")
        
        return fallback
    except Exception as e:
        logger.warning(f"Thread ID extraction failed: {str(e)}")
        return "UNKNOWN"

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


async def process_and_cache_file(filename: str):
    try:
        await file_processor.set_status(filename, FileStatus.PROCESSING)
        result = await parse_log_file(filename)
        await file_processor.cache_result(filename, result)
    except Exception as e:
        await file_processor.set_status(filename, FileStatus.ERROR)
        logger.error(f"Error processing {filename}: {str(e)}")

async def preload_files_async():
    """Background task for file preloading"""
    if PRELOAD_LARGE_FILES:
        large_files = [f for f in os.listdir(LOG_DIR) 
                     if os.path.getsize(os.path.join(LOG_DIR, f)) > 100 * 1024 * 1024]
        
        # Process up to 2 large files concurrently
        semaphore = asyncio.Semaphore(2)
        tasks = [process_with_semaphore(semaphore, f) for f in large_files]
        await asyncio.gather(*tasks)
    
    await async_preload_logs()

async def process_with_semaphore(semaphore, filename):
    async with semaphore:
        await process_and_cache_file(filename)

async def preload_large_files():
    """Cache large files at startup"""
    large_files = [
        f for f in os.listdir(LOG_DIR)
        if os.path.isfile(os.path.join(LOG_DIR, f)) and 
           os.path.getsize(os.path.join(LOG_DIR, f)) > 100 * 1024 * 1024  # >100MB
    ]
    
    if not large_files:
        return
    
    logger.info(f"Found {len(large_files)} large files to preload")
    
    # Process files with limited concurrency
    semaphore = asyncio.Semaphore(2)  # Process 2 large files at a time
    
    async def process_file(file):
        async with semaphore:
            try:
                logger.info(f"Preloading large file: {file}")
                start_time = time.time()
                await parse_log_file(file)
                logger.info(f"Preloaded {file} in {time.time()-start_time:.2f}s")
            except Exception as e:
                logger.error(f"Failed to preload {file}: {str(e)}")
    
    await asyncio.gather(*[process_file(file) for file in large_files])

@app.on_event("startup")
async def startup_event():
    logger.info("FastAPI server starting...")
    logger.info(f"Log directory: {os.path.abspath(LOG_DIR)}")

    # Initialize critical endpoints first
    await initialize_critical_services()

    if PRELOAD_ENABLED:
        # Start background preload as low-priority task
        asyncio.create_task(delayed_background_preload())
        logger.info("Background preload will start after server becomes responsive")
    else:
        logger.info("Skipping preload (PRELOAD_ENABLED=False)")

async def initialize_critical_services():
    """Initialize essential services before accepting requests"""
    logger.info("Initializing critical services...")
    # Add any essential initialization here
    pass

async def delayed_background_preload():
    """Start background preload after a short delay"""
    await asyncio.sleep(10)  # Wait for server to become fully responsive
    logger.info("Starting background preload now")
    await background_preload()

@app.get("/", response_class=HTMLResponse)
async def serve_ui(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

################################
# psutil memory monitoring - Start
################################

@app.middleware("http")
async def combined_middleware(request: Request, call_next):
    # 1. First define critical endpoints (at the top of the middleware)
    CRITICAL_ENDPOINTS = os.getenv('CRITICAL_ENDPOINTS', '').split(',') + [
        '/list_logs',
        '/healthcheck',
        '/get_rqrs'
    ]

    # 2. Endpoint Prioritization Logic (NEW)
    if request.url.path in CRITICAL_ENDPOINTS:
        # Add small delay for background tasks to prioritize user requests
        if request.headers.get('x-request-priority') == 'background':
            await asyncio.sleep(0.1)  # 100ms delay for background tasks
        return await call_next(request)
        
    # --- Original Memory Protection Logic ---
    process = psutil.Process()
    system_mem = psutil.virtual_memory()
    
    if system_mem.percent > 90 or system_mem.available < 100 * 1024 * 1024:
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
    
    # --- Before request metrics ---
    mem_before = process.memory_info().rss / 1024 / 1024
    start_time = time.time()
    
    try:
        response = await call_next(request)
        
    except Exception as e:
        elapsed = time.time() - start_time
        print(f"❌ Error in {request.url.path}: {str(e)} [{elapsed:.2f}s]")
        raise
    
    # --- After request metrics ---
    mem_after = process.memory_info().rss / 1024 / 1024
    elapsed = time.time() - start_time
    memory_used = mem_after - mem_before
    
    if system_mem.percent > 50:
        print(f"🚨 WARNING: System memory at {system_mem.percent}%")
        print(f"    Available: {system_mem.available/1024/1024:.1f}MB")
        print(f"    Used by Python: {mem_after:.1f}MB")
        print(f"    Request consumed: {memory_used:.1f}MB")
    
    endpoint_metrics[request.url.path] = {
        "memory_used_mb": round(memory_used, 2),
        "system_memory_percent": system_mem.percent,
        "time_sec": round(elapsed, 2),
        "timestamp": datetime.now().isoformat()
    }
    
    status_code = getattr(response, "status_code", 500)
    print(f"{request.method} {request.url.path} ({status_code}) {elapsed:.2f}s | +{memory_used:.1f}MB")
    
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
                    # smart_preload_rqrs()
                    list_log_files()
                    list_logs()
                    async_preload_logs()
                else:
                    # Allow empty stderr if returncode is still 0
                    if stderr.strip() == "":
                        print("⚠️ SCP ended with no error output but returned a non-zero exit code.")
                        # smart_preload_rqrs()
                        list_log_files()
                        list_logs()
                        async_preload_logs()
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


class FileStatus(Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETE = "complete"
    ERROR = "error"

class Priority(IntEnum):
    USER_REQUEST = 1  # Highest priority
    BACKGROUND_PRELOAD = 2  # Lower priority

class FileProcessor:
    def __init__(self):
        self.active_tasks: Dict[str, asyncio.Task] = {}
        self.pending_requests: Dict[str, asyncio.Event] = {}
        self.results: Dict[str, dict] = {}
        self.lock = asyncio.Lock()
    
    async def process_file(self, filename: str, priority: Priority) -> dict:
        async with self.lock:
            # Return cached result if available
            if filename in self.results:
                return self.results[filename]
            
            # If already being processed, wait for completion
            if filename in self.active_tasks:
                if priority == Priority.USER_REQUEST and filename in self.pending_requests:
                    # Cancel background preload for user requests
                    self.active_tasks[filename].cancel()
                    del self.active_tasks[filename]
                else:
                    await self.pending_requests[filename].wait()
                    return self.results.get(filename)
            
            # Create new processing task
            done_event = asyncio.Event()
            self.pending_requests[filename] = done_event
            
            task = asyncio.create_task(
                self._process_file(filename, done_event, priority),
                name=f"process_{filename}"
            )
            self.active_tasks[filename] = task
            
        await done_event.wait()
        return self.results.get(filename)
    
    async def _process_file(self, filename: str, done_event: asyncio.Event, priority: Priority):
        try:
            result = await parse_log_file(filename)
            async with self.lock:
                self.results[filename] = result
        except asyncio.CancelledError:
            logger.info(f"Processing of {filename} was cancelled (priority: {priority.name})")
        except Exception as e:
            logger.error(f"Error processing {filename}: {str(e)}")
        finally:
            async with self.lock:
                done_event.set()
                if filename in self.active_tasks:
                    del self.active_tasks[filename]
                if filename in self.pending_requests:
                    del self.pending_requests[filename]

file_processor = FileProcessor()
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
                self.order.remove(key)
                self.order.append(key)
                return self.cache[key]
            return None

    async def set(self, key: str, value: Any) -> None:
        async with self.lock:
            if key in self.cache:
                self.cache[key] = value
                self.order.remove(key)
                self.order.append(key)
            elif len(self.cache) >= self.maxsize:
                oldest = self.order.pop(0)
                logger.info(f"[🗑️] Evicting oldest cache entry: {oldest}")
                del self.cache[oldest]
                self.cache[key] = value
                self.order.append(key)
            else:
                self.cache[key] = value
                self.order.append(key)

    async def invalidate(self, key: str):
        async with self.lock:
            if key in self.cache:
                del self.cache[key]
                self.order.remove(key)

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
    """Process individual log line"""
    if not (match := RX_RQRS.search(current)):
        return None
        
    is_inline_xml = bool(RX_DATE.match(current))
    source_line = current if is_inline_xml else previous
    
    # Thread ID extraction
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
        "raw": current[:512],
        "has_issue": bool(RX_ERRORS.search(current))
    }

def extract_xml_info(stripped_line, previous_line, line_number):
    """Optimized XML extraction logic"""
    if match := RX_RQRS.search(stripped_line):
        is_inline_xml = bool(RX_DATE.match(stripped_line))
        source_line = stripped_line if is_inline_xml else previous_line
        
        # Fast thread ID extraction - FIXED SYNTAX
        thread_match = (RX_THREAD.search(source_line) or RX_ALT_THREAD.search(source_line))
        thread_id = thread_match.group(1) if thread_match else None
        if not thread_id:
            bracketed = RX_BRACKETED.findall(source_line)
            thread_id = next((x for x in bracketed if RX_THREAD_FALLBACK.match(x)), "UNKNOWN")
        
        return {
            "line": line_number,
            "thread": thread_id,
            "tag": match.group(1),
            "raw": stripped_line[:512],
            "has_issue": bool(RX_ERRORS.search(stripped_line))
        }
    return None

async def async_preload_logs():
    """Optimized log preloading that processes all files regardless of size"""
    # Initialize tracking variables
    process = psutil.Process(os.getpid())
    start_mem = process.memory_info().rss / (1024 * 1024)
    start_time = time.time()
    
    logger.info(f"[⚡] Starting optimized async preload (initial memory: {start_mem:.2f} MB)")
    
    stats = {
        'processed': 0,
        'skipped': 0,
        'failed': 0,
        'total_entries': 0,
        'total_lines': 0
    }

    # Create a semaphore for limited concurrent processing
    # Reduced to 2 concurrent files to better handle large files
    semaphore = asyncio.Semaphore(2)  # Process up to 2 files concurrently

    async def process_single_file(file):
        """Helper function to process a single file"""
        nonlocal stats
        filepath = os.path.join(LOG_DIR, file)
        
        try:
            async with semaphore:
                # Skip non-files immediately
                if not os.path.isfile(filepath):
                    stats['skipped'] += 1
                    return

                # Check cache first
                if await LOG_CACHE.get(file) is not None:
                    stats['skipped'] += 1
                    return

                file_size = os.path.getsize(filepath) / (1024 * 1024)  # in MB
                logger.info(f"Processing {file} ({file_size:.2f} MB)")

                # Get the current process
                process = psutil.Process(os.getpid())
                
                # Rate limiting - pause every few files
                if stats['processed'] > 0 and stats['processed'] % 3 == 0:
                    await asyncio.sleep(0.2)  # 200ms pause

                # Process the file
                file_start = time.time()
                entries = []
                line_count = 0
                
                # Special handling for very large files
                if file_size > 100:
                    logger.info(f"Processing large file {file} - this may take a while...")
                    # More frequent progress updates for large files
                    progress_interval = 100000
                else:
                    progress_interval = 10000

                file_size = os.path.getsize(filepath) / (1024 * 1024)  # in MB
                if file_size > 100:  # Only use chunked reading for large files
                    logger.info(f"Processing large file {file} with chunked reading...")
                    return await process_large_file_chunked(filepath, file)
                else:
                    # Process small files normally
                    return await process_file_normal(filepath, file)
                
                async with aiofiles.open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                    previous_line = ""
                    line_count = 0

                    async for line in f:
                        line_count += 1
                        stripped = line.strip()

                        # Memory check for large files (every 50,000 lines)
                        if file_size > 100 and line_count % 50000 == 0:
                            current_mem = process.memory_info().rss / (1024 * 1024)
                            logger.info(
                                f"{file}: Line {line_count:,} - "
                                f"Memory: {current_mem:.2f} MB - "
                                f"Entries found: {len(entries)}"
                            )
                        
                        # Progress reporting for large files
                        if file_size > 100 and line_count % progress_interval == 0:
                            logger.info(f"{file}: Processed {line_count:,} lines...")
                        
                        # Only process non-empty lines that might contain XML
                        if stripped and "<" in stripped:
                            if match := RX_RQRS.search(stripped):
                                # Simplified thread ID extraction
                                is_inline_xml = bool(RX_DATE.match(stripped))
                                source_line = stripped if is_inline_xml else previous_line
                                thread_id = extract_thread_id(source_line)
                                
                                entries.append({
                                    'line': line_count,
                                    'tag': match.group(1),
                                    'thread': thread_id,
                                    'raw': stripped[:512],
                                    'has_issue': bool(RX_ERRORS.search(stripped))
                                })
                        
                        previous_line = stripped
                
                # Update statistics
                stats['processed'] += 1
                stats['total_entries'] += len(entries)
                stats['total_lines'] += line_count
                
                # Cache the results
                await LOG_CACHE.set(file, {
                    "metadata": {
                        "preloaded": True,
                        "lines_processed": line_count,
                        "entries_found": len(entries),
                        "processing_time": round(time.time() - file_start, 2),
                        "file_size_mb": round(file_size, 2)
                    },
                    "rqrs": entries
                })
                
                processing_time = time.time() - file_start
                logger.info(f"Finished {file} ({line_count} lines, {len(entries)} entries) in {processing_time:.2f}s")
                
        except Exception as e:
            logger.error(f"Failed to process {file}: {str(e)}")
            stats['failed'] += 1

    # Process all files using asyncio.gather for better concurrency
    files = os.listdir(LOG_DIR)
    await asyncio.gather(*[process_single_file(file) for file in files])

    # Final statistics
    end_mem = process.memory_info().rss / (1024 * 1024)
    elapsed = time.time() - start_time
    
    logger.info("\n📊 Final Preload Summary:")
    logger.info(f"  Files processed: {stats['processed']}")
    logger.info(f"  Files skipped (cached): {stats['skipped']}")
    logger.info(f"  Files failed: {stats['failed']}")
    logger.info(f"  Total lines scanned: {stats['total_lines']:,}")
    logger.info(f"  Total RQ/RS entries found: {stats['total_entries']:,}")
    logger.info(f"  Memory usage: {start_mem:.2f} MB → {end_mem:.2f} MB")
    logger.info(f"  Total time: {elapsed:.2f} seconds")
    logger.info(f"  Processing rate: {stats['total_lines']/elapsed if elapsed > 0 else 0:,.1f} lines/sec")
    logger.info(f"  Cache size: {len(LOG_CACHE.cache)}/{MAX_CACHE_SIZE} files")

async def process_file_normal(filepath, filename):
    """Process normal-sized files (original method)"""
    # [Your original file processing code here]
    
async def process_large_file_chunked(filepath, filename):
    """Process large files in chunks"""
    entries = []
    line_count = 0
    previous_line = ""
    chunk_size = 1024 * 1024  # 1MB chunks
    file_start = time.time()
    
    async with aiofiles.open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
        while True:
            chunk = await f.read(chunk_size)
            if not chunk:
                break
                
            # Process each line in the chunk
            for line in chunk.splitlines():
                line_count += 1
                stripped = line.strip()
                
                # Memory monitoring (every 50,000 lines)
                if line_count % 50000 == 0:
                    current_mem = psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024)
                    logger.info(
                        f"{filename}: Line {line_count:,} - "
                        f"Memory: {current_mem:.2f} MB"
                    )
                
                if stripped and "<" in stripped:
                    if match := RX_RQRS.search(stripped):
                        # [Your existing XML processing logic]
                        entries.append({
                            # [Your existing entry structure]
                        })
                
                previous_line = stripped
    
    processing_time = time.time() - file_start
    logger.info(
        f"Finished chunked processing of {filename} - "
        f"{line_count} lines, {len(entries)} entries in {processing_time:.2f}s"
    )
    
    return {
        "entries": entries,
        "line_count": line_count,
        "processing_time": processing_time
    }

@app.get("/get_rqrs")
async def get_rqrs(log: str):
    """Endpoint that prioritizes user requests"""
    try:
        result = await file_processor.process_file(log, Priority.USER_REQUEST)
        if result is None:
            raise HTTPException(500, detail="Processing failed")
        return result
    except asyncio.CancelledError:
        raise HTTPException(503, detail="Service unavailable, please retry")
    except Exception as e:
        raise HTTPException(500, detail=str(e))

async def background_preload():
    """Optimized background preload that minimizes impact"""
    large_files = await get_large_files()
    
    # Process files with cooperative scheduling
    for i, filename in enumerate(large_files):
        try:
            # Process file with lower priority
            await file_processor.process_file(filename, Priority.BACKGROUND_PRELOAD)
            
            # Yield to event loop every 2 files
            if i % 2 == 0:
                await asyncio.sleep(0.1)  # Allow other tasks to run
                
        except Exception as e:
            logger.error(f"Background preload failed for {filename}: {str(e)}")

async def get_large_files():
    """Get list of large files with cooperative yielding"""
    files = []
    for filename in os.listdir(LOG_DIR):
        filepath = os.path.join(LOG_DIR, filename)
        if os.path.isfile(filepath) and os.path.getsize(filepath) > 100 * 1024 * 1024:
            files.append(filename)
        
        # Yield periodically during directory scanning
        if len(files) % 10 == 0:
            await asyncio.sleep(0)
    
    return files

@app.get("/healthcheck")
async def health_check():
    """Lightweight endpoint to verify server responsiveness"""
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}

async def process_large_file_in_background(log: str, timeout: int):
    """Background task for large file processing"""
    try:
        result = await asyncio.wait_for(
            parse_log_file(log),
            timeout=timeout
        )
        progress_tracker.complete(log)
        return result
    except asyncio.TimeoutError:
        progress_tracker.update(log, {"status": "timeout"})
        logger.error(f"Background processing timed out for {log}")
    except Exception as e:
        progress_tracker.update(log, {"status": "error", "error": str(e)})
        logger.error(f"Background processing failed for {log}: {str(e)}")

@app.get("/file_status/{filename}")
async def get_file_status(filename: str):
    status = await file_processor.get_status(filename)
    return {
        "filename": filename,
        "status": status.value,
        "is_ready": status == FileStatus.COMPLETE
    }

@app.get("/get_progress")
async def get_progress(self, filename: str) -> dict:
    """Check progress of background processing"""
    progress = progress_tracker.get_progress(log)
    if not progress:
        raise HTTPException(404, detail="No such task or task completed")
    return {
        "status": "processing" if filename in self.active_tasks else "ready",
        "filename": filename,
        "in_cache": filename in self.results
    }

@app.get("/parse_progress")
async def get_parse_progress(log: str):
    """Check progress of parsing"""
    if log in progress_tracker.active_tasks:
        return progress_tracker.active_tasks[log]
    return {"status": "not_found"}
    
async def parse_log_file(log: str):
    """Dramatically faster version using buffered reading"""
    if (cached := await LOG_CACHE.get(log)) is not None:
        logger.info(f"Cache HIT for {log}")
        return cached

    filepath = os.path.join(LOG_DIR, log)
    if not os.path.exists(filepath):
        raise HTTPException(404, detail="File not found")

    start_time = time.time()
    entries = []
    line_count = 0
    previous_line = ""
    last_report_time = start_time
    chunk_size = 1024 * 1024  # 1MB chunks

    try:
        async with aiofiles.open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            while True:
                chunk = await f.read(chunk_size)
                if not chunk:
                    break
                
                for line in chunk.splitlines():
                    line_count += 1
                    stripped = line.strip()
                    
                    # Skip empty lines and header
                    if not stripped or line_count == 1:
                        continue
                        
                    if "<" in stripped:
                        if entry := extract_xml_info(stripped, previous_line, line_count):
                            entries.append(entry)
                    
                    previous_line = stripped
                    
                    # Progress reporting (throttled)
                    current_time = time.time()
                    if current_time - last_report_time > 5:  # Every 5 seconds
                        logger.info(f"Processed {line_count:,} lines...")
                        last_report_time = current_time
                        await asyncio.sleep(0)  # Yield to event loop

        logger.info(f"Finished {line_count:,} lines with {len(entries):,} entries in {time.time()-start_time:.2f}s")
        
        result = {
            "metadata": {
                "lines_processed": line_count,
                "entries_found": len(entries),
                "processing_time": round(time.time() - start_time, 2)
            },
            "rqrs": entries
        }
        
        await LOG_CACHE.set(log, result)
        return result

    except Exception as e:
        logger.error(f"Error processing {log}: {str(e)}")
        raise HTTPException(500, detail="Internal server error")

class ProgressTracker:
    def __init__(self):
        self.active_tasks = {}
        
    def start(self, log_file):
        self.active_tasks[log_file] = {
            'start_time': time.time(),
            'lines_processed': 0,
            'status': 'processing'
        }
        
    def update(self, log_file, lines_processed):
        if log_file in self.active_tasks:
            self.active_tasks[log_file]['lines_processed'] = lines_processed
            self.active_tasks[log_file]['elapsed'] = time.time() - self.active_tasks[log_file]['start_time']
            
    def complete(self, log_file):
        if log_file in self.active_tasks:
            self.active_tasks[log_file]['status'] = 'complete'

progress_tracker = ProgressTracker()

### Debugging cached parsed XMLs
@app.get("/debug_rqrs_cache")
async def debug_rqrs_cache():
    return {
        "file_count": len(RQRS_CACHE),
        "sample_entry": list(RQRS_CACHE.items())[0] if RQRS_CACHE else None,
        "meta_count": len(LOG_CACHE_META)
    }

@app.get("/debug_cache")
async def debug_cache():
    return {
        "cache_contents": LOG_CACHE.cache,
        "cache_order": LOG_CACHE.order
    }

# To get the cached parsed XML's status - http://127.0.0.1:8001/cache_status 
@app.get("/cache_status")
async def cache_status():
    """Check cache status"""
    return {
        "cached_logs": list(LOG_CACHE.cache.keys()),
        "cache_size": f"{len(LOG_CACHE.cache)}/{MAX_CACHE_SIZE}",
        "next_to_evict": LOG_CACHE.order[0] if LOG_CACHE.order else None
    }

# To flush the cached parsed XML's - http://127.0.0.1:8001/clear_cache
@app.post("/clear_cache")
async def clear_cache():
    """Clear the cache"""
    LOG_CACHE.cache.clear()
    LOG_CACHE.order.clear()
    return {"status": "Cache cleared"}

# To refresh the cached parsed XML's - http://127.0.0.1:8001/refresh_cache
@app.post("/refresh_cache")
async def refresh_cache():
    """Manually trigger a full cache refresh"""
    files = [f for f in os.listdir(LOG_DIR) if os.path.isfile(os.path.join(LOG_DIR, f))]
    await process_files(files)
    return {"status": "Cache refreshed", "files_processed": len(files)}

if __name__ == "__main__":
    uvicorn.run("main:app", port=8001, reload=True)
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

##### View raw logs endpoints Start ######  
### Files Dropdown Listing  
@app.get("/api/logs/list")
async def list_log_files():
    """List all log files in the logs directory, excluding compressed files"""
    try:
        logger.info("Starting to scan log directory: %s", LOG_DIR)
        start_time = datetime.now()
        log_files = []
        scanned_files = 0
        
        for file in Path(LOG_DIR).iterdir():
            if file.is_file():
                scanned_files += 1
                if not is_compressed_file(file.name):
                    metadata = get_file_metadata(file)
                    log_files.append({
                        "name": file.name,
                        "path": str(file),
                        "size": metadata['size'],
                        "lines": metadata['lines']
                    })
                    logger.debug("Found log file: %s (Size: %s, Lines: %s)", 
                               file.name, metadata['size'], metadata['lines'])
        
        duration = (datetime.now() - start_time).total_seconds()
        logger.info(
            "Completed directory scan. Files: %d (scanned %d). Time taken: %.2fs",
            len(log_files), scanned_files, duration
        )
        
        return JSONResponse(content={
            "files": log_files,
            "scan_metrics": {
                "total_files_scanned": scanned_files,
                "log_files_found": len(log_files),
                "time_taken_seconds": duration
            }
        })
    except Exception as e:
        logger.error("Failed to list log files: %s", str(e), exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

### View Logs Streaming 
@app.get("/api/logs/stream")
async def stream_log_file(filename: str):
    """Stream complete log file content in one pass"""
    file_path = Path(LOG_DIR) / filename
    
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    
    if is_compressed_file(filename):
        raise HTTPException(status_code=400, detail="Compressed files are not supported")

    async def generate():
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            # Send all lines at once in a single JSON array
            lines = []
            for line in f:
                lines.append(line.rstrip('\r\n'))
            
            yield json.dumps({
                "status": "complete",
                "lines": lines,
                "total_lines": len(lines)
            })

    return StreamingResponse(generate(), media_type="application/json")


def format_file_size(bytes):
    """Format file size in human-readable format (e.g., KB, MB)"""
    if bytes < 1024:
        return f"{bytes} B"
    if bytes < 1024 * 1024:
        return f"{bytes / 1024:.1f} KB"
    if bytes < 1024 * 1024 * 1024:
        return f"{bytes / (1024 * 1024):.1f} MB"
    return f"{bytes / (1024 * 1024 * 1024):.1f} GB"

#### http://127.0.0.1:8001/monitor
def get_process_info(pid):
    """Get detailed information about a specific process"""
    try:
        proc = psutil.Process(pid)
        with proc.oneshot():  # Optimize for multiple info retrieval
            return {
                "pid": pid,
                "name": proc.name(),
                "exe": proc.exe(),
                "cmdline": proc.cmdline(),
                "memory": {
                    "rss": proc.memory_info().rss,
                    "vms": proc.memory_info().vms,
                    "shared": proc.memory_info().shared,
                    "uss": proc.memory_full_info().uss if hasattr(proc, 'memory_full_info') else 0,
                    "pss": proc.memory_full_info().pss if hasattr(proc, 'memory_full_info') else 0,
                },
                "memory_percent": proc.memory_percent(),
                "cpu_percent": proc.cpu_percent(),
                "cpu_times": proc.cpu_times(),
                "status": proc.status(),
                "create_time": proc.create_time(),
                "threads": proc.num_threads(),
                "connections": len(proc.connections()),
                "open_files": len(proc.open_files()),
                "is_browser": any(browser in proc.name().lower() 
                                 for browser in ['chrome', 'firefox', 'edge', 'msedge', 'iexplore'])
            }
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return None

def find_all_processes():
    """Find all relevant processes including browsers and system processes"""
    processes = []
    browser_names = ['chrome', 'firefox', 'edge', 'msedge', 'iexplore']
    
    # Get top memory-consuming processes
    all_procs = []
    for proc in psutil.process_iter(['pid', 'name', 'memory_percent']):
        try:
            all_procs.append(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    
    # Sort by memory usage and get top processes
    top_procs = sorted(all_procs, key=lambda p: p.info['memory_percent'], reverse=True)[:25]
    
    # Get detailed info for top processes
    for proc in top_procs:
        try:
            proc_info = get_process_info(proc.info['pid'])
            if proc_info:
                processes.append(proc_info)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    
    return processes

@app.get("/memory-stream")
async def memory_stream():
    """Stream comprehensive system and process metrics"""
    async def event_generator():
        while True:
            # System-wide metrics
            sys_mem = psutil.virtual_memory()
            sys_swap = psutil.swap_memory()
            sys_cpu = psutil.cpu_percent(interval=1, percpu=True)
            sys_cpu_avg = sum(sys_cpu) / len(sys_cpu) if sys_cpu else 0
            sys_disk = psutil.disk_usage('/')
            sys_net = psutil.net_io_counters()
            sys_temp = psutil.sensors_temperatures() if hasattr(psutil, 'sensors_temperatures') else {}
            sys_battery = psutil.sensors_battery() if hasattr(psutil, 'sensors_battery') else None
            
            # Get all relevant processes
            processes = find_all_processes()
            
            # Current Python process metrics
            current_process = get_process_info(os.getpid())
            
            data = {
                "timestamp": psutil.time.time(),
                "system": {
                    "memory": {
                        "total": sys_mem.total,
                        "available": sys_mem.available,
                        "used": sys_mem.used,
                        "free": sys_mem.free,
                        "percent": sys_mem.percent,
                        "active": getattr(sys_mem, 'active', 0),
                        "inactive": getattr(sys_mem, 'inactive', 0),
                        "buffers": getattr(sys_mem, 'buffers', 0),
                        "cached": getattr(sys_mem, 'cached', 0),
                        "shared": getattr(sys_mem, 'shared', 0),
                    },
                    "swap": {
                        "total": sys_swap.total,
                        "used": sys_swap.used,
                        "free": sys_swap.free,
                        "percent": sys_swap.percent,
                        "sin": sys_swap.sin,
                        "sout": sys_swap.sout,
                    },
                    "cpu": {
                        "percent": sys_cpu_avg,
                        "per_cpu": sys_cpu,
                        "count": psutil.cpu_count(),
                        "freq": psutil.cpu_freq().current if hasattr(psutil, 'cpu_freq') else 0,
                    },
                    "disk": {
                        "total": sys_disk.total,
                        "used": sys_disk.used,
                        "free": sys_disk.free,
                        "percent": sys_disk.percent,
                    },
                    "network": {
                        "bytes_sent": sys_net.bytes_sent,
                        "bytes_recv": sys_net.bytes_recv,
                        "packets_sent": sys_net.packets_sent,
                        "packets_recv": sys_net.packets_recv,
                    },
                    "temperature": sys_temp,
                    "battery": sys_battery,
                },
                "python_process": current_process,
                "top_processes": processes,
            }
            
            yield f"data: {json.dumps(data)}\n\n"
            await asyncio.sleep(1)  # Update every second
    
    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.get("/monitor", response_class=HTMLResponse)
async def monitor_page():
    """Serve a comprehensive monitoring dashboard"""
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Advanced System Monitor</title>
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
            h3 { color: #666; margin-top: 15px; }
            #system-memory-bar { background-color: #4CAF50; }
            #system-cpu-bar { background-color: #FF9800; }
            #system-swap-bar { background-color: #607D8B; }
            #python-memory-bar { background-color: #2196F3; }
            #python-cpu-bar { background-color: #9C27B0; }
            table {
                width: 100%;
                border-collapse: collapse;
                margin-top: 15px;
                font-size: 14px;
            }
            th, td {
                border: 1px solid #ddd;
                padding: 8px;
                text-align: left;
            }
            th {
                background-color: #f2f2f2;
                position: sticky;
                top: 0;
            }
            tr:nth-child(even) {
                background-color: #f9f9f9;
            }
            tr:hover {
                background-color: #f1f1f1;
            }
            .browser-process {
                background-color: #FFF3E0;
            }
            .critical-process {
                background-color: #FFEBEE;
            }
            .grid-container {
                display: grid;
                grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
                gap: 15px;
                margin-bottom: 20px;
            }
            .grid-item {
                border: 1px solid #ddd;
                border-radius: 5px;
                padding: 10px;
            }
            .memory-cell {
                width: 120px;
            }
            .cpu-cell {
                width: 80px;
            }
            .chart-container {
                width: 100%;
                height: 200px;
                margin: 20px 0;
            }
            .tab {
                overflow: hidden;
                border: 1px solid #ccc;
                background-color: #f1f1f1;
                border-radius: 5px 5px 0 0;
            }
            .tab button {
                background-color: inherit;
                float: left;
                border: none;
                outline: none;
                cursor: pointer;
                padding: 10px 16px;
                transition: 0.3s;
            }
            .tab button:hover {
                background-color: #ddd;
            }
            .tab button.active {
                background-color: #ccc;
            }
            .tabcontent {
                display: none;
                padding: 15px;
                border: 1px solid #ccc;
                border-top: none;
                border-radius: 0 0 5px 5px;
            }
            .visible {
                display: block;
            }
        </style>
    </head>
    <body>
        <h1>Advanced System Monitor</h1>
        
        <div class="tab">
            <button class="tablinks active" onclick="openTab(event, 'system')">System</button>
            <button class="tablinks" onclick="openTab(event, 'python')">Python Process</button>
            <button class="tablinks" onclick="openTab(event, 'processes')">All Processes</button>
            <button class="tablinks" onclick="openTab(event, 'network')">Network</button>
        </div>
        
        <div id="system" class="tabcontent visible">
            <h2>System Resources</h2>
            
            <div class="grid-container">
                <div class="grid-item">
                    <h3>Memory Usage</h3>
                    <div class="progress-container">
                        <div id="system-memory-bar" class="progress-bar" style="width: 0%">0%</div>
                    </div>
                    <div class="metric">Total: <span id="sys-mem-total" class="metric-value">0</span> GB</div>
                    <div class="metric">Used: <span id="sys-mem-used" class="metric-value">0</span> GB</div>
                    <div class="metric">Available: <span id="sys-mem-available" class="metric-value">0</span> GB</div>
                    <div class="metric">Active: <span id="sys-mem-active" class="metric-value">0</span> GB</div>
                    <div class="metric">Cached: <span id="sys-mem-cached" class="metric-value">0</span> GB</div>
                </div>
                
                <div class="grid-item">
                    <h3>CPU Usage</h3>
                    <div class="progress-container">
                        <div id="system-cpu-bar" class="progress-bar" style="width: 0%">0%</div>
                    </div>
                    <div class="metric">Cores: <span id="sys-cpu-count" class="metric-value">0</span></div>
                    <div class="metric">Frequency: <span id="sys-cpu-freq" class="metric-value">0</span> MHz</div>
                    <div id="per-cpu-usage"></div>
                </div>
                
                <div class="grid-item">
                    <h3>Swap Memory</h3>
                    <div class="progress-container">
                        <div id="system-swap-bar" class="progress-bar" style="width: 0%">0%</div>
                    </div>
                    <div class="metric">Total: <span id="sys-swap-total" class="metric-value">0</span> GB</div>
                    <div class="metric">Used: <span id="sys-swap-used" class="metric-value">0</span> GB</div>
                    <div class="metric">Free: <span id="sys-swap-free" class="metric-value">0</span> GB</div>
                </div>
                
                <div class="grid-item">
                    <h3>Disk Usage</h3>
                    <div class="progress-container">
                        <div id="system-disk-bar" class="progress-bar" style="width: 0%">0%</div>
                    </div>
                    <div class="metric">Total: <span id="sys-disk-total" class="metric-value">0</span> GB</div>
                    <div class="metric">Used: <span id="sys-disk-used" class="metric-value">0</span> GB</div>
                    <div class="metric">Free: <span id="sys-disk-free" class="metric-value">0</span> GB</div>
                </div>
            </div>
            
            <h3>Temperature Sensors</h3>
            <div id="temperature-sensors"></div>
            
            <h3>Battery Status</h3>
            <div id="battery-status"></div>
        </div>
        
        <div id="python" class="tabcontent">
            <h2>Python Process Resources</h2>
            
            <div class="grid-container">
                <div class="grid-item">
                    <h3>Memory Usage</h3>
                    <div class="progress-container">
                        <div id="python-memory-bar" class="progress-bar" style="width: 0%">0%</div>
                    </div>
                    <div class="metric">RSS: <span id="py-rss" class="metric-value">0</span> MB</div>
                    <div class="metric">VMS: <span id="py-vms" class="metric-value">0</span> MB</div>
                    <div class="metric">USS: <span id="py-uss" class="metric-value">0</span> MB</div>
                    <div class="metric">PSS: <span id="py-pss" class="metric-value">0</span> MB</div>
                    <div class="metric">Memory %: <span id="py-memory-percent" class="metric-value">0</span>%</div>
                </div>
                
                <div class="grid-item">
                    <h3>CPU Usage</h3>
                    <div class="progress-container">
                        <div id="python-cpu-bar" class="progress-bar" style="width: 0%">0%</div>
                    </div>
                    <div class="metric">CPU %: <span id="py-cpu-percent" class="metric-value">0</span>%</div>
                    <div class="metric">Threads: <span id="py-threads" class="metric-value">0</span></div>
                    <div class="metric">User Time: <span id="py-cpu-user" class="metric-value">0</span>s</div>
                    <div class="metric">System Time: <span id="py-cpu-system" class="metric-value">0</span>s</div>
                </div>
                
                <div class="grid-item">
                    <h3>Process Info</h3>
                    <div class="metric">PID: <span id="py-pid" class="metric-value">0</span></div>
                    <div class="metric">Name: <span id="py-name" class="metric-value">-</span></div>
                    <div class="metric">Status: <span id="py-status" class="metric-value">-</span></div>
                    <div class="metric">Created: <span id="py-created" class="metric-value">-</span></div>
                    <div class="metric">Open Files: <span id="py-open-files" class="metric-value">0</span></div>
                    <div class="metric">Connections: <span id="py-connections" class="metric-value">0</span></div>
                </div>
            </div>
        </div>
        
        <div id="processes" class="tabcontent">
            <h2>All Processes (Top 25 by Memory)</h2>
            <div class="metric">Showing <span id="process-count" class="metric-value">0</span> processes</div>
            <table>
                <thead>
                    <tr>
                        <th>PID</th>
                        <th>Name</th>
                        <th class="memory-cell">Memory (MB)</th>
                        <th>Memory %</th>
                        <th class="cpu-cell">CPU %</th>
                        <th>Threads</th>
                        <th>Status</th>
                        <th>Type</th>
                    </tr>
                </thead>
                <tbody id="process-table-body">
                    <!-- Process data will be inserted here -->
                </tbody>
            </table>
        </div>
        
        <div id="network" class="tabcontent">
            <h2>Network Activity</h2>
            <div class="grid-container">
                <div class="grid-item">
                    <h3>Network Usage</h3>
                    <div class="metric">Sent: <span id="net-sent" class="metric-value">0</span> MB</div>
                    <div class="metric">Received: <span id="net-recv" class="metric-value">0</span> MB</div>
                    <div class="metric">Packets Sent: <span id="net-packets-sent" class="metric-value">0</span></div>
                    <div class="metric">Packets Received: <span id="net-packets-recv" class="metric-value">0</span></div>
                </div>
            </div>
        </div>
        
        <script>
            // Tab functionality
            function openTab(evt, tabName) {
                const tabcontent = document.getElementsByClassName("tabcontent");
                for (let i = 0; i < tabcontent.length; i++) {
                    tabcontent[i].classList.remove("visible");
                }
                
                const tablinks = document.getElementsByClassName("tablinks");
                for (let i = 0; i < tablinks.length; i++) {
                    tablinks[i].classList.remove("active");
                }
                
                document.getElementById(tabName).classList.add("visible");
                evt.currentTarget.classList.add("active");
            }
            
            // Format bytes to human-readable format
            function formatBytes(bytes, decimals = 2) {
                if (bytes === 0) return '0 Bytes';
                const k = 1024;
                const dm = decimals < 0 ? 0 : decimals;
                const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB'];
                const i = Math.floor(Math.log(bytes) / Math.log(k));
                return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i];
            }
            
            // Format seconds to human-readable time
            function formatTime(seconds) {
                if (seconds < 60) return seconds.toFixed(1) + 's';
                const minutes = Math.floor(seconds / 60);
                const secs = seconds % 60;
                return minutes + 'm ' + secs.toFixed(0) + 's';
            }
            
            // Format timestamp to readable date
            function formatTimestamp(timestamp) {
                if (!timestamp) return '-';
                const date = new Date(timestamp * 1000);
                return date.toLocaleString();
            }
            
            const eventSource = new EventSource('/memory-stream');
            
            eventSource.onmessage = function(event) {
                const data = JSON.parse(event.data);
                
                // Update System Memory
                const sysMemPercent = data.system.memory.percent;
                document.getElementById('system-memory-bar').style.width = `${sysMemPercent}%`;
                document.getElementById('system-memory-bar').textContent = `${sysMemPercent.toFixed(1)}%`;
                
                document.getElementById('sys-mem-total').textContent = (data.system.memory.total / 1024 / 1024 / 1024).toFixed(2);
                document.getElementById('sys-mem-used').textContent = (data.system.memory.used / 1024 / 1024 / 1024).toFixed(2);
                document.getElementById('sys-mem-available').textContent = (data.system.memory.available / 1024 / 1024 / 1024).toFixed(2);
                document.getElementById('sys-mem-active').textContent = (data.system.memory.active / 1024 / 1024 / 1024).toFixed(2);
                document.getElementById('sys-mem-cached').textContent = (data.system.memory.cached / 1024 / 1024 / 1024).toFixed(2);
                
                // Update System CPU
                const sysCpuPercent = data.system.cpu.percent;
                document.getElementById('system-cpu-bar').style.width = `${sysCpuPercent}%`;
                document.getElementById('system-cpu-bar').textContent = `${sysCpuPercent.toFixed(1)}%`;
                document.getElementById('sys-cpu-count').textContent = data.system.cpu.count;
                document.getElementById('sys-cpu-freq').textContent = data.system.cpu.freq.toFixed(0);
                
                // Update per-CPU usage
                let perCpuHtml = '';
                if (data.system.cpu.per_cpu && data.system.cpu.per_cpu.length > 0) {
                    perCpuHtml = '<div class="metric">Per Core:</div>';
                    data.system.cpu.per_cpu.forEach((cpu, idx) => {
                        perCpuHtml += `
                            <div class="metric">
                                Core ${idx}: 
                                <div class="progress-container" style="display: inline-block; width: 100px; margin-left: 10px;">
                                    <div class="progress-bar" style="width: ${cpu}%; background-color: ${cpu > 80 ? '#F44336' : '#FF9800'}">${cpu.toFixed(1)}%</div>
                                </div>
                            </div>
                        `;
                    });
                }
                document.getElementById('per-cpu-usage').innerHTML = perCpuHtml;
                
                // Update System Swap
                const sysSwapPercent = data.system.swap.percent;
                document.getElementById('system-swap-bar').style.width = `${sysSwapPercent}%`;
                document.getElementById('system-swap-bar').textContent = `${sysSwapPercent.toFixed(1)}%`;
                
                document.getElementById('sys-swap-total').textContent = (data.system.swap.total / 1024 / 1024 / 1024).toFixed(2);
                document.getElementById('sys-swap-used').textContent = (data.system.swap.used / 1024 / 1024 / 1024).toFixed(2);
                document.getElementById('sys-swap-free').textContent = (data.system.swap.free / 1024 / 1024 / 1024).toFixed(2);
                
                // Update System Disk
                const sysDiskPercent = data.system.disk.percent;
                document.getElementById('system-disk-bar').style.width = `${sysDiskPercent}%`;
                document.getElementById('system-disk-bar').textContent = `${sysDiskPercent.toFixed(1)}%`;
                
                document.getElementById('sys-disk-total').textContent = (data.system.disk.total / 1024 / 1024 / 1024).toFixed(2);
                document.getElementById('sys-disk-used').textContent = (data.system.disk.used / 1024 / 1024 / 1024).toFixed(2);
                document.getElementById('sys-disk-free').textContent = (data.system.disk.free / 1024 / 1024 / 1024).toFixed(2);
                
                // Update Temperature Sensors
                let tempHtml = '';
                if (data.system.temperature && Object.keys(data.system.temperature).length > 0) {
                    for (const [name, sensors] of Object.entries(data.system.temperature)) {
                        tempHtml += `<h4>${name}</h4>`;
                        sensors.forEach(sensor => {
                            tempHtml += `
                                <div class="metric">
                                    ${sensor.label || 'Sensor'}: 
                                    <span class="metric-value">${sensor.current}°C</span>
                                    (High: ${sensor.high}°C, Critical: ${sensor.critical}°C)
                                </div>
                            `;
                        });
                    }
                } else {
                    tempHtml = '<div class="metric">No temperature sensors available</div>';
                }
                document.getElementById('temperature-sensors').innerHTML = tempHtml;
                
                // Update Battery Status
                let batteryHtml = '';
                if (data.system.battery) {
                    batteryHtml = `
                        <div class="metric">Percent: <span class="metric-value">${data.system.battery.percent}%</span></div>
                        <div class="metric">Power Plugged: <span class="metric-value">${data.system.battery.power_plugged ? 'Yes' : 'No'}</span></div>
                        ${data.system.battery.secsleft ? `<div class="metric">Time Left: <span class="metric-value">${formatTime(data.system.battery.secsleft)}</span></div>` : ''}
                    `;
                } else {
                    batteryHtml = '<div class="metric">No battery information available</div>';
                }
                document.getElementById('battery-status').innerHTML = batteryHtml;
                
                // Update Python Process
                if (data.python_process) {
                    const py = data.python_process;
                    
                    // Python Memory
                    const pyMemPercent = py.memory_percent;
                    document.getElementById('python-memory-bar').style.width = `${pyMemPercent}%`;
                    document.getElementById('python-memory-bar').textContent = `${pyMemPercent.toFixed(1)}%`;
                    
                    document.getElementById('py-rss').textContent = (py.memory.rss / 1024 / 1024).toFixed(1);
                    document.getElementById('py-vms').textContent = (py.memory.vms / 1024 / 1024).toFixed(1);
                    document.getElementById('py-uss').textContent = (py.memory.uss / 1024 / 1024).toFixed(1);
                    document.getElementById('py-pss').textContent = (py.memory.pss / 1024 / 1024).toFixed(1);
                    document.getElementById('py-memory-percent').textContent = pyMemPercent.toFixed(1);
                    
                    // Python CPU
                    const pyCpuPercent = py.cpu_percent;
                    document.getElementById('python-cpu-bar').style.width = `${pyCpuPercent}%`;
                    document.getElementById('python-cpu-bar').textContent = `${pyCpuPercent.toFixed(1)}%`;
                    
                    document.getElementById('py-cpu-percent').textContent = pyCpuPercent.toFixed(1);
                    document.getElementById('py-threads').textContent = py.threads;
                    document.getElementById('py-cpu-user').textContent = py.cpu_times ? py.cpu_times.user.toFixed(1) : '0';
                    document.getElementById('py-cpu-system').textContent = py.cpu_times ? py.cpu_times.system.toFixed(1) : '0';
                    
                    // Python Process Info
                    document.getElementById('py-pid').textContent = py.pid;
                    document.getElementById('py-name').textContent = py.name;
                    document.getElementById('py-status').textContent = py.status;
                    document.getElementById('py-created').textContent = formatTimestamp(py.create_time);
                    document.getElementById('py-open-files').textContent = py.open_files;
                    document.getElementById('py-connections').textContent = py.connections;
                }
                
                // Update Process Table
                const processTableBody = document.getElementById('process-table-body');
                processTableBody.innerHTML = '';
                
                if (data.top_processes && data.top_processes.length > 0) {
                    document.getElementById('process-count').textContent = data.top_processes.length;
                    
                    data.top_processes.forEach(proc => {
                        const row = document.createElement('tr');
                        if (proc.is_browser) {
                            row.classList.add('browser-process');
                        } else if (proc.memory_percent > 10 || proc.cpu_percent > 50) {
                            row.classList.add('critical-process');
                        }
                        
                        row.innerHTML = `
                            <td>${proc.pid}</td>
                            <td>${proc.name}</td>
                            <td class="memory-cell">${(proc.memory.rss / 1024 / 1024).toFixed(1)}</td>
                            <td>${proc.memory_percent.toFixed(1)}</td>
                            <td class="cpu-cell">${proc.cpu_percent.toFixed(1)}</td>
                            <td>${proc.threads}</td>
                            <td>${proc.status}</td>
                            <td>${proc.is_browser ? 'Browser' : 'System'}</td>
                        `;
                        
                        processTableBody.appendChild(row);
                    });
                }
                
                // Update Network
                document.getElementById('net-sent').textContent = (data.system.network.bytes_sent / 1024 / 1024).toFixed(2);
                document.getElementById('net-recv').textContent = (data.system.network.bytes_recv / 1024 / 1024).toFixed(2);
                document.getElementById('net-packets-sent').textContent = data.system.network.packets_sent;
                document.getElementById('net-packets-recv').textContent = data.system.network.packets_recv;
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