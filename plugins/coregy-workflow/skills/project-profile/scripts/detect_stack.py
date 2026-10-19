#!/usr/bin/env python3
"""
Auto-detect project tech stack from config files.
Outputs .coregy/profile.yaml with detected stack info.

This is a backward-compatible wrapper. All logic lives in detectors/ package.
"""
from detectors import build_profile, to_yaml, load_existing_integrations
from detectors.serializer import main

if __name__ == "__main__":
    main()
