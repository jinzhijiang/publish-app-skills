---
name: vasdolly-multi-channel-apk
description: Use the bundled VasDolly.jar CLI to read, add, or remove Android channel info on a signed APK for multi-channel distribution. Use when packaging APKs for multiple Chinese app stores (huawei/xiaomi/oppo/vivo/yingyongbao 等), generating 渠道包/多渠道包, reading or writing channel.txt, verifying or stripping VasDolly channel data, or when the user mentions VasDolly, 渠道包, multi-channel APK, v1/v2 签名渠道.
disable-model-invocation: true
---

# VasDolly 多渠道打包

打包阶段用本 skill 自带的 `VasDolly.jar` CLI 给已签名 APK 注入或读取渠道信息。

> 运行期要读回渠道号，调用方项目需自行集成 Tencent VasDolly 运行时库（`com.tencent.vasdolly:helper`）；本 skill 只负责打包阶段的 CLI。

## 何时使用

- 已经 `fvm flutter build apk --release` 生成签名 APK，需要拆出多渠道包
- 验证某个 APK 的签名方式（V1/V2）或当前渠道
- 删除某个 APK 里历史写入的渠道信息
- 用户提到 VasDolly、渠道包、多渠道、`channel.txt`、`-mtc`、FastMode 等关键字

## 前置条件

- 已安装 JDK（`java -version` 可用）
- 已构建并**签名**的 APK（debug/release 都可以，但渠道写入是基于已签名的 APK 上做）
- VasDolly CLI 位置：本 skill 目录下的 `VasDolly.jar`（全局安装时为 `~/.claude/skills/vasdolly-multi-channel-apk/VasDolly.jar`，可用 `$VASDOLLY_JAR` 覆盖）

> Flutter 构建命令参考：`fvm flutter build apk --release`，产物默认在 `build/app/outputs/flutter-apk/app-release.apk`。

## 命令速查

所有命令都在项目根目录执行；为简洁起见，用 `VD` 代指 jar 路径：

```bash
VD="${VASDOLLY_JAR:-$HOME/.claude/skills/vasdolly-multi-channel-apk/VasDolly.jar}"
[ -f "$VD" ] || VD=.agents/skills/vasdolly-multi-channel-apk/VasDolly.jar
```

### 1. 查看帮助

```bash
java -jar "$VD" help
```

### 2. 获取 APK 签名方式（V1 / V2）

```bash
java -jar "$VD" get -s build/app/outputs/flutter-apk/app-release.apk
```

### 3. 获取 APK 渠道信息

```bash
java -jar "$VD" get -c build/app/outputs/flutter-apk/app-release.apk
```

### 4. 删除 APK 渠道信息

```bash
java -jar "$VD" remove -c build/app/outputs/flutter-apk/app-release.apk
```

### 5. 通过渠道字符串批量生成渠道包

`-c` 后跟逗号分隔的渠道名，最后两个参数：基础 APK + 输出目录。

```bash
java -jar "$VD" put -c "huawei,xiaomi,oppo,vivo,yingyongbao" \
  build/app/outputs/flutter-apk/app-release.apk \
  build/app/outputs/channels/
```

### 6. 给单个渠道生成到指定 APK 路径

第三个参数是目标 APK 文件（不是目录）：

```bash
java -jar "$VD" put -c "huawei" \
  build/app/outputs/flutter-apk/app-release.apk \
  build/app/outputs/channels/app-huawei.apk
```

### 7. 通过 `channel.txt` 文件生成渠道包

项目渠道列表见 `android/channel.txt`（一行一个渠道名）。

```bash
java -jar "$VD" put -c android/channel.txt \
  build/app/outputs/flutter-apk/app-release.apk \
  build/app/outputs/channels/
```

### 8. V1 多渠道多线程（渠道数量较多时）

仅 V1 签名场景需要；V2 签名本身已经很快。

```bash
java -jar "$VD" put -mtc android/channel.txt \
  build/app/outputs/flutter-apk/app-release.apk \
  build/app/outputs/channels/
```

### 9. FastMode（跳过强校验，提速 10x+）

适合本地批量出包；正式发版建议关闭以保留校验：

```bash
java -jar "$VD" put -c android/channel.txt -f \
  build/app/outputs/flutter-apk/app-release.apk \
  build/app/outputs/channels/
```

## 推荐工作流

```
Task Progress:
- [ ] fvm flutter build apk --release（生成签名 APK）
- [ ] java -jar "$VD" get -s <apk>  # 确认 V1/V2 签名
- [ ] 准备渠道列表（命令行字符串或 `android/channel.txt`）
- [ ] java -jar "$VD" put -c <渠道源> <base.apk> <outputDir/>
- [ ] 抽样：java -jar "$VD" get -c <outputDir>/xxx.apk 验证渠道写入
- [ ] 如需，归档到 build/app/outputs/channels/
```

## 与项目运行时的衔接

- 注入后的渠道在运行期由 `ChannelReaderUtil.getChannel(ctx)` 读取（已封装在 `AndroidChannelInfoBridge.kt`）
- Flutter 侧通过 `AppChannelService.readChannel()` 调用，返回 `unknown` 表示未写入或读取失败
- 鸿蒙 / iOS / 桌面端不走 VasDolly，`AppChannelService.supported` 已限制为 Android

## 注意事项

- **必须先签名再写渠道**：对未签名 APK 写渠道，安装时会报签名失败
- **不要重复写入**：若 APK 已有渠道，先 `remove -c` 再 `put -c`，或直接基于干净的基础 APK 出包
- **输出目录要存在或可创建**：建议提前 `mkdir -p build/app/outputs/channels/`
- **FastMode `-f` 仅用于本地批量**：正式发版包请去掉 `-f`，保留完整校验
- jar 不要随便升级位置；如需更新版本，从 [VasDolly Releases](https://github.com/Tencent/VasDolly/releases) 下载新 jar 覆盖本 skill 目录下的 `VasDolly.jar` 即可（改完记得重新部署）

## 故障排查

| 现象 | 处理 |
|------|------|
| `java: command not found` | 安装/配置 JDK，确认 `JAVA_HOME` |
| `get -c` 返回空 | APK 未写过渠道，或写入失败；用 `get -s` 先确认签名方式 |
| 安装渠道包提示签名冲突 | 基础 APK 未签名；改用 release 签名 APK 重新 `put` |
| 渠道包过多耗时长 | V1 用 `-mtc` 多线程；本地批量加 `-f` FastMode |
| 找不到 jar | 按 `$VASDOLLY_JAR` > `~/.claude/skills/vasdolly-multi-channel-apk/VasDolly.jar` > 项目内 `.agents/skills/...` 依次找；其余命令仍在项目根目录执行 |
