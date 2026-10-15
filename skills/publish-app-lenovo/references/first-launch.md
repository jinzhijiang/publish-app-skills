# 联想首次上架（创建应用）

> 2026-10-15 实测（opencli 驱动主 Chrome，一次首发提交到「上架审核中」）。联想没有开发者可用的发版 API，
> 建应用、传包、填资料、提交审核全部在控制台完成。已上架应用的版本更新见 [workflow.md](workflow.md)。

## 一、入口与流程

| 步骤 | 页面 | 要点 |
| --- | --- | --- |
| 应用列表 | `https://open.lenovomm.com/developer/mgmt` 的「Phone/Pad应用」 | 先用包名确认目标不在列表里。同一账号下可能已有别的应用 |
| 创建 | 列表右上「＋ 创建」→ `/developer/mgmt/appcreate?type=1` | 顶部四步：创建应用 → 完善信息 → 测试审核 → 发布上线 |
| 第 1 步 | 同一网址 | 「创建类型」默认已选 Phone/Pad；「应用类型」选「软件」或「游戏」，点「下一步」 |
| 第 2 步 完善信息 | 同一网址 | 一张长表单，底部「返回 / 保存 / 提交审核」 |

列表里已经有目标包名（含「该版本来自合作渠道」的）时不要创建，走更新或应用认领。

## 二、完善信息表单契约

file input 共 15 个：安装包 1、图标 1、截图 5（每个位一个）、著作权证明 1、联想承诺函 1、特殊资质证明 1、
其他资料证明 5。**按 `.ant-form-item` 的 label 定位后打标记**，别靠下标记忆。

| 字段 | 控件 | 限制与说明 |
| --- | --- | --- |
| 上传方式 | 单选「单包上传 / 双包上传」 | **默认双包**。arm64 单包要先切「单包上传」，切换会重建 input，切完再找 input |
| 上传APK | 第一个 file input（`accept` 为空） | 只收 32/64 兼容包或纯 64 位包。约 30 秒后解析区显示 `包名 / CPU: 64 / 大小 / 版本`（没有 versionCode） |
| APP备案号 | 只读展示 | 平台自动带出，不能手填（本次首发页面上没显示具体值，备案号另在「ICP备案号」里填） |
| 选择分类 | antd Select `#appCategoryCode` | 例：理财金融 |
| 应用标签 | antd Select `#appTags` | 选项随分类变化；理财金融下有 支付 / 彩票 / 记账 / 银行 / 理财 / 保险 |
| 应用名称 | `#appName` | ≤16 字 |
| 一句话描述 | `#introduction` | ≤32 字 |
| 应用简介 | `#detailInfo`（textarea） | ≤1000 字 |
| 是否具备AI能力 | 单选，默认「否」 | 选「是」会多出必填「AI能力描述」 |
| 新版本特性 | `#releaseInfo`（textarea） | ≤800 字，首发写首个版本介绍 |
| 应用图标 | file input | 512×512，jpg / png / gif，≤2MB |
| 应用截图 | 5 个 file input，每位一个 | 3–5 张，9:16，≥450×800，单张 ≤2MB（1080×1920 PNG 海报 1.3–1.7MB 可以直接用） |
| 隐私政策网址 | `#privacyProtocolUrl` | 带 `https://` |
| ICP备案号 | `#icp` | ≤50 字；填 App 的备案号（形如 `…ICP备…号-NNA`） |
| 著作权证明 | file input | **只收 JPG / PNG**，≤15MB，不收 PDF |
| 联想承诺函 | file input | 页面未标必填，但本次首发补传后才提交。用页面「联想承诺函模板」链接下载 docx，填应用名、包名、公司名、日期，盖公司鲜章后拍照或扫描上传，≤15MB，不得改模板内容 |
| 特殊资质证明 | file input | 新闻、即时通信、直播、系统工具、社交、网络支付、加密代理、网络金融类才需要 |
| 其他资料证明 | 5 个 file input | 选填，可放 App 备案截图 |
| 是否需要账号登录 | 单选，默认「否」 | 选「是」多出测试账号两个框，由发布人亲自填 |
| 发布方式 | 单选，默认「审核通过后立即发布」 | 或「定时发布」 |

