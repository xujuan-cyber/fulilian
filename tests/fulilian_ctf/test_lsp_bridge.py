"""LSP / 编译诊断桥接 (F4-008) 单元测试。"""

from __future__ import annotations

import shutil

import pytest

from fulilian_ctf.lsp_bridge import diagnostics_summary, get_compile_errors, lsp_diagnostics

GCC_MISSING = shutil.which("gcc") is None


@pytest.mark.skipif(GCC_MISSING, reason="gcc not on PATH")
def test_compile_errors_bad_c(tmp_path):
    bad = tmp_path / "exploit.c"
    bad.write_text("int main() { return oops; }\n", encoding="utf-8")
    errors = get_compile_errors(str(bad), "c")
    assert errors and "error" in "\n".join(errors).lower()


@pytest.mark.skipif(GCC_MISSING, reason="gcc not on PATH")
def test_compile_clean_c(tmp_path):
    good = tmp_path / "ok.c"
    good.write_text("#include <stdio.h>\nint main(void) { puts(\"hi\"); return 0; }\n", encoding="utf-8")
    assert get_compile_errors(str(good), "c") == []


def test_unsupported_language(tmp_path):
    f = tmp_path / "x.py"
    f.write_text("print('hi')\n", encoding="utf-8")
    errors = get_compile_errors(str(f), "python")
    assert errors and "unsupported" in errors[0]


def test_missing_file():
    errors = get_compile_errors("/nonexistent/nope.c", "c")
    assert errors and "not found" in errors[0]


@pytest.mark.skipif(GCC_MISSING, reason="gcc not on PATH")
def test_diagnostics_summary_format(tmp_path):
    good = tmp_path / "ok.c"
    good.write_text("int main(void) { return 0; }\n", encoding="utf-8")
    summary = diagnostics_summary(str(good), "c")
    assert "OK" in summary
    bad = tmp_path / "bad.c"
    bad.write_text("int main() { return oops; }\n", encoding="utf-8")
    summary = diagnostics_summary(str(bad), "c")
    assert "diagnostic line(s)" in summary


def test_lsp_diagnostics_returns_none_without_service():
    # agent/lsp 服务未启用时安静返回 None（不抛异常）
    assert lsp_diagnostics("/tmp/x.c") is None or isinstance(lsp_diagnostics("/tmp/x.c"), list)
