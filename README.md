# 场外纳斯达克100 / 标普500 基金申购限额监控

自动监控全市场场外（非 ETF）纳斯达克100 和标普500 QDII 基金的申购限额状态，数据来源于天天基金网（备用数据源：蛋卷基金），支持 GitHub Actions 每日定时运行并通过 Gmail 推送结果。

## 快速开始

### 本地运行
```bash
pip install -r requirements.txt
python monitor.py                 # 单次扫描
python monitor.py --once --email  # 扫描 + 有变化时邮件推送
python monitor.py --daemon --interval 3600  # 常驻监控
```

### GitHub Actions 每日定时（推荐）
1. 将本仓库推送到 GitHub
2. Gmail 开启两步验证 → 生成**应用专用密码**（16 位）
3. 在仓库 Settings → Secrets and variables → Actions 中添加：
   - `GMAIL_USER`：你的 Gmail 地址
   - `GMAIL_APP_PASSWORD`：应用专用密码
4. 在 `config.yaml` 的 `email` 节填入 `sender`（发件 Gmail）和 `recipient`（收件人）
5. 推送代码后，Actions 将在 **每天北京时间 18:00** 自动运行

首次部署建议到 Actions 页面手动触发 `workflow_dispatch` 验证链路。

## 命令行参数

| 参数 | 说明 |
|---|---|
| `--init` | 从天天基金网重新发现基金列表，保存到 `fund_list.json` |
| `--once` | 单次扫描全部基金申购状态 |
| `--daemon --interval N` | 常驻监控，每 N 秒扫描一次 |
| `--email` | 检测到变化时通过 Gmail 发送邮件（正文=变化明细，附件=全量结果 CSV） |
| `--config` | 指定配置文件路径（默认 `config.yaml`） |

## 输出文件

| 文件 | 说明 |
|---|---|
| `report.txt` | 人类可读的扫描报告 |
| `changelog.csv` | 变更历史（可用 Excel 打开） |
| `status_log.json` | 最近一次扫描的状态快照（GitHub Actions 会提交回仓库作为下次对比基线） |
| `monitor.log` | 详细运行日志 |
| `fund_list.json` | 监控基金列表（可手动编辑） |

## 邮件推送

- **正文**：HTML 格式，直接列出本次**有变化的标的**（基金名称、代码、跟踪指数、旧状态→新状态、限额变化），附扫描时间与全量状态分布摘要
- **附件**：`基金监控结果.csv`，包含**所有被监控标的**的检测结果（扫描时间、代码、简称、指数、状态、限额、数据源），UTF-8 BOM 编码，Excel 可直接打开
- **无变化时不发送邮件**，避免噪音

凭证通过环境变量 `GMAIL_USER` / `GMAIL_APP_PASSWORD` 提供（GitHub Secrets），不会写入代码或配置文件。

## 首次运行

首次运行会：
1. 从天天基金网下载全市场约 2.6 万只基金列表
2. 按关键词（纳斯达克100、标普500）筛选场外人民币 A/C 类份额
3. 逐一查询每只基金的申购状态（约80-120秒）
4. 生成 `report.txt`，有变化时发送邮件

## 数据源与容错

查询优先级依次为：
1. 天天基金手机端 API v1
2. 天天基金手机端 API v2
3. 蛋卷基金 JSON API（备用，天天基金反爬时可用）
4. 天天基金 f10 状态页
5. 天天基金详情页

单只基金所有来源均失败时标记为"未知"，**不会覆盖上一轮有效快照**，避免误报变化。

## 配置文件 `config.yaml`

```yaml
scan:
  interval: 1800           # daemon 模式扫描间隔（秒）
  timeout: 15              # 单次 HTTP 请求超时（秒）
  delay_between_requests: 1.5  # 请求间隔

api:
  fund_list_url: ""        # 可自定义覆盖默认 API 地址
  mobile_api_url: ""
  mobile_api_v2_url: ""
  danjuan_url: ""          # 蛋卷基金备用源

notify:
  webhook_url: ""          # 钉钉/飞书/Server酱 Webhook（可选）

email:
  smtp_host: "smtp.gmail.com"
  smtp_port: 587
  sender: ""               # 发件 Gmail
  recipient: ""            # 收件人（多个用逗号分隔）

proxy:
  http: ""                 # HTTP 代理
```

## 常见问题

**中文显示乱码（Windows CMD）**
脚本已自动设置 UTF-8 编码。如仍有问题，手动执行 `chcp 65001` 后再运行。

**某只基金始终显示"未知"**
可能是页面结构变化导致解析失败。可查看 `monitor.log` 排查。程序不会用"未知"覆盖上一轮有效快照。

**Gmail 发送失败（534 等错误）**
需使用应用专用密码而非登录密码：Google 账户 → 安全性 → 两步验证 → 应用专用密码。

**GitHub Actions 中基金抓取失败**
GitHub Actions 运行在美国 IP，天天基金可能限流。已内置蛋卷基金备用源；如仍失败可考虑在 workflow 中配置代理。

## 项目结构

```
project/
  monitor.py        # 主程序入口
  fetcher.py        # 数据抓取（天天基金 / 蛋卷基金）
  email_sender.py   # Gmail 邮件推送（正文变化明细 + CSV 附件）
  notifier.py       # 输出通知（控制台/CSV/Webhook）
  utils.py          # 工具函数
  config.yaml       # 配置文件
  fund_list.json    # 监控基金列表
  .github/workflows/daily-monitor.yml  # 每日定时任务
  run.bat / run.sh  # 一键启动脚本
```