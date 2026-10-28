# python_server — 国内热榜抓取 + DeepSeek 分析

一个只做"榜单发现"的小服务：定时抓取 **微博热搜 / B站热门 / 知乎热榜**，用 DeepSeek 给每条标题打热度分、写理由和简介、提炼热词，每天生成一份 CSV。

不依赖 Node、不依赖 Web 前端、不需要数据库服务；SQLite 只作为内部去重和缓存，CSV 是唯一对外产物。

## 项目结构

```text
python_server/
├── main.py                    # CLI：daemon / once / export / sources / ping
├── config.yaml                # 抓取时间、导出时间、源开关、AI 参数
├── .env.example               # DeepSeek Key 模板
├── requirements.txt           # requests / python-dotenv / PyYAML
├── start_service.bat          # Windows 后台启动（pythonw）
├── stop_service.bat           # 优雅停止
├── README.md                  # 本文件
├── 需求与方案.md               # 设计文档（最终口径）
├── app/
│   ├── config.py              # 配置加载、.env（兼容 BOM）
│   ├── db.py                  # SQLite：items + runs，去重/待分析/按天查询
│   ├── models.py              # RawItem / Analysis
│   ├── utils.py               # 标题归一化、时间、热度解析
│   ├── lock.py                # 单实例文件锁
│   ├── logging_setup.py       # 控制台 + 按天轮转日志
│   ├── ai.py                  # DeepSeek 健康检查、批量分析、JSON 校验
│   ├── pipeline.py            # 抓取→去重→分析→导出 一轮任务
│   ├── exporter.py            # CSV 原子写、按分数排序
│   ├── scheduler.py           # 固定时间调度、23:50 导出
│   └── sources/
│       ├── base.py            # 请求、超时、重试、错误类型
│       ├── weibo.py           # 微博热搜
│       ├── bilibili.py        # B站热门
│       ├── zhihu.py           # 知乎热榜
│       └── __init__.py        # 源注册表
├── tests/
│   └── test_core.py           # 11 个离线单元测试
├── data/                      # 运行时生成（gitignore）
│   ├── hotspot.db
│   ├── service.pid
│   └── exports/
└── logs/
    └── app.log                # 运行时生成（gitignore）
```

## 工作流程

1. 到达 `run_times` 中的固定时间后，依次抓取微博、B站、知乎；
2. 标题清洗、归一化，按 SHA-1 去重入库；重复标题只刷新时间与次数；
3. 当天未分析的条目按每 20 条一批发给 DeepSeek，返回热词、分数、理由、简介、分类；
4. 每轮结束刷新当天 CSV；23:50 再做一次最终导出；
5. 某个源失败只跳过该源；DeepSeek 健康检查失败则整轮放弃，等下一个固定时间。

## 1. 当前行为（v0.1）

- **固定抓取时间**：`00:00 / 08:00 / 16:00`（`config.yaml` 可改）
- **每日导出**：`23:50` 生成当天 CSV
- **不做启动补跑**：进程启动后等下一个固定时间；想立刻抓一轮用 `once`
- **不做次日补导**：错过 23:50 不会在第二天补生成昨天文件
- **跨天重复标题会重新进入当天 CSV**：数据库里同一标题只有一条；再次抓到会刷新"抓取时间"和 `seen_count`，并按最新时间归入当天
- **CSV 排序**：按 AI 热度分从高到低，未分析的排最后
- **热词格式**：JSON 数组字符串，例如 `["雷军", "小米SU7"]`
- **AI 不可用时**：健康检查重试 3 次仍失败，本轮直接放弃（不抓取、不入库）

## 2. 环境准备

本项目在 Windows 上开发，Python 3.10+。

先确认解释器可用：

```bat
python --version
```

如果提示找不到 `python`，请把 Python 加入 PATH，或使用 Anaconda Prompt；也可以把下文命令中的 `python` 替换成你的解释器完整路径。

安装依赖（从仓库根目录进入项目目录）：

```bat
cd python_server
python -m pip install -r requirements.txt
```

## 3. 配置

### 3.1 API Key

复制模板并填写：

```bat
copy .env.example .env
notepad .env
```

```ini
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxx
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
```

Key 申请：<https://platform.deepseek.com/>

