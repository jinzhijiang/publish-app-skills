# publish-app-skills

国内 Android / HarmonyOS 应用市场发版 skill，通过 Git 统一管理和复用。

这些 skill 原先散在各个 app 仓库里、写死了各自的包名与凭据路径。收拢到这里时一并**去项目化**：
任何 Flutter 项目在自己的仓库目录下跑同一套 skill 就能发版，凭据与项目信息按 git 根目录名自动隔离，互不串台。

## 目录结构

每个 skill 是 `skills/` 下的一个子目录，目录名即 skill 名称：

```
publish-app-skills/
├── skills/
│   ├── publish-app-huawei/           # 华为 AppGallery：首次上架 + API 发版（Android/HarmonyOS）
│   │   ├── SKILL.md
│   │   ├── config.example.env        # 凭据模板，按项目放到 ~/.config/ai-ignore-config/<项目名>/
│   │   ├── agents/openai.yaml        # Codex 互操作
│   │   ├── references/               # reference.md(API)、first-launch.md(首次上架)
│   │   └── scripts/appgallery_publish.py
│   ├── publish-app-honor/            # 荣耀：Publish-API 传包
│   ├── publish-app-oppo/             # OPPO：API 传包
│   ├── publish-app-vivo/             # vivo：API 传包
│   ├── publish-app-xiaomi/           # 小米：自动发布 API
│   ├── publish-app-yingyongbao/      # 应用宝：open.qq.com API（HmacSHA256 + COS 预签名）
│   ├── publish-app-360/              # 360：浏览器流程 + 控制台接口只读查状态
│   │   ├── SKILL.md
│   │   ├── config.example.env        # 应用名/包名/AppID 等项目侧信息，同样按项目隔离
│   │   └── references/workflow.md    # 平台实测：控制台路由、表单约束、选择器
│   ├── publish-app-ali/              # 阿里应用分发 / 九游：同上
│   ├── publish-app-baidu/            # 百度：同上
│   ├── publish-app-lenovo/           # 联想：同上
│   ├── publish-app-samsung/          # 三星 Galaxy Store：同上
│   ├── publish-app-xunfei/           # 科大讯飞 AI 学习机：浏览器流程 + 自带大包上传 harness
│   │   └── scripts/cors_upload_server.py
│   └── vasdolly-multi-channel-apk/   # 渠道包打包 CLI，上面 11 个 skill 都依赖它
│       └── VasDolly.jar
├── scripts/deploy_skills.py          # 部署到 ~/.cc-switch/skills + ~/.claude/skills
└── README.md
```

## 平台一览

| Skill | 发版通道 | 凭据文件 | 备注 |
| --- | --- | --- | --- |
| `publish-app-huawei` | AppGallery Connect API | `appgallery.env` | 服务账号 JWT；覆盖 Android + HarmonyOS，另含首次上架流程 |
| `publish-app-honor` | Publish-API 传包 | `honor.env` | `client_credentials` 换 token |
| `publish-app-oppo` | API 传包 | `oppo.env` | HmacSHA256 签名，token 缓存在凭据目录 |
| `publish-app-vivo` | API 传包 | `vivo.env` | HmacSHA256 签名 |
| `publish-app-xiaomi` | 自动发布 API | `xiaomi.env` | RSA 走系统 `openssl`，不引第三方库 |
| `publish-app-yingyongbao` | open.qq.com API | `yingyongbao.env` | HmacSHA256 + COS 预签名上传 |
| `publish-app-360` | 浏览器 | `360.env` | 无发版 API；状态可在已登录标签页内读接口 |
| `publish-app-ali` | 浏览器 | `ali.env` | 同上 |
| `publish-app-baidu` | 浏览器 | `baidu.env` | 同上，含 AI 合规声明字段 |
| `publish-app-lenovo` | 浏览器 | `lenovo.env` | 仅版本更新，不走建应用/应用认领 |
| `publish-app-samsung` | 浏览器 | `samsung.env` | 需英文默认商店资料；含拒审修复流程 |
| `publish-app-xunfei` | 浏览器 | `xunfei.env` | 请求体加密，状态只能读页面；大包走自带 harness |

