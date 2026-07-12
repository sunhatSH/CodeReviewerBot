"""Authentication/authorization missing detector for Python web frameworks.

Detects endpoints and handlers that may be missing auth checks:
1. Route-decorated functions missing auth decorators (@login_required, etc.)
2. API handlers accepting resource IDs without ownership validation
3. Admin/mutating endpoints without role/permission checks
4. Class-based views missing auth mixins

Requirements: 2.2 代码审查能力 — 鉴权缺失检测
"""

from __future__ import annotations

import ast
import os
from pathlib import Path
from typing import Optional

from crb.report.models import (
    Finding,
    FindingCategory,
    OutputLang,
    Severity,
    _finding_msg,
)

# Route decorator names (framework-agnostic patterns)
_ROUTE_DECORATORS = {
    "route", "get", "post", "put", "patch", "delete",
    "head", "options",
}

# Decorator prefixes that indicate route registration
_ROUTE_PREFIXES = {
    "app", "route", "router", "bp", "blueprint",
    "api", "site", "dashboard",
}

# Name suffixes/pieces that identify route/blueprint objects
_ROUTE_OBJECT_NAMES = {
    "route", "router", "blueprint", "bp",
    "app", "api",
}

# Auth decorators that satisfy login/authentication requirement
_AUTH_DECORATORS = {
    "login_required",
    "login_required",
    "auth_required",
    "requires_auth",
    "authenticated",
    "authenticated",
    "jwt_required",
    "jwt_required",
    "token_required",
    "token_required",
    "oauth_required",
    "session_required",
}

# Permission/role decorators
_PERMISSION_DECORATORS = {
    "permission_required",
    "permission_required",
    "roles_required",
    "roles_required",
    "role_required",
    "role_required",
    "has_permission",
    "has_permission",
    "has_role",
    "has_role",
    "admin_required",
    "admin_required",
    "staff_required",
    "staff_required",
    "superuser_required",
    "group_required",
    "has_access",
    "require_scope",
    "scopes_required",
}

# ViewSet / MethodView base class names that provide built-in auth
_AUTH_MIXIN_CLASSES = {
    "LoginRequiredMixin",
    "PermissionRequiredMixin",
    "UserPassesTestMixin",
    "AccessMixin",
    "LoginRequired",
}

_MUTATING_KEYWORDS = {
    "create", "update", "delete", "remove", "edit",
    "save", "write", "modify", "change", "upload",
    "import", "export", "publish", "archive", "restore",
}


