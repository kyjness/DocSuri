"""AIDLC Code Reviewer — automated, language-agnostic code quality analysis."""

# Copyright 2026 Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

from pathlib import Path

# Project root: scripts/aidlc-codereview/
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# Config directory: scripts/aidlc-codereview/config/
CONFIG_DIR = PROJECT_ROOT / "config"
