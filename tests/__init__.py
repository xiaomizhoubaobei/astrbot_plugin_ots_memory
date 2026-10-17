"""测试包：以 ``python -m tests.<模块>`` 的形式运行测试辅助脚本.

``-m`` 本身不强求本文件（没有它时 ``tests`` 会退化成命名空间包，照样能 ``-m``）。
真正的理由是 **pytest 的包相对导入**：``conftest.py`` 用 ``from .package_view
import ...`` 取包视图，只有 ``tests`` 是常规包时这条相对导入才稳定成立；
同时避免 ``tests`` 与站点里任何同名命名空间包混在一起，导致 ``python -m
tests.run_coverage`` 解析到别的目录。
"""
