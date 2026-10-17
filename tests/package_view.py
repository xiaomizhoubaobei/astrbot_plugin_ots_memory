"""建立插件包视图：把仓库根暴露为顶层包名 ``astrbot_plugin_ots_memory``.

供两处复用，保证「测试可导入」与「coverage 可解析 --source」口径一致：

- ``tests/conftest.py``：pytest 收集前注册，测试里的顶层包名导入才能命中；
- ``tests/run_coverage.py``：coverage 启动前注册（它解析 ``--source`` 早于 pytest）。

本模块只依赖标准库，且导入即完成注册（幂等），调用方无需关心顺序。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

# 仓库根目录（本文件位于 tests/ 下）
REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_meta_path() -> Any:
    """按路径加载同目录的 meta_path.py（不依赖 sys.path 的插入策略）."""
    spec = importlib.util.spec_from_file_location(
        "_ots_memory_meta_path", Path(__file__).with_name("meta_path.py")
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# 导入即注册：返回策略名（alias=已注册 finder，existing=已有真实同名包）
PACKAGE_VIEW_MODE = _load_meta_path().install(str(REPO_ROOT))
