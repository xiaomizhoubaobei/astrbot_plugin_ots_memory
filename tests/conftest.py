"""pytest 共享夹具：让插件包以「顶层包名」可导入.

本仓库目录名即包名（``astrbot_plugin_ots_memory``），但在仓库根直接跑
``pytest`` 时父目录里没有同名包，``from astrbot_plugin_ots_memory.client import``
会失败。此处在测试收集前构造一个临时包视图：在同名临时目录下放一个指回
仓库根的符号链接（不支持符号链接时退化为复制），再加入 ``sys.path``。
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

# 插件包名：与 AstrBot 宿主的加载口径一致
_PACKAGE_NAME = "astrbot_plugin_ots_memory"
# 仓库根目录（本文件位于 tests/ 下）
_REPO_ROOT = Path(__file__).resolve().parents[1]
# 临时包视图的宿主目录
_VIEW_ROOT = Path(tempfile.gettempdir()) / "ots-memory-test-view"

_installed = False


def _ensure_package_view() -> None:
    """确保插件包可按顶层包名导入（幂等）."""
    global _installed
    if _installed:
        return

    # 仓库目录本身已是该包名时，无需垫片
    if _REPO_ROOT.name == _PACKAGE_NAME:
        _installed = True
        return

    _VIEW_ROOT.mkdir(parents=True, exist_ok=True)
    link = _VIEW_ROOT / _PACKAGE_NAME
    if link.is_symlink() or link.exists():
        if link.is_symlink() or link.is_dir():
            try:
                link.unlink()
            except OSError:
                shutil.rmtree(link, ignore_errors=True)

    try:
        os.symlink(_REPO_ROOT, link, target_is_directory=True)
    except (OSError, NotImplementedError):
        # 退化路径：不支持符号链接的环境（如部分 Windows 配置）用复制
        shutil.copytree(_REPO_ROOT, link, dirs_exist_ok=True)

    if str(_VIEW_ROOT) not in sys.path:
        sys.path.insert(0, str(_VIEW_ROOT))
    _installed = True


_ensure_package_view()
