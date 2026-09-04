#!/usr/bin/env python3
"""Honor AppMarket (荣耀应用市场) Publish-API client.

Docs: https://developer.honor.com/cn/doc/guides/101359
"""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any

TOKEN_URL = "https://iam.developer.honor.com/auth/token"
API_BASE = "https://appmarket-openapi-drcn.cloud.honor.com/openapi/v1/publish"

DEFAULT_APK = "build/app/outputs/channels/honor-app-release.apk"
DEFAULT_PKG = ""  # 必填，由 <项目>/honor.env 提供
DEFAULT_LANGUAGE = "zh-CN"

FILE_TYPE_APK = 100

SKILL_DIR = Path(__file__).resolve().parents[1]
CONFIG_ENV = SKILL_DIR / "config.env"


def project_name() -> str:
    """Project identity for per-project credential isolation.

    Priority: $HONOR_PROJECT > git root dir name (from cwd) > cwd name.
    Mirrors the countly-data-analysis convention so one machine can hold
    credentials for many apps without them silently crossing over.
    """
    override = os.environ.get("HONOR_PROJECT")
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

USER_CONFIG_ENV = Path.home() / ".config" / "ai-ignore-config" / project_name() / "honor.env"

ERROR_CODES = {
    10001: "未传递 access_token",
    10002: "access_token 非合法格式",
    10003: "access_token 已过期",
    10004: "横向越权，无请求资源的操作权限",
    10005: "纵向越权，无权限访问当前资源",
    11003: "非法安装包名",
    20005: "请求的 APPID 不存在",
    20022: "应用正在审核中，不允许提交",
    20023: "应用未上架过，不允许提交",
    20030: "objectId 不存在",
    20078: "指定的媒体资源横纵向互相冲突",
    30003: "应用包名和 APK 中解析的包名不一致",
    30005: "应用包无法解析",
    30006: "应用包版本低于之前上架的版本",
    30007: "应用包名和之前版本不一致",
    30010: "文件上传失败",
    30011: "版本提交过于频繁，请稍后再试",
    30017: "应用不存在指定的语言信息",
    40000: "系统服务异常",
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
    if path is None:
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
        "client_id": os.environ.get("HONOR_CLIENT_ID", ""),
        "client_secret": os.environ.get("HONOR_CLIENT_SECRET", ""),
        "package_name": os.environ.get("HONOR_PACKAGE_NAME", DEFAULT_PKG),
        "app_id": os.environ.get("HONOR_APP_ID", ""),
        "default_language": os.environ.get("HONOR_DEFAULT_LANGUAGE", DEFAULT_LANGUAGE),
        "_config_path": str(loaded or ""),
    }
    if require_auth and not (cfg["client_id"] and cfg["client_secret"] and cfg["package_name"]):
        print(
            "error: missing credentials (HONOR_CLIENT_ID, HONOR_CLIENT_SECRET, HONOR_PACKAGE_NAME).\n"
            f"  Recommended: cp {SKILL_DIR / 'config.example.env'} {USER_CONFIG_ENV}\n"
            f"  Then edit {USER_CONFIG_ENV}. Loaded config: {loaded or 'none'}",
            file=sys.stderr,
        )
        sys.exit(2)
    return cfg


# --------------------------------------------------------------------------- http


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
        print(f"error: HTTP {e.code} {url}\n{raw}", file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"error: request failed {url}: {e.reason}", file=sys.stderr)
        sys.exit(1)


def get_access_token(cfg: dict[str, str]) -> str:
    body = urllib.parse.urlencode(
        {
            "grant_type": "client_credentials",
            "client_id": cfg["client_id"],
            "client_secret": cfg["client_secret"],
        }
    ).encode("utf-8")
    raw = http_request(
        TOKEN_URL,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data=body,
        timeout=60,
    )
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        print(f"error: token response is not JSON: {raw}", file=sys.stderr)
        sys.exit(1)
    token = data.get("access_token")
    if not token:
        print(f"error: no access_token in response: {raw}", file=sys.stderr)
        sys.exit(1)
    return token


def auth_headers(token: str, *, json_body: bool = False) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if json_body:
        headers["Content-Type"] = "application/json"
    return headers


