---
name: publish-app-baidu
description: Prepare and publish Android APK updates to the Baidu App Open Platform through Chrome, or query 百度上架/审核状态与驳回原因 read-only via the console's own API. Use when working with 百度应用开放平台 or 百度移动应用平台, uploading a baidu VasDolly channel APK, checking whether a version is 已上线 / 审核中 / 未通过, reading the 未通过原因 rejectReason text, reading parsed package/version or audit status, updating release notes, answering Baidu AI compliance fields, or submitting an app update for review.
---

# 百度应用市场发版

> 本文中形如 `docs/发布版本更新日志.md`、`docs/应用发布平台清单.md` 的路径，指的是**调用方项目**仓库里的文档（相对项目根），不是本 skill 目录里的文件；各项目按自己的约定放置即可。

通过 Chrome 为目标应用更新百度渠道 APK、合规资料并提交审核。百度没有官方发布 API；只使用实时控制台，不编写或伪造上传 API。

## 固定合同

- 控制台：`https://app.baidu.com/newapp/index`
- 应用列表：`https://app.baidu.com/newapp/apps/list`
- 导航：应用分发 → 应用发布 → 应用列表
- 应用：`BAIDU_APP_NAME`（每次都在控制台应用列表里用应用名和包名交叉确认目标）
- 包名：`BAIDU_PACKAGE_NAME`（即调用方项目的 applicationId）
- 渠道：`baidu`
- 默认 APK：`build/app/outputs/channels/baidu-app-release.apk`
- 更新说明来源：`docs/发布版本更新日志.md`
- 发布状态清单：`docs/应用发布平台清单.md`
- 实测浏览器路由与字段约束：`references/workflow.md`

上面的 `BAIDU_*` 取自**调用方项目**的配置，不写进本 skill：

```bash
# 在目标项目仓库里执行；<项目名> 即 git 根目录名
mkdir -p ~/.config/ai-ignore-config/<项目名>
cp "$SKILL_DIR/config.example.env" ~/.config/ai-ignore-config/<项目名>/baidu.env
```

读不到就停下来问，不要拿别的应用的值顶上。登录密码、验证码不进配置，由发布人在浏览器里手动完成。

不要固化历史 tab、详情 URL、APPID、下载地址、控件顺序、版本或摘要。每次都读取本地产物和实时页面。

## 0. 实时状态查询（只读，不必走完整发版流程）

只想知道某版本上架到哪一步、或想读驳回原因时用这一节。**驳回原因在页面上藏在状态列图标的
弹出抽屉里，`get_page_text` 读不到**，只有走接口或截图才拿得到——这也是本节存在的主要理由。

做法：在 Chrome 里打开 `https://app.baidu.com/newapp/apps/list`（已登录），
用 `javascript_tool` 在该标签页执行下面这段。

```js
const PATH = 'passauth/GET/AppCenterPackageService/getAppPackageList';
const reqid = crypto.randomUUID();
const form = new URLSearchParams({
  optid: '-1',
  params: JSON.stringify({ pageNo: 1, pageSize: 20, type: 2, filters: [] }),
  path: PATH,
  reqid,
  token: '',                                   // 平台就是传空串，不要试图找 token
  userid: String(window.__app_pass_id || '')   // userid 来源
});
const r = await fetch('/hairuo/request.ajax?path=' + encodeURIComponent(PATH) + '&reqid=' + reqid, {
  method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' }, body: form.toString()
});
if (!(r.headers.get('content-type')||'').includes('json')) { 'SESSION_EXPIRED'; }
const j = await r.json();
const KEEP = ['appId','appName','packageName','packageVersion','state',
              'onlineState','rejectReason','updateTime','isCommit'];
const rows = ((j.data && j.data.appList) || []).map(o => Object.fromEntries(KEEP.map(k => [k, o[k]])));
JSON.stringify({ total: j.data && j.data.totalCount, rows });
```

关于这几个参数（2026-09-02 实测）：

