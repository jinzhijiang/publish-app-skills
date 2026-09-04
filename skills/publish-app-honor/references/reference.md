# 荣耀 API 传包服务接口摘要

来源：[API传包服务指引](https://developer.honor.com/cn/doc/guides/101359)（2026-07 抓取）。本文件只保留发版链路会用到的部分；国家/地区表、完整语言表、完整应用分类表以官方文档为准。

## 服务时序

```
获取 access_token
  → get-app-id（包名 → appId）
  → get-file-upload-url（登记文件，拿 objectId + uploadUrl）
  → file-upload（上传文件流）        // 或 upload-by-url 由荣耀后台回源下载
  → update-app-info / update-language-info / update-file-info（按需更新）
  → submit-audit（拿 releaseId）
  → get-audit-result（轮询审核结论）
```

## 鉴权

| 项 | 值 |
|---|---|
| 协议 | HTTPS POST |
| URL | `https://iam.developer.honor.com/auth/token` |
| 请求 | `Content-Type: application/x-www-form-urlencoded` |
| 响应 | `Content-Type: application/json` |

请求体：`grant_type=client_credentials`（固定值）、`client_id`、`client_secret`。

响应：`access_token`（账号级）、`expires_in`（秒，示例为 3600）、`token_type`（固定 `Bearer`）。

后续所有接口带 `Authorization: Bearer ${access_token}`。

所有业务接口统一返回 `{ "code": 0, "msg": "...", "data": ... }`，`code=0` 为成功。

## 接口列表

Base：`https://appmarket-openapi-drcn.cloud.honor.com/openapi/v1/publish`

| 接口 | 方法 | 路径 | 说明 |
|---|---|---|---|
| 根据包名查询APPID | GET | `/get-app-id?pkgName=` | 包名支持逗号分隔，最多 10 个；只返回当前账号下的应用 |
| 查询应用详细信息 | GET | `/get-app-detail?appId=` | 返回 `basicInfo` / `languageInfo` / `publishInfo` / `fileInfo` / `releaseInfo` |
| 获取应用文件上传路径 | POST | `/get-file-upload-url?appId=` | Body 是 `List<UploadFile>`，一次最多 20 个 |
| 上传应用文件 | POST | `/file-upload?appId=&objectId=` | `multipart/form-data`，字段名 `file` |
| 通过URL上传文件 | POST | `/upload-by-url?appId=` | 大文件场景，由荣耀后台回源下载 |
| 更新应用基础信息 | POST | `/update-app-info?appId=` | 分类、发布国家、年龄分级、隐私政策、备案信息等 |
| 更新应用多语言信息 | POST | `/update-language-info?appId=` | `languageInfoList` + `setAll` |
| 更新应用文件信息 | POST | `/update-file-info?appId=` | `bindingFileList`，把 `objectId` 绑到应用 |
| 应用提交审核 | POST | `/submit-audit?appId=` | 返回 `releaseId` |
| 查询应用审核状态 | POST | `/get-audit-result` | Body `{"appId":[{"appId":…,"releaseId":…}]}`，单次最多 20 个 |
| 查询最新版本与审核状态 | GET | `/get-app-current-release?appId=` | 直接按 appId 查 |
| 查询分阶段发布状态 | GET | `/get-phased-release-info?appId=` | 无分阶段版本时返回空 |
| 更新分阶段发布信息 | POST | `/update-phased-release-info?appId=` | 暂停 / 重启 / 取消 / 提前全网 / 更新计划 |

### get-file-upload-url

请求体是数组，每项：

| 字段 | 必选 | 类型 | 说明 |
|---|---|---|---|
| `fileName` | 是 | String | 用于生成 ID 和校验后缀；单次请求不允许重名 |
| `fileType` | 是 | Integer | 见下方文件类型表 |
| `fileSize` | 是 | Long | 字节 |
| `fileSha256` | 是 | String | 完整性校验 |

响应 `data` 为 `List<FileUploadPath>`：`fileName`、`uploadUrl`、`objectId`、`expireTime`（UTC 绝对秒，过期需重新获取）。

### upload-by-url

Body：`type`（`1` 创建上传任务 / `2` 查询上传结果）、`uploadList`（type=1 必传，最多 20 项，比 `UploadFile` 多一个 `fileUploadUrl`）、`objectList`（type=2 必传，元素 `{objectId}`）。

下载路径必须是 HTTPS、无鉴权、GET 直接可取文件流，长度 < 1024 字符。**查询上传状态频率需低于 3min/次**，否则可能被网关限流。

返回项含 `status`：`0` 上传成功、`1` 待上传、`2` 上传失败（失败原因在 `message`）。

### update-app-info

**整体覆盖，不是增量。** 只传要改的字段会报 `20034 app supply name is empty`
这类"必填为空"——未提交的必填字段被判空。正确做法是先 `get-app-detail`，
把已有必填项一并带上再改想改的。（vivo 恰好相反，它只更新你传的字段，别记混。）

字段名与 `get-app-detail` 的 `basicInfo` **同名**。不确定某个字段叫什么时，
先跑 `detail` 看键名，别猜。

| 字段 | 必填 | 说明 |
|---|---|---|
| `appCategoryId` | 是 | `1` 游戏 / `2` 应用 |
| `appClassification` | 是 | **只传三级分类 id** |
| `packageName` / `defaultLanguage` | 是 | 与建应用时一致 |
| `devName` / `supplyName` | 是 | 开发者/供应商名称，devName 不可改 |
| `releaseCountry` | 是 | 多个用 `|` 分隔，如 `CN|JP|DE` |
| `paymentInfo` | 是 | `1` 非联运 / `2` 联运 |
| `ratingId` | 是 | 年龄分级，取值 **3 / 8 / 12 / 16 / 18**（原 7 映射成 8） |
| `privacyPolicyUrl` | 是 | http(s) 网址 |
| `appRegistrationEntityStatus` | 分发含中国大陆则必填 | `1` 备案主体与账号主体一致 / `2` 不一致 / `3` 单机应用无需备案 |
| `unifiedSocialCreditId` | 同上 | 18 字符以内 |
| `appRegistrationNumber` / `appRegistrationEntityName` | 否 | 主动输入的备案号与主体名 |
| `webUrl` / `customerServiceEmail` / `customerServiceTel` | 否 | 客服电话纯数字 ≤20 字符 |
| `publicationNumber` | 中国大陆 + 游戏才必填 | 版号 |

#### 应用分类（三级 id，2026-09-04 从官方文档取）

一级 `-1` 软件 / `-2` 游戏；二级如 `112` 金融理财、`110` 商务、`101` 实用工具、`114` 便捷生活。
三级只列本类常用：**`11205` 记账**、`11204` 理财、`11002` 效率、`11003` 笔记、
`10105` 工具、`11407` 日历。完整表见
[API传包服务指引](https://developer.honor.com/cn/doc/guides/101359) 的「应用分类表」。

### update-language-info

| 字段 | 必选 | 说明 |
|---|---|---|
| `languageInfoList` | 是 | `List<PubLanguageInfo>` |
| `setAll` | 否 | 默认 **1**：不在列表里的语种会被删除；`0` 只更新列表中的语种 |

`PubLanguageInfo`：`languageId`（如 `zh-CN`）、`appName`（≤15 汉字 / 30 其他字符）、`intro`（≤8000 字符）、`briefIntro`（≤80，选填）、`newFeature`（≤500，选填）。

`appName` 与 `intro` 是必填，所以只想改 `newFeature` 时必须先 `get-app-detail` 把已有文案带回去 —— 脚本的 `language` / `publish` 子命令就是这么做的。

### update-file-info

Body `bindingFileList`，每项 `BindingFile`：

| 字段 | 必选 | 说明 |
|---|---|---|
| `objectId` | 是 | 已上传成功的文件 ID |
| `languageId` | 视文件类型 | 需要绑定语种的类型必填，且该语种此前已通过 `update-language-info` 建过 |
| `order` | 否 | 同类型多文件的展示顺序，从 0 开始；重复指定同一 order 会绑定失败 |

更新升级场景**只需绑定要更新的文件**，未更新的继承上一版本。

### submit-audit

| 字段 | 必选 | 说明 |
|---|---|---|
| `forceUpdate` | 否 | `0` 非强制（默认）、`1` 强制更新 |
| `testAccount` / `testPassword` | 否 | 审核用测试账号密码 |
| `testComment` | 否 | 审核备注，≤500 字 |
| `releaseType` | 是 | `1` 全网发布、`2` 指定时间发布、`3` 分阶段发布 |
| `releaseTime` | releaseType=2 必填 | `yyyy-MM-dd'T'HH:mm:ssZZ`，如 `2026-01-01T01:01:01+0800` |
| `phasedReleaseInfo` | releaseType=3 必填 | 见下 |

`phasedReleaseInfo`：`releasePercentage`（`0.00`–`100.00`，2 位小数）、`releaseStartDate`（须大于当前时间）、`releaseEndDate`（与开始时间差 ≤30 天，到点转全网）、`releaseNote`（≤500 字符）。分阶段发布要求**至少存在一个已全网发布的版本**。

响应 `data` 是 `releaseId`。

约束：更新场景需至少更新过基础信息、多语言信息、文件信息之一；首次发布需更新全部所需信息；存在审核中 / 待发布 / 待分阶段发布 / 分阶段发布中的版本时不可再次提交。

### get-audit-result

`auditResult`：`0` 审核中、`1` 审核通过、`2` 审核不通过、`3` 未提交审核或其他非审核状态。`get-app-current-release` 多一个 `4` 编辑中未提交审核。审核意见在 `auditMessage`，附件 URL 在 `auditAttachment`。

**建议轮询频率 3 小时一次**，超出可能被限流并影响其他业务请求。

### update-phased-release-info

`operationType`：`3` 暂停（发布中可操作）、`0` 重启（已暂停可操作）、`5` 取消（待发布/发布中/已暂停可操作，取消后不可恢复，需重新提审）、`4` 提前全网发布（不可撤销）、`1` 更新计划（此时 `phasedReleaseInfo` 必传）。

更新计划时发布比例**只能增大**；已到原计划开始时间后开始时间不可修改。

`get-phased-release-info` 的 `releaseStatus`：`1` 审核通过待发布、`2` 分阶段发布中、`3` 已暂停、`4` 已全网发布。

## 文件类型表

| fileType | 说明 | 绑语种 | 尺寸 | 大小 | 数量 | 格式 | 必选 |
|---|---|---|---|---|---|---|---|
| 1 | 应用图标 | 是 | 512×512 | 200KB | 1 | PNG/JPG/JPEG | 是 |
| 2 | 应用介绍截图-横向 | 是 | 1920×1080 | 5MB | 3–5 | PNG/JPG/JPEG | 横纵二选一 |
| 3 | 应用介绍截图-纵向 | 是 | 1080×1920 | 5MB | 3–5 | PNG/JPG/JPEG | 横纵二选一 |
| 10 | 应用介绍视频-横向 | 是 | 建议 1280×720，16:9，15s–2min | 500MB | 1 | MOV/MP4 | 否，方向须与截图一致 |
| 11 | 应用介绍视频-纵向 | 是 | 建议 720×1280，9:16 | 500MB | 1 | MOV/MP4 | 否，方向须与截图一致 |
| 12 | 应用推荐视频 | 是 | 建议 1440×810，16:9 | 500MB | 1 | MOV/MP4 | 否 |
| 26 | 介绍视频海报帧-横向 | 是 | 1280×720 | 5MB | 1 | PNG/JPG/JPEG | 否 |
| 27 | 介绍视频海报帧-纵向 | 是 | 720×1280 | 5MB | 1 | PNG/JPG/JPEG | 否 |
| 33 | 应用头图 | 是 | 1440×810 | 5MB | 1 | PNG/JPG/JPEG | 传了推荐视频则必选 |
| 13 | 计算机软件著作权登记书 | 否 | — | 15MB | 1 | JPEG/JPG/PNG/BMP/PDF | 中国大陆必填 |
| 14 | 版权授权书（自研可不提供） | 否 | — | 15MB | 1 | 同上 | 否 |
| 15 | 增值电信业务经营许可证(ICP) | 否 | — | 15MB | 1 | 同上 | 中国大陆且是应用则必填 |
| 16 | 其他渠道上架合规报告 | 否 | — | 15MB | 1 | 同上 | 大陆棋牌娱乐类游戏必填 |
| 17 | 公司股权结构 | 否 | — | 15MB | 1 | 同上 | 大陆棋牌娱乐类游戏必填 |
| 18 | 游戏合规运营承诺书 | 否 | — | 15MB | 1 | 同上 | 大陆棋牌娱乐类游戏必填 |
| 19 | 增值电信经营许可证 | 否 | — | 15MB | 1 | 同上 | 大陆棋牌娱乐类游戏必填 |
| 21 | 版号批文【官方合作渠道】 | 否 | — | 4MB | 1 | 同上 | 大陆游戏 21/22 至少一项 |
| 22 | 版号授权书 | 否 | — | 4MB | 1–2 | 同上 | 同上 |
| 35 | 其他特殊资质 | 否 | — | 15MB | 0–4 | 同上 | 否 |
| 36 | 其他资质文件 ZIP 包 | 否 | — | 100MB | 1 | ZIP | 否 |
| 37 | 备案主体营业执照 | 否 | — | 15MB | 1 | 同上 | 备案主体状态=2 时必填 |
| 38 | 备案说明协议 | 否 | — | 15MB | 1 | 同上 | 备案主体状态=2 时必填 |
| 39 | 单机应用免责承诺函 | 否 | — | 15MB | 1 | 同上 | 备案主体状态=3 时必填 |
| **100** | **APK 应用包** | **是** | — | **4GB** | 1 | APK | 是 |

> APK 包名要和应用绑定的包名一致，版本号需 **大于等于** 当前已上架版本。

## 常用枚举

- **语言**：`zh-CN` 简体中文、`zh-HK` 繁体（中国香港）、`zh-TW` 繁体（中国台湾）、`en-US` 美式英语、`en-GB` 英式英语、`ja` 日语、`ko` 韩语。完整表见官方文档。
- **年龄分级 `ratingId`**：3 / 8 / 12 / 16 / 18（原 7 会被映射成 8）。
- **`paymentInfo`**：`1` 非联运、`2` 联运。
- **`appCategoryId`**：`1` 游戏、`2` 应用。
- **`appRegistrationEntityStatus`**：`1` 备案主体与账号主体一致、`2` 不一致、`3` 单机应用不需备案。
- **应用分类（三级，`appClassification` 只传三级）**：一级 `-1` 软件 / `-2` 游戏；二级如 `110` 商务、`101` 实用工具、`114` 便捷生活；三级如 `11002` 效率、`11003` 笔记、`10105` 工具、`11407` 日历。完整表见官方文档。
- **发布国家 `releaseCountry`**：`|` 分隔的国家码，如 `CN|JP|DE`。

## 错误码

| 错误码 | 说明 |
|---|---|
| 10001 / 10002 / 10003 | 未传 / 格式非法 / 已过期的 access_token |
| 10004 / 10005 | 横向越权（无该资源操作权限）/ 纵向越权 |
| 10006 / 10007 | 签名不存在 / 签名校验不通过 |
| 11003 | 非法安装包名 |
| 20001–20005 | 包名或 APPID 为空 / 格式错 / APPID 不存在 |
| 20006–20009 | 应用名称、一句话描述、应用介绍、更新说明格式错误 |
| 20010–20013 | 图标、介绍视频、介绍截图格式错误或截图 URL 不正确 |
| 20014 / 20015 | 客服 Email / 热线格式不正确 |
| 20016–20019 | 版本包 URL 不存在或格式错 / 上架类型不存在 / 上架时间格式错 |
| 20020 / 20021 | 付费信息不正确 / 包名已被占用 |
| 20022 | 应用正在审核中，不允许提交 |
| 20023 | 应用未上架过，不允许提交 |
| 20024 | 指定的参数超出限制 |
| 20025–20027 | 流程 ID 为空 / 格式错 / 版本记录不存在 |
| 20028–20030 | objectId 为空 / 格式错 / 不存在 |
| 20031 | languageId 为空 |
| 20078 | 指定的媒体资源横纵向互相冲突 |
| 30001 / 30002 | APPID 不存在 / 包名不存在 |
| 30003 | 应用包名和 APK 中解析的包名不一致 |
| 30004 / 30005 | 应用包下载失败 / 无法解析 |
| 30006 | 应用包版本低于之前上架的版本 |
| 30007 | 应用包名和之前版本不一致 |
| 30009 | 应用包 MD5 校验不一致 |
| 30010 | 文件上传失败 |
| 30011 | 版本提交过于频繁，请稍后再试 |
| 30017 | 应用不存在指定的语言信息 |
| 31000–31005 | 签名过期 / 错误 / 参数错误 / 秘钥错误 / 参数类型错误 / 签名异常 |
| 40000 | 系统服务异常 |
