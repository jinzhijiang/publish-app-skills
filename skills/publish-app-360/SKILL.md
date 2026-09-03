---
name: publish-app-360
description: Prepare and publish Android APK updates to the 360 Mobile Open Platform through Chrome, or query 360 上架/审核状态 read-only via the console's own API. Use when uploading c360 VasDolly channel APKs, updating 360 store release notes or release settings, checking whether a version is 已上线 / 审核中 / 未通过, reading parsed package/version or audit status, or automating the dev.360.cn browser workflow for 360 应用市场.
---

# 360 应用市场发版

> 本文中形如 `docs/发布版本更新日志.md`、`docs/应用发布平台清单.md` 的路径，指的是**调用方项目**仓库里的文档（相对项目根），不是本 skill 目录里的文件；各项目按自己的约定放置即可。

通过 Chrome 为目标应用上传 `c360` 渠道 APK、填写更新说明并提交 360 审核。360 没有官方发版 API，必须以实时控制台页面为准。

## 固定入口

- 控制台：`https://dev.360.cn/mod3/mobile/applist`
- 应用：`C360_APP_NAME`（每次都在控制台应用列表里用应用名和包名交叉确认目标）
- AppID：`C360_APP_ID`（首次跑通后填进配置；**每次仍需用应用名和包名交叉确认**，不要当固定入口用）
- 包名：`C360_PACKAGE_NAME`（即调用方项目的 applicationId）
- 渠道名：`c360`
- 实测页面、字段和选择器：[references/workflow.md](references/workflow.md)
- 更新说明唯一来源：`docs/发布版本更新日志.md`
- 平台能力与渠道定义：`docs/应用发布平台清单.md`

上面的 `C360_*` 取自**调用方项目**的配置，不写进本 skill：

```bash
# 在目标项目仓库里执行；<项目名> 即 git 根目录名
mkdir -p ~/.config/ai-ignore-config/<项目名>
cp "$SKILL_DIR/config.example.env" ~/.config/ai-ignore-config/<项目名>/360.env
```

读不到就停下来问，不要拿别的应用的值顶上。登录密码、验证码不进配置，由发布人在浏览器里手动完成。

## 0. 实时状态查询（只读，不必走完整发版流程）

只想知道某版本上架到哪一步时用这一节，**不要**为了查状态去点页面读 DOM。

做法：在 Chrome 里打开 `https://dev.360.cn/mod3/mobile/applist`（已登录），
用 `javascript_tool` 在该标签页执行下面这段，一次调用出结果。

```js
const r = await fetch('/mod3/mobile/Newgetappinfopage?page=1&page_size=50&cate1=&condition=');
if (!(r.headers.get('content-type')||'').includes('json')) { 'SESSION_EXPIRED (non-json)'; }
const j = await r.json();
if (String(j.errno) !== '0') { 'SESSION_EXPIRED or API error: errno=' + j.errno; }
const KEEP = ['appid','appname','pname','version','status','lifestatus','comtest_status','updatetime'];
const rows = ((j.data && j.data.list) || []).map(o => Object.fromEntries(KEEP.map(k => [k, o[k]])));
JSON.stringify({ errno: j.errno, count: j.data && j.data.count, rows });
```

**返回值必须白名单裁剪**（上面的 `KEEP`）。整包回传会因为含 URL / 查询串被 Chrome 扩展拦成
`[BLOCKED: Cookie/query string data]`；用黑名单过滤也不行——平台新增带 URL 的字段就会突然失效。

判定口径（2026-09-02 实测）：

| 字段 | 含义 |
| --- | --- |
| `version` | 线上 versionCode，与本次包的 versionCode 相等即已上线 |
| `status` | `VERIFY_SUCC` = 审核通过 |
| `lifestatus` | `NORMAL` = 正常在架 |
| `comtest_status` | 安检状态 |

只实测到上述取值，**完整码表未知**。判定以 `version` 是否等于目标 versionCode 为准，
不要反过来猜 `status` 的其他码值；遇到新码值补记到本节。

辅助接口，只给线上版本号、不给状态，适合快速比对：

```
GET https://dev.360.cn/mod3/mobile/versions?pnames=<包名>
→ {"errno":"0","data":{"<包名>":"30007"}}
```

会话失效信号：响应不是 JSON，或 `errno != 0`。此时**请用户在该标签页自行登录**后重试，
不读取、不填写、不记录任何凭据。

## 1. 本地包预检

优先复用同一版本已构建的干净 Release APK；工作树有未提交改动时，不要无依据地重建或覆盖现有发布包。

目标文件：

