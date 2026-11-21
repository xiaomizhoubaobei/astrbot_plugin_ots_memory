#!/usr/bin/env python3
"""Socket CLI 轻量封装 (stdlib only).

只依赖标准库：负责预检、调用 `socket`，并把 JSON 信封压成可读摘要。
脚本不读取、不打印 Token；凭据由 Socket CLI 从环境变量或本地配置获取。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Iterable, Sequence
from typing import Any

SOCKET_BIN = "socket"
MIN_NODE_MAJOR = 22
TIMEOUT_SECONDS = 600
TOKEN_ENV_VARS = ("SOCKET_CLI_API_TOKEN", "SOCKET_SECURITY_API_TOKEN")
ANALYTICS_METRICS = (
    "total_critical_alerts",
    "total_high_alerts",
    "total_medium_alerts",
    "total_low_alerts",
    "total_critical_added",
    "total_high_added",
    "total_medium_added",
    "total_low_added",
    "total_critical_prevented",
    "total_high_prevented",
    "total_medium_prevented",
    "total_low_prevented",
)


class HelperError(RuntimeError):
    """封装层的可预期错误 (helper error)."""


def _find_socket() -> str:
    """Return the socket executable path, or raise HelperError."""
    path = shutil.which(SOCKET_BIN)
    if not path:
        raise HelperError("未找到 socket，请先执行 `npm install -g socket`")
    return path


def _node_status() -> tuple[bool, str]:
    """Return whether Node.js is new enough, plus a human-readable note."""
    path = shutil.which("node")
    if not path:
        return False, "node 未安装（需要 22+）"
    try:
        proc = subprocess.run(
            [path, "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"无法执行 node: {exc.__class__.__name__}"
    version = proc.stdout.strip().lstrip("v")
    major = version.split(".", 1)[0]
    if not major.isdigit():
        return False, f"无法解析 node 版本: {version or '?'}"
    return int(major) >= MIN_NODE_MAJOR, f"node {version}"


def _run_socket(
    args: Sequence[str], *, dry_run: bool = False
) -> subprocess.CompletedProcess[str]:
    """Run socket with quiet global flags and return the finished process."""
    cmd = [_find_socket(), *args, "--no-banner", "--no-spinner"]
    if dry_run:
        cmd.append("--dry-run")
    try:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise HelperError(f"socket 调用超时（{TIMEOUT_SECONDS}s）") from exc
    except OSError as exc:
        raise HelperError(f"无法执行 socket: {exc.__class__.__name__}") from exc


def _load_envelope(proc: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    """Parse the JSON envelope from stdout, rejecting non-JSON noise."""
    text = proc.stdout.strip()
    if not text:
        raise HelperError(f"socket 无输出（exit={proc.returncode}）")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise HelperError(f"socket 返回非 JSON（exit={proc.returncode}）") from exc
    if not isinstance(payload, dict) or "ok" not in payload:
        raise HelperError("socket 返回的 JSON 缺少 ok 字段")
    return payload


def _raise_for_error(payload: dict[str, Any]) -> None:
    """Raise HelperError using only non-secret error fields."""
    message = str(payload.get("message") or "socket 调用失败")
    detail = payload.get("cause") or payload.get("data")
    if not isinstance(detail, str):
        detail = ""
    detail = detail.strip().splitlines()[0][:200] if detail.strip() else ""
    raise HelperError(f"{message}: {detail}" if detail else message)


def _write_json(path: str, payload: dict[str, Any]) -> None:
    """Write the raw socket envelope to a UTF-8 file."""
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def _emit(summary: Any, as_json: bool, render: Any) -> None:
    """Print a summary as JSON or via the given renderer."""
    if as_json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        render(summary)


def _collect_alerts(node: Any, trail: tuple[str, ...] = ()) -> Iterable[dict[str, Any]]:
    """Yield alert leaves from the nested scan report structure."""
    if not isinstance(node, dict):
        return
    if "type" in node and "policy" in node:
        yield {
            "trail": trail,
            "type": str(node.get("type") or "unknown"),
            "policy": str(node.get("policy") or "unknown"),
            "url": str(node.get("url") or ""),
        }
        return
    for key, value in node.items():
        yield from _collect_alerts(value, (*trail, str(key)))


def cmd_preflight(args: argparse.Namespace) -> int:
    """Check node, socket, and credential environment variables."""
    node_ok, node_note = _node_status()
    socket_path = shutil.which(SOCKET_BIN)
    socket_version = ""
    default_org = ""
    if socket_path:
        proc = subprocess.run(
            [socket_path, "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
        )
        socket_version = (
            proc.stdout.strip().splitlines()[0] if proc.stdout.strip() else ""
        )
        org_proc = subprocess.run(
            [socket_path, "config", "get", "defaultOrg", "--no-banner", "--no-spinner"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
        )
        if org_proc.returncode == 0:
            value = org_proc.stdout.strip()
            if ":" in value:
                value = value.split(":", 1)[1].strip()
            default_org = "" if value in {"", "undefined", "null"} else value
    token_env = next((name for name in TOKEN_ENV_VARS if os.environ.get(name)), "")
    result = {
        "node_ok": node_ok,
        "node": node_note,
        "socket": socket_version or "未找到",
        "socket_path": socket_path or "",
        "token_env": token_env,
        "token_env_set": bool(token_env),
        "org_env": os.environ.get("SOCKET_CLI_ORG_SLUG", ""),
        "default_org": default_org,
    }
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"Node:   {'OK' if node_ok else 'FAIL'}  {node_note}")
        print(f"Socket: {socket_version or '未找到'}")
        token_note = f"已设置（{token_env}）" if token_env else "未在环境变量中设置"
        print(f"Token:  {token_note}")
        print(f"Org:    {result['org_env'] or default_org or '未设置'}")
        if not node_ok or not socket_path:
            print("提示: 先安装 Node.js 22+ 与 `npm install -g socket`。")
        elif not token_env and not default_org:
            print("提示: 运行 `socket login` 或设置 SOCKET_CLI_API_TOKEN。")
    return 0 if node_ok and socket_path else 1


def _summarize_analytics(
    rows: list[dict[str, Any]], scope: str, days: int
) -> dict[str, Any]:
    """Aggregate daily analytics rows into totals and a latest-day snapshot."""
    totals = {metric: 0 for metric in ANALYTICS_METRICS}
    types: dict[str, int] = {}
    for row in rows:
        for metric in ANALYTICS_METRICS:
            value = row.get(metric)
            if isinstance(value, (int, float)):
                totals[metric] += int(value)
        top = row.get("top_five_alert_types") or {}
        if isinstance(top, dict):
            for key, value in top.items():
                if isinstance(value, (int, float)):
                    types[str(key)] = types.get(str(key), 0) + int(value)
    latest: dict[str, Any] = {}
    if rows:
        latest_row = max(rows, key=lambda item: str(item.get("created_at", "")))
        latest = {
            "created_at": latest_row.get("created_at"),
            "critical": latest_row.get("total_critical_alerts", 0),
            "high": latest_row.get("total_high_alerts", 0),
        }
    top_types = sorted(types.items(), key=lambda item: (-item[1], item[0]))[:5]
    return {
        "scope": scope,
        "window_days": days,
        "data_points": len(rows),
        "totals": totals,
        "latest": latest,
        "top_types": [{"type": name, "count": count} for name, count in top_types],
    }


def _render_analytics(summary: dict[str, Any]) -> None:
    """Print a compact analytics summary."""
    totals = summary["totals"]
    scope = summary["scope"]
    print(
        f"范围: {scope} / 最近 {summary['window_days']} 天 "
        f"/ 数据点 {summary['data_points']}"
    )
    print(
        "告警总量: "
        f"critical={totals['total_critical_alerts']} "
        f"high={totals['total_high_alerts']} "
        f"medium={totals['total_medium_alerts']} "
        f"low={totals['total_low_alerts']}"
    )
    print(
        "新增: "
        f"critical={totals['total_critical_added']} "
        f"high={totals['total_high_added']} "
        f"medium={totals['total_medium_added']} "
        f"low={totals['total_low_added']}"
    )
    print(
        "已拦截: "
        f"critical={totals['total_critical_prevented']} "
        f"high={totals['total_high_prevented']} "
        f"medium={totals['total_medium_prevented']} "
        f"low={totals['total_low_prevented']}"
    )
    latest = summary.get("latest") or {}
    if latest:
        print(
            f"最新一天 {latest.get('created_at', '?')}: "
            f"critical={latest.get('critical')} high={latest.get('high')}"
        )
    top_types = summary.get("top_types") or []
    if top_types:
        print(
            "Top 类型: "
            + ", ".join(f"{item['type']}={item['count']}" for item in top_types)
        )
    else:
        print("Top 类型: 无数据")


def cmd_analytics(args: argparse.Namespace) -> int:
    """Fetch analytics and print a summary."""
    scope_args = ["repo", args.repo] if args.repo else ["org"]
    scope = f"repo:{args.repo}" if args.repo else "org"
    proc = _run_socket(
        ["analytics", "--json", *scope_args, str(args.days)],
        dry_run=args.dry_run,
    )
    if args.dry_run:
        print(proc.stdout.strip() or f"[dry-run exit={proc.returncode}]")
        return 0 if proc.returncode == 0 else 1
    payload = _load_envelope(proc)
    if not payload.get("ok"):
        _raise_for_error(payload)
    rows = payload.get("data") or []
    if not isinstance(rows, list):
        raise HelperError("analytics 的 data 不是数组")
    if args.json_out:
        _write_json(args.json_out, payload)
    if not rows:
        message = payload.get("message") or "暂无分析数据"
        print(f"{message}（范围: {scope}，最近 {args.days} 天）")
        return 0
    summary = _summarize_analytics(rows, scope, args.days)
    _emit(summary, args.json, _render_analytics)
    return 0


def _summarize_report(data: dict[str, Any]) -> dict[str, Any]:
    """Summarize a scan report by policy, type, and package."""
    findings = list(_collect_alerts(data.get("alerts") or {}))
    by_policy: dict[str, int] = {}
    by_type: dict[str, int] = {}
    by_package: dict[str, int] = {}
    for finding in findings:
        by_policy[finding["policy"]] = by_policy.get(finding["policy"], 0) + 1
        by_type[finding["type"]] = by_type.get(finding["type"], 0) + 1
        trail = finding["trail"]
        package = trail[1] if len(trail) > 1 else "?"
        version = trail[2] if len(trail) > 2 else "?"
        key = f"{package}@{version}"
        by_package[key] = by_package.get(key, 0) + 1
    return {
        "healthy": bool(data.get("healthy")),
        "scan_id": data.get("scanId", ""),
        "org": data.get("orgSlug", ""),
        "options": data.get("options", {}),
        "alert_count": len(findings),
        "by_policy": dict(sorted(by_policy.items())),
        "by_type": dict(sorted(by_type.items(), key=lambda item: (-item[1], item[0]))),
        "by_package": dict(
            sorted(by_package.items(), key=lambda item: (-item[1], item[0]))
        ),
        "findings": findings,
    }


def _render_report(summary: dict[str, Any]) -> None:
    """Print a compact scan report summary."""
    print(f"健康状态: {'PASS' if summary['healthy'] else 'FAIL'}")
    if summary["scan_id"]:
        print(f"扫描: {summary['scan_id']}")
    print(f"告警数: {summary['alert_count']}")
    if summary["by_policy"]:
        print(
            "按策略: " + ", ".join(f"{k}={v}" for k, v in summary["by_policy"].items())
        )
    if summary["by_type"]:
        top = list(summary["by_type"].items())[:10]
        print("按类型: " + ", ".join(f"{k}={v}" for k, v in top))
    if summary["by_package"]:
        top = list(summary["by_package"].items())[:10]
        print("涉及包: " + ", ".join(f"{k}({v})" for k, v in top))


def cmd_scan_report(args: argparse.Namespace) -> int:
    """Fetch a scan report and print a health summary."""
    cmd = ["scan", "report", args.scan_id, "--json", f"--fold={args.fold}"]
    if args.license:
        cmd.append("--license")
    if args.org:
        cmd.extend(["--org", args.org])
    if args.short:
        cmd.append("--short")
    proc = _run_socket(cmd, dry_run=args.dry_run)
    if args.dry_run:
        print(proc.stdout.strip() or f"[dry-run exit={proc.returncode}]")
        return 0 if proc.returncode == 0 else 1
    payload = _load_envelope(proc)
    if not payload.get("ok"):
        _raise_for_error(payload)
    data = payload.get("data") or {}
    if not isinstance(data, dict):
        raise HelperError("scan report 的 data 不是对象")
    if args.json_out:
        _write_json(args.json_out, payload)
    if args.short:
        healthy = bool(data.get("healthy"))
        print(f"healthy={str(healthy).lower()}")
        return 0 if healthy else 2
    summary = _summarize_report(data)
    _emit(summary, args.json, _render_report)
    return 0 if summary["healthy"] else 2


def _summarize_score(data: dict[str, Any]) -> dict[str, Any]:
    """Extract the useful fields from a deep package score response."""
    self_data = data.get("self") or {}
    transitive = data.get("transitively") or {}
    return {
        "purl": data.get("purl", ""),
        "self_score": self_data.get("score") or {},
        "deep_score": transitive.get("score") or {},
        "dependency_count": transitive.get("dependencyCount", 0),
        "lowest": transitive.get("lowest") or {},
        "self_alerts": self_data.get("alerts") or [],
        "transitive_alerts": transitive.get("alerts") or [],
    }


def _render_score(summary: dict[str, Any]) -> None:
    """Print a compact package score summary."""
    print(f"包: {summary['purl']}")
    self_score = summary["self_score"]
    deep_score = summary["deep_score"]
    print(
        "自身: "
        f"overall={self_score.get('overall', '-')} "
        f"supplyChain={self_score.get('supplyChain', '-')} "
        f"maintenance={self_score.get('maintenance', '-')} "
        f"quality={self_score.get('quality', '-')} "
        f"vulnerability={self_score.get('vulnerability', '-')} "
        f"license={self_score.get('license', '-')}"
    )
    print(
        "含传递依赖: "
        f"overall={deep_score.get('overall', '-')} "
        f"依赖数={summary['dependency_count']} "
        f"supplyChain={deep_score.get('supplyChain', '-')} "
        f"vulnerability={deep_score.get('vulnerability', '-')}"
    )
    for label, alerts in (
        ("自身", summary["self_alerts"]),
        ("传递依赖", summary["transitive_alerts"]),
    ):
        if isinstance(alerts, list) and alerts:
            names = ", ".join(str(item.get("name", "?")) for item in alerts[:10])
            print(f"{label}告警: {names}")
    if summary["lowest"]:
        lowest = ", ".join(f"{k}={v}" for k, v in summary["lowest"].items())
        print(f"最低分维度: {lowest}")


def cmd_package_score(args: argparse.Namespace) -> int:
    """Fetch the deep score for one package and print a summary."""
    proc = _run_socket(
        ["package", "score", args.ecosystem, args.package, "--json"],
        dry_run=args.dry_run,
    )
    if args.dry_run:
        print(proc.stdout.strip() or f"[dry-run exit={proc.returncode}]")
        return 0 if proc.returncode == 0 else 1
    payload = _load_envelope(proc)
    if not payload.get("ok"):
        _raise_for_error(payload)
    data = payload.get("data") or {}
    if not isinstance(data, dict):
        raise HelperError("package score 的 data 不是对象")
    if args.json_out:
        _write_json(args.json_out, payload)
    summary = _summarize_score(data)
    _emit(summary, args.json, _render_score)
    return 0


def _summarize_shallow(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Reduce shallow score artifacts to package rows."""
    rows = []
    for item in items:
        alerts = item.get("alerts") or []
        rows.append(
            {
                "ecosystem": item.get("ecosystem", ""),
                "namespace": item.get("namespace", ""),
                "name": item.get("name", ""),
                "version": item.get("version", ""),
                "score": item.get("score") or {},
                "alert_count": len(alerts) if isinstance(alerts, (list, dict)) else 0,
            }
        )
    return rows


