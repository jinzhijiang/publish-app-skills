---
name: publish-app-ali
description: Prepare and publish Android APK updates to the Ali App Distribution Open Platform through Chrome, or query 阿里上架/审核状态 read-only via the console's own API. Use when working with 阿里应用分发开放平台 or 九游开放平台, uploading an ali VasDolly channel APK, checking whether a version is 已上架 / 审核中, reading online or parsed package/version and audit status, updating release notes or APK MD5, handling risk SDK or legal declarations, or submitting an app update for review.
---

# 阿里应用分发发布

> 本文中形如 `docs/发布版本更新日志.md`、`docs/应用发布平台清单.md` 的路径，指的是**调用方项目**仓库里的文档（相对项目根），不是本 skill 目录里的文件；各项目按自己的约定放置即可。

通过 Chrome 为目标应用更新阿里渠道 APK 并提交审核。阿里没有官方发布 API；只使用实时控制台，不编写或伪造上传 API。

## 固定合同

- 控制台：`https://open.9game.cn/`
- 应用列表：`https://aliapp-open.9game.cn/app/mng/index`
- 软件发布入口：`https://aliapp-open.9game.cn/addapp`
- 应用：`ALI_APP_NAME`（每次都在控制台应用列表里用应用名和包名交叉确认目标）
- 包名：`ALI_PACKAGE_NAME`（即调用方项目的 applicationId）
- 渠道：`ali`
- 默认 APK：`build/app/outputs/channels/ali-app-release.apk`
- 更新说明来源：`docs/发布版本更新日志.md`
- 发布状态清单：`docs/应用发布平台清单.md`
- 实测浏览器路由与字段约束：`references/workflow.md`

上面的 `ALI_*` 取自**调用方项目**的配置，不写进本 skill：

```bash
# 在目标项目仓库里执行；<项目名> 即 git 根目录名
mkdir -p ~/.config/ai-ignore-config/<项目名>
cp "$SKILL_DIR/config.example.env" ~/.config/ai-ignore-config/<项目名>/ali.env
```

读不到就停下来问，不要拿别的应用的值顶上。登录密码、验证码不进配置，由发布人在浏览器里手动完成。

不要固化历史 tab、详情 URL、APPID、控件顺序、版本号或文件摘要。每次都读取本地产物和实时页面。

## 0. 实时状态查询（只读，不必走完整发版流程）

只想知道某版本上架到哪一步时用这一节，**不要**为了查状态去点页面读 DOM——
阿里控制台是 SPA，`get_page_text` 在渲染完成前会返回空壳。

做法：在 Chrome 里打开 `https://aliapp-open.9game.cn/app/mng/index`（已登录），
用 `javascript_tool` 在该标签页执行下面这段。

```js
const r = await fetch('/app/mng/packlist', {
  method: 'POST', headers: { 'X-Requested-With': 'XMLHttpRequest' }, body: ''
});
if (r.redirected || !(r.headers.get('content-type')||'').includes('json')) { 'SESSION_EXPIRED'; }
const j = await r.json();
if (j.success !== true) { 'SESSION_EXPIRED or API error'; }
const KEEP = ['appId','appName','packName','versionName','auditStatus',
              'isOnline','isPushed','isOffline','updateTime'];
const rows = ((j.data && j.data.appList) || []).map(o => Object.fromEntries(KEEP.map(k => [k, o[k]])));
JSON.stringify({ code: j.state && j.state.code, total: j.data && j.data.pageUtil && j.data.pageUtil.recordCount, rows });
```

body 传空字符串即可，无需分页参数。**返回值必须白名单裁剪**（上面的 `KEEP`）：
`appList` 行内含 `iconUrl` 等字段，整包回传会被 Chrome 扩展拦成
`[BLOCKED: Cookie/query string data]`。

判定口径（2026-09-02 实测）：

| 字段 | 含义 |
| --- | --- |
| `isOnline` | **上架标志，判定已上架以此为准**（`1` = 已上架） |
| `auditStatus` | `0` 对应页面「审核中」；完整码表未知 |
| `versionName` | 最近一次提交的版本名 |
| `isPushed` / `isOffline` | 推送 / 下架标志 |

`auditStatus` 只实测到 `0`，**不要单凭它判定**；以 `isOnline` 为准。遇到新码值补记到本节。

会话失效信号：重定向到 `open.9game.cn/login`，或 `success !== true`。
此时**请用户在该标签页自行登录**（淘宝账号 / 九游 / 豌豆荚三选一）后重试，
不读取、不填写、不记录任何凭据。

## 1. 预检本地 APK

先运行 `git status --short`。工作树有未提交改动时，优先复用同版本渠道包，不重建或覆盖产物。“已验证”必须指本次已重新完成下列本地解析，且签名证书能追溯到仓库任务证据、用户明确提供的可信指纹或可信历史发布包；找不到可信签名基准时停止，不能自行挑选历史包建立信任。

渠道包缺失、校验失败或平台拒绝时，先说明原因并停止，不猜测构建或渠道生成命令。确需基于脏工作树重建时，先展示可能进入安装包的改动并取得明确确认，再按项目构建 Skill 和 `vasdolly-multi-channel-apk` Skill 操作；所有 Flutter/Dart 命令使用 FVM。

上传前解析绝对路径并记录以下合同：

