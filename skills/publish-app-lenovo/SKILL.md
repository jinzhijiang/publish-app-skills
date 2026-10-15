---
name: publish-app-lenovo
description: Create new apps (首次上架) and upload/submit updates in Lenovo Open Platform by driving the user's main Chrome with opencli, or query 联想上架/审核状态 read-only via the console's own API. Use for Lenovo App Market first launches, version updates, filling the 联想承诺函 / 著作权 / 分类标签 fields, and checking whether a version is 未提交 / 上架审核中 / 已上架; not for package ownership claims (应用认领).
---

# 联想应用市场发版

> 本文中形如 `docs/发布版本更新日志.md`、`docs/应用发布平台清单.md` 的路径，指的是**调用方项目**仓库里的文档（相对项目根），不是本 skill 目录里的文件；各项目按自己的约定放置即可。

通过 opencli 驱动用户的主 Chrome，在联想开放平台为目标应用首次上架，或为已存在的应用上传 `lenovo` 渠道 APK 并提交版本审核。联想没有开发者可用的官方发版 API，始终以实时页面为准。

## 适用范围

- 控制台：`https://open.lenovomm.com/developer/mgmt`
- 应用：`LENOVO_APP_NAME`（每次都在控制台应用列表里用应用名和包名交叉确认目标）
- 包名：`LENOVO_PACKAGE_NAME`（即调用方项目的 applicationId）
- 渠道：`lenovo`
- 渠道包：`build/app/outputs/channels/lenovo-app-release.apk`
- 更新说明来源：`docs/发布版本更新日志.md`
- 发布状态清单：`docs/应用发布平台清单.md`
- 实测页面合同：[references/workflow.md](references/workflow.md)
- 首次上架（创建应用表单契约、opencli 自动化的坑）：[references/first-launch.md](references/first-launch.md)

上面的 `LENOVO_*` 取自**调用方项目**的配置，不写进本 skill：

```bash
# 在目标项目仓库里执行；<项目名> 即 git 根目录名
mkdir -p ~/.config/ai-ignore-config/<项目名>
cp "$SKILL_DIR/config.example.env" ~/.config/ai-ignore-config/<项目名>/lenovo.env
```

读不到就停下来问，不要拿别的应用的值顶上。登录密码、验证码不进配置，由发布人在浏览器里手动完成。

- 列表里已有目标包名且操作列有「更新」：走版本更新（§ 2–3）。不要点「创建」，也不要改走「应用认领」。
- 列表里没有目标包名：走首次上架，按 [references/first-launch.md](references/first-launch.md) 从「创建」进入。
- 列表里有目标包名但状态是「未提交」：这是自己保存过的首发草稿，点「完善信息」继续，不要再建一个。
- 本地相同版本已经审核中或已上架：停止，不重复上传或提交。

## 浏览器驱动：只用 opencli

首次上架和版本更新都用 opencli 驱动用户自己的主 Chrome，不用 chrome-devtools MCP 或 Claude in Chrome
（主 Chrome 有发布人的登录态、没有自动化标记）。会话名下文用 `lenovo`；`CFU` 指 `chrome-file-upload` skill 目录
（部署后是 `~/.claude/skills/chrome-file-upload`）。

```bash
opencli doctor                                   # 需要 Extension: connected
opencli browser lenovo open https://open.lenovomm.com/developer/mgmt
```

- **页面脚本**：`opencli browser lenovo eval '<IIFE>'`，返回 JSON 字符串；async IIFE 会等结果。
- **上传**：一律 `chrome-file-upload` 分块注入（`opencli browser upload` 对 antd 隐藏 input 弹不出文件选择框）。
- **分类 / 标签下拉**：antd Select 点选项不生效，用 first-launch.md 里调组件 `onChange` 的做法，选完核对显示文字。
- **保活**：等发布人操作期间后台起 `"$CFU/scripts/opencli_keepalive.sh" lenovo 60 &`，没保存的表单约 45 秒空闲就会随标签页丢失。
- **偶发 `attach_failed`**：别的扩展插了 iframe，隔 3 秒重试。
- 收尾 `opencli browser lenovo close` 释放标签页。

## 0. 实时状态查询（只读，不必走完整发版流程）

只想知道某版本上架到哪一步时用这一节，**不要**为了查状态去点页面读 DOM。

做法：`opencli browser lenovo open https://open.lenovomm.com/developer/mgmt`（已登录），再执行：

```bash
opencli browser lenovo eval "(async () => {
  const r = await fetch('/developerService/android/app/list', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ pageNo: 1, pageSize: 50 })
  });
  if (r.redirected || !(r.headers.get('content-type') || '').includes('json')) return 'SESSION_EXPIRED';
  const j = await r.json();
  const page = j.data || {};
  const KEEP = ['appName', 'packageName', 'versionName', 'versionCode', 'onShelfLatestVersion',
                'state', 'appSource', 'submitDate', 'submitId'];
  const rows = (page.records || []).map(o => Object.fromEntries(KEEP.map(k => [k, o[k]])));
  return JSON.stringify({ status: j.status, total: page.total, count: rows.length, rows });
})()"
```

