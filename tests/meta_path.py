"""插件包视图：用 meta path finder 让「仓库目录」冒充「顶层包」.

为什么不用 ``sys.path`` + 造包目录：
``sys.path`` 只能指定「从哪个目录里找包」，而本仓库的**仓库根自身就是包根**
（``__init__.py`` 在仓库根，模块写作 ``from astrbot_plugin_ots_memory.client import``）。
仓库目录一般**不叫**这个包名，于是直接跑 ``pytest`` 时既没有可导入的包，也会
连带把覆盖率口径带偏——``coverage run --source=<包名>`` 找不到包就直接报
``No module named``。

本模块注册一个 meta path finder，把「与本目录同级的仓库根」以固定包名
``astrbot_plugin_ots_memory`` 暴露出去，效果等同「从父目录导入同名目录」，
但**不依赖检出目录名**：

- 环境里已有**可用的同名包**（能解析出包规格，且真实装着可运行的插件）→ 让位，不抢；
- 同名但只是单个模块、或没有 ``__init__.py`` 的命名空间包 → 不认，仍由本 finder 建立视图；
- 其余情况 → 由本 finder 提供包视图。

注意：**检出目录名是不是包名，不影响走哪条路径**。早期版本曾对「目录名恰好等于
包名」开绿灯直通默认机制，但目录名对上不等于可导入（只有「根的父目录」进了
``sys.path`` 才成立），会造成本地侥幸通过、CI 随机目录名必挂的两面派行为；
直通已被删除，任何目录名都只走本 finder 这一条代码路径。

实现要求：本文件在 pytest 收集阶段被导入，届时 ``astrbot_plugin_ots_memory``
的导入链（``main.py`` 依赖 AstrBot 宿主）尚未就绪，故这里**只用标准库**，
不得 import 任何第三方或插件内模块。
"""

from __future__ import annotations

import importlib.abc
import importlib.util
import pathlib
import sys
from types import ModuleType
from typing import Optional, Sequence

# 插件包名：与 AstrBot 宿主的加载口径一致
PACKAGE_NAME = "astrbot_plugin_ots_memory"
# 判定「真实同名包」时要求存在这两个文件：前者说明是常规包（不是命名空间包），
# 后者是本插件入口（缺了就不可能被宿主加载）
_PACKAGE_MARKER = "__init__.py"
_PLUGIN_ENTRY = "main.py"


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


def _has_usable_package(package_name: str) -> bool:
    """判断环境里是否已有**能正常使用**的同名包（而非同名模块/空壳命名空间包）.

    只认「带 ``__init__.py`` 的常规包」且其目录里确有本插件入口 ``main.py``：
    同名单文件模块、无 ``__init__.py`` 的命名空间包都没有 ``client`` 子模块，
    让位只会让测试 import 到错误对象、收集阶段就整片失败。
    """
    try:
        probe = importlib.util.find_spec(package_name)
    except (ImportError, ValueError):
        # 父包不存在、或名称为空等异常形态，一律视为「没有可用同名包」
        return False
    if probe is None:
        return False
    for location in probe.submodule_search_locations or ():
        package_dir = pathlib.Path(location)
        if (package_dir / _PACKAGE_MARKER).is_file() and (
            package_dir / _PLUGIN_ENTRY
        ).is_file():
            return True
    return False


def install(package_root: str, package_name: str = PACKAGE_NAME) -> str:
    """注册包视图并返回本次采取的策略名（幂等）.

    策略：``existing``=已存在可用的同名包，未介入；``alias``=已注册别名 finder。
    """
    if package_name in sys.modules:
        return "existing"

    if _has_usable_package(package_name):
        return "existing"

    finder = _PackageAliasFinder(package_name, package_root)
    # 插到最前：优先于默认 finder，但上面的检查已保证不会盖住真实可用的包。
    sys.meta_path.insert(0, finder)
    return "alias"
