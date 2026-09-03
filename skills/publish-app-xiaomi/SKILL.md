---
name: publish-app-xiaomi
description: Publish APK updates to Xiaomi App Store via the Xiaomi automatic publishing API. Use when uploading xiaomi channel APKs, automating 小米应用商店发版, querying Xiaomi package info or categories, submitting normal APK updates, submitting Xiaomi channel APK packages, or working with dev.mi.com / api.developer.xiaomi.com automatic release docs.
---

# 小米 APK 自动发布

> 本文中形如 `docs/发布版本更新日志.md`、`docs/应用发布平台清单.md` 的路径，指的是**调用方项目**仓库里的文档（相对项目根），不是本 skill 目录里的文件；各项目按自己的约定放置即可。

通过小米应用商店自动发布接口提交 APK 更新、查询应用包信息、查询分类、提交渠道包。

官方文档：[应用自动发布接口操作指南](https://dev.mi.com/xiaomihyperos/documentation/detail?pId=1134)  
接口摘要与字段说明：[reference.md](reference.md)  
脚本路径：`$SKILL_DIR/scripts/xiaomi_publish.py`

## 前置条件

1. 小米开放平台已创建应用包名，普通更新需应用已在架。
2. 已在控制台获取 API 私钥和公钥证书；私钥不是登录密码，重置私钥会让旧私钥失效。
3. 已构建小米渠道 APK；本项目渠道名通常为 `xiaomi`。
4. 系统可用 `openssl` 命令；脚本用它执行 RSA/PKCS1 公钥分段加密。

## 凭据配置

不要把私钥、账号、证书内容贴到对话里，也不要提交到 git。

推荐配置：

脚本按**目标项目的 git 根目录名**找配置（与 publish-app-huawei / countly-data-analysis 同一套约定），所以要**在目标项目仓库目录里执行**；`$SKILL_DIR` 指本 skill 目录。

```bash
mkdir -p ~/.config/ai-ignore-config/<项目名>
cp "$SKILL_DIR/config.example.env" \
  ~/.config/ai-ignore-config/<项目名>/xiaomi.env
# 自行编辑 ~/.config/ai-ignore-config/<项目名>/xiaomi.env
```

脚本按顺序读取：

1. `--config /path/to/file`
2. `~/.config/ai-ignore-config/<项目名>/xiaomi.env`
3. `$SKILL_DIR/config.env`

项目名可用 `XIAOMI_PROJECT` 环境变量覆盖。跑错目录会因缺配置直接报错，不会静默发到别的应用。

## 推荐发版流程

```bash
fvm flutter build apk --release
VD="${VASDOLLY_JAR:-$HOME/.claude/skills/vasdolly-multi-channel-apk/VasDolly.jar}"
[ -f "$VD" ] || VD=.agents/skills/vasdolly-multi-channel-apk/VasDolly.jar
mkdir -p build/app/outputs/channels/
java -jar "$VD" put -c xiaomi \
  build/app/outputs/flutter-apk/app-release.apk \
  build/app/outputs/channels/xiaomi-app-release.apk
```

先验证配置和包名：

```bash
python3 "$SKILL_DIR/scripts/xiaomi_publish.py" query
```

提交 APK 更新：

```bash
PY="$SKILL_DIR/scripts/xiaomi_publish.py"
python3 "$PY" push \
  --apk build/app/outputs/channels/xiaomi-app-release.apk \
  --synchro-type 1 \
  --update-desc "修复若干问题，优化使用体验。"
```

版本更新内容记录在 `docs/发布版本更新日志.md`。发版前从对应版本的“商店更新说明”复制到 `--update-desc`，不要写进凭据配置文件。

如需先看签名参数、避免真实提交：

```bash
python3 "$PY" push --apk build/app/outputs/channels/xiaomi-app-release.apk \
  --synchro-type 1 --update-desc "修复若干问题，优化使用体验。" --dry-run
```

## 子命令

| 命令 | 用途 |
|---|---|
| `doctor` | 自检凭据、证书、产物与线上版本；缺凭据也不报错，只列缺哪几项 |
| `category` | 查询小米应用分类；无需凭据 |
| `query` | 按包名查询当前账号下应用详情 |
| `push` | 提交新增、更新包、内容更新；`0=新增`、`1=更新包`、`2=内容更新` |
| `push-channel-apk` | 向在架普通应用补充渠道包 |

## 注意事项

- 小米没有开放沙盒环境；不加 `--dry-run` 的 `push` / `push-channel-apk` 会真实提交。
- 2026-02-04 起，`testAccount` 必须使用新版结构化 JSON 字符串，旧字符串格式会被拒绝。
- 更新包通常只需传 APK 和更新说明；新增应用需要 icon、截图、分类、简介、隐私政策等完整信息。
- 官方暂未开放审核状态查询接口；提交成功后需要在开放平台页面查看和撤回。
- 若接口返回非 0，先查 [reference.md](reference.md) 的错误码，再检查 `RequestData` JSON、文件 MD5、证书和私钥。
