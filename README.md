# 观测站 · 最小可跑通版本

一个真正定时抓取数据、存库、通过 API 展示的最小项目。目前只接了两个数据源:

1. **CoinGecko 价格快照**(比特币/以太坊/Solana)—— 每 5 分钟抓一次,真正的实时数据。
2. **The Block RSS**—— 每 60 分钟抓一次,示范"新闻类"数据源怎么接。

其余 13 个没有实时源的板块,直接在 `/api/static-topics` 里给出,前端诚实展示"为什么没有",不编时间戳。

## 目录结构

```
observation-station/
  backend/
    main.py          FastAPI 应用 + 定时任务调度
    fetcher.py        抓取逻辑(CoinGecko + RSS),SQLite 读写
    requirements.txt
  frontend/
    index.html         纯 HTML+JS 页面,轮询后端 API
```

## 启动步骤

```bash
cd observation-station/backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

打开浏览器访问 `http://localhost:8000` 即可看到页面。启动时会立刻跑一次抓取,之后按设定频率自动运行,不需要手动干预。

## 我做了什么、你需要做什么

**我做的**:
- 写完了全部代码,语法检查通过(`python -m py_compile` 无报错)。
- 我这边的沙箱环境没有联网权限,所以**没能实际跑一遍验证 CoinGecko 请求是否成功**——代码逻辑是对的,但请在你自己的机器上跑一次确认。

**你需要做的(预计 5 分钟)**:
1. 按上面步骤跑起来。
2. 如果 CoinGecko 请求失败(比如报 429 限流),稍等几分钟重试,免费额度有限但个人用完全够。
3. 打开 `http://localhost:8000`,应该能看到"Web3 / 区块链"板块下出现实时价格条目,以及下方无数据源板块的说明卡片。

## 下一步怎么扩展

想加一个新的"有数据"板块,只需要在 `fetcher.py` 里:
1. 仿照 `fetch_crypto` 或 `fetch_rss` 写一个新的 `fetch_xxx()` 函数,内部调用对应 API 或抓页面,最后调用 `_insert_item(...)` 存库。
2. 在 `main.py` 的 `on_startup` 里加一行 `scheduler.add_job(fetcher.fetch_xxx, "interval", minutes=N, id="fetch_xxx")`。
3. 前端 `index.html` 里的 `topicLabels` 加一个中文标签映射。

不需要改数据库结构,`items` 表是通用的。

## 想把某个"无数据"板块变成"有数据"

把它从 `main.py` 的 `STATIC_TOPICS` 挪到 `fetcher.py` 里写一个新的抓取函数——前提是你能找到一个真实、稳定、可被程序访问的数据源(官网 RSS、公开 API,或者你愿意维护的固定几个信源列表)。如果找不到稳定源,建议保持在"无数据"区,比硬凑一个假实时源要好。
