"""pytest 共享夹具：让插件包以「顶层包名」可导入.

本仓库的 ``__init__.py`` 就在仓库根，即**包根等于检出根**；而测试一律按顶层包名
导入（``from astrbot_plugin_ots_memory.xxx import``）。只有「检出根的父目录」进了
``sys.path`` 时这才能成立——本地凑巧满足，CI 的检出目录名则不保证，于是会整片
收集失败，连带 ``coverage --source`` 也找不到包、写出空报告。

这里不做 ``sys.path`` 造包，而是注册一个 meta path finder（见
``meta_path.py``），把仓库根以固定包名暴露给 import 系统：与检出目录名无关，
不往文件系统写符号链接/副本。

注册逻辑放在普通模块 ``package_view`` 而非本文件：conftest 由 pytest 按 rootdir
特殊加载，写 ``import conftest`` 的用法在「pytest 之外」（如覆盖率启动器）会失效。

注意：本文件只在 pytest 收集阶段才被导入，而 ``coverage run --source=<包名>``
的解析早于这一步。需要覆盖率口径时请用 ``python -m tests.run_coverage``
（同一进程内先建包视图、再启动 coverage）。
"""

from __future__ import annotations

# 导入即注册包视图，供下方测试模块的顶层包名导入使用
from .package_view import PACKAGE_VIEW_MODE as PACKAGE_VIEW_MODE

__all__ = ["PACKAGE_VIEW_MODE"]
