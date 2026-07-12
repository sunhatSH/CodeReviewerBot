"""CLI entry point for CodeReviewerBot.

Usage:
    crb review <paths>              # Auto-detect language, review all
    crb review --lang python <path> # Explicitly specify language
    crb list-langs                  # List supported languages
    crb list-sort-presets           # List sort order options
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import click

from crb.config.settings import AppConfig, LLMConfig
from crb.llm.client import LLMError, chat
from crb.report.models import ReviewReport, Severity

_PRESET_SORT_ORDERS = {
    "default": [Severity.BLOCKER, Severity.CRITICAL, Severity.MAJOR],
    "severity-up": [Severity.MAJOR, Severity.CRITICAL, Severity.BLOCKER],
    "critical-first": [Severity.CRITICAL, Severity.BLOCKER, Severity.MAJOR],
}


def _resolve_sort_order(sort: str) -> list[Severity]:
    if sort in _PRESET_SORT_ORDERS:
        return _PRESET_SORT_ORDERS[sort]
    try:
        return [Severity[s.upper().strip()] for s in sort.split(",")]
    except (KeyError, ValueError):
        click.echo(f"Warning: invalid sort order '{sort}', using default.", err=True)
        return _PRESET_SORT_ORDERS["default"]


def _run_analyzer(
    lang: str, files: list[str], config: AppConfig, sort_order: list[Severity], output_lang: str
) -> ReviewReport:
    """Dispatch to the appropriate language analyzer."""
    if lang == "python":
        from crb.analyzers.python.reporter import analyze_files
        return analyze_files(files, config=config, sort_order=sort_order, output_lang=output_lang)
    elif lang == "c_cpp":
        from crb.analyzers.c_cpp.reporter import analyze_files
        return analyze_files(files, config=config, sort_order=sort_order, output_lang=output_lang)
    elif lang == "go":
        from crb.analyzers.go.reporter import analyze_files
        return analyze_files(files, config=config, sort_order=sort_order, output_lang=output_lang)
    elif lang == "rust":
        from crb.analyzers.rust.reporter import analyze_files
        return analyze_files(files, config=config, sort_order=sort_order, output_lang=output_lang)
    else:
        raise ValueError(f"Unsupported language: {lang}")


def _write_report(
    report: ReviewReport,
    report_dir: str,
    project_name: str,
    output_format: str,
) -> None:
    """Write report to disk."""
    report_path = Path(report_dir) / f"{project_name}_report.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)

    if output_format == "markdown":
        content = report.to_markdown()
        report_path.write_text(content, encoding="utf-8")
    else:
        json_path = report_path.with_suffix(".json")
        data = {
            "target": report.target,
            "blocker": report.blocker_count,
            "critical": report.critical_count,
            "major": report.major_count,
            "findings": [f.to_dict() for f in report.findings],
        }
        json_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        click.echo(f"Report written to {json_path}")
        return

    click.echo(f"Report written to {report_path}")
    click.echo(
        f"Summary: {report.blocker_count} Blocker, "
        f"{report.critical_count} Critical, "
        f"{report.major_count} Major"
    )


# ---------------------------------------------------------------------------
# CLI commands
# ---------------------------------------------------------------------------


@click.group()
def cli() -> None:
    """CodeReviewerBot — AI-powered code review."""


@cli.command()
@click.argument("paths", nargs=-1, required=True)
@click.option("--lang", "-l", default=None, help="Language override: python, c_cpp, go, rust")
@click.option(
    "--sort", default="default",
    help="Sort order. Presets: default, severity-up, critical-first. Or custom: 'Blocker,Critical,Major'.",
)
@click.option("--output", "-o", type=click.Choice(["markdown", "json"]), default="markdown")
@click.option("--report-dir", default="report")
@click.option(
    "--output-lang", type=click.Choice(["ch", "en", "ch_en"]), default="ch",
    help="Report language: ch (Chinese), en (English), ch_en (bilingual).",
)
def review(paths, lang, sort, output, report_dir, output_lang):
    """Review source code in PATHS (files or directories).

    Detects language automatically from file extensions unless --lang is given.
    """
    from crb.analyzers.detector import Lang, detect

    # Load LLM config from environment
    llm_config = LLMConfig.from_env()
    config = AppConfig(report_dir=report_dir, llm=llm_config)

    # Validate LLM config — required for analysis
    if not llm_config.is_valid():
        click.echo("Error: LLM not configured.", err=True)
        click.echo("  Set the following environment variables:", err=True)
        click.echo("    CRB_LLM_API_URL   (e.g. https://api.openai.com/v1)", err=True)
        click.echo("    CRB_LLM_API_KEY   (your API key)", err=True)
        click.echo("  Optional:", err=True)
        click.echo("    CRB_LLM_MODEL     (default: gpt-4o)", err=True)
        click.echo("  Or run:  crb doctor  to diagnose.", err=True)
        sys.exit(1)

    sort_order = _resolve_sort_order(sort)

    # Resolve all paths
    resolved = []
    for p in paths:
        rp = str(Path(p).resolve())
        if not os.path.exists(rp):
            click.echo(f"Warning: path not found: {p}", err=True)
            continue
        resolved.append(rp)

    if not resolved:
        click.echo("No valid paths provided.", err=True)
        sys.exit(1)

    # Detect or override language
    detection = detect(resolved)

    if lang:
        # Explicit language override
        target_langs = [lang]
    else:
        target_langs = detection.detected_langs
        if not target_langs:
            click.echo("No supported source files found.", err=True)
            click.echo("Supported: .py, .c/.h/.cpp/.hpp, .go, .rs", err=True)
            # Still print what we found
            if detection.lang_counts.get(Lang.UNKNOWN, 0) > 0:
                click.echo(f"  ({detection.lang_counts[Lang.UNKNOWN]} unsupported files skipped)", err=True)
            sys.exit(1)

    click.echo(f"Detected: {', '.join(detection.label(lang) for lang in target_langs)}")

    # Derive project name from first resolved path
    first = resolved[0]
    project_name = os.path.basename(os.path.dirname(first)) if os.path.isfile(first) else os.path.basename(first)
    if not project_name or project_name == ".":
        project_name = os.path.basename(os.getcwd())

    # Find project root (directory containing .git) for file tree
    project_root: str | None = None
    candidate = Path(resolved[0])
    if candidate.is_file():
        candidate = candidate.parent
    for parent in [candidate] + list(candidate.parents):
        if (parent / ".git").exists():
            project_root = str(parent)
            break
    if not project_root and os.path.isdir(resolved[0]):
        project_root = resolved[0]

    # Collect all project files for the file tree overview
    all_project_files: list[str] = []
    if project_root:
        root_path = Path(project_root)
        for f in sorted(root_path.rglob("*")):
            if f.is_file() and not any(
                part.startswith(".") or part == "archived" or part == "__pycache__"
                or part == "build" or part == "node_modules"
                for part in f.parts
            ):
                all_project_files.append(str(f))

    for target_lang in target_langs:
        lang_files = detection.files.get(target_lang, [])
        if not lang_files:
            continue

        click.echo(f"Analyzing {len(lang_files)} {detection.label(target_lang)} file(s)...")
        report = _run_analyzer(target_lang, lang_files, config, sort_order, output_lang)
        report.all_files = all_project_files
        _write_report(report, report_dir, project_name, output)

    # Cross-language security scan (hardcoded secrets in all project files)
    if all_project_files:
        from crb.analyzers.secret_detector import analyze_file as secret_scan
        secret_findings: list = []
        for fp in all_project_files:
            secret_findings.extend(secret_scan(fp, lang=OutputLang(output_lang)))
        if secret_findings:
            click.echo(f"Security: found {len(secret_findings)} potential secret(s)")
            sec_report = ReviewReport(target="security_scan", lang=OutputLang(output_lang))
            sec_report.set_sort_order(sort_order)
            for f in secret_findings:
                sec_report.add_finding(f)
            sec_report.all_files = all_project_files
            _write_report(sec_report, report_dir, f"{project_name}_security", output)


@cli.command(name="list-langs")
def list_langs():
    """List supported programming languages."""
    click.echo("Supported languages:")
    click.echo("  python  - Python (.py)")
    click.echo("  c_cpp   - C/C++ (.c, .h, .cpp, .hpp, .cc, .cxx)")
    click.echo("  go      - Go (.go)")
    click.echo("  rust    - Rust (.rs)")


@cli.command(name="list-sort-presets")
def list_sort_presets():
    """List available sort order presets."""
    click.echo("Available sort presets:")
    for name, order in _PRESET_SORT_ORDERS.items():
        click.echo(f"  {name}: {', '.join(s.value for s in order)}")
    click.echo("\nCustom: comma-separated severity names, e.g. 'Blocker,Critical,Major'")


@cli.command()
def doctor():
    """Diagnose LLM configuration."""

    config = LLMConfig.from_env()

    click.echo("CodeReviewerBot Doctor")
    click.echo("=" * 40)

    # Check LLM config
    click.echo(f"\nLLM API URL:    {config.api_url or '(not set)'}")
    click.echo(f"LLM API Key:    {'✓ set' if config.api_key else '✗ not set'}")
    click.echo(f"LLM Model:      {config.model or '(not set, will use gpt-4o)'}")

    if not config.is_valid():
        click.echo("\n✗ LLM not configured.")
        click.echo("  Set CRB_LLM_API_URL and CRB_LLM_API_KEY in your environment.")
        click.echo("  Example:")
        click.echo('    export CRB_LLM_API_URL="https://api.openai.com/v1"')
        click.echo('    export CRB_LLM_API_KEY="sk-..."')
        click.echo('    export CRB_LLM_MODEL="gpt-4o"')
        return

    # Test connection
    click.echo("\nTesting LLM connection...")
    try:
        reply = chat(config, "You are a test assistant.", "Reply only with: OK")
        click.echo(f"✓ LLM response: {reply.strip()}")
    except LLMError as e:
        click.echo(f"✗ LLM connection failed: {e}")
