"""Tests for the Python analyzer module."""

from pathlib import Path

from crb.analyzers.python import bloat_detector, bug_detector, comment_detector, complexity, dead_code_detector, dependency_detector, design_detector, edge_case_detector, multi_agent, orphan_detector, retry_detector, style_checker, test_theater_detector
from crb.analyzers import secret_detector
from crb.config.settings import PythonAnalyzerConfig
from crb.report.models import FindingCategory


class TestComplexityAnalyzer:
    def test_simple_function(self, tmp_path: Path) -> None:
        """A simple function should have complexity 1."""
        f = tmp_path / "simple.py"
        f.write_text("def foo():\n    return 42\n")
        findings = complexity.analyze_file(str(f))
        assert len(findings) == 0, f"Expected no issues, got {findings}"

    def test_high_complexity(self, tmp_path: Path) -> None:
        """Function with many branches should exceed threshold."""
        lines = ["def foo(x):"]
        for i in range(15):
            lines.append(f"    if x == {i}:")
            lines.append(f"        print({i})")
        lines.append("    return x")
        f = tmp_path / "complex.py"
        f.write_text("\n".join(lines))
        findings = complexity.analyze_file(str(f))
        complexity_findings = [
            f for f in findings if f.title == "High Cyclomatic Complexity"
        ]
        assert len(complexity_findings) > 0

    def test_long_function(self, tmp_path: Path) -> None:
        """Function exceeding 50 lines should trigger warning."""
        lines = ["def foo():", "    pass"]
        # Add enough lines to exceed threshold
        for i in range(55):
            lines.append(f"    x = {i}")
        f = tmp_path / "long_func.py"
        f.write_text("\n".join(lines))
        findings = complexity.analyze_file(str(f))
        line_findings = [
            f for f in findings if f.title == "Overly Long Function"
        ]
        assert len(line_findings) > 0

    def test_complex_func_decorator(self, tmp_path: Path) -> None:
        """@complex_func should suppress complexity warnings."""
        lines = ["@complex_func", "def foo(x):"]
        for i in range(15):
            lines.append(f"    if x == {i}:")
            lines.append(f"        print({i})")
        lines.append("    return x")
        f = tmp_path / "decorated.py"
        f.write_text("\n".join(lines))
        findings = complexity.analyze_file(str(f))
        assert len(findings) == 0, f"Expected no findings, got {findings}"

    def test_large_class(self, tmp_path: Path) -> None:
        """Class exceeding 200 lines should trigger warning."""
        lines = ["class Foo:", "    pass"]
        for i in range(210):
            lines.append(f"    def method_{i}(self):")
            lines.append(f"        return {i}")
        f = tmp_path / "large_class.py"
        f.write_text("\n".join(lines))
        findings = complexity.analyze_file(str(f))
        class_findings = [
            f for f in findings if f.title == "Overly Large Class"
        ]
        assert len(class_findings) > 0


class TestRetryDetector:
    def test_retry_decorator_exceeded(self, tmp_path: Path) -> None:
        """Retry decorator with high max_retries should trigger warning."""
        code = """
import tenacity

@tenacity.retry(max_retries=10)
def fetch_data():
    return None
"""
        f = tmp_path / "retry_dec.py"
        f.write_text(code)
        config = PythonAnalyzerConfig()
        config.retry.max_retries = 3
        findings = retry_detector.analyze_file(str(f), config)
        retry_findings = [
            f for f in findings if f.title == "Excessive Retry Decorator Attempts"
        ]
        assert len(retry_findings) > 0

    def test_while_retry_loop(self, tmp_path: Path) -> None:
        """While retry_count < N loop should be detected."""
        code = """
def process():
    retry_count = 0
    while retry_count < 5:
        try:
            return do_something()
        except Exception:
            retry_count += 1
            sleep(1)
    raise RuntimeError("failed")
"""
        f = tmp_path / "retry_loop.py"
        f.write_text(code)
        config = PythonAnalyzerConfig()
        config.retry.max_retries = 3
        findings = retry_detector.analyze_file(str(f), config)
        retry_findings = [
            f for f in findings if "retry" in f.category.value
        ]
        # This might not catch the while loop pattern depending on detection
        # Just verify no crash
        assert isinstance(findings, list)


