#!/usr/bin/env python3
"""vivo 开放平台 API 传包 client.

Docs: https://dev.vivo.com.cn/documentCenter/doc/327 (API接入说明)
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import mimetypes
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any

ENDPOINTS = {
    "prod": "https://developer-api.vivo.com.cn/router/rest",
    "sandbox": "https://sandbox-developer-api.vivo.com.cn/router/rest",
}

DEFAULT_APK = "build/app/outputs/channels/vivo-app-release.apk"
DEFAULT_PKG = ""  # 必填，由 <项目>/vivo.env 提供

API_VERSION = "1.0"
SIGN_METHOD = "HMAC-SHA256"
TARGET_APP_KEY = "developer"

SKILL_DIR = Path(__file__).resolve().parents[1]
CONFIG_ENV = SKILL_DIR / "config.env"


def project_name() -> str:
    """Project identity for per-project credential isolation.

    Priority: $VIVO_PROJECT > git root dir name (from cwd) > cwd name.
    Mirrors the countly-data-analysis convention so one machine can hold
    credentials for many apps without them silently crossing over.
    """
    override = os.environ.get("VIVO_PROJECT")
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

USER_CONFIG_ENV = Path.home() / ".config" / "ai-ignore-config" / project_name() / "vivo.env"

# 公共返回码 https://dev.vivo.com.cn/documentCenter/doc/330
CODES = {
    404: "接口不存在",
    405: "不允许的 HTTP 请求方法",
    440: "缺少参数",
    441: "请求参数错误",
    500: "服务器错误",
    10001: "签名校验失败",
    10002: "业务请求参数不能为空",
    10004: "没有接口访问权限",
    10005: "timestamp 时间戳失效（本机时间与 vivo 相差超过 20 分钟）",
    10006: "请求频次过高",
    10008: "vivo 开发者账号非正常状态",
    10011: "当天请求次数超过限制（正式环境每个传包接口 50 次/天）",
    10014: "API 版本号不正确",
    10015: "签名的验证方式不支持",
    10018: "禁止访问，请核对接入信息",
}

# 业务返回码（subCode），取 app.upload.apk.app / app.sync.update.app 两个接口的并集
SUB_CODES = {
    "11001": "包名不正确，未查询到应用",
    "11011": "开发者账号下不存在该应用——首次上架须先在控制台建应用，API 不能建",
    "12002": "应用不存在，更新失败",
    "12006": "应用主标题一年修改超过 4 次",
    "12010": "应用正在审核中，不允许操作",
    "12022": "当前更新应用待上架，不允许更新",
    "13001": "上传的文件不存在，上传失败",
    "13002": "包名不属于当前开发者 / 其它开发者已上传过该应用",
    "13003": "请检查文件是否正常，文件上传失败",
    "13004": "文件上传服务异常",
    "15001": "上传的 apk 包名与当前包名不一致",
    "15002": "targetSdkVersion 版本低于之前版本",
    "15003": "上传的 APK 版本号低于之前上传的版本",
    "15005": "apk 包解析失败",
    "15009": "apk 包 md5 与请求参数不一致",
    "15010": "上传的 apk 版本号低于之前上传的版本",
    "15012": "apk 版本号与请求参数版本号不一致",
    "18007": "附件的流水号错误",
    "20002": "流水号错误，未查询到上传的 apk 包信息",
    "20008": "必填参数不能为空",
    "20016": "新版说明长度不符合要求（5~200 个字符）",
    "20017": "应用简介长度不符合要求（50~1000 个字符）",
    "21003": "应用资料正在审核中，请审核完后再更新",
    "21004": "合同已过期或未签署",
    "22009": "上架类型参数不合法",
    "22010": "上架类型为定时上架，上架时间不能为空",
    "22011": "上架时间不能小于当前时间",
}


# --------------------------------------------------------------------------- config


def resolve_config_path(explicit: str | None = None) -> Path | None:
    if explicit:
        path = Path(explicit).expanduser()
        return path if path.is_file() else None
    for path in (USER_CONFIG_ENV, CONFIG_ENV):
        if path.is_file():
            return path
    return None


def load_config_env(config_path: Path | None = None) -> Path | None:
    path = config_path or resolve_config_path()
    if path is None or not path.is_file():
        return None
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


def get_config(config_path: Path | None = None, *, require_auth: bool = True) -> dict[str, str]:
    loaded = load_config_env(config_path)
    cfg = {
        "access_key": os.environ.get("VIVO_ACCESS_KEY", ""),
        "access_secret": os.environ.get("VIVO_ACCESS_SECRET", ""),
        "package_name": os.environ.get("VIVO_PACKAGE_NAME", DEFAULT_PKG),
        "online_type": os.environ.get("VIVO_ONLINE_TYPE", "1"),
        "compatible_device": os.environ.get("VIVO_COMPATIBLE_DEVICE", "2"),
        "_config_path": str(loaded or ""),
    }
    if require_auth and not (cfg["access_key"] and cfg["access_secret"] and cfg["package_name"]):
        print(
            "error: missing credentials (VIVO_ACCESS_KEY, VIVO_ACCESS_SECRET, VIVO_PACKAGE_NAME).\n"
            f"  Recommended: cp {SKILL_DIR / 'config.example.env'} {USER_CONFIG_ENV}\n"
            f"  Then edit {USER_CONFIG_ENV}. Loaded config: {loaded or 'none'}",
            file=sys.stderr,
        )
        sys.exit(2)
    return cfg


# --------------------------------------------------------------------------- signing


def common_params(cfg: dict[str, str], method: str) -> dict[str, Any]:
    return {
        "method": method,
        "access_key": cfg["access_key"],
        "timestamp": str(int(time.time() * 1000)),
        "format": "json",
        "v": API_VERSION,
        "sign_method": SIGN_METHOD,
        "target_app_key": TARGET_APP_KEY,
    }


def sign_params(params: dict[str, Any], access_secret: str) -> str:
    """HmacSHA256 over `k=v` pairs sorted by key and joined with `&`, hex lowercase.

    `file` never participates: file uploads sign only the scalar form fields.
    """
    parts = [
        f"{key}={params[key]}"
        for key in sorted(params)
        if key not in ("sign", "file") and params[key] is not None
    ]
    return hmac.new(
        access_secret.encode("utf-8"),
        "&".join(parts).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


# --------------------------------------------------------------------------- http


def http_request(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    data: Any = None,
    timeout: int = 300,
) -> str:
    req = urllib.request.Request(url, data=data, method="POST", headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        print(f"error: HTTP {e.code} {url}\n{raw}", file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"error: request failed {url}: {e.reason}", file=sys.stderr)
        sys.exit(1)


def check_result(raw: str, *, label: str, strict: bool = True) -> Any:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        if not strict:
            return {"_error": {"label": label, "reason": "non-JSON", "raw": raw[:400]}}
        print(f"error: {label} returned non-JSON: {raw}", file=sys.stderr)
        sys.exit(1)
    code = data.get("code")
    if code != 0:
        hint = CODES.get(code, "")
        suffix = f" ({hint})" if hint else ""
        if not strict:
            return {"_error": {"label": label, "code": code, "hint": hint, "msg": data.get("msg")}}
        print(f"error: {label} failed, code={code}{suffix}, msg={data.get('msg')}", file=sys.stderr)
        sys.exit(1)
    sub = str(data.get("subCode") or "0")
    if sub not in ("0", ""):
        hint = SUB_CODES.get(sub, "")
        suffix = f" ({hint})" if hint else ""
        if not strict:
            return {"_error": {"label": label, "subCode": sub, "hint": hint, "msg": data.get("msg")}}
        print(
            f"error: {label} failed, subCode={sub}{suffix}, msg={data.get('msg')}",
            file=sys.stderr,
        )
        sys.exit(1)
    return data.get("data")


def call(
    cfg: dict[str, str],
    endpoint: str,
    method: str,
    business: dict[str, Any],
    *,
    strict: bool = True,
) -> Any:
    params = common_params(cfg, method)
    params.update({k: v for k, v in business.items() if v is not None})
    params["sign"] = sign_params(params, cfg["access_secret"])
    body = urllib.parse.urlencode(params).encode("utf-8")
    raw = http_request(
        endpoint,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data=body,
        timeout=120,
    )
    return check_result(raw, label=method, strict=strict)


def call_upload(
    cfg: dict[str, str],
    endpoint: str,
    method: str,
    business: dict[str, Any],
    path: Path,
) -> Any:
    """multipart/form-data upload; `file` is excluded from the signature."""
    params = common_params(cfg, method)
    params.update({k: v for k, v in business.items() if v is not None})
    params["sign"] = sign_params(params, cfg["access_secret"])

    boundary = "----vivo-publish-" + uuid.uuid4().hex
    mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"

    # Stream through a temp file so multi-hundred-MB APKs never sit in memory twice.
    with tempfile.TemporaryFile() as body:
        for key, value in params.items():
            body.write(
                (
                    f"--{boundary}\r\n"
                    f'Content-Disposition: form-data; name="{key}"\r\n'
                    f"Content-Type: text/plain; charset=utf-8\r\n\r\n"
                    f"{value}\r\n"
                ).encode("utf-8")
            )
        body.write(
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
                f"Content-Type: {mime_type}\r\n\r\n"
            ).encode("utf-8")
        )
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                body.write(chunk)
        body.write(f"\r\n--{boundary}--\r\n".encode("utf-8"))
        length = body.tell()
        body.seek(0)
        raw = http_request(
            endpoint,
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Content-Length": str(length),
            },
            data=body,
            timeout=1800,
        )
    return check_result(raw, label=method)


# --------------------------------------------------------------------------- helpers


def dump(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def existing_file(path_value: str, label: str) -> Path:
    path = Path(path_value).expanduser()
    if not path.is_file():
        print(f"error: {label} not found: {path}", file=sys.stderr)
        sys.exit(2)
    return path


def file_md5(path: Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def update_body(cfg: dict[str, str], args: argparse.Namespace, **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "packageName": args.package_name or cfg["package_name"],
        "onlineType": args.online_type or cfg["online_type"],
        "compatibleDevice": args.compatible_device or cfg["compatible_device"],
    }
    body.update({k: v for k, v in overrides.items() if v is not None})
    for key, value in (
        ("updateDesc", args.update_desc),
        ("detailDesc", args.detail_desc),
        ("remark", args.remark),
        ("scheOnlineTime", args.sche_online_time),
    ):
        if value:
            body[key] = value
    for spec in args.set or []:
        key, _, value = spec.partition("=")
        body[key.strip()] = value
    if str(body["onlineType"]) == "2" and not body.get("scheOnlineTime"):
        print(
            "error: onlineType 2 (定时上架) requires --sche-online-time 'yyyy-MM-dd HH:mm:ss'",
            file=sys.stderr,
        )
        sys.exit(2)
    return body


# --------------------------------------------------------------------------- commands


def cmd_doctor(cfg: dict[str, str], args: argparse.Namespace) -> None:
    apk = Path(args.apk).expanduser()
    report: dict[str, Any] = {
        "configPath": cfg["_config_path"] or "none",
        "hasAccessKey": bool(cfg["access_key"]),
        "hasAccessSecret": bool(cfg["access_secret"]),
        "packageName": cfg["package_name"],
        "endpoint": ENDPOINTS[args.env],
        "apkPath": args.apk,
        "apkExists": apk.is_file(),
    }
    if cfg["access_key"] and cfg["access_secret"]:
        # doctor 的职责是诊断，不能因为业务错误就崩掉——凭据是否可用、
        # 应用在不在账号下，恰恰是它要回答的两个问题。strict=False 让
        # 业务错误以数据形式返回而不是 sys.exit。
        detail = call(
            cfg,
            ENDPOINTS[args.env],
            "app.query.details",
            {"packageName": cfg["package_name"]},
            strict=False,
        )
        err = detail.get("_error") if isinstance(detail, dict) else None
        if err:
            report["appDetail"] = None
            report["appQueryError"] = err
            # 能拿到业务错误码，说明签名与鉴权本身已经通过
            report["credentialsOk"] = "subCode" in err or "code" in err
            report["appExists"] = False
            if str(err.get("subCode")) in ("11011", "11001", "12002"):
                report["hint"] = (
                    "凭据没问题，但开发者账号下还没有这个应用。vivo 的 API "
                    "不能建应用——首次上架必须先在开放平台控制台创建并完整上架一次，"
                    "之后才能用本脚本做版本更新。"
                )
        else:
            report["appDetail"] = detail
            report["credentialsOk"] = True
            report["appExists"] = True
    dump(report)


def cmd_detail(cfg: dict[str, str], args: argparse.Namespace) -> None:
    dump(
        call(
            cfg,
            ENDPOINTS[args.env],
            "app.query.details",
            {"packageName": args.package_name or cfg["package_name"]},
        )
    )


def cmd_upload(cfg: dict[str, str], args: argparse.Namespace) -> None:
    path = existing_file(args.file, "file")
    business: dict[str, Any] = {"packageName": args.package_name or cfg["package_name"]}
    if args.method == "app.upload.apk.app":
        business["fileMd5"] = file_md5(path)
        if args.stage_type:
            business["stageType"] = args.stage_type
    if args.dry_run:
        dump({"method": args.method, "file": str(path), "business": business})
        return
    dump(call_upload(cfg, ENDPOINTS[args.env], args.method, business, path))


def cmd_update(cfg: dict[str, str], args: argparse.Namespace) -> None:
    body = update_body(
        cfg,
        args,
        versionCode=args.version_code,
        apk=args.serialnumber,
        fileMd5=args.file_md5,
    )
    if args.dry_run:
        dump({"method": "app.sync.update.app", "business": body})
        return
    call(cfg, ENDPOINTS[args.env], "app.sync.update.app", body)
    dump({"packageName": body["packageName"], "versionCode": body.get("versionCode"), "ok": True})


def cmd_publish(cfg: dict[str, str], args: argparse.Namespace) -> None:
    apk = existing_file(args.apk, "apk")
    md5 = file_md5(apk)
    package_name = args.package_name or cfg["package_name"]

    if args.dry_run:
        dump(
            {
                "endpoint": ENDPOINTS[args.env],
                "apk": str(apk),
                "apkSize": apk.stat().st_size,
                "fileMd5": md5,
                "uploadMethod": "app.upload.apk.app",
                "updateBody": update_body(
                    cfg,
                    args,
                    versionCode="<from upload response>",
                    apk="<serialnumber from upload response>",
                    fileMd5=md5,
                ),
            }
        )
        return

    endpoint = ENDPOINTS[args.env]
    uploaded = call_upload(
        cfg,
        endpoint,
        "app.upload.apk.app",
        {"packageName": package_name, "fileMd5": md5},
        apk,
    )
    serial = uploaded.get("serialnumber")
    version_code = args.version_code or uploaded.get("versionCode")
    print(
        f"uploaded {apk.name} -> serialnumber {serial} "
        f"(versionCode {uploaded.get('versionCode')}, versionName {uploaded.get('versionName')})",
        file=sys.stderr,
    )

    body = update_body(cfg, args, versionCode=version_code, apk=serial, fileMd5=md5)
    call(cfg, endpoint, "app.sync.update.app", body)
    dump({"packageName": package_name, "serialnumber": serial, "versionCode": version_code})


# --------------------------------------------------------------------------- cli


def add_update_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--package-name")
    parser.add_argument("--update-desc", help="新版说明，5~200 个字符")
    parser.add_argument("--detail-desc", help="应用简介，50~1000 个字符")
    parser.add_argument("--remark", help="审核留言，10~200 个字符")
    parser.add_argument("--online-type", help="1=实时上架 2=定时上架")
    parser.add_argument("--sche-online-time", help="定时上架时间 yyyy-MM-dd HH:mm:ss")
    parser.add_argument("--compatible-device", help="1=手机 2=手机和平板 3=平板")
    parser.add_argument(
        "--set",
        action="append",
        metavar="key=value",
        help="任意业务参数，可重复，例如 --set rateAge=12",
    )
    parser.add_argument("--dry-run", action="store_true")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="vivo 开放平台 API 传包 client")
    parser.add_argument("--config", help="Credentials file path")
    parser.add_argument("--env", default="prod", choices=["prod", "sandbox"])
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="Check credentials, app detail and local APK")
    doctor.add_argument("--apk", default=DEFAULT_APK)

    detail = sub.add_parser("detail", help="app.query.details：查询应用详情与审核状态")
    detail.add_argument("--package-name")

    upload = sub.add_parser("upload", help="上传单个文件，返回流水号 serialnumber")
    upload.add_argument("--package-name")
    upload.add_argument("--file", default=DEFAULT_APK)
    upload.add_argument(
        "--method",
        default="app.upload.apk.app",
        help="app.upload.apk.app / app.upload.icon / app.upload.screenshot 等",
    )
    upload.add_argument("--stage-type", type=int, help="分阶段包传 1")
    upload.add_argument("--dry-run", action="store_true")

    update = sub.add_parser("update", help="app.sync.update.app：用已有流水号提交更新")
    update.add_argument("--version-code", required=True)
    update.add_argument("--serialnumber", required=True, help="apk 上传返回的流水号")
    update.add_argument("--file-md5", required=True)
    add_update_args(update)

    publish = sub.add_parser("publish", help="一条龙：上传 APK → 同步更新提交审核")
    publish.add_argument("--apk", default=DEFAULT_APK)
    publish.add_argument("--version-code", help="默认取上传接口解析出的 versionCode")
    add_update_args(publish)

    return parser


def main() -> None:
    args = build_parser().parse_args()
    config_path = Path(args.config).expanduser() if args.config else None
    # doctor reports on missing credentials; --dry-run never leaves the machine.
    offline = args.command == "doctor" or getattr(args, "dry_run", False)
    cfg = get_config(config_path, require_auth=not offline)
    commands = {
        "doctor": cmd_doctor,
        "detail": cmd_detail,
        "upload": cmd_upload,
        "update": cmd_update,
        "publish": cmd_publish,
    }
    commands[args.command](cfg, args)


if __name__ == "__main__":
    main()
