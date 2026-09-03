# AppGallery Connect API Reference

Use this reference only after the `publish-app-huawei` skill triggers. It keeps endpoint and field details out of `SKILL.md`.

## Sources

- Official overview: https://developer.huawei.com/consumer/cn/doc/AppGallery-connect-Guides/agcapi-overview-0000001158245083
- Official AGC product overview: https://developer.huawei.com/consumer/en/agconnect
- Postman mirror of Huawei Connect API: https://www.postman.com/trl2dtse/hms-core/documentation/uzfweoj/connect-api
- Submit app request mirror: https://www.postman.com/trl2dtse/hms-core/request/zuv7gy1/submitting-an-app-for-release

## Domains

Connect API domain must match the app data processing location:

| Location | Domain |
|---|---|
| China | `connect-api.cloud.huawei.com` |
| Germany | `connect-api-dre.cloud.huawei.com` |
| Singapore | `connect-api-dra.cloud.huawei.com` |
| Russia | `connect-api-drru.cloud.huawei.com` |

Token and publish endpoints must use the same domain.

## Authentication (Service Account / JWT)

Auth uses a Huawei **service account** key file (downloaded JSON) — not client_id/client_secret. Build a JWT signed with the key file's `private_key` using **PS256 (SHA256withRSA/PSS)**. The signed JWT **is** the bearer token — there is NO token-exchange request (do not POST it anywhere).

- JWT header: `{"alg":"PS256","typ":"JWT","kid":<key_id>}`
- JWT claims: `iss=<sub_account>`, `aud=<token_uri>` (fixed to `https://oauth-login.cloud.huawei.com/oauth2/v3/token`), `iat=<now>`, `exp=<now+3600>`

Call the publish API with the JWT directly as the bearer token:

```text
GET /api/publish/v2/appid-list?... HTTP/1.1
Host: connect-api.cloud.huawei.com
Authorization: Bearer <signed JWT>
```

No `client_id` header is needed for service accounts. Credentials come from a single shared `HUAWEI_SERVICE_ACCOUNT_KEY` — one Huawei service account publishes every app in the account. The `aud`/token_uri value is overridable via `HUAWEI_SA_TOKEN_URL`.

The service account must be **developer-level (开发者级)** and hold a **role that includes Publishing API permission**, otherwise the API authenticates the JWT but returns **HTTP 403 (empty body)**. A wrong/garbage token instead returns 401 `{"ret":{"code":205524993,"msg":"client token auth failed"}}`.

## Platform Defaults

| Platform | Package/bundle | `packageTypes` | Default file | Default `fileType` |
|---|---:|---:|---|---:|
| Android | `$HUAWEI_ANDROID_PACKAGE_NAME` (per-project) | `1` | `build/app/outputs/channels/huawei-app-release.apk` | `5` |
| HarmonyOS | `$HUAWEI_OHOS_PACKAGE_NAME` (per-project) | `7` | `build/ohos/app/ohos-release-signed.app` | `5` |

Auth is a single shared service account key file `HUAWEI_SERVICE_ACCOUNT_KEY` (one Huawei service account can publish every app in the account); only the appId differs per platform (`HUAWEI_ANDROID_APP_ID` / `HUAWEI_OHOS_APP_ID`).

`fileType=5` is used by common AppGallery package upload integrations for APK/AAB-style app packages. Keep it configurable because Huawei can extend file type rules for HarmonyOS packages.

## Useful Endpoints

### Query appId

`GET /api/publish/v2/appid-list?packageName=<package>&packageTypes=<type>`

Use this before configuring the final app IDs. Android uses `packageTypes=1`; HarmonyOS uses `packageTypes=7`.

### Query app info / status

`GET /api/publish/v2/app-info?appId=<appId>`

Use for credential checks and current draft/status inspection. The script's `status` command currently prints this response; add a dedicated version-list endpoint later if Huawei exposes one for the current HarmonyOS release workflow.

### Upload by OBS

`GET /api/publish/v2/upload-url/for-obs?appId=<appId>&fileName=<name>&contentLength=<bytes>&suffix=<suffix>`

Response shape used by the script:

```json
{
  "urlInfo": {
    "url": "https://...",
    "objectId": "...",
    "headers": {
      "Authorization": "...",
      "Content-Type": "application/octet-stream",
      "Host": "...",
      "x-amz-date": "...",
      "x-amz-content-sha256": "..."
    }
  }
}
```