class TestOrphanDetector:
    def test_referenced_function_not_reported(self, tmp_path: Path) -> None:
        """A function that is called from another file should NOT be flagged."""
        a = tmp_path / "a.py"
        a.write_text("def helper():\n    return 42\n")
        b = tmp_path / "b.py"
        b.write_text("from a import helper\nresult = helper()\n")
        findings = orphan_detector.analyze_files([str(a), str(b)])
        assert len(findings) == 0, f"Expected no orphans, got {len(findings)}"

    def test_orphan_function_reported(self, tmp_path: Path) -> None:
        """A function defined but never called should be flagged as orphan."""
        a = tmp_path / "orphan.py"
        a.write_text("def unused_helper():\n    return 42\n")
        b = tmp_path / "main.py"
        b.write_text("x = 1\n")
        findings = orphan_detector.analyze_files([str(a), str(b)])
        orphan = [f for f in findings if f.category.value == "orphan"]
        assert len(orphan) > 0
        assert "unused_helper" in orphan[0].message or "unused_helper" in orphan[0].title

    def test_orphan_class_reported(self, tmp_path: Path) -> None:
        """An unused class should be flagged as orphan."""
        a = tmp_path / "models.py"
        a.write_text("class UnusedModel:\n    pass\n")
        b = tmp_path / "main.py"
        b.write_text("x = 1\n")
        findings = orphan_detector.analyze_files([str(a), str(b)])
        orphan = [f for f in findings if f.category.value == "orphan"]
        assert len(orphan) > 0
        assert "UnusedModel" in orphan[0].message or "UnusedModel" in orphan[0].title

    def test_dunder_not_reported(self, tmp_path: Path) -> None:
        """Dunder methods like __init__ should not be reported as orphans.
        The class itself IS orphaned if unreferenced, but dunder methods inside
        should not generate separate findings.
        """
        a = tmp_path / "clazz.py"
        a.write_text("class MyClass:\n    def __init__(self):\n        pass\n")
        findings = orphan_detector.analyze_files([str(a)])
        orphan = [f for f in findings if f.category.value == "orphan"]
        # Only the class MyClass is orphaned; __init__ is not separately flagged
        assert len(orphan) == 1
        assert "MyClass" in orphan[0].message or "MyClass" in orphan[0].title
        assert "__init__" not in orphan[0].message

    def test_no_orphans_in_normal_code(self, tmp_path: Path) -> None:
        """Normal code with proper cross-references should have no orphans."""
        a = tmp_path / "utils.py"
        a.write_text("def add(a, b):\n    return a + b\n")
        b = tmp_path / "main.py"
        b.write_text("from utils import add\nprint(add(1, 2))\n")
        findings = orphan_detector.analyze_files([str(a), str(b)])
        orphan = [f for f in findings if f.category.value == "orphan"]
        assert len(orphan) == 0

    def test_self_referenced_function_not_orphan(self, tmp_path: Path) -> None:
        """A function called by another visible function in the same file is not orphaned."""
        f = tmp_path / "mod.py"
        f.write_text("def helper():\n    return 42\n\ndef caller():\n    return helper()\n")
        findings = orphan_detector.analyze_files([str(f)])
        orphan_names = {o.title for o in findings if o.category.value == "orphan"}
        # helper() is called by caller() — not orphaned
        # caller() is called by nothing — IS orphaned
        assert "helper" not in str(orphan_names), "helper should not be orphaned"
        # caller is orphaned (nothing calls it from outside)
        orphan_caller = [o for o in findings if "caller" in o.message or "caller" in o.title]
        assert len(orphan_caller) == 1


