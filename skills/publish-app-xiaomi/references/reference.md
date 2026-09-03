# 小米自动发布接口参考

来源：

- <https://dev.mi.com/xiaomihyperos/documentation/detail?pId=1134>（更新时间：2026-02-02 13:39:00）
- <https://t1.market.xiaomi.com/download/AppStore/09b54e4c74d644a292dc96a1ca379b04f13493eab/Example.java>
- <https://t1.market.xiaomi.com/download/AppStore/0a6456feeba9a4835a6900ae22189cab5df680e68/Example.py>

## 基础信息

- API Base：`https://api.developer.xiaomi.com/devupload`
- 请求协议：HTTP/1.1，POST
- 数据编码：JSON，UTF-8
- 附件字段用 multipart/form-data 上传
- 无测试环境；线上调试成功后需在控制台撤回审核

## SIG 生成

1. 计算 `RequestData` JSON 字符串 MD5；文件字段计算整个文件 MD5。
2. 生成签名前 JSON：

```json
{
  "sig": [
    {"name": "RequestData", "hash": "RequestData json字符串的md5 32位小写值"},
    {"name": "apk", "hash": "apk文件的md5 32位小写值"}
  ],
  "password": "小米 API 私钥"
}
```

3. 用小米分配的公钥证书做 RSA/PKCS1Padding 分段加密，并输出小写 hex。官方 Java 示例使用 `RSA/NONE/PKCS1Padding`，官方 Python 示例使用 `Crypto.Cipher.PKCS1_v1_5`；1024-bit key 时每段明文最大 117 字节。

本 skill 的 `xiaomi_publish.py` 按官方 Python / Java 示例的协议实现，但为了避免给项目增加 `Crypto`、`cryptography`、`requests` 依赖，改用 Python 标准库加系统 `openssl` 命令完成请求和 RSA/PKCS1 加密。

## 接口

### `/dev/query`

按包名查询当前账号下最新应用详情。

`RequestData`：

| 字段 | 必选 | 说明 |
|---|---|---|
| `packageName` | 是 | 应用包名 |
| `userName` | 是 | 小米开发者站登录邮箱 |

返回重点字段：

| 字段 | 说明 |
|---|---|
| `result` | `0` 成功，非 0 失败；`-7` 表示包名被其他开发者占用 |
| `packageInfo` | 应用包信息，含 `appName`、`versionName`、`versionCode`、`packageName` |
| `create` | 是否允许新增该包名应用 |
| `updateVersion` | 是否允许版本更新 |
| `updateInfo` | 是否允许应用信息更新 |

### `/dev/category`

查询应用分类；无请求参数。

### `/dev/push`

提交应用新增、更新包、内容更新。

表单字段：

| 字段 | 必选 | 说明 |
|---|---|---|
| `RequestData` | 是 | JSON 字符串 |
| `SIG` | 是 | 加密签名 |
| `apk` | 条件必选 | 新增和更新包时必传 |
| `secondApk` | 可选 | 双包发布时传另一个 APK，32/64 位顺序不限 |
| `icon` | 新增必选 | 应用图标 |
| `screenshot_1`..`screenshot_5` | 新增条件必选 | 手机截图 |
| `screenshot_pad_1`..`screenshot_pad_5` | 条件必选 | `suitableType=1/2` 新增时的平板截图 |

`RequestData`：

| 字段 | 必选 | 说明 |
|---|---|---|
| `userName` | 是 | 小米开发者站登录邮箱 |
| `synchroType` | 是 | `0` 新增，`1` 更新包，`2` 内容更新 |
| `appInfo` | 是 | JSON 字符串，内容见下 |

`appInfo` 常用字段：

| 字段 | 必选 | 说明 |
|---|---|---|
| `appName` | 新增必选 | 应用名称 |
| `packageName` | 是 | 包名 |
| `publisherName` | 可选 | 开发者名称 |
| `versionName` | 可选 | 默认读取 APK |
| `category` | 新增必选 | 分类 ID，用 `category` 查询 |
| `keyWords` | 新增必选 | 搜索关键字，空格分隔 |
| `desc` | 新增必选 | 应用介绍 |
| `updateDesc` | 更新必选 | 更新说明 |
| `brief` | 新增必选 | 一句话简介 |
| `privacyUrl` | 必选 | 隐私政策 URL |
| `testAccount` | 可选 | JSON 字符串，2026-02-04 起必须是结构化格式 |
| `onlineTime` | 可选 | 定时上线时间，毫秒时间戳 |
| `suitableType` | 可选 | `0` 手机，`1` 平板，`2` 手机和平板；默认手机 |

`testAccount` 新结构示例：

```json
{
  "zh_CN": {
    "accounts": [
      {"t": 1, "a": "account", "p": "password", "c": "invite-code"}
    ],
    "auditNotes": "审核补充说明"
  }
}
```

`accounts[].t`：`1` 账号密码登录，`2` 短信验证码登录。`a` / `p` / `c` 均限制 50 字符以内，账号和密码、手机号和验证码必须同时填写。

### `/dev/pushChannelApk`

向在架普通应用提交渠道包。

`RequestData`：

| 字段 | 必选 | 说明 |
|---|---|---|
| `userName` | 是 | 小米开发者站登录邮箱 |
| `apkChannel` | 是 | 渠道名 |

文件字段：`channelApk`。

## 常见错误码

| 错误码 | 说明 |
|---|---|
| `-10000` | 参数格式、公钥加密、JSON 或整体调用方式有误 |
| `-2` | `appInfo.packageName` 和 APK 解析出的包名不一致 |
| `-20014` | 私钥/密码错误，检查是否重置过私钥 |
| `-32` | 未创建包名；删除应用后也需要重新创建包名 |
| `-92` | APK 不满足要求，如同版本同 APK 更新 |
| `-20002` | 数字签名异常，检查 SIG 明文 JSON 和公钥加密 |
| `-20029` | `RequestData` 不是合法 JSON |
| `-20030` | SIG 明文不是合法 JSON |
| `-20034` | `testAccount` 不是合法 JSON |
