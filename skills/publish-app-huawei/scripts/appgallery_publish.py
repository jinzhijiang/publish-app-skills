#!/usr/bin/env python3
"""Huawei AppGallery Connect publisher for Android and HarmonyOS builds.

Generic across projects: credentials resolve per project by the git root
directory name -> ~/.config/ai-ignore-config/<project>/appgallery.env.
Run from inside the target project repo, or override with --config /
HUAWEI_PROJECT.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import time
import uuid
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_DOMAIN = "connect-api.cloud.huawei.com"
DEFAULT_LANG = "zh-CN"
# Huawei unified service-account token endpoint (JWT client_assertion flow).
SA_TOKEN_URL = "https://oauth-login.cloud.huawei.com/oauth2/v3/token"

SKILL_DIR = Path(__file__).resolve().parents[1]
CONFIG_ENV = SKILL_DIR / "config.env"


def project_name() -> str:
    """Project identity for per-project credential isolation.

    Priority: $HUAWEI_PROJECT > git root dir name (from cwd) > cwd name.
    Mirrors the countly-data-analysis convention so one machine can hold
    credentials for many apps without them silently crossing over.
    """
    override = os.environ.get("HUAWEI_PROJECT")
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


USER_CONFIG_ENV = Path.home() / ".config" / "ai-ignore-config" / project_name() / "appgallery.env"

PLATFORMS = {
    "android": {
        "label": "Android",
        "app_id_env": "HUAWEI_ANDROID_APP_ID",
        "package_env": "HUAWEI_ANDROID_PACKAGE_NAME",
        "package_default": "",
        "package_type_env": "HUAWEI_ANDROID_PACKAGE_TYPE",
        "package_type_default": "1",
        "file_env": "HUAWEI_ANDROID_FILE",
        "file_default": "build/app/outputs/channels/huawei-app-release.apk",
        "file_type_env": "HUAWEI_ANDROID_FILE_TYPE",
        "file_type_default": "5",
        "suffixes": {"apk", "aab"},
    },
    "ohos": {
        "label": "HarmonyOS",
        "app_id_env": "HUAWEI_OHOS_APP_ID",
        "package_env": "HUAWEI_OHOS_PACKAGE_NAME",
        "package_default": "",
        "package_type_env": "HUAWEI_OHOS_PACKAGE_TYPE",
        "package_type_default": "7",
        "file_env": "HUAWEI_OHOS_FILE",
        "file_default": "build/ohos/app/ohos-release-signed.app",
        "file_type_env": "HUAWEI_OHOS_FILE_TYPE",
        "file_type_default": "5",
        "suffixes": {"hap", "app"},
    },
}


class AppGalleryError(Exception):
    """Raised for expected AppGallery API failures."""


def print_json(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def fail(message: str, code: int = 1) -> None:
    print(f"error: {message}", file=sys.stderr)
    sys.exit(code)


def redact(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "***"
    return f"{value[:4]}...{value[-4:]}"


def resolve_config_path(explicit: str | None = None) -> Path | None:
    if explicit:
        path = Path(explicit).expanduser()
        return path if path.is_file() else None
    for path in (USER_CONFIG_ENV, CONFIG_ENV):
        if path.is_file():
            return path
    return None


def load_config_env(explicit: str | None = None) -> Path | None:
    path = resolve_config_path(explicit)
    if path is None:
        return None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value
    return path


def config_hint() -> str:
    return (
        "Recommended setup:\n"
        f"  mkdir -p {USER_CONFIG_ENV.parent}\n"
        f"  cp {SKILL_DIR / 'config.example.env'} {USER_CONFIG_ENV}\n"
        f"  edit {USER_CONFIG_ENV} locally; do not paste secrets into chat"
    )


def resolve_key_file() -> tuple[str, str]:
    """Return ``(key_file_path, source_env)`` for the service account key.

    A Huawei service account is created at the developer-account level and can
    publish every app in the account, so a single ``HUAWEI_SERVICE_ACCOUNT_KEY``
    covers both Android and HarmonyOS — only the appId differs per platform.
    """
    return os.environ.get("HUAWEI_SERVICE_ACCOUNT_KEY", ""), "HUAWEI_SERVICE_ACCOUNT_KEY"


def load_service_account(path: Path) -> dict[str, Any]:
    """Parse a Huawei AGC service-account key file (JSON).

    Exported field names vary a little, so each value is looked up across a few
    known aliases. Returns the resolved fields plus the raw top-level key names
    (``_fields``) for diagnostics — never the private key value.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AppGalleryError(f"cannot read service account key {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise AppGalleryError(f"service account key {path} is not a JSON object")

    def pick(*names: str) -> tuple[str, str]:
        for name in names:
            value = data.get(name)
            if value:
                return str(value), name
        return "", ""

    iss, iss_src = pick("sub_account", "client_id", "iss", "sub")
    key_id, kid_src = pick("key_id", "keyId", "kid")
    private_key, _ = pick("private_key", "privateKey", "key")
    client_id, cid_src = pick("client_id", "app_id", "sub_account")
    token_uri, _ = pick("token_uri", "token_url")
    return {
        "iss": iss,
        "key_id": key_id,
        "private_key": private_key,
        "client_id": client_id,
        "token_uri": token_uri,
        "project_id": str(data.get("project_id") or ""),
        "_fields": sorted(data.keys()),
        "_sources": {"iss": iss_src, "key_id": kid_src, "client_id": cid_src},
    }


def build_jwt(sa: dict[str, Any], audience: str) -> str:
    """Build a PS256 (SHA256withRSA/PSS) JWT for the Huawei token endpoint."""
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    missing = [k for k in ("iss", "private_key") if not sa.get(k)]
    if missing:
        raise AppGalleryError(
            "service account key missing field(s): "
            + ", ".join(missing)
            + f"; found keys: {sa.get('_fields')}"
        )

    def b64(raw: bytes) -> str:
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

    header: dict[str, str] = {"alg": "PS256", "typ": "JWT"}
    if sa.get("key_id"):
        header["kid"] = sa["key_id"]
    now = int(time.time())
    payload = {"iss": sa["iss"], "aud": audience, "iat": now, "exp": now + 3600}
    signing_input = (
        b64(json.dumps(header, separators=(",", ":")).encode("utf-8"))
        + "."
        + b64(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    ).encode("ascii")

    try:
        key = serialization.load_pem_private_key(
            sa["private_key"].encode("utf-8"), password=None
        )
    except Exception as exc:  # noqa: BLE001 - surface any key parse failure clearly
        raise AppGalleryError(f"cannot load service account private_key: {exc}") from exc
    # SHA256withRSA/PSS: MGF1(SHA-256), salt length = digest length (32).
    signature = key.sign(
        signing_input,
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=hashes.SHA256().digest_size),
        hashes.SHA256(),
    )
    return f"{signing_input.decode('ascii')}.{b64(signature)}"


def load_config(args: argparse.Namespace, *, allow_missing: bool = False) -> dict[str, str]:
    loaded_path = load_config_env(getattr(args, "config", None))
    domain = getattr(args, "domain", None) or os.environ.get(
        "HUAWEI_CONNECT_API_DOMAIN", DEFAULT_DOMAIN
    )
    platform = getattr(args, "platform", None)
    if platform == "all":
        platform = None
    key_file, key_source = resolve_key_file()
    cfg: dict[str, Any] = {
        "domain": domain.strip().removeprefix("https://").removeprefix("http://").rstrip("/"),
        "key_file": key_file,
        "key_file_source": key_source,
        "sa_token_url": os.environ.get("HUAWEI_SA_TOKEN_URL", SA_TOKEN_URL),
        "client_id": "",  # set from the service account once a token is obtained
        "platform_scope": platform or "",
        "default_lang": os.environ.get("HUAWEI_DEFAULT_LANG", DEFAULT_LANG),
        "loaded_config": str(loaded_path) if loaded_path else "",
    }
    if not key_file and not allow_missing:
        fail(
            f"missing service account key: set {key_source} to the downloaded AGC "
            "service-account JSON key file path\n"
            f"Loaded config: {loaded_path or 'none'}\n" + config_hint(),
            code=2,
        )
    return cfg


def platform_config(platform: str, args: argparse.Namespace | None = None) -> dict[str, Any]:
    spec = PLATFORMS[platform]
    app_id = os.environ.get(spec["app_id_env"], "")
    package_name = os.environ.get(spec["package_env"], spec["package_default"])
    package_type = os.environ.get(spec["package_type_env"], spec["package_type_default"])
    file_path = os.environ.get(spec["file_env"], spec["file_default"])
    file_type = os.environ.get(spec["file_type_env"], spec["file_type_default"])

    if args is not None:
        if getattr(args, "app_id", None):
            app_id = args.app_id
        if getattr(args, "package_name", None):
            package_name = args.package_name
        if getattr(args, "package_types", None):
            package_type = args.package_types
        if getattr(args, "file", None):
            file_path = args.file
        if getattr(args, "file_type", None):
            file_type = str(args.file_type)

    return {
        "platform": platform,
        "label": spec["label"],
        "app_id": app_id,
        "package_name": package_name,
        "package_types": package_type,
        "file": file_path,
        "file_type": str(file_type),
        "suffixes": spec["suffixes"],
    }


def require_app_id(pcfg: dict[str, Any]) -> str:
    app_id = pcfg["app_id"]
    if not app_id:
        platform = pcfg["platform"]
        env_name = PLATFORMS[platform]["app_id_env"]
        fail(f"missing {env_name}; run appid-list or fill config.env", code=2)
    return app_id


def api_url(cfg: dict[str, str], path: str, query: dict[str, Any] | None = None) -> str:
    encoded = ""
    if query:
        cleaned = {k: v for k, v in query.items() if v not in (None, "")}
        encoded = "?" + urllib.parse.urlencode(cleaned)
    return f"https://{cfg['domain']}/api{path}{encoded}"


def parse_json(raw: bytes, context: str) -> dict[str, Any]:
    text = raw.decode("utf-8", errors="replace")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AppGalleryError(f"{context}: invalid JSON response: {text}") from exc
    if not isinstance(data, dict):
        raise AppGalleryError(f"{context}: unexpected response type: {text}")
    return data


def check_ret(data: dict[str, Any], context: str) -> dict[str, Any]:
    ret = data.get("ret")
    if isinstance(ret, dict):
        code = ret.get("code")
        if str(code) not in ("0", "None"):
            msg = ret.get("msg", "")
            raise AppGalleryError(f"{context} failed (ret.code={code}): {msg}")
    return data


def http_json(
    method: str,
    url: str,
    *,
    token: str | None = None,
    cfg: dict[str, str] | None = None,
    body: dict[str, Any] | None = None,
    timeout: int = 60,
    check_api_ret: bool = True,
) -> dict[str, Any]:
    headers = {"Accept": "application/json"}
    data = None
    if cfg and cfg.get("client_id"):
        headers["client_id"] = cfg["client_id"]
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            parsed = parse_json(response.read(), url)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise AppGalleryError(f"HTTP {exc.code} from {url}: {raw}") from exc
    except urllib.error.URLError as exc:
        raise AppGalleryError(f"request failed for {url}: {exc.reason}") from exc

    return check_ret(parsed, url) if check_api_ret else parsed


def obtain_token(cfg: dict[str, Any]) -> dict[str, Any]:
    key_file = cfg.get("key_file")
    if not key_file:
        raise AppGalleryError(
            f"missing service account key ({cfg.get('key_file_source')})"
        )
    sa = load_service_account(Path(key_file).expanduser())
    cfg["sa"] = sa
    # Service Account: the signed JWT itself is the bearer token — there is NO
    # separate token-exchange request, and no client_id header. `aud` is fixed to
    # the token_uri value from the key file.
    audience = sa.get("token_uri") or cfg["sa_token_url"]
    cfg["sa_token_url"] = audience
    jwt = build_jwt(sa, audience)
    return {"access_token": jwt, "expires_in": 3600, "token_type": "Bearer"}


def authed_get(
    cfg: dict[str, str],
    token: str,
    path: str,
    query: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return http_json("GET", api_url(cfg, path, query), token=token, cfg=cfg)


def authed_put(
    cfg: dict[str, str],
    token: str,
    path: str,
    query: dict[str, Any],
    body: dict[str, Any],
) -> dict[str, Any]:
    return http_json("PUT", api_url(cfg, path, query), token=token, cfg=cfg, body=body)


def authed_post(
    cfg: dict[str, str],
    token: str,
    path: str,
    query: dict[str, Any],
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return http_json("POST", api_url(cfg, path, query), token=token, cfg=cfg, body=body or {})


def file_suffix(path: Path) -> str:
    return path.suffix.lower().lstrip(".")


def validate_package_path(path: Path, pcfg: dict[str, Any], *, require_exists: bool = True) -> None:
    suffix = file_suffix(path)
    if suffix not in pcfg["suffixes"]:
        allowed = ", ".join(sorted(pcfg["suffixes"]))
        fail(f"{pcfg['label']} package must end with one of: {allowed}; got {path}")
    if require_exists and not path.is_file():
        fail(f"package file not found: {path}")


def read_notes(args: argparse.Namespace, cfg: dict[str, str]) -> tuple[str, str] | None:
    notes = getattr(args, "release_notes", None)
    notes_file = getattr(args, "release_notes_file", None)
    if notes_file:
        notes = Path(notes_file).expanduser().read_text(encoding="utf-8").strip()
    if not notes:
        return None
    lang = getattr(args, "lang", None) or cfg["default_lang"]
    return lang, notes.strip()


def multipart_form(
    fields: dict[str, str],
    file_field: str,
    file_path: Path,
) -> tuple[bytes, str]:
    boundary = f"----AppGalleryUpload{uuid.uuid4().hex}"
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode("utf-8"),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"),
                str(value).encode("utf-8"),
                b"\r\n",
            ]
        )
    chunks.extend(
        [
            f"--{boundary}\r\n".encode("utf-8"),
            (
                f'Content-Disposition: form-data; name="{file_field}"; '
                f'filename="{file_path.name}"\r\n'
            ).encode("utf-8"),
            b"Content-Type: application/octet-stream\r\n\r\n",
            file_path.read_bytes(),
            b"\r\n",
            f"--{boundary}--\r\n".encode("utf-8"),
        ]
    )
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def upload_obs(upload_info: dict[str, Any], file_path: Path, *, timeout: int = 600) -> str:
    url_info = upload_info.get("urlInfo") or {}
    upload_url = url_info.get("url")
    headers = url_info.get("headers") or {}
    object_id = url_info.get("objectId") or url_info.get("objectID")
    if not upload_url or not object_id:
        raise AppGalleryError(f"OBS upload response missing urlInfo.url/objectId: {upload_info}")
    if not isinstance(headers, dict):
        raise AppGalleryError(f"OBS upload response has invalid headers: {upload_info}")
    request = urllib.request.Request(
        upload_url,
        data=file_path.read_bytes(),
        method="PUT",
        headers={str(k): str(v) for k, v in headers.items()},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if response.status not in (200, 201, 204):
                raise AppGalleryError(f"OBS upload HTTP {response.status}")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise AppGalleryError(f"OBS upload HTTP {exc.code}: {raw}") from exc
    except urllib.error.URLError as exc:
        raise AppGalleryError(f"OBS upload failed: {exc.reason}") from exc
    return str(object_id)


def upload_legacy(upload_info: dict[str, Any], file_path: Path, *, timeout: int = 600) -> dict[str, Any]:
    upload_url = upload_info.get("uploadUrl")
    auth_code = upload_info.get("authCode")
    if not upload_url or not auth_code:
        raise AppGalleryError(f"legacy upload response missing uploadUrl/authCode: {upload_info}")
    body, content_type = multipart_form(
        {"authCode": str(auth_code), "fileCount": "1"},
        "file",
        file_path,
    )
    request = urllib.request.Request(
        str(upload_url),
        data=body,
        method="POST",
        headers={"Content-Type": content_type},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            parsed = parse_json(response.read(), str(upload_url))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise AppGalleryError(f"legacy upload HTTP {exc.code}: {raw}") from exc
    except urllib.error.URLError as exc:
        raise AppGalleryError(f"legacy upload failed: {exc.reason}") from exc

    file_infos = (
        parsed.get("result", {})
        .get("UploadFileRsp", {})
        .get("fileInfoList", [])
    )
    if not file_infos:
        raise AppGalleryError(f"legacy upload response missing fileInfoList: {parsed}")
    info = file_infos[0]
    file_dest_url = info.get("fileDestUrl") or info.get("fileDestUlr")
    if not file_dest_url:
        raise AppGalleryError(f"legacy upload response missing fileDestUrl: {parsed}")
    return {
        "fileDestUrl": file_dest_url,
        "size": info.get("size"),
        "raw": parsed,
    }


def upload_package(
    cfg: dict[str, str],
    token: str,
    pcfg: dict[str, Any],
    file_path: Path,
    upload_mode: str,
) -> dict[str, Any]:
    suffix = file_suffix(file_path)
    if upload_mode == "obs":
        info = authed_get(
            cfg,
            token,
            "/publish/v2/upload-url/for-obs",
            {
                "appId": require_app_id(pcfg),
                "fileName": file_path.name,
                "contentLength": str(file_path.stat().st_size),
                "suffix": suffix,
            },
        )
        file_dest_url = upload_obs(info, file_path)
        return {
            "mode": "obs",
            "fileName": file_path.name,
            "fileDestUrl": file_dest_url,
            "size": str(file_path.stat().st_size),
            "raw": info,
        }

    info = authed_get(
        cfg,
        token,
        "/publish/v2/upload-url",
        {
            "appId": require_app_id(pcfg),
            "suffix": suffix,
            "releaseType": "1",
        },
    )
    uploaded = upload_legacy(info, file_path)
    return {
        "mode": "legacy",
        "fileName": file_path.name,
        "fileDestUrl": uploaded["fileDestUrl"],
        "size": str(uploaded.get("size") or file_path.stat().st_size),
        "raw": uploaded["raw"],
    }


def attach_file(
    cfg: dict[str, str],
    token: str,
    pcfg: dict[str, Any],
    *,
    file_name: str,
    file_dest_url: str,
    size: str | None = None,
) -> dict[str, Any]:
    entry = {
        "fileName": file_name,
        "fileDestUrl": file_dest_url,
    }
    if size:
        entry["size"] = str(size)
    return authed_put(
        cfg,
        token,
        "/publish/v2/app-file-info",
        {"appId": require_app_id(pcfg)},
        {"fileType": int(pcfg["file_type"]), "files": [entry]},
    )


def update_release_notes(
    cfg: dict[str, str],
    token: str,
    pcfg: dict[str, Any],
    *,
    lang: str,
    notes: str,
) -> dict[str, Any]:
    return update_language_info(cfg, token, pcfg, lang=lang, fields={"newFeatures": notes})


def update_language_info(
    cfg: dict[str, str],
    token: str,
    pcfg: dict[str, Any],
    *,
    lang: str,
    fields: dict[str, str],
) -> dict[str, Any]:
    """PUT app-language-info with an arbitrary subset of the localized text fields.

    AppGallery treats this endpoint as a PARTIAL update: omitted keys keep their
    stored value, which is why `release-notes` can send `newFeatures` alone
    without wiping the icon and screenshots. `store-listing --merge-current`
    re-sends the sibling text fields anyway for callers who would rather not
    rely on that.
    """
    return authed_put(
        cfg,
        token,
        "/publish/v2/app-language-info",
        {"appId": require_app_id(pcfg)},
        {"lang": lang, **fields},
    )


def submit_release(
    cfg: dict[str, str],
    token: str,
    pcfg: dict[str, Any],
    args: argparse.Namespace,
) -> dict[str, Any]:
    query = {
        "appId": require_app_id(pcfg),
        "releaseTime": getattr(args, "release_time", None),
        "remark": getattr(args, "remark", None),
        "channelId": getattr(args, "channel_id", None),
        "releaseType": getattr(args, "release_type", None),
    }
    body = {
        "phasedReleaseStartTime": getattr(args, "phased_start", None),
        "phasedReleaseEndTime": getattr(args, "phased_end", None),
        "phasedReleasePercent": getattr(args, "phased_percent", None),
        "phasedReleaseDescription": getattr(args, "phased_description", None),
    }
    body = {k: v for k, v in body.items() if v not in (None, "")}
    return authed_post(cfg, token, "/publish/v2/app-submit", query, body)


def dry_run_request(command: str, cfg: dict[str, Any], pcfg: dict[str, Any], extra: dict[str, Any]) -> None:
    print_json(
        {
            "dryRun": True,
            "command": command,
            "domain": cfg["domain"],
            "keyFile": cfg.get("key_file") or None,
            "tokenUrl": cfg.get("sa_token_url"),
            "platform": pcfg["platform"],
            "appId": pcfg["app_id"] or "<missing>",
            "packageName": pcfg["package_name"],
            "packageTypes": pcfg["package_types"],
            **extra,
        }
    )


def cmd_doctor(args: argparse.Namespace) -> None:
    cfg = load_config(args, allow_missing=True)
    platforms = PLATFORMS.keys() if args.platform == "all" else [args.platform]
    checks = []
    for platform in platforms:
        pcfg = platform_config(platform, args)
        file_path = Path(pcfg["file"])
        suffix = file_suffix(file_path)
        checks.append(
            {
                "platform": platform,
                "label": pcfg["label"],
                "appIdConfigured": bool(pcfg["app_id"]),
                "packageName": pcfg["package_name"],
                "packageTypes": pcfg["package_types"],
                "defaultFile": str(file_path),
                "fileExists": file_path.is_file(),
                "suffix": suffix,
                "suffixAllowed": suffix in pcfg["suffixes"],
                "fileType": pcfg["file_type"],
            }
        )
    key_path, key_source = resolve_key_file()
    service_account: dict[str, Any] = {
        "keyFileEnv": key_source,
        "keyFileConfigured": bool(key_path),
        "keyFilePath": key_path or None,
    }
    if key_path:
        key_p = Path(key_path).expanduser()
        service_account["keyFileExists"] = key_p.is_file()
        if key_p.is_file():
            try:
                sa = load_service_account(key_p)
                service_account["keyFields"] = sa["_fields"]
                service_account["resolvedIssField"] = sa["_sources"]["iss"] or None
                service_account["resolvedKeyIdField"] = sa["_sources"]["key_id"] or None
                service_account["hasPrivateKey"] = bool(sa["private_key"])
                if sa.get("project_id"):
                    service_account["projectScopedWarning"] = (
                        "key file has a non-empty project_id → this is a PROJECT-level "
                        "service account; Connect API requires a DEVELOPER-level (开发者级) "
                        "one (empty project_id), otherwise every call returns HTTP 403"
                    )
            except AppGalleryError as exc:
                service_account["keyFileError"] = str(exc)
    print_json(
        {
            "configLoaded": cfg["loaded_config"] or None,
            "domain": cfg["domain"],
            "tokenUrl": cfg["sa_token_url"],
            "defaultLang": cfg["default_lang"],
            "serviceAccount": service_account,
            "platforms": checks,
            "hint": None if cfg["loaded_config"] else config_hint(),
        }
    )


def cmd_token(args: argparse.Namespace) -> None:
    cfg = load_config(args, allow_missing=args.dry_run)
    if args.dry_run:
        info: dict[str, Any] = {
            "dryRun": True,
            "tokenUrl": cfg["sa_token_url"],
            "keyFileEnv": cfg["key_file_source"],
            "keyFile": cfg["key_file"] or None,
        }
        key_file = cfg["key_file"]
        if key_file:
            key_p = Path(key_file).expanduser()
            if key_p.is_file():
                try:
                    sa = load_service_account(key_p)
                    info["keyFields"] = sa["_fields"]
                    info["iss"] = redact(sa["iss"])
                    info["keyId"] = redact(sa["key_id"])
                    info["hasPrivateKey"] = bool(sa["private_key"])
                except AppGalleryError as exc:
                    info["keyFileError"] = str(exc)
            else:
                info["keyFileExists"] = False
        print_json(info)
        return
    data = obtain_token(cfg)
    token = str(data["access_token"])
    print_json(
        {
            "clientId": redact(cfg.get("client_id", "")),
            "accessToken": token if args.show_token else redact(token),
            "expiresIn": data.get("expires_in"),
            "tokenType": data.get("token_type"),
            "shownFullToken": bool(args.show_token),
        }
    )


def cmd_appid_list(args: argparse.Namespace) -> None:
    cfg = load_config(args, allow_missing=args.dry_run)
    pcfg = platform_config(args.platform, args)
    query = {
        "packageName": pcfg["package_name"],
        "packageTypes": pcfg["package_types"],
    }
    if args.dry_run:
        dry_run_request(
            "appid-list",
            cfg,
            pcfg,
            {"method": "GET", "url": api_url(cfg, "/publish/v2/appid-list", query)},
        )
        return
    token = obtain_token(cfg)["access_token"]
    print_json(authed_get(cfg, token, "/publish/v2/appid-list", query))


def cmd_info(args: argparse.Namespace) -> None:
    cfg = load_config(args, allow_missing=args.dry_run)
    pcfg = platform_config(args.platform, args)
    query = {"appId": require_app_id(pcfg) if not args.dry_run else pcfg["app_id"]}
    if args.dry_run:
        dry_run_request(
            args.command,
            cfg,
            pcfg,
            {"method": "GET", "url": api_url(cfg, "/publish/v2/app-info", query)},
        )
        return
    token = obtain_token(cfg)["access_token"]
    print_json(authed_get(cfg, token, "/publish/v2/app-info", query))


def cmd_release_notes(args: argparse.Namespace) -> None:
    cfg = load_config(args, allow_missing=args.dry_run)
    pcfg = platform_config(args.platform, args)
    notes = read_notes(args, cfg)
    if not notes:
        fail("provide --release-notes or --release-notes-file", code=2)
    lang, text = notes
    if args.dry_run:
        dry_run_request(
            "release-notes",
            cfg,
            pcfg,
            {
                "method": "PUT",
                "path": "/api/publish/v2/app-language-info",
                "lang": lang,
                "newFeatures": text,
            },
        )
        return
    token = obtain_token(cfg)["access_token"]
    print_json(update_release_notes(cfg, token, pcfg, lang=lang, notes=text))


LISTING_TEXT_FIELDS = ("appName", "briefInfo", "appDesc", "newFeatures")


def read_text_arg(inline: str | None, file_path: str | None, label: str) -> str | None:
    if inline and file_path:
        fail(f"pass only one of --{label} / --{label}-file", code=2)
    if file_path:
        path = Path(file_path).expanduser()
        if not path.is_file():
            fail(f"{label} file not found: {path}", code=2)
        return path.read_text(encoding="utf-8").strip()
    return inline


def cmd_store_listing(args: argparse.Namespace) -> None:
    """Update the localized store listing (ASO copy), not just release notes."""
    cfg = load_config(args, allow_missing=args.dry_run)
    pcfg = platform_config(args.platform, args)
    lang = args.lang or cfg["default_lang"]

    fields: dict[str, str] = {}
    for key, inline, file_path in (
        ("appName", args.app_name, None),
        ("briefInfo", args.brief_info, args.brief_info_file),
        ("appDesc", args.app_desc, args.app_desc_file),
        ("newFeatures", args.release_notes, args.release_notes_file),
    ):
        value = read_text_arg(inline, file_path, key)
        if value:
            fields[key] = value
    if not fields:
        fail(
            "nothing to update: pass at least one of --app-name / --brief-info(-file) / "
            "--app-desc(-file) / --release-notes(-file)",
            code=2,
        )

    token = None
    if args.merge_current and not args.dry_run:
        token = obtain_token(cfg)["access_token"]
        current = authed_get(
            cfg, token, "/publish/v2/app-info", {"appId": require_app_id(pcfg)}
        )
        stored = next(
            (l for l in current.get("languages") or [] if l.get("lang") == lang), {}
        )
        merged = {k: stored[k] for k in LISTING_TEXT_FIELDS if stored.get(k)}
        merged.update(fields)
        fields = merged

    preview = {
        k: (f"{v[:60]}…({len(v)} chars)" if len(v) > 60 else v) for k, v in fields.items()
    }
    if args.dry_run:
        dry_run_request(
            "store-listing",
            cfg,
            pcfg,
            {
                "method": "PUT",
                "path": "/api/publish/v2/app-language-info",
                "lang": lang,
                "fields": preview,
            },
        )
        return
    if token is None:
        token = obtain_token(cfg)["access_token"]
    result = update_language_info(cfg, token, pcfg, lang=lang, fields=fields)
    print_json({"lang": lang, "sent": preview, "response": result})


def cmd_upload(args: argparse.Namespace) -> None:
    cfg = load_config(args, allow_missing=args.dry_run)
    pcfg = platform_config(args.platform, args)
    path = Path(pcfg["file"]).expanduser()
    validate_package_path(path, pcfg)
    if args.dry_run:
        dry_run_request(
            "upload",
            cfg,
            pcfg,
            {
                "uploadMode": args.upload_mode,
                "file": str(path),
                "fileDestUrl": "DRY_RUN_FILE_DEST_URL",
            },
        )
        return
    token = obtain_token(cfg)["access_token"]
    print_json(upload_package(cfg, token, pcfg, path, args.upload_mode))


def cmd_attach_file(args: argparse.Namespace) -> None:
    cfg = load_config(args, allow_missing=args.dry_run)
    pcfg = platform_config(args.platform, args)
    if args.dry_run:
        dry_run_request(
            "attach-file",
            cfg,
            pcfg,
            {
                "method": "PUT",
                "path": "/api/publish/v2/app-file-info",
                "fileName": args.file_name,
                "fileDestUrl": args.file_dest_url,
                "size": args.size,
            },
        )
        return
    token = obtain_token(cfg)["access_token"]
    print_json(
        attach_file(
            cfg,
            token,
            pcfg,
            file_name=args.file_name,
            file_dest_url=args.file_dest_url,
            size=args.size,
        )
    )


def cmd_submit(args: argparse.Namespace) -> None:
    cfg = load_config(args, allow_missing=args.dry_run)
    pcfg = platform_config(args.platform, args)
    if args.dry_run:
        dry_run_request(
            "submit",
            cfg,
            pcfg,
            {
                "method": "POST",
                "path": "/api/publish/v2/app-submit",
                "releaseType": args.release_type,
                "releaseTime": args.release_time,
                "channelId": args.channel_id,
                "remark": args.remark,
            },
        )
        return
    token = obtain_token(cfg)["access_token"]
    print_json(submit_release(cfg, token, pcfg, args))


def cmd_publish(args: argparse.Namespace) -> None:
    cfg = load_config(args, allow_missing=args.dry_run)
    pcfg = platform_config(args.platform, args)
    path = Path(pcfg["file"]).expanduser()
    validate_package_path(path, pcfg)
    notes = read_notes(args, cfg)
    if args.dry_run:
        dry_run_request(
            "publish",
            cfg,
            pcfg,
            {
                "steps": [
                    "obtain token",
                    "query app info",
                    f"upload package via {args.upload_mode}",
                    "attach file to draft",
                    "update release notes" if notes else "skip release notes",
                    "submit for review" if args.submit else "skip submit",
                ],
                "file": str(path),
                "releaseNotesLang": notes[0] if notes else None,
            },
        )
        return

    token = obtain_token(cfg)["access_token"]
    result: dict[str, Any] = {
        "platform": pcfg["platform"],
        "appId": require_app_id(pcfg),
        "info": authed_get(cfg, token, "/publish/v2/app-info", {"appId": pcfg["app_id"]}),
    }
    uploaded = upload_package(cfg, token, pcfg, path, args.upload_mode)
    result["upload"] = {
        "mode": uploaded["mode"],
        "fileName": uploaded["fileName"],
        "fileDestUrl": uploaded["fileDestUrl"],
        "size": uploaded["size"],
    }
    result["attachFile"] = attach_file(
        cfg,
        token,
        pcfg,
        file_name=uploaded["fileName"],
        file_dest_url=uploaded["fileDestUrl"],
        size=uploaded["size"],
    )
    if notes:
        lang, text = notes
        result["releaseNotes"] = update_release_notes(
            cfg,
            token,
            pcfg,
            lang=lang,
            notes=text,
        )
    else:
        result["releaseNotes"] = "skipped"
    result["submit"] = submit_release(cfg, token, pcfg, args) if args.submit else "skipped"
    print_json(result)


def add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", help="Path to appgallery.env/config.env")
    parser.add_argument("--domain", help=f"Connect API domain, default {DEFAULT_DOMAIN}")
    parser.add_argument("--dry-run", action="store_true", help="Print planned API calls only")


def add_platform(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--platform", choices=sorted(PLATFORMS), required=True)
    parser.add_argument("--app-id", help="Override platform appId from config")


def add_package_query(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--package-name", help="Override package/bundle name")
    parser.add_argument("--package-types", help="Override AppGallery packageTypes")


def add_file_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--file", help="Package file path")
    parser.add_argument("--file-type", help="AppGallery app-file-info fileType override")
    parser.add_argument(
        "--upload-mode",
        choices=("obs", "legacy"),
        default="obs",
        help="OBS direct upload by default; use legacy for multipart upload-url",
    )


def add_release_notes(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--release-notes", help="Release notes/newFeatures text")
    parser.add_argument("--release-notes-file", help="Read release notes from file")
    parser.add_argument("--lang", help=f"Listing language, default {DEFAULT_LANG}")


def add_submit_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--release-type", choices=("1", "3"), default="1")
    parser.add_argument("--release-time", help="Scheduled release time, e.g. 2026-06-10T10:00:00+0800")
    parser.add_argument("--remark", help="10-300 character release remark")
    parser.add_argument("--channel-id", help="AppGallery channelId")
    parser.add_argument("--phased-start", help="Phased release start time")
    parser.add_argument("--phased-end", help="Phased release end time")
    parser.add_argument("--phased-percent", help="Phased release percentage")
    parser.add_argument("--phased-description", help="Phased release description")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor = subparsers.add_parser("doctor", help="Check local config and package defaults")
    add_common(doctor)
    doctor.add_argument("--platform", choices=["all", *sorted(PLATFORMS)], default="all")
    doctor.set_defaults(func=cmd_doctor)

    token = subparsers.add_parser("token", help="Obtain access token")
    add_common(token)
    token.add_argument("--show-token", action="store_true", help="Print full token locally")
    token.set_defaults(func=cmd_token)

    appid = subparsers.add_parser("appid-list", help="Query appId by package name")
    add_common(appid)
    add_platform(appid)
    add_package_query(appid)
    appid.set_defaults(func=cmd_appid_list)

    info = subparsers.add_parser("info", help="Query app info")
    add_common(info)
    add_platform(info)
    info.set_defaults(func=cmd_info)

    status = subparsers.add_parser("status", help="Query app status via app-info")
    add_common(status)
    add_platform(status)
    status.set_defaults(func=cmd_info)

    listing = subparsers.add_parser(
        "store-listing",
        help="更新商店文案（应用名称/一句话简介/应用介绍/更新说明），用于 ASO",
    )
    add_common(listing)
    add_platform(listing)
    add_release_notes(listing)
    listing.add_argument("--app-name", help="应用名称 appName（改名会重新走审核，慎用）")
    listing.add_argument("--brief-info", help="一句话简介 briefInfo（华为上限 80 字）")
    listing.add_argument("--brief-info-file", help="从文件读取一句话简介")
    listing.add_argument("--app-desc", help="应用介绍 appDesc（华为上限 8000 字）")
    listing.add_argument("--app-desc-file", help="从文件读取应用介绍")
    listing.add_argument(
        "--merge-current",
        action="store_true",
        help="先读回线上文案再合并提交，不依赖服务端的增量更新语义",
    )
    listing.set_defaults(func=cmd_store_listing)

    release_notes = subparsers.add_parser("release-notes", help="Update release notes")
    add_common(release_notes)
    add_platform(release_notes)
    add_release_notes(release_notes)
    release_notes.set_defaults(func=cmd_release_notes)

    upload = subparsers.add_parser("upload", help="Upload package and print fileDestUrl")
    add_common(upload)
    add_platform(upload)
    add_file_options(upload)
    upload.set_defaults(func=cmd_upload)

    attach = subparsers.add_parser("attach-file", help="Attach uploaded package to app draft")
    add_common(attach)
    add_platform(attach)
    attach.add_argument("--file-name", required=True)
    attach.add_argument("--file-dest-url", required=True)
    attach.add_argument("--size")
    attach.add_argument("--file-type", help="AppGallery app-file-info fileType override")
    attach.set_defaults(func=cmd_attach_file)

    submit = subparsers.add_parser("submit", help="Submit app for review")
    add_common(submit)
    add_platform(submit)
    add_submit_options(submit)
    submit.set_defaults(func=cmd_submit)

    publish = subparsers.add_parser("publish", help="Upload, attach, update notes, optionally submit")
    add_common(publish)
    add_platform(publish)
    add_file_options(publish)
    add_release_notes(publish)
    add_submit_options(publish)
    publish.add_argument("--submit", action="store_true", help="Actually submit for review")
    publish.set_defaults(func=cmd_publish)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        args.func(args)
    except AppGalleryError as exc:
        fail(str(exc))
    except KeyboardInterrupt:
        fail("interrupted", code=130)


if __name__ == "__main__":
    main()