### 3.2 抓取与导出

编辑 `config.yaml`：

```yaml
run_times:
  - "00:00"
  - "08:00"
  - "16:00"

export_time: "23:50"

sources:
  weibo: 50
  bilibili: 50
  zhihu: 50
```

- `run_times`：固定抓取点，本地时间，按 8 小时间隔排列即可
- `export_time`：当天 CSV 的最终导出时间
- `sources`：启用的源与每个源最多抓多少条

## 4. 快速验证

```bat
rem 在仓库根目录
cd python_server

rem 1) 只测试数据源，不花钱
python main.py sources --limit 3

rem 2) 只抓取入库并导出，不调用 AI
python main.py once --no-ai

rem 3) 测试 DeepSeek 连通性
python main.py ping

rem 4) 完整跑一轮（会消耗 AI 费用）
python main.py once
```

生成的 CSV：

```
data\exports\2026-10-28_hotspots.csv
```

## 5. 常驻运行

### 5.1 前台（第一次建议这样观察日志）

```bat
python main.py
```

关闭窗口即停止。

### 5.2 后台（日常使用）

```bat
start_service.bat
stop_service.bat
```

- `start_service.bat` 会自动探测可用的 Python（`PYTHON_EXE`、`pythonw`、`python`、常见安装位置）；如果都找不到，先设置 `PYTHON_EXE` 为解释器路径；
- 用 `pythonw` 启动，没有黑窗口，日志写入 `logs\app.log`；
- PID 写入 `data\service.pid`；
- `stop_service.bat` 先写 `data\stop.flag` 让进程优雅退出，最多等 60 秒，超时才强制结束。

启动后不会立刻抓取，日志会打印"下次抓取"时间。想马上有一份数据，先执行一次 `once`。

## 6. 输出 CSV

路径：`data\exports\YYYY-MM-DD_hotspots.csv`，UTF-8 带 BOM，Excel 直接打开不乱码。

| 列 | 说明 |
|---|---|
| 抓取时间 | 该标题**最近一次**被抓到的时间 |
| 来源 | 微博热搜 / B站热门 / 知乎热榜 |
| 原标题 | 原始标题 |
| 热词 | JSON 数组，如 `["雷军", "小米SU7"]` |
| AI热度分 | 0–100，未分析为空 |
| 评分理由 | AI 给分依据 |
| 简介 | 一句话说明 |
| 分类 | 科技/财经/社会/… |
| 榜单排名 | 平台原始排名 |
| 平台热度 | 微博热度值 / B站播放量 / 知乎热度 |
| 链接 | 原文地址 |
| 发布时间 | 平台发布时间，没有则为空 |

排序：`AI热度分` 降序，空分排最后；同分按抓取时间倒序。

> 热词列在 CSV 原文里会被整体加引号并转义，这是 CSV 的正常行为；Excel 打开后显示为 `["a", "b"]`。

### 6.1 AI 判断了什么

每批 20 条，把「来源 + 标题」发给 `deepseek-chat`，要求只返回 JSON：

| 字段 | 含义 |
|---|---|
| `hot_words` | 能代表事件主体的短语（人名/品牌/作品/地名/型号/事件名等），数量不设上限，排除"网友、视频、回应"这类通用词 |
| `score` | 0–100，信息价值 + 传播潜力，不等于平台热度 |
| `reason` | 打分依据，最多 50 字 |
| `summary` | 一句话说明，最多 40 字 |
| `category` | 科技/财经/社会/娱乐/体育/游戏/汽车/教育/健康/其他 |
| `is_junk` | 是否广告/营销号/无意义内容 |

Prompt 在 `app/ai.py` 的 `SYSTEM_PROMPT`，可以直接改措辞；改完建议先 `once` 跑一小批看效果。

只发送标题，不发送正文，目的是控制成本；B站简介、知乎摘要等只存在数据库 `extra` 字段里，不参与分析。

## 7. 去重规则

- 标题先做归一化：全半角统一、去 `#`、去空白和标点、忽略大小写；
- 归一化结果取 SHA-1，SQLite `UNIQUE` 约束保证全局一条；
- 同一标题再次抓到：
  - `seen_count + 1`
  - `fetched_at` 刷新为最新抓取时间
  - `last_seen_at` 更新
  - **不再调用 AI**
