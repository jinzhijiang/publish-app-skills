---
name: publish-app-xunfei
description: Publish APK updates to the 科大讯飞AI学习机应用中心开放平台 (xxj.xunfei.cn) through Chrome, and read 讯飞上架/审核状态 from the console page (this platform is the one exception that cannot be queried via its API — the request body is encrypted). Use when uploading the xunfei VasDolly channel APK, automating 讯飞应用市场发版, checking whether a version is 已上线 / 审核中, reading parsed package/version or audit status, replacing 版本说明 release notes, answering 年龄/学段/付费/广告 declarations, or submitting an app update for review on the iFlytek AI learning-machine app center.
---

# 科大讯飞应用市场发版

> 本文中形如 `docs/发布版本更新日志.md`、`docs/应用发布平台清单.md` 的路径，指的是**调用方项目**仓库里的文档（相对项目根），不是本 skill 目录里的文件；各项目按自己的约定放置即可。

通过 Chrome 为目标应用上传 `xunfei` 渠道 APK、走完三步上架向导并提交讯飞审核。讯飞**没有官方发版 API**，必须以实时控制台页面为准。

44MB 渠道包无法用浏览器工具直传，本 skill 自带上传 harness：
`$SKILL_DIR/scripts/cors_upload_server.py`（`$SKILL_DIR` 指本 skill 目录）。

> **前提：Chrome 必须为该控制台站点放行本地网络访问。** 没放行时 `fetch('http://127.0.0.1:8765/…')`
> 会**静默挂起**——promise 不 resolve 不 reject、console 无报错、harness 服务端零日志。
> 出现这个现象不要反复重试或改写注入 JS：**先放个几字节的探针文件 fetch 一发**，探针也挂就是
> 本地网络限制，去 Chrome 里给该站点放行即可（2026-08-09 放行后同一套注入成功传了 44MB 包）。
> 另外 harness serve 的是 APK 所在**目录**，`build/app/outputs/channels/` 下各渠道包共用一个端口，
> 换平台不必重启。表单在 iframe 里时用 `iframe.contentDocument` 定位控件，且 `File` / `DataTransfer`
> 要用 iframe 自己的 window 构造。兜底路径都不通：`file_upload` 硬上限 10MB，`computer-use`
> 对浏览器只有 read 档点不动原生文件选择器。

## 固定入口

- 控制台：`https://xxj.xunfei.cn/app-open-platform/#/home`
- 平台全称：科大讯飞AI学习机应用中心开放平台（教育垂类，面向讯飞 AI 学习机设备）
- 应用：`XUNFEI_APP_NAME`（每次都在控制台应用列表里用应用名和包名交叉确认目标）
- 包名：`XUNFEI_PACKAGE_NAME`（即调用方项目的 applicationId）
- APP ID：`XUNFEI_APP_ID`（首次跑通后填进配置；**每次仍用应用名和包名交叉确认**，不要当固定入口用）
- 渠道名：`xunfei`
- 实测页面、字段与选择器：[references/workflow.md](references/workflow.md)
- 更新说明唯一来源：`docs/发布版本更新日志.md`
- 平台能力与渠道定义：`docs/应用发布平台清单.md`

上面的 `XUNFEI_*` 取自**调用方项目**的配置，不写进本 skill：

```bash
# 在目标项目仓库里执行；<项目名> 即 git 根目录名
mkdir -p ~/.config/ai-ignore-config/<项目名>
cp "$SKILL_DIR/config.example.env" ~/.config/ai-ignore-config/<项目名>/xunfei.env
```

读不到就停下来问，不要拿别的应用的值顶上。登录密码、验证码不进配置，由发布人在浏览器里手动完成。

本文所有路径相对项目根目录。

## 1. 本地包预检

优先复用同一版本已构建的干净 Release APK；工作树有未提交改动时，不要无依据地重建或覆盖现有发布包。

目标文件：`build/app/outputs/channels/xunfei-app-release.apk`

若渠道包不存在，按项目 FVM 与 VasDolly 约定生成：

```bash
VD="${VASDOLLY_JAR:-$HOME/.claude/skills/vasdolly-multi-channel-apk/VasDolly.jar}"
[ -f "$VD" ] || VD=.agents/skills/vasdolly-multi-channel-apk/VasDolly.jar
fvm flutter build apk --release
mkdir -p build/app/outputs/channels
java -jar "$VD" put -c xunfei \
  build/app/outputs/flutter-apk/app-release.apk \
  build/app/outputs/channels/xunfei-app-release.apk
```

上传前必须记录并核对：

