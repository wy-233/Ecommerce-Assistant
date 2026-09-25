# Ecommerce Assistant
基于 Python、FastAPI、LangGraph 和 Streamlit 实现的跨境电商 AI 助手，支持售后知识库问答、订单查询、库存查询和物流查询。

仓库地址：<https://github.com/wy-233/Ecommerce-Assistant>

## 当前状态

截至 2026-09-26，第一阶段 MVP 的核心链路已经完成：

- FastAPI、Streamlit 工作台和独立 Web 前端均可运行；
- Agent、API 和工作台复用 `tools/database.py` 的统一业务查询层；
- 订单、库存和物流数据由 SQLite 确定性查询，不允许模型猜测业务数据；
- 商品与仓库主数据、SKU 引用约束、数据库迁移和知识文章检索已经落地；
- Dashboard 与库存看板已完成可视化优化；
- 全量测试基线为 `203 passed`，原 Starlette / AnyIO 弃用 warning 已消除。

当前仍属于演示型 MVP：默认使用 Demo 数据，尚未提供完整用户登录、API 鉴权、调用限流和生产级 Demo/Real 数据隔离。接入真实订单数据或公开部署前，请先完成这些安全能力。

## 1. 核心功能

当前实现的查询链路：

```
用户问题
  ↓
意图识别
  ├── 售后/商品问题 → RAG 知识库
  ├── 订单问题     → 查询订单工具
  ├── 库存问题     → 查询库存工具
  └── 物流问题     → 查询物流工具
```
暂不实现：

- 真实 ERP 对接；
- 退款和改地址；
- 多 Agent；
- 用户登录；
- 模型训练。

### 运营工作台

Streamlit 工作台包括：

- 首页运营指标、最近订单、库存预警和物流异常；
- 订单管理：订单筛选、订单商品和多包裹信息；
- 库存看板：SKU、商品名称、仓库和库存状态筛选；
- 可售库存与安全库存阈值图：红色表示缺货、橙色表示库存不足、绿色表示正常，深灰短线表示安全库存线；
- 物流跟踪：按状态和关键字筛选，并按时间顺序展示轨迹；
- AI 助手：模型选择、原生对话界面、工具调用和知识来源展示。

库存状态统一使用以下规则：

| 条件 | 状态码 | 展示名 |
| --- | --- | --- |
| `available <= 0` | `out_of_stock` | 缺货 |
| `available <= safety_stock` | `low_stock` | 库存不足 |
| `available > safety_stock` | `normal` | 正常 |

## 2. 技术栈

- Python `>=3.12,<3.15`
- FastAPI
- LangGraph
- Pydantic
- HTTPX
- Streamlit
- SQLite
- uv
- Docker Compose
Python 版本要求以本仓库的 [`pyproject.toml`](pyproject.toml) 为准。

## 3. 项目结构