```bash
VD="${VASDOLLY_JAR:-$HOME/.claude/skills/vasdolly-multi-channel-apk/VasDolly.jar}"
[ -f "$VD" ] || VD=.agents/skills/vasdolly-multi-channel-apk/VasDolly.jar
shasum -a 256 build/app/outputs/channels/ali-app-release.apk
md5 -q build/app/outputs/channels/ali-app-release.apk
java -jar "$VD" get -c \
  build/app/outputs/channels/ali-app-release.apk
java -jar "$VD" get -s \
  build/app/outputs/channels/ali-app-release.apk
aapt dump badging build/app/outputs/channels/ali-app-release.apk
apksigner verify --verbose --print-certs \
  build/app/outputs/channels/ali-app-release.apk
```

若 `aapt` 或 `apksigner` 不在 `PATH`，使用本机 Android SDK 已安装 build-tools 中的对应可执行文件。核对应用名、包名、版本名、版本号、`ali` 渠道、V2 签名和签名证书；证书应与可信历史发布包或已验证发布证书一致。任何字段缺失或不一致都停止。

## 2. 读取实时状态

使用 `chrome:control-chrome` 复用用户指定且已登录的 Chrome 会话进入固定入口。登录、验证码、二次验证和协议登录动作交给用户亲自处理。

不要读取、复制、记录或复述账号、密码、验证码、测试账号、证件号、备案号、服务器地址及其他敏感字段；这些字段保留实时页面原值，必须处理时让用户亲自完成。

从实时页面定位目标应用，再以包名交叉确认。先读取当前线上版本、审核状态和版本记录：

- 同一 `versionCode` 已审核中或已上线时停止，不重复上传或提交；同时展示 `versionName` 供人工核对。
- 同版本只有草稿、失败、被拒或已撤回记录时，不自动覆盖或重提；先读取状态和平台允许的恢复动作，展示差异并取得针对该恢复动作的新确认。
- 本地 `versionCode` 不高于线上 `versionCode` 时停止并核查版本合同；页面未显示可比的版本号时也停止。
- 目标应用、页面语义或实时状态不明确时停止，不猜测历史 ID 或选择器。

## 3. 上传 APK

上传是独立的外部传输动作。操作前展示目标站点、APK 绝对路径、SHA-256、MD5、应用名、包名、版本名、版本号、渠道和签名核验结果；只有用户明确确认上传后才继续。

使用 Chrome 可见文件上传控件和文件选择器上传已确认的绝对路径，不按历史坐标盲点，也不直接操作未经核对的隐藏输入。页面要求先删除或替换旧包时暂停；先区分对象是临时上传文件、未提交草稿、审核记录还是线上版本，并展示精确目标、可恢复性和线上影响，再为这一次删除或替换另取确认。

上传完成后重新读取页面，核对平台解析的应用名、包名、版本名和版本号。页面展示或要求 APK MD5 时，与本地 32 位 MD5 对照；任何不一致都停止，不填写声明、不提交审核。

## 4. 更新版本资料

从 `docs/发布版本更新日志.md` 读取与 APK 版本完全对应的 Android 简体中文更新说明。页面存在长度限制时仅作可追溯的保真压缩，不补写未经证实的功能、隐私、安全或合规承诺。

只更新当前版本要求的字段。保留已有分类、简介、标签、图标、截图、资质、隐私政策、测试资料、备案信息和其他商店材料，除非实时页面明确要求或用户明确要求变更。若平台强制补充、改变或重新确认资料，暂停并把它作为新的资料变更或声明展示给用户，不能自行填写。不要把“提交审核”当作保存草稿。

## 5. 合规和法务闸门

风险 SDK 自查、隐私承诺、开发者协议及其他有法律或合规含义的声明都需要独立确认。勾选或接受前：

1. 读取实时声明原文，展示拟选择内容和当前证据。
2. 无法依据代码、APK 或用户提供的事实判断时暂停，不猜测。
3. 涉及开发者协议、主体保证或其他法律承诺时，优先让账号持有人亲自勾选或接受；平台允许代理操作且用户明确要求时，也必须针对该声明单独确认。

上传确认不能授权任何声明；一个声明的确认也不能授权其他声明或最终提交。

## 6. 最终提交

“提交审核”是独立的最终动作。点击前重新展示：

- 平台解析的应用名、包名、版本名、版本号和 APK MD5
- 当前线上版本、版本记录与防重复检查
- 完整更新说明
- 风险 SDK、隐私和法律声明状态
- 保留的既有资料及预期状态变化

只有用户在看到摘要后明确要求“提交审核”才点击最终按钮。请求开头或历史消息中的“直接提交审核”不是最终点击的预授权；上传、继续、保存或先看看也不构成最终提交授权。

同时看到成功页“已上传应用，请等待审核”和应用列表中新版本“审核中”，才报告提交成功。任一信号缺失时，只做有限的等待、刷新和只读状态查询；保留页面并报告实际状态，不猜测结果，也不重复点击提交。

## 7. 收尾与破坏性动作

提交成功后更新 `docs/应用发布平台清单.md` 中阿里应用分发行的版本、渠道包、上传和审核中状态；审核通过前不要勾选“审核通过”。

撤回审核、删除记录、替换已上传包、下线版本或其他改变现有状态的动作，都必须展示精确目标和影响并分别取得新确认。一次确认只授权一个明确动作。

只有用户明确要求暂存或提交 Git 时才执行；只纳入本次实际产生的发布 Skill、发布文档和任务文件，不纳入用户已有的无关改动。
