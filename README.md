# Ecommerce Assistant
基于 Python、FastAPI、LangGraph 和 Streamlit 实现的跨境电商 AI 助手，支持售后知识库问答、订单查询、库存查询和物流查询。

## 1. 最小功能
第一阶段只实现：

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
- 复杂前端；
- 模型训练。

## 2. 技术栈

- Python `>=3.12,<3.15`
- FastAPI
- LangGraph
- Pydantic
- HTTPX
- Streamlit
- ChromaDB 或 SQLite
- uv
- Docker Compose
参考仓库的 Python 版本要求来自 [`pyproject.toml`](E:/ai应用开发项目实践/agent-service-toolkit/pyproject.toml)。

## 3. 项目结构

```
ecommerce-ai-assistant/
├── src/
│   ├── agents/
│   │   ├── agents.py
│   │   └── ecommerce_assistant.py
│   ├── api/
│   │   └── service.py
│   ├── client/
│   │   └── client.py
│   ├── rag/
│   │   ├── ingest.py
│   │   └── retriever.py
│   ├── tools/
│   │   ├── order.py
│   │   ├── inventory.py
│   │   └── logistics.py
│   ├── schema/
│   │   └── schema.py
│   └── streamlit_app.py
├── data/
│   ├── return_policy.md
│   └── shipping_policy.md
├── tests/
├── .env.example
├── pyproject.toml
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
HOST=0.0.0.0
PORT=8080
```
API Key 只放在 `.env`，不要提交到 Git。

## 5. 安装依赖

```
uv sync
```
如果项目使用锁文件：

```
uv sync --frozen
```

## 6. 启动后端

```
python src/run_service.py
```
后端地址：

```
http://localhost:8080
```
接口文档：

```
http://localhost:8080/docs
```

## 7. 启动前端
另开一个终端：

```
streamlit run src/streamlit_app.py
```
前端地址通常是：

```
http://localhost:8501
```

## 8. 主要接口

### 查看服务信息

```
GET /info
```
返回可用 Agent 和模型。

### 普通调用

```
POST /ecommerce-assistant/invoke
```
请求：

```
{
  "message": "订单 1001 现在到哪里了？",
  "thread_id": "demo-thread-001",
  "user_id": "demo-user-001"
}
```
响应：

```
{
  "type": "ai",
  "content": "订单 1001 当前正在运输中。",
  "tool_calls": [],
  "run_id": "run-001"
}
```

### 流式调用

```
POST /ecommerce-assistant/stream
```
响应格式：

```
data: {"type":"token","content":"订单"}

data: {"type":"token","content":"正在运输中"}

data: [DONE]
```

## 9. 最小演示问题
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
- 普通问题不会导致服务崩溃。

## 10. 第一阶段验收标准

```
[ ] /info 可以返回 ecommerce-assistant
[ ] /invoke 可以返回 ChatMessage
[ ] /stream 可以返回 SSE
[ ] 订单工具可以独立调用
[ ] 库存工具可以独立调用
[ ] 物流工具可以独立调用
[ ] 售后文档可以被检索
[ ] RAG 回答包含来源
[ ] 不同 thread_id 的对话状态互相隔离
[ ] pytest 至少通过核心工具和接口测试
[ ] README 能让别人从零启动项目
```

## 11. 最小调用链

```
Streamlit
  ↓
AgentClient
  ↓
POST /ecommerce-assistant/invoke
  ↓
FastAPI service
  ↓
get_agent("ecommerce-assistant")
  ↓
_handle_input()
  ↓
ecommerce_graph.ainvoke()
  ↓
RAG 或业务 Tool
  ↓
ChatMessage
  ↓
前端展示
```
实现顺序建议固定为：

```
业务工具
→ RAG
→ LangGraph Agent
→ FastAPI
→ AgentClient
→ Streamlit
→ 测试和 Docker
```
第一版只要这条链路跑通，就已经具备一个可演示的 AI 应用开发项目。
