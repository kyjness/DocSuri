# Copyright (c) 2026 AIDLC Design Reviewer Contributors
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.


"""
ArtifactLoader — eager file loading with progress bar and credential scrubbing at export.

Loads all artifact file contents into memory. Individual failures are advisory (logged
and skipped); all-failure is fatal (MissingArtifactError).

Credential scrubbing is applied to the Dict[Path, str] export only — ArtifactInfo.content
retains the raw unmodified content.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Tuple

from charset_normalizer import from_path as detect_encoding

from design_reviewer.foundation.exceptions import MissingArtifactError
from design_reviewer.foundation.logger import Logger
from design_reviewer.foundation.progress import progress_bar
from design_reviewer.validation.models import ArtifactInfo


# Generic catch-all from Logger.CREDENTIAL_PATTERNS that must NOT run over document
# content: it matches any 40-char [A-Za-z0-9/+=] run, so it redacts non-secret tokens
# (sha/hex IDs, long identifiers) into ***REDACTED_SECRET***, which the AI then reports
# as a leaked-secret finding. Excluded here; logs keep it (ephemeral, over-redaction is
# harmless there). See operations/code-reviews/2026-06-28/designreview-audit.md (H1).
_GENERIC_SECRET_PATTERN = r"[A-Za-z0-9/+=]{40}"

# High-precision secret shapes only — safe to apply to content fed to the reviewer.
CONTENT_CREDENTIAL_PATTERNS = [
    (pat, repl)
    for pat, repl in Logger.CREDENTIAL_PATTERNS
    if pat != _GENERIC_SECRET_PATTERN
]


def scrub_credentials(content: str) -> str:
    """Scrub real secret shapes from document content (no generic 40-char heuristic)."""
    scrubbed = content
    for pattern, replacement in CONTENT_CREDENTIAL_PATTERNS:
        scrubbed = re.sub(pattern, replacement, scrubbed)
    return scrubbed


class ArtifactLoader:
    """
    Eagerly loads all artifact file contents in a single batch.

    Returns both a rich typed list (ArtifactInfo with content) and a simple
    path-to-scrubbed-content dict for downstream parsers (Unit 3).
    """

    def __init__(self, logger: Logger) -> None:
        self._logger = logger

    def load_multiple_artifacts(
        self, artifact_infos: List[ArtifactInfo]
    ) -> Tuple[List[ArtifactInfo], Dict[Path, str]]:
        """
        Load all artifact files eagerly with a progress bar.

        Credential scrubbing is applied to the Dict[Path, str] export.
        ArtifactInfo.content retains raw content.

        Args:
            artifact_infos: List of ArtifactInfo from ValidationResult (no content).

        Returns:
            Tuple of:
              - List[ArtifactInfo]: Successfully loaded artifacts with raw content.
              - Dict[Path, str]: Path → scrubbed content for downstream parsers.

        Raises:
            MissingArtifactError: If ALL files fail to load.
        """
        loaded_artifacts: List[ArtifactInfo] = []
        path_content_map: Dict[Path, str] = {}
        failed_paths: List[Path] = []

        self._logger.info(f"Loading {len(artifact_infos)} artifact files...")

        with progress_bar(
            total=len(artifact_infos), description="Loading design artifacts"
        ) as progress:
            for artifact in artifact_infos:
                try:
                    raw_content = self._read_file(artifact.path)
                    loaded_artifact = artifact.with_content(raw_content)
                    scrubbed = self._scrub_credentials(raw_content)
                    loaded_artifacts.append(loaded_artifact)
                    path_content_map[artifact.path] = scrubbed
                except Exception as exc:
                    self._logger.warning(
                        f"Failed to load {artifact.artifact_type.value} artifact: "
                        f"{artifact.path} "
                        f"({type(exc).__name__}: {exc})"
                    )
                    failed_paths.append(artifact.path)
                finally:
                    progress.advance()

        if not loaded_artifacts:
            raise MissingArtifactError(
                f"All {len(artifact_infos)} artifact files failed to load",
                context={
                    "file_path": None,
                    "error_type": "AllArtifactsFailedToLoad",
                    "artifact_type": None,
                    "original_message": (
                        f"{len(artifact_infos)} files attempted, 0 loaded successfully"
                    ),
                },
            )

        if failed_paths:
            self._logger.warning(
                f"{len(failed_paths)} artifact(s) failed to load and were skipped: "
                + ", ".join(str(p.name) for p in failed_paths)
            )

        self._logger.info(
            f"Loading complete: {len(loaded_artifacts)} loaded, "
            f"{len(failed_paths)} skipped"
        )
        return loaded_artifacts, path_content_map

    def _scrub_credentials(self, content: str) -> str:
        """Delegate to module-level scrub_credentials function."""
        return scrub_credentials(content)

    def _read_file(self, path: Path) -> str:
        """
        Read file as UTF-8; fall back to charset-normalizer on decode error.

        Raises:
            OSError: File not found or permission denied.
            MissingArtifactError: If encoding detection also fails.
        """
        try:
            return path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            self._logger.debug(
                f"UTF-8 decode failed for {path.name}, attempting encoding detection"
            )
            result = detect_encoding(path).best()
            if result is None:
                raise MissingArtifactError(
                    f"Could not determine encoding for: {path}",
                    context={
                        "file_path": str(path),
                        "error_type": "EncodingDetectionFailed",
                        "artifact_type": None,
                        "original_message": "charset-normalizer could not detect encoding",
                    },
                )
            return str(result)