```bash
# Android SDK 工具取版本号最大的一份，不写死 build-tools 版本
sdk_tool() { ls "${ANDROID_HOME:-$HOME/Library/Android/sdk}"/build-tools/*/"$1" 2>/dev/null | sort -V | tail -1; }
VD="${VASDOLLY_JAR:-$HOME/.claude/skills/vasdolly-multi-channel-apk/VasDolly.jar}"
[ -f "$VD" ] || VD=.agents/skills/vasdolly-multi-channel-apk/VasDolly.jar
APK=build/app/outputs/channels/xunfei-app-release.apk
shasum -a 256 "$APK"
md5 -q "$APK"
stat -f%z "$APK"
java -jar "$VD" get -c "$APK"
"$(sdk_tool aapt)" dump badging "$APK" | grep -E "^package|application-label:"
"$(sdk_tool apksigner)" verify --verbose "$APK"
```

确认包名、版本名、版本号、`xunfei` 渠道和签名全部正确；任一不一致都停止。

## 2. 登录并读取实时状态

> **讯飞是唯一不能走接口查状态的平台，只能读页面。** 其余五家无 API 平台（360、联想、阿里、
> 百度、三星）都已改为在控制台页面内调接口/解析 HTML，讯飞不行，原因见下方「为什么不接口化」。
> 别浪费时间去找讯飞的状态接口。

登录凭据、验证码由用户在 Chrome 中完成，不读取、不记录。1Password 的 `request_credentials` 授权即使返回 `approved`，本会话也可能没有可用的填充工具——直接请用户手动登录，别在授权环节反复重试。

会话过期时点「应用管理」会跳到 `#/login`。登录后：

- 应用管理 `#/app-list` →「普通应用」页签，用应用名 + 包名交叉确认目标行，记录**版本状态**（如 `3.1.0 已上线`、`3.5.0审核中`）
- 「查看详情」`#/app-detail` → 记录 APP ID、发行时间、服务备案号与完整版本历史

两个路由坑：

- `#/appManage` **不是有效路由**，直接导航会白屏。正确路径是 `#/app-list`。
- 讯飞是 SPA，`get_page_text` 在渲染完成前会返回只有页脚的空壳。导航后至少等 6 秒再读，
  读到的内容里没有「普通应用 / 合作应用 / 应用认领」页签就是还没渲染完，再等，别当成没数据。

把实时版本号与本地 APK 比较；本地版本不高于线上版本、同版本已在审核中或已上线时停止，不重复上传或提交。

### 为什么不接口化（2026-09-02 探查结论）

列表数据来自：

```
POST https://openapi.xunfeixxj.com/xxj-openplat/app/management/getPageInfo?c=3.0
headers: Content-Type: application/json, timestamp, appid: H5PC, Authorization（569 字节）
body:    base64 密文，不是明文 JSON
token:   localStorage.XUNFEIXXJ_APP_OPEN_PLATFORM_TOKEN
```

**请求体是加密的**，响应大概率同样加密，密钥藏在前端 bundle 里。要复现就得逆向加解密与
`Authorization` 的生成逻辑——成本高，且前端版本一变就整个失效。判定为不值得，保持读页面。

若哪天讯飞改成明文接口，再按其余五家的 `## 0. 实时状态查询` 体例补一节。

## 3. 上传 APK（harness）

上传是独立对外传输动作。操作前展示目标站点、APK 绝对路径、大小、SHA-256、MD5、包名、版本和渠道，并取得**明确的上传确认**。

在应用详情页点右上角「版本更新」打开弹窗，确认弹窗里存在 `input.el-upload__input`，然后：

**① 起本地 harness**（只绑 loopback，用完即停）：

```bash
python3 "$SKILL_DIR/scripts/cors_upload_server.py" \
  build/app/outputs/channels/xunfei-app-release.apk 8765
```

自检（应返回 200 + 正确 Content-Length，OPTIONS 返回 204 且带 CORS 头）：

```bash
curl -sI http://127.0.0.1:8765/xunfei-app-release.apk | head -6
curl -sI -X OPTIONS http://127.0.0.1:8765/xunfei-app-release.apk | head -6
```

**② 页面 JS 注入**（在控制台标签页执行，fire-and-forget + 轮询，**不要直接 await**）：

```javascript
window.__xf = {phase: 'start', size: 0, dispatched: false, error: null};
(async () => {
  const s = window.__xf;
  try {
    s.phase = 'fetching';
    const r = await fetch('http://127.0.0.1:8765/xunfei-app-release.apk', {cache: 'no-store'});
    if (!r.ok) throw new Error('status ' + r.status);
    const blob = await r.blob();
    s.size = blob.size;
    s.phase = 'injecting';
    const input = document.querySelector('input.el-upload__input[type=file]');
    if (!input) throw new Error('file input missing');
    const file = new File([blob], 'xunfei-app-release.apk', {type: 'application/vnd.android.package-archive'});
    const dt = new DataTransfer();
    dt.items.add(file);
    input.files = dt.files;
    input.dispatchEvent(new Event('change', {bubbles: true}));
    s.dispatched = true;
    s.phase = 'dispatched';
  } catch (e) {
    s.error = String(e);
    s.phase = 'failed';
  }
})();
'kicked-off'
```

