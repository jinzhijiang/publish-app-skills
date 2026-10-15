# 百度首次上架（新建应用）

> 2026-10-15 实测（opencli 驱动主 Chrome，一次首发提交到「审核中」）。百度没有发版 API，
> 建应用、传包、填资料、提交审核全部在控制台完成。已上架应用的版本更新见 [workflow.md](workflow.md)。

## 一、入口

| 步骤 | 页面 | 要点 |
| --- | --- | --- |
| 应用列表 | `https://app.baidu.com/newapp/apps/list` | 先用包名确认目标还不在列表里；同一账号下可能已有别的应用 |
| 新建应用 | 列表左上「新建应用」→ `/newapp/apps/detail`（不带 id，标题「新建应用」） | **页面刚加载完时点了常常没反应**：点完等 5 秒看网址，没跳就再点一次 |

更新已有应用的表单是 `/newapp/apps/detail/<id>`，带 id；没有 id 的就是新建。

## 二、表单字段契约

页面一张长表单，分「基础信息 / 应用素材 / 资质合规 / 测试」四块，底部是两个勾选和「提交审核 / 保存 / 取消」。
file input 共 4 个，按页面顺序：安装包、图标、截图、版权证明。**每次先列一遍再打标记，别靠下标记忆。**

| 字段 | 控件 | 限制与说明 |
| --- | --- | --- |
| 上传安装包 | `.one-uploader-input[accept*=apk]` | 解析出「上传时间 / 应用名称 / 包名称 / 版本号」（只有版本名，没有 versionCode），并列出包内图标供「自动预置到【应用图标】」 |
| 应用图标 | 第 2 个 file input | ≥192×192，JPG/PNG，<2MB；必须与安装后的图标一致，透明底、白边、蓝边都是常见驳回原因 |
| 应用分类 | `.app-category-select`：一级单选、二级多选（≤3） | 例：金融理财 → 记账 |
| 一句话描述 | `#summary` | 10–34 **字节**（汉字 2 字节，约 17 个汉字）；必须写出应用类型和功能，不能用繁体 |
| 应用简介 | `#appIntroduce`（textarea） | 100–2000 字节，约 1000 个汉字以内。超过的通用长描述要换短版 |
| 更新说明 | `#updateInfo`（textarea） | ≤500 字节；首发不是必填，建议写首个版本介绍 |
| 开发者名称 | `#developerName` | 账号认证主体自动带出 |
| 核准（原备案）单位类型 | 单选「企业 / 个人」 | **新建表单不预选**，要点一下「企业」 |
| 核准（原备案）主体证件号 | `#licenseNum` | 自动带出统一社会信用代码。属于证件号，不要读出、复述或写进记录 |
| 核准（原备案）主体名称 | `#licenseName` | 空的，填备案主体全称 |
| 应用截图 | 第 3 个 file input，`multiple` | 4–6 张、竖版、尺寸一致、≥480×800、**单张 <1MB**、内容不能重复 |
| 隐私政策 | `#privateUrl` | 带 `https://` 的完整网址，内容要与 App 内隐私政策一致 |
| 版权证明 | 第 4 个 file input，`multiple` | JPG/PNG/PDF，单个 <5MB。软著或 App 电子版权认证证书；著作权人须与开发者名称一致。软著 PDF 可直接传（预览显示裂图是正常的） |
| AI 生成能力 / AI 内容传播平台 | 两个下拉，默认「否」 | 按真实产品填，见 SKILL.md § 5 |
| 测试账号 / 测试视频 | textarea / 网盘链接 | 都不是必填。App 不登录也能完整使用时可以留空；百度把「需要短信验证码才能登录」列为常见驳回原因 |
| 《用户隐私保护承诺协议》、无风险 SDK 自查 | 两个 checkbox | 法律声明，须账号持有人确认。**「保存」也要求先勾这两项**（提示「请阅读并勾选同意协议」） |

关键结论：**首发表单没有不带声明的草稿**。两项声明没确认前，填好的内容只存在于标签页里，
标签页一丢就全部重来——所以等人确认期间必须保活（见下）。

## 三、opencli 自动化做法与坑

会话名下面用 `baidu`，`CFU` 指 `chrome-file-upload` skill 目录（部署后是 `~/.claude/skills/chrome-file-upload`）。

