/// static_analyzer — C++ static analysis for Python source files.
///
/// Reads Python files, performs line-based pattern analysis (no full AST),
/// outputs JSON findings to stdout.
///
/// Usage: static_analyzer <file1.py> [file2.py ...]  > findings.json

#include "third_party/json.hpp"
#include <algorithm>
#include <cctype>
#include <cmath>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <regex>
#include <set>
#include <sstream>
#include <string>
#include <vector>

using json = nlohmann::json;
namespace fs = std::filesystem;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

static std::string trim_left(const std::string &s) {
    auto it = std::find_if(s.begin(), s.end(), [](unsigned char c) { return !std::isspace(c); });
    return {it, s.end()};
}

static int indent_level(const std::string &line) {
    int n = 0;
    for (char c : line) {
        if (c == ' ')      ++n;
        else if (c == '\t') n += 4;  // treat tab as 4 spaces
        else break;
    }
    return n;
}

static bool is_blank(const std::string &line) {
    return std::all_of(line.begin(), line.end(), [](unsigned char c) { return std::isspace(c); });
}

// Check if line is a comment (after stripping leading whitespace)
static bool is_comment(const std::string &line) {
    auto t = trim_left(line);
    return t.size() >= 1 && t[0] == '#';
}

// Check if line looks like code (for commented-out code detection)
static bool looks_like_code(const std::string &line) {
    static const char *keywords[] = {
        "import ", "from ", "def ", "class ", "return ", "if ", "elif ",
        "else:", "for ", "while ", "try:", "except", "finally:", "with ",
        "raise ", "yield ", "assert ", "break", "continue", "pass", "global ",
        "nonlocal ", "lambda ", "print(", "self.", "@",
    };
    auto t = trim_left(line);
    for (auto kw : keywords) {
        if (t.find(kw) == 0) return true;
    }
    return false;
}

// Count sequential commented-out code lines (>3 consecutive code-like comments)
static int count_commented_out_code(const std::vector<std::string> &lines) {
    int max_run = 0, current_run = 0;
    for (const auto &line : lines) {
        auto t = trim_left(line);
        if (t.size() >= 1 && t[0] == '#' && looks_like_code(t.substr(1))) {
            ++current_run;
            max_run = std::max(max_run, current_run);
        } else {
            current_run = 0;
        }
    }
    return max_run;
}

// ---------------------------------------------------------------------------
// Function-level analysis
// ---------------------------------------------------------------------------

struct FunctionInfo {
    std::string name;
    int start_line = 0;
    int end_line = 0;
    int indent = 0;
    int param_count = 0;
    int cyclomatic = 1;        // base = 1
    int nesting_depth = 0;     // max indentation within function (in levels)
    int line_count = 0;
    bool has_silent_except = false;
    bool has_bare_except = false;
    bool has_range_len = false;
    bool has_dangerous_div = false;
    int isinstance_count = 0;
    bool has_global = false;
    bool has_nested_func = false;
    bool has_missing_annotations = false;
    int missing_annotation_count = 0;
};

static int count_params(const std::string &line) {
    // Find opening paren in "def foo(" or "def foo(self, ..."
    auto lp = line.find('(');
    if (lp == std::string::npos) return 0;
    auto rp = line.rfind(')');
    if (rp == std::string::npos || rp <= lp) return 0;
    std::string params = line.substr(lp + 1, rp - lp - 1);
    if (params.empty()) return 0;

    // Simple comma counting (doesn't handle nested generics perfectly)
    int count = 1;
    int depth = 0;
    for (char c : params) {
        if (c == '(' || c == '[' || c == '{') ++depth;
        else if (c == ')' || c == ']' || c == '}') --depth;
        else if (c == ',' && depth == 0) ++count;
    }
    // Remove 'self' and 'cls' from count
    std::istringstream ss(params);
    std::string token;
    while (ss >> token) {
        token.erase(std::remove(token.begin(), token.end(), ','), token.end());
        if (token == "self" || token == "cls") --count;
    }
    return std::max(0, count);
}

