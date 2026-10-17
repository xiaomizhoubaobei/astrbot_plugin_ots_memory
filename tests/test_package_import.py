"""锁定「插件包能被顶层包名导入」这一 CI 契约.

背景：历史上的 CI 收集失败（``ModuleNotFoundError: No module named
'astrbot_plugin_ots_memory'``）不是业务代码的锅，而是**包视图**没建立——
测试里写 ``from astrbot_plugin_ots_memory.client import ...``，但仓库目录
本身并不叫这个名字。

本用例把该契约固化下来：无论检出目录叫什么、有没有设置 ``PYTHONPATH``，
测试进程里都必须能按顶层包名导入本仓库的代码；否则
``coverage --source=astrbot_plugin_ots_memory`` 同样会因找不到包而空跑。

环境里已经装了**真实的同名插件包**时，``install`` 会主动让位（``existing``
模式），此时按顶层包名解析到的是装好的那份，不再指向本仓库——那种场合下
「解析到本仓库文件」的断言无从成立，跳过即可。

注意：所有判据都在**用例运行时**求值，不用模块级 ``skipif``。收集阶段求值会
踩到「模块已被上一个收集顺序导入、策略名却是别的进程状态」的坑。
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path

import pytest

from tests import package_view

_PACKAGE_NAME = "astrbot_plugin_ots_memory"
_REPO_ROOT = Path(__file__).resolve().parents[1]


def _owns_view() -> bool:
    """当前进程的包视图是否由本仓库接管（用例运行时求值）."""
    return package_view.PACKAGE_VIEW_MODE == "alias"


def _registered_finders() -> list[object]:
    """已在 ``sys.meta_path`` 中、指向本仓库的别名 finder."""
    return [
        f for f in sys.meta_path if getattr(f, "package_root", None) == str(_REPO_ROOT)
    ]


def test_package_view_mode_is_self_consistent() -> None:
    """策略名必须与环境自洽：要么真注册了 finder，要么确有同名包可让位."""
    assert package_view.PACKAGE_VIEW_MODE in {"alias", "existing"}
    registered = _registered_finders()
    if _owns_view():
        # alias 模式必须真的注册了 finder，而不是只返回了一个策略名
        assert registered, "alias 模式却没有注册包视图 finder"
    else:
        # 让位的前提是同名包确实可导入，不能凭空空转
        assert importlib.util.find_spec(_PACKAGE_NAME) is not None


def test_coverage_source_target_is_resolvable() -> None:
    """``coverage --source=<包名>`` 依赖的 spec 查找必须命中."""
    spec = importlib.util.find_spec(_PACKAGE_NAME)
    assert spec is not None
    found = {Path(p).resolve() for p in spec.submodule_search_locations or []}
    if _owns_view():
        assert _REPO_ROOT.resolve() in found


def test_package_is_importable_by_top_level_name() -> None:
    """按顶层包名可导入，且解析到仓库根内的 ``__init__.py``."""
    if not _owns_view():
        pytest.skip("环境里已有可用的同名插件包，包视图按设计让位（existing）")
    module = importlib.import_module(_PACKAGE_NAME)
    assert module.__file__ is not None
    assert Path(module.__file__).resolve() == (_REPO_ROOT / "__init__.py").resolve()


def test_submodule_import_follows_the_view() -> None:
    """子模块随包视图一起解析，不依赖检出目录名."""
    if not _owns_view():
        pytest.skip("环境里已有可用的同名插件包，包视图按设计让位（existing）")
    client = importlib.import_module(f"{_PACKAGE_NAME}.client")
    assert client.__file__ is not None
    assert Path(client.__file__).resolve() == (_REPO_ROOT / "client.py").resolve()