## 使用方式

### 部署（推荐）

```bash
python3 scripts/deploy_skills.py
```

部署链路：

```
skills/<name>/  --rsync -a --delete-->  ~/.cc-switch/skills/<name>/  (真目录)
                                        ~/.claude/skills/<name>      (符号链接)
```

装完在任意项目里都能直接调用，不需要每个 app 各存一份。常用参数：

```bash
python3 scripts/deploy_skills.py --list                 # 看仓库里有哪些 skill
python3 scripts/deploy_skills.py --check                # 只报差异，不改文件
python3 scripts/deploy_skills.py publish-app-oppo       # 只部署指定 skill
python3 scripts/deploy_skills.py --prune                # 顺带清理已删除 skill 的残留
```

**本仓库是唯一真源**：`~/.cc-switch/skills/` 下的内容随时会被 `--delete` 覆盖，不要在那里改。

### 凭据与项目信息配置（按项目隔离）

**本仓库不含任何具体应用、开发者主体或凭据信息。**
API 密钥、控制台应用标识（AppID / Content ID）、备案号、分级与付费声明等，一律按调用方项目的 git 根目录名存放：

```bash
# 在目标项目仓库里执行；<项目名> 即 git 根目录名
mkdir -p ~/.config/ai-ignore-config/<项目名>
cp ~/.claude/skills/publish-app-oppo/config.example.env \
   ~/.config/ai-ignore-config/<项目名>/oppo.env
# 本地编辑填写，勿贴到对话
```

读取顺序：`--config PATH` > `~/.config/ai-ignore-config/<git 根目录名>/<vendor>.env` > skill 目录 `config.env`。
项目名可用 `<VENDOR>_PROJECT` 环境变量覆盖（如 `OPPO_PROJECT`）。

带脚本的 6 个 skill 由脚本自己读；纯浏览器的 6 个 skill 在 SKILL.md 里以 `<VENDOR>_APP_NAME` 这类变量名引用，
读不到就停下来问，不会拿别的应用的值顶上。

这条约定的意义：**跑错目录会因缺配置直接报错，不会静默把包发到别的应用**。
带脚本的 skill 可用 `doctor` 子命令自检这一步。

## 添加 Skill

1. 在 `skills/` 下创建以 skill 名称命名的子目录
2. 写 `SKILL.md`（frontmatter 的 `name` 必须与目录名一致）；按需加 `references/`、`scripts/`、`agents/openai.yaml`、`config.example.env`
3. `python3 scripts/deploy_skills.py <name>` 部署验证
4. 提交到 Git

## 注意事项

- **不绑定具体项目**：SKILL.md 与脚本里不写死包名、AppID、OSS 桶、产物绝对路径。
  应用标识走 `config.example.env`，路径用 `$SKILL_DIR`（skill 目录）与相对项目根的路径。
- **凭据不进仓库**：`.gitignore` 挡掉 `config.env` 与一切 `*.env`（`*.example.env` 除外）。
  服务账号密钥文件、证书同理，只在 `~/.config/ai-ignore-config/<项目名>/` 里放绝对路径引用。
- **脚本是单文件、纯标准库**：外部命令只用到 `git`、`rsync`、`java`、`openssl`。
  刻意不抽公共模块，这样 `python3 <skill>/scripts/x.py` 可以直接跑，不需要 `sys.path` 引导。
- **VasDolly 路径按三级解析**：`$VASDOLLY_JAR` > `~/.claude/skills/vasdolly-multi-channel-apk/VasDolly.jar`
  > 项目内 `.agents/skills/vasdolly-multi-channel-apk/VasDolly.jar`。
- **只收「各应用市场发版」这一类**：官网直链发版那种强绑定自家 CDN、站点配置与 CI 的流程不放这里，
  留在各自 app 仓库。
- 提交信息按 `git-cz` 约定：`{emoji}{type}{scope}: {subject}`。
