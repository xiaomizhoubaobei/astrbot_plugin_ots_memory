"""测试包：以 ``python -m tests.<模块>`` 的形式运行测试辅助脚本.

不加本文件的话 ``tests`` 只是 pytest 的 rootdir 子目录，无法被 ``-m`` 引用；
而覆盖率脚本（``tests/run_coverage.py``）必须作为模块启动——它要在**同一个
解释器进程内**先建好包视图，再调用 coverage 的 main，否则 coverage 解析
``--source=<包名>`` 时包还不存在。
"""
