---
name: publish-app-lenovo
description: Upload and submit updates for an existing Android app in Lenovo Open Platform through its current Chrome update flow, or query 联想上架/审核状态 read-only via the console's own API. Use for future Lenovo App Market version updates and for checking whether a version is 已上架 / 审核中, not new-app creation or package ownership claims.
---

# 联想应用市场发版

> 本文中形如 `docs/发布版本更新日志.md`、`docs/应用发布平台清单.md` 的路径，指的是**调用方项目**仓库里的文档（相对项目根），不是本 skill 目录里的文件；各项目按自己的约定放置即可。

通过已登录的 Chrome 会话，为联想开放平台中已存在的目标应用上传 `lenovo` 渠道 APK 并提交版本审核。联想没有开发者可用的官方发版 API，始终以实时页面为准。

## 适用范围

- 控制台：`https://open.lenovomm.com/developer/mgmt`
- 应用：`LENOVO_APP_NAME`（每次都在控制台应用列表里用应用名和包名交叉确认目标）
- 包名：`LENOVO_PACKAGE_NAME`（即调用方项目的 applicationId）
- 渠道：`lenovo`
- 渠道包：`build/app/outputs/channels/lenovo-app-release.apk`
- 更新说明来源：`docs/发布版本更新日志.md`
- 发布状态清单：`docs/应用发布平台清单.md`
- 实测页面合同：[references/workflow.md](references/workflow.md)

上面的 `LENOVO_*` 取自**调用方项目**的配置，不写进本 skill：

```bash
# 在目标项目仓库里执行；<项目名> 即 git 根目录名
mkdir -p ~/.config/ai-ignore-config/<项目名>
cp "$SKILL_DIR/config.example.env" ~/.config/ai-ignore-config/<项目名>/lenovo.env
```

读不到就停下来问，不要拿别的应用的值顶上。登录密码、验证码不进配置，由发布人在浏览器里手动完成。

仅适用于管理中心已经显示该应用且操作列提供“更新”的场景。不要点“创建”，也不要在已有应用更新流程中改走“应用认领”。若列表显示本地相同版本已经审核中或已上架，停止，不重复上传或提交。

## 0. 实时状态查询（只读，不必走完整发版流程）

只想知道某版本上架到哪一步时用这一节，**不要**为了查状态去点页面读 DOM。

做法：在 Chrome 里打开 `https://open.lenovomm.com/developer/mgmt`（已登录），
用 `javascript_tool` 在该标签页执行下面这段。

```js
const r = await fetch('/developerService/android/app/list', {
  method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ pageNo: 1, pageSize: 50 })
});
if (r.redirected || !(r.headers.get('content-type')||'').includes('json')) { 'SESSION_EXPIRED'; }
const j = await r.json();
const page = j.data || {};
const KEEP = ['appName','packageName','versionName','versionCode','onShelfLatestVersion',
              'state','appSource','submitDate','submitId'];
const rows = (page.records || []).map(o => Object.fromEntries(KEEP.map(k => [k, o[k]])));
JSON.stringify({ status: j.status, total: page.total, count: rows.length, rows });
```

**`data` 是 MyBatis-Plus 分页对象 `{records,total,size,current,pages,...}`，不是裸数组**，
行在 `data.records[]`。把 `j.data` 当数组会静默拿到 0 行——这一条踩过，别用
`j.data.list||j.data.records||j.data` 之类的回退链去糊，回退链会掩盖真实契约。

**返回值必须白名单裁剪**（上面的 `KEEP`），否则会被 Chrome 扩展拦成
`[BLOCKED: Cookie/query string data]`。

判定口径（2026-09-02 实测）：

| 字段 | 含义 |
| --- | --- |
| `onShelfLatestVersion` | **在架版本，判定已上架以此为准** |
| `versionName` / `versionCode` | 最近一次提交的版本 |
| `state` | `5` 对应页面「已上架」；完整码表未知 |
| `appSource` | `1` 对应页面「该版本来自合作渠道」 |

`state` 只实测到 `5` 这一个取值，**不要单凭它判定**；以 `onShelfLatestVersion` 是否等于
目标版本为准。遇到新码值补记到本节。

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

使用页面可见的文件上传入口选择 `lenovo-app-release.apk`，等待平台解析完成后重新核对应用名、包名、版本名和 versionCode。解析失败或不一致时停止，不尝试手改页面返回的版本字段。

更新说明仅复制本次版本的 Android 简体中文“商店更新说明”；不要新增仓库和当前页面都没有依据的功能、隐私或安全声明。合规问卷、定时发布、控量和其他新出现的声明以实时原文为准，需分别取得用户确认。

“提交审核”会创建实际审核记录。点击前再次核对解析版本、完整更新说明及发布设置，并取得用户明确提交确认。提交后通过应用列表的新版本和“审核中”或平台等效状态验证结果；审核通过前不得标为上架。

## 4. 收尾

记录实际页面入口、字段限制和可靠状态信号到 `references/workflow.md`；更新 `docs/应用发布平台清单.md` 与任务证据。只暂存本次发布相关的 skill、工作流、证据和文档。