def _render_shallow(rows: list[dict[str, Any]]) -> None:
    """Print shallow scores one package per line."""
    for row in rows:
        score = row["score"]
        name = f"{row['namespace']}/{row['name']}" if row["namespace"] else row["name"]
        print(
            f"{name}@{row['version']}  "
            f"supplyChain={score.get('supplyChain', '-')} "
            f"maintenance={score.get('maintenance', '-')} "
            f"quality={score.get('quality', '-')} "
            f"vulnerability={score.get('vulnerability', '-')} "
            f"license={score.get('license', '-')} "
            f"alerts={row['alert_count']}"
        )


def cmd_package_shallow(args: argparse.Namespace) -> int:
    """Fetch shallow scores for one or more packages and print them."""
    proc = _run_socket(
        ["package", "shallow", args.ecosystem, *args.packages, "--json"],
        dry_run=args.dry_run,
    )
    if args.dry_run:
        print(proc.stdout.strip() or f"[dry-run exit={proc.returncode}]")
        return 0 if proc.returncode == 0 else 1
    payload = _load_envelope(proc)
    if not payload.get("ok"):
        _raise_for_error(payload)
    items = payload.get("data") or []
    if not isinstance(items, list):
        raise HelperError("package shallow 的 data 不是数组")
    if args.json_out:
        _write_json(args.json_out, payload)
    rows = _summarize_shallow(items)
    _emit(rows, args.json, _render_shallow)
    return 0


