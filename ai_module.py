# ✅ ai_module.py — AI Assistant backend logic

import re
from collections import Counter
from typing import Dict, Any
import Levenshtein

# 🔍 Basic regex patterns to reuse from main app
ERROR_PATTERN = re.compile(r'\[(ERROR|WARN|FATAL)\]')
THREAD_PATTERN = re.compile(r'\[(NDC_[^\]]+?)\]')
SERVICE_PATTERN = re.compile(r'\[(com\.datalex\..+?)\]')

# ✅ Main AI analysis function
def analyze_log_content(log_text: str) -> Dict[str, Any]:
    """
    Analyze the given log content and return AI-generated insights.
    Includes: error counts, service names, Levenshtein similarity, anomalies.
    """
    lines = log_text.splitlines()
    level_counter = Counter()
    thread_counter = Counter()
    service_counter = Counter()
    error_services_counter = Counter()  # ✅ NEW: Track services in error lines
    error_lines = []  # ✅ Preserve for Levenshtein

    for i, line in enumerate(lines):
        # ✅ Count log levels
        level_match = ERROR_PATTERN.search(line)
        if level_match:
            level = level_match.group(1)
            level_counter[level] += 1
            error_lines.append((i + 1, line))  # For Levenshtein

            # ✅ Track services that failed
            service_match = SERVICE_PATTERN.search(line)
            if service_match:
                service = service_match.group(1).split('.')[-1]
                error_services_counter[service] += 1

        # ✅ Count threads
        thread_match = THREAD_PATTERN.search(line)
        if thread_match:
            thread_counter[thread_match.group(1)] += 1

        # ✅ Count all services (not just error ones)
        service_match = SERVICE_PATTERN.search(line)
        if service_match:
            service = service_match.group(1).split('.')[-1]
            service_counter[service] += 1

    # ✅ Top summaries
    top_threads = thread_counter.most_common(3)
    top_services = service_counter.most_common(3)
    top_error_services = error_services_counter.most_common(5)

    # ✅ Start building anomaly list
    anomalies = []

    if level_counter["FATAL"] > 0:
        anomalies.append("⚠️ FATAL errors detected — critical issue present.")
    if level_counter["ERROR"] > 10:
        anomalies.append("📌 High volume of ERRORs — investigate root cause.")
    if len(top_threads) == 1 and top_threads[0][1] > 5:
        anomalies.append(f"🧵 Thread '{top_threads[0][0]}' may be problematic (appears {top_threads[0][1]} times).")

    # ✅ NEW: Repeating errors based on Levenshtein
    similar_count = detect_similar_errors(error_lines, threshold=0.85)
    if similar_count >= 3:
        anomalies.append(f"🔁 {similar_count} repeating error lines (≥85% match) — possible retry loop.")

    # ✅ NEW: Failing services based on ERROR/FATAL
    if top_error_services:
        summary = ", ".join([f"{name} ({count})" for name, count in top_error_services])
        anomalies.append(f"🛠️ Services with most errors: {summary}")

    # ✅ Return structured insights
    return {
        "summary": f"Total lines: {len(lines)}\nLog Levels: {dict(level_counter)}",
        "top_threads": top_threads,
        "top_services": top_services,
        "anomalies": anomalies,
        "recommendations": [
            "Check services with highest errors",
            "Focus on most active thread IDs",
            "Use the Raw Logs viewer to inspect context"
        ]
    }

# ✅ Helper function to detect similar error lines using Levenshtein distance
def detect_similar_errors(error_lines: list, threshold: float = 0.85) -> int:
    """
    Detect how many lines are similar to each other using Levenshtein ratio.
    - Only compares [ERROR], [WARN], [FATAL] lines.
    - Returns how many lines were part of ≥85% match groups.
    """
    matched_indices = set()
    count = 0

    for i, (line_num_i, line_i) in enumerate(error_lines):
        for j in range(i + 1, len(error_lines)):
            if j in matched_indices:
                continue  # Skip already matched

            line_j = error_lines[j][1]
            similarity = Levenshtein.ratio(line_i, line_j)

            if similarity >= threshold:
                matched_indices.update({i, j})  # Save both
                count += 1
                break  # Stop comparing line_i with more

    return count