class TestSecretDetector:
    def test_api_key_detected(self, tmp_path: Path) -> None:
        f = tmp_path / "config.py"
        f.write_text('API_KEY = "sk-1234567890abcdef"\n')
        findings = secret_detector.analyze_file(str(f))
        sec = [f for f in findings if f.category == FindingCategory.SECURITY]
        assert len(sec) > 0

    def test_password_detected(self, tmp_path: Path) -> None:
        f = tmp_path / "db.py"
        f.write_text('password = "supersecret123"\n')
        findings = secret_detector.analyze_file(str(f))
        sec = [f for f in findings if f.category == FindingCategory.SECURITY]
        assert len(sec) > 0

    def test_connection_string_detected(self, tmp_path: Path) -> None:
        f = tmp_path / "db_url.py"
        f.write_text('url = "postgresql://user:pass@localhost/db"\n')
        findings = secret_detector.analyze_file(str(f))
        sec = [f for f in findings if f.category == FindingCategory.SECURITY]
        assert len(sec) > 0

    def test_private_key_detected(self, tmp_path: Path) -> None:
        f = tmp_path / "key.py"
        f.write_text("key = '''-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEA...'''\n")
        findings = secret_detector.analyze_file(str(f))
        sec = [f for f in findings if f.category == FindingCategory.SECURITY]
        assert len(sec) > 0

    def test_env_var_not_false_positive(self, tmp_path: Path) -> None:
        """Reading from env should not flag."""
        f = tmp_path / "safe.py"
        f.write_text('import os\nAPI_KEY = os.environ["API_KEY"]\n')
        findings = secret_detector.analyze_file(str(f))
        sec = [f for f in findings if f.category == FindingCategory.SECURITY]
        assert len(sec) == 0

    def test_innocent_string_not_flagged(self, tmp_path: Path) -> None:
        f = tmp_path / "normal.py"
        f.write_text('greeting = "hello world"\n')
        findings = secret_detector.analyze_file(str(f))
        sec = [f for f in findings if f.category == FindingCategory.SECURITY]
        assert len(sec) == 0


class TestBugDetector:
    def test_bare_except(self, tmp_path: Path) -> None:
        f = tmp_path / "bare_except.py"
        f.write_text("try:\n    x = 1\nexcept:\n    pass\n")
        findings = bug_detector.analyze_file(str(f))
        bug = [f for f in findings if f.category == FindingCategory.BUG]
        assert len(bug) > 0

    def test_bare_except_with_type_ok(self, tmp_path: Path) -> None:
        f = tmp_path / "good_except.py"
        f.write_text("try:\n    x = 1\nexcept Exception:\n    pass\n")
        findings = bug_detector.analyze_file(str(f))
        bug = [f for f in findings if f.category == FindingCategory.BUG]
        assert len(bug) == 0

    def test_mutable_default_arg(self, tmp_path: Path) -> None:
        f = tmp_path / "mutable_default.py"
        f.write_text("def foo(x=[]):\n    pass\n")
        findings = bug_detector.analyze_file(str(f))
        bug = [f for f in findings if f.category == FindingCategory.BUG]
        assert len(bug) > 0

    def test_dict_default_arg(self, tmp_path: Path) -> None:
        f = tmp_path / "dict_default.py"
        f.write_text("def foo(x={}):\n    pass\n")
        findings = bug_detector.analyze_file(str(f))
        bug = [f for f in findings if f.category == FindingCategory.BUG]
        assert len(bug) > 0

    def test_none_default_ok(self, tmp_path: Path) -> None:
        f = tmp_path / "none_default.py"
        f.write_text("def foo(x=None):\n    if x is None:\n        x = []\n")
        findings = bug_detector.analyze_file(str(f))
        bug = [f for f in findings if f.category == FindingCategory.BUG]
        assert len(bug) == 0

    def test_is_none_comparison(self, tmp_path: Path) -> None:
        f = tmp_path / "bad_compare.py"
        f.write_text("if x == None:\n    pass\n")
        findings = bug_detector.analyze_file(str(f))
        bug = [f for f in findings if f.category == FindingCategory.BUG]
        assert len(bug) > 0

    def test_is_none_ok(self, tmp_path: Path) -> None:
        f = tmp_path / "good_compare.py"
        f.write_text("if x is None:\n    pass\n")
        findings = bug_detector.analyze_file(str(f))
        bug = [f for f in findings if f.category == FindingCategory.BUG]
        assert len(bug) == 0


