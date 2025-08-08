# Import Python modules
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Query, HTTPException, Response, BackgroundTasks
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse, PlainTextResponse, FileResponse
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
from typing import Dict, Any, Optional, List
from xml.etree import ElementTree as ET
from io import StringIO
from ai_module import analyze_log_content
from ml_logger import log_user_action
import uvicorn, shutil, asyncio, os, re, difflib, json, time, subprocess, math, logging, sys, aiofiles, threading, psutil, signal, traceback, zipfile, tarfile, gzip


@asynccontextmanager
async def lifespan(app: FastAPI):
    # This replaces both @app.on_event("startup") and startup_event()
    
    # 1. Show ASCII Banner (your original startup code)
    banner = r"""
 ##::::::::'#######:::'######:::::::'######::'##::: ##:'####:'########:'########:'########:'########::
 ##:::::::'##.... ##:'##... ##:::::'##... ##: ###:: ##:. ##:: ##.....:: ##.....:: ##.....:: ##.... ##:
 ##::::::: ##:::: ##: ##:::..:::::: ##:::..:: ####: ##:: ##:: ##::::::: ##::::::: ##::::::: ##:::: ##:
 ##::::::: ##:::: ##: ##::'####::::. ######:: ## ## ##:: ##:: ######::: ######::: ######::: ########::
 ##::::::: ##:::: ##: ##::: ##::::::..... ##: ##. ####:: ##:: ##...:::: ##...:::: ##...:::: ##.. ##:::
 ##::::::: ##:::: ##: ##::: ##:::::'##::: ##: ##:. ###:: ##:: ##::::::: ##::::::: ##::::::: ##::. ##::
 ########:. #######::. ######::::::. ######:: ##::. ##:'####: ##::::::: ##::::::: ########: ##:::. ##:
........:::.......::::......::::::::......:::..::::..::....::..::::::::..::::::::........::..:::::..::
:: Log Sniffer Tool ::                                                           (v1.0.0.BETA_RELEASE)
    """
    print(banner)
    
    # 2. Your original startup_event() logic
    logger.info("⚡FastAPI server starting...")
    logger.info(f"🗂️ Log directory: {os.path.abspath(Config.LOG_DIR)}")
    
    await initialize_critical_services()
    
    if Config.PRELOAD_ENABLED:
        asyncio.create_task(delayed_background_preload())
        logger.info("📦 Background preload will start after server becomes responsive")
    else:
        logger.info("📛 Skipping preload (PRELOAD_ENABLED=False)")
    
    yield  # This is where your app runs
    
    # (Optional) Add shutdown logic here if needed
    logger.info("🚨⏻ Server shutting down...")

# Initialize FastAPI
app = FastAPI(lifespan=lifespan)

# Configuration Constants
class Config:
    LOG_OUTPUT_DIR = "./applog"
    LOG_DIR = "./logs"
    MAX_CACHE_SIZE = 10
    PRELOAD_ENABLED = True  # Enable background preloading of logs
    PRELOAD_LARGE_FILES = True  # Preload large files in background
    LARGE_FILE_THRESHOLD_MB = 10 # Threshold for processing XML RQ/RS from logs
    EXCLUDED_EXTENSIONS = {'.zip', '.tar', '.gz', '.tar.gz', '.7z', '.Z', '.bz2', '.rar', '.xz'}
    CRITICAL_ENDPOINTS = [
        '/list_logs',
        '/healthcheck',
        '/get_rqrs',
        '/api/search_logs_stream',
        '/get_rqrs_content',
        '/download_remote_logs'
    ]

# Initialize global state
class GlobalState:
    scp_progress = {"percent": 0, "eta": 0}
    scp_proc = None
    scp_aborted = False
    abort_event = threading.Event()
    status = {
        "search_active": False,
        "matches_found": 0,
        "files_scanned": 0
    }
    endpoint_metrics = {}

# Regex patterns
class Patterns:
    TIMESTAMP = re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2},\d{3}')
    THREAD_ID = re.compile(r'(?:\[[^\]]*\] ){1,2}\[(\d{13}_\d{4})\]')
    ERROR = re.compile(r"\[(ERROR|WARN|FATAL)\]")
    SERVICE = re.compile(r"\[(com\.datalex\..+?)\]")
    RQRS_MARKER = re.compile(r'(XML Request:|XML Response:)\s*$')
    RQRS = re.compile(r'<([a-zA-Z_][\w]*?(RQ|RS))[\s>]')
    DATE = re.compile(r'^\d{4}-\d{2}-\d{2}')
    THREAD = re.compile(r'\[(NDC_[^\]]+?)\]')
    ALT_THREAD = re.compile(r'\[NA\] \[([^\]]+?)\] \[NA\]')
    BRACKETED = re.compile(r'\[([^\[\]]+)\]')
    THREAD_FALLBACK = re.compile(r'\d{13}_\d{4,}')
    SERVICE_CLASS = re.compile(r'\[([^\]]+?)\]$')
    XML_ERRORS = re.compile(r'<(ns1:)?Errors>|<.*Error.*>|ErrorCode|WarningCode', re.IGNORECASE)

# Mount static directories
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/js", StaticFiles(directory="js"), name="js")
templates = Jinja2Templates(directory="templates")

# Setup CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

