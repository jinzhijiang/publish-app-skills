---
name: publish-app-samsung
description: Prepare, repair, and submit Android APK releases to Samsung Galaxy Store Seller Portal through Chrome, or query 三星上架/审核状态 read-only by parsing the console's own list HTML. Use when uploading the sanxing VasDolly channel APK, checking whether a version is 未提交草稿 / 审核中 / 销售 / 暂停, re-registering a rejected Samsung release, reading a Samsung rejection report, adding English default store metadata or screenshots, checking parsed version and device status, answering GMS, AIGC, minor-mode, or US minor-law declarations, or submitting a Galaxy Store update for review.
---

# 三星 Galaxy Store 发布

> 本文中形如 `docs/发布版本更新日志.md`、`docs/应用发布平台清单.md` 的路径，指的是**调用方项目**仓库里的文档（相对项目根），不是本 skill 目录里的文件；各项目按自己的约定放置即可。

通过 Chrome 为目标应用更新三星渠道 APK、修复拒审资料并提交审核。Seller Portal 页面和校验规则会变化，始终以实时页面为准。

## 固定合同

- 控制台：`https://seller.samsungapps.com/content/common/summaryContentList.as`
- 应用：`SAMSUNG_APP_NAME`（每次都在控制台应用列表里用应用名和包名交叉确认目标）
- Content ID：`SAMSUNG_APP_ID`（首次跑通后填进配置；**每次仍需用应用名和包名交叉确认**，不要当固定入口用）
- 包名：`SAMSUNG_PACKAGE_NAME`（即调用方项目的 applicationId）
- 渠道：`sanxing`
- 默认 APK：`build/app/outputs/channels/sanxing-app-release.apk`
- 更新说明来源：`docs/发布版本更新日志.md`
- 发布状态清单：`docs/应用发布平台清单.md`
- 实测浏览器路由与字段约束：`references/workflow.md`

上面的 `SAMSUNG_*` 取自**调用方项目**的配置，不写进本 skill：

```bash
# 在目标项目仓库里执行；<项目名> 即 git 根目录名
mkdir -p ~/.config/ai-ignore-config/<项目名>
cp "$SKILL_DIR/config.example.env" ~/.config/ai-ignore-config/<项目名>/samsung.env
```

读不到就停下来问，不要拿别的应用的值顶上。登录密码、验证码不进配置，由发布人在浏览器里手动完成。

不要固化历史标签页、详情 URL、控件顺序、版本、文件摘要或审核状态。

## 0. 实时状态查询（只读，不必走完整发版流程）

三星**没有 JSON 接口**，`summaryContentList.as` 是服务端渲染的 JSP。但仍可用同源 fetch
取回 HTML 后在页面内解析，比截图判读稳。

做法：在 Chrome 里打开 `https://seller.samsungapps.com/content/common/summaryContentList.as`
（已登录），用 `javascript_tool` 在该标签页执行下面这段。

```js
const r = await fetch('/content/common/summaryContentList.as');
const html = await r.text();
const doc = new DOMParser().parseFromString(html, 'text/html');
const tb = doc.querySelectorAll('table')[0];
if (!tb) { 'SESSION_EXPIRED (no list table)'; }
const txt = el => el ? (el.innerText || el.textContent || '').trim().replace(/\s+/g, ' ') : '';
const items = []; let cur = null;
for (let i = 2; i < tb.rows.length; i++) {            // 前 2 行是两层表头
  const cells = [...tb.rows[i].cells];
  const idCell = cells.find(c => /\btit\b/.test(c.className) && /^\d{6,}$/.test(txt(c)));
  if (idCell) {                                        // 含内容 ID 的行 = 新起一条
    cur = { contentId: txt(idCell), appName: txt(cells.find(c => /\bexpl\b/.test(c.className))),
            draft: '', ready: '', review: '', sale: '', updated: [] };
    items.push(cur);
  }
  if (!cur) continue;                                  // 续行合并进当前条
  const g = re => { const c = cells.find(x => re.test(x.className)); return c ? txt(c) : ''; };
  cur.draft  = cur.draft  || g(/\bregi\b/);            // 可编辑草稿
  cur.ready  = cur.ready  || g(/\bprec\b/);            // 已提交待审（Ready for Review）
  cur.review = cur.review || g(/\bcertifi\b/);
  cur.sale   = cur.sale   || g(/\bstatSale\b/);
  const d = g(/\bdate\b/); if (d) cur.updated.push(d);
}
JSON.stringify({ http: r.status, count: items.length, items });
```

