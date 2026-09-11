# 应用宝 API 更新应用信息 — 参考

官方文档：[wiki 4015262492](https://wikinew.open.qq.com/index.html#/iwiki/4015262492)

## 基址与限制

| 项 | 值 |
|---|---|
| 正式环境 | `https://p.open.qq.com/open_file/developer_api` |
| Content-Type | `application/x-www-form-urlencoded` |
| 编码 | UTF-8 |
| 时间戳误差 | ±30 分钟 |
| 每日上传文件 | ≤100 次/用户 |
| 每日更新提交 | ≤50 次/用户 |

**限制**：仅已上架应用的版本/信息更新；不支持新应用首发；仅主账号（子账号不可用）。首发前的表现与控制台流程见 [first-launch.md](first-launch.md)。

## 签名算法

1. 收集所有请求参数（公共 + 业务），**排除** `sign` 与空值
2. 按参数名 ASCII 升序排序
3. 拼接 `k1=v1&k2=v2&...`（**不做 URL 编码**）
4. `HmacSHA256(access_secret, sign_str)` → 小写 hex → 作为 `sign`

公共参数：

| 参数 | 说明 |
|---|---|
| `user_id` | 开放平台 UserID |
| `timestamp` | 秒级 Unix 时间戳 |
| `sign` | 签名结果 |

## API 路由

| 路由 | 功能 | 建议超时 |
|---|---|---|
| `/query_app_detail` | 查询应用详情 | 30s |
| `/get_file_upload_info` | 获取 COS 预签名 URL + 流水号 | 30s |
| `/update_app` | 提交应用更新 | 60–120s |
| `/query_app_update_status` | 查询审核状态 | 30s |

### 文件上传流程

1. `POST /get_file_upload_info` — 传 `file_type`（apk/img/pdf/video/txt）、`file_name`
2. `PUT` 文件全文到返回的 `pre_sign_url`（`Content-Type: application/octet-stream`）
3. 在 `/update_app` 中引用返回的 `serial_number`

### 仅更新 APK（64 位单包）

`/update_app` 常用字段：

| 参数 | 值 |
|---|---|
| `pkg_name` | 包名 |
| `app_id` | 应用 ID |
| `deploy_type` | `1` = 审核通过后立即发布 |
| `feature` | 版本特性说明 |
| `apk64_flag` | `1` |
| `apk64_file_serial_number` | 上传流水号 |
| `apk64_file_md5` | APK 文件 MD5（32 位小写 hex） |

双包时额外传 `apk32_flag=1`、`apk32_file_serial_number`、`apk32_file_md5`。

> 脚本的 `update` / `publish` 只提交上表字段（外加可选 `deploy_time`），**不提交 `introduce` 等文案字段**。
> 官方 `update_app` 是否支持改应用介绍尚未核实，封装前先查 wiki。

### `query_app_detail` 回读字段（2026-09-11 实测）

| 字段 | 示例 / 说明 |
|---|---|
| `app_id` / `pkg_name` / `app_name` | 基础标识 |
| `version_name` / `version_code` | 最近一次提交的版本 |
| `category` | 分类 ID，如 `17` |
| `age_level` | 年龄分级，如 `12` |
| `operator` / `developer` | 运营 / 开发主体名称 |
| `introduce` | 应用介绍，**上限 500 字，超出被截断** |
| `one_word_summary` | 一句话简介 |
| `feature` | 版本更新说明 |
| `login_flag` / `login_account` | 是否需登录；**`login_account` 明文含测试账号密码** |
| `app_type` / `device_type` / `pay_type` / `demo_video_flag` / `screen_size` / `language` / `is_support_ipv6` | 枚举值，含义以官方 wiki 为准 |

回读里**没有审核状态或上架状态字段**；审核状态只能用 `query_app_update_status`，且只覆盖经 API 提交的更新。

### 审核状态

| audit_status | 含义 |
|---|---|
| 1 | 审核中 |
| 2 | 审核驳回 |
| 3 | 审核通过 |
| 8 | 开发者主动撤销 |

## 常见错误码

| ret | 说明 |
|---|---|
| 1000005 | `pkg_name` 为空（必填） |
| 1000006 | `app_id` 为空（必填） |
| 1000009 | 「请求pkg_name与app_id不匹配」——**兜底码**：首发前所有接口都返回；编造的 app_id 也返回同一个码，不能据此判断哪个参数错 |
| 1000019 | 未申请 access_secret |
| 1000020 | 签名校验失败 |
| 1000011 | 应用尚未上架 |
| 1000012 | 无应用权限 |
| 2000004 | COS 预签名失败 |
| 4000040 | 未传 apk64_file_md5 |
| 4000043 | 未查到文件上传记录 |
| 4000053 | 提交审核失败（见 msg） |
| 5000002 | 未查询到应用审核信息：该应用没有经 API 提交过更新（首发走控制台时即如此） |

完整错误码见官方 wiki §5。
