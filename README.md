# 链盾 1.6.1 · 全中文三链风险查询

此工程对应真实编译的安卓安装包，保留币安链（BNB）、索拉纳链（SOL）、以太坊链（ETH）只读查询。界面、检测说明、错误、更新提示均为中文；数据源名称、代币名称和符号、地址、网址及版本号保留原样。

## 本版能力

- 临时网络或服务错误自动重试一次；限流和授权错误不重复轰炸接口。
- 连续三次接口失败后冷却三十秒，随后允许恢复；故障不会判为安全。
- 在线配置只包含数据：接口版本路径、兼容字段别名、数据源开关、费率单位、中文词库。不能下载执行任意代码。
- 固定维护公钥验证签名，拒绝篡改、旧版、过期、过大、不兼容配置及陌生接口域名。更新失败保留仍有效的上次配置，过期恢复内置配置。
- 在线配置激活后连续三次完整查询均无可用来源时，隔离该配置并恢复内置配置；明确停用数据源时不自动解除停用。
- 前台自动检查维护配置，成功后六小时检查一次，失败后十五分钟可再自动重试；可手动检查。退出应用后不常驻后台。
- 发现正式新版时显示中文说明，打开签名确认的 GitHub 发布页。安装由用户在安卓系统中确认，不支持静默安装。
- 已知英文风险提供中文说明；未收录类型显示中文核查提示，保留原风险等级，不虚构翻译或降为安全。

## 仓库与自动维护

源码仓库：https://github.com/489652639-stack/chainshield 。1.6.1 内置更新地址：`https://raw.githubusercontent.com/489652639-stack/chainshield/main/updates/channel.json`。

每六小时自动执行离线安全回归、真实接口检查。六项接口均通过且 Actions 已配置维护签名密钥时，才续签十四天有效的配置并发布；缺少密钥时会明确报告仅完成健康检查，没有续签。故障不会覆盖既有配置。

首次云端构建和模拟器测试正在验证，实际结果以 `TEST_REPORT.md` 及 Actions 记录为准。源码中的流程定义不代表已经运行通过。自动续签仍需把单独备份的密钥写入 GitHub Actions Secrets，私钥不在公开仓库中。

自动流程能更新受限的兼容配置，核心逻辑改版或新增授权要求仍需维护者修复并发布新版。

## 安装与签名

本版使用独立、固定且已另行备份的安装包签名，关闭应用调试。只申请联网权限，不读取相册、联系人、定位或私钥，不连接钱包，不执行交易。

**1.5 的临时测试签名密钥没有保留，1.6 不能直接覆盖安装 1.5。首次切换需卸载旧版后安装，旧版查询历史会被清除。** 后续继续使用本次固定签名，才能覆盖升级。私钥和密码不在源码包中，应单独保密保存。

## 使用

选择币安链、索拉纳链或以太坊链，粘贴代币合约或铸币地址，点击“开始安全检测”。手机直接获取 GoPlus、Honeypot.is、RugCheck 数据，不需要本次聊天继续打开或电脑常驻。

“未知”表示证据不足。“未见异常”仅描述本次已有信息，不保证未来能卖出或不会撤池。第三方原始报告页面的语言由对方网站决定。

## 验证与构建

本版结果见 `TEST_REPORT.md` 与 Actions；`qa/` 内保留 1.6 的历史证据，不能充当 1.6.1 的设备验收。

```sh
python3 -m unittest discover -s tests -v
python3 tools/check_signature.py
node --check app/src/main/assets/app.js
node --check app/src/main/assets/maintenance.js
python3 tools/channel_live_check.py
```

构建需要 JDK 17、Python 3.11、安卓 SDK 35、构建工具 35.0.0。Gradle Wrapper 8.10.2、AGP 8.7.3、Chaquopy 17.1.0；包含 ARM64、ARMv7、x86_64。根目录 `engine.py`、`runtime_policy.py` 与手机端对应文件保持一致。

使用 `CHAINSHIELD_KEYSTORE`、`CHAINSHIELD_STORE_PASSWORD`、`CHAINSHIELD_KEY_PASSWORD`、`CHAINSHIELD_KEY_ALIAS` 指定固定签名。必要时用 `CHAINSHIELD_BUILD_PYTHON` 指定构建 Python。不要把私钥或密码提交到仓库。

```sh
./gradlew --no-daemon :app:assembleRelease :app:lintRelease
```

安装包位于 `app/build/outputs/apk/release/app-release.apk`。维护发布细节见 `maintenance/更新说明.md`。
