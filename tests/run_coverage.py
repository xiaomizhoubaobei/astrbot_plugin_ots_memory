"""在「包视图已就位」的前提下跑覆盖率，供 CI 与本地共用.

为什么不能直接 ``coverage run --source=<包名> -m pytest``：
coverage 在**启动阶段**就解析 ``--source``，而彼时 pytest 还没加载
``conftest.py``——插件包视图尚未建立，于是它只会警告
``Module ... was never imported`` 并写出空报告（退出码 2）。

本脚本把顺序倒过来：先在不导入插件包的前提下建好包视图，再在**同一进程**里
启动 coverage 与 pytest。等价于 ``coverage run``，只是包名此刻已可解析。

用法::

    python -m tests.run_coverage                       # 跑 tests + 打印报告 + 写 coverage.xml
    python -m tests.run_coverage --report-only         # 仅打印已有数据
    python -m tests.run_coverage -- -k signing         # ``--`` 之后的参数透传给 pytest
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

from coverage import Coverage

# 关键顺序：先建包视图（此处**不**导入插件包本身，否则 coverage 会报
# "module was previously imported, but not measured"），再构造 Coverage。
from tests import package_view  # noqa: F401  # 导入即注册包视图

PACKAGE_NAME = "astrbot_plugin_ots_memory"
_REPO_ROOT = Path(__file__).resolve().parents[1]
_XML_PATH = _REPO_ROOT / "coverage.xml"
# 与 pyproject.toml 的 coverage.report.omit 口径一致（此处不读配置文件，
# 免得 CI 与本地因配置文件位置差异而漂移）
_OMIT = ["tests/*", "ai-audit/*"]
# pytest 侧透传参数：``--`` 之后原样交给 pytest
_PYTEST_ARGS = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else ["tests"]


def _mark_package_measured() -> None:
    """让 coverage 认下「包名已被测量」，否则报告会判它从没被测过.

    coverage 的 ``--source=<包名>`` 是按**调用方 frame 的模块名**匹配的
    （见 ``coverage.inorout.name_for_module``）：只有当某段被测代码的
    ``__name__`` 以包名开头（如 ``astrbot_plugin_ots_memory.client``）时，
    才算这个 source 命中过。pytest 跑测试时，仓库根的 ``main.py`` 会以
    ``__main__`` / ``main`` 的名字出现，包名本身便一直「未命中」，收尾时
    coverage 就打出 ``Module ... was previously imported, but not measured``。

    这里在 coverage **已启动**的前提下，按真实包名导入一次包（其
    ``__init__.py`` 此时被记入数据，且模块名正是包名），source 即视为命中。
    文件本身 0 行，对覆盖率分子分母无影响。
    """
    importlib.import_module(PACKAGE_NAME)


def main() -> int:
    """跑测试、打印报告并写出 coverage.xml，返回退出码."""
    cov = Coverage(source=[PACKAGE_NAME], omit=_OMIT, config_file=False)

    if "--report-only" not in sys.argv:
        cov.start()
        _mark_package_measured()
        try:
            import pytest

            code = pytest.main(["-q", *_PYTEST_ARGS])
        finally:
            cov.stop()
            cov.save()
        if code != 0:
            # 测试失败时仍产出报告，便于分辨是「用例挂」还是「口径挂」
            cov.report()
            return int(code)

    cov.report()
    cov.xml_report(outfile=str(_XML_PATH))
    print(f"[coverage] XML 已写出：{_XML_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