**③ 轮询状态**：`JSON.stringify(window.__xf)`，期望 `{"phase":"dispatched","size":43981409,...}`，`size` 必须等于本地 `stat -f%z`。页面出现进度条，44MB 约 10–15 秒传完。

**④ 上传完成立刻停 harness**（不要等提交）：

```bash
pkill -f cors_upload_server.py
```

**⑤ 核对解析结果**：弹窗四个只读字段由平台解析回填，逐项与本地合同比对。

```javascript
JSON.stringify([...document.querySelectorAll('input.el-input__inner')]
  .filter(i => i.disabled).map(i => i.value))
```

期望 `["<应用名>","<包名>","<versionName>"]`（版本只显示 versionName，不显示 versionCode）。任一不一致立即停止，不点提交。

## 4. 三步上架向导

⚠️ **弹窗里的「提交」不是提审。** 它只创建 `<版本号> 未提交` 草稿，并跳转到 `#/app-list/app-update` 的三步向导：**填写应用信息 → 填写版本信息 → 提交**。二次确认文案是「是否确认更新应用?」。

### 第 1 步：应用信息

全部自动沿用上一版，正常无需改动：应用名称、包名、一句话简介、应用简介、应用分类、图标、截图。核对后点右上角「下一步」。不要修改分类——页面明确说明上架分类由讯飞决定。

### 第 2 步：版本信息（**唯一需要人工干预的地方**）

用页面 JS 一次性审计所有必填项，比逐个截图可靠：

```javascript
const items=[...document.querySelectorAll('.el-form-item')].filter(e=>e.offsetParent);
const out=items.map(e=>{const lab=e.querySelector('.el-form-item__label');const label=(lab?lab.textContent:'').trim();
const req=e.className.includes('is-required');
const hasChoice=e.querySelector('.el-radio, .el-checkbox');
const checked=[...e.querySelectorAll('.el-radio input, .el-checkbox input')].some(i=>i.checked);
const inp=e.querySelector('input.el-input__inner, textarea');
const files=e.querySelectorAll('.el-upload-list__item').length;
return {label, req, filled: hasChoice?checked:(inp?inp.value.length>0:files>0)};}).filter(o=>o.label);
JSON.stringify({missing: out.filter(o=>o.req && !o.filled).map(o=>o.label), total: out.length}, null, 0)
```

15 个表单项中 13 项自动沿用，**2 项必须人工处理**：

| 字段 | 行为 |
| --- | --- |
| **版本说明**（maxlength 500） | ❌ 沿用的是**上一版旧文案**，必须整段替换 |
| **年龄**（3+/8+/12+/16+） | ❌ **不会沿用，必填但为空**，必须重选 |
| 安装包 / 应用版本 / 应用权限 | 由上传解析 |
| 隐私政策网址、付费提示、付费内容、广告类型、学段、软件版权证明、ICP备案号、特殊类证书、客服电话、备注 | ✅ 沿用上一版 |

**替换版本说明**：取 `docs/发布版本更新日志.md` 对应版本的 Android 简体中文段落。Element UI 的 textarea 必须用原生 setter + `input` 事件，直接赋 `.value` 不会触发 Vue 更新：

```javascript
const ta = document.querySelectorAll('textarea')[2];  // 先用上面的审计脚本确认下标
const notes = "1、...\n2、...";
const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;
setter.call(ta, notes);
ta.dispatchEvent(new Event('input', {bubbles: true}));
ta.dispatchEvent(new Event('change', {bubbles: true}));
JSON.stringify({len: ta.value.length, max: ta.maxLength, ok: ta.value === notes})
```

**确定年龄档**：不要猜。先点右上角「暂存」（`暂存成功` toast，安全、不提审），再点左侧版本树里**已上架**的旧版本只读查看其选择，然后回到新版本照搬：

```javascript
const items=[...document.querySelectorAll('.el-form-item')].filter(e=>e.offsetParent);
JSON.stringify(items.map(e=>{const lab=e.querySelector('.el-form-item__label');
const label=(lab?lab.textContent:'').trim();
const radios=[...e.querySelectorAll('.el-radio')].map(r=>r.textContent.trim()+(r.querySelector('input').checked?'[X]':''));
const checks=[...e.querySelectorAll('.el-checkbox')].map(c=>c.textContent.trim()+(c.querySelector('input').checked?'[X]':''));
return {label,radios,checks};}).filter(o=>o.label&&(o.radios.length||o.checks.length)))
```