```
ecommerce-ai-assistant/
├── src/
│   ├── ecommerce_assistant/
│   │   ├── agents/ecommerce_assistant.py   # LangGraph 编排：意图路由 + 结构化回答
│   │   ├── api/service.py                  # FastAPI 应用（含 CORS、SSE）
│   │   ├── client/client.py                # AgentClient（Streamlit 调用后端）
│   │   ├── db/init_db.py                   # 建表、播种、引用完整性校验
│   │   ├── db/chat_dao.py                  # 会话与消息读写
│   │   ├── llm/client.py                   # 中转站调用、模型清单
│   │   ├── pages/                          # Streamlit 多页：订单 / 库存 / 物流
│   │   ├── rag/retriever.py                # 知识库检索，返回结构化来源
│   │   ├── schema/schema.py                # 接口模型（含 ChatMessage）
│   │   ├── schema/routes.py                # route 枚举与工具名映射
│   │   ├── schema/statuses.py              # 状态码 -> 中文标签
│   │   ├── tools/database.py               # 业务查询层（唯一查询入口）
│   │   ├── tools/{order,inventory,logistics}.py  # Agent 工具
│   │   ├── workbench/queries.py            # 工作台只读查询层
│   │   └── streamlit_app.py                # Streamlit 首页（含模型选择）
│   └── run_service.py                      # 后端启动入口（8084）
├── frontend/
│   ├── index.html                          # 独立 Web 前端：路由分拣台
│   └── README.md
├── design/
│   ├── DESIGN.md                           # 设计语言
│   ├── FRONTEND-SPEC.md                    # 前端实现规格（框架无关）
│   ├── tokens.json                         # 机器可读 token
│   ├── index.html                          # 设计参照实现
│   └── index.v0.1-prototype.html           # 早期原型
├── data/
│   ├── demo/*.csv                          # 演示数据的权威源
│   ├── ecommerce_assistant.db              # SQLite 库（运行后生成）
│   ├── return_policy.md
│   └── shipping_policy.md
├── docs/
│   ├── PRD.md                              # 需求与验收（v0.3）
│   ├── WORKBENCH_PLAN.md                   # 数据库设计与扩展基线
│   └── REAL_DATA_IMPORT.md
├── scripts/
│   ├── init_database.py                    # 建库 + 播种（幂等）
│   ├── init_demo_data.py                   # 从 data/demo/*.csv 重建演示数据
│   └── import_data.py                      # 真实数据导入
├── tests/
├── Dockerfile                              # 多阶段构建，依赖用 uv sync --frozen 装
├── docker-compose.yml                      # api + streamlit + web 三个服务
├── .dockerignore
├── .env.example
├── pyproject.toml
├── uv.lock
└── README.md
```

## 4. 环境配置
复制环境变量文件：

```
Copy-Item .env.example .env
```
最小配置：

```
OPENAI_API_KEY=your_api_key
OPENAI_BASE_URL=https://aihub.top/v1
OPENAI_MODEL=gpt-5.6-sol
```

| 变量 | 作用 |
| --- | --- |
| `OPENAI_API_KEY` | 中转站 Key，只放在 `.env`，不要提交到 Git |
| `OPENAI_BASE_URL` | 中转站地址，需兼容 OpenAI 的 `/chat/completions` |
| `OPENAI_MODEL` | 未在页面选择模型时的默认模型 |
| `OPENAI_MODELS` | 「回复模型」下拉框的候选清单，逗号分隔；留空则只用 `OPENAI_MODEL` |
| `ECOMMERCE_DB_PATH` | 覆盖 SQLite 库路径，默认 `data/ecommerce_assistant.db` |
| `API_BASE_URL` | Streamlit 调用的后端地址，默认 `http://localhost:8084` |

独立 Web 前端不走环境变量：后端地址写在 `frontend/index.html` 顶部的 `API_BASE` 常量里，改端口时同步修改（见 [`frontend/README.md`](frontend/README.md)）。

### 模型选择
工作台首页「AI 助手对话」区域上方有「回复模型」下拉框，选项来自后端 `GET /models`：

- 默认读取 `.env` 的 `OPENAI_MODELS` 短清单，不产生额外网络请求；
- 点「拉取全部模型」会向后端请求 `GET /models?include_remote=true`，由后端实时读取中转站 `GET {OPENAI_BASE_URL}/models` 并与短清单合并；拉取失败则保留短清单并在页面提示降级；
- 选中的模型随 `POST /ecommerce-assistant/invoke` 的 `model` 字段下发，服务端为空时回退 `OPENAI_MODEL`。

**作用范围**：模型只影响售后政策（`rag`）与通用问答（`llm`）两个分支。订单、库存、物流三条分支由确定性 SQL 查询得出，不调用模型——这是「不允许大模型猜测业务数据」约束的直接结果，页面会在气泡上方标注实际走的是模型还是工具。

## 5. 安装依赖

获取代码：

```powershell
git clone https://github.com/wy-233/Ecommerce-Assistant.git
Set-Location Ecommerce-Assistant
```

安装依赖：

```powershell
uv sync --frozen
```