> `cur` 初始化时记得带上 `ready: ''`，与 `draft`/`review`/`sale` 一起。

上面这段是**逐字段构造输出对象**（`contentId` / `appName` / `draft` / `review` / `sale` / `updated`），
等价于其余平台的白名单裁剪——**不要改成回传整行 HTML 或整个 cell 集合**，
那会因为含 URL 被 Chrome 扩展拦成 `[BLOCKED: Cookie/query string data]`。

**按 CSS class 解析，不要按列下标**（2026-09-02 实测的 class 语义）：

| class | 含义 |
| --- | --- |
| `tit rowTd`（内容为纯数字）| 内容 ID |
| `expl` | 应用名 |
| `regi` | 「未提交 (草稿)」列 —— 可编辑草稿，文案如「更新中」 |
| **`prec`** | **同一列，但已提交待审，文案是 `Ready for Review`** |
| `certifi` | 「审核中」列 |
| `statSale` | 「销售」列（`暂停` 等） |
| `date` | 上次更新时间 |

> **`regi` 与 `prec` 占同一列但语义相反**：`regi` = 还没交，`prec` = 已经交了。
> 2026-09-02 首次实测提交后就踩了这个坑——解析器当时只认 `regi`，
> 于是把一个刚提交成功的应用读成「三列全空」。判「是否已提交」看 `prec` 是否非空。

三星用**列位置**表达状态：哪一列有文案就是处于哪个阶段。且**一个应用跨 2 个 `<tr>`**
（主行的应用信息单元格带 `rowSpan=2`，续行只有状态与日期），所以必须「遇到内容 ID 就新起一条，
后续行合并进当前条」，否则会把一个应用读成两条或漏读状态。

本轮实测输出（3.5.0）：

```json
{"contentId":"<ContentID>","appName":"<应用名>","draft":"更新中","review":"","sale":"暂停",
 "updated":["2024-07-10","2026-09-01"]}
```

读法：`draft=更新中` 说明 3.5.0 还是**未提交的草稿**；`sale=暂停` 说明在架那条处于暂停。
**`draft` 有值不等于已提交**——这是三星最容易误判的地方。

会话失效信号：返回的 HTML 里没有列表表格（拿到的是登录页）。
此时**请用户在该标签页自行登录**后重试，不读取、不填写、不记录任何凭据。

## 0.5 换包前必查：草稿里现在是哪个包

上传报「已在使用」时，**先去应用程序包页看那张表，不要急着换文件名**。
2026-09-02 实测：草稿里躺的是 3.3.0（versionCode 30004）、标着「审核失败」的旧包，
文件名与本地待传包同为 `sanxing-app-release.apk`——重名的是**它**，不是版本冲突。

两条应对，缺一不可：

1. 复制一份带版本号的副本再传，绕开重名。**文件名不能带点**——平台校验「只允许下划线（`_`）
   和连词符（`-`），不能有空格」，`sanxing-app-release-3.5.0-30007.apk` 会因版本号里的点被拒；
   用 `sanxing-app-release-350-30007.apk` 这种形式。
2. 用旧包行的**编辑（铅笔）原位替换**，不要按删除——删除包属独立破坏性动作，须单独确认。
   铅笔打开的是「添加应用程序包」模态框，里面同时有文件选择和 **Google Mobile Service** 单选，
   保存模态框时这两项一起落库。

**上传前先验 `targetSdkVersion ≥ 34`**：平台明写「低于 Android 14 (API level 34) 的应用程序
无法提交至中国大陆以外的国家/地区（仅在大陆销售时可用 30–33）」。只要分发范围不含中国大陆，
这就是硬门槛，包不合规时整条链路白跑。

