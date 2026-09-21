#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""report-page-composer / scripts/style_benchmark_audit.py  —— SHIM（转发壳）

真正的实现已收敛到 **唯一一份**：

    skills/report-style-benchmark/scripts/style_benchmark_audit.py

本文件只做两件事：

  1) 定位真源脚本 —— 默认按同仓库相对路径 `../../report-style-benchmark/scripts/`
     查找；也可用环境变量 `REPORT_STYLE_BENCHMARK_SCRIPTS` 覆盖（便于 skill 被
     复制到别处执行时仍能指向真源）。
  2) 若调用方没有显式给 `--baseline`，自动补上真源 skill 的 `samples_baseline.json`，
     这样 `--baseline-only` 不带参数也能直接做基线自检。

## 为什么保留 shim，而不是删掉这个文件

composer 的 `SKILL.md` 与 `references/` 里大量写着 `scripts/style_benchmark_audit.py`，
历史执行记录也都按这个路径。保留同名入口可以让既有引用全部继续有效，同时把实现
收敛成一份。

## 为什么必须收敛（2026-09-17 事故）

这里原本有一份**独立副本**，与 benchmark 版字节不同、且各自配了一份
`samples_baseline.json`。两份 baseline 的口径不同（全文档扫描 vs audit p2 单页），
导致 `--baseline` 的回归结论取决于你碰巧调用了哪一份。副本已于 2026-09-18 删除。

退出码与真源完全一致：0 无阻断项，1 有阻断项，2 输入非法。
"""

from __future__ import annotations

import importlib.util
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_REAL_REL = os.path.join("..", "..", "report-style-benchmark", "scripts")


def _resolve_real_scripts_dir():
    """返回真源 scripts 目录；找不到返回 None。"""
    candidates = []
    env = os.environ.get("REPORT_STYLE_BENCHMARK_SCRIPTS")
    if env:
        candidates.append(os.path.abspath(env))
    candidates.append(os.path.normpath(os.path.join(_HERE, _REAL_REL)))
    for c in candidates:
        if os.path.isfile(os.path.join(c, "style_benchmark_audit.py")):
            return c
    return None


def _load_real(scripts_dir):
    """按文件路径加载真源模块，避免依赖 sys.path 上恰好有同名模块。"""
    path = os.path.join(scripts_dir, "style_benchmark_audit.py")
    spec = importlib.util.spec_from_file_location("_benchmark_style_audit_real", path)
    if spec is None or spec.loader is None:
        sys.stderr.write(f"ERROR: 无法加载真源脚本 {path}\n")
        return None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def main():
    scripts_dir = _resolve_real_scripts_dir()
    if scripts_dir is None:
        sys.stderr.write(
            "ERROR: 找不到 report-style-benchmark 的真源脚本。\n"
            "  期望位置：" + os.path.normpath(os.path.join(_HERE, _REAL_REL)) + "\n"
            "  可用环境变量 REPORT_STYLE_BENCHMARK_SCRIPTS 指向真源的 scripts 目录。\n"
            "  说明：本文件是转发壳，实现只有一份，在 report-style-benchmark 下。\n"
        )
        return 2

    argv = sys.argv[1:]

    # 未显式指定 --baseline 时补默认值，让 --baseline-only 能直接跑。
    if "--baseline" not in argv and "--baseline=" not in argv:
        default_baseline = os.path.join(scripts_dir, "samples_baseline.json")
        if os.path.isfile(default_baseline):
            argv = argv + ["--baseline", default_baseline]

    mod = _load_real(scripts_dir)
    if mod is None:
        return 2

    saved_argv = sys.argv
    try:
        sys.argv = [os.path.join(scripts_dir, "style_benchmark_audit.py")] + argv
        return mod.main()
    except SystemExit as e:  # 真源用 sys.exit(main()) 时透传退出码
        return e.code if isinstance(e.code, int) else 2
    finally:
        sys.argv = saved_argv


if __name__ == "__main__":
    sys.exit(main())