def check_result(raw: str, *, label: str) -> Any:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        print(f"error: {label} returned non-JSON: {raw}", file=sys.stderr)
        sys.exit(1)
    code = data.get("code")
    if code != 0:
        hint = ERROR_CODES.get(code, "")
        suffix = f" ({hint})" if hint else ""
        print(
            f"error: {label} failed, code={code}{suffix}, msg={data.get('msg')}",
            file=sys.stderr,
        )
        sys.exit(1)
    return data.get("data")


def api_get(token: str, path: str, params: dict[str, Any] | None = None, *, label: str) -> Any:
    url = f"{API_BASE}/{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    raw = http_request(url, headers=auth_headers(token), timeout=120)
    return check_result(raw, label=label)


def api_post(
    token: str,
    path: str,
    body: Any,
    params: dict[str, Any] | None = None,
    *,
    label: str,
    timeout: int = 300,
) -> Any:
    url = f"{API_BASE}/{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    raw = http_request(
        url,
        method="POST",
        headers=auth_headers(token, json_body=True),
        data=payload,
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


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def dry_app_id(cfg: dict[str, str], override: str | None = None) -> Any:
    """appId for --dry-run output, without spending a token request."""
    if override:
        return int(override)
    if cfg["app_id"]:
        return int(cfg["app_id"])
    return f"<resolved from get-app-id {cfg['package_name']}>"


def resolve_app_id(token: str, cfg: dict[str, str], override: str | None = None) -> int:
    if override:
        return int(override)
    if cfg["app_id"]:
        return int(cfg["app_id"])
    package_name = cfg["package_name"]
    data = api_get(token, "get-app-id", {"pkgName": package_name}, label="get-app-id") or []
    for item in data:
        if item.get("packageName") == package_name:
            return int(item["appId"])
    print(
        f"error: no appId returned for package {package_name}; "
        "check that the app exists under this account and the package name is bound.",
        file=sys.stderr,
    )
    sys.exit(1)


def upload_file(
    token: str,
    app_id: int,
    path: Path,
    file_type: int,
    *,
    upload_via: str = "api",
) -> int:
    """Register a file, upload the bytes, return the objectId."""
    meta = {
        "fileName": path.name,
        "fileType": file_type,
        "fileSize": path.stat().st_size,
        "fileSha256": file_sha256(path),
    }
    slots = api_post(
        token,
        "get-file-upload-url",
        [meta],
        {"appId": app_id},
        label="get-file-upload-url",
    )
    if not slots:
        print("error: get-file-upload-url returned no slot", file=sys.stderr)
        sys.exit(1)
    slot = slots[0]
    object_id = int(slot["objectId"])

    if upload_via == "url":
        url = slot["uploadUrl"]
    else:
        url = f"{API_BASE}/file-upload?" + urllib.parse.urlencode(
            {"appId": app_id, "objectId": object_id}
        )

    boundary = "----honor-publish-" + uuid.uuid4().hex
    mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    head = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
        f"Content-Type: {mime_type}\r\n\r\n"
    ).encode("utf-8")
    tail = f"\r\n--{boundary}--\r\n".encode("utf-8")

    # Stream through a temp file so multi-hundred-MB APKs never sit in memory twice.
    with tempfile.TemporaryFile() as body:
        body.write(head)
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                body.write(chunk)
        body.write(tail)
        length = body.tell()
        body.seek(0)
        raw = http_request(
            url,
            method="POST",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Content-Length": str(length),
            },
            data=body,
            timeout=1800,
        )
    check_result(raw, label="file-upload")
    return object_id


def parse_binding(spec: str) -> dict[str, Any]:
    """objectId[:languageId[:order]] -> BindingFile dict."""
    parts = spec.split(":")
    binding: dict[str, Any] = {"objectId": int(parts[0])}
    if len(parts) > 1 and parts[1]:
        binding["languageId"] = parts[1]
    if len(parts) > 2 and parts[2]:
        binding["order"] = int(parts[2])
    return binding