################################
# Logger Setup
################################
def setup_logger():
    os.makedirs(Config.LOG_OUTPUT_DIR, exist_ok=True)
    log_file_path = os.path.join(Config.LOG_OUTPUT_DIR, "fastAPI.log")

    logger = logging.getLogger("fastapi_logger")
    logger.setLevel(logging.DEBUG)

    # File handler with rotation (100MB, keep last 5 logs)
    file_handler = RotatingFileHandler(
        log_file_path,
        maxBytes=100 * 1024 * 1024,
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

    return logger

if os.getenv("RELOADER") != "true":
    # Only configure logging in the main process
    logger = setup_logger()  # Your existing logger setup

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

# Override print() to use our logger
print = lambda *args, **kwargs: printf(" ".join(str(a) for a in args), level="info")

################################
# Models
################################
class SearchRequest(BaseModel):
    search_text: str
    search_mode: str
    target_file: Optional[str] = None

class SCPDownloadRequest(BaseModel):
    host: str
    username: str = "remotedeploy"
    remote_path: str = "/datalex/logs/jboss"
    pattern: str = "matrixtdp4.log*"
    clear_existing: bool = False

class FileStatus(Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETE = "complete"
    ERROR = "error"

class Priority(IntEnum):
    USER_REQUEST = 1
    BACKGROUND_PRELOAD = 2

################################
# Helper Functions
################################
def is_compressed_file(filename: str) -> bool:
    """Check if file has a compressed extension"""
    return any(filename.lower().endswith(ext) for ext in Config.EXCLUDED_EXTENSIONS)

def get_file_metadata(filepath: Path) -> Dict[str, Any]:
    """Get file metadata with performance logging"""
    start_time = datetime.now()
    size = filepath.stat().st_size
    lines = 0
    
    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
        lines = sum(1 for _ in f)
    
    duration = (datetime.now() - start_time).total_seconds()
    return {
        'size': size,
        'lines': lines,
        'processing_time': duration
    }

def extract_thread_id(line: str) -> str:
    """Extract thread ID from log line with multiple fallback patterns"""
    # First try the specific thread patterns
    match = Patterns.THREAD_ID.search(line)
    if match:
        return match.group(1)   
    
    # Only if none of the above match, return UNKNOWN
    # Don't fall back to BRACKETED as it might catch wrong things
    return "UNKNOWN"

def extract_service(line: str) -> str:
    """Extract the Java class name from a bracket that contains dots"""
    if not Patterns.TIMESTAMP.match(line):
        return "UNKNOWN"

    brackets = Patterns.BRACKETED.findall(line)
    for value in reversed(brackets):
        if '.' in value:
            return value.split('.')[-1]

    return "UNKNOWN"

def format_bytes(size: int) -> str:
    """Format bytes to human-readable string"""
    if size < 0:
        return "0B"
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024:
            return f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}PB"

def format_time(seconds: float) -> str:
    """Convert seconds to HH:MM:SS format"""
    return str(timedelta(seconds=seconds))

def memory_safe(min_mb: int = 100) -> bool:
    """Check if system has sufficient memory"""
    return psutil.virtual_memory().available > min_mb * 1024 * 1024

def similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()

################################
# File Processing Classes
################################
class AsyncLRUCache:
    def __init__(self, maxsize: int = Config.MAX_CACHE_SIZE):
        self.maxsize = maxsize
        self.cache: Dict[str, Any] = {}
        self.lock = asyncio.Lock()
        self.order: List[str] = []

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

    async def invalidate_all(self):
        """Clear all items from the cache"""
        async with self.lock:
            self.cache.clear()
            self.order.clear()
            logger.info("🧹 Cache completely cleared (all items removed)")

class FileProcessor:
    def __init__(self):
        self.active_tasks: Dict[str, asyncio.Task] = {}
        self.pending_requests: Dict[str, asyncio.Event] = {}
        self.results: Dict[str, dict] = {}
        self.lock = asyncio.Lock()
    
    async def process_file(self, filename: str, priority: Priority) -> dict:
        async with self.lock:
            if filename in self.results:
                return self.results[filename]
            
            if filename in self.active_tasks:
                if priority == Priority.USER_REQUEST and filename in self.pending_requests:
                    self.active_tasks[filename].cancel()
                    del self.active_tasks[filename]
                else:
                    await self.pending_requests[filename].wait()
                    return self.results.get(filename)
            
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

class ProgressTracker:
    def __init__(self):
        self.active_tasks = {}
        
    def start(self, log_file: str):
        self.active_tasks[log_file] = {
            'start_time': time.time(),
            'lines_processed': 0,
            'status': 'processing'
        }
        
    def update(self, log_file: str, lines_processed: int):
        if log_file in self.active_tasks:
            self.active_tasks[log_file]['lines_processed'] = lines_processed
            self.active_tasks[log_file]['elapsed'] = time.time() - self.active_tasks[log_file]['start_time']
            
    def complete(self, log_file: str):
        if log_file in self.active_tasks:
            self.active_tasks[log_file]['status'] = 'complete'

# Initialize global instances
LOG_CACHE = AsyncLRUCache()
file_processor = FileProcessor()
progress_tracker = ProgressTracker()

################################
# Core Functions
################################

async def parse_log_file(log: str) -> Dict[str, Any]:
    if (cached := await LOG_CACHE.get(log)) is not None:
        return cached

    filepath = os.path.join(Config.LOG_DIR, log)
    
    try:
        file_size = os.path.getsize(filepath)
        if file_size <= Config.LARGE_FILE_THRESHOLD_MB * 1024 * 1024:
            logger.info(f"🔬 Processing {log} as normal file ({file_size/1024/1024:.2f} MB)")
            result = await process_file_normal(filepath, log)
        else:
            logger.info(f"🔬 Processing {log} as large file ({file_size/1024/1024:.2f} MB)")
            result = await process_large_file_chunked(filepath, log)
        
        # Standardize the response format
        if "rqrs" not in result:
            standardized_result = {"rqrs": result.get("entries", [])}
        else:
            standardized_result = result
            
        await LOG_CACHE.set(log, standardized_result)
        return standardized_result
        
    except Exception as e:
        logger.error(f"Failed to process {log}: {str(e)}")
        return {"rqrs": []}  # Always return valid format

async def async_preload_logs():
    """Optimized log preloading that processes all files regardless of size"""
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

    semaphore = asyncio.Semaphore(2)

    async def process_single_file(file: str):
        nonlocal stats
        filepath = os.path.join(Config.LOG_DIR, file)
        
        try:
            async with semaphore:
                if not os.path.isfile(filepath):
                    stats['skipped'] += 1
                    return

                if await LOG_CACHE.get(file) is not None:
                    stats['skipped'] += 1
                    return

                file_size = os.path.getsize(filepath) / (1024 * 1024)
                logger.info(f"🔵 Processing single file {file} ({file_size:.2f} MB)")

                if file_size > 50:
                    logger.info(f"🔵 Processing large file {file} with chunked reading...")
                    result = await process_large_file_chunked(filepath, file)
                else:
                    result = await process_file_normal(filepath, file)
                
                stats['processed'] += 1
                stats['total_entries'] += len(result['entries'])
                stats['total_lines'] += result['line_count']
                
                await LOG_CACHE.set(file, {
                    "metadata": {
                        "preloaded": True,
                        "lines_processed": result['line_count'],
                        "entries_found": len(result['entries']),
                        "processing_time": round(time.time() - start_time, 2),
                        "file_size_mb": round(file_size, 2)
                    },
                    "rqrs": result['entries']
                })
                
        except Exception as e:
            logger.error(f"🔴 Failed to process {file}: {str(e)}")
            stats['failed'] += 1

    files = os.listdir(Config.LOG_DIR)
    await asyncio.gather(*[process_single_file(file) for file in files])

    end_mem = process.memory_info().rss / (1024 * 1024)
    elapsed = time.time() - start_time
    
    logger.info("\n📊 Final Preload Summary:")
    logger.info(f"🔵  Files processed: {stats['processed']}")
    logger.info(f"🔵  Files skipped (cached): {stats['skipped']}")
    logger.info(f"🔵  Files failed: {stats['failed']}")
    logger.info(f"🔵  Total lines scanned: {stats['total_lines']:,}")
    logger.info(f"🔵  Total RQ/RS entries found: {stats['total_entries']:,}")
    logger.info(f"🔵  Memory usage: {start_mem:.2f} MB → {end_mem:.2f} MB")
    logger.info(f"🔵  Total time: {elapsed:.2f} seconds")

async def process_file_normal(filepath: str, filename: str) -> Dict[str, Any]:
    """Process normal-sized files with XML marker support"""
    entries = []
    line_count = 0
    previous_line = ""
    start_time = time.time()
    xml_marker_found = False
    xml_buffer = []
    last_timestamp = ""
    last_service = "UNKNOWN"
    xml_start_line = 0
    
    try:
        async with aiofiles.open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            async for line in f:
                line_count += 1
                stripped = line.strip()
                
                if not stripped:
                    continue
                    
                # Check for timestamp line
                if Patterns.TIMESTAMP.match(stripped):
                    # If we were collecting XML, process it before starting new entry
                    if xml_buffer:
                        xml_content = '\n'.join(xml_buffer)
                        if match := Patterns.RQRS.search(xml_content):
                            entries.append({
                                "line": xml_start_line,
                                "thread": extract_thread_id(last_timestamp),
                                "service": last_service,
                                "tag": match.group(1),
                                "raw": xml_content[:512],  # First 512 chars
                                "has_issue": bool(Patterns.XML_ERRORS.search(xml_content))
                            })
                        xml_buffer = []
                    
                    last_timestamp = stripped
                    last_service = extract_service(stripped)
                    xml_marker_found = False
                    
                    # Check if this line contains an XML marker
                    if "XML Request:" in stripped or "XML Response:" in stripped:
                        xml_marker_found = True
                        xml_start_line = line_count + 1  # Next line will be XML start
                
                # Handle XML content collection
                elif xml_marker_found:
                    if stripped.startswith("<"):
                        xml_buffer.append(stripped)
                    elif xml_buffer:  # If we're in XML and hit non-XML line
                        # Process the collected XML
                        xml_content = '\n'.join(xml_buffer)
                        if match := Patterns.RQRS.search(xml_content):
                            entries.append({
                                "line": xml_start_line,
                                "thread": extract_thread_id(last_timestamp),
                                "service": last_service,
                                "tag": match.group(1),
                                "raw": xml_content[:512],
                                "has_issue": bool(Patterns.XML_ERRORS.search(xml_content))
                            })
                        xml_buffer = []
                        xml_marker_found = False
                
                previous_line = stripped
            
            # Process any remaining XML at end of file
            if xml_buffer:
                xml_content = '\n'.join(xml_buffer)
                if match := Patterns.RQRS.search(xml_content):
                    entries.append({
                        "line": xml_start_line,
                        "thread": extract_thread_id(last_timestamp),
                        "service": last_service,
                        "tag": match.group(1),
                        "raw": xml_content[:512],
                        "has_issue": bool(Patterns.XML_ERRORS.search(xml_content))
                    })
        
        processing_time = time.time() - start_time
        logger.info(f"Processed {filename} ({line_count} lines, {len(entries)} entries) in {processing_time:.2f}s")
        
        return {
            "entries": entries,
            "line_count": line_count,
            "processing_time": processing_time
        }
        
    except Exception as e:
        logger.error(f"Error processing {filename}: {str(e)}")
        raise

async def process_large_file_chunked(filepath: str, filename: str) -> Dict[str, Any]:
    """Process large files with accurate line numbers"""
    entries = []
    line_count = 0
    file_start = time.time()
    xml_buffer = []
    xml_marker_found = False
    xml_start_line = 0
    last_timestamp = ""
    last_service = "UNKNOWN"
    
    async with aiofiles.open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
        buffer = ""
        while True:
            chunk = await f.read(1024 * 1024)  # 1MB chunks
            if not chunk:
                break
                
            buffer += chunk
            lines = buffer.splitlines(True)  # Keep line endings
            
            # Process complete lines (leave partial line in buffer)
            for line in lines[:-1]:
                line_count += 1
                stripped = line.strip()
                
                if Patterns.TIMESTAMP.match(stripped):
                    # Process any pending XML
                    if xml_buffer:
                        xml_content = '\n'.join(xml_buffer)
                        if match := Patterns.RQRS.search(xml_content):
                            entries.append({
                                "line": xml_start_line,
                                "thread": extract_thread_id(last_timestamp),
                                "service": last_service,
                                "tag": match.group(1),
                                "raw": xml_content[:512],
                                "has_issue": bool(Patterns.XML_ERRORS.search(xml_content))
                            })
                        xml_buffer = []
                    
                    last_timestamp = stripped
                    last_service = extract_service(stripped)
                    xml_marker_found = False
                    
                    if "XML Request:" in stripped or "XML Response:" in stripped:
                        xml_marker_found = True
                        xml_start_line = line_count + 1
                
                elif xml_marker_found:
                    if stripped.startswith("<"):
                        xml_buffer.append(stripped)
                    elif xml_buffer:
                        xml_content = '\n'.join(xml_buffer)
                        if match := Patterns.RQRS.search(xml_content):
                            entries.append({
                                "line": xml_start_line,
                                "thread": extract_thread_id(last_timestamp),
                                "service": last_service,
                                "tag": match.group(1),
                                "raw": xml_content[:512],
                                "has_issue": bool(Patterns.XML_ERRORS.search(xml_content))
                            })
                        xml_buffer = []
                        xml_marker_found = False
            
            buffer = lines[-1]  # Save partial line for next chunk
            
    # Process any remaining XML at end of file
    if xml_buffer:
        xml_content = '\n'.join(xml_buffer)
        if match := Patterns.RQRS.search(xml_content):
            entries.append({
                "line": xml_start_line,
                "thread": extract_thread_id(last_timestamp),
                "service": last_service,
                "tag": match.group(1),
                "raw": xml_content[:512],
                "has_issue": bool(Patterns.XML_ERRORS.search(xml_content))
            })
    
    processing_time = time.time() - file_start
    logger.info(f"Processed {filename} - {line_count} lines, {len(entries)} entries in {processing_time:.2f}s")
    
    return {
        "metadata": {
            "lines_processed": line_count,
            "entries_found": len(entries),
            "processing_time": round(processing_time, 2),
            "file_size_mb": round(os.path.getsize(filepath)/(1024*1024), 2)
        },
        "rqrs": entries
    }

################################
# Middleware
################################
@app.middleware("http")
async def combined_middleware(request: Request, call_next):
    # Endpoint Prioritization Logic
    if request.url.path in Config.CRITICAL_ENDPOINTS:
        if request.headers.get('x-request-priority') == 'background':
            await asyncio.sleep(0.1)
        return await call_next(request)
        
    # Memory Protection Logic
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
        logger.warning(f"🚨 MEMORY PROTECTION TRIGGERED: {error_msg}")
        return JSONResponse(error_msg, status_code=503)
    
    # Request Metrics
    process = psutil.Process()
    mem_before = process.memory_info().rss / 1024 / 1024
    start_time = time.time()
    
    body = None
    if request.method in ("POST", "PUT"):
        try:
            body = await request.body()
        except RuntimeError:
            body = b"<stream already consumed>"
    
    response = await call_next(request)
    process_time = (time.time() - start_time) * 1000
    formatted_process_time = "{0:.2f}".format(process_time)

    logger.info(
        f"🚨 Endpoint called: {request.method} {request.url.path} "
        f"| Params: {dict(request.query_params)} "
        f"| Body: {body.decode() if body else 'None'} "
        f"| Status: {response.status_code} "
        f"| Time: {formatted_process_time}ms"
    )

    # After request metrics
    mem_after = process.memory_info().rss / 1024 / 1024
    elapsed = time.time() - start_time
    memory_used = mem_after - mem_before
    
    if system_mem.percent > 50:
        logger.info(f"🚨 WARNING: System memory at {system_mem.percent}%")
        logger.info(f"    Available: {system_mem.available/1024/1024:.1f}MB")
        logger.info(f"    Used by Python: {mem_after:.1f}MB")
        logger.info(f"    Request consumed: {memory_used:.1f}MB")
    
    GlobalState.endpoint_metrics[request.url.path] = {
        "memory_used_mb": round(memory_used, 2),
        "system_memory_percent": system_mem.percent,
        "time_sec": round(elapsed, 2),
        "timestamp": datetime.now().isoformat()
    }
    
    status_code = getattr(response, "status_code", 500)
    logger.info(f"{request.method} {request.url.path} ({status_code}) {elapsed:.2f}s | +{memory_used:.1f}MB")
    
    return response

################################
# Event Handlers
################################

async def initialize_critical_services():
    """Initialize essential services before accepting requests"""
    logger.info("🚀 Initializing critical services...")
    # Add any essential initialization here
    pass

async def delayed_background_preload():
    """Start background preload after a short delay"""
    await asyncio.sleep(10)
    logger.info("🚀 Starting background preload now")
    await background_preload()

async def background_preload():
    """Optimized background preload that minimizes impact"""
    large_files = await get_large_files()
    
    for i, filename in enumerate(large_files):
        try:
            await file_processor.process_file(filename, Priority.BACKGROUND_PRELOAD)
            
            if i % 2 == 0:
                await asyncio.sleep(0.1)
                
        except Exception as e:
            logger.error(f"🔴 Background preload failed for {filename}: {str(e)}")

async def get_large_files() -> List[str]:
    """Get list of large files with cooperative yielding"""
    files = []
    for filename in os.listdir(Config.LOG_DIR):
        filepath = os.path.join(Config.LOG_DIR, filename)
        if os.path.isfile(filepath) and os.path.getsize(filepath) > 100 * 1024 * 1024:
            files.append(filename)
        
        if len(files) % 10 == 0:
            await asyncio.sleep(0)
    
    return files

################################
# SCP Download Functions
################################
def extract_compressed_files():
    """Extract all compressed files in the logs directory"""
    for file in os.listdir(Config.LOG_DIR):
        file_path = os.path.join(Config.LOG_DIR, file)
        try:
            if file.endswith(".zip"):
                with zipfile.ZipFile(file_path, 'r') as zip_ref:
                    zip_ref.extractall(Config.LOG_DIR)
                    logger.info(f"🗂️ Extracted {file} as ZIP")
                os.remove(file_path)
                logger.info(f"🗑️ Deleted ZIP file: {file}")

            elif file.endswith((".tar.gz", ".tgz", ".tar")):
                with tarfile.open(file_path, 'r:*') as tar_ref:
                    tar_ref.extractall(Config.LOG_DIR)
                    logger.info(f"🗂️ Extracted {file} as TAR")
                os.remove(file_path)
                logger.info(f"🗑️ Deleted TAR file: {file}")

            elif file.endswith(".gz") and not file.endswith((".tar.gz", ".tgz")):
                out_path = os.path.splitext(file_path)[0]
                with gzip.open(file_path, 'rb') as f_in:
                    with open(out_path, 'wb') as f_out:
                        shutil.copyfileobj(f_in, f_out)
                        logger.info(f"🗂️ Extracted {file} as GZ → {os.path.basename(out_path)}")
                os.remove(file_path)
                logger.info(f"🗑️ Deleted GZ file: {file}")

        except Exception as e:
            logger.error(f"❌ Failed to extract {file}: {e}")

    # Move all discovered .log files from subdirectories to ./logs
    for root, dirs, files in os.walk(Config.LOG_DIR):
        for file in files:
            if file.endswith(".log"):
                full_path = os.path.join(root, file)
                if os.path.abspath(root) != os.path.abspath(Config.LOG_DIR):
                    target_path = os.path.join(Config.LOG_DIR, file)
                    try:
                        shutil.move(full_path, target_path)
                        logger.info(f"📂 Moved extracted {file} → {target_path}")
                    except Exception as move_err:
                        logger.error(f"❌ Failed to move {file}: {move_err}")
    
    # Cleanup empty directories
    for root, dirs, files in os.walk(Config.LOG_DIR, topdown=False):
        for dir_name in dirs:
            dir_path = os.path.join(root, dir_name)
            try:
                if not os.listdir(dir_path):
                    os.rmdir(dir_path)
                    logger.info(f"🧹 Deleted empty directory: {dir_path}")
            except Exception as e:
                logger.error(f"❌ Failed to delete directory {dir_path}: {e}")

def list_log_files_sync():
    """Synchronous helper function to list log files"""
    try:
        return sorted(
            f for f in os.listdir(Config.LOG_DIR)
            if os.path.isfile(os.path.join(Config.LOG_DIR, f))
        )
    except Exception as e:
        print(f"[Error] Failed to list log files: {e}")
        return []

def list_log_files():
    """Helper function to list log files"""
    try:
        return sorted(
            f for f in os.listdir(Config.LOG_DIR)
            if os.path.isfile(os.path.join(Config.LOG_DIR, f)) and not is_compressed_file(f)
        )
    except Exception as e:
        print(f"[Error] Failed to list log files: {e}")
        return []

################################
# API Endpoints
################################
@app.get("/", response_class=HTMLResponse)
async def serve_ui(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/healthcheck")
async def health_check():
    """Lightweight endpoint to verify server responsiveness"""
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}

@app.get("/list_logs")
async def list_logs_endpoint():
    return {"logs": list_log_files()}

@app.get("/scp_progress")
async def scp_progress():
    async def event_stream():
        last_sent = None
        while True:
            if last_sent != GlobalState.scp_progress:
                yield f"data: {json.dumps(GlobalState.scp_progress)}\n\n"
                last_sent = GlobalState.scp_progress.copy()
            if GlobalState.scp_progress["percent"] >= 100:
                break
            await asyncio.sleep(0.5)
    return StreamingResponse(event_stream(), media_type="text/event-stream")

@app.post("/download_remote_logs")
async def download_remote_logs(request: Request, req: SCPDownloadRequest):
    GlobalState.scp_progress = {"percent": 0, "eta": 0, "current_size": 0, "total_size": 0}
    GlobalState.scp_aborted = False
    start_time = time.time()

    if req.clear_existing:
        for f in os.listdir(Config.LOG_DIR):
            fp = os.path.join(Config.LOG_DIR, f)
            if os.path.isfile(fp):
                os.remove(fp)

    remote = f"{req.username}@{req.host}:{req.remote_path}/{req.pattern}"
    scp_cmd = ["bash", "./scp_wrapper.sh", "-p", remote, Config.LOG_DIR]
    print(f"📥 Running SCP command: {' '.join(scp_cmd)}")

    try:
        # Get the expected filename from the pattern (handles wildcards)
        base_pattern = req.pattern.replace('*', '')
        ssh_cmd = ["ssh", f"{req.username}@{req.host}", f"du -cb {req.remote_path}/{req.pattern} | tail -1 | cut -f1"]
        stdout = subprocess.check_output(ssh_cmd, stderr=subprocess.DEVNULL, text=True).strip()
        total_bytes = int(stdout) if stdout.isdigit() else 0
        print(f"📦 Remote file size: {total_bytes} bytes ({format_bytes(total_bytes)})")
    except Exception as e:
        print(f"⚠️ Failed to get remote file size: {e}")
        total_bytes = 0

    scp_status = {"done": False, "error": None}

    def format_eta(seconds):
        if seconds < 0:
            return "unknown"
        minutes, secs = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        if hours > 0:
            return f"{hours}h {minutes}m {secs}s"
        if minutes > 0:
            return f"{minutes}m {secs}s"
        return f"{secs}s"

    async def run_scp():
        try:
            GlobalState.scp_proc = Popen(
                scp_cmd,
                stdout=PIPE,
                stderr=PIPE,
                text=True,
                start_new_session=True
            )

            # Initialize tracking variables
            last_size = 0
            stalled_count = 0
            max_stalled = 10  # If progress stalls for 10 checks, consider it failed

            while GlobalState.scp_proc.poll() is None:
                if GlobalState.scp_aborted:
                    print("🛑 Aborting SCP from UI...")
                    try:
                        print(f"🔍 SCP_PROC PID: {GlobalState.scp_proc.pid}")
                        parent = psutil.Process(GlobalState.scp_proc.pid)
                        print(f"🔍 Parent cmdline: {parent.cmdline()}")
                        for child in parent.children(recursive=True):
                            print(f"🔍 Killing child PID: {child.pid} cmdline: {child.cmdline()}")

                        for _ in range(10):
                            if GlobalState.scp_proc.poll() is not None:
                                break
                            print("⌛ Waiting for SCP to terminate...")
                            await asyncio.sleep(0.5)
                    except Exception as e:
                        print(f"❌ Error during abort: {e}")

                    GlobalState.scp_progress = {"percent": 0, "eta": 0, "current_size": 0, "total_size": total_bytes}
                    scp_status["error"] = "Download aborted by user."
                    break

                # Find the most recently modified file matching our pattern
                target_files = [
                    f for f in os.listdir(Config.LOG_DIR)
                    if os.path.isfile(os.path.join(Config.LOG_DIR, f)) and base_pattern in f
                ]
                
                if target_files:
                    # Get the newest file (most likely the one being downloaded)
                    target_file = max(
                        target_files,
                        key=lambda f: os.path.getmtime(os.path.join(Config.LOG_DIR, f))
                    )  # Closing parenthesis for max()
                    current_size = os.path.getsize(os.path.join(Config.LOG_DIR, target_file))  # Removed extra parenthesis
                else:
                    current_size = 0

                # Check for stalled download
                if current_size == last_size:
                    stalled_count += 1
                    if stalled_count >= max_stalled:
                        scp_status["error"] = "Download stalled - no progress detected"
                        break
                else:
                    stalled_count = 0
                    last_size = current_size

                elapsed = time.time() - start_time
                rate = (current_size / elapsed) if elapsed > 0 else 0
                
                # Calculate progress (cap at 100%)
                percent = min(int((current_size / total_bytes) * 100), 100) if total_bytes > 0 else 0
                
                # Calculate ETA only if we're making progress
                eta = int((total_bytes - current_size) / rate) if rate > 0 and current_size < total_bytes else -1
                
                # Update progress state
                GlobalState.scp_progress = {
                    "percent": percent,
                    "eta": eta,
                    "eta_str": format_eta(eta),
                    "current_size": current_size,
                    "total_size": total_bytes,
                    "filename": target_file if target_files else None
                }
                
                print(f"📊 SCP Progress → {percent}% | ETA: {format_eta(eta)} | "
                      f"Size: {format_bytes(current_size)}/{format_bytes(total_bytes)} | "
                      f"Rate: {format_bytes(rate)}/s")
                
                await asyncio.sleep(1)

            # Handle completion
            if not GlobalState.scp_aborted and not scp_status["error"]:
                stdout, stderr = GlobalState.scp_proc.communicate()
                print(f"📦 SCP return code: {GlobalState.scp_proc.returncode}")
                print("📤 SCP stdout:", stdout.strip())
                print("📛 SCP stderr:", stderr.strip())

                if GlobalState.scp_proc.returncode == 0:
                    print("✅ SCP completed successfully.")
                    extract_compressed_files()
                    log_files = list_log_files() 
                    print(f"📋 Found {len(log_files)} log files after download")
                    if Config.PRELOAD_LARGE_FILES:
                        logger.info(f"⚡Preloading task TRIGGERED. (PRELOAD_LARGE_FILES=True)")
                        asyncio.create_task(async_preload_logs())
                    else:
                        logger.info(f"🔴 Preloading task HALTED. (PRELOAD_LARGE_FILES=False)")
                else:
                    if stderr.strip() == "":
                        print("⚠️ SCP ended with no error output but returned a non-zero exit code.")
                        log_files = list_log_files()
                        print(f"📋 Found {len(log_files)} log files after failed download")
                        if Config.PRELOAD_LARGE_FILES:
                            logger.info(f"⚡Preloading task TRIGGERED. (PRELOAD_LARGE_FILES=True)")
                            asyncio.create_task(async_preload_logs())
                        else:
                            logger.info(f"🔴 Preloading task HALTED. (PRELOAD_LARGE_FILES=False)")
                    else:
                        scp_status["error"] = f"SCP failed: {stderr.strip()}"

        except Exception as e:
            scp_status["error"] = f"Unexpected error: {str(e)}"
            print(f"❌ Unexpected error in SCP process: {str(e)}")
            traceback.print_exc()
        finally:
            GlobalState.scp_progress["percent"] = 100 if not scp_status["error"] else 0
            scp_status["done"] = True
            GlobalState.scp_proc = None
            GlobalState.scp_aborted = False

    # Create and run the SCP task
    asyncio.create_task(run_scp())

    # Wait for completion
    while not scp_status["done"]:
        await asyncio.sleep(1)

    if scp_status["error"]:
        return {"status": "error", "message": scp_status["error"]}
    return {"status": "success", "message": "Logs downloaded and processed successfully."}

@app.post("/abort_download")
async def abort_download():
    GlobalState.scp_aborted = True
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
    GlobalState.scp_aborted = True
    return {"status": "Abort requested"}

@app.post("/analyze_logs")
async def analyze_logs(request: Request):
    try:
        data = await request.json()
        mode = data.get("mode")
        specific_log = data.get("log")
        
        log_dir = Path(Config.LOG_DIR)
        error_counts = {"FATAL": 0, "ERROR": 0, "WARN": 0}
        error_details = []

        if mode == "all":
            log_files = [f for f in log_dir.iterdir() if f.is_file() and not is_compressed_file(f.name)]
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
                            level = None
                            for lvl in ["FATAL", "ERROR", "WARN"]:
                                if f"[{lvl}]" in line:
                                    level = lvl
                                    error_counts[level] += 1
                                    break

                            thread_match = re.findall(r"\[([^\[\]]*)\]", line)
                            thread_id = thread_match[1] if len(thread_match) > 1 else "N/A"

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

@app.get("/file_status/{filename}")
async def get_file_status(filename: str):
    status = await file_processor.get_status(filename)
    return {
        "filename": filename,
        "status": status.value,
        "is_ready": status == FileStatus.COMPLETE
    }

@app.get("/get_progress")
async def get_progress(filename: str) -> dict:
    """Check progress of background processing"""
    progress = progress_tracker.get_progress(filename)
    if not progress:
        raise HTTPException(404, detail="No such task or task completed")
    return {
        "status": "processing" if filename in file_processor.active_tasks else "ready",
        "filename": filename,
        "in_cache": filename in file_processor.results
    }

@app.get("/parse_progress")
async def get_parse_progress(log: str):
    """Check progress of parsing"""
    if log in progress_tracker.active_tasks:
        return progress_tracker.active_tasks[log]
    return {"status": "not_found"}

@app.get("/get_log_context")
async def get_log_context(log_file: str, line_number: int):
    log_path = Path(Config.LOG_DIR) / log_file

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
    log_path = Path(Config.LOG_DIR) / log

    if not log_path.exists() or not log_path.is_file():
        raise HTTPException(status_code=404, detail="Log file not found")

    context_lines = []

    try:
        with log_path.open("r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()

        start_index = max(0, line - 1)

        while start_index > 0:
            if re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2},", lines[start_index]):
                break
            start_index -= 1

        context_lines.append(lines[start_index].rstrip())

        for i in range(start_index + 1, len(lines)):
            if re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2},", lines[i]):
                break
            context_lines.append(lines[i].rstrip())

        return {"lines": context_lines}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/get_rqrs_content")
