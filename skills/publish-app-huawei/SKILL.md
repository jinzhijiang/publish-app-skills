---
name: publish-app-huawei
description: 华为应用市场 AppGallery 上架与发版通用流程，覆盖 App 首次上架（控制台建应用、填应用信息、准备提交）与后续版本更新（AppGallery Connect API 传包、更新说明、提审）。Use when 首次上架华为应用市场、创建 AGC 应用、填写应用信息/截图/测试账号、uploading APK/AAB/HAP/APP packages、querying AppGallery app IDs or release status、updating release notes、submitting Android or HarmonyOS versions for review、automating 华为应用市场 / AppGallery Connect API 发版。
---

# 华为应用市场上架与发版

通用型 skill，不绑定具体项目。两条路线：

| 场景 | 路线 |
| --- | --- |
| **首次上架**（AGC 上还没有这个应用） | 控制台手工建应用 + 填信息（API 建不了应用），首包可走 API 上传。见下文「首次上架」与 `references/first-launch.md` |
| **后续更新**（应用已在架） | 全程 API：`scripts/appgallery_publish.py` 一条命令传包 + 更新说明 + 提审 |

详细接口、字段和排错见 `references/reference.md`。

## 凭据配置（按项目隔离）

不要把服务账号密钥文件、`private_key`、token 贴到对话里，也不要提交到 git。

脚本按**目标项目的 git 根目录名**找配置（与 countly-data-analysis 同一套约定），所以要**在目标项目仓库目录里执行**：

```bash
# 在目标项目仓库里执行；<项目名> 即 git 根目录名
mkdir -p ~/.config/ai-ignore-config/<项目名>
cp "$SKILL_DIR/config.example.env" ~/.config/ai-ignore-config/<项目名>/appgallery.env
# 本地编辑填写，勿贴到对话
```

读取顺序：`--config PATH` > `~/.config/ai-ignore-config/<git 根目录名>/appgallery.env` > skill 目录 `config.env`；项目名可用 `HUAWEI_PROJECT` 环境变量覆盖。跑错目录会因缺配置直接报错，不会静默发到别的应用。

### 鉴权：服务账号（Service Account / JWT）

在 AGC **用户与访问 → API密钥 → Connect API** 创建服务账号：**类型「开发者级」**、**角色含发布权限（管理员 / APP管理员；运营和开发都没有）**，下载 `*private.json` 密钥文件，绝对路径填 `HUAWEI_SERVICE_ACCOUNT_KEY`。

脚本用密钥文件的 `private_key` 以 **PS256** 签发 JWT，**该 JWT 本身即 bearer token**（不需要再 POST 换取），直接 `Authorization: Bearer <JWT>` 调 connect-api。

**服务账号是账号级凭据**：一份密钥可发布该华为账号名下**所有**应用——新上架一个应用**不需要新凭据**，配好 appId 就能用；Android 与 HarmonyOS 也共用同一份，只有 appId 不同。多项目共用华为账号时，各项目的 `appgallery.env` 指向同一个密钥文件即可。

> 排错：密钥文件 `project_id` **必须为空**（非空=项目级，一直 403）；角色缺发布权限时鉴权能过但接口返回 **HTTP 403（空 body）**；token 本身无效则是 401 `client token auth failed`。`doctor` 会回显 `keyFields` / `projectScopedWarning` 帮助核对。

## 首次上架

完整控制台操作与踩坑清单见 **`references/first-launch.md`**。骨架：

1. **控制台建应用**（API 无此能力）：我的APP → 对应平台 tab（Android/HarmonyOS）→ 新建发布。软件包类型 APK、设备、应用名称、分类（要选到二级/三级，如 应用/工具/效率）、默认语言。建完立即能拿到 **APP ID**，填进 `appgallery.env`。
2. **控制台填「应用信息」**：应用介绍(≤8000)/一句话简介(≤80)/新版本特性(≤500)、216×216 直角图标、**严格 9:16 竖版截图 3~5 张**。此页**必填项全填完才能保存**。三个坑：文案**不能带 emoji**；截图非 9:16 直接拒；**同一张图删了也不能重传**（服务端按内容判重，换编码可绕）。
3. **控制台填「准备提交」**：此页**支持部分保存**，可拿到一项填一项。隐私政策网址、付费情况、年龄分级、备案信息、联系方式、测试账号（勾「需要登录进行审核」后出现用户名/密码栏）。
4. **首包上传走 API**（下方「后续更新」同一条命令）：首次传包会把 APK 内的包名**永久绑定**到该 appId——**绑定以 APK 为准，配置里的包名不参与**，传错包就绑错名，传前必核对。传完用 `appid-list` 按包名反查确认绑定正确。
5. 提审前人工过一遍 `references/first-launch.md` 的检查清单（发布国家、测试账号可注销性等），然后 `submit` 或控制台点提交。

