#!/usr/bin/env python3
"""Tencent Yingyongbao (应用宝) API publisher — APK version update via open.qq.com."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

API_BASE = "https://p.open.qq.com/open_file/developer_api"
DEFAULT_PKG = ""  # 必填，由 <项目>/yingyongbao.env 提供
DEFAULT_APK = "build/app/outputs/channels/yingyongbao-app-release.apk"

AUDIT_STATUS = {
    1: "审核中",
    2: "审核驳回",
    3: "审核通过",
    8: "开发者主动撤销",
}

SKILL_DIR = Path(__file__).resolve().parents[1]
CONFIG_ENV = SKILL_DIR / "config.env"


def project_name() -> str:
    """Project identity for per-project credential isolation.

    Priority: $YINGYONGBAO_PROJECT > git root dir name (from cwd) > cwd name.
    Mirrors the countly-data-analysis convention so one machine can hold
    credentials for many apps without them silently crossing over.
    """
    override = os.environ.get("YINGYONGBAO_PROJECT")
    if override:
        return override
    try:
        # --git-common-dir resolves linked worktrees to the MAIN repo's .git,
        # so running from a worktree still yields the main repo's name.
        result = subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True, text=True, check=True,
        )
        common = result.stdout.strip()
        if common:
            return Path(common).parent.name
    except (OSError, subprocess.CalledProcessError):
        pass
    return Path.cwd().name

USER_CONFIG_ENV = Path.home() / ".config" / "ai-ignore-config" / project_name() / "yingyongbao.env"

_CONFIG_PATH: Path | None = None


def resolve_config_path(explicit: str | None = None) -> Path | None:
    """Return the first existing credentials file path, or None."""
    if explicit:
        path = Path(explicit).expanduser()
        return path if path.is_file() else None
    candidates = [
        USER_CONFIG_ENV,
        CONFIG_ENV,
    ]
    for path in candidates:
        if path.is_file():
            return path
    return None


def load_config_env(config_path: Path | None = None) -> Path | None:
    """Load key=value pairs from a .env file (does not override existing env)."""
    global _CONFIG_PATH
    path = config_path or resolve_config_path()
    if path is None:
        return None
    _CONFIG_PATH = path
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value
    return path


def get_config(config_path: Path | None = None) -> dict[str, str]:
    loaded = load_config_env(config_path)
    cfg = {
        "user_id": os.environ.get("YINGYONGBAO_USER_ID", ""),
        "access_secret": os.environ.get("YINGYONGBAO_ACCESS_SECRET", ""),
        "app_id": os.environ.get("YINGYONGBAO_APP_ID", ""),
        "pkg_name": os.environ.get("YINGYONGBAO_PKG_NAME", DEFAULT_PKG),
    }
    missing = [k for k, v in cfg.items() if not v]
    if missing:
        env_names = {
            "user_id": "YINGYONGBAO_USER_ID",
            "access_secret": "YINGYONGBAO_ACCESS_SECRET",
            "app_id": "YINGYONGBAO_APP_ID",
            "pkg_name": "YINGYONGBAO_PKG_NAME",
        }
        hint = ", ".join(env_names[k] for k in missing)
        print(
            f"error: missing credentials ({hint}).\n"
            f"  Recommended: mkdir -p {USER_CONFIG_ENV.parent} && "
            f"cp {SKILL_DIR / 'config.example.env'} "
            f"{USER_CONFIG_ENV}\n"
            f"  Then edit {USER_CONFIG_ENV} (outside repo, AI typically cannot read).\n"
            f"  Loaded config: {loaded or 'none'}",
            file=sys.stderr,
        )
        sys.exit(2)
    return cfg


def cal_sign(access_secret: str, params: dict[str, str]) -> str:
    items = sorted(
        (k, v)
        for k, v in params.items()
        if k != "sign" and v is not None and v != ""
    )
    sign_str = "&".join(f"{k}={v}" for k, v in items)
    digest = hmac.new(
        access_secret.encode("utf-8"),
        sign_str.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return digest


def file_md5(path: Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def api_post(
    route: str,
    cfg: dict[str, str],
    biz_params: dict[str, str | int],
    *,
    timeout: int = 60,
) -> dict[str, Any]:
    params: dict[str, str] = {
        "user_id": cfg["user_id"],
        "timestamp": str(int(time.time())),
    }
    for k, v in biz_params.items():
        if v is not None and v != "":
            params[k] = str(v)
    params["sign"] = cal_sign(cfg["access_secret"], params)

    body = urllib.parse.urlencode(params).encode("utf-8")
    url = f"{API_BASE}{route}"
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        print(f"error: HTTP {e.code} from {route}: {raw}", file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"error: request failed for {route}: {e.reason}", file=sys.stderr)
        sys.exit(1)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        print(f"error: invalid JSON from {route}: {raw}", file=sys.stderr)
        sys.exit(1)

    if not isinstance(data, dict):
        print(f"error: unexpected response from {route}: {raw}", file=sys.stderr)
        sys.exit(1)
    return data


def check_ret(data: dict[str, Any], context: str) -> dict[str, Any]:
    ret = data.get("ret", -1)
    if ret != 0:
        msg = data.get("msg", "")
        print(f"error: {context} failed (ret={ret}): {msg}", file=sys.stderr)
        sys.exit(1)
    return data


def upload_to_cos(pre_sign_url: str, file_path: Path, *, timeout: int = 300) -> None:
    content = file_path.read_bytes()
    req = urllib.request.Request(
        pre_sign_url,
        data=content,
        method="PUT",
        headers={"Content-Type": "application/octet-stream"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                print(
                    f"error: COS upload HTTP {resp.status}",
                    file=sys.stderr,
                )
                sys.exit(1)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"error: COS upload HTTP {e.code}: {body}", file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"error: COS upload failed: {e.reason}", file=sys.stderr)
        sys.exit(1)


def cmd_query_detail(cfg: dict[str, str], args: argparse.Namespace) -> None:
    data = api_post(
        "/query_app_detail",
        cfg,
        {"pkg_name": cfg["pkg_name"], "app_id": cfg["app_id"]},
    )
    check_ret(data, "query_app_detail")
    print(json.dumps(data, ensure_ascii=False, indent=2))


def upload_file_serial(
    cfg: dict[str, str],
    file_path: Path,
    file_type: str,
    *,
    dry_run: bool = False,
) -> str:
    if not file_path.is_file():
        print(f"error: file not found: {file_path}", file=sys.stderr)
        sys.exit(1)
    file_name = file_path.name
    if dry_run:
        print(
            f"[dry-run] would upload {file_path} as {file_type} -> serial_number (mock)",
            file=sys.stderr,
        )
        return "DRY_RUN_SERIAL"

    data = api_post(
        "/get_file_upload_info",
        cfg,
        {
            "pkg_name": cfg["pkg_name"],
            "app_id": cfg["app_id"],
            "file_type": file_type,
            "file_name": file_name,
        },
        timeout=30,
    )
    check_ret(data, "get_file_upload_info")
    pre_sign_url = data.get("pre_sign_url", "")
    serial = data.get("serial_number", "")
    if not pre_sign_url or not serial:
        print(f"error: missing pre_sign_url or serial_number: {data}", file=sys.stderr)
        sys.exit(1)

    print(f"uploading {file_path.name} to COS...", file=sys.stderr)
    upload_to_cos(pre_sign_url, file_path)
    print(f"upload ok, serial_number={serial}", file=sys.stderr)
    return serial


def cmd_upload_file(cfg: dict[str, str], args: argparse.Namespace) -> None:
    path = Path(args.file)
    serial = upload_file_serial(cfg, path, args.type, dry_run=args.dry_run)
    print(json.dumps({"serial_number": serial, "file": str(path)}, ensure_ascii=False))


def cmd_update(cfg: dict[str, str], args: argparse.Namespace) -> None:
    biz: dict[str, str | int] = {
        "pkg_name": cfg["pkg_name"],
        "app_id": cfg["app_id"],
        "deploy_type": args.deploy_type,
        "feature": args.feature,
    }
    if args.deploy_type == 2 and args.deploy_time:
        biz["deploy_time"] = args.deploy_time

    if args.apk64:
        apk_path = Path(args.apk64)
        if args.dry_run:
            serial = "DRY_RUN_SERIAL"
            md5 = file_md5(apk_path) if apk_path.is_file() else "dry_run_md5"
        else:
            serial = upload_file_serial(cfg, apk_path, "apk")
            md5 = file_md5(apk_path)
        biz["apk64_flag"] = 1
        biz["apk64_file_serial_number"] = serial
        biz["apk64_file_md5"] = md5

    if args.apk32:
        apk_path = Path(args.apk32)
        if args.dry_run:
            serial = "DRY_RUN_SERIAL"
            md5 = file_md5(apk_path) if apk_path.is_file() else "dry_run_md5"
        else:
            serial = upload_file_serial(cfg, apk_path, "apk")
            md5 = file_md5(apk_path)
        biz["apk32_flag"] = 1
        biz["apk32_file_serial_number"] = serial
        biz["apk32_file_md5"] = md5

    if not args.apk64 and not args.apk32:
        print("error: specify --apk64 and/or --apk32 for APK update", file=sys.stderr)
        sys.exit(2)

    if args.dry_run:
        print("[dry-run] update_app params:", file=sys.stderr)
        print(json.dumps(biz, ensure_ascii=False, indent=2))
        return

    data = api_post("/update_app", cfg, biz, timeout=120)
    check_ret(data, "update_app")
    print(json.dumps(data, ensure_ascii=False, indent=2))


def cmd_status(cfg: dict[str, str], args: argparse.Namespace) -> None:
    data = api_post(
        "/query_app_update_status",
        cfg,
        {"pkg_name": cfg["pkg_name"], "app_id": cfg["app_id"]},
    )
    check_ret(data, "query_app_update_status")
    status = data.get("audit_status")
    if status in AUDIT_STATUS:
        data["audit_status_text"] = AUDIT_STATUS[status]
    print(json.dumps(data, ensure_ascii=False, indent=2))


def cmd_publish(cfg: dict[str, str], args: argparse.Namespace) -> None:
    apk_path = Path(args.apk)
    if not apk_path.is_file() and not args.dry_run:
        print(f"error: APK not found: {apk_path}", file=sys.stderr)
        sys.exit(1)

    print("step 1/4: query app detail...", file=sys.stderr)
    detail = api_post(
        "/query_app_detail",
        cfg,
        {"pkg_name": cfg["pkg_name"], "app_id": cfg["app_id"]},
    )
    check_ret(detail, "query_app_detail")
    app_name = detail.get("app_name", cfg["pkg_name"])
    print(f"  app: {app_name} ({cfg['pkg_name']})", file=sys.stderr)

    print("step 2/4: upload APK...", file=sys.stderr)
    if args.dry_run:
        serial = "DRY_RUN_SERIAL"
        md5 = file_md5(apk_path) if apk_path.is_file() else "dry_run_md5"
    else:
        serial = upload_file_serial(cfg, apk_path, "apk")
        md5 = file_md5(apk_path)

    print("step 3/4: submit update...", file=sys.stderr)
    biz: dict[str, str | int] = {
        "pkg_name": cfg["pkg_name"],
        "app_id": cfg["app_id"],
        "deploy_type": 1,
        "feature": args.feature,
        "apk64_flag": 1,
        "apk64_file_serial_number": serial,
        "apk64_file_md5": md5,
    }
    if args.dry_run:
        print("[dry-run] would call update_app:", file=sys.stderr)
        print(json.dumps(biz, ensure_ascii=False, indent=2))
        return

    update_data = api_post("/update_app", cfg, biz, timeout=120)
    check_ret(update_data, "update_app")
    print(json.dumps(update_data, ensure_ascii=False, indent=2))

    if not args.poll:
        print("tip: run `status` or re-run with --poll to watch audit", file=sys.stderr)
        return

    print("step 4/4: polling audit status...", file=sys.stderr)
    deadline = time.time() + args.poll_timeout
    interval = args.poll_interval
    while time.time() < deadline:
        time.sleep(interval)
        status_data = api_post(
            "/query_app_update_status",
            cfg,
            {"pkg_name": cfg["pkg_name"], "app_id": cfg["app_id"]},
        )
        if status_data.get("ret") != 0:
            print(
                f"warning: status poll ret={status_data.get('ret')}: "
                f"{status_data.get('msg')}",
                file=sys.stderr,
            )
            continue
        audit = status_data.get("audit_status")
        label = AUDIT_STATUS.get(audit, str(audit))
        print(f"  audit_status={audit} ({label})", file=sys.stderr)
        if audit in (2, 3, 8):
            status_data["audit_status_text"] = label
            print(json.dumps(status_data, ensure_ascii=False, indent=2))
            if audit == 2:
                sys.exit(1)
            return
    print("error: poll timeout", file=sys.stderr)
    sys.exit(1)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Tencent Yingyongbao (应用宝) API — APK version publish",
    )
    parser.add_argument(
        "--config",
        metavar="PATH",
        help=(
            "Credentials file (default: ~/.config/ai-ignore-config/<git 根目录名>/yingyongbao.env, "
            "then skill config.env)"
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print actions without calling update/publish APIs",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("query-detail", help="Query current app detail")

    p_upload = sub.add_parser("upload-file", help="Upload one file to COS")
    p_upload.add_argument(
        "--type",
        required=True,
        choices=["img", "apk", "pdf", "video", "txt"],
        help="File type for get_file_upload_info",
    )
    p_upload.add_argument("--file", required=True, help="Local file path")

    p_update = sub.add_parser("update", help="Submit app update")
    p_update.add_argument("--feature", required=True, help="Version feature / changelog")
    p_update.add_argument("--apk64", help="64-bit APK path")
    p_update.add_argument("--apk32", help="32-bit or 32/64 compatible APK path")
    p_update.add_argument(
        "--deploy-type",
        type=int,
        default=1,
        choices=[1, 2],
        help="1=immediate after audit, 2=scheduled",
    )
    p_update.add_argument(
        "--deploy-time",
        type=int,
        help="Scheduled deploy unix timestamp (seconds, Beijing) when deploy-type=2",
    )

    sub.add_parser("status", help="Query latest update audit status")

    p_pub = sub.add_parser("publish", help="Full flow: detail -> upload -> update")
    p_pub.add_argument(
        "--apk",
        default=DEFAULT_APK,
        help=f"APK path (default: {DEFAULT_APK})",
    )
    p_pub.add_argument("--feature", required=True, help="Version feature / changelog")
    p_pub.add_argument(
        "--poll",
        action="store_true",
        help="Poll audit status after submit",
    )
    p_pub.add_argument(
        "--poll-interval",
        type=int,
        default=30,
        help="Poll interval seconds (default: 30)",
    )
    p_pub.add_argument(
        "--poll-timeout",
        type=int,
        default=3600,
        help="Max poll wait seconds (default: 3600)",
    )

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    config_path = Path(args.config).expanduser() if args.config else None
    if args.config and not config_path.is_file():
        print(f"error: config file not found: {config_path}", file=sys.stderr)
        sys.exit(2)
    cfg = get_config(config_path)

    handlers = {
        "query-detail": cmd_query_detail,
        "upload-file": cmd_upload_file,
        "update": cmd_update,
        "status": cmd_status,
        "publish": cmd_publish,
    }
    handlers[args.command](cfg, args)


if __name__ == "__main__":
    main()
