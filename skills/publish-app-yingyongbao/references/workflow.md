# 腾讯应用开放平台（应用宝）· APK 上架流程

> API 自动发版见 skill：本 skill 的 `SKILL.md`  
> 控制台：[https://app.open.qq.com/p/](https://app.open.qq.com/p/)  
> 官方 API 文档：[wiki 4015262492](https://wikinew.open.qq.com/index.html#/iwiki/4015262492)

---

## 前置条件

- 已有腾讯开放平台开发者账号（主账号，API 不支持子账号）
- 应用已在应用宝**上架**（API 仅支持版本/信息更新，不支持新应用首发）
- 已构建并签名 Release APK
- 应用宝渠道包：`build/app/outputs/channels/yingyongbao-app-release.apk`（VasDolly 渠道名 `yingyongbao`）

---

## 方式一：API 自动发版（推荐）

### 1. 申请 API 密钥

1. 登录 [应用宝开放平台](https://app.open.qq.com/p/)
2. 选择应用 → **账户管理** → **API发布接口**
3. 点击 **申请开通**，获取 `access_secret`
4. 在 **安卓应用管理 → 应用首页** 记录 `app_id` 与 `pkg_name`

### 2. 配置凭据

```bash
mkdir -p ~/.config/ai-ignore-config/<项目名>
cp "$SKILL_DIR/config.example.env" \
   ~/.config/ai-ignore-config/<项目名>/yingyongbao.env
# 填写 YINGYONGBAO_USER_ID / ACCESS_SECRET / APP_ID
```

凭据放在 **`~/.config/ai-ignore-config/<项目名>/`**（仓库外），各台电脑同路径；详见 skill 的「凭据配置」章节。

### 3. 构建渠道包并发版

```bash
fvm flutter build apk --release
VD="${VASDOLLY_JAR:-$HOME/.claude/skills/vasdolly-multi-channel-apk/VasDolly.jar}"
[ -f "$VD" ] || VD=.agents/skills/vasdolly-multi-channel-apk/VasDolly.jar
mkdir -p build/app/outputs/channels/
java -jar "$VD" put -c yingyongbao \
  build/app/outputs/flutter-apk/app-release.apk \
  build/app/outputs/channels/yingyongbao-app-release.apk

PY="$SKILL_DIR/scripts/yingyongbao_publish.py"
python3 "$PY" query-detail
python3 "$PY" publish \
  --apk build/app/outputs/channels/yingyongbao-app-release.apk \
  --feature "版本更新说明" \
  --poll
```

### API 流程概要

1. `POST /query_app_detail` — 确认应用信息
2. `POST /get_file_upload_info` — 获取 COS 预签名 URL
3. `PUT` APK 到 COS
4. `POST /update_app` — 提交版本（`apk64_flag=1` + serial_number + md5 + feature）
5. `POST /query_app_update_status` — 查询审核（可选 `--poll`）

---

## 方式二：控制台手动发版

> 待补充：登录、选择应用、上传 APK、填写更新说明、提交审核等步骤。

---

## 本应用信息

| 属性 | 值 |
| --- | --- |
| 应用名称 | `<应用名>` |
| 包名 | `<applicationId>` |
| 渠道名 | `yingyongbao` |
| 渠道包路径 | `build/app/outputs/channels/yingyongbao-app-release.apk` |

---

## 自动化备注

- **API 限制**：无沙盒；提交后可在控制台撤回审核
- **签名**：HmacSHA256，参数 ASCII 排序后拼接（详见 skill `reference.md`）
- **64 位包**：脚本默认单 64 位包更新；双包需 `--apk32` + `--apk64`
- **测试账号**：应用含登录能力时，`update_app` 可能需传 `login_flag=1` 与 `login_account`（后续扩展）

---

*最后更新：2026-05-29*