def merged_language_info(
    token: str,
    app_id: int,
    *,
    new_feature: str | None,
    language_ids: list[str],
    app_name: str | None = None,
    intro: str | None = None,
    brief_intro: str | None = None,
) -> list[dict[str, Any]]:
    """Build the full PubLanguageInfo list for update-language-info.

    The endpoint requires appName and intro on every entry, so an update that
    only wants to change newFeature must carry the existing copy back — that is
    what the no-override path does.

    First launch has no existing languageInfo at all (only appName, set when the
    app was created on the console). Then the caller must supply `intro` via
    override; appName/briefIntro fall back to whatever the console already has.
    """
    detail = api_get(token, "get-app-detail", {"appId": app_id}, label="get-app-detail") or {}
    existing = detail.get("languageInfo") or []
    if not existing and intro is None:
        print(
            "error: app has no existing language info. First launch must supply the "
            "required intro: --intro / --intro-file (appName defaults to the console value).",
            file=sys.stderr,
        )
        sys.exit(1)
    if not existing:
        # 首发：控制台建应用时只落了 appName，languageInfo 还是空的
        existing = [{"languageId": lid, "appName": app_name or "", "intro": ""} for lid in language_ids]
    targets = set(language_ids)
    out: list[dict[str, Any]] = []
    for item in existing:
        if item.get("languageId") not in targets:
            continue
        out.append(
            {
                "languageId": item.get("languageId"),
                "appName": app_name or item.get("appName"),
                "intro": intro if intro is not None else item.get("intro"),
                "briefIntro": brief_intro if brief_intro is not None else (item.get("briefIntro") or ""),
                "newFeature": new_feature if new_feature is not None else (item.get("newFeature") or ""),
            }
        )
    if not out:
        have = ", ".join(str(i.get("languageId")) for i in existing)
        print(
            f"error: none of {sorted(targets)} exist on this app; available languages: {have}",
            file=sys.stderr,
        )
        sys.exit(1)
    return out


def build_submit_body(args: argparse.Namespace) -> dict[str, Any]:
    body: dict[str, Any] = {
        "forceUpdate": args.force_update,
        "releaseType": args.release_type,
    }
    if args.release_time:
        body["releaseTime"] = args.release_time
    for key, value in (
        ("testAccount", args.test_account),
        ("testPassword", args.test_password),
        ("testComment", args.test_comment),
    ):
        if value:
            body[key] = value
    if args.release_type == 3:
        missing = [
            name
            for name, value in (
                ("--percentage", args.percentage),
                ("--start", args.start),
                ("--end", args.end),
                ("--note", args.note),
            )
            if not value
        ]
        if missing:
            print(
                "error: releaseType 3 (分阶段发布) requires " + ", ".join(missing),
                file=sys.stderr,
            )
            sys.exit(2)
        body["phasedReleaseInfo"] = {
            "releasePercentage": args.percentage,
            "releaseStartDate": args.start,
            "releaseEndDate": args.end,
            "releaseNote": args.note,
        }
    elif args.release_type == 2 and not args.release_time:
        print("error: releaseType 2 (指定时间发布) requires --release-time", file=sys.stderr)
        sys.exit(2)
    return body


# --------------------------------------------------------------------------- commands


def cmd_doctor(cfg: dict[str, str], args: argparse.Namespace) -> None:
    report: dict[str, Any] = {
        "configPath": cfg["_config_path"] or "none",
        "hasClientId": bool(cfg["client_id"]),
        "hasClientSecret": bool(cfg["client_secret"]),
        "packageName": cfg["package_name"],
        "configuredAppId": cfg["app_id"] or None,
        "defaultLanguage": cfg["default_language"],
        "apkPath": args.apk,
        "apkExists": Path(args.apk).expanduser().is_file(),
    }
    if cfg["client_id"] and cfg["client_secret"]:
        token = get_access_token(cfg)
        report["tokenOk"] = True
        data = api_get(
            token, "get-app-id", {"pkgName": cfg["package_name"]}, label="get-app-id"
        )
        report["appIdLookup"] = data
    else:
        report["tokenOk"] = False
    dump(report)


def cmd_token(cfg: dict[str, str], args: argparse.Namespace) -> None:
    token = get_access_token(cfg)
    dump({"tokenPrefix": token[:12] + "...", "length": len(token)})


