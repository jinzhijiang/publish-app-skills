# 讯飞首次上架（创建应用）

> 2026-10-15 实测（opencli 驱动主 Chrome 填表并两步暂存，账号持有人点最终「提交」，列表显示「审核中」）。
> 讯飞没有发版 API，建应用、传包、填资料、提交审核全部在控制台完成。已上架应用的版本更新见 SKILL.md 与 [workflow.md](workflow.md)。

## 一、先想清楚：这个平台适不适合

讯飞AI学习机应用中心面向 K12 学生设备，**应用分类只有教育类**（学习综合 / 数学 / 英语 / 语文 / 物化生 / 政史地 / 课外拓展），
还要填学段和年龄。非教育类应用（记账、工具、娱乐）只能挂在「课外拓展」下，审核可能以定位不符驳回。
上架前把这个风险告诉发布人，由发布人决定是否继续。

## 二、入口与流程

| 步骤 | 页面 | 要点 |
| --- | --- | --- |
| 应用列表 | `#/app-list` 的「普通应用」页签 | 先确认目标包名不在列表里；「应用认领」页签用于认领已在讯飞的应用 |
| 创建应用 | 列表右上「创建应用」→ 弹窗 `.add-app-dialog` | 只有一个上传控件，平台解析后回填 应用名称 / 包名 / 版本 / 权限（只读） |
| 建应用 | 弹窗「提交」→「是否确认创建该应用？」→ 确认 | 分配 APP ID，生成 `<版本> 未提交` 草稿，跳到 `#/app-list/app-update` 向导；弹「离开页面别忘了暂存哦~」点「我知道了」 |
| 第 1 步 | 填写应用信息 | 右上「暂存 / 下一步」 |
| 第 2 步 | 填写版本信息 | 右上「暂存 / 上一步 / 提交」——**这里的「提交」就是最终提审** |

弹窗「提交」只是建应用，不是提审；最终提审是第 2 步右上角的「提交」（向导第 3 格「提交」不是单独一页）。

**回到草稿**：列表「查看详情」→ `#/app-detail`（显示 APP ID、发行时间、服务备案）→ 版本行「编辑」→ 向导概览页，
左侧「应用信息」「<版本号>」分别打开两步的表单。

## 三、表单契约

### 第 1 步：应用信息

| 字段 | 控件 | 限制与说明 |
| --- | --- | --- |
| 应用名称 / 应用包名 | 只读文本 | 来自安装包解析；审计脚本会误报为缺失 |
| 一句话简介 | input，maxlength 15 | **5–15 字** |
| 应用简介 | textarea，maxlength 1000 | 50–1000 字 |
| 应用分类 | 两个 Element Plus select | 一级只有教育类；「课外拓展」下是 益智 / 学习工具 / 其他。只能选一个，上架分类最终由讯飞决定 |
| 上传图标 | file input | 512×512，PNG / GIF，**直角**（和阿里相反），≤200KB，须与安装包图标一致 |
| 上传图片介绍 | file input（单文件，逐张传） | 竖屏 1080×1920 或横屏 1920×1080，PNG / JPG，**单张 ≤1MB**，3–5 张；去掉状态栏通知图标，不得用其他品牌设备做边框 |

### 第 2 步：版本信息

| 字段 | 控件 | 限制与说明 |
| --- | --- | --- |
| 应用安装包 / 版本 / 权限 | 解析回填 | |
| 版本说明 | textarea，maxlength 500 | 首发写首个版本介绍 |
| 隐私政策网址 | input，maxlength 500 | |
| 付费提示 | 单选 无 / 含付费项目 | 选「含付费项目」才出现必填「付费内容」（激活 / 会员 / 课程 / 部分章节 / 其他） |
| 广告类型 | 单选 无 / 轻度广告 / 重度广告 | 非「无」才出现必填「广告内容」（开屏 / 弹窗 / banner） |
| 学段 | 多选 幼儿 / 小学 / 初中 / 高中 | 声明项，按应用实际受众填，和年龄保持一致 |
| 年龄 | 单选 3+ / 8+ / 12+ / 16+ | 声明项；建议与其他商店已填的年龄分级一致 |
| 软件版权证明 | file input | 《计算机软件著作权证书》，jpg / png，<2MB |
| ICP备案网址或备案号 | input，maxlength 500 | 填 App 备案号 |
| 特殊类证书 / 客服电话 / 备注 | 选填 | 客服电话 ≤50、备注 ≤500 |

学段、年龄、付费、广告都是对外声明，提交前和完整摘要一起交发布人确认。

## 四、opencli 自动化做法与坑

