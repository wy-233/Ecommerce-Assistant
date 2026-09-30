# Ecommerce Assistant

一个面向跨境电商运营场景的 AI 助手 MVP，用于演示如何把自然语言问答、确定性业务查询和运营工作台组合成一条可运行的应用链路。

仓库地址：<https://github.com/wy-233/Ecommerce-Assistant>

## 项目介绍

项目围绕售后、订单、库存和物流四类高频问题展开：

- 售后政策问题从数据库知识库检索，并返回文章来源；
- 订单、库存、物流问题通过统一业务查询层读取 SQLite；
- Agent 负责识别问题类型和组织回答，业务数据不交给大模型猜测；
- FastAPI 提供接口，Streamlit 提供运营工作台，独立 Web 页面提供轻量演示入口。

这个项目重点展示以下工程实践：

- 将 Agent、API 和页面查询统一到同一套业务函数，避免多处维护 SQL；
- 将商品、仓库抽为主数据，并为 SKU 建立引用约束；
- 将订单、库存、物流查询结果设计为结构化返回，区分参数错误、数据不存在、无物流记录和数据库错误；
- 使用 FastAPI lifespan 管理数据库初始化和演示数据播种；
- 用测试覆盖查询层、API 同源性、Agent 路由和 Streamlit 页面。

当前版本是演示型 MVP，默认使用 Demo 数据，不包含真实 ERP 对接、用户登录和生产级权限控制。

## 技术栈

| 分类 | 技术 |
| --- | --- |
| 语言与运行时 | Python 3.12+ |
| API 服务 | FastAPI、Uvicorn、Pydantic |
| Agent 编排 | LangGraph |
| 模型调用 | OpenAI 兼容接口，通过 `OPENAI_BASE_URL` 配置 |
| 知识库 | SQLite `knowledge_articles` 表 |
| 业务数据 | SQLite、参数化 SQL、外键和索引 |
| 运营界面 | Streamlit、Altair |
| 独立前端 | 原生 HTML / CSS / JavaScript |
| 工程化 | uv、pytest、Docker Compose |

Python 版本和依赖以 [`pyproject.toml`](pyproject.toml) 与 [`uv.lock`](uv.lock) 为准。

## 核心功能

### AI 助手问答

- 自动识别售后、订单、库存、物流和通用问题；
- 支持模型选择、普通调用和 SSE 流式显示；
- 返回 `route`、`intent`、`tool_calls`、`sources` 等结构化字段；
- 不同 `thread_id` 的会话历史相互隔离。

### 订单查询

- 按 `order_id` 查询订单状态、商品、金额和全部包裹；
- 支持一单多包裹；
- 订单不存在时返回明确的 `NOT_FOUND` 结果。

### 库存查询

- 按 SKU 精确查询；
- 按 SKU 或商品名称搜索；
- 按仓库筛选；
- 返回 `on_hand`、`reserved`、`available`、`safety_stock`；
- 按统一规则计算库存状态：

| 规则 | 状态 |
| --- | --- |
| `available <= 0` | 缺货 |
| `available <= safety_stock` | 库存不足 |
| `available > safety_stock` | 正常 |

库存看板用彩色横条表示可售库存，深灰短线表示安全库存阈值，并按缺货、库存不足、正常的顺序展示风险 SKU。

### 物流查询

- 按 `shipment_id`、`order_id` 或 `tracking_number` 查询；
- 按订单查询时返回全部包裹；
- 返回当前物流状态和按时间升序排列的轨迹；
- 区分订单不存在和订单没有物流记录。

### 运营工作台

Streamlit 工作台包含首页运营指标、最近订单、库存预警、物流异常、订单管理、库存看板、物流跟踪、AI 对话和模型选择。

## 处理流程

```text
用户问题
    ↓
Agent 识别问题类型
    ├── 售后问题 → knowledge_articles 检索 → 返回答案和来源
    ├── 订单问题 → tools/database.py → 查询订单、商品和包裹
    ├── 库存问题 → tools/database.py → 查询库存并计算状态
    ├── 物流问题 → tools/database.py → 查询包裹和轨迹
    └── 通用问题 → 调用 OpenAI 兼容模型
    ↓
FastAPI 返回结构化结果
    ↓
Streamlit 或 Web 前端展示
```

订单、库存和物流数据来自 SQLite 查询结果。模型只参与售后知识库回答和通用问答，不参与业务数据判断。

## 项目结构

```text
src/
├── ecommerce_assistant/
│   ├── agents/ecommerce_assistant.py  # Agent 路由与结构化回答
│   ├── api/service.py                 # FastAPI 接口、SSE、lifespan
│   ├── db/init_db.py                  # 建表、迁移、播种、完整性检查
│   ├── pages/                         # Streamlit 订单 / 库存 / 物流页面
│   ├── rag/retriever.py               # knowledge_articles 检索
│   ├── tools/database.py              # 统一业务查询层
│   ├── tools/order.py                 # 订单工具薄封装
│   ├── tools/inventory.py             # 库存工具薄封装
│   ├── tools/logistics.py             # 物流工具薄封装
│   ├── workbench/queries.py           # 工作台展示适配层
│   └── streamlit_app.py               # Streamlit 首页
└── run_service.py                     # 后端启动入口

data/demo/                             # 演示 CSV 数据源
frontend/                              # 独立 Web 前端
scripts/init_database.py               # 初始化数据库
scripts/import_data.py                 # 真实数据导入入口
tests/                                 # 自动化测试
Dockerfile                             # 多阶段镜像构建
docker-compose.yml                     # API、Streamlit、Web 三个服务
```