class _AuthVisitor(ast.NodeVisitor):
    """AST visitor to detect missing authentication patterns."""

    def __init__(self, file_path: str, lang: OutputLang = OutputLang.EN):
        self.file_path = file_path
        self.lang = lang
        self.findings: list[Finding] = []
        self._route_object_names: set[str] = set()
        self._current_class_bases: set[str] = set()

    def _collect_route_objects(self, tree: ast.Module) -> None:
        """Pre-scan for Flask/FastAPI route object names (app, router, bp, etc.)."""
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        name_lower = target.id.lower()
                        if name_lower in _ROUTE_OBJECT_NAMES:
                            self._route_object_names.add(target.id)
                        # FastAPI: router = APIRouter() — name is "router"
                        if isinstance(node.value, ast.Call):
                            if isinstance(node.value.func, ast.Name):
                                if "route" in node.value.func.id.lower():
                                    self._route_object_names.add(target.id)

    def _is_route_call(self, node: ast.Call) -> bool:
        """Check if an AST Call is a route registration (e.g., @app.route)."""
        if isinstance(node.func, ast.Attribute):
            # Pattern: app.route(...) or router.get(...)
            if isinstance(node.func.value, ast.Name):
                if node.func.value.id in self._route_object_names:
                    return node.func.attr in _ROUTE_DECORATORS
            # Pattern: some_module.route(...) or some_obj.get(...)
            if isinstance(node.func.value, ast.Attribute):
                if node.func.attr in _ROUTE_DECORATORS:
                    return True
        return False

    def _is_route_decorator(self, node: ast.AST) -> bool:
        """Check if a decorator node registers a route."""
        if isinstance(node, ast.Call):
            return self._is_route_call(node)
        return False

    def _is_auth_decorator(self, node: ast.AST) -> bool:
        """Check if a decorator provides authentication."""
        name = None
        if isinstance(node, ast.Name):
            name = node.id
        elif isinstance(node, ast.Attribute):
            name = node.attr
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                name = node.func.attr
        if name is None:
            return False
        return name.lower() in _AUTH_DECORATORS or name.lower() in _PERMISSION_DECORATORS

    def _has_class_based_auth(self, bases: list[ast.expr]) -> bool:
        """Check if class inherits from an auth mixin."""
        for base in bases:
            if isinstance(base, ast.Name):
                if base.id in _AUTH_MIXIN_CLASSES:
                    return True
            elif isinstance(base, ast.Attribute):
                if base.attr in _AUTH_MIXIN_CLASSES:
                    return True
        return False

    def _function_has_mutation(self, node: ast.FunctionDef) -> bool:
        """Check if function name or body suggests it mutates data."""
        name_lower = node.name.lower()
        for keyword in _MUTATING_KEYWORDS:
            if keyword in name_lower:
                return True

        # Check for HTTP methods that mutate
        decorator_names = set()
        for dec in node.decorator_list:
            if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute):
                decorator_names.add(dec.func.attr.lower())
            elif isinstance(dec, ast.Attribute):
                decorator_names.add(dec.attr.lower())

        if {"post", "put", "patch", "delete"} & decorator_names:
            return True

        return False

    def _extracts_resource_id(self, node: ast.FunctionDef) -> bool:
        """Check if function accepts a resource identifier parameter."""
        for arg in node.args.args:
            name_lower = arg.arg.lower()
            if any(term in name_lower for term in (
                "id", "pk", "key", "slug", "uid",
                "resource", "target",
            )):
                return True
        return False

    def _check_endpoint_auth(
        self, node: ast.FunctionDef, is_class_method: bool = False,
    ) -> None:
        """Check if a route endpoint has proper authentication."""
        has_route = any(self._is_route_decorator(d) for d in node.decorator_list)
        if not has_route:
            return

        has_auth = any(self._is_auth_decorator(d) for d in node.decorator_list)

        # Check if class has auth mixin (for class-based views)
        if not has_auth and is_class_method:
            if self._has_class_based_auth(self._current_class_bases):
                has_auth = True

        if has_auth:
            return

        # Determine severity based on risk indicators
        is_mutating = self._function_has_mutation(node)
        has_resource_id = self._extracts_resource_id(node)
        is_admin = "admin" in node.name.lower() or any(
            "admin" in d.attr.lower()
            for d in node.decorator_list
            if isinstance(d, ast.Attribute)
        )

        if is_mutating or is_admin:
            severity = Severity.CRITICAL
            category = FindingCategory.SECURITY
            msg_key = "auth_missing_critical"
        elif has_resource_id:
            severity = Severity.MAJOR
            category = FindingCategory.SECURITY
            msg_key = "auth_missing_major"
        else:
            severity = Severity.MAJOR
            category = FindingCategory.SECURITY
            msg_key = "auth_missing_minor"

        # Build route path for context
        route_path = self._extract_route_path(node)
        title, msg, suggestion = _finding_msg(
            self.lang, msg_key,
            name=node.name,
            path=route_path or node.name,
        )
        self.findings.append(
            Finding(
                file=self.file_path,
                line=node.lineno,
                severity=severity,
                category=category,
                title=title,
                message=msg,
                suggestion=suggestion,
            )
        )

    def _extract_route_path(self, node: ast.FunctionDef) -> str | None:
        """Extract the route path from decorators."""
        for dec in node.decorator_list:
            if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute):
                if dec.func.attr in _ROUTE_DECORATORS and dec.args:
                    if isinstance(dec.args[0], ast.Constant):
                        return str(dec.args[0].value)
        return None

    def visit_Module(self, node: ast.Module) -> None:
        self._collect_route_objects(node)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        # Check if this is a standalone route handler
        self._check_endpoint_auth(node, is_class_method=False)
        # Also check async functions via generic_visit
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._check_endpoint_auth(node, is_class_method=False)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._current_class_bases = set()
        for base in node.bases:
            if isinstance(base, ast.Name):
                self._current_class_bases.add(base.id)
            elif isinstance(base, ast.Attribute):
                self._current_class_bases.add(base.attr)

        for item in node.body:
            if isinstance(item, ast.FunctionDef):
                self._check_endpoint_auth(item, is_class_method=True)
            elif isinstance(item, ast.AsyncFunctionDef):
                self._check_endpoint_auth(item, is_class_method=True)

        self._current_class_bases = set()


def analyze_file(
    file_path: str,
    config: Optional[object] = None,
    lang: OutputLang = OutputLang.EN,
) -> list[Finding]:
    """Analyze a single Python file for missing authentication patterns.

    Args:
        file_path: Path to the .py file.
        config: Analyzer configuration (unused, kept for API compatibility).
        lang: Output language for messages.

    Returns:
        List of findings.
    """
    path = Path(file_path)
    if not path.exists():
        return []

    source = path.read_text(encoding="utf-8")

    try:
        tree = ast.parse(source, filename=file_path)
    except SyntaxError:
        return []

    visitor = _AuthVisitor(file_path=file_path, lang=lang)
    visitor.visit(tree)
    return visitor.findings
