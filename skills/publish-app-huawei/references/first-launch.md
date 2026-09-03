# 首次上架华为应用市场（AGC 控制台流程与踩坑）

Use this reference only when the app does **not** exist in AppGallery Connect yet.
后续更新不用看本文，直接走 `SKILL.md` 的 API 发版流程。

控制台入口：<https://developer.huawei.com/consumer/cn/service/josp/agc/index.html#/myApp>

分工一句话：**建应用和填信息只能在控制台做（API 无此能力）；传包、更新说明、提审可走 API。**

---

## 第一步：创建应用

「APP与元服务」→ 顶部选平台 tab（**HarmonyOS / Android / Windows**，Android 应用必须切到 Android tab）→ 右上「新建发布」。

| 字段 | 说明 |
| --- | --- |
| 软件包类型 | APK(Android应用) / RPK(快应用) / EXE(Windows应用) |
| 支持设备 | 手机 / VR / 手表 / 大屏 / 路由器 / 车机 |
| 应用名称 | ≤30 字符；**必须与软件包内应用名一致**（`android:label`） |
| 应用分类 | 应用 / 游戏 二选一，后面还有二级三级分类（如 应用/工具/效率） |
| 默认语言 | 商店文案的默认语言 |

确认后立即进入应用主页，此时就能拿到 **APP ID**（页面「应用信息」区可见）——把它填进
`~/.config/ai-ignore-config/<项目名>/appgallery.env` 的 `HUAWEI_ANDROID_APP_ID`，
后续 API 全靠它。

> 同名应用可在 HarmonyOS 与 Android 两个 tab 各建一个，互不冲突，appId 不同、包名也
> 可以不同（例如 `cn.example.app` 与 `cn.example.appoh`）。别把两边的 appId 填串。

## 第二步：填「应用信息」页

此页**必填项全部填完才能整页保存**（保存时统一校验），与「准备提交」页不同。

### 文案字段

| 字段 | 上限 | 备注 |
| --- | --- | --- |
| 应用名称 | 30 | 与包内一致 |
| 应用介绍 | 8000 | 完整描述 |
| 应用一句话简介（小编推荐） | 80 | |
| 新版本特性 | 500 | 客户端更新页展示 |

**坑 1：所有文案字段不能带 emoji。** 保存时弹「不能输入（🎉）特殊符号」整页保存失败。
从 CHANGELOG 抄更新说明前先把 emoji 删干净。

### 应用图标

- 216×216 **直角**正方形（华为自己加圆角蒙层），PNG ≤2MB 或 WEBP ≤100KB。
- 必须与软件包内图标一致。从项目的 1024 源图 `sips -z 216 216` 缩一张即可。

### 应用截图

- 竖版应用选「竖向截图」，需 3~5 张，**宽高比严格 9:16**（建议值 450×800，实测 1080×1920 通过）。
- 格式 PNG / JPG / JPEG ≤2MB，WEBP ≤100KB。

**坑 2：比例是硬校验。** 现代手机原始截图多为 9:19.5 ~ 9:21（如 1080×2400），直接传会弹
「图片尺寸不符合要求」。不要拉伸或土法补边——用营销海报图（画布 1080×1920，手机 mockup +
大标题文案）质量更好也天然合规；`app-store-screenshots` 类工具的 Android 导出尺寸就是 1080×1920。

**坑 3：同一张图（按内容）不能重复上传，且删除后服务端仍记得。** 重传同一文件弹
「您上传的应用截图重复，请重新上传」。误删想恢复时，把图重新编码一次（PNG→JPEG 或改质量参数）
内容哈希变了就能传。正常操作下别反复删传同一张。

## 第三步：填「准备提交」页

此页**支持部分保存**——填一项存一项，不会因为别的必填项为空而整页失败。区块与要点：

