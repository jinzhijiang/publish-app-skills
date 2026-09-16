# 360 首次上架（创建软件）

> 2026-09-11 实测。360 没有发版 API，建应用、填资料、传包、提交审核全部在控制台完成。
> 本文记录入口、表单字段契约与自动化的坑；已上架应用的版本更新见 [workflow.md](workflow.md)。

## 一、入口：外壳页 + iframe 标签，但表单可以直接打开

控制台是 iframe 标签式后台模板：外壳页 `/mod3/mobilenavs/index`，左侧菜单 `a.J_menuItem`
在外壳里以 iframe 标签打开各页面。创建流程三跳：

| 步骤 | 页面 | 自动化要点 |
| --- | --- | --- |
| 应用列表 | `/mod3/mobile/applist`（外壳内 iframe） | 「创建软件」是 `a.btn` + jQuery 事件，调用 `dev.managePublic.tools.addJmenuTab` 在外壳里开新标签。**单独打开 applist 时点了没反应**（没有外壳，调用静默失败） |
| 选择类型 | `/mod3/createmobile/guide?type=soft&qid=` | 不带 `type=soft` 单独打开是空白页 |
| 填写表单 | `/mod3/createmobile/BaseInfo?appType=soft` | 「软件」按钮是 `a.createbtn[target=_blank]`。**脚本 `.click()` 会被当成弹窗拦截**，真实点击才会开出新标签 |

**结论：直接打开 `https://dev.360.cn/mod3/createmobile/BaseInfo?appType=soft` 即可**，前两跳只是导航。

其它路由（页面脚本中出现）：游戏 `/mod3/createmobilegame/app`、应用认领 `/mod3/mobileclaim/index/`。

## 二、BaseInfo 表单字段契约（第 1 步「填写应用信息」）

页面顶部三步：1. 填写应用信息 → 2. 填写资质信息 → 3. 完成提交审核。

| 字段 | name / 控件 | 限制与说明 |
| --- | --- | --- |
| 软件安装包 | `#uploadapk_btn`（WebUploader）；`input[type=file][accept="application/vnd.android.package-archive"]` | 须 64 位或 32/64 位兼容包；解析结果写入 `uploadedApkInfo`，应用名显示在 `now-name` |
| 名称后缀 | `name_link`（`-` / `( )` / `:`）+ `name_ext` | 运营字段，可为空 |
| 分类 | `tag1` → `tag2` | 选了 `tag1` 才会出现 `tag2` 选项，例：理财 → 记账 |
| 个性推荐语 | `onewords` | **≤13 字**，用于首页精准推荐 |
| 支持语言 | `lang` | 简体中文 / 繁体中文 / 英文 |
| 资费类型 | `is_free` | 功能付费 / 免费软件 / 免费试用 / 部分功能付费 / 部分内容付费 / 内容付费 |
| 应用简介 | `brief` | 50–1500 字；没有 `maxlength`，只有页面计数「还可以输入 N 字」 |
| 当前版本介绍 | `edition_brief` | 10–400 字符 |
| 隐私权限说明 | `sensitive_permission_explain` | ≤400 字；上传 APK 后页面列出检测到的敏感权限，要求逐项说明 |
| 隐私政策网址 | `sensitive_url` | 填带协议头的完整网址 |
| 备案主体与开发者主体是否一致 | `is_beian_same`（`1` 是 / `0` 否） | 默认「否」。**选「是」后下面四项仍然显示、仍需填写** |
| APP 备案主体 / 统一社会信用代码 / 备案编码 | `beian_corp_name` / `beian_id_code` / `beian_number` | 选「否」时还要在资质处补关联关系的备案授权函 |
| 备案截图 | `#uploadbeian_btn` → `beian_img` | jpg / png / gif，≤2MB。工信部查询有滑块验证码，需人工截图 |
| 应用图标 | `#uploadlogobtn` → `uploadedLogoInfo` | 512×512 PNG，**圆角半径 70px**，与安装包内图标一致（华为、荣耀要求直角，360 相反） |
| 应用截图 | `uploadshotspanel` 下 5 个 `input[type=file]` → `uploadedShotsInfo` | 4–5 张同尺寸 JPG / PNG，不小于 800×480，单张 ≤3MB，去除顶部通知栏 |
| 审核辅助说明 | `apk_desc` | 选填，≤400 字，可写测试账号 |
| 网络友好度测试 | `is_smarter`（`1` / `0`） | 默认否 |
| 发布时间 | `timed_pub`（`0` 立即 / `1` 定时）+ `timed_pub_day` / `timed_pub_hour` | 默认审核后立即发布 |
| 风险 SDK 自查 | `sdk_check` = `1` | 合规声明，须账号持有人确认后才勾 |

