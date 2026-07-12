#!/usr/bin/env python3
"""Build a single binary using PyInstaller.

Usage:
    python build_binary.py
"""
import os
import subprocess
import sys


def main():
    repo_root = os.path.abspath(os.path.dirname(__file__))
    src_crb = os.path.join(repo_root, "src", "crb")
    separator = ";" if sys.platform == "win32" else ":"
    subprocess.check_call([
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--name", "crb",
        "--distpath", os.path.join(repo_root, "dist"),
        "--workpath", os.path.join(repo_root, "build", "pyinstaller"),
        "--specpath", os.path.join(repo_root, "build"),
        "--add-data", f"{src_crb}{separator}crb",
        os.path.join(src_crb, "__main__.py"),
    ])
    print(f"\nBinary built: {os.path.join(repo_root, 'dist', 'crb')}")


if __name__ == "__main__":
    main()