## 本地运行

### 1. 准备环境

要求 Python `>=3.12,<3.15`，并安装 [uv](https://docs.astral.sh/uv/getting-started/installation/)。如果需要 AI 回答，还要准备 OpenAI 兼容接口的 API Key。

```powershell
git clone https://github.com/wy-233/Ecommerce-Assistant.git
Set-Location Ecommerce-Assistant
uv sync --frozen
```

### 2. 配置环境变量

```powershell
Copy-Item .env.example .env
```

编辑 `.env`，至少填写：

```dotenv
OPENAI_API_KEY=your_api_key
OPENAI_BASE_URL=https://aihub.top/v1
OPENAI_MODEL=gpt-5.6-sol
```

`.env` 只保存在本机，不要提交到 GitHub。订单、库存和物流查询不依赖模型 Key，模型不可用时仍可使用确定性查询和知识库功能。

### 3. 初始化数据库

服务启动时会自动建库和播种 Demo 数据。需要提前检查数据库时，可以运行：

```powershell
uv run python scripts/init_database.py
```

该命令是幂等的，不会覆盖已有业务数据。恢复 Demo 数据基线时使用：

```powershell
uv run python scripts/init_database.py --reset-demo
```

`--reset-demo` 会清空核心业务表并重新导入 CSV，只用于演示环境。

### 4. 启动 FastAPI

打开第一个终端：

```powershell
python src/run_service.py
```

访问 API：<http://localhost:8084>，Swagger 文档：<http://localhost:8084/docs>。

### 5. 启动 Streamlit 工作台

打开第二个终端：

```powershell
uv run streamlit run src/ecommerce_assistant/streamlit_app.py
```

访问：<http://localhost:8501>。

### 6. 启动独立 Web 前端（可选）

打开第三个终端：

```powershell
python -m http.server 5500 --directory frontend
```

访问：<http://localhost:5500>。API 地址写在 `frontend/index.html` 的 `API_BASE` 常量中，默认是 `http://localhost:8084`。

## Docker 运行

Docker Compose 可以一次启动 API、Streamlit 和独立 Web 前端：

```powershell
Copy-Item .env.example .env
# 编辑 .env，填入 API Key
docker compose up -d --build
```

访问地址：

| 服务 | 地址 |
| --- | --- |
| API 文档 | <http://localhost:8084/docs> |
| Streamlit | <http://localhost:8501> |
| Web 前端 | <http://localhost:5500> |

常用命令：

```powershell
docker compose ps
docker compose logs -f api
docker compose down
```

`docker compose down -v` 会删除 `ea-data` 数据卷，导致 SQLite 数据被清除并在下次启动时重新播种，只用于重置演示环境。

当前 Compose 文件面向本地演示。公网部署还需要 HTTPS 反向代理、访问认证、请求限流、数据库备份，并让 API 和 Streamlit 使用同一个持久化数据库卷。

## 主要接口

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET` | `/info` | 服务和 Agent 信息 |
| `GET` | `/models` | 获取可选模型 |
| `GET` | `/dashboard/summary` | 首页统计摘要 |
| `GET` | `/orders` | 订单列表和筛选 |
| `GET` | `/orders/{order_id}` | 订单详情 |
| `GET` | `/inventory` | 库存列表和筛选 |
| `GET` | `/inventory/{sku}` | SKU 库存详情 |
| `GET` | `/shipments` | 包裹列表和筛选 |
| `GET` | `/shipments/{shipment_id}/events` | 物流轨迹 |
| `POST` | `/ecommerce-assistant/invoke` | 普通问答 |
| `POST` | `/ecommerce-assistant/stream` | SSE 流式问答 |

## 测试与验证

运行全部测试：

```powershell
uv run pytest -q
```

当前基线：

```text
209 passed
```

测试覆盖数据库初始化、迁移、播种、外键约束、业务查询、错误码、Agent 路由、API 同源性、知识库来源、Streamlit 页面和前端响应契约。

## 当前边界与改进方向

### 当前边界

- 使用 SQLite，适合单机 MVP 和低并发演示，不适合多实例并发写入；
- 默认数据为 Demo 数据，尚未完成完整的 Demo/Real 数据隔离；
- 尚未提供用户登录、角色权限、API 鉴权和操作审计；
- 尚未加入请求限流、模型调用额度控制和生产级可观测性；
- 订单和物流中的 `warehouse_id` 表示商品关联的库存仓库，不代表真实履约发货仓库；
- 尚未对接真实 ERP、OMS、WMS 或物流服务商。

### 改进方向

1. 增加用户登录、角色权限、API 鉴权和操作审计；
2. 完成 Demo/Real 数据筛选与真实数据联调；
3. 将 SQLite 迁移到 PostgreSQL，支持多实例部署；
4. 为订单、库存和物流接入真实业务系统或消息队列；
5. 增加模型调用限流、成本统计、超时重试和可观测性；
6. 为公网部署补充 HTTPS、自动备份和 CI/CD；
7. 在明确履约仓库数据来源后，增加真实发货仓库模型。

## 项目验证结论

当前版本已经完成从自然语言入口到业务查询、API 返回和运营界面的完整闭环，并通过 `209` 条自动化测试。SSE 前端会逐段显示回答，但后端目前先生成完整回答再分段发送，并非模型实时生成。后续工作重点从 MVP 功能实现转向生产安全、真实数据接入和部署稳定性。
