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

**限制**：仅已上架应用的版本/信息更新；不支持新应用首发；仅主账号（子账号不可用）。

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
| 1000019 | 未申请 access_secret |
| 1000020 | 签名校验失败 |
| 1000011 | 应用尚未上架 |
| 1000012 | 无应用权限 |
| 2000004 | COS 预签名失败 |
| 4000040 | 未传 apk64_file_md5 |
| 4000043 | 未查到文件上传记录 |
| 4000053 | 提交审核失败（见 msg） |

完整错误码见官方 wiki §5。