| 区块 | 要点 |
| --- | --- |
| 发布国家/地区 | **默认全球（含 ALL，200+国家）**。只发国内就改成仅中国大陆；发欧洲会触发 DSA 要求（邓白氏号/营业执照验证），别无意间背上 |
| 开放式测试 | 首次正式上架选否 |
| 付费情况 | 免费/付费；免费无内购就都选无 |
| 内容分级 | 问卷式年龄分级（无敏感内容的工具类通常 3+） |
| 隐私声明 | **隐私政策网址**（必填），隐私标签、个人信息收集声明 |
| AI 功能声明 | 是否含 AI 生成合成服务 |
| 版权信息 | 电子版权证书（软著 PDF）或代理证书上传 |
| 备案信息 | APP 类型、主办单位类型/名称/**统一社会信用代码**——对应 ICP 备案主体 |
| 应用审核信息 | 见下 |
| 联系方式 | 应用负责人手机/邮箱/姓名（审核沟通用，真人信息） |
| 上架时间 | 审核通过后立即上架 / 定时 |

### 测试账号（应用审核信息）

勾选「**需要登录进行审核**」后才会展开「测试帐号」**用户名/密码两个结构化输入框**，
加上 300 字「备注」。推荐写法：

- 用户名/密码栏：填测试手机号 / 固定验证码（验证码登录的应用把固定码当"密码"填）。
- 备注栏模板：

```text
本应用无需登录即可完整使用全部核心功能，登录仅用于云同步。

需验证登录相关功能时可用测试账号：
手机号：<测试号>
验证码：<固定码>（固定码，点「获取验证码」后直接输入即可，不会收到真实短信）

账号注销入口：<注销路径>。
如有疑问请联系：<客服邮箱>
```

**坑 4：审核员大概率会实测「账号注销」。** 固定验证码的测试白名单账号常常走不了注销
（注销场景要真实短信）。两种解法：后端给测试号放开注销，或在备注里另给一个能收真实
短信的账号专供注销演示。提审前务必确认其中之一成立。

## 第四步：首包上传（走 API）

「应用信息」保存成功后即可传包，用 `SKILL.md` 的 publish 命令（不带 `--submit`）。

**首次传包 = 包名永久绑定。** AGC 把 APK 内的 `applicationId` 绑到该 appId，之后不能改。
绑定**以 APK 内为准**——脚本配置/dry-run 回显里的 `packageName` 只用于查询和自检，不参与
绑定。所以传前核对的是 **APK 本身**：

```bash
BT=$(ls -d ~/Library/Android/sdk/build-tools/* | sort -V | tail -1)
"$BT/aapt2" dump badging <apk> | head -2        # package name / versionCode / versionName
"$BT/apksigner" verify --print-certs <apk> | head -3   # release 证书主体
"$BT/aapt2" dump badging <apk> | grep native-code       # ABI 清单
```

传完反查确认绑定：

```bash
python3 "$PY" appid-list --platform android --package-name <包名>
# 返回的 value 应当就是这个应用的 appId
```

## 第五步：提审前检查清单

- [ ] 「应用信息」已保存：文案（无 emoji）、216 图标、3~5 张 9:16 截图
- [ ] 隐私政策网址可公网访问，与包内弹窗口径一致
- [ ] 发布国家/地区已按意图收敛（只发国内就别留全球）
- [ ] 测试账号可登录，且**注销路径对审核员可走通**（坑 4）
- [ ] 备案信息与 ICP 备案主体一致；软著已上传
- [ ] APK 包名/签名/versionCode 已核对，包已 attach 到草稿（`info` 可回读 versionNumber）
- [ ] 新版本特性 ≤500 字、无 emoji
- [ ] 提审是不可逆动作，和用户确认后再 `submit` / 控制台点提交

## 控制台自动化备注（供 AI 参考）

AGC 控制台的表单渲染在同源 iframe（`#mainIframeView`）里，浏览器扩展的 a11y 树看不到
iframe 内元素，`find`/`read_page` 会一无所获。可行做法：

- 文本/选择字段：`javascript_tool` 直接操作 `iframe.contentDocument`，Element-UI 表单要用
  原型 setter + `dispatchEvent(new Event('input', {bubbles:true}))` 才能写进 Vue 模型。
- 图片上传：页面 CSP 的 `connect-src` 只放行华为域名（fetch 本地文件被拒），但 `img-src *`
  放行——本地起 HTTP 服务，用 `Image` + canvas 转 File，塞进 `input[type=file]` 的
  `files`（DataTransfer）再派发 change 事件。
- 大文件（APK）别走浏览器，直接用本 skill 的 API 上传。
- Element-UI 上传组件传完会清空 `input.files`，判断"已上传"要看容器里的删除按钮/预览图，
  不能看 `input.files.length`。
