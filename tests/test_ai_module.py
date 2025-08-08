import os
import sys

import pytest

# Ensure the repository root is on sys.path for direct script execution
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from ai_module import detect_similar_errors


def test_detect_similar_errors_counts_duplicates():
    """Two identical error lines and one distinct should count as one."""
    error_lines = [
        (1, "[ERROR] Something went wrong"),
        (2, "[ERROR] Something went wrong"),
        (3, "[ERROR] Different issue"),
    ]

    assert detect_similar_errors(error_lines) == 1


def test_detect_similar_errors_no_similar_lines():
    """Non-similar error lines should not be counted."""
    error_lines = [
        (1, "[ERROR] First unique issue"),
        (2, "[ERROR] Second unique issue"),
        (3, "[ERROR] Third unique problem"),
    ]

    assert detect_similar_errors(error_lines) == 0
