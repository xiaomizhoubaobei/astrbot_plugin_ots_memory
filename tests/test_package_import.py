"""锁定「插件包能被顶层包名导入」这一 CI 契约.

背景：历史上的 CI 收集失败（``ModuleNotFoundError: No module named
'astrbot_plugin_ots_memory'``）不是业务代码的锅，而是**包视图**没建立——
测试里写 ``from astrbot_plugin_ots_memory.client import ...``，但仓库目录
本身并不叫这个名字。

本用例把该契约固化下来：无论检出目录叫什么、有没有设置 ``PYTHONPATH``，
测试进程里都必须能按顶层包名导入，且解析到的就是本仓库的文件；否则
``coverage run --source=astrbot_plugin_ots_memory`` 同样会因找不到包而空跑。
"""

from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path

import conftest

_PACKAGE_NAME = "astrbot_plugin_ots_memory"
_REPO_ROOT = Path(__file__).resolve().parents[1]


def test_package_is_importable_by_top_level_name() -> None:
    """按顶层包名可导入，且解析到仓库根内的 ``__init__.py``."""
    module = importlib.import_module(_PACKAGE_NAME)
    assert Path(module.__file__).resolve() == (_REPO_ROOT / "__init__.py").resolve()


def test_coverage_source_target_is_resolvable() -> None:
    """``coverage run --source=<包名>`` 依赖的 spec 查找必须命中."""
    spec = importlib.util.find_spec(_PACKAGE_NAME)
    assert spec is not None
    # 包视图生效时，子模块搜索路径即仓库根（含 client.py）
    assert _REPO_ROOT.resolve() in {Path(p).resolve() for p in spec.submodule_search_locations or []}


def test_submodule_import_follows_the_view() -> None:
    """子模块随包视图一起解析，不依赖检出目录名."""
    client = importlib.import_module(f"{_PACKAGE_NAME}.client")
    assert Path(client.__file__).resolve() == (_REPO_ROOT / "client.py").resolve()


def test_package_view_reports_mode() -> None:
    """包视图策略落在白名单内（alias=注册了 finder，existing=已有真实同名包）."""
    assert conftest.PACKAGE_VIEW_MODE in {"alias", "existing"}
