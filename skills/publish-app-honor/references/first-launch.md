# 荣耀首次上架（控制台建应用 + API 全流程）

> 2026-09-04 实测。与 vivo 不同：**荣耀除"建应用"外全部可以走 API**，
> 不需要在控制台填草稿，`submit-audit` 也不校验控制台状态。

## 一、控制台建应用（API 建不了）

入口：管理中心 → 应用服务 → **新建**。表单只有七项：

| 字段 | 约束 |
| --- | --- |
| 平台类型 | 安卓 |
| 支持设备 | 手机/平板 或 手表 |
| 应用分类 | 游戏 / 应用 |
| 应用名称 | ≤15 个中文字符或 30 个其他字符 |
| 默认语言 | 如简体中文 |
| 应用包名 | 需以字母开头、中间必须有点，≤128 字符。**创建后不可改** |
| 应用图标 | 正方形**不要圆角**、**≤200KB**、512×512、PNG/JPG/JPEG |

创建后页面给出 **APP ID** 与 **SecretKey**，APP ID 填进 `honor.env` 的 `HONOR_APP_ID`。

> 图标 200KB 的限制比别家紧（vivo 500KB、华为无此限）。512×512 的 PNG 常常超，
> 转成 256 色调色板 PNG 通常能压到 150KB 左右且肉眼无损。

### 控制台表单在 iframe 里：怎么传图标

荣耀控制台把表单渲染在 `managecenter/opencards/app/` 这个**同源 iframe** 内。
两个后果：

1. 主文档的 `document.querySelectorAll` 查不到表单元素，要先
   `document.querySelectorAll('iframe')[0].contentDocument` 穿进去
2. **a11y 树不穿 iframe**，浏览器自动化的 `file_upload` 拿不到 ref

解法（比起本地桥接更省事，**不需要 Chrome 的 PNA 授权**）：

```js
// 1) 把 file input 临时搬到主文档，a11y 树立刻可见
const f = document.querySelectorAll('iframe')[0];
const fi = [...f.contentDocument.querySelectorAll('input[type=file]')][0];
window.__slot = {parent: fi.parentElement, next: fi.nextSibling};
document.body.appendChild(document.adoptNode(fi));
fi.id = 'tmp-upload';
fi.style.cssText = 'position:fixed;left:8px;top:8px;width:200px;height:32px;opacity:1;z-index:2147483647;display:block';

// 2) 用 file_upload 按 id 找到 ref 上传

// 3) 搬回原位并派发事件（文件选择跟着元素走）
const D = f.contentDocument, W = f.contentWindow, s = window.__slot;
fi.style.cssText = 'display:none';
s.parent.insertBefore(D.adoptNode(fi), s.next);
fi.dispatchEvent(new W.Event('change', {bubbles: true}));
```

元素对象自始至终是同一个，框架挂在它上面的监听器不受影响。
注入后 `input.files.length` 读到 0 是正常的（组件在 change 里接管后清空），
**以页面回显的缩略图为准**。

下拉选项（如默认语言）不在 DOM 的 `li` 里，鼠标点不中，**用键盘**：
点开后 `Down` × N + `Enter`。

## 二、之后全部走 API

拿到 API 密钥（管理中心 → 开放能力 → **凭证** → API密钥）填进 `honor.env`，
`doctor` 应显示 `tokenOk: true` 且 `appIdLookup` 能按包名查到 appId。

顺序：

```bash
PY="$SKILL_DIR/scripts/honor_publish.py"

# 1) 传 APK 与截图，各自记下 objectId
python3 "$PY" upload --file <apk> --file-type 100
python3 "$PY" upload --file <shot>.png --file-type 3      # 3=纵向 1080×1920

# 2) 先写文案——update-file-info 绑语种要求该语种已通过 update-language-info 建过
python3 "$PY" language --intro-file <intro> --brief-intro-file <brief> \
                       --new-feature "$(cat <notes>)"

# 3) 绑素材（order 从 0 开始，重复 order 会失败）
python3 "$PY" bind --object-id <apkObjectId> \
                   --object-id <shot1>:zh-CN:0 --object-id <shot2>:zh-CN:1 ...

# 4) 基础信息（整体覆盖，必须带齐必填字段，见 reference.md）
python3 "$PY" app-info --set appClassification=11205 --set releaseCountry=CN ...

# 5) 提审
python3 "$PY" submit --release-type 1 --test-comment "…"
```

**文案上限与华为一致**（`intro` ≤8000、`briefIntro` ≤80、`newFeature` ≤500），
多平台发版时这两家可以共用一份，不像 OPPO（13/1024）与 vivo（17/200/1000）要各写一份。

## 三、控制台仍需手工的部分

以下在 API 里没有对应字段，仍要登控制台：

- **软著 / 版权证明上传**
- 部分账号下的年龄分级确认流程

发版脚本跑完后去控制台补这两项再提交审核。
