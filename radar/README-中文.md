# 链盾·热点雷达 0.1 模拟版

本版复用当前链盾 engine.py/runtime_policy.py，在单个Python进程中实现新闻优先的热点→新币名称关联→安全初筛→Jupiter V2双向只读报价→模拟记账与退出。无Redis、AI模型或额外Python依赖。现有链盾APK不受影响，新安卓应用包名为com.chainshield.radar。

**当前范围：SOL自动模拟；三链手动风险查询。没有实盘签名器，不能把配置改成live来交易。没有接入X/Telegram；新闻规则只识别简单实体，名称关联不能证明代币与新闻主体真实相关。**

## 启动与部署

需要Ubuntu的Python 3.10+。从仓库根目录运行：

```bash
export RADAR_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(36))')"
python3 -m radar.server
```

浏览器打开http://127.0.0.1:8787，在设置填写访问密钥。服务器仅监听回环地址。手机必须通过有效HTTPS域名连接，使用radar/deploy/Caddyfile配置反向代理（需要自有域名和证书；Caddy须另行安装）。不要对外开放8787端口。

服务器安装：`sudo bash radar/deploy/install.sh`。默认每60秒扫描，最多5个模拟持仓，初始模拟余额1000USDC；关闭手机仍运行。默认BBC世界新闻和Guardian世界新闻，可用RADAR_FEEDS指定多个HTTPS RSS源。JUPITER_API_KEY可选，无密钥接口是否可用由实时探针确定；接口限额和供应商规则可能变化。

## 少量必要条件

1. 同一实体30分钟内至少两个独立来源、不同标题提及；保留原文、发布时间和首次发现时间。并非付费实时社交热榜，也不宣称新币全覆盖。
2. DexScreener搜索SOL名称/符号精确或完整单词匹配，交易池年龄24小时内。交易池年龄不是铸币年龄；同名冒牌仍可能通过文本匹配。
3. 复用链盾检测。所有高危直接拦截；增发、冻结、转账限制、可变费用、Hook等关键项必须有明确无风险结果，RugCheck不得有风险项。资料可变、报告最新扫描时间等非关键未知项继续展示，**通过初筛不叫“安全认证”**。
4. Jupiter V2买卖方向报价均有效；平台费用必须可读且不超过1%；每次模拟本金约100元人民币（美元兑人民币参考汇率，假设USDC≈1美元）；最多5仓、余额不足不买。

模拟使用报价输出，额外扣0.5%滑点，每边再扣0.03USDC作为网络费用假设。报价内DEX/平台费不重复扣。此模型未包含真实成交失败、MEV、USDC脱锚、ATA租金等全部成本；不能用模拟收益证明能盈利。止盈20%、止损10%、发现高危触发模拟退出；没有卖出报价就保留持仓并标记失败，不伪造成交。禁止误把“有卖出报价”等同于“实际链上卖出成功”。

## 安卓构建

四个中文页面：热点雷达、链盾检查、自动交易、系统设置。仅需网络权限。连接密钥保存在应用私有存储，不加载远程网页，不存钱包私钥。

```bash
./gradlew -p radar/android :app:assembleDebug
```

GitHub Actions工作流“热点雷达模拟版构建验收”执行构建、模拟器安装和真实服务器连接。debug APK可安装但非固定生产签名；后续稳定发行需固定签名。设备测试先用仅限调试构建的测试证书连接CI服务器，交付APK重建时移除此信任，保留系统可信HTTPS证书。

## 测试与证据

```bash
python3 -m unittest discover -s tests -v
python3 -m unittest discover -s radar/tests -v
python3 -m radar.live_probe
```

radar/evidence为实测记录。自动流程正向测试使用明确标识的Fake数据；真实API探针不签名、不广播，也没有验证实际新币的完整正向成交。设备查询允许供应商返回未知，但不能返回伪造安全结论。API可连接不代表其全部字段可靠、永续可用或所有新币均支持。

## 阿里云迁移腾讯云

旧服务器执行`sudo bash radar/deploy/backup.sh /root/radar-backup-日期`，得到包含SQLite一致性快照、源码和环境配置的tar.gz。私下传到新Ubuntu服务器并解压，在新服务器执行`sudo bash source/radar/deploy/restore.sh 解压目录`。目标已有数据库时拒绝覆盖。先停止旧服务器，再启动新服务器；迁移域名解析、HTTPS反代与防火墙，手机连接后核对余额与持仓。归档含访问密钥，不要上传公开仓库。

当前环境没有用户云主机SSH入口、域名或证书，因此尚未部署到阿里云/腾讯云；提供脚本不等于已完成云部署或已实测迁移。
