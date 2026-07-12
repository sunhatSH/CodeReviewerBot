#!/usr/bin/env python3
"""Build script for CodeReviewerBot single binary.

Usage:
    python scripts/build.py           # Build for current platform
    python scripts/build.py --clean   # Clean build artifacts first
"""
import argparse
import os
import shutil
import subprocess
import sys

# Paths relative to project root
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST_DIR = os.path.join(PROJECT_ROOT, "dist")
BUILD_DIR = os.path.join(PROJECT_ROOT, "build")
SPEC_FILE = os.path.join(PROJECT_ROOT, "crb.spec")
VENV_PYTHON = os.path.join(PROJECT_ROOT, ".venv", "bin", "python3")


def clean():
    """Remove build artifacts."""
    for path in [DIST_DIR, BUILD_DIR]:
        if os.path.exists(path):
            shutil.rmtree(path)
            print(f"  Removed: {path}")
    if os.path.exists(SPEC_FILE):
        os.remove(SPEC_FILE)
        print(f"  Removed: {SPEC_FILE}")


def build():
    """Build single binary with PyInstaller."""
    python = VENV_PYTHON if os.path.exists(VENV_PYTHON) else sys.executable

    # Ensure dependencies
    subprocess.check_call(
        [python, "-m", "pip", "install", "pyinstaller"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Build
    result = subprocess.run(
        [
            python, "-m", "PyInstaller",
            "--onefile",
            "--name", "crb",
            "--distpath", DIST_DIR,
            "--workpath", os.path.join(BUILD_DIR, "pyinstaller"),
            "--specpath", BUILD_DIR,
            "--clean",
            "--noconfirm",
            os.path.join(PROJECT_ROOT, "src", "crb", "__main__.py"),
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        print("Build failed:")
        print(result.stdout)
        print(result.stderr)
        sys.exit(1)

    # Verify binary
    binary = os.path.join(DIST_DIR, "crb")
    if os.path.exists(binary):
        size = os.path.getsize(binary)
        print(f"Binary: {binary}")
        print(f"Size:   {size / 1024 / 1024:.1f} MB")
        print(f"Type:  {subprocess.check_output(['file', binary]).decode().strip()}")
    else:
        print("Error: binary not found!")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Build CodeReviewerBot binary")
    parser.add_argument("--clean", action="store_true", help="Clean build artifacts before building")
    args = parser.parse_args()

    os.chdir(PROJECT_ROOT)

    if args.clean:
        print("Cleaning build artifacts...")
        clean()

    print("Building CodeReviewerBot...")
    build()
    print("Done.")


if __name__ == "__main__":
    main()
