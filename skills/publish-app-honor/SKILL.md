---
name: publish-app-honor
description: Publish APK updates to the Honor AppMarket (荣耀应用市场) through the Publish-API 传包服务. Use when uploading honor channel APKs, automating 荣耀应用市场发版, querying Honor appId or audit status, binding uploaded files, updating 新版本特性, submitting for review, managing 分阶段发布, or working with developer.honor.com / appmarket-openapi-drcn.cloud.honor.com API 传包服务 docs.
---

# 荣耀应用市场 API 传包发版

> 本文中形如 `docs/发布版本更新日志.md`、`docs/应用发布平台清单.md` 的路径，指的是**调用方项目**仓库里的文档（相对项目根），不是本 skill 目录里的文件；各项目按自己的约定放置即可。

通过荣耀开发者服务平台的 **API 传包服务** 上传 APK、绑定资源文件、更新新版本特性并提交审核。

官方文档：[API传包服务指引](https://developer.honor.com/cn/doc/guides/101359)
接口摘要、文件类型表与错误码：[references/reference.md](references/reference.md)
脚本路径：`$SKILL_DIR/scripts/honor_publish.py`

## 前置条件

1. 已在荣耀开发者服务平台注册并创建**安卓应用**，且已绑定包名（即调用方项目的 `applicationId`）。
2. 在 **管理中心 → 开放能力 → 凭证 → API密钥** 申请 `Client_id` 与密钥。
3. 应用至少在控制台完整填写过一次基础信息与多语言信息（`update-language-info` 需要已有 `appName` / `intro` 才能只改新版本特性）。
4. 已构建并签名 `honor` 渠道 APK；渠道名见 `docs/应用发布平台清单.md`。
5. 只需要 Python 3 标准库，无第三方依赖。

## 凭据配置

不要把 `Client_id`、API 密钥、access_token 贴到对话里，也不要提交到 git。

脚本按**目标项目的 git 根目录名**找配置（与 publish-app-huawei / countly-data-analysis 同一套约定），所以要**在目标项目仓库目录里执行**；`$SKILL_DIR` 指本 skill 目录。

```bash
mkdir -p ~/.config/ai-ignore-config/<项目名>
cp "$SKILL_DIR/config.example.env" \
  ~/.config/ai-ignore-config/<项目名>/honor.env
# 自行编辑 ~/.config/ai-ignore-config/<项目名>/honor.env
```

脚本按顺序读取：

1. `--config /path/to/file`
2. `~/.config/ai-ignore-config/<项目名>/honor.env`
3. `$SKILL_DIR/config.env`

项目名可用 `HONOR_PROJECT` 环境变量覆盖。跑错目录会因缺配置直接报错，不会静默发到别的应用。

鉴权是账号级 `client_credentials`：脚本每次运行用 `client_id` + `client_secret` 向 `https://iam.developer.honor.com/auth/token` 换取 `access_token`（有效期 3600 秒），再以 `Authorization: Bearer <token>` 调用传包接口。没有签名步骤，也不需要证书。

## 推荐发版流程

构建并打 `honor` 渠道包：

```bash
fvm flutter build apk --release
VD="${VASDOLLY_JAR:-$HOME/.claude/skills/vasdolly-multi-channel-apk/VasDolly.jar}"
[ -f "$VD" ] || VD=.agents/skills/vasdolly-multi-channel-apk/VasDolly.jar
mkdir -p build/app/outputs/channels/
java -jar "$VD" put -c honor \
  build/app/outputs/flutter-apk/app-release.apk \
  build/app/outputs/channels/honor-app-release.apk
```

先体检：确认凭据可用、appId 能查到、APK 存在。

```bash
PY="$SKILL_DIR/scripts/honor_publish.py"
python3 "$PY" doctor
```

确认当前在架版本与是否有审核中的单（有审核中/待发布的版本时不能再次提交）：

```bash
python3 "$PY" current-release
```

预演整条发版链路，不发起任何写操作：

```bash
python3 "$PY" publish \
  --apk build/app/outputs/channels/honor-app-release.apk \
  --new-feature "修复若干问题，优化使用体验。" \
  --dry-run
```

真正发版（上传 APK → 绑定文件 → 更新新版本特性 → 提交审核）：

```bash
python3 "$PY" publish \
  --apk build/app/outputs/channels/honor-app-release.apk \
  --new-feature "修复若干问题，优化使用体验。"
```

输出里的 `releaseId` 用于查审核结果（**轮询间隔建议 3 小时**，过频会被限流）：

```bash
python3 "$PY" audit-status --release-id <releaseId>
```

版本更新内容记录在 `docs/发布版本更新日志.md`。发版前从对应版本的“商店更新说明”复制到 `--new-feature`，不要写进凭据配置文件。

## 子命令

| 命令 | 用途 |
|---|---|
| `doctor` | 检查配置、换取 token、按包名查 appId、检查本地 APK |
| `token` | 单独验证 `client_id` / 密钥能否换到 access_token |
| `appid` | 按包名查询 appId |
| `detail` | 查询应用全量信息，可用 `--section` 取单块（如 `languageInfo`） |
| `current-release` | 查询最新版本号与审核状态 |
| `upload` | 上传单个文件（APK、图标、截图、资质等），返回 `objectId` |
| `bind` | 把 `objectId` 绑定到应用；参数格式 `objectId[:languageId[:order]]` |
| `app-info` | 更新应用基础信息：分类、年龄分级、发布国家、隐私政策、备案。**整体覆盖**，需带齐必填字段 |
| `language` | 更新多语言文案。默认只改 `newFeature` 保留既有文案；首发用 `--intro(-file)` 补必填的应用介绍 |
| `submit` | 提交审核，返回 `releaseId` |
| `audit-status` | 按 `releaseId` 查审核结论与审核意见 |
| `phased-info` | 查询分阶段发布状态 |
| `phased-update` | 暂停 / 重启 / 取消 / 提前全网发布 / 更新分阶段计划 |
| `publish` | 一条龙：上传 APK → 绑定 → 更新新版本特性 → 提交审核 |

## 分阶段发布

分阶段发布要求**至少已有一个全网发布过的版本**。提交时用 `--release-type 3`：

```bash
python3 "$PY" publish --apk build/app/outputs/channels/honor-app-release.apk \
  --new-feature "修复若干问题。" \
  --release-type 3 --percentage 20.00 \
  --start 2026-01-01T10:00:00+0800 \
  --end 2026-01-15T10:00:00+0800 \
  --note "众测发布中，比例 20%"
```

之后调整或收尾：

```bash
python3 "$PY" phased-info
python3 "$PY" phased-update --operation-type 4   # 提前全网发布，不可撤销
```

`--operation-type`：`3` 暂停、`0` 重启、`5` 取消（不可恢复，需重新提审）、`4` 提前全网发布（不可撤销）、`1` 更新计划（同时传 `--percentage/--start/--end/--note`，比例只能增大）。

## 注意事项

- 荣耀没有沙盒环境；不加 `--dry-run` 的 `publish` / `submit` / `bind` / `language` 都是真实写操作，`submit` 会真正进入审核队列。
- 更新场景只需绑定要更新的文件，其余资源继承上一版本；首次发布才需要绑定图标、截图、资质等全部必选文件。
- APK（`fileType=100`）**需要和语种绑定**，默认绑到 `HONOR_DEFAULT_LANGUAGE`（`zh-CN`）；多语言应用用 `--language-id` 重复传。
- `update-language-info` 的 `setAll` 默认值是 1（会删掉未传的语种）。本脚本 `language` / `publish` 一律用 `setAll=0`，并先读 `get-app-detail` 把已有 `appName` / `intro` 带回去，避免把商店文案清空。
- APK 包名必须与应用绑定包名一致，`versionCode` 必须 ≥ 当前在架版本，否则报 `30003` / `30006`。
- 存在审核中、待发布、待分阶段发布、分阶段发布中的版本时无法再次提交（`20022`）。
- 大包（上限 4GB）可改用「通过URL上传文件」接口由荣耀后台回源下载；脚本目前只实现直传，若需要 URL 上传见 [references/reference.md](references/reference.md)。
- 文件上传路径有过期时间；`upload` 默认 POST 到文档示例里的 `file-upload` 接口，如遇网关问题可用 `--upload-via url` 改用返回的 `uploadUrl`。
- 接口返回非 0 时先查 [references/reference.md](references/reference.md) 的错误码表，再核对 appId、objectId、语种和包名。