async def get_rqrs_content(log: str, line_number: int, tag: str):
    log_path = os.path.join(Config.LOG_DIR, log)
    if not os.path.exists(log_path):
        return JSONResponse({"error": "Log file not found"}, status_code=404)

    try:
        with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = [line.strip() for line in f.readlines()]
            
            # Convert to 0-based index
            line_idx = line_number - 1
            
            # Safety check
            if line_idx < 0 or line_idx >= len(lines):
                return JSONResponse(
                    {"error": f"Line number {line_number} out of range"},
                    status_code=400
                )
            
            # Get the XML content starting from the specified line
            xml_lines = []
            closing_tag = f"</{tag}>"
            found_closing = False
            
            # Search forward to find the complete XML content
            for i in range(line_idx, len(lines)):
                xml_lines.append(lines[i])
                if closing_tag in lines[i]:
                    found_closing = True
                    break
            
            if not found_closing:
                # If closing tag not found, search backward (for cases where XML might start before the marker)
                for i in range(line_idx - 1, -1, -1):
                    if f"<{tag}" in lines[i]:
                        # Found opening tag, now search forward from here
                        xml_lines = []
                        for j in range(i, len(lines)):
                            xml_lines.append(lines[j])
                            if closing_tag in lines[j]:
                                found_closing = True
                                break
                        if found_closing:
                            line_number = i + 1  # Update the line number to the actual start
                        break
            
            if not found_closing:
                return JSONResponse(
                    {"error": f"Closing tag {closing_tag} not found in the log file"},
                    status_code=400
                )
            
            full_xml = '\n'.join(xml_lines)
            
            # Verify the tag matches
            if not (full_xml.startswith(f"<{tag}") or not full_xml.endswith(f"</{tag}>")):
                return JSONResponse(
                    {"error": f"Invalid XML structure for tag {tag}"},
                    status_code=400
                )
            
            # Try to pretty-print the XML
            try:
                # First try with xml.etree.ElementTree
                parser = ET.XMLParser(encoding="utf-8")
                root = ET.fromstring(full_xml, parser=parser)
                ET.indent(root, space="  ", level=0)
                pretty_xml = ET.tostring(root, encoding="unicode", method="xml")
                
                return JSONResponse({
                    "pretty_xml": pretty_xml,
                    "raw_xml": full_xml,
                    "actual_start_line": line_number,
                    "actual_end_line": line_number + len(xml_lines) - 1,
                    "status": "success"
                })
            except ET.ParseError as e:
                # If ET fails, try with minidom as fallback
                try:
                    dom = minidom.parseString(full_xml)
                    pretty_xml = dom.toprettyxml(indent="  ")
                    return JSONResponse({
                        "pretty_xml": pretty_xml,
                        "raw_xml": full_xml,
                        "actual_start_line": line_number,
                        "actual_end_line": line_number + len(xml_lines) - 1,
                        "status": "success"
                    })
                except Exception as dom_error:
                    return JSONResponse({
                        "error": f"XML parsing failed with both parsers: {str(e)} and {str(dom_error)}",
                        "raw_xml": full_xml,
                        "status": "partial_success"
                    }, status_code=200)

    except Exception as e:
        logger.error(f"File processing failed: {str(e)}")
        return JSONResponse(
            {"error": f"File processing failed: {str(e)}"},
            status_code=500
        )