**`data` 是 MyBatis-Plus 分页对象 `{records,total,size,current,pages,...}`，不是裸数组**，
行在 `data.records[]`。把 `j.data` 当数组会静默拿到 0 行——这一条踩过，别用
`j.data.list||j.data.records||j.data` 之类的回退链去糊，回退链会掩盖真实契约。

**返回值必须白名单裁剪**（上面的 `KEEP`），否则会被 Chrome 扩展拦成
`[BLOCKED: Cookie/query string data]`。

判定口径：

| 字段 | 含义 |
| --- | --- |
| `onShelfLatestVersion` | **在架版本，判定已上架以此为准** |
| `versionName` / `versionCode` | 最近一次提交的版本；首发草稿时为 `null` |
| `state` | `0` = 未提交（首发草稿，2026-10-15）、`1` = 提交中 / 上架审核中（2026-10-14、10-15）、`5` = 已上架（2026-09-02）；完整码表未知 |
| `appSource` | `1` = 合作渠道同步（页面标「该版本来自合作渠道」）、`2` = 自主上传 |
| `submitDate` | 首发时是草稿第一次保存的时间，提交后不更新 |

判定上架**不要单凭 `state`**，以 `onShelfLatestVersion` 是否等于目标版本为准。遇到新码值补记到本节。

会话失效信号：HTTP 302 跳登录页，或响应不是 JSON。此时**请用户在该标签页自行登录**后重试，
不读取、不填写、不记录任何凭据。

## 1. 预检 APK

先运行 `git status --short`。工作树有改动时，优先复用同版本已有渠道包；除非用户明确要求，不重新构建或覆盖发布产物。

若渠道包不存在，使用项目 FVM 与 VasDolly 合同生成：

```bash
VD="${VASDOLLY_JAR:-$HOME/.claude/skills/vasdolly-multi-channel-apk/VasDolly.jar}"
[ -f "$VD" ] || VD=.agents/skills/vasdolly-multi-channel-apk/VasDolly.jar
fvm flutter build apk --release
java -jar "$VD" put -c lenovo \
  build/app/outputs/flutter-apk/app-release.apk \
  build/app/outputs/channels/
```

上传前核对：

```bash
VD="${VASDOLLY_JAR:-$HOME/.claude/skills/vasdolly-multi-channel-apk/VasDolly.jar}"
[ -f "$VD" ] || VD=.agents/skills/vasdolly-multi-channel-apk/VasDolly.jar
shasum -a 256 build/app/outputs/channels/lenovo-app-release.apk
java -jar "$VD" get -c \
  build/app/outputs/channels/lenovo-app-release.apk
aapt dump badging build/app/outputs/channels/lenovo-app-release.apk
apksigner verify --verbose --print-certs \
  build/app/outputs/channels/lenovo-app-release.apk
```

确认应用名、包名、版本名、versionCode、渠道 `lenovo` 和签名均正确，且版本高于控制台当前版本；任一不一致都停止。
若 `aapt` 或 `apksigner` 不在 `PATH`，使用本机 Android SDK 已安装 build-tools 中的对应可执行文件。

## 2. 从既有应用进入更新

1. 在管理中心的 Phone/Pad 应用列表中，以配置里的应用名和包名交叉确认目标。
2. 读取当前版本、提交时间和状态。
3. 仅在本地版本更高时点击该行“更新”。
4. 保留既有分类、图标、截图、隐私政策、版权与应用资料，除非本次发布有证据要求更新。

登录、验证码、二次验证、账号资料和测试凭据由用户在 Chrome 中处理。不要读取、复制、记录或导出浏览器 Cookie、令牌、动态上传地址、请求头或会话信息，也不要把页面网络请求当作可复用 API。

## 3. 上传与提交

上传是单独的对外传输动作。上传前展示目标站点、APK 绝对路径、SHA-256、包名、版本和渠道，并取得用户确认。

上传方式先切到实际要用的「单包 / 双包」，再给 APK 的 input 打标记，用 `chrome-file-upload` 注入：

```bash
python3 "$CFU/scripts/opencli_upload.py" --session lenovo --file "$APK" \
  --expect-url open.lenovomm.com --selector '[data-cfu="apk"]'
```

等平台解析完成（约 30 秒）后重新核对应用名、包名、版本名和 versionCode。解析失败或不一致时停止，不尝试手改页面返回的版本字段。

更新说明仅复制本次版本的 Android 简体中文“商店更新说明”；不要新增仓库和当前页面都没有依据的功能、隐私或安全声明。合规问卷、定时发布、控量和其他新出现的声明以实时原文为准，需分别取得用户确认。

“提交审核”会创建实际审核记录。点击前再次核对解析版本、完整更新说明及发布设置，并取得用户明确提交确认。提交后通过应用列表的新版本和“审核中”或平台等效状态验证结果；审核通过前不得标为上架。

## 4. 收尾

记录实际页面入口、字段限制和可靠状态信号到 `references/workflow.md`；更新 `docs/应用发布平台清单.md` 与任务证据。只暂存本次发布相关的 skill、工作流、证据和文档。
