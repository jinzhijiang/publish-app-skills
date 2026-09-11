# 应用宝首次上架（控制台手工 + 之后切 API）

> 2026-09-09 ~ 09-11 实测（笔笔记账 1.2.0）。结论：**开放平台 API 做不了首发**。
> 建应用、填资料、认领、传包、提交审核全部在控制台完成；提交之后 API 才查得到这个应用。

## 一、控制台先给 app_id，包名后填

「创建应用」时什么都不填、直接点创建，就会分配 `app_id`；包名、名称、分类等基础信息之后在
**基本信息**页补。与华为 / vivo / 荣耀「建应用时必须填包名且创建后不可改」正好相反。

拿到 `app_id` 就可以先写进 `yingyongbao.env`，但**首发前 API 仍然用不了**，见下节。

## 二、首发前 API 全部不可用：`1000009` 是兜底码

凭据正确（`doctor` 里 `hasUserId` / `hasAccessSecret` 都是 true）时，首发前四个接口
`query_app_detail`、`get_file_upload_info`、`update_app`、`query_app_update_status`
**全部**返回：

```text
ret=1000009 请求pkg_name与app_id不匹配
```

**别被字面意思带去反复核对包名。** 对照实验：

| 请求 | 结果 |
| --- | --- |
| 真 app_id + 真 pkg_name | `1000009` |
| 真 app_id + 假 pkg_name | `1000009` |
| **编造的** app_id + 真 pkg_name | `1000009` |

连编造的 app_id 都是这个码，说明它只表示「按这对参数查不到可操作的应用」，不携带配置对错的信息。
基础信息全部填完、还没提交时，结果也不变。

另外两个参数**都必填**（缺 `pkg_name` 报 `1000005`，缺 `app_id` 报 `1000006`），
开放平台也没有「凭包名查 app_id」的接口。

## 三、隐私自查（基本信息页，六项）

基本信息页要求填隐私政策 URL，并逐项勾选「隐私自查」。应用宝会**解析该 URL 的内容**做自动化检测，
所以链接必须是可直接访问的静态 HTML（不支持博客、云笔记、网盘、图片等），检测失败会影响合规检测。

下表按各项名称的通行口径整理——控制台里每项的「查看样例」原文未能读到，勾选前以样例为准：

| 自查项 | 需要满足什么 |
| --- | --- |
| 隐私政策独立一致性 | 独立页面，不与用户协议合并；App 内展示的与填报 URL 是同一份 |
| 隐私政策声明主体 | 写明开发运营主体全称，与开发者账号主体一致 |
| 隐私政策注销流程 | 可操作的注销路径、前置条件、处理时限、无法自助时的人工渠道；只写「可以注销」不够 |
| 注册/登录界面提醒用户阅读隐私政策 | App 内要求：登录页有默认不勾选的同意框和可点开的《隐私政策》 |
| 隐私政策个性化 | 有个性化推荐 / 定向推送就说明并给关闭入口；**没有也要明示没有** |
| 儿童隐私政策 | 儿童（不满 14 周岁）专门条款：监护人同意、监护人代为行权、误收集后删除 |

笔笔记账首发前，后三项里的「注销流程」「个性化」「儿童」都不达标，是在提交前补的。

## 四、认领：用正式签名签空包

首发过程中控制台要求先**认领应用**：提供一个未签名空包（本次为 `tap_unsign.apk`，包名 `tap.claim.nosig`），
要求用应用的正式签名签好后传回，证明持有签名私钥。校验的是**证书**而不是包名，空包的包名不用改。
本次按下面的步骤签好后一次认领成功（2026-09-11）。

```bash
BT="$(ls -d ~/Library/Android/sdk/build-tools/* | sort -V | tail -1)"
# 1) 先对齐，否则 v2/v3 签名会失败
"$BT/zipalign" -p -f 4 tap_unsign.apk tap_aligned.apk
# 2) 密码走环境变量（env:），不要写成 pass:明文，否则会出现在进程参数里
"$BT/apksigner" sign --ks <keystore> --ks-key-alias <alias> \
  --ks-pass env:KS_STORE_PASS --key-pass env:KS_KEY_PASS \
  --v1-signing-enabled true --v2-signing-enabled true --v3-signing-enabled true \
  --out tap_signed.apk tap_aligned.apk
# 3) 必做：证书 SHA-256 与线上正式包逐字比对，一致才上传
"$BT/apksigner" verify --print-certs tap_signed.apk   | grep 'SHA-256'
"$BT/apksigner" verify --print-certs app-release.apk  | grep 'SHA-256'
```

v1（JAR 签名）也一并打开：不确定对方的校验逻辑读哪种签名，三种都签成本为零。

## 五、提交之后

- `query_app_detail` 转为 `ret=0`，能回读版本、文案、分级等字段（字段表见 [reference.md](reference.md)）。
  是「提交即解锁」还是「过审才解锁」这次没能区分。
- `query_app_update_status` 返回 `5000002 未查询到应用审核信息`：首发不是经 `update_app` 提交的，
  API 侧没有这张审核单。**首发的审核结果只能在控制台看**；之后经 API 提交的版本才查得到。
- 从下个版本起走 `publish`。本项目没接 VasDolly 渠道包时，直接
  `--apk build/app/outputs/flutter-apk/app-release.apk`。

## 六、文案字段实测

| 字段 | 实测 |
| --- | --- |
| `introduce`（应用介绍） | 填入 1328 字，回读**恰好 500 字**、断在小标题中间 → 按 **≤500 字**单独写一份 |
| `one_word_summary`（一句话简介） | 12 字完整保存，上限未测 |
| `feature`（更新说明） | 242 字完整保存，上限未测 |

各家长度上限不同，应用宝的介绍是目前见过最短的：华为 / 荣耀 8000、OPPO 1024、vivo 1000、**应用宝 500**。
