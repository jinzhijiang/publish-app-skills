# 阿里应用分发首次上架（创建软件）

> 2026-10-15 实测（opencli 驱动主 Chrome 填表并保存草稿，账号持有人补齐备案信息后提交，列表显示「审核中」）。
> 阿里没有发版 API，建应用、传包、填资料、提交审核全部在控制台完成。已上架应用的版本更新见 [workflow.md](workflow.md)。

## 一、入口

| 步骤 | 页面 | 要点 |
| --- | --- | --- |
| 登录 | `https://open.9game.cn/login` | 发布人在**主 Chrome** 里登录（淘宝账号 / 九游 / 豌豆荚）。登录完会跳到 `open.9game.cn/index` |
| 应用列表 | `https://aliapp-open.9game.cn/app/mng/index` | 用 SKILL.md § 0 的接口按包名确认目标不在列表里；同一账号下可能已有别的应用 |
| 创建软件 | `https://aliapp-open.9game.cn/addapp` | 标题「安卓应用管理 > 创建软件」，顶部三步：填写应用信息 → 应用审核中 → 应用上架 |

**等人登录**：opencli 打开登录页后，先起保活，再在后台轮询网址，跳离 `/login` 就继续：

```bash
"$CFU/scripts/opencli_keepalive.sh" ali 60 &
for i in $(seq 1 120); do u=$(opencli browser ali get url | tail -1)
  case "$u" in *open.9game.cn/login*) sleep 15;; *) echo "logged in: $u"; break;; esac; done
```

## 二、创建软件表单契约

控件 id 稳定，可以直接用 id 选择器，不必另打标记。

| 字段 | 控件 | 限制与说明 |
| --- | --- | --- |
| 上传安装包 | `#fileupload`（accept `.apk`） | 解析出 `包标题 / 包名 / 签名（证书指纹）/ 版本代号 / 版本名 / 包大小`，十几秒就出来 |
| 申请首发 | 解析区下方横幅 | 只给**没在任何其他市场发布过**的应用用；已在别家上架的不要点 |
| 无风险违规 SDK 自查 | `#sdkCheckbox` | 法律声明，由发布人确认。**「保存暂不提交」也要求先勾**，否则弹「温馨提示：请勾选…」 |
| 应用名称 | `#appNameInput` | 建议 ≤20 字、上限 100；解析 APK 后自动带出应用名 |
| 类型 / 分类 | 原生 select：`#categorySel`（应用）→ `#tagSel` 一级 → `#tagSubSel` 二级 | 例：金融理财 → 理财记账。选完一级二级才出选项 |
| 搜索关键字 | `#kwInput1`–`#kwInput3` | 选填，每个 ≤4 个汉字 |
| 一句话简介 | `#sentenceDescInput` | **≤8 个字**，平台可能改写。别家的一句话简介基本都超，要单独准备 |
| 应用描述 | `#descInput` | ≤1000 汉字，禁止链接 |
| 新版特征 | `#updateInput` | ≤1000 汉字，首发写首个版本介绍 |
| 隐私政策 | `#privacyPolicyUrlInput` | 完整网址 |
| 权限获取说明 | 上传 APK 后出现 | 没检测到隐私权限时提示「系统无读取到应用隐私权限，可填写"无"」，下面的**「其它权限」`[id="permissionGroupDescDto.OTHER"]`（id 里有点号，CSS 要用属性选择器） 仍是必填**，空着保存会就地标红「不能为空」。填「无」可以提交，也可以如实写各权限来源 |
| APK包MD5值 | `[name="packageDto.inputMd5"]` | 选填，填本地 32 位 MD5 |
| 服务器IP地址 / 登录账号 | `#serverIp` / `#testAccount` | 选填；属于敏感信息，要填由发布人亲自填 |
| 收费描述 / 广告状态 / 支持语言 | 单选 `#chargeRadio1-3` / `#adRadio1-4` / `#lanRadio1-3` | 支持语言是**单选**（简体中文 / 英文 / 其他） |
| 应用属性 | 单选 `#singleGameTypeRadio1-4` | 一般选「非以上3种属性」（`#singleGameTypeRadio1`） |
| 主体类型 | 单选 `#subjectTypeRadio1` 企业 / `2` 个人 | |
| 主体证件号 | `#licenseNo` | 统一社会信用代码。属于证件号，由发布人亲自填，不读出、不记录 |
| 主办单位名称 | `#appSubjectName` | 备案主体全称 |
| APP备案情况 / 备案号 | `#icpStatusRadio1` 已备案 → 按钮「点击验证备案号」→ `#icpNo` | 备案号不能手填，按钮按主体证件号自动带出；先填证件号再点 |
| 应用图标 | `#iconFile`（只收 PNG） | **透明背景、带圆角**，建议 512×512（最低 256）。直角满底的商店图标不合格，要另做一版（见下） |
| 应用截图 | `#shot1`–`#shot5` | 至少 4 张，jpg / png，≥480×800，不能用 iOS 截图 |
| 电子版权认证证书 | `#electronicFile`（PDF ≤5MB） | 选填。指易版权那种两页 PDF 的「App 电子版权认证证书」；**不要把普通软著证书转成 PDF 传这里**，页面明说会导致不通过 |
| 证明材料 | `#copyRightFile`（JPEG / PNG，最多 6 张，一次一张） | 必填。软著扫描件 + **《开发者权利声明》**（页面「开发者声明」链接下载 .doc，法人或负责人手写签名、盖公章、附签字人身份证正反面后扫描） |
| 安全评估报告 | `#safeReportFile`（PDF ≤5MB） | 选填；公告点名的 App 才必须 |
| 提交 / 保存 | `span#submit`「提交应用」/ `span#save`「保存暂不提交」 | 提交即进入审核，审核期间不能编辑 |