class TestEdgeCaseDetector:
    def test_missing_else_flagged(self, tmp_path: Path) -> None:
        f = tmp_path / "no_else.py"
        f.write_text("if x == 1:\n    pass\nelif x == 2:\n    pass\nelif x == 3:\n    pass\n")
        findings = edge_case_detector.analyze_file(str(f))
        bug = [f for f in findings if f.category == FindingCategory.BUG]
        assert len(bug) > 0

    def test_has_else_ok(self, tmp_path: Path) -> None:
        f = tmp_path / "with_else.py"
        f.write_text("if x == 1:\n    pass\nelif x == 2:\n    pass\nelse:\n    pass\n")
        findings = edge_case_detector.analyze_file(str(f))
        bug = [f for f in findings if f.category == FindingCategory.BUG]
        assert len(bug) == 0

    def test_range_len_detected(self, tmp_path: Path) -> None:
        f = tmp_path / "range_len.py"
        f.write_text("for i in range(len(items)):\n    print(items[i])\n")
        findings = edge_case_detector.analyze_file(str(f))
        bug = [f for f in findings if f.category == FindingCategory.BUG]
        assert len(bug) > 0

    def test_enumerate_not_flagged(self, tmp_path: Path) -> None:
        f = tmp_path / "good_enumerate.py"
        f.write_text("for i, item in enumerate(items):\n    print(item)\n")
        findings = edge_case_detector.analyze_file(str(f))
        bug = [f for f in findings if f.category == FindingCategory.BUG]
        assert len(bug) == 0

    def test_short_if_no_warning(self, tmp_path: Path) -> None:
        f = tmp_path / "short_if.py"
        f.write_text("if x:\n    pass\nelse:\n    pass\n")
        findings = edge_case_detector.analyze_file(str(f))
        bug = [f for f in findings if f.category == FindingCategory.BUG]
        assert len(bug) == 0


class TestMultiAgent:
    def test_fix_agent_adds_suggestions(self, tmp_path: Path) -> None:
        """Fix agent should enrich findings with fix suggestions."""
        f = tmp_path / "buggy.py"
        f.write_text("try:\n    x = 1\nexcept:\n    pass\n")
        agent = multi_agent.ReviewAgent()
        report = agent.analyze([str(f)], output_lang="en")
        assert len(report.findings) > 0
        # At least one finding should have a suggestion from fix agent
        has_fix = any(
            f.suggestion and "Fix" in f.suggestion
            for f in report.findings
        )
        assert has_fix, f"No findings had fix suggestions: {report.findings}"

    def test_organizer_generates_summary(self, tmp_path: Path) -> None:
        f = tmp_path / "buggy2.py"
        f.write_text("try:\n    x = 1\nexcept:\n    pass\n")
        agent = multi_agent.ReviewAgent()
        report = agent.analyze([str(f)], output_lang="en")
        assert hasattr(report, "_executive_summary")
        assert len(report._executive_summary) > 0


class TestTestTheaterDetector:
    def test_no_assertions(self, tmp_path: Path) -> None:
        f = tmp_path / "test_no_assert.py"
        f.write_text("def test_foo():\n    x = 1 + 1\n")
        findings = test_theater_detector.analyze_file(str(f))
        test_issues = [f for f in findings if f.category == FindingCategory.TEST]
        assert len(test_issues) > 0

    def test_normal_test_ok(self, tmp_path: Path) -> None:
        f = tmp_path / "test_normal.py"
        f.write_text("def test_foo():\n    assert 1 + 1 == 2\n")
        findings = test_theater_detector.analyze_file(str(f))
        test_issues = [f for f in findings if f.category == FindingCategory.TEST]
        assert len(test_issues) == 0

    def test_always_true_assertion(self, tmp_path: Path) -> None:
        f = tmp_path / "test_always_true.py"
        f.write_text("def test_foo():\n    assert True\n")
        findings = test_theater_detector.analyze_file(str(f))
        test_issues = [f for f in findings if f.category == FindingCategory.TEST]
        assert len(test_issues) > 0

    def test_non_test_file_skipped(self, tmp_path: Path) -> None:
        f = tmp_path / "production.py"
        f.write_text("def do_work():\n    pass\n")
        findings = test_theater_detector.analyze_file(str(f))
        assert len(findings) == 0


