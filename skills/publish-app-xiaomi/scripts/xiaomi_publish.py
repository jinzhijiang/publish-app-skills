#!/usr/bin/env python3
"""Xiaomi App Store automatic publisher."""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

API_BASE = "https://api.developer.xiaomi.com/devupload"
DEFAULT_APK = "build/app/outputs/channels/xiaomi-app-release.apk"
DEFAULT_PKG = ""  # 必填，由 <项目>/xiaomi.env 提供

SKILL_DIR = Path(__file__).resolve().parents[1]
CONFIG_ENV = SKILL_DIR / "config.env"


def project_name() -> str:
    """Project identity for per-project credential isolation.

    Priority: $XIAOMI_PROJECT > git root dir name (from cwd) > cwd name.
    Mirrors the countly-data-analysis convention so one machine can hold
    credentials for many apps without them silently crossing over.
    """
    override = os.environ.get("XIAOMI_PROJECT")
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

USER_CONFIG_ENV = Path.home() / ".config" / "ai-ignore-config" / project_name() / "xiaomi.env"


def json_compact(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def md5_text(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def file_md5(path: Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


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
        "user_name": os.environ.get("XIAOMI_USER_NAME", ""),
        "private_key": os.environ.get("XIAOMI_PRIVATE_KEY", ""),
        "public_cert_path": os.environ.get("XIAOMI_PUBLIC_CERT_PATH", ""),
        "package_name": os.environ.get("XIAOMI_PACKAGE_NAME", DEFAULT_PKG),
        "app_name": os.environ.get("XIAOMI_APP_NAME", ""),
        "publisher_name": os.environ.get("XIAOMI_PUBLISHER_NAME", ""),
        "category": os.environ.get("XIAOMI_CATEGORY", ""),
        "keywords": os.environ.get("XIAOMI_KEYWORDS", ""),
        "privacy_url": os.environ.get("XIAOMI_PRIVACY_URL", ""),
        "brief": os.environ.get("XIAOMI_BRIEF", ""),
    }
    if require_auth:
        missing = [
            name
            for name in ("user_name", "private_key", "public_cert_path", "package_name")
            if not cfg[name]
        ]
        if missing:
            names = {
                "user_name": "XIAOMI_USER_NAME",
                "private_key": "XIAOMI_PRIVATE_KEY",
                "public_cert_path": "XIAOMI_PUBLIC_CERT_PATH",
                "package_name": "XIAOMI_PACKAGE_NAME",
            }
            print(
                "error: missing credentials ("
                + ", ".join(names[name] for name in missing)
                + ").\n"
                f"  Recommended: cp {SKILL_DIR / 'config.example.env'} {USER_CONFIG_ENV}\n"
                f"  Then edit {USER_CONFIG_ENV}. Loaded config: {loaded or 'none'}",
                file=sys.stderr,
            )
            sys.exit(2)
    return cfg


def run_openssl(args: list[str], *, input_bytes: bytes | None = None) -> bytes:
    try:
        proc = subprocess.run(
            ["openssl", *args],
            input=input_bytes,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except FileNotFoundError:
        print("error: openssl command not found", file=sys.stderr)
        sys.exit(2)
    if proc.returncode != 0:
        print(
            "error: openssl failed: " + proc.stderr.decode("utf-8", errors="replace"),
            file=sys.stderr,
        )
        sys.exit(1)
    return proc.stdout


def public_key_from_cert(cert_path: Path, tmpdir: Path) -> tuple[Path, int]:
    if not cert_path.is_file():
        print(f"error: public certificate not found: {cert_path}", file=sys.stderr)
        sys.exit(2)
    pub_path = tmpdir / "xiaomi_public_key.pem"
    proc = subprocess.run(
        ["openssl", "x509", "-in", str(cert_path), "-pubkey", "-noout"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode == 0 and proc.stdout.strip():
        pub_path.write_bytes(proc.stdout)
    else:
        # Some consoles export a PEM public key instead of an X.509 certificate.
        pub_path.write_bytes(cert_path.read_bytes())

    text = run_openssl(["rsa", "-pubin", "-in", str(pub_path), "-text", "-noout"])
    first_line = text.decode("utf-8", errors="replace").splitlines()[0]
    if "(" not in first_line or " bit" not in first_line:
        print(f"error: cannot determine RSA key size from {pub_path}", file=sys.stderr)
        sys.exit(1)
    bits = int(first_line.split("(")[1].split(" bit")[0])
    return pub_path, bits // 8


def encrypt_by_public_key(plain_text: str, cert_path: Path) -> str:
    data = plain_text.encode("utf-8")
    with tempfile.TemporaryDirectory() as d:
        tmpdir = Path(d)
        pub_path, key_bytes = public_key_from_cert(cert_path, tmpdir)
        chunk_size = key_bytes - 11
        encrypted = bytearray()
        for idx in range(0, len(data), chunk_size):
            chunk_path = tmpdir / f"chunk-{idx}.bin"
            chunk_path.write_bytes(data[idx : idx + chunk_size])
            encrypted.extend(
                run_openssl(
                    [
                        "pkeyutl",
                        "-encrypt",
                        "-pubin",
                        "-inkey",
                        str(pub_path),
                        "-pkeyopt",
                        "rsa_padding_mode:pkcs1",
                        "-in",
                        str(chunk_path),
                    ]
                )
            )
    return encrypted.hex()


def build_sig(private_key: str, cert_path: Path, request_data_text: str, files: dict[str, Path]) -> tuple[str, str]:
    sig_items = [{"name": "RequestData", "hash": md5_text(request_data_text)}]
    for name, path in files.items():
        sig_items.append({"name": name, "hash": file_md5(path)})
    sig_json = {"sig": sig_items, "password": private_key}
    sig_text = json_compact(sig_json)
    return encrypt_by_public_key(sig_text, cert_path), sig_text


def encode_multipart(fields: dict[str, str], files: dict[str, Path]) -> tuple[bytes, str]:
    boundary = "----xiaomi-publish-" + uuid.uuid4().hex
    body = bytearray()

    def add_line(value: str | bytes = b"") -> None:
        if isinstance(value, str):
            value = value.encode("utf-8")
        body.extend(value + b"\r\n")

    for name, value in fields.items():
        add_line(f"--{boundary}")
        add_line(f'Content-Disposition: form-data; name="{name}"')
        add_line()
        add_line(value)

    for name, path in files.items():
        mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        add_line(f"--{boundary}")
        add_line(
            f'Content-Disposition: form-data; name="{name}"; filename="{path.name}"'
        )
        add_line(f"Content-Type: {mime_type}")
        add_line()
        body.extend(path.read_bytes())
        add_line()

    add_line(f"--{boundary}--")
    return bytes(body), f"multipart/form-data; boundary={boundary}"


def post_multipart(route: str, fields: dict[str, str], files: dict[str, Path], *, timeout: int = 300) -> str:
    body, content_type = encode_multipart(fields, files)
    req = urllib.request.Request(
        API_BASE + route,
        data=body,
        method="POST",
        headers={"Content-Type": content_type, "Content-Length": str(len(body))},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        print(f"error: HTTP {e.code}: {raw}", file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"error: request failed: {e.reason}", file=sys.stderr)
        sys.exit(1)


def print_response(raw: str) -> None:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        print(raw)
        return
    print(json.dumps(data, ensure_ascii=False, indent=2))
    if isinstance(data, dict) and data.get("result", 0) != 0:
        sys.exit(1)


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


def cmd_doctor(cfg: dict[str, str], args: argparse.Namespace) -> None:
    """Offline-first credential/artifact self-check. Reports presence, never values."""
    cert = Path(cfg["public_cert_path"]).expanduser() if cfg["public_cert_path"] else None
    apk = Path(args.apk).expanduser()
    openssl = shutil.which("openssl")
    report: dict[str, Any] = {
        "project": project_name(),
        "configPath": str(resolve_config_path(args.config) or "none"),
        "hasUserName": bool(cfg["user_name"]),
        "hasPrivateKey": bool(cfg["private_key"]),
        "publicCertPath": cfg["public_cert_path"] or "",
        "publicCertExists": bool(cert and cert.is_file()),
        "packageName": cfg["package_name"],
        "apkPath": args.apk,
        "apkExists": apk.is_file(),
        "versionCodeFromPubspec": version_code_from_pubspec(),
        "opensslAvailable": bool(openssl),
    }
    missing = [
        name
        for name, key in (
            ("XIAOMI_USER_NAME", "user_name"),
            ("XIAOMI_PRIVATE_KEY", "private_key"),
            ("XIAOMI_PUBLIC_CERT_PATH", "public_cert_path"),
            ("XIAOMI_PACKAGE_NAME", "package_name"),
        )
        if not cfg[key]
    ]
    report["missingCredentials"] = missing
    if missing or not report["publicCertExists"] or not openssl:
        report["queryOk"] = False
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return
    # Credentials look complete: prove them against the live read-only endpoint.
    try:
        request_text = json_compact(
            {"packageName": cfg["package_name"], "userName": cfg["user_name"]}
        )
        sig, _ = build_sig(cfg["private_key"], cert, request_text, {})
        raw = post_multipart("/dev/query", {"RequestData": request_text, "SIG": sig}, {}, timeout=60)
        data = json.loads(raw)
        report["queryOk"] = data.get("result") == 0
        report["queryResult"] = data.get("result")
        report["queryMessage"] = data.get("message")
        # -7 = package name taken by another developer; anything non-0 blocks publishing.
        if isinstance(data.get("data"), dict):
            report["onlineVersionCode"] = data["data"].get("versionCode")
            report["onlineVersionName"] = data["data"].get("versionName")
    except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as exc:
        report["queryOk"] = False
        report["queryError"] = f"{type(exc).__name__}: {exc}"
    print(json.dumps(report, ensure_ascii=False, indent=2))


def redact_sig(sig_text: str) -> dict[str, Any]:
    """SIG 明文里的 `password` 就是 XIAOMI_PRIVATE_KEY。

    --dry-run 的目的是核对 RequestData / 文件 MD5 / 签名结构，不需要看私钥本身；
    而 dry-run 的输出经常被贴进工单、日志或 AI 对话，泄漏一次就得重置私钥
    （重置会让旧私钥立即失效，正在跑的发版脚本一并挂掉）。所以这里只回显长度。
    """
    data = json.loads(sig_text)
    if isinstance(data, dict) and data.get("password"):
        data["password"] = f"<redacted: {len(data['password'])} chars>"
    return data


def cmd_category(cfg: dict[str, str], args: argparse.Namespace) -> None:
    raw = post_multipart("/dev/category", {}, {}, timeout=60)
    print_response(raw)


def cmd_query(cfg: dict[str, str], args: argparse.Namespace) -> None:
    package_name = args.package_name or cfg["package_name"]
    request_data = {"packageName": package_name, "userName": cfg["user_name"]}
    request_text = json_compact(request_data)
    sig, sig_text = build_sig(
        cfg["private_key"],
        Path(cfg["public_cert_path"]).expanduser(),
        request_text,
        {},
    )
    if args.dry_run:
        print(json.dumps({"RequestData": request_data, "SIG_plain": redact_sig(sig_text)}, ensure_ascii=False, indent=2))
        return
    raw = post_multipart("/dev/query", {"RequestData": request_text, "SIG": sig}, {}, timeout=60)
    print_response(raw)


def load_json_arg(value: str | None, label: str) -> dict[str, Any]:
    if not value:
        return {}
    path = Path(value).expanduser()
    raw = path.read_text(encoding="utf-8") if path.is_file() else value
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"error: invalid {label} JSON: {e}", file=sys.stderr)
        sys.exit(2)
    if not isinstance(data, dict):
        print(f"error: {label} must be a JSON object", file=sys.stderr)
        sys.exit(2)
    return data


def existing_file(path_value: str | None, label: str) -> Path | None:
    if not path_value:
        return None
    path = Path(path_value).expanduser()
    if not path.is_file():
        print(f"error: {label} not found: {path}", file=sys.stderr)
        sys.exit(2)
    return path


def add_optional_file(files: dict[str, Path], name: str, path_value: str | None) -> None:
    path = existing_file(path_value, name)
    if path is not None:
        files[name] = path


def build_app_info(cfg: dict[str, str], args: argparse.Namespace) -> dict[str, Any]:
    app_info = load_json_arg(args.app_info_json, "app-info")
    defaults: dict[str, Any] = {
        "packageName": args.package_name or cfg["package_name"],
    }
    optional = {
        "appName": args.app_name or cfg["app_name"],
        "publisherName": args.publisher_name or cfg["publisher_name"],
        "category": args.category or cfg["category"],
        "keyWords": args.keywords or cfg["keywords"],
        "brief": args.brief or cfg["brief"],
        "privacyUrl": args.privacy_url or cfg["privacy_url"],
        "updateDesc": args.update_desc,
        "versionName": args.version_name,
        "desc": args.desc,
        "web": args.web,
        "testAccount": args.test_account,
        "onlineTime": args.online_time,
        "suitableType": args.suitable_type,
    }
    for key, value in optional.items():
        if value not in (None, ""):
            defaults[key] = int(value) if key in {"category", "onlineTime", "suitableType"} else value
    defaults.update(app_info)
    return defaults


def cmd_push(cfg: dict[str, str], args: argparse.Namespace) -> None:
    app_info = build_app_info(cfg, args)
    request_data = {
        "userName": cfg["user_name"],
        "appInfo": json_compact(app_info),
        "synchroType": args.synchro_type,
    }
    request_text = json_compact(request_data)

    files: dict[str, Path] = {}
    add_optional_file(files, "apk", args.apk)
    add_optional_file(files, "secondApk", args.second_apk)
    add_optional_file(files, "icon", args.icon)
    for index, item in enumerate(args.screenshot or [], start=1):
        add_optional_file(files, f"screenshot_{index}", item)
    for index, item in enumerate(args.pad_screenshot or [], start=1):
        add_optional_file(files, f"screenshot_pad_{index}", item)
    for item in args.file or []:
        if "=" not in item:
            print(f"error: --file must be name=path, got {item}", file=sys.stderr)
            sys.exit(2)
        name, _, value = item.partition("=")
        add_optional_file(files, name, value)

    sig, sig_text = build_sig(
        cfg["private_key"],
        Path(cfg["public_cert_path"]).expanduser(),
        request_text,
        files,
    )
    if args.dry_run:
        print(
            json.dumps(
                {
                    "endpoint": "/dev/push",
                    "RequestData": request_data,
                    "SIG_plain": redact_sig(sig_text),
                    "files": {name: str(path) for name, path in files.items()},
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    raw = post_multipart("/dev/push", {"RequestData": request_text, "SIG": sig}, files)
    print_response(raw)


def cmd_push_channel_apk(cfg: dict[str, str], args: argparse.Namespace) -> None:
    channel_apk = existing_file(args.channel_apk, "channelApk")
    request_data = {"userName": cfg["user_name"], "apkChannel": args.apk_channel}
    request_text = json_compact(request_data)
    files = {"channelApk": channel_apk}
    sig, sig_text = build_sig(
        cfg["private_key"],
        Path(cfg["public_cert_path"]).expanduser(),
        request_text,
        files,
    )
    if args.dry_run:
        print(
            json.dumps(
                {
                    "endpoint": "/dev/pushChannelApk",
                    "RequestData": request_data,
                    "SIG_plain": redact_sig(sig_text),
                    "files": {"channelApk": str(channel_apk)},
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    raw = post_multipart(
        "/dev/pushChannelApk",
        {"RequestData": request_text, "SIG": sig},
        files,
    )
    print_response(raw)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Xiaomi App Store automatic publisher")
    parser.add_argument("--config", help="Credentials file path")
    parser.add_argument("--dry-run", action="store_true", help="Print payload without submitting")
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="检查凭据、证书、产物与线上版本")
    doctor.add_argument("--apk", default=DEFAULT_APK)

    sub.add_parser("category", help="Query Xiaomi app categories")

    query = sub.add_parser("query", help="Query package info")
    query.add_argument("--package-name")
    query.add_argument("--dry-run", action="store_true", help="Print payload without submitting")

    push = sub.add_parser("push", help="Submit app create/update/info change")
    push.add_argument("--dry-run", action="store_true", help="Print payload without submitting")
    push.add_argument("--synchro-type", type=int, default=1, choices=[0, 1, 2])
    push.add_argument("--apk", default=DEFAULT_APK)
    push.add_argument("--second-apk")
    push.add_argument("--icon")
    push.add_argument("--screenshot", action="append", help="Phone screenshot; repeat in display order")
    push.add_argument("--pad-screenshot", action="append", help="Pad screenshot; repeat in display order")
    push.add_argument("--file", action="append", help="Extra multipart file as field=path")
    push.add_argument("--app-info-json", help="JSON object string or path for appInfo overrides")
    push.add_argument("--package-name")
    push.add_argument("--app-name")
    push.add_argument("--publisher-name")
    push.add_argument("--category")
    push.add_argument("--keywords")
    push.add_argument("--version-name")
    push.add_argument("--desc")
    push.add_argument("--web")
    push.add_argument("--update-desc")
    push.add_argument("--brief")
    push.add_argument("--privacy-url")
    push.add_argument("--test-account", help="Structured testAccount JSON string")
    push.add_argument("--online-time")
    push.add_argument("--suitable-type")

    channel = sub.add_parser("push-channel-apk", help="Submit Xiaomi channel APK")
    channel.add_argument("--dry-run", action="store_true", help="Print payload without submitting")
    channel.add_argument("--apk-channel", default="xiaomi")
    channel.add_argument("--channel-apk", default=DEFAULT_APK)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.command in {"category", "doctor"}:
        cfg = get_config(Path(args.config).expanduser() if args.config else None, require_auth=False)
    else:
        cfg = get_config(Path(args.config).expanduser() if args.config else None, require_auth=True)
    if args.command not in {"category", "doctor"} and shutil.which("openssl") is None:
        print("error: openssl is required for Xiaomi RSA signing", file=sys.stderr)
        sys.exit(2)
    commands = {
        "category": cmd_category,
        "doctor": cmd_doctor,
        "query": cmd_query,
        "push": cmd_push,
        "push-channel-apk": cmd_push_channel_apk,
    }
    commands[args.command](cfg, args)


if __name__ == "__main__":
    main()
