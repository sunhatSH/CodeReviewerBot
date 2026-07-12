#!/usr/bin/env python3
"""Build crb binaries for Linux distros using Docker cross-compilation.

Requires Docker Desktop (or Docker daemon) to be running.

Usage:
    python build_linux.py
"""

import os
import shutil
import subprocess
import sys
import tempfile

REPO_ROOT = os.path.abspath(os.path.dirname(__file__))
DIST_DIR = os.path.join(REPO_ROOT, "dist")
BUILD_DIR = os.path.join(REPO_ROOT, "build", "linux")

DOCKERFILE_APT = r"""FROM {image}

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

COPY src/ /build/src/
COPY pyproject.toml /build/

RUN python3 -m venv /build/venv && \
    . /build/venv/bin/activate && \
    pip install . pyinstaller --no-build-isolation

RUN . /build/venv/bin/activate && \
    pyinstaller --onefile \
        --name crb \
        --distpath /build/dist \
        --workpath /build/work \
        --specpath /build/spec \
        --add-data src/crb:crb \
        src/crb/__main__.py
"""

DOCKERFILE_DNF = r"""FROM {image}

RUN dnf install -y python3 python3-pip && \
    dnf clean all

WORKDIR /build

COPY src/ /build/src/
COPY pyproject.toml /build/

RUN python3 -m venv /build/venv && \
    . /build/venv/bin/activate && \
    pip install . pyinstaller --no-build-isolation

RUN . /build/venv/bin/activate && \
    pyinstaller --onefile \
        --name crb \
        --distpath /build/dist \
        --workpath /build/work \
        --specpath /build/spec \
        --add-data src/crb:crb \
        src/crb/__main__.py
"""

TARGETS = [
    {
        "name": "ubuntu",
        "image": "ubuntu:22.04",
        "binary": "crb-ubuntu",
        "dockerfile": DOCKERFILE_APT,
    },
    {
        "name": "debian",
        "image": "debian:bookworm-slim",
        "binary": "crb-debian",
        "dockerfile": DOCKERFILE_APT,
    },
    {
        "name": "centos",
        "image": "centos:stream9",
        "binary": "crb-centos",
        "dockerfile": DOCKERFILE_DNF,
    },
]


def _build_for_target(target: dict) -> str:
    """Build crb binary for a single Linux distro target.

    Returns the path to the built binary.
    """
    name = target["name"]
    image = target["image"]
    binary_name = target["binary"]
    dockerfile_template = target["dockerfile"]

    print(f"\n{'='*60}")
    print(f"Building for {name} ({image})...")
    print(f"{'='*60}")

    with tempfile.TemporaryDirectory(prefix=f"crb-docker-{name}-") as tmpdir:
        # Write Dockerfile
        dockerfile = dockerfile_template.format(image=image)
        dockerfile_path = os.path.join(tmpdir, "Dockerfile")
        with open(dockerfile_path, "w") as f:
            f.write(dockerfile)

        # Copy project files needed for build
        src_dst = os.path.join(tmpdir, "src")
        shutil.copytree(os.path.join(REPO_ROOT, "src"), src_dst)
        shutil.copy2(
            os.path.join(REPO_ROOT, "pyproject.toml"),
            os.path.join(tmpdir, "pyproject.toml"),
        )

        # Build Docker image
        tag = f"crb-builder-{name}:latest"
        print(f"\nBuilding Docker image {tag}...")
        subprocess.check_call(
            ["docker", "build", "-t", tag, "-f", dockerfile_path, tmpdir],
            stdout=sys.stdout,
            stderr=sys.stderr,
        )

        # Create a container and extract the binary
        print(f"\nExtracting binary from {name} container...")
        container_id = subprocess.check_output(
            ["docker", "create", tag], text=True,
        ).strip()

        try:
            subprocess.check_call(
                [
                    "docker", "cp",
                    f"{container_id}:/build/dist/crb",
                    os.path.join(DIST_DIR, binary_name),
                ],
                stdout=sys.stdout,
                stderr=sys.stderr,
            )
        finally:
            subprocess.check_call(
                ["docker", "rm", container_id],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

        # Clean up image after extraction
        subprocess.check_call(
            ["docker", "rmi", tag],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    output_path = os.path.join(DIST_DIR, binary_name)
    print(f"  -> {output_path}")
    return output_path


def main():
    os.makedirs(DIST_DIR, exist_ok=True)
    os.makedirs(BUILD_DIR, exist_ok=True)

    built = []
    for target in TARGETS:
        try:
            path = _build_for_target(target)
            built.append(path)
        except subprocess.CalledProcessError as e:
            print(f"ERROR: Build failed for {target['name']}: {e}", file=sys.stderr)

    print(f"\n{'='*60}")
    print(f"Build complete. {len(built)}/{len(TARGETS)} binaries built:")
    for p in built:
        size = os.path.getsize(p)
        print(f"  {p}  ({size / 1024 / 1024:.1f} MB)")


if __name__ == "__main__":
    main()
