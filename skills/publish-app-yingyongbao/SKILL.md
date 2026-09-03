---
name: publish-app-yingyongbao
description: Publish APK version updates to Tencent Yingyongbao (应用宝) via the open.qq.com Developer API (HmacSHA256 sign, COS pre-signed upload). Use when uploading yingyongbao channel APKs, automating 应用宝发版, API更新应用信息, open.qq.com publish, or querying Yingyongbao audit status.
disable-model-invocation: true
---

# 应用宝 APK 自动发布

> 本文中形如 `docs/发布版本更新日志.md`、`docs/应用发布平台清单.md` 的路径，指的是**调用方项目**仓库里的文档（相对项目根），不是本 skill 目录里的文件；各项目按自己的约定放置即可。

通过腾讯应用宝 **API更新应用信息** 接口提交已上架应用的 APK 版本更新，无需手动登录控制台上传。

官方文档：[wiki 4015262492](https://wikinew.open.qq.com/index.html#/iwiki/4015262492)  
详细 API / 错误码：[reference.md](reference.md)

## 何时使用

- 已构建 VasDolly 渠道包 `yingyongbao-app-release.apk`，需要提交到应用宝
- 用户提到应用宝、yingyongbao、open.qq.com、API 发版、自动上架
- 查询应用宝审核状态

## 前置条件

1. **主账号**（子账号不支持 API）
2. 应用**已在应用宝上架**（API 不支持新应用首发）
3. 在开放平台 **账户管理 → API发布接口** 申请开通，获取 `access_secret`
4. 在 **安卓应用管理 → 应用首页** 查看 `app_id` 与 `pkg_name`
5. 已安装 Python 3；脚本路径：`$SKILL_DIR/scripts/yingyongbao_publish.py`

## 凭据配置（多机 + 防 AI 读取）

**不要**把密钥写进会被 git 跟踪的文件，也**不要**在对话里粘贴 `access_secret`。

### 推荐：用户目录配置文件

每台电脑使用**同一路径**，用 iCloud / 1Password / 手动拷贝同步即可，无需 `export` 环境变量：

脚本按**目标项目的 git 根目录名**找配置（与 publish-app-huawei / countly-data-analysis 同一套约定），所以要**在目标项目仓库目录里执行**；`$SKILL_DIR` 指本 skill 目录。

```bash
mkdir -p ~/.config/ai-ignore-config/<项目名>
cp "$SKILL_DIR/config.example.env" \
   ~/.config/ai-ignore-config/<项目名>/yingyongbao.env
# 编辑 ~/.config/ai-ignore-config/<项目名>/yingyongbao.env
```

脚本默认按顺序查找：

1. `--config /path/to/file`（显式指定）
2. `~/.config/ai-ignore-config/<项目名>/yingyongbao.env`（**推荐**）
3. `$SKILL_DIR/config.env`（项目内备选）

项目名可用 `YINGYONGBAO_PROJECT` 环境变量覆盖。跑错目录会因缺配置直接报错，不会静默发到别的应用。

| 变量 | 说明 |
|---|---|
| `YINGYONGBAO_USER_ID` | 开放平台 UserID |
| `YINGYONGBAO_ACCESS_SECRET` | API 接入密钥 |
| `YINGYONGBAO_APP_ID` | 应用宝应用 ID |
| `YINGYONGBAO_PKG_NAME` | 包名（必填，调用方项目的 `applicationId`） |

### 为何 AI 通常读不到

| 机制 | 作用 |
|---|---|
| **`~/.config/...` 在仓库外** | Cursor 工作区一般只索引项目目录，用户目录下的密钥文件 Agent 默认访问不到 |
| **`.gitignore`** | 项目内的 `config.env` 不会进 git |
| **`.cursorignore`** | 项目内的 `config.env` 不会被 AI 索引进上下文 |

若必须在项目目录放密钥，只能用 skill 下的 `config.env`（已 gitignore + cursorignore），**仍不如 `~/.config` 安全**。

### 多机同步方式（任选）

- **1Password / Bitwarden**：每台机器从密码库复制到 `~/.config/ai-ignore-config/<项目名>/yingyongbao.env`
- **iCloud 同步**：把 `<项目名>` 文件夹放在 iCloud Drive，各机 symlink 到 `~/.config/ai-ignore-config/<项目名>`
- **仅本机**：只在常用开发机配置，发版时再操作

### 与 Agent 协作时注意

- 发版时说「用应用宝 skill 发版」，**不要**在聊天里贴密钥
- 若 Agent 报 `missing credentials`，自行在本地编辑配置文件，不要让 Agent「帮你填 key」
- **Cursor / Codex / Claude Code 通用**：密钥放 `~/.config/ai-ignore-config/<项目名>/`，由脚本读取；Agent 只执行 `python3 ... publish`，不要 `@` 引用或让 Agent 打开凭据文件

### 多 Agent 隔离（Cursor + Codex + Claude Code）

| 层级 | 作用 |
|---|---|
| **`~/.config/ai-ignore-config/<项目名>/yingyongbao.env`** | 仓库外，三端默认都碰不到（首选） |
| **`.gitignore`** | 项目内 `config.env` 不进 git |
| **`.cursorignore`** | Cursor 不索引项目内凭据 |
| **`.claude/settings.json`** | Claude Code `deny` 读凭据路径 |
| **`AGENTS.md` § Local Secrets** | Codex / Claude Code 读到的统一约定 |

无环境变量：每台机器只需维护同一路径下的文件，用 1Password / iCloud 同步内容即可。

## 推荐发版流程

```
Task Progress:
- [ ] fvm flutter build apk --release
- [ ] VasDolly 生成 yingyongbao 渠道包（见 vasdolly-multi-channel-apk skill）
- [ ] python3 ... query-detail   # 验证凭据
- [ ] python3 ... publish --feature "..." [--poll]
- [ ] 若驳回：python3 ... status 查看 audit_reason
```

### 1. 构建渠道包

```bash
fvm flutter build apk --release
VD="${VASDOLLY_JAR:-$HOME/.claude/skills/vasdolly-multi-channel-apk/VasDolly.jar}"
[ -f "$VD" ] || VD=.agents/skills/vasdolly-multi-channel-apk/VasDolly.jar
mkdir -p build/app/outputs/channels/
java -jar "$VD" put -c yingyongbao \
  build/app/outputs/flutter-apk/app-release.apk \
  build/app/outputs/channels/yingyongbao-app-release.apk
```

### 2. 验证凭据

```bash
python3 "$SKILL_DIR/scripts/yingyongbao_publish.py" query-detail
```

### 3. 一键发版

```bash
PY="$SKILL_DIR/scripts/yingyongbao_publish.py"
python3 "$PY" publish \
  --apk build/app/outputs/channels/yingyongbao-app-release.apk \
  --feature "2.1.11 修复若干问题" \
  --poll
```

`--poll` 每 30s 查询审核状态，直到通过/驳回/撤销或超时（默认 1h）。

### 4. 仅查审核状态

```bash
python3 "$PY" status
```

## 子命令速查

| 命令 | 用途 |
|---|---|
| `query-detail` | 查询当前应用详情 |
| `upload-file --type apk --file <path>` | 单文件上传到 COS，返回 serial_number |
| `update --apk64 <path> --feature "..."` | 上传 APK 并提交更新 |
| `status` | 查询最近一次更新的审核状态 |
| `publish --apk <path> --feature "..."` | 完整流程：查详情 → 上传 → 提交 |

全局选项 `--dry-run`：跳过实际上传/提交，打印将执行的参数（`query-detail` / `status` 仍会真实调用）。

## 常见错误

| 现象 | 处理 |
|---|---|
| `missing credentials` | 配置 `config.env` 或 export 环境变量 |
| ret=1000019 | 未申请 API 密钥，去控制台开通 |
| ret=1000020 | 签名错误，检查 access_secret 是否最新 |
| ret=1000011 | 应用未上架，API 仅支持更新 |
| ret=1000012 | 非主账号或无权限 |
| ret=4000053 | 审核提交失败，读 `msg`；常见为缺少测试账号、版本号未递增 |
| COS 上传超时 | 大包体增大 `--poll-timeout` 无关；上传超时在脚本内默认 300s |

## 注意事项

- **无沙盒环境**：`publish` 会真实提交审核；调试可用 `--dry-run`
- 审核中可在控制台撤回；API 不提供撤回接口
- 仅更新 APK 时不必重传 icon/截图/软著（字段留空 = 不变更）
- 64 位单包场景：`publish` 默认 `apk64_flag=1`；32/64 双包用 `update --apk32 ... --apk64 ...`
- 与本项目 VasDolly 渠道名 `yingyongbao` 对应，见 `android/channel.txt`

## 相关文档

- 手动控制台流程：[references/workflow.md](references/workflow.md)
- 平台总览：`docs/应用发布平台清单.md`
- 多渠道打包：[vasdolly-multi-channel-apk](../vasdolly-multi-channel-apk/SKILL.md)