## 三、opencli 自动化做法与坑

会话名下面用 `ali`，`CFU` 指 `chrome-file-upload` skill 目录（部署后是 `~/.claude/skills/chrome-file-upload`）。

- **上传**：所有 file input 都用 `chrome-file-upload` 分块注入，直接用 id：

  ```bash
  python3 "$CFU/scripts/opencli_upload.py" --session ali --file "$APK" \
    --expect-url aliapp-open.9game.cn --selector '#fileupload'
  ```

  截图逐位注入 `#shot1`…`#shot5`，每次之间等几秒。
- **核对上传结果**：每个上传位旁边有个隐藏计数框，`#iconErrorInput` / `#shotErrorInput` / `#copyrightErrorInput` 的值
  就是已传张数（图标 1、截图 4–5、证明材料 ≥1），比逐张截图快；页面上传成功处也会显示绿勾。
- **原生下拉**：`opencli browser ali select '#tagSel' 金融理财`，再 `select '#tagSubSel' 理财记账`。
- **单选**：`opencli browser ali check '#chargeRadio1'`（`check` 会回报是否已选中）。
- **文本**：所有 input / textarea 用 `opencli browser ali fill` 都正常，它会回读校验。
- **圆角图标**：用 Pillow 给现有 512 图标加透明圆角（示例图圆角约为边长的 1/5，实测用 90px）：

  ```python
  from PIL import Image, ImageDraw
  src = Image.open('icon-512.png').convert('RGBA'); S, W, R = 4, 512, 90
  m = Image.new('L', (W*S, W*S), 0); ImageDraw.Draw(m).rounded_rectangle([0, 0, W*S-1, W*S-1], radius=R*S, fill=255)
  src.putalpha(m.resize((W, W), Image.LANCZOS)); src.save('icon-512-round.png')
  ```

- **预填开发者声明**：模板是 .doc，可在 macOS 上 `textutil -convert html` 后把公司名、应用名、包名填进空白，
  再 `textutil -convert docx` 交给发布人打印签字。签名、盖章、身份证只能发布人自己完成。
- **保存的反馈**：缺 SDK 勾选时弹模态框；缺必填字段时**不弹框**，只在字段旁标红「不能为空」并停在原页。
  找红字：遍历叶子节点里文字为「不能为空」的元素，往上找它所在的表单行。保存成功会直接跳回应用列表。
- **右下角的「SDK 风险提示」浮层**是平台公告，和本应用无关，不用处理；遮挡截图时滚动一下即可。
- **偶发 `attach_failed`**：隔 3 秒重试。

## 四、状态码（列表接口，SKILL.md § 0）

| 阶段 | 列表文字 | 接口 |
| --- | --- | --- |
| 草稿 | 未提交 | `auditStatus=2`，`isOnline=0`，已分配 `appId` |
| 首发提交后 | 审核中 | `auditStatus=4`，`isOnline=0` |
| 版本更新提交后 | 审核中 | `auditStatus=0`（2026-10-14 更新实测，与首发不同） |
| 已上线 | 已上架 | `isOnline=1`；`auditStatus=1` |

草稿从列表行「应用管理」进入继续编辑（本次草稿由发布人自己接着提交，进入路径未逐步记录）。
首发提交时是否也会弹「您的应用被检测出风险SDK」选项层未观察到；版本更新时会弹，见 workflow.md。
