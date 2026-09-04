---
name: publish-app-oppo
description: Publish APK updates to the OPPO 软件商店 through the API 传包能力. Use when uploading oppo channel APKs, automating OPPO 应用商店发版, querying OPPO app info or audit status, uploading files for icons/screenshots, submitting 发布版本 or 更新资料, polling 任务状态, or working with open.oppomobile.com / oop-openapi-cn.heytapmobi.com API 传包 docs.
---

# OPPO 软件商店 API 传包发版

> 本文中形如 `docs/发布版本更新日志.md`、`docs/应用发布平台清单.md` 的路径，指的是**调用方项目**仓库里的文档（相对项目根），不是本 skill 目录里的文件；各项目按自己的约定放置即可。

通过 OPPO 开放平台的 **API 传包能力** 上传 APK、继承线上资料并提交新版本审核。

官方文档：[API传包能力接入](https://open.oppomobile.com/documentation/page/info?id=10998)
接口摘要、必传字段与状态码：[references/reference.md](references/reference.md)
脚本路径：`$SKILL_DIR/scripts/oppo_publish.py`

## 前置条件

1. 已在 OPPO 开放平台**手动创建过应用**并至少完整上架过一次。API 只能更新已有应用，不能建应用。
2. 管理中心 → 产品导航 → 我的API → 创建服务端应用，拿到 `client_id`（19 位）与 `client_secret`（64 位）。团队账号要用管理员登录。
3. API 传包能力目前只对**企业开发者**开放（普通应用、合作游戏）。
4. 已构建并签名 `oppo` 渠道 APK；渠道名见 `docs/应用发布平台清单.md`。
5. 只需要 Python 3 标准库，无第三方依赖。

## 凭据配置

不要把 `client_id`、`client_secret`、access_token 贴到对话里，也不要提交到 git。

脚本按**目标项目的 git 根目录名**找配置（与 publish-app-huawei / countly-data-analysis 同一套约定），所以要**在目标项目仓库目录里执行**；`$SKILL_DIR` 指本 skill 目录。

```bash
mkdir -p ~/.config/ai-ignore-config/<项目名>
cp "$SKILL_DIR/config.example.env" \
  ~/.config/ai-ignore-config/<项目名>/oppo.env
# 自行编辑 ~/.config/ai-ignore-config/<项目名>/oppo.env
```

脚本按顺序读取：

1. `--config /path/to/file`
2. `~/.config/ai-ignore-config/<项目名>/oppo.env`
3. `$SKILL_DIR/config.env`

项目名可用 `OPPO_PROJECT` 环境变量覆盖。跑错目录会因缺配置直接报错，不会静默发到别的应用。

鉴权是账号级的：`client_id` + `client_secret` 换 `access_token`（48 小时有效），之后每个请求再用
`client_secret` 对全部参数做 HmacSHA256 得到 `api_sign`。**重复换 token 会让旧 token 在 5 分钟内失效**，
所以脚本把 token 缓存在 `~/.config/ai-ignore-config/<项目名>/.oppo_token.json`（权限 0600），
需要强制换新时用 `token --force`。

## 推荐发版流程

构建并打 `oppo` 渠道包：

```bash
fvm flutter build apk --release
VD="${VASDOLLY_JAR:-$HOME/.claude/skills/vasdolly-multi-channel-apk/VasDolly.jar}"
[ -f "$VD" ] || VD=.agents/skills/vasdolly-multi-channel-apk/VasDolly.jar
mkdir -p build/app/outputs/channels/
java -jar "$VD" put -c oppo \
  build/app/outputs/flutter-apk/app-release.apk \
  build/app/outputs/channels/oppo-app-release.apk
```

先体检：确认凭据可用、能查到线上版本、本地 APK 存在、发布必需的资料字段线上都有值。

```bash
PY="$SKILL_DIR/scripts/oppo_publish.py"
python3 "$PY" doctor
```

`missingForPublish` 非空说明控制台上少填了东西，先去控制台补齐（或发版时用 `--set` 显式传），
否则 `publish` 会在提交前就报错退出。

预演。`--dry-run` 完全离线；`--preview` 会调查询接口（只读），把继承 + `--set` 合并后
**真正要 POST 的整份 body** 打出来——OPPO 最容易出问题的就是继承回来的资料对不对，
提审前建议看这一份：

```bash
python3 "$PY" publish \
  --apk build/app/outputs/channels/oppo-app-release.apk \
  --update-desc "修复若干问题，优化使用体验。" \
  --preview
```

真正发版（上传 APK → 读线上资料 → 提交发布版本）：

```bash
python3 "$PY" publish \
  --apk build/app/outputs/channels/oppo-app-release.apk \
  --update-desc "修复若干问题，优化使用体验。"
```

发布版本是**异步任务**，接口返回只代表收下了。等 10 秒以上再查处理结果：

```bash
python3 "$PY" task-state --version-code 30004
```

`task_state`：1 待处理、2 处理成功、3 处理失败（`err_msg` 是原因）。处理成功后用
`python3 "$PY" info --field audit_status --field audit_status_name` 跟审核进度。

版本更新内容记录在 `docs/发布版本更新日志.md`。发版前从对应版本的"商店更新说明"
复制到 `--update-desc`，不要写进凭据配置文件。

## 子命令

| 命令 | 用途 |
|---|---|
| `doctor` | 检查配置、token、线上版本与审核状态、本地 APK、缺失的必传资料字段 |
| `token` | 查看当前缓存 token；`--force` 强制换新（旧 token 5 分钟后失效） |
| `info` | 查询应用详情，`--field` 可重复，只输出关心的字段 |
| `upload` | 上传单个文件（`--type apk`/`photo`/`resource`），返回 url 与 md5 |
| `task-state` | 查询发布版本异步任务的处理结果 |
| `publish` | 一条龙：上传 APK → 继承线上资料 → 提交发布版本（`--dry-run` 离线预演，`--preview` 只读打印完整 body） |

## 版本号

`--version-code` 不传时脚本读项目根 `pubspec.yaml` 的 `version: x.y.z+CODE`，取 `+` 后面那段。
提交前会和线上 `version_code` 比较，不大于线上版本直接退出，避免白跑一次上传。

## 注意事项

- OPPO **没有沙箱环境**，不加 `--dry-run` 的 `publish` / `upload` 都是真实写操作。
- 发布版本接口（`/resource/v1/app/upd`）要求**整份资料一起提交**：只传 apk 会把商店文案、截图、
  资质全部清空。脚本因此先读 `/resource/v1/app/info`，把 `app_name`、分类、`summary`、`detail_desc`、
  `icon_url`、`pic_url`、`copyright_url`、商务联系人、`age_level` 等继承回来，只替换
  `version_code` / `apk_url` / `update_desc`。要改其它字段用 `--set key=value`（可重复）。
- 继承来的逗号分隔 URL 字段（截图、版权证明）会被清掉空位——`info` 返回的值常带尾随逗号，
  原样回传会被校验拦下。
- 发版接口**不接受自建 CDN 地址**，APK/图片必须走平台的文件上传接口拿 URL。
- 文件上传的 `sign` 是一次性的，每个文件都要重新调一次 `get-upload-url`；脚本已经处理。
- 字段长度硬约束：`summary` ≤13 字符且不能有标点空格，`detail_desc` **≥20 且 ≤1024 字**，
  `update_desc` ≥5 字，竖版截图 ≥2 张。
- **`detail_desc` 超 1024 字会被静默截断**，不报错、任务照样「处理成功」，但商店页会断在句子中间。
  提交前自己卡长度，提交后用 `info --field detail_desc` 回读比对。
- `version_code` 必须严格大于线上版本，`version_name` 建议同步更新，否则报"版本低于线上版本"。
- 应用正在审核中时不能再次提交。
- **继承回来的 `adaptive_type` 不能原样提交**：`info` 返回 `"0"`（未设置的哨兵值），
  回传会得到 `errno=911001 适配方式有误`。它不在必传字段里，发版时加 `--omit adaptive_type`
  让平台沿用上一版即可。报错发生在 APK 上传成功**之后**，重跑会重新上传一次。
  详见 [references/reference.md](references/reference.md)。
- 只改文案不换包用 `更新资料`（`/resource/v1/app/updm`）而不是发布版本；脚本暂未封装该接口，
  参数见 [references/reference.md](references/reference.md)。