Upload the raw file bytes with `PUT` to `urlInfo.url`, passing Huawei's returned headers exactly. Use `urlInfo.objectId` as `fileDestUrl`.

### Upload by legacy multipart

`GET /api/publish/v2/upload-url?appId=<appId>&suffix=<suffix>&releaseType=1`

Response contains `uploadUrl` and `authCode`. Upload using multipart form fields:

- file field name: `file`
- `authCode`
- `fileCount=1`

The upload response may spell the destination as `fileDestUlr` in older examples. The script accepts both `fileDestUlr` and `fileDestUrl`.

### Attach package file

`PUT /api/publish/v2/app-file-info?appId=<appId>`

Body:

```json
{
  "fileType": 5,
  "files": [
    {
      "fileName": "app-huawei.apk",
      "fileDestUrl": "...",
      "size": "123456"
    }
  ]
}
```

The response commonly includes `pkgVersion`; keep it in the command output because it helps diagnose AAB/Harmony package parsing.

### Update release notes

`PUT /api/publish/v2/app-language-info?appId=<appId>`

本地化文案字段（`store-listing` 命令可写，实测 2026-09-03）：

| 字段 | 含义 | 上限 | ASO 权重 |
| --- | --- | ---: | --- |
| `appName` | 应用名称 | 以后台校验为准 | 最高；**改名会重新走审核** |
| `briefInfo` | 一句话简介 | 80 | 高，参与商店搜索 |
| `appDesc` | 应用介绍 | 8000 | 中，参与商店搜索 |
| `newFeatures` | 新版本特性（更新说明） | 500 | 低 |

`GET app-info` 的 `languages[]` 里还会返回 `icon` / `introPic` / `deviceMaterials` /
`introVideo` / `rcmdPic` / `showType` 等素材字段——那些是**只读回显**，不要原样 PUT 回去。

该接口是**增量更新**：只传 `newFeatures` 不会清空 `appDesc` 与素材
（`release-notes` 命令一直这么用）。不放心时加 `--merge-current`，
它先 `app-info` 读回四个文本字段再一起提交。

**华为硬性要求：文案不能带 emoji**，否则保存被拒。

## releaseState 实测取值（2026-09-03，一次 Android + HarmonyOS 发版）

`GET app-info` 的 `appInfo.releaseState` 是判断「到底提交没有」最直接的信号，
比看 `versionNumber` 可靠——草稿版本号在传包后就变了，但那不代表已提交。

| 值 | 观察到的时机 |
| ---: | --- |
| `0` | 稳定态：有在架版本，草稿无待提交变更 |
| `7` | 传包 + 改文案之后、提审之前（草稿有待提交变更） |
| `5` | **Android** 提交审核后 |
| `12` | **HarmonyOS** 提交审核后 |

两端提审后的取值**不一样**，别用同一个常量判断。这些是实测观察，不是华为公开文档的枚举，
新场景（定时发布、分阶段发布、驳回）可能有别的值——遇到就补进本表。

判断「已上架」看 `onShelfVersionNumber` / `onShelfVersionCode`，
它们在提审后**不会变**，只有审核通过发布后才更新。

Body:

```json
{
  "lang": "zh-CN",
  "newFeatures": "修复若干问题，优化使用体验。"
}
```

Use only the listing languages already configured in AppGallery Connect.

### Submit for release

`POST /api/publish/v2/app-submit?appId=<appId>`

Optional query parameters:

| Parameter | Meaning |
|---|---|
| `releaseTime` | Scheduled release time, UTC format like `2015-01-01T01:01:01+0800` |
| `remark` | 10-300 character remark |
| `channelId` | Channel ID |
| `releaseType` | `1` full release, `3` phased release |

For phased release, body can include:

```json
{
  "phasedReleaseStartTime": "...",
  "phasedReleaseEndTime": "...",
  "phasedReleasePercent": "...",
  "phasedReleaseDescription": "..."
}
```

## Common Failures

| Symptom | Likely cause |
|---|---|
| `client token auth failed` | Using the raw token response instead of `access_token`, domain mismatch, wrong API client, or missing `client_id` header |
| `get no file from request` | Legacy upload used the wrong multipart file field; use field name `file` |
| `SignatureDoesNotMatch` | OBS upload headers were changed; pass returned OBS headers exactly and upload raw bytes |
| package parse/version error | Wrong appId, wrong platform package, unsigned package, package name mismatch, or version code not incremented |
| submit rejected | Required draft fields are incomplete in AppGallery Connect, such as privacy policy, age rating, screenshots, or release notes |