################################
# Search API Endpoints
################################
@app.post("/api/search_logs")
async def search_logs(req: SearchRequest):
    GlobalState.abort_event.clear()
    search_text = req.search_text
    search_mode = req.search_mode
    target_file = req.target_file

    start_time = time.time()
    GlobalState.status['search_active'] = True
    GlobalState.status['matches_found'] = 0
    GlobalState.status['files_scanned'] = 0

    results = []
    files_with_matches = set()

    try:
        if search_mode == 'all':
            files_to_search = [
                f for f in os.listdir(Config.LOG_DIR)
                if f.endswith('.log') and not is_compressed_file(f)
            ]
        elif search_mode == 'targeted' and target_file:
            files_to_search = [target_file]
        else:
            return {
                "status": "error",
                "message": "Invalid search mode or missing target file."
            }

        print(f"[Search Started] {time.ctime(start_time)} | Files: {files_to_search}")

        for fname in files_to_search:
            if GlobalState.abort_event.is_set():
                print("[Search Aborted by user]")
                break

            fpath = os.path.join(Config.LOG_DIR, fname)
            if not os.path.isfile(fpath):
                continue

            GlobalState.status['files_scanned'] += 1
            file_has_matches = False
            section_buffer = []
            last_timestamp_idx = -1
            current_thread = "UNKNOWN"
            current_service = "UNKNOWN"

            with open(fpath, 'r', encoding='utf-8', errors='ignore') as f:
                for idx, line in enumerate(f):
                    line = line.rstrip('\n')

                    if Patterns.TIMESTAMP.match(line):
                        last_timestamp_idx = idx
                        section_buffer = [line]
                        current_thread = extract_thread_id(line)
                        current_service = extract_service(line)
                    else:
                        section_buffer.append(line)

                    if re.search(re.escape(search_text), line, re.IGNORECASE):
                        if not file_has_matches:
                            files_with_matches.add(fname)
                            file_has_matches = True

                        snippet = line if Patterns.TIMESTAMP.match(line) else '\n'.join(section_buffer)

                        match_info = {
                            'log_file': fname,
                            'line_number': idx + 1,
                            'thread_id': current_thread,
                            'service': current_service,
                            'snippet': snippet
                        }
                        results.append(match_info)
                        GlobalState.status['matches_found'] += 1
                        print(f"[Match Found] {fname}:{idx + 1}")

        elapsed = time.time() - start_time
        print(f"[Search Completed] Files Scanned: {GlobalState.status['files_scanned']} | " +
              f"Files with Matches: {len(files_with_matches)} | " +
              f"Total Occurrences: {len(results)} | " +
              f"Time: {elapsed:.2f}s")

        return {
            "status": "aborted" if GlobalState.abort_event.is_set() else "completed",
            "files_scanned": GlobalState.status['files_scanned'],
            "file_matches": len(files_with_matches),
            "total_occurrences": len(results),
            "results": results,
            "elapsed_time": elapsed
        }

    finally:
        GlobalState.status['search_active'] = False
        GlobalState.abort_event.clear()

