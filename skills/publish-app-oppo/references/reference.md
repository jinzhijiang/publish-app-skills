# OPPO API 传包接口摘要

官方文档目录：[API传包能力](https://open.oppomobile.com/documentation/page/info?id=10997)

| 文档 | 链接 |
|---|---|
| API传包能力接入（鉴权/签名） | https://open.oppomobile.com/documentation/page/info?id=10998 |
| 发布版本 | https://open.oppomobile.com/documentation/page/info?id=10999 |
| 更新资料 | https://open.oppomobile.com/documentation/page/info?id=11000 |
| 获取任务状态 | https://open.oppomobile.com/documentation/page/info?id=11001 |
| 文件上传 | https://open.oppomobile.com/documentation/page/info?id=11003 |
| 查询普通包应用详情 | https://open.oppomobile.com/documentation/page/info?id=11004 |
| 资源分类对照表 | https://open.oppomobile.com/documentation/page/info?id=11017 |
| 审核状态对照表 | https://open.oppomobile.com/documentation/page/info?id=11176 |
| API传包FAQ | https://open.oppomobile.com/documentation/page/info?id=12442 |

## 域名

传包接口用的是 **`https://oop-openapi-cn.heytapmobi.com`**，和 OPPO 其它开放能力
（`https://openapi.heytapmobi.com`，[接口鉴权接入](https://open.oppomobile.com/documentation/page/info?id=12237)）
不是同一套网关，签名规则也不同。本 skill 只涉及前者。

## 鉴权与签名

`GET /developer/v1/token?client_id=<id>&client_secret=<secret>`

```json
{ "errno": 0, "data": { "access_token": "eyJ...", "expire_in": 1615531646 } }
```

- `expire_in` 是**绝对 Unix 时间戳**（token 48 小时有效），不是剩余秒数。
- 重复调用会让上一个 token 在 5 分钟内失效，所以脚本把 token 缓存到
  `~/.config/ai-ignore-config/<项目名>/.oppo_token.json`（权限 0600）。

每个业务接口都要带三个公共参数：`access_token`、`timestamp`（**秒级**，误差 15 分钟内）、`api_sign`。

签名：公共参数 + 业务参数（不含 `api_sign`）按 key 的 ASCII 升序排序 → `k1=v1&k2=v2` 拼接
→ HmacSHA256（key 为 `client_secret`）→ 小写十六进制。

## 接口速查

| 用途 | 路由 | 方法 | 关键参数 |
|---|---|---|---|
| 获取上传配置 | `/resource/v1/upload/get-upload-url` | GET | 仅公共参数，返回 `upload_url` + 一次性 `sign` |
| 文件上传 | 上一步返回的 `upload_url` | POST multipart | `type`（`apk`/`photo`/`resource`）、`sign`、`file` |
| 查询应用详情 | `/resource/v1/app/info` | GET | `pkg_name`、可选 `version_code` |
| 发布版本 | `/resource/v1/app/upd` | POST form | 整份资料，见下 |
| 更新资料（不新增版本） | `/resource/v1/app/updm` | POST form | 同上，少了 apk/分类字段 |
| 获取任务状态 | `/resource/v1/app/task-state` | POST form | `pkg_name`、`version_code` |

文件上传的 `sign` 是**一次性**的，每个文件都要重新调 `get-upload-url`。

响应统一是 `{"errno": 0, "data": {...}}`；失败时 `errno != 0`，`data.message` 是原因。

## 发布版本（`/resource/v1/app/upd`）

异步任务，返回只表示"收下了"，处理结果要查 `task-state`（`task_state`：1 待处理、2 处理成功、3 处理失败）。
建议等待 10 秒以上再查。

普通应用必传字段：

`pkg_name`、`version_code`、`apk_url`、`app_name`、`second_category_id`、`third_category_id`、
`summary`（≤13 字符、无标点空格）、`detail_desc`（≥20 字）、`update_desc`（≥5 字）、
`privacy_source_url`、`icon_url`、`pic_url`（≥2 张）、`online_type`、`test_desc`、
`copyright_url`、`business_username`、`business_email`、`business_mobile`、
`age_level`、`adaptive_equipment`

`apk_url` 是 JSON 字符串数组：

```json
[{"url":"http://.../app.apk","md5":"...","cpu_code":0}]
```

`cpu_code`：非多包应用 `0`，多包 `32` / `64`。

`online_type`：1=审核立即发布，2=定时发布（同时传 `sche_online_time`，格式 `2006-01-02 15:04:05`）。

**注意**：这个接口要求整份资料一起提交，只传 apk 会把商店文案清空。脚本先读
`/resource/v1/app/info` 把线上资料继承回来，只替换 `version_code` / `apk_url` / `update_desc`。

## 审核状态对照表（`audit_status`）

| 值 | 描述 | 值 | 描述 |
|---|---|---|---|
| 0 | 未发布 | 00 | 资质审核中 |
| 1 | 审核中 | 11 | 资质审核通过 |
| 2 | 审核通过 | -11 | 资质审核不通过 |
| 3 | 测试不通过 | -22 | 报备提交成功 |
| 4 | 运营审核中 | 22 | 已冻结 |
| 5 | 运营打回 | 111 | 上线 |
| 6 | 运营通过 | 222 | 下线 |
| 7 | 定时发布 | 444 | 审核不通过 |

## FAQ 要点

- 没有沙箱环境，任何非 `--dry-run` 的写操作都是真的。
- 一套密钥可用于账号下所有 App，不用每个 App 单独申请。
- 发版接口**不能**填自建 CDN 地址，必须用平台的文件上传接口拿到的 URL。
- 发版只能更新已存在的应用，**不能创建新应用**；首次上架要在控制台手动建。
- `version_code` 必须严格大于线上版本，`version_name` 建议同步更新。