**有草稿**：「保存」不要求任何声明，提示「保存成功」。草稿在列表里显示「未提交」，操作列是「完善信息 / 删除」；
「完善信息」打开 `/developer/mgmt/appcreate?opt=2&type=1&submitId=<id>&softId=&packageName=<包名>`，已传的包和图片都还在。
所以联想可以先把能填的填完保存，再等发布人补材料（比如承诺函）。

**提交没有额外勾选项**：点「提交审核」直接弹「提交成功，将于1-2个工作日完成审核！」，确定后回列表。

## 三、opencli 自动化做法与坑

会话名下面用 `lenovo`，`CFU` 指 `chrome-file-upload` skill 目录（部署后是 `~/.claude/skills/chrome-file-upload`）。

- **单选**：`opencli browser lenovo click --text 软件`、`click --text 单包上传` 都能用。按钮用 `click --role button --name 创建 / 下一步`。
- **上传**：都用 `chrome-file-upload` 分块注入。先给目标 input 打标记，例如承诺函：

  ```bash
  opencli browser lenovo eval '(() => { const it = Array.from(document.querySelectorAll(".ant-form-item"))
    .find(x => (x.querySelector("label") || {}).innerText?.includes("联想承诺函"));
    it.querySelector("input[type=file]").setAttribute("data-cfu", "pledge"); return "tagged"; })()'
  python3 "$CFU/scripts/opencli_upload.py" --session lenovo --file "$PLEDGE_JPG" \
    --expect-url open.lenovomm.com --selector '[data-cfu="pledge"]'
  ```

  5 个截图位逐个打标记、逐个注入，每次之间等几秒。
- **核对图片有没有传上去**：预览不是 `img` 标签，按 `img` 计数永远是 0。看网络：每次注入后会有
  `getOssParam` → POST `app-img-lestore-adp…aliyuncs.com`，两个都 200 才算传上；或者截图看预览。
- **下拉框点不中**：分类和标签是 antd Select（虚拟列表）。`click` 选项、`keys ArrowDown` 都不会改值，
  在可见选项上真实点击也不行。可靠做法是在页面里找到 Select 组件、直接调它的 `onChange`：

  ```bash
  PICK='((sel, label) => { const input = document.querySelector(sel);
    const key = Object.keys(input).find(k => k.startsWith("__reactFiber")); let f = input[key];
    while (f && !(f.memoizedProps && f.memoizedProps.onChange && f.memoizedProps.children && typeof f.type !== "string")) f = f.return;
    const opts = [].concat(f.memoizedProps.children).flat().filter(Boolean);
    const hit = opts.find(c => c.props.children === label);
    if (!hit) return JSON.stringify({ error: "option not found", available: opts.map(c => c.props.children) });
    f.memoizedProps.onChange(hit.props.value, hit.props); return JSON.stringify({ picked: label, value: hit.props.value }); })'
  opencli browser lenovo eval "$PICK('#appCategoryCode', '理财金融')"
  opencli browser lenovo eval "$PICK('#appTags', '记账')"     # 分类选好后标签选项才会出来
  ```

  选完用 `.ant-select-selection-item` 的文字核对。实测分类「理财金融」值 `28`、标签「记账」值 `131`。
- **文本**：`#appName` 等 input 和两个 textarea 用 `opencli browser lenovo fill` 都正常，它会回读校验。
- **保活**：等发布人补材料或确认提交时，后台起 `bash "$CFU/scripts/opencli_keepalive.sh" lenovo 60 &`。
  已经保存过的草稿不怕标签页被回收，没保存的会整页丢失。
- **偶发 `attach_failed`**（`Cannot access a chrome-extension:// URL of different extension`）：隔 3 秒重试。

## 四、状态码（列表接口，SKILL.md § 0）

| 阶段 | 列表文字 | 接口 |
| --- | --- | --- |
| 草稿 | 未提交 | `state=0`，`versionName` / `versionCode` 为 `null` |
| 提交后 | 上架审核中 | `state=1`，`versionName` / `versionCode` 有值，`appSource=2`（自主上传），`onShelfLatestVersion=null` |
| 已上架 | 已上架 | `state=5`，`onShelfLatestVersion` 为在架版本 |

提交后 `submitDate` 仍是草稿第一次保存的时间，不会变成提交时间；记录提交时间以页面提示出现的时刻为准。