// Count params that lack type annotations in a function signature
// Returns number of unannotated params (excluding self/cls, *args, **kwargs)
static int count_missing_annotations(const std::string &line) {
    auto lp = line.find('(');
    if (lp == std::string::npos) return 0;
    auto rp = line.rfind(')');
    if (rp == std::string::npos || rp <= lp) return 0;
    std::string params_str = line.substr(lp + 1, rp - lp - 1);
    if (params_str.empty()) return 0;

    // Split by comma, respecting nested brackets
    std::vector<std::string> params;
    int depth = 0;
    std::string current;
    for (char c : params_str) {
        if ((c == '(' || c == '[' || c == '{')) ++depth;
        else if ((c == ')' || c == ']' || c == '}')) --depth;
        else if (c == ',' && depth == 0) {
            params.push_back(current);
            current.clear();
            continue;
        }
        current += c;
    }
    if (!current.empty()) params.push_back(current);

    int missing = 0;
    for (auto &p : params) {
        p = trim_left(p);
        // Skip self, cls, *args, **kwargs, and bare *
        if (p == "self" || p == "cls") continue;
        if (p.find('*') != std::string::npos) continue;
        if (p.find('/') != std::string::npos) continue; // positional-only marker
        // Has annotation if it contains ':'
        if (p.find(':') == std::string::npos) {
            ++missing;
        }
    }
    return missing;
}

// Detect if this line contains `except ...: pass` pattern
static bool is_silent_except(const std::string &line, const std::vector<std::string> &lines, int idx) {
    auto t = trim_left(line);
    if (t.find("except") != 0) return false;
    // Check if next non-blank line is just "pass"
    for (size_t i = idx + 1; i < lines.size(); ++i) {
        if (is_blank(lines[i]) || is_comment(lines[i])) continue;
        auto nt = trim_left(lines[i]);
        return nt == "pass";
    }
    return false;
}

// Detect bare except: line begins with "except:" (no exception type)
static bool is_bare_except(const std::string &line) {
    auto t = trim_left(line);
    return t.find("except:") == 0 || t.find("except :") == 0;
}

// Check for `range(len(` pattern
static bool has_range_len_pattern(const std::string &line) {
    return line.find("range(len(") != std::string::npos;
}

// Check for division without zero check
static bool has_dangerous_division(const std::string &line, const std::vector<std::string> &func_body) {
    auto t = trim_left(line);
    if (t.find('#') == 0) return false;  // comment

    // Simple: find `/` operator (not `//` or `/=` and not in string)
    bool in_string = false;
    for (size_t i = 0; i < line.size(); ++i) {
        if (line[i] == '"' || line[i] == '\'') in_string = !in_string;
        if (!in_string && line[i] == '/' && i + 1 < line.size() && line[i+1] != '/' && line[i+1] != '=') {
            // Check if this function has a zero-check before
            bool has_zero_check = false;
            for (const auto &fl : func_body) {
                if (fl.find("== 0") != std::string::npos ||
                    fl.find("!= 0") != std::string::npos ||
                    fl.find("> 0") != std::string::npos ||
                    fl.find("is None") != std::string::npos ||
                    fl.find("len(") != std::string::npos) {
                    has_zero_check = true;
                    break;
                }
            }
            if (!has_zero_check) return true;
        }
    }
    return false;
}

// Count isinstance calls in a line
static int count_isinstance(const std::string &line) {
    int count = 0;
    size_t pos = 0;
    while ((pos = line.find("isinstance", pos)) != std::string::npos) {
        ++count;
        pos += 10;
    }
    return count;
}

// ---------------------------------------------------------------------------
// Main analysis
// ---------------------------------------------------------------------------