@app.post("/api/search_logs_stream")
async def search_logs_stream(req: SearchRequest):
    """Streaming search endpoint optimized for large log files"""
    GlobalState.abort_event.clear()  # Clear any previous abort state
    
    async def generate():
        try:
            search_text = req.search_text
            search_mode = req.search_mode
            target_file = req.target_file
            start_time = time.time()
            files_with_matches = set()
            total_files_scanned = 0
            total_occurrences = 0
            
            start_time_str = time.strftime("%H:%M:%S", time.localtime(start_time))
            print(f"\n[Search Started] {start_time_str} | Pattern: '{search_text}' | Mode: {search_mode}")

            # Get files to search
            if search_mode == 'all':
                files_to_search = [
                    f for f in os.listdir(Config.LOG_DIR)
                    if os.path.isfile(os.path.join(Config.LOG_DIR, f)) and
                    not any(f.lower().endswith(ext) for ext in Config.EXCLUDED_EXTENSIONS)
                ]
            elif search_mode == 'targeted' and target_file:
                files_to_search = [target_file]
            else:
                error_msg = "Invalid search mode or missing target file"
                print(f"[Search Failed] {error_msg}")
                yield 'data: {"error": "Invalid search mode or missing target file", "code": 400}\n\n'
                return

            # Process each file
            for fname in files_to_search:
                if GlobalState.abort_event.is_set():
                    print(f"[Search Aborted] User requested abort")
                    yield 'data: {"status": "aborted", "code": 499}\n\n'
                    GlobalState.abort_event.clear()  # Clear the abort flag
                    return  # Exit completely

                # Send current file being processed
                yield f'data: {{"current_file": "{fname}"}}\n\n'
                
                fpath = os.path.join(Config.LOG_DIR, fname)
                if not os.path.isfile(fpath):
                    continue

                total_files_scanned += 1
                file_has_matches = False  
                current_entry = []  # Buffer for current log entry
                current_thread = "UNKNOWN"
                current_service = "UNKNOWN"
                in_entry = False  # Flag to track if we're inside a log entry

                try:
                    with open(fpath, 'r', encoding='utf-8', errors='ignore') as f:
                        for line_idx, line in enumerate(f):
                            # Check abort flag more frequently
                            if line_idx % 10 == 0 and GlobalState.abort_event.is_set():
                                logger.info(f"🔴 [Search Aborted] During file processing")
                                yield 'data: {"status": "aborted", "code": 499}\n\n'
                                GlobalState.abort_event.clear()
                                return
                            
                            line = line.rstrip('\n')
                            
                            # Check for timestamp line (start of new entry)
                            if Patterns.TIMESTAMP.match(line):
                                # If we were in an entry and it had a match, send it
                                if in_entry and file_has_matches:
                                    snippet = '\n'.join(current_entry)
                                    data = {
                                        "log_file": fname,
                                        "line_number": line_idx + 1 - len(current_entry),  # Start line of entry
                                        "thread_id": current_thread,
                                        "service": current_service,
                                        "snippet": snippet
                                    }
                                    yield f'data: {json.dumps(data)}\n\n'
                                
                                # Start new entry
                                current_entry = [line]
                                in_entry = True
                                current_thread = extract_thread_id(line)
                                current_service = extract_service(line)
                                file_has_matches = False  # Reset for new entry
                            elif in_entry:
                                current_entry.append(line)
                            
                            # Check for search text match
                            if in_entry and re.search(re.escape(search_text), line, re.IGNORECASE):
                                if not file_has_matches:
                                    files_with_matches.add(fname)
                                    file_has_matches = True
                                    print(f"✅ [Match Found] File: {fname}")
                                total_occurrences += 1

                except Exception as e:
                    logger.error(f"🔴 [File Processing Error] {fname}: {str(e)}")
                    continue

            # Only send completion if not aborted
            if not GlobalState.abort_event.is_set():
                yield f'data: {{"files_scanned": {total_files_scanned}}}\n\n'
                elapsed = time.time() - start_time
                print(f"\n🔍 [Search Completed] {time.strftime('%H:%M:%S', time.localtime())}")
                print(f"  🔍 Files scanned: {total_files_scanned}")
                print(f"  📂 Files with matches: {len(files_with_matches)}")
                print(f"  ✔️ Total occurrences: {total_occurrences}")
                print(f"  🕒 Elapsed time: {elapsed:.2f} seconds")

                yield f'data: {json.dumps({"status": "complete", "code": 200, "files_scanned": total_files_scanned, "file_matches": len(files_with_matches), "total_occurrences": total_occurrences, "elapsed_time": round(elapsed, 2)})}\n\n'

        except Exception as e:
            print(f"[Search Error] {str(e)}")
            yield 'data: {"error": "Search processing failed", "code": 500}\n\n'
        finally:
            GlobalState.abort_event.clear()  # Ensure flag is cleared when done

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
    GlobalState.abort_event.set()
    return {"status": "abort signal sent"}
    
