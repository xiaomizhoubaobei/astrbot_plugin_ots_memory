"""插件包视图：用 meta path finder 让「仓库目录」冒充「顶层包」.

为什么不用 ``sys.path`` + 造包目录：
``sys.path`` 只能指定「从哪个目录里找包」，而本仓库的**仓库根自身就是包根**
（``__init__.py`` 在仓库根，模块写作 ``from astrbot_plugin_ots_memory.client import``）。
仓库目录一般**不叫**这个包名，于是直接跑 ``pytest`` 时既没有可导入的包，也会
连带把覆盖率口径带偏——``coverage run --source=<包名>`` 找不到包就直接报
``No module named``。

本模块注册一个 meta path finder，把「与本目录同级的仓库根」以固定包名
``astrbot_plugin_ots_memory`` 暴露出去，效果等同「从父目录导入同名目录」，
但**不依赖检出目录名、也不影子化真实的同名包**：

- 环境里已有真正的可导入同名包（如站点里装了插件包）→ 让位，不抢；
- 检出目录名恰好就是包名（如 GitHub Actions 的 ``$GITHUB_WORKSPACE``）→
  交给默认机制，无需介入；
- 其余情况 → 由本 finder 提供包视图。

实现要求：本文件在 pytest 收集阶段被导入，届时 ``astrbot_plugin_ots_memory``
的导入链（``main.py`` 依赖 AstrBot 宿主）尚未就绪，故这里**只用标准库**，
不得 import 任何第三方或插件内模块。
"""

from __future__ import annotations

import importlib.abc
import importlib.machinery
import importlib.util
import sys
from types import ModuleType
from typing import Optional, Sequence

# 插件包名：与 AstrBot 宿主的加载口径一致
PACKAGE_NAME = "astrbot_plugin_ots_memory"


class _PackageAliasFinder(importlib.abc.MetaPathFinder):
    """把 ``package_root`` 以 ``package_name`` 的身份暴露给 import 系统."""

    def __init__(self, package_name: str, package_root: str) -> None:
        self.package_name = package_name
        self.package_root = package_root

    def find_spec(
        self,
        fullname: str,
        path: Optional[Sequence[str]] = None,
        target: Optional[ModuleType] = None,
    ) -> Optional[importlib.machinery.ModuleSpec]:
        # 只接管包本身：子模块 ``xxx.client`` 会自然落到本 spec 的
        # submodule_search_locations 上，由默认的路径查找器继续解析。
        if fullname != self.package_name:
            return None
        return importlib.util.spec_from_file_location(
            fullname,
            f"{self.package_root}/__init__.py",
            submodule_search_locations=[self.package_root],
        )


def install(package_root: str, package_name: str = PACKAGE_NAME) -> str:
    """注册包视图并返回本次采取的策略名（幂等）.

    策略：``existing``=已存在可解析的同名包，未介入；``alias``=已注册别名
    finder。

    为什么**不再**对「检出目录本身就叫包名」的形态开绿灯（早期写过
    ``native`` 直通）：目录名是包名并不等于包可导入——`__init__.py` 恰好
    在根目录时，只有「根的父目录」进了 `sys.path` 才成立，而 pytest 默认只
    插入 rootdir 自身。放行会造成「本地目录名侥幸对上、CI 随机名必挂」的
    两面派行为。统一走 finder，任何目录名都只有一条代码路径。
    """
    if package_name in sys.modules:
        return "existing"

    # 有真实同名包可解析时让位，避免影子化站点里安装的插件包。
    try:
        probe = importlib.util.find_spec(package_name)
    except (ImportError, ValueError):
        probe = None
    if probe is not None:
        return "existing"

    finder = _PackageAliasFinder(package_name, package_root)
    # 插到最前：优先于默认 finder，但上面的检查已保证不会盖住真实包。
    sys.meta_path.insert(0, finder)
    return "alias"