## 后续更新（推荐发版流程）

先检查配置和本地产物（在目标项目仓库根执行；`$SKILL_DIR` 为本 skill 目录）：

```bash
PY="$SKILL_DIR/scripts/appgallery_publish.py"
python3 "$PY" doctor
```

查询 appId，确认 Android 与 HarmonyOS 没有串：

```bash
python3 "$PY" appid-list --platform android
python3 "$PY" appid-list --platform ohos
```

构建（Flutter 项目示例；FVM 管理的项目记得 `fvm` 前缀，产物路径以项目为准）：

```bash
fvm flutter build apk --release
```

预演（强烈建议先跑，`--dry-run` 不改线上任何东西）：

```bash
python3 "$PY" publish --platform android \
  --file build/app/outputs/flutter-apk/app-release.apk \
  --release-notes-file /path/to/notes-zh.txt \
  --dry-run
```

真实上传并关联草稿；**不提交审核**：

```bash
python3 "$PY" publish --platform android \
  --file build/app/outputs/flutter-apk/app-release.apk \
  --release-notes-file /path/to/notes-zh.txt
```

确认无误后提审（加 `--submit`），或改在控制台人工点「提交审核」。

HarmonyOS 同一脚本换平台与产物：

```bash
python3 "$PY" publish --platform ohos \
  --file build/ohos/hap/entry-default-signed.hap \
  --release-notes "修复若干问题，优化使用体验。" \
  --dry-run
```

更新说明从项目的 CHANGELOG / 发布日志复制（写给用户看、无 emoji、卡 500 字），不写进凭据配置文件。

### 临时发另一个应用（不建配置）

`--app-id` / `--file` 可完全覆盖配置，适合同账号下给别的应用应急传包：

```bash
python3 "$PY" publish --platform android --app-id <目标appId> --file <apk路径> \
  --release-notes-file <notes> 
```

包名绑定以 APK 内为准，dry-run 回显里的 `packageName` 只是配置值、不参与上传，但**appId 一定要核对**。

## 子命令速查

| 命令 | 用途 |
|---|---|
| `doctor` | 检查配置、平台 appId、包名、默认产物路径和文件后缀 |
| `token` | 获取 token，默认只打印脱敏 token 和有效期 |
| `appid-list` | 按包名查询 appId，Android 默认 `packageTypes=1`，HarmonyOS 默认 `packageTypes=7` |
| `info` | 查询应用信息，验证 appId 与权限；也可回读隐私政策/分级/发布国家等已配字段 |
| `status` | 查询当前可见的应用/版本状态，当前实现复用 `app-info` 响应 |
| `release-notes` | 更新草稿的 `newFeatures` 更新说明 |
| `upload` | 上传本地包，返回可用于 `attach-file` 的 `fileDestUrl` |
| `attach-file` | 把已上传包关联到应用草稿 |
| `submit` | 提交审核；支持正式全量、定时、分阶段发布参数 |
| `publish` | 一键执行查询、上传、关联、更新说明；只有显式 `--submit` 才提交审核 |

## 注意事项

- AppGallery Connect **没有本地沙盒**；`upload`、`attach-file`、`release-notes`、`submit` 都会改线上草稿。调试先加 `--dry-run`。
- 提审是不可逆动作：默认不带 `--submit`，提审前和用户确认。
- 默认 OBS 直传；接口不兼容时用 `--upload-mode legacy` 走旧版 multipart。
- 提交审核前，应用信息、隐私政策、分级、截图、测试账号等必须已在 AGC 草稿中配置完整，否则 submit 被拒。
- versionCode 只能增不能减；被 AGC 拦「版本号重复」时改的是构建版本号（Flutter 项目即 `pubspec.yaml` 的 `+n`）。
