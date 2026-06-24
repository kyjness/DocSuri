"""Language detection by scanning file extensions in a target directory."""

# Copyright 2026 Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

from __future__ import annotations

from pathlib import Path

EXTENSION_MAP: dict[str, str] = {
    ".py": "python",
    ".java": "java",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
    ".rb": "ruby",
    ".rs": "rust",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".c": "c",
    ".h": "c",
    ".hpp": "cpp",
    ".cs": "csharp",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".swift": "swift",
    ".scala": "scala",
    ".php": "php",
    ".r": "r",
    ".R": "r",
    ".sh": "shell",
    ".bash": "shell",
}


def detect_languages(target: Path) -> set[str]:
    """Scan a target path and return the set of detected programming languages.

    If target is a file, detects from that single file's extension.
    If target is a directory, recursively scans all files.
    """
    detected: set[str] = set()

    if target.is_file():
        lang = EXTENSION_MAP.get(target.suffix.lower())
        if lang:
            detected.add(lang)
        return detected

    for file_path in target.rglob("*"):
        if file_path.is_file():
            lang = EXTENSION_MAP.get(file_path.suffix.lower())
            if lang:
                detected.add(lang)

    return detected