```bash
# Android SDK 工具取版本号最大的一份，不写死 build-tools 版本
sdk_tool() { ls "${ANDROID_HOME:-$HOME/Library/Android/sdk}"/build-tools/*/"$1" 2>/dev/null | sort -V | tail -1; }
"$(sdk_tool aapt)" dump badging <apk> | grep -E "^package|targetSdkVersion|native-code"
```

另：中国大陆分发会触发大陆资质要求，而资质区块（`资质编号及文件`）默认商店语言为 English 时
处于 `ng-hide`，**肉眼看不到**。要判断资质是否齐备，直接读 DOM：编号是 `input[type=text]` 的值，
文件是否已传要看有没有渲染出文件名——8 个位置全是「选择」按钮就说明一个文件都没有。
编号有值 ≠ 文件已传，这两者是分开的。

## 1. 预检本地 APK

先运行 `git status --short`。工作树有未提交改动时，优先复用同版本已构建的渠道包；不要无依据重建或覆盖发布产物。确需重建时，先展示可能进入 APK 的改动并取得确认，所有 Flutter/Dart 命令使用 FVM。

上传前记录 APK 绝对路径并核对：

```bash
VD="${VASDOLLY_JAR:-$HOME/.claude/skills/vasdolly-multi-channel-apk/VasDolly.jar}"
[ -f "$VD" ] || VD=.agents/skills/vasdolly-multi-channel-apk/VasDolly.jar
shasum -a 256 build/app/outputs/channels/sanxing-app-release.apk
md5 -q build/app/outputs/channels/sanxing-app-release.apk
java -jar "$VD" get -c \
  build/app/outputs/channels/sanxing-app-release.apk
java -jar "$VD" get -s \
  build/app/outputs/channels/sanxing-app-release.apk
aapt dump badging build/app/outputs/channels/sanxing-app-release.apk
apksigner verify --verbose --print-certs \
  build/app/outputs/channels/sanxing-app-release.apk
```

若 `aapt` 或 `apksigner` 不在 `PATH`，使用本机 Android SDK 已安装 build-tools 中的对应可执行文件。核对应用名、包名、版本名、版本号、`sanxing` 渠道、签名方案和证书；证书必须能追溯到可信历史包、任务证据或用户提供的可信指纹。任一字段缺失或不一致都停止。

## 2. 读取拒审证据和实时状态

使用 `chrome:control-chrome` 复用用户指定且已登录的 Chrome。登录、验证码、二次验证、证件和测试账号均由用户亲自处理；不要读取、复制、记录或复述敏感字段。

若用户提供 Samsung HTML 拒审报告，先读取报告并逐条保存：

- 原问题和复现条件
- 平台要求的修复路径
- 新 APK 或商店资料提供的对应证据

从应用列表用 Content ID、应用名和包名交叉确认目标，再比较线上、拒审、草稿和本地 APK 版本：

- 同一 `versionCode` 已处于 `Ready for Review`、审核中或销售状态时停止，不重复提交。
- 本地 `versionCode` 不高于已发布版本时停止。
- 拒审记录存在“重新注册”时，先确认它打开同一 Content ID 的编辑流程，而不是创建重复应用、删除记录或下线版本。

## 3. 修复多语言商店资料

多国家/地区分发时，把 English 添加为商店语言并设为默认；保留真实的简体中文资料。填写：

- 应用名称与调用方项目一致
- 英文应用介绍和一句话简介
- 最多 5 个真实英文关键词
- 与 APK 版本完全对应的英文更新日志
- 4–8 张符合平台尺寸要求的截图

不要编造功能、隐私、安全或合规承诺。优先上传真实英文界面截图；若只能复用现有商店截图，先说明截图语言和审核风险并取得确认。可通过当前页面的 `pageAssets` 获取已展示的现有截图，再用可见多文件上传入口注册到 English 资料。

商店语言和“支持的语言”是两个独立字段：

- English 设为默认商店语言后，还要把 English 加入“支持的语言”。
- 保留简体中文支持语言。
- 提交校验若同时报告应用名称、简介、介绍和截图缺失，检查是否误加了一个空白语言；只在确认该语言无意添加且为空后删除。

