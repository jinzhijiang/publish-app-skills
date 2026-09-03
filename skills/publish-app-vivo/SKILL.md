---
name: publish-app-vivo
description: Publish APK updates to the vivo 应用商店 through the API 传包服务. Use when uploading vivo channel APKs, automating vivo 应用商店发版, querying vivo app details or audit status, uploading apk/icon/screenshot files for 流水号, submitting app.sync.update.app, or working with dev.vivo.com.cn / developer-api.vivo.com.cn API 接口传包 docs.
---

# vivo 应用商店 API 传包发版

> 本文中形如 `docs/发布版本更新日志.md`、`docs/应用发布平台清单.md` 的路径，指的是**调用方项目**仓库里的文档（相对项目根），不是本 skill 目录里的文件；各项目按自己的约定放置即可。

通过 vivo 开放平台的 **API 传包服务** 上传 APK、拿到流水号并同步提交更新审核。

官方文档：[API接入说明](https://dev.vivo.com.cn/documentCenter/doc/327)
接口摘要、返回码与字典项：[references/reference.md](references/reference.md)
脚本路径：`$SKILL_DIR/scripts/vivo_publish.py`

## 前置条件

1. 已在 vivo 开放平台创建应用并至少完整上架过一次。
2. 管理中心 → 账号管理 → api管理 → 立即开通，拿到 `access_key` 与 `access_secret`。
   一次申请，账号下所有应用都能用。
3. 已构建并签名 `vivo` 渠道 APK；渠道名见 `docs/应用发布平台清单.md`。
4. 只需要 Python 3 标准库，无第三方依赖。

## 凭据配置

不要把 `access_key`、`access_secret` 贴到对话里，也不要提交到 git。

脚本按**目标项目的 git 根目录名**找配置（与 publish-app-huawei / countly-data-analysis 同一套约定），所以要**在目标项目仓库目录里执行**；`$SKILL_DIR` 指本 skill 目录。

```bash
mkdir -p ~/.config/ai-ignore-config/<项目名>
cp "$SKILL_DIR/config.example.env" \
  ~/.config/ai-ignore-config/<项目名>/vivo.env
# 自行编辑 ~/.config/ai-ignore-config/<项目名>/vivo.env
```

脚本按顺序读取：

1. `--config /path/to/file`
2. `~/.config/ai-ignore-config/<项目名>/vivo.env`
3. `$SKILL_DIR/config.env`

项目名可用 `VIVO_PROJECT` 环境变量覆盖。跑错目录会因缺配置直接报错，不会静默发到别的应用。

vivo 没有 token 换取步骤：每次请求都用 `access_secret` 对全部参数（按 key 排序拼串）做
HmacSHA256 得到 `sign`。文件上传时 `file` 不参与签名。

## 推荐发版流程

构建并打 `vivo` 渠道包：

```bash
fvm flutter build apk --release
VD="${VASDOLLY_JAR:-$HOME/.claude/skills/vasdolly-multi-channel-apk/VasDolly.jar}"
[ -f "$VD" ] || VD=.agents/skills/vasdolly-multi-channel-apk/VasDolly.jar
mkdir -p build/app/outputs/channels/
java -jar "$VD" put -c vivo \
  build/app/outputs/flutter-apk/app-release.apk \
  build/app/outputs/channels/vivo-app-release.apk
```

先体检：确认凭据可用、能查到应用详情、本地 APK 存在。

```bash
PY="$SKILL_DIR/scripts/vivo_publish.py"
python3 "$PY" doctor
```

`appDetail.status` 是审核状态（1 草稿、2 待审核、3 审核通过、4 审核不通过、5 撤销审核），
`saleStatus` 是上架状态（0 待上架、1 已上架、2 已下架）。审核中的版本不能再提交。

预演整条链路，不发起任何写操作：

```bash
python3 "$PY" publish \
  --apk build/app/outputs/channels/vivo-app-release.apk \
  --update-desc "修复若干问题，优化使用体验。" \
  --dry-run
```

真正发版（上传 APK → 同步更新提交审核）：

```bash
python3 "$PY" publish \
  --apk build/app/outputs/channels/vivo-app-release.apk \
  --update-desc "修复若干问题，优化使用体验。"
```

`app.sync.update.app` 是同步接口，返回成功即已进入审核队列。之后查进度：

```bash
python3 "$PY" detail
```

版本更新内容记录在 `docs/发布版本更新日志.md`。发版前从对应版本的"商店更新说明"
复制到 `--update-desc`，不要写进凭据配置文件。

## 沙箱环境

vivo 是这几家里少数**提供沙箱**的，调试签名和参数不必拿正式环境试：

```bash
python3 "$PY" --env sandbox detail
```

沙箱的 `access_key` / `access_secret` 要单独申请，和正式环境不通用；沙箱里看不到正式环境的应用，
调更新接口前得先在沙箱建应用。沙箱每个接口 100 次/天，正式环境每个传包接口 50 次/天。

## 子命令

| 命令 | 用途 |
|---|---|
| `doctor` | 检查配置、应用详情与审核状态、本地 APK |
| `detail` | `app.query.details`：查询应用详情、版本号、审核与上架状态 |
| `upload` | 上传单个文件，返回流水号 `serialnumber`；`--method` 可切 icon/截图接口 |
| `update` | `app.sync.update.app`：用已有流水号提交更新 |
| `publish` | 一条龙：上传 APK → 同步更新提交审核 |

常用可选参数（`update` / `publish` 通用）：`--detail-desc`、`--remark`、`--online-type`、
`--sche-online-time`、`--compatible-device`，其它业务字段用 `--set key=value`（可重复），
例如 `--set rateAge=12`。

## 注意事项

- `versionCode` 默认取上传接口从 APK 里解析出来的值，不用手填；两者不一致会报 `15012`。
- 和 OPPO 不同，vivo 的更新接口**只更新你传的字段**，没传的资料保留，所以常规发版只要
  apk + 新版说明。
- 字段长度硬约束：`updateDesc` 5~200 字符，`detailDesc` 50~1000 字符，`remark` 10~200 字符。
  超出会报 20016 / 20017 / 20015。
- `compatibleDevice` 是必传项（1 手机、2 手机和平板、3 平板），默认从 `VIVO_COMPATIBLE_DEVICE` 读，
  配置里给的是 `2`。
- `onlineType=2`（定时上架）必须同时给 `--sche-online-time 'yyyy-MM-dd HH:mm:ss'`，且不能早于当前时间；
  脚本会在发请求前拦下这种情况。
- 时间戳误差要在 20 分钟内，本机时间不准会报 `10005`。
- 正式环境每个传包接口 **50 次/天**，别拿它当轮询用；查状态走 `detail`。
- 应用审核中（`12010`）或待上架（`12022`）时不允许更新。
- 合同过期或未签署会报 `21004`，要先登录 vivo 开放平台签合同。