static std::vector<json> analyze_file(const std::string &filepath) {
    std::vector<json> findings;

    std::ifstream file(filepath);
    if (!file.is_open()) {
        json f;
        f["file"] = filepath;
        f["line"] = 0;
        f["severity"] = "MAJOR";
        f["category"] = "io";
        f["title"] = "无法打开文件";
        f["message"] = "无法读取文件: " + filepath;
        findings.push_back(std::move(f));
        return findings;
    }

    std::vector<std::string> lines;
    {
        std::string line;
        while (std::getline(file, line)) {
            lines.push_back(line);
        }
    }

    // --- File-level checks ---

    // File too long
    int total_lines = (int)lines.size();
    if (total_lines > 1000) {
        json f;
        f["file"] = filepath;
        f["line"] = 1;
        f["severity"] = "MAJOR";
        f["category"] = "style";
        f["title"] = "文件过长";
        std::ostringstream msg;
        msg << "文件共 " << total_lines << " 行（建议不超过 1000 行）。";
        f["message"] = msg.str();
        findings.push_back(std::move(f));
    }

    // Commented-out code blocks (>3 consecutive code-like comment lines)
    int commented_lines = count_commented_out_code(lines);
    if (commented_lines >= 4) {
        json f;
        f["file"] = filepath;
        f["line"] = 1;
        f["severity"] = "MAJOR";
        f["category"] = "documentation";
        f["title"] = "注释掉的代码块";
        std::ostringstream msg;
        msg << "检测到 " << commented_lines << " 行连续的注释代码。";
        f["message"] = msg.str();
        findings.push_back(std::move(f));
    }

    // --- Function-level analysis ---
    // Track current function context using indentation
    std::vector<FunctionInfo> functions;
    FunctionInfo current;
    bool in_function = false;

    for (int i = 0; i < total_lines; ++i) {
        const auto &raw = lines[i];
        std::string trimmed = trim_left(raw);
        int ind = indent_level(raw);

        if (is_blank(raw) || is_comment(raw)) {
            if (in_function) current.line_count++;
            continue;
        }

        // Detect function definition: line starts with "def " (after whitespace)
        if (trimmed.find("def ") == 0) {
            // Finalize previous function
            if (in_function) {
                current.end_line = i;
                functions.push_back(current);
            }

            // Start new function
            in_function = true;
            current = FunctionInfo{};
            current.start_line = i + 1;  // 1-based line
            current.indent = ind;

            // Extract function name
            auto name_start = trimmed.find("def ") + 4;
            auto name_end = trimmed.find('(');
            if (name_end != std::string::npos) {
                current.name = trimmed.substr(name_start, name_end - name_start);
            } else {
                current.name = trimmed.substr(name_start);
            }
            // Remove any trailing whitespace from name
            current.name.erase(std::find_if(current.name.rbegin(), current.name.rend(),
                [](unsigned char c) { return !std::isspace(c); }).base(), current.name.end());

            current.param_count = count_params(trimmed);
            current.missing_annotation_count = count_missing_annotations(trimmed);
            current.has_missing_annotations = (current.missing_annotation_count > 0);
            current.line_count = 1;
            continue;
        }

        // Detect nested function
        if (trimmed.find("def ") != std::string::npos && in_function && ind > current.indent) {
            current.has_nested_func = true;
            // Still counts as a line but handled separately
        }

        // Analyze lines within function
        if (in_function && ind >= current.indent) {
            current.line_count++;

            // Branch keywords for cyclomatic complexity
            if (trimmed.find("if ") == 0 || trimmed.find("elif ") == 0 ||
                trimmed.find("for ") == 0 || trimmed.find("while ") == 0) {
                current.cyclomatic++;
            }
            if (trimmed.find("except") == 0 || trimmed.find("except ") == 0) {
                current.cyclomatic++;
            }
            if (trimmed.find("and ") != std::string::npos || trimmed.find("or ") != std::string::npos) {
                // count and/or for additional complexity (rough estimate)
                size_t pos = 0;
                while ((pos = trimmed.find(" and ", pos)) != std::string::npos) {
                    // Don't count if inside a string (rough)
                    current.cyclomatic++;
                    pos += 5;
                }
                pos = 0;
                while ((pos = trimmed.find(" or ", pos)) != std::string::npos) {
                    current.cyclomatic++;
                    pos += 4;
                }
            }

            // Nesting depth: track relative to function indent
            int relative_indent = (ind - current.indent) / 4;  // ~levels
            current.nesting_depth = std::max(current.nesting_depth, relative_indent);

            // Silent exception
            if (is_silent_except(raw, lines, i)) {
                current.has_silent_except = true;
            }

            // Bare except
            if (is_bare_except(raw)) {
                current.has_bare_except = true;
            }

            // range(len(...))
            if (has_range_len_pattern(raw)) {
                current.has_range_len = true;
            }

            // Dangerous division
            // Collect function body for context-aware check
            std::vector<std::string> func_body;
            for (int j = current.start_line - 1; j <= i && j < total_lines; ++j) {
                if (indent_level(lines[j]) >= current.indent) {
                    func_body.push_back(lines[j]);
                }
            }
            if (has_dangerous_division(raw, func_body)) {
                current.has_dangerous_div = true;
            }

            // isinstance count
            current.isinstance_count += count_isinstance(raw);

            // Global statement
            if (trimmed.find("global ") == 0) {
                current.has_global = true;
            }
        }

        // End of function: line at same or lesser indentation as function def
        if (in_function && ind <= current.indent && !is_blank(raw) && !is_comment(raw) && trimmed.find("def ") != 0) {
            // Still within the function if same indent and not blank (e.g., class-level)
            // Actually, if at same indent as def, it's outside the function body
            // But we handle this by checking if it's a class-level line or decorator
        }
    }

    // Finalize last function
    if (in_function) {
        current.end_line = total_lines;
        functions.push_back(current);
    }

    // --- Generate findings for each function ---
    for (const auto &func : functions) {
        // Cyclomatic complexity > 10
        if (func.cyclomatic > 10) {
            json f;
            f["file"] = filepath;
            f["line"] = func.start_line;
            f["severity"] = "MAJOR";
            f["category"] = "complexity";
            f["title"] = "圈复杂度过高";
            std::ostringstream msg;
            msg << "函数 " << func.name << " 的圈复杂度为 " << func.cyclomatic
                << "，超过阈值 10。";
            f["message"] = msg.str();
            findings.push_back(std::move(f));
        }

        // Function too long > 50 lines
        if (func.line_count > 50) {
            json f;
            f["file"] = filepath;
            f["line"] = func.start_line;
            f["severity"] = "MAJOR";
            f["category"] = "complexity";
            f["title"] = "函数过长";
            std::ostringstream msg;
            msg << "函数 " << func.name << " 有 " << func.line_count << " 行，超过阈值 50 行。";
            f["message"] = msg.str();
            findings.push_back(std::move(f));
        }

        // Too many params > 6
        if (func.param_count > 6) {
            json f;
            f["file"] = filepath;
            f["line"] = func.start_line;
            f["severity"] = "MAJOR";
            f["category"] = "complexity";
            f["title"] = "参数过多";
            std::ostringstream msg;
            msg << "函数 " << func.name << " 有 " << func.param_count << " 个参数，超过阈值 6。";
            f["message"] = msg.str();
            findings.push_back(std::move(f));
        }

        // Excessive nesting > 5 levels
        if (func.nesting_depth > 5) {
            json f;
            f["file"] = filepath;
            f["line"] = func.start_line;
            f["severity"] = "MAJOR";
            f["category"] = "complexity";
            f["title"] = "嵌套过深";
            std::ostringstream msg;
            msg << "函数 " << func.name << " 的嵌套深度为 " << func.nesting_depth
                << "，超过阈值 5。";
            f["message"] = msg.str();
            findings.push_back(std::move(f));
        }

        // Silent exception (except: pass)
        if (func.has_silent_except) {
            json f;
            f["file"] = filepath;
            f["line"] = func.start_line;
            f["severity"] = "MAJOR";
            f["category"] = "bug";
            f["title"] = "静默的异常捕获";
            f["message"] = "使用 except: pass 静默忽略了异常。";
            findings.push_back(std::move(f));
        }

        // Bare except
        if (func.has_bare_except) {
            json f;
            f["file"] = filepath;
            f["line"] = func.start_line;
            f["severity"] = "MAJOR";
            f["category"] = "bug";
            f["title"] = "裸 except";
            f["message"] = "使用裸 except: 捕获所有异常，建议指定具体异常类型。";
            findings.push_back(std::move(f));
        }

        // range(len(...))
        if (func.has_range_len) {
            json f;
            f["file"] = filepath;
            f["line"] = func.start_line;
            f["severity"] = "MAJOR";
            f["category"] = "bug";
            f["title"] = "建议使用 enumerate";
            f["message"] = "使用 range(len(...)) 迭代索引，应改用 enumerate。";
            findings.push_back(std::move(f));
        }

        // Dangerous division
        if (func.has_dangerous_div) {
            json f;
            f["file"] = filepath;
            f["line"] = func.start_line;
            f["severity"] = "MAJOR";
            f["category"] = "bug";
            f["title"] = "可能的除零错误";
            f["message"] = "函数中存在除法操作，但除数没有零值检查。";
            findings.push_back(std::move(f));
        }

        // Too many isinstance checks (≥ 3)
        if (func.isinstance_count >= 3) {
            json f;
            f["file"] = filepath;
            f["line"] = func.start_line;
            f["severity"] = "MAJOR";
            f["category"] = "design";
            f["title"] = "过多的 isinstance 检查";
            std::ostringstream msg;
            msg << "函数 " << func.name << " 包含 " << func.isinstance_count
                << " 次 isinstance 类型检查，可能缺少多态设计。";
            f["message"] = msg.str();
            findings.push_back(std::move(f));
        }

        // Global statement
        if (func.has_global) {
            json f;
            f["file"] = filepath;
            f["line"] = func.start_line;
            f["severity"] = "MAJOR";
            f["category"] = "style";
            f["title"] = "使用了 global 语句";
            std::ostringstream msg;
            msg << "函数 " << func.name << " 使用了 global 语句。";
            f["message"] = msg.str();
            findings.push_back(std::move(f));
        }

        // Missing type annotations in function signature
        if (func.has_missing_annotations) {
            json f;
            f["file"] = filepath;
            f["line"] = func.start_line;
            f["severity"] = "MAJOR";
            f["category"] = "style";
            f["title"] = "函数参数缺少类型注解";
            std::ostringstream msg;
            msg << "函数 " << func.name << " 有 " << func.missing_annotation_count
                << " 个参数缺少类型注解，建议为所有参数添加类型注解以提高可维护性。";
            f["message"] = msg.str();
            findings.push_back(std::move(f));
        }

        // Nested function
        if (func.has_nested_func) {
            json f;
            f["file"] = filepath;
            f["line"] = func.start_line;
            f["severity"] = "MAJOR";
            f["category"] = "design";
            f["title"] = "嵌套函数";
            std::ostringstream msg;
            msg << "函数 " << func.name << " 包含嵌套函数定义。";
            f["message"] = msg.str();
            findings.push_back(std::move(f));
        }
    }

    return findings;
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

int main(int argc, char *argv[]) {
    if (argc < 2) {
        std::cerr << "Usage: static_analyzer <file1.py> [file2.py ...]" << std::endl;
        return 1;
    }

    json output = json::array();

    for (int i = 1; i < argc; ++i) {
        std::string path = argv[i];
        if (!fs::exists(path)) {
            json f;
            f["file"] = path;
            f["line"] = 0;
            f["severity"] = "MAJOR";
            f["category"] = "io";
            f["title"] = "文件不存在";
            f["message"] = "文件不存在: " + path;
            output.push_back(std::move(f));
            continue;
        }

        auto file_findings = analyze_file(path);
        for (auto &f : file_findings) {
            output.push_back(std::move(f));
        }
    }

    std::cout << output.dump(2) << std::endl;
    return 0;
}