@app.get("/api/debug_search_status")
async def debug_search_status():
    return GlobalState.status

@app.get("/api/logs/list")
async def list_log_files_with_metadata():
    """
    List all log files with metadata (size, line count)
    This is the comprehensive version that was in the original code
    """
    try:
        logger.info("📂 Starting to scan log directory: %s", Config.LOG_DIR)
        start_time = datetime.now()
        log_files = []
        scanned_files = 0
        
        for file in Path(Config.LOG_DIR).iterdir():
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
                    logger.debug("🪵Found log file: %s (Size: %s, Lines: %s)", 
                               file.name, metadata['size'], metadata['lines'])
        
        duration = (datetime.now() - start_time).total_seconds()
        logger.info(
            "🔍📄 Completed directory scan. Files: %d (scanned %d). Time taken: %.2fs",
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
        logger.error("❌Failed to list log files: %s", str(e), exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/list_log_files")
async def list_log_files_simple():
    """
    Simplified version that just returns filenames
    This matches the simpler version I provided earlier
    """
    try:
        log_files = [
            f for f in os.listdir(Config.LOG_DIR)
            if os.path.isfile(os.path.join(Config.LOG_DIR, f)) and not is_compressed_file(f)
        ]
        return {"log_files": log_files}
    except Exception as e:
        logger.error(f"Failed to list log files: {e}")
        return {"log_files": []}
################################
# Cache Management Endpoints
################################
@app.get("/debug_rqrs_cache")
async def debug_rqrs_cache():
    return {
        "file_count": len(LOG_CACHE.cache),
        "sample_entry": list(LOG_CACHE.cache.items())[0] if LOG_CACHE.cache else None
    }

@app.get("/debug_cache")
async def debug_cache():
    return {
        "cache_contents": LOG_CACHE.cache,
        "cache_order": LOG_CACHE.order
    }

@app.get("/cache_status")
async def cache_status():
    """Check cache status"""
    return {
        "cached_logs": list(LOG_CACHE.cache.keys()),
        "cache_size": f"{len(LOG_CACHE.cache)}/{Config.MAX_CACHE_SIZE}",
        "next_to_evict": LOG_CACHE.order[0] if LOG_CACHE.order else None
    }

@app.post("/clear_cache")
async def clear_cache():
    """Clear the entire cache"""
    try:
        # Get count before clearing (for logging/reporting)
        keys_count = len(LOG_CACHE.cache)
        
        # Clear all cached items at once
        await LOG_CACHE.invalidate_all()
        
        logger.info(f"🧹 Cleared cache with {keys_count} items")
        return {
            "status": "Cache cleared", 
            "keys_cleared": keys_count,
            "message": f"Successfully cleared {keys_count} items from cache"
        }
    except Exception as e:
        logger.error(f"❌ Error clearing cache: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail={
                "error": "Cache clearance failed",
                "message": str(e)
            }
        )

@app.post("/refresh_cache")  # This requires a POST request
async def refresh_cache():
    """Manually trigger a full cache refresh"""
    files = [f for f in os.listdir(Config.LOG_DIR) if os.path.isfile(os.path.join(Config.LOG_DIR, f))]
    await asyncio.gather(*[file_processor.process_file(f, Priority.BACKGROUND_PRELOAD) for f in files])
    return {"status": "Cache refreshed", "files_processed": len(files)}

################################
# View Logs API Endpoints
################################

@app.get("/api/logs/stream")
async def stream_log_file(filename: str, request: Request):
    """Stream log file content as NDJSON with optimizations for virtual scrolling"""
    file_path = Path(Config.LOG_DIR) / filename
    
    # Validate file exists and is accessible
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    
    if is_compressed_file(filename):
        raise HTTPException(status_code=400, detail="Compressed files are not supported")

    async def generate():
        total_lines = 0
        chunk_size = 50000  # Increased chunk size for better performance
        chunk = []
        line_count = 0
        
        # Get approximate line count first (for progress reporting)
        async with aiofiles.open(file_path, mode='r', encoding='utf-8', errors='ignore') as f:
            # First send metadata with estimated line count if possible
            yield json.dumps({
                "filename": filename,
                "size": file_path.stat().st_size,
                "timestamp": datetime.now().isoformat(),
                "type": "metadata",
                "estimated_lines": await estimate_line_count(f) if file_path.stat().st_size > 0 else 0
            }) + "\n\n"
            
            # Rewind file
            await f.seek(0)
            
            # Stream lines
            async for line in f:
                if request.client is None:  # Client disconnected
                    break
                    
                chunk.append(line.rstrip())  # Use rstrip() instead of strip() to preserve indentation
                line_count += 1
                
                if len(chunk) >= chunk_size:
                    yield json.dumps({
                        "lines": chunk,
                        "total_lines": line_count,
                        "type": "chunk"
                    }) + "\n\n"
                    chunk = []
            
            # Send remaining lines
            if chunk and request.client is not None:
                yield json.dumps({
                    "lines": chunk,
                    "total_lines": line_count,
                    "type": "chunk"
                }) + "\n\n"

    return StreamingResponse(
        generate(),
        media_type="application/x-ndjson",
        headers={
            "X-Accel-Buffering": "no",  # Disable buffering for nginx if used
            "Cache-Control": "no-store"  # Prevent caching of log data
        }
    )

async def estimate_line_count(file_handle):
    """Estimate line count by sampling beginning and end of file"""
    try:
        # Read first 10k and last 10k bytes to estimate line density
        file_size = (await file_handle.seek(0, 2))  # Seek to end to get size
        sample_size = min(10000, file_size)
        
        # Sample beginning
        await file_handle.seek(0)
        start_sample = await file_handle.read(sample_size)
        start_lines = start_sample.count('\n')
        
        # Sample end
        if file_size > sample_size:
            await file_handle.seek(-sample_size, 2)
            end_sample = await file_handle.read(sample_size)
            end_lines = end_sample.count('\n')
        else:
            end_lines = start_lines
            
        # Calculate average lines per sample
        avg_lines = (start_lines + end_lines) / 2
        estimated_total = int((file_size / sample_size) * avg_lines)
        return max(estimated_total, 1)
    except:
        return 0

################################
# Monitoring Helper Functions
################################
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

################################
# Monitoring Endpoints
################################
@app.get("/metrics")
async def show_metrics():
    return GlobalState.endpoint_metrics

@app.get("/light")
async def light_endpoint():
    return {"message": "Light endpoint"}

@app.get("/heavy")
async def heavy_endpoint():
    big_list = [i for i in range(1_000_000)]
    return {"message": "Heavy endpoint"}

@app.get("/memory-stream")
async def memory_stream():
    """Stream comprehensive system and process metrics"""
    async def event_generator():
        while True:
            sys_mem = psutil.virtual_memory()
            sys_swap = psutil.swap_memory()
            sys_cpu = psutil.cpu_percent(interval=1, percpu=True)
            sys_cpu_avg = sum(sys_cpu) / len(sys_cpu) if sys_cpu else 0
            sys_disk = psutil.disk_usage('/')
            sys_net = psutil.net_io_counters()
            sys_temp = psutil.sensors_temperatures() if hasattr(psutil, 'sensors_temperatures') else {}
            sys_battery = psutil.sensors_battery() if hasattr(psutil, 'sensors_battery') else None
            
            processes = find_all_processes()
            current_process = get_process_info(os.getpid())
            
            data = {
                "timestamp": time.time(),
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
            await asyncio.sleep(1)
    
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
################################
# AI Modules
################################

@app.post("/ai/inspect_log")
async def ai_inspect_log(req: Request):
    """
    Endpoint that runs AI analysis on a selected log file.
    Also logs user behavior for future ML personalization.
    """
    data = await req.json()
    log_name = data.get("log")

    # ❌ Guard clause: no log name sent
    if not log_name:
        raise HTTPException(status_code=400, detail="Missing log name")

    # ❌ Guard clause: file not found in ./logs
    filepath = os.path.join(Config.LOG_DIR, log_name)
    if not os.path.isfile(filepath):
        raise HTTPException(status_code=404, detail="Log file not found")

    try:
        # ✅ Read full log file (streamed)
        async with aiofiles.open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            log_content = await f.read()

        # ✅ Run the AI analyzer on the log content
        result = analyze_log_content(log_content)

        # ✅ NEW: Log user behavior — what log they analyzed
        log_user_action("ai_analysis", {
            "log_file": log_name
        })

        return result

    except Exception as e:
        logger.error(f"AI inspection failed: {str(e)}")
        raise HTTPException(status_code=500, detail="AI analysis failed")
        
@app.post("/ai/log_action")
async def ai_log_action(req: Request):
    """
    Generic endpoint for front-end to log user behavior (searches, views, etc).
    """
    try:
        data = await req.json()
        action = data.get("action")
        metadata = data.get("details", {})
        if not action:
            raise HTTPException(status_code=400, detail="Missing 'action'")
        
        log_user_action(action, metadata)
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"AI behavior log failed: {e}")
        raise HTTPException(status_code=500, detail="Logging failed")

########################################################
# Starting FastAPI server in port 8001 by default
########################################################
# Commands during:
# Development 
#     python3 -m uvicorn main:app --host 0.0.0.0 --port 8001 --reload
# Production:
#     python3 -m uvicorn main:app --host 0.0.0.0 --port 8001
# or
#     python3 python3 main.py
########################################################
port = int(os.getenv("FASTAPI_PORT", 8001))
if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        # reload=True, # Enable only during development
        workers=1,
        access_log=False  # Disables duplicate request logs
    )