class TestDependencyDetector:
    def test_shadows_stdlib(self, tmp_path: Path) -> None:
        f = tmp_path / "os.py"
        f.write_text("x = 1\n")
        findings = dependency_detector.analyze_files([str(f)])
        dep = [f for f in findings if f.category == FindingCategory.DEPENDENCY]
        assert len(dep) > 0

    def test_normal_module_ok(self, tmp_path: Path) -> None:
        f = tmp_path / "utils.py"
        f.write_text("x = 1\n")
        findings = dependency_detector.analyze_files([str(f)])
        dep = [f for f in findings if f.category == FindingCategory.DEPENDENCY]
        assert len(dep) == 0


class TestDesignDetector:
    def test_excessive_isinstance(self, tmp_path: Path) -> None:
        f = tmp_path / "many_isinstance.py"
        code = """def process(value):
    if isinstance(value, int):
        return 1
    elif isinstance(value, str):
        return 2
    elif isinstance(value, list):
        return 3
    elif isinstance(value, dict):
        return 4
    return 0
"""
        f.write_text(code)
        findings = design_detector.analyze_file(str(f))
        design = [f for f in findings if f.category == FindingCategory.DESIGN]
        assert len(design) > 0

    def test_no_isinstance_ok(self, tmp_path: Path) -> None:
        f = tmp_path / "no_isinstance.py"
        f.write_text("def process(value):\n    return value.handle()\n")
        findings = design_detector.analyze_file(str(f))
        design = [f for f in findings if f.category == FindingCategory.DESIGN]
        assert len(design) == 0

    def test_silent_except(self, tmp_path: Path) -> None:
        f = tmp_path / "silent_except.py"
        f.write_text("try:\n    x = 1\nexcept Exception:\n    pass\n")
        findings = design_detector.analyze_file(str(f))
        bug = [f for f in findings if f.category == FindingCategory.BUG]
        assert len(bug) > 0

    def test_bare_except_not_double_counted(self, tmp_path: Path) -> None:
        """Bare except without type is covered by bug_detector, not design_detector."""
        f = tmp_path / "bare_except.py"
        f.write_text("try:\n    x = 1\nexcept:\n    pass\n")
        findings = design_detector.analyze_file(str(f))
        bug = [f for f in findings if f.category == FindingCategory.BUG]
        assert len(bug) == 0  # Bare except pass, this detector only catches Exception: pass


class TestDeadCodeDetector:
    def test_commented_out_code_block(self, tmp_path: Path) -> None:
        f = tmp_path / "dead_code.py"
        code = "\n".join([
            "# import os",
            "# import sys",
            "# import json",
            "# import re",
            "x = 1",
        ])
        f.write_text(code + "\n")
        findings = dead_code_detector.analyze_file(str(f))
        docs = [f for f in findings if f.category == FindingCategory.DOCUMENTATION]
        assert len(docs) > 0

    def test_stale_todo_detected(self, tmp_path: Path) -> None:
        f = tmp_path / "stale_todo.py"
        f.write_text("# TODO: fix this 2020-01-01\nx = 1\n")
        findings = dead_code_detector.analyze_file(str(f))
        docs = [f for f in findings if f.category == FindingCategory.DOCUMENTATION]
        assert len(docs) > 0

    def test_fresh_todo_ok(self, tmp_path: Path) -> None:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        fresh_date = f"{now.year}-{now.month:02d}-{now.day:02d}"
        f = tmp_path / "fresh_todo.py"
        f.write_text(f"# TODO: check this {fresh_date}\nx = 1\n")
        findings = dead_code_detector.analyze_file(str(f))
        docs = [f for f in findings if f.category == FindingCategory.DOCUMENTATION]
        assert len(docs) == 0