- `first_seen_at` 保留首次抓到的时间，仅内部使用；
- 不同标题但同一事件（如"雷军回应"和"小米回应"）不会合并。

## 8. 数据与日志

```
data/
├── hotspot.db          # SQLite，items + runs 两张表
├── service.pid         # 后台进程 PID
├── stop.flag           # 停止请求（临时）
└── exports/
    └── 2026-10-28_hotspots.csv

logs/
└── app.log             # 按天轮转，保留 14 天
```

备份：复制 `data\hotspot.db` 即可；CSV 可随时用 `export` 从库中重新生成。

## 9. 命令一览

| 命令 | 作用 |
|---|---|
| `python main.py` | 常驻服务（默认） |
| `python main.py daemon` | 同上，显式写法 |
| `python main.py once` | 立刻跑一轮（抓取 + AI + 导出） |
| `python main.py once --no-ai` | 立刻跑一轮，跳过 AI |
| `python main.py export --date 2026-10-28` | 从数据库重新导出指定日期 |
| `python main.py sources --limit 3` | 测试各数据源 |
| `python main.py ping` | 测试 DeepSeek 连通性 |

## 10. 新增数据源

1. 在 `app/sources/` 新建类，继承 `BaseSource`，实现：

   ```python
   def fetch(self, limit: int) -> list[RawItem]:
       ...
   ```

2. 在 `app/sources/__init__.py` 注册 `SOURCE_CLASSES` 和 `SOURCE_LABELS`；
3. 在 `config.yaml` 的 `sources:` 下加名字和条数。

pipeline、数据库、CSV 不需要改。

## 11. 常见问题

**知乎返回 401？**
`www.zhihu.com` 的接口现在要求登录；本项目改用 `api.zhihu.com/topstory/hot-lists/total` 匿名接口。若以后也被封，日志会告警并跳过该源。

**B站 412？**
已带随机 `buvid3` cookie；如果仍失败，降低频率或换网络。

**AI 报 401/403/404？**
Key 无效、base_url 或模型名不对。`ping` 会直接给出提示，不会重试。

**AI 临时不可用？**
`run_once` 会先做健康检查，重试 3 次（5s/15s/30s）；仍失败则本轮状态 `ai_unavailable`，不抓取。等下一个固定时间自动再试。

**CSV 打不开或没更新？**
如果文件正在 Excel 中打开，导出会保留旧文件并记录警告；关闭 Excel 后执行 `python main.py export` 即可。

**改了 `run_times` 要重启吗？**
要。配置在进程启动时读取。

**`start_service.bat` 提示 `service.pid` 已存在？**
说明上次可能是被强制结束的，`data\service.pid` 成了残留。确认没有 pythonw 在跑后，删除 `data\service.pid` 再启动。

**为什么启动后一直没抓取？**
这是固定时间调度的预期行为：启动时不会立即抓取，只等下一个 `run_times`。想立刻验证用 `python main.py once`。

## 12. 测试

```bat
python -m unittest discover -s tests -v
```

覆盖：标题归一化、热度解析、去重与时间刷新、CSV 排序、热词 JSON 解析、固定时间计算。

## 13. 交付与验证状态

本地测试已完成：

- 微博 / B站 / 知乎三源实时抓取（知乎已切换为 `api.zhihu.com` 匿名接口）；
- `once --no-ai` 完整跑通：抓取入库、CSV 12 列、UTF-8 BOM；
- 二次抓取去重：不新增行，`seen_count` 增加，`fetched_at` 刷新为最新时间；
- 11 个离线单元测试全部通过；
- `start_service.bat` 能拉起 `pythonw` 并写入 `service.pid`。

尚未验证（按约定等确认后再做）：

- 真实 DeepSeek 调用：当前未配置 Key，`ping` 与 `once` 的 AI 字段尚未实测；
- 固定时间自动触发：需要等到 00:00 / 08:00 / 16:00，或临时改 `run_times` 做联调；
- `stop_service.bat` 的最终联调：脚本已改为"写 stop.flag → 等待 pid 文件消失 → 超时才 taskkill"，尚未做完整验证。

测试过程中生成的 `data/`、`logs/`、临时 `.env` 已清理，首次运行会自动创建。