- `token` **实际是空字符串**——参数存在但不带值，百度靠 cookie 认证，别去翻 localStorage 找 token。
- `userid` === `window.__app_pass_id`（已用 SHA-256 比对确认）。
- `optid` 固定 `-1`；`reqid` 每次用 `crypto.randomUUID()` 新生成。

**返回值必须白名单裁剪**（上面的 `KEEP`）。行内有 `packageUrl` / `icons` / `appScreenshots`
等大量含 URL 的字段，整包回传必被 Chrome 扩展拦成 `[BLOCKED: Cookie/query string data]`。

判定口径：

| 字段 | 含义 |
| --- | --- |
| `rejectReason` | **非空即被驳回，原文就是审核意见**；重新提交通过后会被清空 |
| `state` | `900` = 未通过、`100` = 已上线（2026-09-02 两个取值都实测到）；完整码表仍未知 |
| `onlineState` | 在架状态：`1` = 已上线、`2` = 未在架 |
| `packageVersion` | 最近一次提交的版本名 |

判定优先看 `rejectReason` 是否非空，其次才是 `state` / `onlineState`。遇到新码值补记到本节。

会话失效信号：页面跳 `passport.baidu.com`，或响应不是 JSON。
此时**请用户在该标签页自行登录**后重试，不读取、不填写、不记录任何凭据。

## 1. 预检本地 APK

先运行 `git status --short`。工作树有未提交改动时，优先复用同版本已验证的渠道包，不无依据重建或覆盖产物；若必须重建，先展示可能进入安装包的改动并取得明确确认。

仅在目标渠道包缺失且发布源状态已确认时，使用项目 FVM 和 VasDolly 生成：

```bash
VD="${VASDOLLY_JAR:-$HOME/.claude/skills/vasdolly-multi-channel-apk/VasDolly.jar}"
[ -f "$VD" ] || VD=.agents/skills/vasdolly-multi-channel-apk/VasDolly.jar
fvm flutter build apk --release
mkdir -p build/app/outputs/channels
java -jar "$VD" put -c baidu \
  build/app/outputs/flutter-apk/app-release.apk \
  build/app/outputs/channels/baidu-app-release.apk
```

上传前解析并记录绝对路径及以下合同：

```bash
VD="${VASDOLLY_JAR:-$HOME/.claude/skills/vasdolly-multi-channel-apk/VasDolly.jar}"
[ -f "$VD" ] || VD=.agents/skills/vasdolly-multi-channel-apk/VasDolly.jar
shasum -a 256 build/app/outputs/channels/baidu-app-release.apk
java -jar "$VD" get -c \
  build/app/outputs/channels/baidu-app-release.apk
java -jar "$VD" get -s \
  build/app/outputs/channels/baidu-app-release.apk
aapt dump badging build/app/outputs/channels/baidu-app-release.apk
apksigner verify --verbose --print-certs \
  build/app/outputs/channels/baidu-app-release.apk
```

若 `aapt` 或 `apksigner` 不在 `PATH`，使用本机 Android SDK 已安装 build-tools 中的对应可执行文件。核对应用名、包名、版本名、版本号、`baidu` 渠道、签名方案和签名证书；证书应与可信历史发布包或已验证发布证书一致。任何字段缺失或不一致都停止。

## 2. 读取实时状态

使用 `chrome:control-chrome` 复用用户已登录的 Chrome 会话进入固定入口。登录、验证码、二次验证、测试账号和证件资料均交给用户亲自处理；不要读取、复制、记录或复述账号、密码、验证码、证件号及其他敏感字段。

从实时导航进入应用列表，用配置里的应用名和包名交叉确认目标。先读取当前线上版本、审核状态和版本管理记录：

- 同版本已审核中、已上线或已有记录时停止，不重复上传或提交。
- 本地版本不高于线上版本时停止并核查版本合同。
- 目标应用、页面语义或实时状态不明确时停止，不猜测历史 ID 或选择器。

## 3. 上传 APK

