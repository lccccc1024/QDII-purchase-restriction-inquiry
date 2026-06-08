# 场外纳斯达克100 / 标普500 基金申购限额监控

自动监控全市场场外（非 ETF）纳斯达克100 和标普500 QDII 基金的申购限额状态，数据来源于天天基金网。

## 快速开始

### Windows
双击 `run.bat`，或：
```bat
run.bat              # 单次扫描（首次自动初始化）
run.bat daemon 3600  # 常驻监控（每小时）
```

### macOS / Linux
```bash
pip install -r requirements.txt
python monitor.py                 # 单次扫描
python monitor.py --once --chart  # 扫描 + 生成图表
python monitor.py --chart-only    # 仅用最近数据生成图表
```

## 命令行参数

| 参数 | 说明 |
|---|---|
| `--init` | 从天天基金网重新发现基金列表，保存到 `fund_list.json` |
| `--once` | 单次扫描全部基金申购状态 |
| `--daemon --interval N` | 常驻监控，每 N 秒扫描一次 |
| `--chart` | 扫描后生成 `chart.png` |
| `--chart-only` | 仅用上次 `status_log.json` 生成图表（无需网络） |
| `--config` | 指定配置文件路径（默认 `config.yaml`） |

## 输出文件

| 文件 | 说明 |
|---|---|
| `report.txt` | 人类可读的扫描报告 |
| `chart.png` | 基金状态一览图表（纳指/标普分开展示） |
| `changelog.csv` | 变更历史（可用 Excel 打开） |
| `status_log.json` | 最近一次扫描的状态快照 |
| `monitor.log` | 详细运行日志 |
| `fund_list.json` | 监控基金列表（可手动编辑） |

## 首次运行

首次运行会：
1. 从天天基金网下载全市场约 2.6 万只基金列表
2. 按关键词（纳斯达克100、标普500）筛选场外人民币 A/C 类份额
3. 逐一查询每只基金的申购状态（约80-120秒）
4. 生成 `report.txt` 和 `chart.png`

## 配置文件 `config.yaml`

```yaml
scan:
  interval: 1800           # daemon 模式扫描间隔（秒）
  timeout: 15              # 单次 HTTP 请求超时（秒）
  delay_between_requests: 1.5  # 请求间隔

notify:
  webhook_url: ""          # 钉钉/飞书/Server酱 Webhook
  webhook_type: "dingtalk"

proxy:
  http: ""                 # HTTP 代理
```

## 常见问题

**中文显示乱码（Windows CMD）**
脚本已自动设置 UTF-8 编码。如仍有问题，手动执行 `chcp 65001` 后再运行。

**图表中文不显示**
需系统安装中文字体（微软雅黑、SimHei 等）。脚本会自动检测可用字体。

**某只基金始终显示"未知"**
可能是页面结构变化导致解析失败。可查看 `monitor.log` 排查。程序不会用"未知"覆盖上一轮有效快照。

**网络请求失败**
检查是否能访问 `fund.eastmoney.com`。如需代理，在 `config.yaml` 的 `proxy` 中设置。

## 项目结构

```
project/
  monitor.py        # 主程序入口
  fetcher.py        # 数据抓取（天天基金 API）
  notifier.py       # 输出通知（控制台/CSV/Webhook）
  chart.py          # 图表生成
  utils.py          # 工具函数
  config.yaml       # 配置文件
  fund_list.json    # 监控基金列表
  run.bat / run.sh  # 一键启动脚本
```