def cmd_appid(cfg: dict[str, str], args: argparse.Namespace) -> None:
    token = get_access_token(cfg)
    package_name = args.package_name or cfg["package_name"]
    dump(api_get(token, "get-app-id", {"pkgName": package_name}, label="get-app-id"))


def cmd_detail(cfg: dict[str, str], args: argparse.Namespace) -> None:
    token = get_access_token(cfg)
    app_id = resolve_app_id(token, cfg, args.app_id)
    detail = api_get(token, "get-app-detail", {"appId": app_id}, label="get-app-detail")
    if args.section != "all" and isinstance(detail, dict):
        detail = detail.get(args.section)
    dump(detail)


def cmd_current_release(cfg: dict[str, str], args: argparse.Namespace) -> None:
    token = get_access_token(cfg)
    app_id = resolve_app_id(token, cfg, args.app_id)
    dump(
        api_get(
            token,
            "get-app-current-release",
            {"appId": app_id},
            label="get-app-current-release",
        )
    )


def cmd_upload(cfg: dict[str, str], args: argparse.Namespace) -> None:
    path = existing_file(args.file, "file")
    if args.dry_run:
        dump(
            {
                "appId": dry_app_id(cfg, args.app_id),
                "fileName": path.name,
                "fileType": args.file_type,
                "fileSize": path.stat().st_size,
                "fileSha256": file_sha256(path),
            }
        )
        return
    token = get_access_token(cfg)
    app_id = resolve_app_id(token, cfg, args.app_id)
    object_id = upload_file(token, app_id, path, args.file_type, upload_via=args.upload_via)
    dump({"appId": app_id, "fileName": path.name, "objectId": object_id})


def cmd_bind(cfg: dict[str, str], args: argparse.Namespace) -> None:
    body = {"bindingFileList": [parse_binding(spec) for spec in args.object_id]}
    if args.dry_run:
        dump({"endpoint": "update-file-info", "appId": dry_app_id(cfg, args.app_id), "body": body})
        return
    token = get_access_token(cfg)
    app_id = resolve_app_id(token, cfg, args.app_id)
    api_post(token, "update-file-info", body, {"appId": app_id}, label="update-file-info")
    dump({"appId": app_id, "bound": body["bindingFileList"]})


def cmd_language(cfg: dict[str, str], args: argparse.Namespace) -> None:
    language_ids = args.language_id or [cfg["default_language"]]
    if args.dry_run:
        dump(
            {
                "endpoint": "update-language-info",
                "appId": dry_app_id(cfg, args.app_id),
                "languageIds": language_ids,
                "newFeature": args.new_feature,
                "setAll": args.set_all,
                "note": "appName/intro/briefIntro are read from get-app-detail at run time",
            }
        )
        return
    def _text(inline: str | None, path: str | None, label: str) -> str | None:
        if inline and path:
            print(f"error: pass only one of --{label} / --{label}-file", file=sys.stderr)
            sys.exit(2)
        if path:
            f = Path(path).expanduser()
            if not f.is_file():
                print(f"error: {label} file not found: {f}", file=sys.stderr)
                sys.exit(2)
            return f.read_text(encoding="utf-8").strip()
        return inline

    intro = _text(args.intro, args.intro_file, "intro")
    brief = _text(args.brief_intro, args.brief_intro_file, "brief-intro")
    if not any([args.new_feature, args.app_name, intro, brief]):
        print(
            "error: nothing to update: pass at least one of --new-feature / --app-name / "
            "--intro(-file) / --brief-intro(-file)",
            file=sys.stderr,
        )
        sys.exit(2)

    token = get_access_token(cfg)
    app_id = resolve_app_id(token, cfg, args.app_id)
    info = merged_language_info(
        token,
        app_id,
        new_feature=args.new_feature,
        language_ids=language_ids,
        app_name=args.app_name,
        intro=intro,
        brief_intro=brief,
    )
    body = {"languageInfoList": info, "setAll": args.set_all}
    api_post(
        token, "update-language-info", body, {"appId": app_id}, label="update-language-info"
    )
    dump({"appId": app_id, "updated": [i["languageId"] for i in info]})


