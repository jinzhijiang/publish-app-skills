# vivo API 传包接口摘要

官方文档目录：[API接口传包](https://dev.vivo.com.cn/documentCenter/doc/323)

| 文档 | 链接 |
|---|---|
| API传包服务申请介绍 | https://dev.vivo.com.cn/documentCenter/doc/326 |
| API接入说明（签名） | https://dev.vivo.com.cn/documentCenter/doc/327 |
| 公共返回码 | https://dev.vivo.com.cn/documentCenter/doc/330 |
| 参数字典介绍 | https://dev.vivo.com.cn/documentCenter/doc/344 |
| 应用 apk 包上传 | https://dev.vivo.com.cn/documentCenter/doc/332 |
| icon 文件上传 | https://dev.vivo.com.cn/documentCenter/doc/329 |
| 截图文件上传 | https://dev.vivo.com.cn/documentCenter/doc/331 |
| 应用更新 | https://dev.vivo.com.cn/documentCenter/doc/343 |
| 查询详细信息 | https://dev.vivo.com.cn/documentCenter/doc/346 |
| 应用分阶段创建更新 | https://dev.vivo.com.cn/documentCenter/doc/882 |
| python 调用示例 | https://dev.vivo.com.cn/documentCenter/doc/649 |

## 调用入口

所有接口都 POST 到同一个路由，用 `method` 参数区分：

| 环境 | 地址 |
|---|---|
| 正式 | `https://developer-api.vivo.com.cn/router/rest` |
| 沙箱 | `https://sandbox-developer-api.vivo.com.cn/router/rest` |

沙箱和正式环境的 `access_key` / `access_secret` 要**分别申请**，数据也是隔离的：
沙箱里看不到正式环境的应用，调试更新前得先在沙箱建应用。沙箱每个接口 100 次/天，
正式环境每个传包接口 50 次/天。

## 公共参数与签名

每次调用都要带：

| 参数 | 值 |
|---|---|
| `method` | 接口名，如 `app.sync.update.app` |
| `access_key` | 平台分配 |
| `timestamp` | **毫秒级**，误差 20 分钟内 |
| `format` | `json` |
| `v` | `1.0` |
| `sign_method` | `HMAC-SHA256` |
| `target_app_key` | `developer` |
| `sign` | 见下 |

签名：公共参数 + 业务参数（不含 `sign`）按 key 的 ASCII 升序排序 → `k1=v1&k2=v2` 拼接
→ HmacSHA256（key 为 `access_secret`）→ 小写十六进制。

**文件上传接口签名时要去掉 `file` 参数**，其余表单字段照常参与。

> 文档里 `sign_method` 一处写 `HMAC-SHA256`、一处写 `hmac`。官方 python 示例用的是
> `HMAC-SHA256`，脚本按此取值。

## 接口速查

| 用途 | method | 关键参数 |
|---|---|---|
| 查询应用详情 | `app.query.details` | `packageName` |
| 上传 apk | `app.upload.apk.app` | `packageName`、`file`、`fileMd5`、可选 `stageType=1` |
| 上传 icon | `app.upload.icon` | `packageName`、`file` |
| 上传截图 | `app.upload.screenshot` | `packageName`、`file` |
| 应用同步更新 | `app.sync.update.app` | 见下 |

上传接口返回**流水号** `serialnumber`，更新接口靠它引用刚上传的文件：

```json
{ "code": 0, "subCode": "0", "msg": "成功",
  "data": { "packageName": "...", "serialnumber": "210c...", "versionCode": 12,
            "versionName": "1.2", "fileMd5": "77d8..." } }
```

apk 包上限 3G。

## 应用同步更新（`app.sync.update.app`）

同步接口，返回即代表已提交审核。必传：

| 参数 | 说明 |
|---|---|
| `packageName` | 要和 apk 内包名、平台包名一致 |
| `versionCode` | 必须和上传的 apk 一致，且高于线上版本 |
| `apk` | apk 上传返回的 `serialnumber` |
| `fileMd5` | apk 的 MD5 |
| `onlineType` | 1=实时上架，2=定时上架（需 `scheOnlineTime`，格式 `yyyy-MM-dd HH:mm:ss`） |
| `compatibleDevice` | 1=手机，2=手机和平板，3=平板 |

常用可选：`updateDesc`（新版说明 5~200 字符）、`detailDesc`（应用简介 50~1000 字符）、
`remark`（审核留言 10~200 字符）、`icon` / `screenshot`（流水号）、`mainTitle` / `subTitle`、
`rateAge`、`testAccount`（JSON 字符串）。

和 OPPO 不同，vivo 只更新你传的字段，**不传的资料会保留**，所以常规发版只要
apk + 版本号 + 新版说明就够了。

## 返回码

响应形如 `{"code":0,"subCode":"0","msg":"成功","data":{...}}`。
`code != 0` 是网关/签名层错误，`code == 0` 但 `subCode != "0"` 是业务错误。

公共返回码（`code`）：

| 码 | 描述 | 码 | 描述 |
|---|---|---|---|
| 0 | 成功 | 10007 | 请重新登录，账号验证失败 |
| 404 | 接口不存在 | 10008 | 开发者账号非正常状态 |
| 440 | 缺少参数 | 10010 | 此功能不存在 |
| 441 | 请求参数错误 | 10011 | 当天请求次数超过限制 |
| 500 | 服务器错误 | 10012 | 开发者账号不存在 |
| 10001 | 签名校验失败 | 10013 | 请求参数不合法 |
| 10004 | 没有接口访问权限 | 10014 | API 版本号不正确 |
| 10005 | timestamp 时间戳失效 | 10015 | 签名的验证方式不支持 |
| 10006 | 请求频次过高 | 10018 | 禁止访问，请核对接入信息 |

常见业务返回码（`subCode`）：

| 码 | 描述 |
|---|---|
| 11001 | 包名不正确，未查询到应用 |
| 12010 | 应用正在审核中，不允许操作 |
| 12022 | 当前更新应用待上架，不允许更新 |
| 13002 | 包名不属于当前开发者 |
| 15001 | 上传的 apk 包名与当前包名不一致 |
| 15002 | targetSdkVersion 版本低于之前版本 |
| 15003 / 15010 | 上传的版本号低于之前上传的版本 |
| 15009 | apk 包 md5 与请求参数不一致 |
| 15012 | apk 版本号与请求参数版本号不一致 |
| 20002 / 18007 | 流水号错误 |
| 20016 | 新版说明长度不符合要求（5~200） |
| 20017 | 应用简介长度不符合要求（50~1000） |
| 21003 | 应用资料正在审核中 |
| 21004 | 合同已过期或未签署 |
| 22010 | 定时上架但上架时间为空 |

## 字典项

- **审核状态 `status`**：1 草稿、2 待审核、3 审核通过、4 审核不通过、5 撤销审核
- **上架状态 `saleStatus`**：0 待上架、1 已上架、2 已下架
- **上架类型 `onlineType`**：1 实时上架、2 定时上架
- **应用类型 `appType`**：1 应用、2 游戏
- 应用/游戏分类 ID 见[参数字典介绍](https://dev.vivo.com.cn/documentCenter/doc/344)
