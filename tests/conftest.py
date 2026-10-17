"""pytest 共享夹具：让插件包以「顶层包名」可导入.

本仓库目录名即包名（``astrbot_plugin_ots_memory``），模块内一律写作
``from astrbot_plugin_ots_memory.xxx import``；但仓库目录常常并不叫这个名字
（CI 检出目录名随机），于是在仓库根直接跑 ``pytest`` 会因「没有同名包」而
整片收集失败。

这里不做 ``sys.path`` 造包，而是注册一个 meta path finder（见
``tests/meta_path.py``），把仓库根以固定包名暴露出去。好处有二：

1. 不依赖检出目录名，也不需要往父目录写符号链接（旧方案在只读检出目录或
   并发进程下会互相踩，且要为 Windows 退化到 copytree）；
2. 覆盖率口径与之一致——``coverage run --source=<包名>`` 依赖的正是
   「这个包能从哪导入」，包视图走 import 系统后，直接裸跑
   ``coverage run --source=astrbot_plugin_ots_memory -m pytest`` 即可命中，
   不必再把「仓库的父目录」塞进 ``PYTHONPATH``。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

# 仓库根目录（本文件位于 tests/ 下）
_REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_meta_path():
    """按路径加载同目录的 meta_path.py（不依赖 pytest 的 sys.path 插入策略）."""
    spec = importlib.util.spec_from_file_location(
        "_ots_memory_meta_path", Path(__file__).with_name("meta_path.py")
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# 收集前完成注册：conftest 先于测试模块导入，故测试里的
# `from astrbot_plugin_ots_memory.client import ...` 一定能命中。
PACKAGE_VIEW_MODE = _load_meta_path().install(str(_REPO_ROOT))
