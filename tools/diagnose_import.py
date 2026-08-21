#!/usr/bin/env python3
"""Diagnose the import error in dashboard.py"""
import sys
from pathlib import Path

# Check the actual import in dashboard.py
dashboard_path = Path('/workspaces/Dashboard-demo/dashboard.py')
if dashboard_path.exists():
    content = dashboard_path.read_text()
    # Look for the pyximport or import section that might have issues
    lines = content.split('\n')
    for i, line in enumerate(lines[:120], 1):
        print(f"{i:4d}: {line}")
        