def cmd_app_info(cfg: dict[str, str], args: argparse.Namespace) -> None:
    """update-app-info：只提交显式给出的字段。

    这个接口没有"先读回再整体回传"的必要——实测未提交的字段保持原值。
    字段名与 get-app-detail 的 basicInfo 同名，不确定某个字段叫什么时先跑
    `detail` 看键名，别猜。
    """
    fields: dict[str, Any] = {}
    for cli, key in (
        ("privacy_policy_url", "privacyPolicyUrl"),
        ("web_url", "webUrl"),
        ("customer_service_email", "customerServiceEmail"),
        ("customer_service_tel", "customerServiceTel"),
        ("rating_id", "ratingId"),
        ("release_country", "releaseCountry"),
        ("app_registration_number", "appRegistrationNumber"),
        ("app_registration_entity_name", "appRegistrationEntityName"),
        ("unified_social_credit_id", "unifiedSocialCreditId"),
        ("publication_number", "publicationNumber"),
    ):
        v = getattr(args, cli, None)
        if v:
            fields[key] = v
    for pair in args.set or []:
        if "=" not in pair:
            print(f"error: --set expects key=value, got {pair!r}", file=sys.stderr)
            sys.exit(2)
        k, _, v = pair.partition("=")
        fields[k.strip()] = v
    if not fields:
        print(
            "error: nothing to update. Pass --privacy-policy-url / --web-url / ... "
            "or --set key=value (键名见 `detail` 的 basicInfo)",
            file=sys.stderr,
        )
        sys.exit(2)
    if args.dry_run:
        dump({"endpoint": "update-app-info", "appId": dry_app_id(cfg, args.app_id), "body": fields})
        return
    token = get_access_token(cfg)
    app_id = resolve_app_id(token, cfg, args.app_id)
    api_post(token, "update-app-info", fields, {"appId": app_id}, label="update-app-info")
    dump({"appId": app_id, "updated": sorted(fields)})


def cmd_submit(cfg: dict[str, str], args: argparse.Namespace) -> None:
    body = build_submit_body(args)
    if args.dry_run:
        dump({"endpoint": "submit-audit", "appId": dry_app_id(cfg, args.app_id), "body": body})
        return
    token = get_access_token(cfg)
    app_id = resolve_app_id(token, cfg, args.app_id)
    release_id = api_post(token, "submit-audit", body, {"appId": app_id}, label="submit-audit")
    dump({"appId": app_id, "releaseId": release_id})


def cmd_audit_status(cfg: dict[str, str], args: argparse.Namespace) -> None:
    token = get_access_token(cfg)
    app_id = resolve_app_id(token, cfg, args.app_id)
    body = {"appId": [{"appId": app_id, "releaseId": args.release_id}]}
    dump(api_post(token, "get-audit-result", body, label="get-audit-result"))


def cmd_phased_info(cfg: dict[str, str], args: argparse.Namespace) -> None:
    token = get_access_token(cfg)
    app_id = resolve_app_id(token, cfg, args.app_id)
    dump(
        api_get(
            token,
            "get-phased-release-info",
            {"appId": app_id},
            label="get-phased-release-info",
        )
    )


def cmd_phased_update(cfg: dict[str, str], args: argparse.Namespace) -> None:
    body: dict[str, Any] = {"operationType": args.operation_type}
    if args.operation_type == 1:
        missing = [
            name
            for name, value in (
                ("--percentage", args.percentage),
                ("--start", args.start),
                ("--end", args.end),
                ("--note", args.note),
            )
            if not value
        ]
        if missing:
            print(
                "error: operationType 1 (更新分阶段发布计划) requires " + ", ".join(missing),
                file=sys.stderr,
            )
            sys.exit(2)
        body["phasedReleaseInfo"] = {
            "releasePercentage": args.percentage,
            "releaseStartDate": args.start,
            "releaseEndDate": args.end,
            "releaseNote": args.note,
        }
    if args.dry_run:
        dump(
            {
                "endpoint": "update-phased-release-info",
                "appId": dry_app_id(cfg, args.app_id),
                "body": body,
            }
        )
        return
    token = get_access_token(cfg)
    app_id = resolve_app_id(token, cfg, args.app_id)
    api_post(
        token,
        "update-phased-release-info",
        body,
        {"appId": app_id},
        label="update-phased-release-info",
    )
    dump({"appId": app_id, "operationType": args.operation_type, "ok": True})


