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

import fnmatch

import click

from crb.config.settings import AppConfig, LLMConfig
from crb.llm.client import LLMError, chat
from crb.report.models import OutputLang, ReviewReport, Severity
from crb.report.structure_builder import generate_structure_json as _build_structure_json

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


_STRUCTURE_VIEWER_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Project Structure</title>
<script crossorigin src="https://unpkg.com/react@18/umd/react.production.min.js"></script>
<script crossorigin src="https://unpkg.com/react-dom@18/umd/react-dom.production.min.js"></script>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#f5f6fa;color:#2c3e50;padding:24px}
.header{max-width:1200px;margin:0 auto 24px;display:flex;align-items:center;gap:16px}
.header h1{font-size:24px;font-weight:600;color:#1a1a2e}
.header .meta{color:#7f8c8d;font-size:14px}
.grid{max-width:1200px;margin:0 auto;display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:16px;margin-bottom:32px}
.card{background:#fff;border-radius:12px;padding:20px;box-shadow:0 1px 3px rgba(0,0,0,.08);border:1px solid #e8ecf1;cursor:pointer;transition:all .2s}
.card:hover{box-shadow:0 4px 12px rgba(0,0,0,.12);transform:translateY(-2px)}
.card h3{font-size:15px;font-weight:600;margin-bottom:8px;color:#1a1a2e}
.card .count{font-size:28px;font-weight:700;color:#3498db}
.card .sub{font-size:12px;color:#95a5a6;margin-top:4px}
.file-list{max-width:1200px;margin:0 auto;background:#fff;border-radius:12px;box-shadow:0 1px 3px rgba(0,0,0,.08);border:1px solid #e8ecf1;overflow:hidden}
.file-header{padding:16px 20px;border-bottom:1px solid #e8ecf1;font-weight:600;font-size:15px;display:flex;justify-content:space-between;align-items:center}
.file-header .toggle{color:#3498db;font-size:13px;cursor:pointer;user-select:none}
.file-row{display:flex;align-items:center;padding:10px 20px;border-bottom:1px solid #f0f2f5;font-size:13px;transition:background .15s}
.file-row:last-child{border-bottom:none}
.file-row:hover{background:#f8f9fb}
.file-row .name{flex:1;font-family:'SF Mono',Menlo,monospace;color:#2c3e50}
.file-row .path{flex:2;color:#7f8c8d;font-size:12px}
.file-row .module{background:#eaf2fd;color:#2980b9;padding:2px 8px;border-radius:4px;font-size:11px}
.symbols{padding:4px 0 0 32px;font-size:12px;color:#7f8c8d;line-height:1.8}
.symbols .class{color:#27ae60}
.symbols .fn{color:#8e44ad}
.tree-view{padding:12px 20px 16px;font-family:'SF Mono',Menlo,monospace;font-size:13px;line-height:1.7;background:#fafbfc;border-top:1px solid #e8ecf1;max-height:400px;overflow-y:auto}
.tree-line{white-space:pre}
.tree-dir{color:#2c3e50;font-weight:500}
.tree-file{color:#555}
.module-section{margin-bottom:8px}
.module-card{padding:12px 16px;margin-bottom:8px;background:#f8f9fb;border-radius:8px;border-left:3px solid #3498db}
.module-card h4{font-size:14px;margin-bottom:4px}
.module-card .file-count{font-size:12px;color:#95a5a6}
.module-card .files{display:none;margin-top:8px;padding-left:16px}
.module-card.expanded .files{display:block}
.clickable-path{cursor:pointer;color:#3498db;text-decoration:none}
.clickable-path:hover{text-decoration:underline}
@media(prefers-color-scheme:dark){body{background:#0f0f1a;color:#e0e0e0}.card,.file-list,.tree-view{background:#1a1a2e;border-color:#2a2a3e}.card:hover{box-shadow:0 4px 12px rgba(0,0,0,.3)}.file-row:hover{background:#22223a}.file-header{border-color:#2a2a3e}.file-row{border-color:#22223a}.module-card{background:#22223a}}
</style>
</head>
<body>
<div id="root"></div>
<script>
const DATA = __STRUCTURE_DATA__;

function ModuleCard({mod}) {
  const [expanded, setExpanded] = React.useState(false);
  return React.createElement('div',{
    className:'module-card'+(expanded?' expanded':''),
    onClick:()=>setExpanded(!expanded)
  },React.createElement('h4',null,mod.label),
    React.createElement('div',{className:'file-count'},mod.file_count+' files'),
    React.createElement('div',{className:'files'},
      mod.files.map(f=>React.createElement('div',{key:f,style:{fontSize:'12px',padding:'2px 0',fontFamily:"'SF Mono',Menlo,monospace"}},f))
    )
  );
}

function FileRow({file}) {
  return React.createElement('div',{className:'file-row'},
    React.createElement('div',{className:'name'},file.name),
    React.createElement('div',{className:'path'},file.path),
    file.module?React.createElement('div',{className:'module'},file.module):null
  );
}

function App() {
  const [showAllFiles, setShowAllFiles] = React.useState(false);
  const [showTree, setShowTree] = React.useState(false);
  const {modules, files, imports} = DATA;
  const totalFiles = files.length;
  const visibleFiles = showAllFiles ? files : files.slice(0,50);

  return React.createElement(React.Fragment,null,
    React.createElement('div',{className:'header'},
      React.createElement('h1',null,'Project Structure'),
      React.createElement('span',{className:'meta'},totalFiles+' files, '+modules.length+' modules'+(imports.length?', '+imports.length+' dependencies':''))
    ),
    React.createElement('div',{className:'grid'},
      modules.map(mod=>React.createElement('div',{key:mod.name,className:'card',onClick:()=>{
        const el = document.getElementById('files-section');
        if(el) el.scrollIntoView({behavior:'smooth'});
      }},
        React.createElement('h3',null,mod.label),
        React.createElement('div',{className:'count'},mod.file_count),
        React.createElement('div',{className:'sub'},'files')
      ))
    ),
    modules.length>0 && React.createElement('div',{className:'tree-view'},
      modules.map((mod,i)=>{
        const prefix=i===modules.length-1?'└── ':'├── ';
        return React.createElement('div',{key:mod.name,className:'tree-line'},
          React.createElement('span',{className:'tree-dir'},prefix+mod.label+'/'),
          React.createElement('span',{style:{color:'#95a5a6',fontSize:'12px'}},' ('+mod.file_count+' files)')
        );
      })
    ),
    React.createElement('div',{id:'files-section',className:'file-list'},
      React.createElement('div',{className:'file-header'},
        React.createElement('span',null,'Files'),
        React.createElement('span',{className:'toggle',onClick:()=>setShowAllFiles(!showAllFiles)},
          showAllFiles?'Show less':'Show all ('+totalFiles+')'
        )
      ),
      visibleFiles.map(f=>React.createElement(FileRow,{key:f.path,file:f})),
      !showAllFiles && totalFiles>50 && React.createElement('div',{style:{textAlign:'center',padding:'16px',color:'#95a5a6',fontSize:'13px'}},
        'Showing 50 of '+totalFiles+' files'
      )
    ),
    imports.length>0 && React.createElement('div',{className:'file-list',style:{marginTop:'16px'}},
      React.createElement('div',{className:'file-header'},
        React.createElement('span',null,'Dependencies ('+imports.length+')')
      ),
      [...new Set(imports.map(i=>i.target))].sort().slice(0,40).map(target=>
        React.createElement('div',{key:target,className:'file-row'},
          React.createElement('div',{className:'name'},target),
          React.createElement('div',{className:'path'},imports.filter(i=>i.target===target).length+' references')
        )
      )
    )
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(React.createElement(App));
</script>
</body>
</html>"""


def _write_structure_viewer(report: ReviewReport, output_dir: str) -> None:
    """Write structure-data.json and structure-viewer.html for human browsing."""
    import json

    all_files = report.all_files or []
    data = _build_structure_json(all_files, output_dir)
    json_path = Path(output_dir) / "structure-data.json"
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    html = _STRUCTURE_VIEWER_TEMPLATE.replace("__STRUCTURE_DATA__", json.dumps(data, ensure_ascii=False))
    html_path = Path(output_dir) / "structure-viewer.html"
    html_path.write_text(html, encoding="utf-8")
    click.echo(f"Structure viewer: {html_path}")


def _write_report(
    report: ReviewReport,
    report_dir: str,
    project_name: str,
    output_format: str,
    project_root: str | None = None,
    app_config: AppConfig | None = None,
) -> None:
    """Write report and structure docs to disk."""
    report_path = Path(report_dir) / f"{project_name}_report.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)

    if output_format == "markdown":
        # Run LLM-powered review agents to add deep semantic findings
        if app_config and app_config.llm.is_valid() and report.findings is not None:
            try:
                from crb.agents.review_agent import analyze_files as llm_review
                llm_files = list(report.all_files) if report.all_files else []
                if not llm_files and project_root:
                    root_path = Path(project_root)
                    for ext in ("*.py",):
                        llm_files.extend(str(f) for f in root_path.rglob(ext) if not any(
                            p.startswith(".") for p in f.parts
                        ))
                if llm_files:
                    llm_findings = llm_review(
                        llm_files[:20],  # limit to 20 files per run
                        config=app_config,
                        project_root=project_root,
                        report=report,  # pass report for fix suggestions
                    )
                    for f in llm_findings:
                        report.add_finding(f)
                    if llm_findings:
                        click.echo(f"LLM review: {len(llm_findings)} finding(s)")
            except Exception as e:
                click.echo(f"  (LLM review skipped: {e})", err=True)

        content = report.to_markdown()
        report_path.write_text(content, encoding="utf-8")

        # Write structure docs to project root (not inside report/)
        structure_root = project_root or report_dir
        structure_paths = report.generate_hierarchical_structure_docs(structure_root)
        for sp in structure_paths:
            click.echo(f"Structure doc: {sp}")

        # Write structure data JSON + React viewer for human browsing
        _write_structure_viewer(report, structure_root)

        # Enhance structure docs with LLM
        if project_root and app_config and app_config.llm.is_valid():
            try:
                from crb.agents.structure_agent import StructureDocAgent
                agent = StructureDocAgent(app_config)
                enhanced = agent.enhance_all(project_root)
                if enhanced:
                    click.echo(f"Enhanced {len(enhanced)} structure doc(s) with LLM")
            except Exception as e:
                click.echo(f"  (structure enhancement skipped: {e})", err=True)
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
@click.option("--report-dir", default=None)
@click.option(
    "--output-lang", type=click.Choice(["ch", "en", "ch_en"]), default="ch",
    help="Report language: ch (Chinese), en (English), ch_en (bilingual).",
)
@click.option(
    "--exclude", multiple=True, default=[],
    help="Exclude files/dirs matching glob pattern. Can be repeated. E.g.: --exclude 'data/*' --exclude '*.txt'",
)
def review(paths, lang, sort, output, report_dir, output_lang, exclude):
    """Review source code in PATHS (files or directories).

    Detects language automatically from file extensions unless --lang is given.
    """
    from crb.analyzers.detector import Lang, detect

    # Load LLM config from environment
    llm_config = LLMConfig.from_env()
    config = AppConfig(report_dir=report_dir, llm=llm_config)

    # LLM is optional — static analyzers work without it, only LLM agents are skipped
    if not llm_config.is_valid():
        click.echo("Note: LLM not configured — LLM-powered agents will be skipped.", err=True)
        click.echo("  Set CRB_LLM_API_URL and CRB_LLM_API_KEY to enable deep semantic review.", err=True)

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
    if not project_root:
        if os.path.isdir(resolved[0]):
            project_root = resolved[0]
        else:
            project_root = str(Path(resolved[0]).parent)

    # Default report_dir to inside the analyzed project, not cwd
    if report_dir is None:
        report_dir = os.path.join(project_root or os.getcwd(), "report")

    # Collect all project files for the file tree overview
    all_project_files: list[str] = []
    if project_root:
        root_path = Path(project_root)
        for f in sorted(root_path.rglob("*")):
            if f.is_file() and not any(
                part.startswith(".") or part == "archived" or part == "__pycache__"
                or part == "build" or part == "dist" or part == "node_modules" or part == "report"
                for part in f.parts
            ) and f.name not in ("structure.md", "structure_zh.md", "structure_en.md"):
                all_project_files.append(str(f))

    # Apply --exclude patterns
    if exclude:
        def _should_exclude(fp: str) -> bool:
            for pattern in exclude:
                if fnmatch.fnmatch(fp, pattern) or fnmatch.fnmatch(os.path.basename(fp), pattern):
                    return True
                # Also match path segments (e.g. --exclude data matches /any/path/data/...)
                if "/" + pattern.rstrip("/") in fp:
                    return True
            return False

        n_before = len(all_project_files)
        all_project_files = [f for f in all_project_files if not _should_exclude(f)]
        n_after = len(all_project_files)
        if n_before != n_after:
            click.echo(f"Excluded {n_before - n_after} file(s) from project overview")

        # Also filter detection results so analysis doesn't run on excluded files
        for lang_key in list(detection.files.keys()):
            detection.files[lang_key] = [
                f for f in detection.files[lang_key]
                if not _should_exclude(f)
            ]

    for target_lang in target_langs:
        lang_files = detection.files.get(target_lang, [])
        if not lang_files:
            continue

        click.echo(f"Analyzing {len(lang_files)} {detection.label(target_lang)} file(s)...")
        report = _run_analyzer(target_lang, lang_files, config, sort_order, output_lang)
        report.all_files = all_project_files
        _write_report(report, report_dir, project_name, output, project_root=project_root, app_config=config)

    # Cross-language structure analysis (AI code spread detection)
    if all_project_files and len(all_project_files) >= 5:
        from crb.analyzers.generic.structure_analyzer import analyze_structure
        struct_findings = analyze_structure(all_project_files, project_root=project_root)
        if struct_findings:
            click.echo(f"Structure: found {len(struct_findings)} structural issue(s)")
            struct_report = ReviewReport(target=project_root or ", ".join(resolved), lang=OutputLang(output_lang))
            struct_report.set_sort_order(sort_order)
            for f in struct_findings:
                struct_report.add_finding(f)
            struct_report.all_files = all_project_files
            _write_report(struct_report, report_dir, f"{project_name}_structure", output, project_root=project_root, app_config=config)

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
            _write_report(sec_report, report_dir, f"{project_name}_security", output, project_root=project_root, app_config=config)


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