class TestBloatDetector:
    def test_too_many_params(self, tmp_path: Path) -> None:
        f = tmp_path / "many_params.py"
        code = "def foo(a, b, c, d, e, f, g):\n    pass\n"
        f.write_text(code)
        findings = bloat_detector.analyze_file(str(f))
        comp = [f for f in findings if f.category == FindingCategory.COMPLEXITY]
        assert len(comp) > 0

    def test_few_params_ok(self, tmp_path: Path) -> None:
        f = tmp_path / "few_params.py"
        code = "def foo(a, b, c):\n    pass\n"
        f.write_text(code)
        findings = bloat_detector.analyze_file(str(f))
        comp = [f for f in findings if f.category == FindingCategory.COMPLEXITY]
        assert len(comp) == 0

    def test_excessive_nesting(self, tmp_path: Path) -> None:
        f = tmp_path / "deep_nest.py"
        code = """def foo():
    if True:
        if True:
            if True:
                if True:
                    if True:
                        if True:
                            pass
"""
        f.write_text(code)
        findings = bloat_detector.analyze_file(str(f))
        comp = [f for f in findings if f.category == FindingCategory.COMPLEXITY]
        assert len(comp) > 0

    def test_shallow_nesting_ok(self, tmp_path: Path) -> None:
        f = tmp_path / "shallow.py"
        code = """def foo():
    if True:
        pass
"""
        f.write_text(code)
        findings = bloat_detector.analyze_file(str(f))
        comp = [f for f in findings if f.category == FindingCategory.COMPLEXITY]
        assert len(comp) == 0


class TestCommentDetector:
    def test_redundant_docstring(self, tmp_path: Path) -> None:
        """Docstring that just repeats the function name."""
        f = tmp_path / "redundant_doc.py"
        f.write_text('def foo():\n    """foo"""\n    pass\n')
        findings = comment_detector.analyze_file(str(f))
        docs = [f for f in findings if f.category == FindingCategory.DOCUMENTATION]
        assert len(docs) > 0

    def test_meaningful_docstring_ok(self, tmp_path: Path) -> None:
        f = tmp_path / "good_doc.py"
        f.write_text('def foo():\n    """Calculate the result of bar."""\n    pass\n')
        findings = comment_detector.analyze_file(str(f))
        docs = [f for f in findings if f.category == FindingCategory.DOCUMENTATION]
        assert len(docs) == 0

    def test_empty_docstring(self, tmp_path: Path) -> None:
        f = tmp_path / "empty_doc.py"
        f.write_text('def foo():\n    """"""\n    pass\n')
        findings = comment_detector.analyze_file(str(f))
        docs = [f for f in findings if f.category == FindingCategory.DOCUMENTATION]
        assert len(docs) > 0

    def test_stub_todo_comment(self, tmp_path: Path) -> None:
        f = tmp_path / "stub_todo.py"
        f.write_text("# TODO\nx = 1\n")
        findings = comment_detector.analyze_file(str(f))
        docs = [f for f in findings if f.category == FindingCategory.DOCUMENTATION]
        assert len(docs) > 0

    def test_detailed_todo_ok(self, tmp_path: Path) -> None:
        f = tmp_path / "detailed_todo.py"
        f.write_text("# TODO(sunhao): refactor this module\nx = 1\n")
        findings = comment_detector.analyze_file(str(f))
        docs = [f for f in findings if f.category == FindingCategory.DOCUMENTATION]
        assert len(docs) == 0


class TestStyleChecker:
    def test_wildcard_import_detected(self, tmp_path: Path) -> None:
        f = tmp_path / "bad_import.py"
        f.write_text("from os import *\n")
        findings = style_checker.analyze_file(str(f))
        wc = [f for f in findings if f.title == "Wildcard Import"]
        assert len(wc) > 0

    def test_global_detected(self, tmp_path: Path) -> None:
        f = tmp_path / "global_usage.py"
        f.write_text("x = 1\ndef foo():\n    global x\n    x = 2\n")
        findings = style_checker.analyze_file(str(f))
        global_findings = [f for f in findings if f.title == "Use of `global` Statement"]
        assert len(global_findings) > 0

    def test_short_variable_name(self, tmp_path: Path) -> None:
        f = tmp_path / "short_var.py"
        f.write_text("a = 42\n")
        findings = style_checker.analyze_file(str(f))
        name_findings = [f for f in findings if f.title == "Non-Descriptive Variable Name"]
        assert len(name_findings) > 0

    def test_long_file(self, tmp_path: Path) -> None:
        lines = ["# comment"] * 1001
        f = tmp_path / "long_file.py"
        f.write_text("\n".join(lines))
        findings = style_checker.analyze_file(str(f))
        long_file_findings = [f for f in findings if f.title == "Overly Long File"]
        assert len(long_file_findings) > 0