上传是独立的对外传输动作。操作前展示目标站点、APK 绝对路径、SHA-256、应用名、包名、版本名、版本号、渠道和签名核验结果；只有用户明确确认上传后才继续。

更新页已有旧包时，在实时 DOM 和可见界面中确认删除控件紧邻旧包链接，再清除该表单项，使可见“文件上传”按钮可用。不要按历史位置盲点删除控件。
本次上传确认只授权清空当前更新表单中的旧包字段；若实时提示该动作会删除已保存记录、线上安装包或产生其他独立影响，立即停止并为该影响取得新确认。

使用 Chrome 文件选择器上传：

1. 先监听 `filechooser`。
2. 点击可见“文件上传”按钮。
3. 对捕获的文件选择器调用 `setFiles`，传入已确认的 APK 绝对路径。
4. 等待上传完成并重新读取页面。

不要直接操作隐藏的 `input[type=file]`。上传后核对平台解析的应用名、包名、版本名和页面提供的版本号；任一不一致都停止，不填写合规声明、不提交审核。

## 4. 更新版本资料

从 `docs/发布版本更新日志.md` 读取对应版本的 Android 简体中文更新说明。按百度页面口径控制在 500 字节内，其中汉字按 2 字节计算；压缩时保留真实功能信息，不编造功能、隐私、安全或合规承诺。填写后重新读取文本和页面校验结果。

只更新当前版本要求的字段。保留已有分类、简介、标签、图标、截图、资质、隐私政策、测试资料和其他商店材料，除非用户明确要求变更。页面若没有独立保存草稿能力，不得用“提交审核”代替保存。

## 5. 如实填写 AI 合规

以当前代码和用户可见产品能力为依据，不沿用页面默认值：

- 应用存在 AI 生成能力时选“是”，再选择真实生成类型；仅按当前产品的真实证据选择，不要沿用别的应用的历史答案。
- AI 文本能力需要平台要求的真实证明图片。图片必须来自真实产品界面并带可核验的 AI 生成标识；缺失时暂停并向用户索取，不得伪造、加工或改填“否”绕过。
- “AI 生成内容下载”把下载、复制、导出都视为可带出能力；逐项核查，只要实际支持其中一项就如实选择。
- “AI 内容传播平台”按是否允许向其他用户或公开范围传播 AI 内容独立判断，不能由“可下载”或页面默认值代替。

上传 AI 证明图片前，展示真实能力判断、图片绝对路径和拟选字段，并取得明确确认。无法用证据判断时暂停。

## 6. 合规和法务闸门

风险 SDK 自查、隐私承诺、新法律协议或类似勾选均属于有法律含义的声明。勾选或接受前，读取实时声明原文，向用户展示拟选择内容及依据，并取得明确确认。不要代表用户推断同意，也不要保存页面中的敏感材料。

## 7. 最终提交

“提交审核”是独立的最终动作，不能沿用上传或合规确认。点击前重新展示：

- 平台解析的应用名、包名、版本名和版本号
- 完整更新说明及百度口径字节数
- AI 生成类型、下载能力、传播平台判断和证明图片
- 风险 SDK、隐私及法律声明状态
- 当前线上版本、重复版本检查和预期状态变化

只有用户在看到该摘要后明确要求“提交审核”才点击最终按钮。仅保存、上传、继续或先看看都不构成最终提交授权。

同时看到页面“提交成功”和应用列表中新版本“审核中”，才报告提交成功。任一信号缺失时保留页面并报告实际状态，不猜测结果。

## 8. 收尾与其他破坏性动作

提交后更新 `docs/应用发布平台清单.md` 中百度行的版本、渠道包和上传/审核中状态；审核通过前不要勾选“审核通过”。

撤回审核、删除记录、替换已上传包、下线版本或其他会改变现有状态的动作，都必须展示精确目标和影响并分别取得新确认。一次确认只授权一个明确动作。

Git 暂存只包含本次发布 Skill、发布文档和任务文件，不纳入用户已有的无关改动。