- **保活**：opencli 自己开的标签页空闲约 45 秒就会被回收，整张表单随之丢失（本次丢过一次）。
  只要接下来要等人（登录、确认声明、确认提交），先在后台起
  `bash "$CFU/scripts/opencli_keepalive.sh" baidu 60 &`，人回来后 `pkill -f 'opencli_keepalive.sh baidu'`。
- **打标记**：4 个 file input 先按 `chrome-file-upload` 第 1 步列出上下文，再分别打上
  `data-cfu="apk" / "icon" / "shots" / "copyright"`，后面的命令都用属性选择器。
- **上传**：`opencli browser baidu upload` 对隐藏的 `one-uploader-input` 必报
  `Page.fileChooserOpened not received`，临时把 input 显示出来也没用。直接用 `chrome-file-upload`
  的 `opencli_upload.py` 分块注入，28MB APK 约 20 秒推完：

  ```bash
  python3 "$CFU/scripts/opencli_upload.py" --session baidu --file "$APK" \
    --expect-url app.baidu.com --selector '[data-cfu="apk"]'
  ```
- **截图一次注入多张**：截图 input 是 `multiple`，6 张要放进同一个 `DataTransfer`。
  先逐个只写入不注入（不带 `--selector`），再一次性注入：

  ```bash
  for f in 01.jpg 02.jpg 03.jpg 04.jpg 05.jpg 06.jpg; do
    python3 "$CFU/scripts/opencli_upload.py" --session baidu --file "$DIR/$f" --expect-url app.baidu.com
  done
  opencli browser baidu eval '(() => { const el = document.querySelector("[data-cfu=shots]");
    const dt = new DataTransfer(); Object.values(window.__cfu.files).filter(f => /\.(jpe?g|png)$/i.test(f.name))
      .sort((a, b) => a.name.localeCompare(b.name)).forEach(f => dt.items.add(f));
    el.files = dt.files; setTimeout(() => el.dispatchEvent(new Event("change", { bubbles: true })), 0);
    return dt.files.length; })()'
  ```

  `window.__cfu.files` 里若还留着之前写入的图标，先按文件名过滤掉。
- **截图体积**：商店海报常见的 1080×1920 PNG 一张 1.3–1.7MB，超过 1MB 上限。
  用 `sips -s format jpeg -s formatOptions 88 in.png --out out.jpg` 转成 JPEG，约 250KB，肉眼无差别。
- **APK 解析要等**：注入后 20–90 秒才出解析结果。解析区不在「上传安装包」那个 `.one-form-item` 里，
  读它要在整页文字里找「包名称：」，或者直接截图看。
- **解析失败要先删再传**：文件条变红「解析失败，请尝试重新上传！」时，同一个 input 再注入不会触发上传。
  先点 `.one-uploader-file-item-error .one-uploader-file-item-control`（垃圾桶）清掉，再注入一次。
  本次第二次传同一个包时解析失败过一回，删掉重传就好了。
- **文本框**：两个 textarea 用 `opencli browser baidu fill` 正常。`#summary` / `#licenseName` / `#privateUrl`
  是 `type=normal` 的自定义 input，`fill` 报 `not_editable`，改用 `opencli browser baidu type '<css>' '<文本>'`，
  再用 eval 读 `.value` 核对。
- **下拉**：点 `.app-category-select .one-select-selection`（`--nth 0` 一级、`--nth 1` 二级）展开，
  再 `opencli browser baidu click --role option --name 金融理财`；二级选完按 `Escape` 收起。
- **单选**：`find --css label` 找到文字为「企业」的 label 的 ref，再 `click <ref>`。`click --text 企业` 曾卡住不返回。
- **偶发 `attach_failed`**：报 `Cannot access a chrome-extension:// URL of different extension`
  时是别的扩展的 iframe 插进了页面，隔 3 秒重试，一般几次内就好。批量操作时给每条命令包一层重试。
- **核对用整页数据**：表单项是否齐了，按 `.one-form-item` 的 label 统计各项下 `img` 数量
  （图标 1、截图 4–6、版权证明 ≥1），比逐张截图快。

## 四、提交之后

- 提交后回到应用列表，新行显示「审核中」，此时才分配 APPID。
- 只读接口（SKILL.md § 0）回读：`state=-998`、`onlineState=0`、`isCommit=true`、`packageVersion` 为提交的版本名。
- 把 APPID 回填到调用方项目的发布清单；skill 里不写具体 APPID。
