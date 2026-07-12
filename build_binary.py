#!/usr/bin/env python3
"""Build a single binary using PyInstaller.

Usage:
    python build_binary.py
"""
import subprocess
import sys


def main():
    subprocess.check_call([
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--name", "crb",
        "--distpath", "dist",
        "--workpath", "build/pyinstaller",
        "--specpath", "build",
        "--add-data", "src/crb:crb",
        "src/crb/__main__.py",
    ])
    print("\nBinary built: dist/crb")


if __name__ == "__main__":
    main()