```text
build/app/outputs/channels/c360-app-release.apk
```

若渠道包不存在，先按项目 FVM 和 VasDolly 约定生成：

```bash
VD="${VASDOLLY_JAR:-$HOME/.claude/skills/vasdolly-multi-channel-apk/VasDolly.jar}"
[ -f "$VD" ] || VD=.agents/skills/vasdolly-multi-channel-apk/VasDolly.jar
fvm flutter build apk --release
mkdir -p build/app/outputs/channels
java -jar "$VD" put -c c360 \
  build/app/outputs/flutter-apk/app-release.apk \
  build/app/outputs/channels/c360-app-release.apk
```

上传前必须记录并核对：

```bash
# Android SDK 工具取版本号最大的一份，不写死 build-tools 版本
sdk_tool() { ls "${ANDROID_HOME:-$HOME/Library/Android/sdk}"/build-tools/*/"$1" 2>/dev/null | sort -V | tail -1; }
VD="${VASDOLLY_JAR:-$HOME/.claude/skills/vasdolly-multi-channel-apk/VasDolly.jar}"
[ -f "$VD" ] || VD=.agents/skills/vasdolly-multi-channel-apk/VasDolly.jar
shasum -a 256 build/app/outputs/channels/c360-app-release.apk
java -jar "$VD" get -c \
  build/app/outputs/channels/c360-app-release.apk
java -jar "$VD" get -s \
  build/app/outputs/channels/c360-app-release.apk
"$(sdk_tool aapt)" dump badging \
  build/app/outputs/channels/c360-app-release.apk
"$(sdk_tool apksigner)" verify --verbose --print-certs \
  build/app/outputs/channels/c360-app-release.apk
```

确认包名、版本名、版本号、`c360` 渠道和签名全部正确；任一不一致都停止。

## 2. 登录并读取实时状态

使用用户指定的 Chrome 会话进入应用列表。登录凭据、验证码、二次验证和协议勾选由用户在 Chrome 中完成，不读取、不记录。

在应用列表中用配置里的应用名和包名交叉确认目标，再记录当前线上版本、状态和安检结果并打开“更新应用信息”。不要依赖历史 `qid`、直达 URL、版本状态或日期。

将实时版本号与本地 APK 比较；本地版本不高于线上版本、同版本已在审核中或已上线时停止，不重复上传或提交。

## 3. 上传 APK

上传是独立对外传输动作。操作前展示目标站点、APK 绝对路径、SHA-256、包名、版本和渠道，并取得明确确认。

浏览器上传遵循 Chrome 文件选择器流程：

1. 先监听 `filechooser`
2. 点击可见 APK 上传容器 `#uploadapk_btn`
3. 传入 APK 绝对路径
4. 等待“上传中...”消失

不要反复点击隐藏的 `input[type=file]`。若 Chrome 无法读取本地文件，请用户在 ChatGPT Chrome Extension 详情中开启“允许访问文件网址”，然后重新接管原表单。

上传完成后逐项核对 360 解析出的应用名称、包名、版本名和版本号；任何不一致都停止。

## 4. 填写版本资料

- 保留已有分类、标签、简介、隐私政策、图标、截图和审核辅助说明。
- “当前版本介绍”复制对应版本 Android 简体中文“商店更新说明”，限制 10–400 字符。
- 不新增仓库没有依据的功能、隐私或安全声明。
- 保留已有发布时间和控量设置，除非用户明确要求变更。
- 实时页面若提供独立“保存草稿”功能，可以保存并重新读取验证；若没有，不要用“提交审核”代替保存。
- 定时发布或控量设置发生变化时，在应用该变化前单独确认。

## 5. 合规与提交门槛

风险 SDK 自查是合规声明。勾选前明确展示声明内容，并取得用户确认。

“提交审核”是独立最终动作，点击前再次展示：

- APK 解析后的包名和版本
- 完整更新说明及长度
- 发布时间
- 是否控量
- 风险 SDK 声明确认状态

只有用户明确说“提交审核”后才能点击。提交成功的可靠信号是新版本显示“审核中”、安检显示“检测中”，并出现“撤销审核”入口。

“撤销审核”会改变已创建的审核记录，必须在点击前单独确认。

## 6. 收尾

提交后更新：

- `references/workflow.md`：记录新发现的页面路径、字段限制和可靠状态信号
- `docs/应用发布平台清单.md`：勾选版本、渠道包、上传状态；审核通过前不要勾选“审核通过”

Git 暂存只包含本次 skill、发布文档和任务文件，不纳入用户已有的无关改动。