会话名下面用 `xunfei`，`CFU` 指 `chrome-file-upload` skill 目录（部署后是 `~/.claude/skills/chrome-file-upload`）。

- **上传后停在 `is-ready`，必须手动触发上传（本次最大的坑）**：`chrome-file-upload` 注入后，文件出现在上传列表里，
  但状态一直是 `el-upload-list__item is-ready`、进度 0%，**一个 XHR 都没发**。上传组件是 Element Plus 的 `ElUpload`
  （`autoUpload=true` + 自定义 `httpRequest`，走 `cystorage.cycore.cn/v2/files/upload`），原因没查实。
  可靠做法：注入后找到包住这个 input 的 `ElUpload` 实例，调它暴露的 `submit()`：

  ```bash
  SUBMIT_FOR='((sel) => { const input = document.querySelector(sel);
    const root = Array.from(document.querySelectorAll("*")).find(e => e.__vue_app__);
    const seen = new Set(); const ups = [];
    const visitV = (v, d) => { if (!v || d > 300) return; if (v.component) walkI(v.component, d + 1);
      if (Array.isArray(v.children)) v.children.forEach(c => typeof c === "object" && visitV(c, d + 1)); };
    const walkI = (inst, d) => { if (!inst || seen.has(inst)) return; seen.add(inst);
      if ((inst.type && inst.type.name) === "ElUpload") ups.push(inst); visitV(inst.subTree, d); };
    visitV(root._vnode, 0);
    const elOf = i => { const e = i.subTree && i.subTree.el; return e && e.nodeType === 1 ? e : (e && e.parentElement); };
    const hit = ups.find(i => { const e = elOf(i); return e && e.contains(input); })
      || ups.find(i => { const e = elOf(i); return e && e.parentElement && e.parentElement.contains(input); });
    if (!hit) return JSON.stringify({ error: "ElUpload not found", total: ups.length });
    hit.exposed.submit(); return JSON.stringify({ submitted: true }); })'
  python3 "$CFU/scripts/opencli_upload.py" --session xunfei --file "$APK" \
    --expect-url xxj.xunfei.cn --selector '[data-cfu="apk"]'
  opencli browser xunfei eval "$SUBMIT_FOR('[data-cfu=\"apk\"]')"
  ```

  生产包的 Vue 3 不在 DOM 元素上挂组件引用，要从挂载容器的 `_vnode` 往下走组件树；`app._instance` 在生产模式是空的。
  图标、截图、软著的上传控件同样如此，每次注入后都要 `submit()` 一次。28MB APK 实测 26 秒传完，
  随后平台调 `packageParse`、`getApkInfoByUid`，十几秒内回填解析字段。
- **验证上传**：给页面装一个 XHR 记录钩子（包一层 `XMLHttpRequest.prototype.open/send`，把网址、状态、
  `upload.onprogress` 的 loaded/total 记到 `window.__xhr`），比看进度条可靠；列表项变 `is-success` 也算传上。
- **截图逐张传**：图片 input 不是 `multiple`。每张注入前重新给当前的 input 打标记（上传后 input 会换），注入、`submit()`、等几秒再传下一张。
- **下拉**：点 select 的 input 展开，再 `opencli browser xunfei find --css '.el-select-dropdown__item'` 拿 ref 点击。
  `click --role option` 和 `click --text` 都点不中。二级选项要等一级选完才出来。
- **单选 / 多选**：先在页面里按文字给 `.el-radio` / `.el-checkbox` 打属性标记并 `scrollIntoView`，再 `opencli browser xunfei click '[data-…]'`。
- **文本**：input、textarea 用 `opencli browser xunfei fill` 正常。
- **暂存验证**：`暂存成功` toast 一闪而过，抓不到就看 XHR 记录里 `/app/management/updateAppVersionInfo` 是否 200，
  或重新进草稿看字段还在不在。
- **保活**：等发布人确认学段 / 年龄、决定提交期间，标签页会被回收（本次就被回收过一次，因为两步都暂存了所以没丢东西）。
  用 `bash "$CFU/scripts/opencli_keepalive.sh" xunfei 120 &` 起保活，再 `pgrep -fl 'opencli_keepalive.sh xunfei'` 确认在跑。

## 五、提交之后

- 第 2 步页面顶部变「<版本> 审核中，预计1-3个工作日反馈结果」，按钮变「撤回申请」；列表 `#/app-list` 显示 `<版本>审核中`。
- 讯飞的状态接口请求体加密，仍只能读页面（见 SKILL.md § 2）。
- 把 APP ID 回填到调用方项目的配置与发布清单；skill 里不写具体 APP ID。