## 三、自动化做法与坑

- **文本框**：用原生 value setter 赋值，再派发 `input` / `keyup` / `change`，页面计数会同步更新。
  长文案放进上传桥目录，页面内 `fetch('http://127.0.0.1:8912/<file>.txt')` 取回再填，
  不必把上千字塞进脚本参数。
- **上传桥**（`chrome-file-upload-bridge`）在 `dev.360.cn` 上可用：HTTPS → `127.0.0.1` 请求放行后直接拿到文件。
- **App 自带的浏览器面板用不了上传桥**：同样的请求立刻 `Failed to fetch`，服务端日志里收不到，
  说明在浏览器内部就被拦了。自动上传必须走 Chrome 扩展。
- **脚本返回值**含 URL / 查询串时会被扩展拦成 `[BLOCKED: Cookie/query string data]`：只回传 pathname 和参数名。
  单次返回约 1000 字符会被截断：大结果先存 `window.__x`，再分片读取。
- **读不到已认证主体**：`/mod3/developer` 的 HTML 只是注册表单结构，输入框没有值。
- **APK 权限以 `aapt2 dump permissions` 为准**：第三方 Gradle 插件可能在 manifest 合并之后再注入权限，
  合并报告里查不到，填隐私权限说明前要核对插件自己的构建日志。
- **提交**：`a#submitform` 只是一层薄包装，校验由 Validform 5.3.2 负责，提交逻辑在
  `/resource/js/mod3/createmobile/create_app_baseinfo.js`。第 1 步写入接口是 `/mod3/createmobile/submitBaseInfo`，
  同文件里还有 `/mod3/createmobile/changeCate`（切换分类）和 `/mod3/createmobile/seo`。
- **改分类会丢未保存的内容**：切换分类会弹「确认变更应用分类吗？未保存的信息可能会丢失」，
  所以**先选分类，再填其它字段**。截图不同尺寸会提示「截图尺寸要统一」。

## 四、上传与解析（实测）

- **APK**：WebUploader 0.1.5，上传接口 `/mod3/upload/apk`，响应形状 `data.status` / `data.data` / `data.error`，
  页面提示「不超过4G的APK文件」。上传桥把 `File` 注入 `#uploadapk_btn` 下的输入框后，
  显示「<文件名> 上传应用文件成功」，随后出现解析卡片（应用名、包名、版本名称、版本号）。
- **解析后回写的隐藏字段**（只列字段名）：`pname`、`version_name`、`version_code`、`label`、`apk_md5`、
  `rsa_md5s`（签名证书摘要）、`file_url`、`file_size`、`apk_name`、`icon`、`isAccessSdk`、`accordance`、
  `apk_status`、`isProtect`、`_apk_token`（会话令牌，不要记录它的值），以及可见的 `uploadedApkInfo`、`now-name`。
- **自适应图标取不出来**：`icon` 回写为字符串 `false`，卡片上的图标是裂图，页面随之请求
  `/mod3/createmobile/false` 得到 404——**这不代表上传失败**，别据此重传。应用图标照常在「应用图标」处单独上传。
- **敏感权限列表**：包里只有普通权限（网络、Wi-Fi 状态、唤醒锁等）时列表为空，但「隐私权限说明」输入框仍在，可照常填写。
- **图标 / 截图**：同样注入 `File` 到 `#uploadlogobtn` 与 `#uploadshotspanel` 下的 5 个输入框，每张返回「上传文件成功」，
  预览分别为 512×512 与 113×200 缩略图。5 个截图输入框按 DOM 顺序对应 5 个格子，逐个注入（间隔约 2.5 秒）不会串位。