2026-07-31 实测：3.1.0（已上架）与 3.3.0 均为 **年龄 `8+`**、学段 `高中`、付费提示 `含付费项目`、付费内容 `会员收费`、广告类型 `无`。

选年龄用真实点击（radio 需要 Vue 事件）。**先滚动到位再取坐标**：`scrollIntoView` 之后必须重新 `getBoundingClientRect()`，否则点空。

改完重跑审计脚本，`missing` 必须为 `[]`。

### 第 3 步：提交

「提交」是独立最终动作。点击前再次展示：APK 解析结果、完整版本说明及字数、年龄/学段/付费/广告各项取值，并取得**新的明确确认**。

点右上角「提交」→ 二次确认「是否确认提交应用信息?」→「确认」。

提交成功的可靠信号（三者都要看到）：

1. `提交成功` toast
2. 页面顶部变为 `<版本号> 审核中，预计1-3个工作日反馈结果`，按钮变「撤回申请」
3. 应用列表 `#/app-list` 版本状态显示 `<版本号> 审核中`

「撤回申请」会改变已创建的审核记录，必须单独确认后才能点。

## 5. 收尾

- 确认 harness 已停：`pkill -f cors_upload_server.py`
- 更新 [references/workflow.md](references/workflow.md)：新发现的页面路径、字段限制、可靠状态信号
- 更新 `docs/应用发布平台清单.md` 科大讯飞行：勾选版本号/渠道包/已上传，备注写审核状态；**审核通过前不要勾「审核通过」**
- Git 暂存只包含本次 skill、发布文档和任务文件，不纳入用户已有的无关改动

## Gotchas

- **弹窗的「提交」≠ 提审**，只是建草稿。真正提审在三步向导第 3 步。第一次做很容易以为点完弹窗就结束了。
- **版本说明会沿用旧版文案**，不替换就会把上个版本的更新说明再发一次，且审核多半看不出来。
- **年龄档不沿用**，是唯一一个必填但空着的字段，不审计就会在提交时被拦。
- **首次 `fetch('http://127.0.0.1:...')` 会无限挂起**：Chrome Local Network Access 权限在拦，请求根本没到服务端。用 `navigator.permissions.query({name:'local-network-access'})` 查状态，返回 `granted` 后重试即成功。挂起时先 `window.stop()` 中止，不要重复发起。
- **不要在浏览器 JS 工具里直接 `await` 大文件 fetch**：CDP `Runtime.evaluate` 45 秒超时，44MB 必定失败。一律 fire-and-forget + 全局状态轮询。
- **`read_network_requests` 在此站会把 data:URI 截图整段吐回来**，瞬间撑爆输出。调试改用 `read_console_messages` 或页面内 JS。
- **`find` / `read_page` 在此站常返回 `Page script returned empty result`**，用页面内 JS 枚举 `.el-form-item` 更可靠。
- **`.el-form-item` 要按 `offsetParent` 过滤**：第 1 步的表单在第 2 步仍留在 DOM 里（`v-show`），不过滤会读到应用简介那个 textarea。
- **`javascript_tool` 输出会被截断**：枚举字段时只取 label/长度/前若干字符，不要整段回传 textarea 值。
- 备注字段里有测试账号（账号 + 手机号），**不要复述到对话里**，也不要改动。
- 讯飞是教育垂类平台，跳版本正常（本项目 3.1.0 → 3.3.0，从未发过 3.2.x）。

## Troubleshooting

| 症状 | 原因 / 处理 |
| --- | --- |
| `Runtime.evaluate timed out after 45000ms` | 在 JS 里 await 了大文件 fetch。改 fire-and-forget + 轮询 `window.__xf`。 |
| `window.__xf.phase` 卡在 `fetching`，服务端日志无请求 | Local Network Access 拦截。`window.stop()` → 查 `permissions.query({name:'local-network-access'})` → 重试。 |
| 点「应用管理」跳到 `#/login` | 会话过期，请用户手动登录后重试。 |
| 直接导航 `#/appManage` 白屏 | 路由名不对。正确路径是 `#/app-list`，或从首页点顶部「应用管理」。 |
| 点击按钮没反应、弹窗还在 | 页面在点击前后发生了滚动，坐标失效。重新截图取坐标再点。 |
| 提交时提示必填项缺失 | 十有八九是「年龄」。跑第 2 步的审计脚本看 `missing`。 |
| `curl` 能访问 harness 但页面不能 | 检查 OPTIONS 是否返回 `Access-Control-Allow-Private-Network: true`；harness 已内置。 |
