"""Language auto-detection from file extensions."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class Lang(str):
    """Language identifier."""
    PYTHON = "python"
    C_CPP = "c_cpp"
    GO = "go"
    RUST = "rust"
    UNKNOWN = "unknown"


# File extension -> language mapping
_EXT_MAP: dict[str, str] = {
    ".py": Lang.PYTHON,
    ".pyi": Lang.PYTHON,
    ".pyx": Lang.PYTHON,
    ".c": Lang.C_CPP,
    ".h": Lang.C_CPP,
    ".cpp": Lang.C_CPP,
    ".cc": Lang.C_CPP,
    ".cxx": Lang.C_CPP,
    ".hpp": Lang.C_CPP,
    ".hh": Lang.C_CPP,
    ".hxx": Lang.C_CPP,
    ".go": Lang.GO,
    ".rs": Lang.RUST,
}

# Display names
_LANG_LABEL: dict[str, str] = {
    Lang.PYTHON: "Python",
    Lang.C_CPP: "C/C++",
    Lang.GO: "Go",
    Lang.RUST: "Rust",
    Lang.UNKNOWN: "Unknown",
}


@dataclass
class DetectionResult:
    files: dict[str, list[str]]  # lang -> list of file paths
    lang_counts: dict[str, int]  # lang -> file count

    @property
    def primary_lang(self) -> str:
        if not self.lang_counts:
            return Lang.UNKNOWN
        return max(self.lang_counts, key=self.lang_counts.get)

    @property
    def detected_langs(self) -> list[str]:
        return sorted(
            [k for k, v in self.lang_counts.items() if v > 0 and k != Lang.UNKNOWN]
        )

    def label(self, lang: str) -> str:
        return _LANG_LABEL.get(lang, lang)


def detect(paths: list[str]) -> DetectionResult:
    """Auto-detect languages from file extensions in given paths.

    Args:
        paths: File or directory paths to scan.

    Returns:
        DetectionResult with files grouped by language.
    """
    files: dict[str, list[str]] = {
        Lang.PYTHON: [],
        Lang.C_CPP: [],
        Lang.GO: [],
        Lang.RUST: [],
        Lang.UNKNOWN: [],
    }

    def _scan(p: Path) -> None:
        if p.is_file():
            ext = p.suffix.lower()
            lang = _EXT_MAP.get(ext, Lang.UNKNOWN)
            files[lang].append(str(p))
        elif p.is_dir():
            for f in sorted(p.rglob("*")):
                if f.is_file() and not any(
                    part.startswith(".") or part == "archived"
                    for part in f.parts
                ):
                    ext = f.suffix.lower()
                    lang = _EXT_MAP.get(ext, Lang.UNKNOWN)
                    files[lang].append(str(f))

    for p_str in paths:
        _scan(Path(p_str))

    lang_counts = {k: len(v) for k, v in files.items()}
    return DetectionResult(files=files, lang_counts=lang_counts)