- 页面发出的上传请求既没被页面内的 XHR / fetch 钩子捕获，也没出现在扩展的网络记录里（原因未查明），
  判断成败以页面回显文字和隐藏字段是否有值为准。

## 五、第 2 步「完善资质信息」（实测）

- 第 1 步点「提交审核」（`submitBaseInfo`）后跳到 `/mod3/createmobile/qualify?id=<appid>&op=&isInCreateFlow=1`，
  **应用记录此时已经建立**：列表接口里出现新应用，`appid` 就是 URL 里的 `id`，
  取值为 `status=VERIFY_ING`、`lifestatus=null`、`version=null`（资质还没交，也还没真正提审）。
- 进页面先弹「建议您上传电子版权认证证书，自动化在线验证，应用可快速审核上架」，点「确定」关掉即可。
- 页面底部写着 **「请在"更新应用信息"中提交应用审核」**：本页按钮 `#submitform` 只是「保存(资质提交)」，
  最终提审要回到更新应用信息的表单去做。
- 通用要求：资质图片 jpg / png / gif ≤2MB，压缩包 ≤10MB。

分类为「理财 → 记账」时可见的资质项：

| 资质 | 控件 | 要求 |
| --- | --- | --- |
| 软著登记证书类型 | `regcerify_type`，可见选项只有 `1`「App 电子版权认证证书」 | |
| App 电子版权认证证书 | `#uploadregcerify_btn2`，只收 PDF | 须为版权中心下发的**原始文件，不得修改，包括文件名**；已实名开发者可凭纸质证书免费换发（约一个工作日） |
| ICP 备案证明或 ICP 证 | `#uploadicpcard_btn` → `uploadedicpcardQualify` | 备案系统网站截图即可；jpg / png / zip |
| 法人手持身份证（或原件扫描件） | `#uploadidCard_btn` → `uploadedidCardQualify` | jpg / png；**身份证件由账号持有人自己上传** |
| 上架承诺书 | `#uploadsjcns_btn` → `uploadedsjcnsQualify` | 下载模板，填写并加盖公章后回传 |
| AI 生成合成内容服务类型 | `ai_content_type`（`1` 提供 / `0` 不涉及） | 选「提供」才出现 `#uploadaicontentmakings_btn` |
| 其他授权或协议（非必填） | `#uploadother_btn` | 多个文件打包上传，jpg / png / pdf / zip |

证券期货、金融许可、支付业务许可、网络文化经营许可、互联网新闻信息服务等资质的上传框默认隐藏，随分类出现。

### 电子版权认证证书的校验（实测）

- 上传走 `/mod3/upload/commfile/`，响应字段 `data.errno` / `data.data` / `data.error` / `data.url`。
  **「上传文件成功」只说明文件存上了**：页面随后把 `regcerify_apply`、`uploadedRegcerifyInfo2` 两个标记写成 `0` 或 `1`，
  而 `uploadedRegcerifyInfo2` 的 Validform `datatype` 是自定义规则 `regcerify_apply`，**只有标记为 `1` 才通过**，
  否则红字「请上传电子版权认证证书」一直在，触发失焦重新校验也不会消失。
- **中国版权保护中心下发的软著电子证书也不被认可**：带数字签名的 PDF、保持原始文件名，标记仍为 `0`。
  页面脚本里的提示原文是「请提交电子版软著登记书，若没有，请去易版权免费转换下电子软著登记证书」。
  需要到易版权的 360 专用通道 `www.yibanquan.com.cn/appcert/nappcertreapplyfor360.jhtml`
  用软著免费换发「App 电子版权认证证书」，约一个工作日，由账号持有人实名办理。
- ICP 备案证明直接用备案系统的查询结果截图即可，上传后 `icpcard` / `uploadedicpcardQualify` 有值，没有额外校验提示。

## 六、待补（流程继续后回填）

- 保存资质之后的跳转，以及「更新应用信息」里最终提审的步骤与成功信号
- 审核中 / 审核通过后列表接口 `status` / `lifestatus` 的取值