def cmd_publish(cfg: dict[str, str], args: argparse.Namespace) -> None:
    apk = existing_file(args.apk, "apk")
    language_ids = args.language_id or [cfg["default_language"]]
    submit_body = build_submit_body(args)

    if args.dry_run:
        dump(
            {
                "appId": dry_app_id(cfg, args.app_id),
                "apk": str(apk),
                "apkSize": apk.stat().st_size,
                "apkSha256": file_sha256(apk),
                "bindLanguages": language_ids,
                "newFeature": args.new_feature,
                "submitBody": submit_body,
            }
        )
        return

    token = get_access_token(cfg)
    app_id = resolve_app_id(token, cfg, args.app_id)
    object_id = upload_file(token, app_id, apk, FILE_TYPE_APK, upload_via=args.upload_via)
    print(f"uploaded {apk.name} -> objectId {object_id}", file=sys.stderr)

    bindings = [{"objectId": object_id, "languageId": lang} for lang in language_ids]
    api_post(
        token,
        "update-file-info",
        {"bindingFileList": bindings},
        {"appId": app_id},
        label="update-file-info",
    )
    print(f"bound APK to {', '.join(language_ids)}", file=sys.stderr)

    if args.new_feature:
        info = merged_language_info(
            token, app_id, new_feature=args.new_feature, language_ids=language_ids
        )
        api_post(
            token,
            "update-language-info",
            {"languageInfoList": info, "setAll": 0},
            {"appId": app_id},
            label="update-language-info",
        )
        print("updated newFeature", file=sys.stderr)

    release_id = api_post(
        token, "submit-audit", submit_body, {"appId": app_id}, label="submit-audit"
    )
    dump({"appId": app_id, "objectId": object_id, "releaseId": release_id})


# --------------------------------------------------------------------------- cli