def cmd_repos(args: argparse.Namespace) -> int:
    """List Socket repositories and optionally filter by name."""
    cmd = ["repository", "list", "--json"]
    if args.org:
        cmd.extend(["--org", args.org])
    proc = _run_socket(cmd, dry_run=args.dry_run)
    if args.dry_run:
        print(proc.stdout.strip() or f"[dry-run exit={proc.returncode}]")
        return 0 if proc.returncode == 0 else 1
    payload = _load_envelope(proc)
    if not payload.get("ok"):
        _raise_for_error(payload)
    try:
        results = payload["data"]["data"]["results"]
    except (KeyError, TypeError) as exc:
        raise HelperError("repository list 返回结构不符合预期") from exc
    rows = [
        {
            "name": item.get("name", ""),
            "default_branch": item.get("default_branch", ""),
            "visibility": item.get("visibility", ""),
            "archived": item.get("archived", False),
        }
        for item in results
        if isinstance(item, dict)
    ]
    if args.filter:
        needle = args.filter.lower()
        rows = [row for row in rows if needle in str(row["name"]).lower()]
    if args.json_out:
        _write_json(args.json_out, payload)
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    elif not rows:
        print("没有匹配的仓库。")
    else:
        for row in rows:
            print(
                f"{row['name']}\t{row['default_branch']}\t"
                f"{row['visibility']}\tarchived={row['archived']}"
            )
    return 0


