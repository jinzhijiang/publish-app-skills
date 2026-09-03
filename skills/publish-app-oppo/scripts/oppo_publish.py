#!/usr/bin/env python3
"""OPPO 开放平台 API 传包 client.

Docs: https://open.oppomobile.com/documentation/page/info?id=10998 (API传包能力接入)
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import mimetypes
import os
import re
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

API_BASE = "https://oop-openapi-cn.heytapmobi.com"
TOKEN_PATH = "/developer/v1/token"

DEFAULT_APK = "build/app/outputs/channels/oppo-app-release.apk"
DEFAULT_PKG = ""  # 必填，由 <项目>/oppo.env 提供

SKILL_DIR = Path(__file__).resolve().parents[1]
CONFIG_ENV = SKILL_DIR / "config.env"


def project_name() -> str:
    """Project identity for per-project credential isolation.

    Priority: $OPPO_PROJECT > git root dir name (from cwd) > cwd name.
    Mirrors the countly-data-analysis convention so one machine can hold
    credentials for many apps without them silently crossing over.
    """
    override = os.environ.get("OPPO_PROJECT")
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

USER_CONFIG_ENV = Path.home() / ".config" / "ai-ignore-config" / project_name() / "oppo.env"
TOKEN_CACHE = Path.home() / ".config" / "ai-ignore-config" / project_name() / ".oppo_token.json"

# Fields carried over from /resource/v1/app/info into /resource/v1/app/upd.
# 发布版本接口要求整份资料一起提交，只传 apk 会把商店文案和资质清空。
REUSED_FIELDS = (
    "app_name",
    "app_subname",
    "second_category_id",
    "third_category_id",
    "summary",
    "detail_desc",
    "privacy_source_url",
    "icon_url",
    "pic_url",
    "landscape_pic_url",
    "video_url",
    "test_desc",
    "copyright_url",
    "electronic_cert_url",
    "icp_url",
    "special_url",
    "special_file_url",
    "business_username",
    "business_email",
    "business_mobile",
    "age_level",
    "adaptive_equipment",
    "adaptive_type",
)

# 发布版本接口的必传字段（普通应用），用于提交前自查
REQUIRED_FIELDS = (
    "pkg_name",
    "version_code",
    "apk_url",
    "app_name",
    "second_category_id",
    "third_category_id",
    "summary",
    "detail_desc",
    "update_desc",
    "privacy_source_url",
    "icon_url",
    "pic_url",
    "online_type",
    "test_desc",
    "copyright_url",
    "business_username",
    "business_email",
    "business_mobile",
    "age_level",
    "adaptive_equipment",
)

AUDIT_STATUS = {
    "0": "未发布",
    "1": "审核中",
    "2": "审核通过",
    "3": "测试不通过",
    "4": "运营审核中",
    "5": "运营打回",
    "6": "运营通过",
    "7": "定时发布",
    "00": "资质审核中",
    "11": "资质审核通过",
    "-11": "资质审核不通过",
    "-22": "报备提交成功",
    "22": "已冻结",
    "111": "上线",
    "222": "下线",
    "444": "审核不通过",
}

TASK_STATE = {"1": "待处理", "2": "处理成功", "3": "处理失败"}


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
        "client_id": os.environ.get("OPPO_CLIENT_ID", ""),
        "client_secret": os.environ.get("OPPO_CLIENT_SECRET", ""),
        "package_name": os.environ.get("OPPO_PACKAGE_NAME", DEFAULT_PKG),
        "online_type": os.environ.get("OPPO_ONLINE_TYPE", "1"),
        "_config_path": str(loaded or ""),
    }
    if require_auth and not (cfg["client_id"] and cfg["client_secret"] and cfg["package_name"]):
        print(
            "error: missing credentials (OPPO_CLIENT_ID, OPPO_CLIENT_SECRET, OPPO_PACKAGE_NAME).\n"
            f"  Recommended: cp {SKILL_DIR / 'config.example.env'} {USER_CONFIG_ENV}\n"
            f"  Then edit {USER_CONFIG_ENV}. Loaded config: {loaded or 'none'}",
            file=sys.stderr,
        )
        sys.exit(2)
    return cfg


# --------------------------------------------------------------------------- http


SECRET_QUERY_KEYS = ("access_token", "api_sign", "client_secret", "sign")


def redact(url: str) -> str:
    """Strip credentials out of a URL before it reaches stderr or a CI log."""
    parts = urllib.parse.urlsplit(url)
    if not parts.query:
        return url
    pairs = [
        (key, "<redacted>" if key in SECRET_QUERY_KEYS else value)
        for key, value in urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
    ]
    return urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(pairs)))


def http_request(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    data: Any = None,
    timeout: int = 300,
) -> str:
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        print(f"error: HTTP {e.code} {redact(url)}\n{raw}", file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"error: request failed {redact(url)}: {e.reason}", file=sys.stderr)
        sys.exit(1)


def check_result(raw: str, *, label: str) -> Any:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        print(f"error: {label} returned non-JSON: {raw}", file=sys.stderr)
        sys.exit(1)
    errno = payload.get("errno")
    if errno != 0:
        data = payload.get("data") or {}
        message = data.get("message") if isinstance(data, dict) else payload.get("message")
        print(f"error: {label} failed, errno={errno}, message={message}", file=sys.stderr)
        sys.exit(1)
    return payload.get("data")


# --------------------------------------------------------------------------- auth


def read_cached_token(client_id: str) -> str | None:
    if not TOKEN_CACHE.is_file():
        return None
    try:
        cached = json.loads(TOKEN_CACHE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if cached.get("client_id") != client_id:
        return None
    # expire_in is an absolute unix timestamp; keep a 10 minute safety margin.
    if int(cached.get("expire_in", 0)) - 600 < int(time.time()):
        return None
    return cached.get("access_token")


def write_cached_token(client_id: str, token: str, expire_in: int) -> None:
    try:
        TOKEN_CACHE.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_CACHE.write_text(
            json.dumps({"client_id": client_id, "access_token": token, "expire_in": expire_in}),
            encoding="utf-8",
        )
        TOKEN_CACHE.chmod(0o600)
    except OSError as e:
        print(f"warning: could not cache token ({e})", file=sys.stderr)


def get_access_token(cfg: dict[str, str], *, force: bool = False) -> str:
    """Token lives 48h. Re-fetching expires the previous one within 5 minutes,
    so cache it on disk instead of pulling a fresh one on every run."""
    if not force:
        cached = read_cached_token(cfg["client_id"])
        if cached:
            return cached
    query = urllib.parse.urlencode(
        {"client_id": cfg["client_id"], "client_secret": cfg["client_secret"]}
    )
    raw = http_request(f"{API_BASE}{TOKEN_PATH}?{query}", timeout=60)
    data = check_result(raw, label="get token") or {}
    token = data.get("access_token")
    if not token:
        print(f"error: no access_token in response: {raw}", file=sys.stderr)
        sys.exit(1)
    write_cached_token(cfg["client_id"], token, int(data.get("expire_in", 0)))
    return token


def signed_params(token: str, client_secret: str, business: dict[str, Any]) -> dict[str, str]:
    params = {str(k): str(v) for k, v in business.items() if v is not None}
    params["access_token"] = token
    params["timestamp"] = str(int(time.time()))
    sign_data = "&".join(f"{key}={params[key]}" for key in sorted(params))
    params["api_sign"] = hmac.new(
        client_secret.encode("utf-8"), sign_data.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return params


def api_get(cfg: dict[str, str], token: str, path: str, business: dict[str, Any], *, label: str) -> Any:
    query = urllib.parse.urlencode(signed_params(token, cfg["client_secret"], business))
    return check_result(http_request(f"{API_BASE}{path}?{query}", timeout=120), label=label)


def api_post(
    cfg: dict[str, str],
    token: str,
    path: str,
    business: dict[str, Any],
    *,
    label: str,
    timeout: int = 300,
) -> Any:
    body = urllib.parse.urlencode(signed_params(token, cfg["client_secret"], business))
    raw = http_request(
        f"{API_BASE}{path}",
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data=body.encode("utf-8"),
        timeout=timeout,
    )
    return check_result(raw, label=label)


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


def version_code_from_pubspec() -> str | None:
    """`version: 3.3.0+30004` in the Flutter project root -> `30004`.

    Looked up from the CALLER's cwd upward, not relative to the skill: the skill
    is installed globally, so its own location says nothing about which project
    is being published.
    """
    for base in (Path.cwd(), *Path.cwd().parents):
        pubspec = base / "pubspec.yaml"
        if pubspec.is_file():
            match = re.search(
                r"^version:\s*\S+\+(\d+)\s*$", pubspec.read_text(encoding="utf-8"), re.M
            )
            return match.group(1) if match else None
    return None


def clean_urls(value: Any) -> Any:
    """/app/info returns comma-joined URL lists that can carry empty trailing slots
    (`"http://a.jpg,,"`); posting those back trips the validator."""
    if not isinstance(value, str) or "," not in value:
        return value
    return ",".join(part for part in value.split(",") if part.strip())


def upload_file(cfg: dict[str, str], token: str, path: Path, file_type: str) -> dict[str, Any]:
    """get-upload-url -> POST the bytes -> return {url, md5, ...}."""
    slot = api_get(cfg, token, "/resource/v1/upload/get-upload-url", {}, label="get-upload-url") or {}
    upload_url = slot.get("upload_url")
    one_time_sign = slot.get("sign")
    if not (upload_url and one_time_sign):
        print(f"error: get-upload-url returned no slot: {slot}", file=sys.stderr)
        sys.exit(1)

    boundary = "----oppo-publish-" + uuid.uuid4().hex
    mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"

    # Stream through a temp file so multi-hundred-MB APKs never sit in memory twice.
    with tempfile.TemporaryFile() as body:
        for key, value in (("type", file_type), ("sign", one_time_sign)):
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
            upload_url,
            method="POST",
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Content-Length": str(length),
            },
            data=body,
            timeout=1800,
        )
    return check_result(raw, label="file upload") or {}


def build_upd_body(
    detail: dict[str, Any],
    args: argparse.Namespace,
    cfg: dict[str, str],
    *,
    version_code: str,
    apk_url: str,
    update_desc: str,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "pkg_name": args.package_name or cfg["package_name"],
        "version_code": version_code,
        "apk_url": apk_url,
        "update_desc": update_desc,
        "online_type": args.online_type or cfg["online_type"],
    }
    for field in REUSED_FIELDS:
        value = clean_urls(detail.get(field))
        if value not in (None, ""):
            body[field] = value
    if args.sche_online_time:
        body["sche_online_time"] = args.sche_online_time
    for spec in args.set or []:
        key, _, value = spec.partition("=")
        body[key.strip()] = value
    # --omit 让某个字段整个不出现在请求里，交给平台沿用上一版的值。
    omitted = {field.strip() for field in (args.omit or [])}
    for field in omitted:
        body.pop(field, None)

    if str(body["online_type"]) == "2" and not body.get("sche_online_time"):
        print(
            "error: online_type 2 (定时发布) requires --sche-online-time 'yyyy-MM-dd HH:mm:ss'",
            file=sys.stderr,
        )
        sys.exit(2)
    missing = [field for field in REQUIRED_FIELDS if field not in omitted and not body.get(field)]
    if missing:
        print(
            "error: 发布版本缺少必传字段: "
            + ", ".join(missing)
            + "\n  这些值通常从 /resource/v1/app/info 继承；控制台上没填过就继承不到，"
            "先在控制台补齐，或用 --set key=value 显式传入。",
            file=sys.stderr,
        )
        sys.exit(2)
    return body


# --------------------------------------------------------------------------- commands


def cmd_doctor(cfg: dict[str, str], args: argparse.Namespace) -> None:
    apk = Path(args.apk).expanduser()
    report: dict[str, Any] = {
        "configPath": cfg["_config_path"] or "none",
        "hasClientId": bool(cfg["client_id"]),
        "hasClientSecret": bool(cfg["client_secret"]),
        "packageName": cfg["package_name"],
        "apkPath": args.apk,
        "apkExists": apk.is_file(),
        "versionCodeFromPubspec": version_code_from_pubspec(),
    }
    if cfg["client_id"] and cfg["client_secret"]:
        token = get_access_token(cfg)
        report["tokenOk"] = True
        report["tokenCache"] = str(TOKEN_CACHE) if TOKEN_CACHE.is_file() else "none"
        detail = (
            api_get(
                cfg,
                token,
                "/resource/v1/app/info",
                {"pkg_name": cfg["package_name"]},
                label="app/info",
            )
            or {}
        )
        report["appId"] = detail.get("app_id")
        report["onlineVersionCode"] = detail.get("version_code")
        report["auditStatus"] = detail.get("audit_status")
        report["auditStatusName"] = detail.get("audit_status_name") or AUDIT_STATUS.get(
            str(detail.get("audit_status"))
        )
        report["missingForPublish"] = [
            field
            for field in REUSED_FIELDS
            if field in REQUIRED_FIELDS and not detail.get(field)
        ]
    else:
        report["tokenOk"] = False
    dump(report)


def cmd_token(cfg: dict[str, str], args: argparse.Namespace) -> None:
    token = get_access_token(cfg, force=args.force)
    dump({"tokenPrefix": token[:16] + "...", "length": len(token), "cache": str(TOKEN_CACHE)})


def cmd_info(cfg: dict[str, str], args: argparse.Namespace) -> None:
    token = get_access_token(cfg)
    business: dict[str, Any] = {"pkg_name": args.package_name or cfg["package_name"]}
    if args.version_code:
        business["version_code"] = args.version_code
    detail = api_get(cfg, token, "/resource/v1/app/info", business, label="app/info") or {}
    if args.field:
        dump({field: detail.get(field) for field in args.field})
        return
    dump(detail)


def cmd_upload(cfg: dict[str, str], args: argparse.Namespace) -> None:
    path = existing_file(args.file, "file")
    if args.dry_run:
        dump({"file": str(path), "type": args.type, "size": path.stat().st_size})
        return
    token = get_access_token(cfg)
    dump(upload_file(cfg, token, path, args.type))


def cmd_task_state(cfg: dict[str, str], args: argparse.Namespace) -> None:
    token = get_access_token(cfg)
    state = api_post(
        cfg,
        token,
        "/resource/v1/app/task-state",
        {
            "pkg_name": args.package_name or cfg["package_name"],
            "version_code": args.version_code,
        },
        label="task-state",
    )
    if isinstance(state, dict):
        state["task_state_name"] = TASK_STATE.get(str(state.get("task_state")), "未知")
    dump(state)


def cmd_publish(cfg: dict[str, str], args: argparse.Namespace) -> None:
    apk = existing_file(args.apk, "apk")
    package_name = args.package_name or cfg["package_name"]
    version_code = args.version_code or version_code_from_pubspec()
    if not version_code:
        print(
            "error: --version-code is required (could not read `version: x.y.z+CODE` "
            "from pubspec.yaml)",
            file=sys.stderr,
        )
        sys.exit(2)

    if args.dry_run:
        dump(
            {
                "pkgName": package_name,
                "apk": str(apk),
                "apkSize": apk.stat().st_size,
                "apkMd5": file_md5(apk),
                "versionCode": version_code,
                "updateDesc": args.update_desc,
                "overrides": args.set or [],
                "note": "离线预演。资料字段在真实运行时从 /resource/v1/app/info 继承，"
                "用 --preview 可以只读地看到合并后的完整 body",
            }
        )
        return

    if args.preview:
        token = get_access_token(cfg)
        detail = (
            api_get(
                cfg, token, "/resource/v1/app/info", {"pkg_name": package_name}, label="app/info"
            )
            or {}
        )
        body = build_upd_body(
            detail,
            args,
            cfg,
            version_code=version_code,
            apk_url=json.dumps(
                [
                    {
                        "url": "<upload 后回填>",
                        "md5": file_md5(apk),
                        "cpu_code": args.cpu_code,
                    }
                ],
                ensure_ascii=False,
            ),
            update_desc=args.update_desc,
        )
        dump({"onlineVersionCode": detail.get("version_code"), "wouldPost": body})
        return

    token = get_access_token(cfg)
    uploaded = upload_file(cfg, token, apk, "apk")
    apk_url, apk_md5 = uploaded.get("url"), uploaded.get("md5")
    print(f"uploaded {apk.name} -> {apk_url}", file=sys.stderr)

    detail = (
        api_get(
            cfg, token, "/resource/v1/app/info", {"pkg_name": package_name}, label="app/info"
        )
        or {}
    )
    online_version = str(detail.get("version_code") or "")
    if online_version and int(version_code) <= int(online_version):
        print(
            f"error: version_code {version_code} must be greater than the online "
            f"version {online_version}",
            file=sys.stderr,
        )
        sys.exit(1)

    body = build_upd_body(
        detail,
        args,
        cfg,
        version_code=version_code,
        apk_url=json.dumps(
            [{"url": apk_url, "md5": apk_md5, "cpu_code": args.cpu_code}], ensure_ascii=False
        ),
        update_desc=args.update_desc,
    )
    api_post(cfg, token, "/resource/v1/app/upd", body, label="app/upd", timeout=600)
    print("submitted 发布版本 (异步任务)，用 task-state 查处理结果", file=sys.stderr)
    dump({"pkgName": package_name, "versionCode": version_code, "apkUrl": apk_url})


# --------------------------------------------------------------------------- cli


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="OPPO 开放平台 API 传包 client")
    parser.add_argument("--config", help="Credentials file path")
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="检查凭据、线上版本与本地 APK")
    doctor.add_argument("--apk", default=DEFAULT_APK)

    token = sub.add_parser("token", help="换取 access_token（默认走本地缓存）")
    token.add_argument("--force", action="store_true", help="强制换新 token，旧 token 5 分钟后失效")

    info = sub.add_parser("info", help="查询应用详情 /resource/v1/app/info")
    info.add_argument("--package-name")
    info.add_argument("--version-code", help="默认取最新版本")
    info.add_argument("--field", action="append", help="只输出指定字段，可重复")

    upload = sub.add_parser("upload", help="上传单个文件，返回 url 与 md5")
    upload.add_argument("--file", default=DEFAULT_APK)
    upload.add_argument("--type", default="apk", choices=["apk", "photo", "resource"])
    upload.add_argument("--dry-run", action="store_true")

    task = sub.add_parser("task-state", help="查询发布版本异步任务的处理结果")
    task.add_argument("--package-name")
    task.add_argument("--version-code", required=True)

    publish = sub.add_parser("publish", help="一条龙：上传 APK → 继承线上资料 → 发布版本")
    publish.add_argument("--apk", default=DEFAULT_APK)
    publish.add_argument("--package-name")
    publish.add_argument("--version-code", help="默认读 pubspec.yaml 的 version: x.y.z+CODE")
    publish.add_argument("--update-desc", required=True, help="版本说明，不少于 5 个字")
    publish.add_argument("--online-type", help="1=审核立即发布 2=定时发布")
    publish.add_argument("--sche-online-time", help="定时发布时间 yyyy-MM-dd HH:mm:ss")
    publish.add_argument("--cpu-code", type=int, default=0, help="非多包应用为 0")
    publish.add_argument(
        "--set",
        action="append",
        metavar="key=value",
        help="覆盖或补充任意发布参数，可重复，例如 --set age_level=12",
    )
    publish.add_argument(
        "--omit",
        action="append",
        metavar="FIELD",
        help="不提交某个继承字段（跳过必传校验），让平台沿用上一版的值，可重复",
    )
    publish.add_argument("--dry-run", action="store_true", help="离线预演，不发任何请求")
    publish.add_argument(
        "--preview",
        action="store_true",
        help="只读预演：查线上资料并打印合并后的完整提交 body，不上传也不提交",
    )

    return parser


def main() -> None:
    args = build_parser().parse_args()
    config_path = Path(args.config).expanduser() if args.config else None
    # doctor reports on missing credentials; --dry-run never leaves the machine.
    offline = args.command == "doctor" or getattr(args, "dry_run", False)
    cfg = get_config(config_path, require_auth=not offline)
    commands = {
        "doctor": cmd_doctor,
        "token": cmd_token,
        "info": cmd_info,
        "upload": cmd_upload,
        "task-state": cmd_task_state,
        "publish": cmd_publish,
    }
    commands[args.command](cfg, args)


if __name__ == "__main__":
    main()