def add_release_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--force-update", type=int, default=0, choices=[0, 1])
    parser.add_argument(
        "--release-type",
        type=int,
        default=1,
        choices=[1, 2, 3],
        help="1=全网发布 2=指定时间发布 3=分阶段发布",
    )
    parser.add_argument("--release-time", help="yyyy-MM-dd'T'HH:mm:ssZZ, e.g. 2026-01-01T10:00:00+0800")
    parser.add_argument("--test-account")
    parser.add_argument("--test-password")
    parser.add_argument("--test-comment")
    parser.add_argument("--percentage", help="分阶段发布比例 0.00-100.00")
    parser.add_argument("--start", help="分阶段发布开始时间")
    parser.add_argument("--end", help="分阶段发布结束时间")
    parser.add_argument("--note", help="分阶段发布说明")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Honor AppMarket Publish-API client")
    parser.add_argument("--config", help="Credentials file path")
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="Check credentials, appId and local APK")
    doctor.add_argument("--apk", default=DEFAULT_APK)

    sub.add_parser("token", help="Fetch an access token and print its shape")

    appid = sub.add_parser("appid", help="Query appId by package name")
    appid.add_argument("--package-name")

    detail = sub.add_parser("detail", help="Query full app detail")
    detail.add_argument("--app-id")
    detail.add_argument(
        "--section",
        default="all",
        choices=["all", "basicInfo", "languageInfo", "publishInfo", "fileInfo", "releaseInfo"],
    )

    current = sub.add_parser("current-release", help="Query latest version and audit state")
    current.add_argument("--app-id")

    upload = sub.add_parser("upload", help="Upload one file, print its objectId")
    upload.add_argument("--app-id")
    upload.add_argument("--file", default=DEFAULT_APK)
    upload.add_argument("--file-type", type=int, default=FILE_TYPE_APK, help="100=APK, 1=icon, ...")
    upload.add_argument("--upload-via", default="api", choices=["api", "url"])
    upload.add_argument("--dry-run", action="store_true")

    bind = sub.add_parser("bind", help="Bind uploaded objectIds to the app")
    bind.add_argument("--app-id")
    bind.add_argument(
        "--object-id",
        action="append",
        required=True,
        metavar="objectId[:languageId[:order]]",
    )
    bind.add_argument("--dry-run", action="store_true")

    language = sub.add_parser(
        "language",
        help="更新多语言文案。默认只改 newFeature 并保留既有 appName/intro；"
             "首发时用 --intro(-file) 补上必填的应用介绍",
    )
    language.add_argument("--app-id")
    language.add_argument("--new-feature", help="新版本特性，≤500 字符")
    language.add_argument("--app-name", help="应用名称，≤15 汉字/30 其他字符")
    language.add_argument("--intro", help="应用介绍，≤8000 字符（首发必填）")
    language.add_argument("--intro-file", help="从文件读取应用介绍")
    language.add_argument("--brief-intro", help="一句话简介，≤80 字符")
    language.add_argument("--brief-intro-file", help="从文件读取一句话简介")
    language.add_argument("--language-id", action="append")
    language.add_argument("--set-all", type=int, default=0, choices=[0, 1])
    language.add_argument("--dry-run", action="store_true")

    info = sub.add_parser("app-info", help="更新应用基础信息（隐私政策、备案、分级等）")
    info.add_argument("--app-id")
    info.add_argument("--privacy-policy-url")
    info.add_argument("--web-url")
    info.add_argument("--customer-service-email")
    info.add_argument("--customer-service-tel")
    info.add_argument("--rating-id", help="年龄分级 id（取值以荣耀文档为准，勿猜）")
    info.add_argument("--release-country")
    info.add_argument("--app-registration-number", help="APP 备案号")
    info.add_argument("--app-registration-entity-name", help="备案主体名称")
    info.add_argument("--unified-social-credit-id", help="统一社会信用代码")
    info.add_argument("--publication_number", dest="publication_number")
    info.add_argument("--set", action="append", metavar="key=value", help="任意 basicInfo 字段")
    info.add_argument("--dry-run", action="store_true")

    submit = sub.add_parser("submit", help="Submit the app for audit")
    submit.add_argument("--app-id")
    submit.add_argument("--dry-run", action="store_true")
    add_release_args(submit)

    audit = sub.add_parser("audit-status", help="Query audit result for a releaseId")
    audit.add_argument("--app-id")
    audit.add_argument("--release-id", required=True)

    phased_info = sub.add_parser("phased-info", help="Query phased release state")
    phased_info.add_argument("--app-id")

    phased = sub.add_parser("phased-update", help="Adjust or end a phased release")
    phased.add_argument("--app-id")
    phased.add_argument(
        "--operation-type",
        type=int,
        required=True,
        choices=[0, 1, 3, 4, 5],
        help="3=暂停 0=重启 5=取消 4=提前全网发布 1=更新计划",
    )
    phased.add_argument("--percentage")
    phased.add_argument("--start")
    phased.add_argument("--end")
    phased.add_argument("--note")
    phased.add_argument("--dry-run", action="store_true")

    publish = sub.add_parser(
        "publish", help="Upload APK, bind it, update newFeature and submit for audit"
    )
    publish.add_argument("--app-id")
    publish.add_argument("--apk", default=DEFAULT_APK)
    publish.add_argument("--new-feature")
    publish.add_argument("--language-id", action="append")
    publish.add_argument("--upload-via", default="api", choices=["api", "url"])
    publish.add_argument("--dry-run", action="store_true")
    add_release_args(publish)

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
        "appid": cmd_appid,
        "detail": cmd_detail,
        "current-release": cmd_current_release,
        "upload": cmd_upload,
        "bind": cmd_bind,
        "language": cmd_language,
        "app-info": cmd_app_info,
        "submit": cmd_submit,
        "audit-status": cmd_audit_status,
        "phased-info": cmd_phased_info,
        "phased-update": cmd_phased_update,
        "publish": cmd_publish,
    }
    commands[args.command](cfg, args)


if __name__ == "__main__":
    main()