保存后切换语言重新读取应用名称、简介、介绍、截图数量、更新日志和默认标识。不要把“提交审核”当作保存。

## 4. 替换拒审 APK

上传是独立的外部传输动作。上传前展示：

- Seller Portal 目标应用和 Content ID
- APK 绝对路径、大小、SHA-256 和 MD5
- 应用名、包名、版本名、版本号和渠道
- 签名验证结果

只有用户明确确认上传后才能继续。

对于拒审应用，优先使用旧拒审包行的 `Modify` 原位替换。不要因为页面存在 `Delete` 就删除旧包；删除记录、线上包或其他非临时对象必须另取确认。

使用 Chrome 文件选择器：

1. 先监听 `filechooser`。
2. 点击实时页面中唯一可见的 APK 选择入口。
3. 传入已确认的 APK 绝对路径。
4. 等待处理完成并确认设备范围变化提示。
5. 保存应用程序包标签页。

上传后核对平台解析的版本名、版本号、文件名、大小、设备数和“可安装”状态；可见字段与本地合同不一致时停止。

## 5. 逐项确认合规声明

每个声明都单独读取实时原文、展示拟选答案和依据，再取得用户确认。上传确认和最终提交确认不能代替声明确认。

### Google Mobile Service

上传弹窗会询问是否使用 Google Mobile Service。检查 APK 是否实际依赖 Google 服务，并说明：

- 选择“是”会自动从销售国家/地区排除中国大陆。
- APK 中出现 Google 或 Firebase 组件只能作为证据，不能代替账号持有人的声明。
- 不能为了保留中国大陆而擅自选择“否”。

### 中国大陆声明

中国大陆分发可能要求：

- 是否提供人工智能生成合成内容（AIGC）
- 是否支持未成年人模式

结合当前产品能力提出建议；无法从代码、APK、产品界面或用户事实判断时停止。让用户明确确认两个答案后再保存。

### 美国未成年人法规

美国分发可能要求判断应用是否符合家长同意政策例外。读取实时例外条件，例如紧急服务、政府或非营利组织运营、标准化考试等。普通效率工具通常不适用，但仍须展示条件并让用户确认，不能自行作法律判断。

任何新出现的隐私、出口、开发者协议或主体保证都按同样门槛处理。

## 6. 最终提交

“提交审核”是独立最终动作。点击前展示：

- Content ID、应用名、包名、版本名和版本号
- English 默认资料、支持语言和截图数量
- APK 文件信息、设备数和可安装状态
- 国家/地区范围
- GMS、AIGC、未成年人模式及美国法规回应
- 当前版本记录和防重复检查

只有用户明确说“提交审核”后才能点击。平台弹出“是否递交应用程序”时，该次最终确认可用于点击“是”；新的法律声明仍须重新确认。

**「对未成年人法规的回应」必须单独点该页底部的「保存」一次**，否则点提交只会把你导航到该页、
不弹确认框，看起来像是没反应。这一节在侧栏**永远不显示绿勾**（和「应用内购买」「应用程序推广」
一样是灰的），别把没绿勾当成没填——以页面上单选的实际选中态为准。

提交校验失败时读取缺失字段，修复并保存后再提交，不要循环点击。提交成功的可靠信号是：

1. 平台完成处理并自动返回应用列表。
2. 同一 Content ID 出现新记录，状态为 `Ready for Review` 或实时页面等价的审核中状态，并显示本次更新时间。

任一信号缺失时只报告实际状态，不猜测成功，也不重复提交。

## 7. 收尾

提交后更新 `docs/应用发布平台清单.md` 中三星行的版本、渠道包、上传和当前审核状态；审核通过前不要勾选“审核通过”。

撤回审核、删除语言、删除应用包、删除审核记录、下线版本或改变销售国家都属于独立状态变更，必须展示精确目标和影响并分别取得确认。

只有用户明确要求暂存或提交 Git 时才执行；只纳入本次 Skill、发布文档和任务文件，不纳入用户已有的无关改动。