def cmd_repo_view(args: argparse.Namespace) -> int:
    """Show one Socket repository's details."""
    cmd = ["repository", "view", args.name, "--json"]
    if args.org:
        cmd.extend(["--org", args.org])
    proc = _run_socket(cmd, dry_run=args.dry_run)
    if args.dry_run:
        print(proc.stdout.strip() or f"[dry-run exit={proc.returncode}]")
        return 0 if proc.returncode == 0 else 1
    payload = _load_envelope(proc)
    if not payload.get("ok"):
        _raise_for_error(payload)
    if args.json_out:
        _write_json(args.json_out, payload)
    if args.json:
        print(json.dumps(payload.get("data") or {}, ensure_ascii=False, indent=2))
    else:
        data = payload.get("data") or {}
        for key in (
            "id",
            "name",
            "visibility",
            "default_branch",
            "homepage",
            "archived",
        ):
            if key in data:
                print(f"{key}: {data[key]}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Create the command-line parser."""
    parser = argparse.ArgumentParser(
        description="Socket CLI 轻量封装：预检、取数并输出摘要。",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    preflight = subparsers.add_parser("preflight", help="检查 node / socket / 凭据")
    preflight.add_argument("--json", action="store_true", help="以 JSON 输出")
    preflight.set_defaults(func=cmd_preflight)

    analytics = subparsers.add_parser("analytics", help="告警趋势摘要")
    scope = analytics.add_mutually_exclusive_group()
    scope.add_argument("--repo", metavar="SLUG", help="仓库级查询")
    scope.add_argument("--org", action="store_true", help="组织级查询（默认）")
    analytics.add_argument("--days", type=int, choices=(7, 30, 90), default=30)
    analytics.add_argument("--json", action="store_true", help="摘要以 JSON 输出")
    analytics.add_argument("--json-out", metavar="PATH", help="原始 JSON 写盘")
    analytics.add_argument("--dry-run", action="store_true", help="只校验参数")
    analytics.set_defaults(func=cmd_analytics)

    report = subparsers.add_parser("scan-report", help="扫描报告健康摘要")
    report.add_argument("scan_id", metavar="SCAN_ID")
    report.add_argument(
        "--fold", choices=("pkg", "version", "file", "none"), default="version"
    )
    report.add_argument("--license", action="store_true", help="纳入 License 策略")
    report.add_argument("--short", action="store_true", help="只取 healthy")
    report.add_argument("--org", metavar="SLUG", help="覆盖默认组织")
    report.add_argument("--json", action="store_true", help="摘要以 JSON 输出")
    report.add_argument("--json-out", metavar="PATH", help="原始 JSON 写盘")
    report.add_argument("--dry-run", action="store_true", help="只校验参数")
    report.set_defaults(func=cmd_scan_report)

    score = subparsers.add_parser("package-score", help="单包深度评分摘要")
    score.add_argument("ecosystem", help="例如 pypi")
    score.add_argument("package", help="包名，可带 @version")
    score.add_argument("--json", action="store_true", help="摘要以 JSON 输出")
    score.add_argument("--json-out", metavar="PATH", help="原始 JSON 写盘")
    score.add_argument("--dry-run", action="store_true", help="只校验参数")
    score.set_defaults(func=cmd_package_score)

    shallow = subparsers.add_parser("package-shallow", help="多包浅分摘要")
    shallow.add_argument("ecosystem", help="例如 pypi")
    shallow.add_argument("packages", nargs="+", metavar="PACKAGE")
    shallow.add_argument("--json", action="store_true", help="摘要以 JSON 输出")
    shallow.add_argument("--json-out", metavar="PATH", help="原始 JSON 写盘")
    shallow.add_argument("--dry-run", action="store_true", help="只校验参数")
    shallow.set_defaults(func=cmd_package_shallow)

    repos = subparsers.add_parser("repos", help="列出仓库 slug")
    repos.add_argument("--filter", metavar="TEXT", help="按名称过滤")
    repos.add_argument("--org", metavar="SLUG", help="覆盖默认组织")
    repos.add_argument("--json", action="store_true", help="以 JSON 输出")
    repos.add_argument("--json-out", metavar="PATH", help="原始 JSON 写盘")
    repos.add_argument("--dry-run", action="store_true", help="只校验参数")
    repos.set_defaults(func=cmd_repos)

    view = subparsers.add_parser("repo-view", help="查看单个仓库")
    view.add_argument("name", metavar="REPO")
    view.add_argument("--org", metavar="SLUG", help="覆盖默认组织")
    view.add_argument("--json", action="store_true", help="以 JSON 输出")
    view.add_argument("--json-out", metavar="PATH", help="原始 JSON 写盘")
    view.add_argument("--dry-run", action="store_true", help="只校验参数")
    view.set_defaults(func=cmd_repo_view)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the helper and translate HelperError into exit code 1."""
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except HelperError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