如果尚未安装 `uv`，请先按 [uv 官方安装说明](https://docs.astral.sh/uv/getting-started/installation/)完成安装。

### 初始化数据库

工作台页面与订单、库存、物流工具共用同一个 SQLite 数据库 `data/ecommerce_assistant.db`。服务启动时会自动初始化；如需预先建库并查看完整性报告，可显式执行：

```
uv run python scripts/init_database.py
```

该命令是幂等的：建表与建索引使用 `IF NOT EXISTS`，仅在 5 张核心业务表（`orders`、`order_items`、`inventory`、`shipments`、`tracking_events`）**全部为空**时才播种演示数据，不会覆盖已有数据。初始化会建立 `products`、`warehouses` 主数据表，从旧库存回填名称，并补齐 `inventory → products/warehouses` 与 `order_items.sku → inventory.sku` 外键；发现无法映射的引用时会列出记录并中止，不会静默删除历史数据。命令结束会打印主数据和业务表行数、外键强制状态与引用完整性报告。

如需把演示数据恢复到 `data/demo/*.csv` 的干净基线，显式重建：

```
uv run python scripts/init_database.py --reset-demo
```

`--reset-demo` 会清空上述 5 张核心业务表及 `products`、`warehouses` 主数据表，并在单个事务内重新导入 `data/demo/` 下的 CSV，属破坏性操作，仅用于重置演示环境。

导入真实数据参考 [`docs/REAL_DATA_IMPORT.md`](docs/REAL_DATA_IMPORT.md)，表设计与迁移方案参考 [`docs/WORKBENCH_PLAN.md`](docs/WORKBENCH_PLAN.md)。

## 6. 启动后端

```
python src/run_service.py
```

后端地址（端口来自 `src/run_service.py`，不是 8080）：

```
http://localhost:8084
```

接口文档：

```
http://localhost:8084/docs
```

服务启动时会通过 FastAPI 的 lifespan 钩子执行一次建库与播种（幂等），因此单独跑
`scripts/init_database.py` 不是启动服务的必要条件；它用于预先检查初始化结果，或配合 `--reset-demo` 显式重建演示数据。

## 7. 启动前端

两套前端并存，共用上面这个后端，可任选或同时启动。

### 7.1 Web 前端（分拣台，默认演示入口）

无需构建，直接打开 `frontend/index.html` 即可：

```
start frontend/index.html
```

或用任意静态服务器（推荐，避免 `file://` 的一些浏览器限制）：

```
python -m http.server 5500 --directory frontend
```

前端地址：

```
http://localhost:5500/index.html
```

后端已放行 `file://` 来源的跨域请求，双击打开也能连上。细节见 [`frontend/README.md`](frontend/README.md)。

### 7.2 Streamlit 工作台（内部看板）

另开一个终端：

```
uv run streamlit run src/ecommerce_assistant/streamlit_app.py
```

前端地址通常是：

```
http://localhost:8501
```

工作台首页会显示 6 个核心指标，并提供订单管理、库存看板和物流跟踪三个子页面入口。库存看板中的彩色横条表示可售库存，深灰短线表示安全库存阈值；风险 SKU 会按“缺货 → 库存不足 → 正常”排序。

## 8. Docker 本地部署

一次起齐三个服务：后端 API（8084）、Streamlit 工作台（8501）、Web 前端分拣台（5500）。

> 当前 `docker-compose.yml` 定位为**本地开发与演示配置**，会将 8084、8501、5500 三个端口发布到宿主机，且 `ea-data` 目前只挂载到 API 容器。初始 Demo 数据虽然一致，但运行后修改数据时，Streamlit 的直接查询可能与 API 数据分叉，因此不应原样用于公网生产环境。生产配置必须让 API 与 Streamlit 挂载同一个数据库卷，并增加 HTTPS 反向代理，只暴露 80/443。

### 8.1 前置

- Docker Desktop 已启动（确认使用 Linux 容器）
- 项目根有 `.env`：`Copy-Item .env.example .env` 后填入中转站 Key

### 8.2 启动

```
docker compose up -d --build
```

| 入口 | 地址 |
| --- | --- |
| Web 前端（分拣台） | http://localhost:5500 |
| Streamlit 工作台 | http://localhost:8501 |
| 接口文档 | http://localhost:8084/docs |

> **首次构建慢或拉包超时？** 容器出网会经过 Docker Desktop 配置的系统代理。实测经代理直连 `pypi.org` 只有约 65 KB/s 并会整片超时，因此 Dockerfile 默认把依赖源指向阿里云镜像（约 346 KB/s）。注意 `uv.lock` 里记的是 PyPI 绝对下载地址，`uv sync --frozen` 会照抄这些 URL 而不走镜像，所以构建时会先把锁里的下载域名改写成镜像域名（版本与 sha256 不变）。要换源：
>
> ```
> docker build --build-arg PYPI_MIRROR=https://mirrors.cloud.tencent.com/pypi/simple/ -t ecommerce-assistant:local .
> ```

### 8.3 常用操作

```
docker compose ps                  # 状态与健康检查
docker compose logs -f api         # 跟后端日志
docker compose down                # 停止并删容器（数据卷保留）
docker compose down -v             # 危险：连数据卷一起删除，下次启动重新播种
docker compose up -d --build api   # 只重建后端
```

### 8.4 设计取舍

| 事项 | 做法 | 原因 |
| --- | --- | --- |
| 依赖安装 | 构建阶段 `uv sync --frozen` 读 `uv.lock` | 与本地开发版本一致。不用 `pip install -e .`：它忽略锁文件，容器内外会漂 |
| 依赖源 | 默认走阿里云 PyPI 镜像，可用 `--build-arg PYPI_MIRROR=...` 覆盖 | 容器出网会经过 Docker Desktop 配的系统代理，拉 pypi.org 实测只有 ~65 KB/s；国内镜像直连实测 ~346 KB/s（约 5 倍）。清华 / 中科大镜像对 `uv` 的 wheel 返回 403，未采用 |
| 镜像分层 | 先复制 `pyproject.toml` / `uv.lock` 装依赖，再复制源码 | 改源码不必重装依赖 |
| 密钥 | `.env` 进 `.dockerignore`，仅由 `env_file` 运行期注入，且只挂 `api` | 密钥不进镜像层；看板与静态页容器不需要它 |
| 数据库 | API 使用 named volume `ea-data` 挂 `/app/data/db`，用 `ECOMMERCE_DB_PATH` 指过去 | 当前是本地演示配置；生产环境还需将同一 volume 挂到 Streamlit。若直接挂 `/app/data`，会连镜像里的 `data/demo/*.csv`（播种源）一起遮住 |
| 容器用户 | 非 root（uid 10001） | 卷属主在镜像里就交给它，容器内可写 |
| 启动顺序 | `api` 带 healthcheck，另两个用 `depends_on: service_healthy` | 否则看板先起来会连不上后端 |
| 建库播种 | 由 FastAPI lifespan 在容器首次启动时完成 | 镜像里不带 `.db`，避免把本机状态带进容器 |
| Web 前端 | 复用同一镜像跑 `python -m http.server` | 少拉一个镜像；静态演示够用，上生产建议换 nginx |

`frontend/index.html` 里的 `API_BASE` 写的是 `http://localhost:8084`，对应宿主发布端口；改宿主端口时同步改这个常量。

### 8.5 公网部署边界

推荐的公网结构是：

```text
用户浏览器
  → Caddy / Nginx（域名、HTTPS、访问保护）
  → Streamlit
  → FastAPI
  → SQLite 持久化卷
```

上线前至少确认：

1. 只有反向代理发布 80/443，8084、8501、5500 不直接暴露公网；
2. API 与 Streamlit 指向同一数据库文件并挂载同一持久化卷；
3. `.env` 仅保存在服务器，不进入 Git 或镜像；
4. 增加登录或 Basic Auth、API 限流和模型调用额度保护；
5. 建立 SQLite 自动备份和恢复验证；
6. 只展示 Demo 数据，或者完成 Demo/Real 隔离和真实数据授权；
7. 独立 Web 前端的 `API_BASE` 改为公网 HTTPS API 地址，不能继续使用 `localhost`。

### 8.6 与不用 Docker 的关系

Docker 只是把第 5～7 节的步骤容器化，两边行为一致。本机已装 uv 时，直接按第 5～7 节跑更快；要一次性拉起三个服务或给别人复现，用 Docker。

## 9. 主要接口

### 查看服务信息

```
GET /info
```
返回可用 Agent 和模型。

### 查看可选模型

```
GET /models?include_remote=false
```
默认返回 `.env` 中 `OPENAI_MODELS` 配置的短清单。`include_remote=true` 时额外合并中转站 `GET {base_url}/models` 的结果，`source` 变为 `merged`；拉取失败时回退短清单并保持 `source="env"`。

```
{
  "models": ["gpt-5.6-sol"],
  "default": "gpt-5.6-sol",
  "source": "env"
}
```

### 普通调用

```
POST /ecommerce-assistant/invoke
```
请求：

```
{
  "message": "订单 1001 现在到哪里了？",
  "thread_id": "demo-thread-001",
  "user_id": "demo-user-001",
  "model": "gpt-5.6-sol"
}
```
`model` 可省略，省略时用 `OPENAI_MODEL`。响应为 `docs/PRD.md` v0.3 §6.7.1 约定的 ChatMessage：

```
{
  "type": "ai",
  "content": "订单 1001 当前状态：已发货。客户地区：中国。订单包含 3 个商品，1 个包裹。",
  "route": "order",
  "tool_calls": [{"name": "order_lookup", "args": {"order_id": "1001"}, "result": null}],
  "sources": [],
  "run_id": "run_a1b2c3",
  "intent": "order"
}
```

| 字段 | 说明 |
| --- | --- |
| `route` | 意图路由结果，取值 `after` / `order` / `stock` / `ship` / `unknown`。前端据此决定分拣带计数与配色，**不得自行推断** |
| `tool_calls` | 本次回答调用的工具，每项含 `name`、`args`，可选 `result`；无调用时为空数组，**不得为 null** |
| `sources` | RAG 来源，每项含 `doc`、`snippet`，可选 `placeholder`；无来源时为空数组，**不得为 null** |
| `run_id` | 本次运行标识，形如 `run_a1b2c3`，每条唯一 |
| `intent` | 实际命中的分支（`order` / `inventory` / `logistics` / `rag` / `llm`），用于判断本次回答是否经过模型 |

`route` 与 `intent` 的区别：`intent` 是关键词路由的判定结果，`route` 是「回答实际来自哪里」。
两者在多数情况下同名（`order`→`order`、`inventory`→`stock`、`logistics`→`ship`），
差异在两处：知识库命中时 `intent="rag"` 而 `route="after"`；模型直接作答时
`intent="llm"` 而 `route="after"`。

### 流式调用

```
POST /ecommerce-assistant/stream
```

SSE 响应，事件类型见 `docs/PRD.md` v0.3 §6.7.2。顺序为
`start` → `route` → `tool_call*` → `sources?` → `token*` → `[DONE]`：

```
data: {"type":"start","run_id":"run_a1b2c3"}

data: {"type":"route","route":"order"}

data: {"type":"tool_call","name":"order_lookup","args":{"order_id":"1001"}}

data: {"type":"token","content":"订单 1001 "}

data: {"type":"token","content":"当前正在运输中。"}

data: [DONE]
```

`route` 先于正文到达，前端据此在正文开始前播放投递动效（`design/FRONTEND-SPEC.md` §7.4）。
除 `token` 与 `[DONE]` 外其余事件均为可选：非 RAG 链路不发 `sources`，无工具调用不发
`tool_call`；出错时发一条 `error`，随后仍以 `[DONE]` 正常收尾。

## 10. 最小演示问题
启动后依次测试：

```
退货需要满足什么条件？
订单 1001 现在到哪里了？
商品 SKU-001 还有库存吗？
订单 1001 使用了什么物流？
```
验证结果：

- 售后问题能返回知识库引用；
- 订单问题能调用订单工具；
- 库存问题能调用库存工具；
- 物流问题能调用物流工具；
- 未找到订单时返回明确错误；
- 普通问题不会导致服务崩溃；
- 在「回复模型」下拉框切换模型后再问「退货需要满足什么条件？」，气泡上方的「模型：xxx」标注跟随变化；
- 用订单、库存、物流问题提问时，气泡上方标注为「工具查询 · 未使用模型」，切换模型不影响结果。

### Web 前端（分拣台）

依次点四个快捷问题，再手输一个无关问题（如「今天深圳的天气怎么样？」），逐项核对：

- 四个快捷问题分别点亮**售后 / 商品、订单、库存、物流**四个道口，包裹沿传送带投递到对应道口；
- 轨迹栏「已调用的工具」出现 `order_lookup`、`stock_lookup`、`shipping_lookup`，各计 1 次；
- 售后问题的回执出现可展开的**来源块**，「知识库命中」+1；
- 订单、库存、物流的回执出现「调用的工具」块，形如 `order_lookup(order_id="1001")`；
- 无关问题落在**兜底形态**：暖色底 + 「未识别 · 兜底回复」，不调用任何工具，不计入「已路由」；
- 后端未启动时，页面追加一条「连接失败 · …」回执，右上角状态灯转为「后端不可达」，不静默失败。

浏览器直接打开 `frontend/index.html#empty` 可查看新会话的空态（分拣带计数全 0）。

## 11. 第一阶段验收标准

`docs/PRD.md` v0.3 §9 共 11 项，逐项通过即完成第一阶段。

| 序号 | 验收项 | 验证方式 |
| --- | --- | --- |
| 1 | `/info` 返回 ecommerce-assistant | `tests/test_api.py::test_info_endpoint` |
| 2 | `/invoke` 返回 ChatMessage：6 个字段齐全、`route` 为合法枚举、数组字段不为 null | `tests/test_frontend_contract.py` |
| 3 | `/stream` 返回 SSE：`start`、`route` 事件 + `token` 增量 + `[DONE]` | `tests/test_frontend_contract.py` 的流式用例 |
| 4 | 订单工具可独立调用 | `tests/test_tools.py` |
| 5 | 库存工具可独立调用 | `tests/test_tools.py` |
| 6 | 物流工具可独立调用 | `tests/test_tools.py` |
| 7 | 售后文档可被检索 | `tests/test_tools.py::test_rag_retriever_returns_source` |
| 8 | RAG 回答的 `sources` 非空（含 `doc` 与 `snippet`），前端渲染可展开来源块 | `tests/test_frontend_contract.py` + 浏览器验证（第 10 节） |
| 9 | 不同 `thread_id` 的对话状态互相隔离 | `tests/test_api.py::test_thread_isolation` |
| 10 | pytest 通过核心测试；普通问题不崩溃 | `uv run pytest tests/` |
| 11 | README 能让别人从零启动项目（含后端与 Web 前端） | 按第 5～8 节复现（本地直跑或 Docker 任选其一） |

另有一组业务查询层验收条件（8 条「必须满足」）固化为 `tests/test_query_layer_acceptance.py`。

当前全量回归基线：

```text
203 passed
```

运行全量测试：

```powershell
uv run pytest -q
```

仅验证 Streamlit 页面：

```powershell
uv run pytest tests/test_streamlit_app.py -q
```

## 12. 最小调用链

```
Web 前端（frontend/index.html） 或 Streamlit（streamlit_app.py）
  ↓
AgentClient / fetch
  ↓
POST /ecommerce-assistant/invoke
  ↓
FastAPI service（api/service.py）
  ↓
LangGraph（agents/ecommerce_assistant.py::build_graph）
  ↓
answer_question() —— 意图路由
  ├── order / inventory / logistics → 业务工具（确定性 SQL）
  ├── rag                          → 知识库检索（返回结构化 sources）
  └── llm                          → 中转站模型
  ↓
{content, route, tool_calls, sources, intent}
  ↓
ChatMessage
  ↓
前端按 route / tool_calls / sources 渲染
```

实现顺序建议固定为：

```
业务工具
→ RAG
→ LangGraph Agent
→ FastAPI
→ AgentClient
→ Web 前端
→ 测试和 Docker
```
当前版本已经跑通这条链路，并完成统一业务查询层、数据库约束、工作台同源查询和主要页面可视化；后续重点是生产部署安全、Demo/Real 隔离以及真实业务系统接入。
