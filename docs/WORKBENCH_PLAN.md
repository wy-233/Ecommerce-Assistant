# 电商工作台数据库扩展方案

## 1. 目标与边界

本阶段的目标不是改造页面，而是为未来的“电商工作台”定义一套数据库扩展方案，并保持当前 MVP 的接口、工具函数和前端行为不受影响。

关键约束：

- 不改动当前 Streamlit 页面结构；
- 不改动现有 FastAPI 接口契约；
- 不破坏 `get_order_status()`、`get_inventory_status()`、`get_logistics_status()` 的调用方式；
- 允许后续按真实业务数据逐步替换内存字典；
- 优先保证 SQLite 兼容，后续可扩展到 PostgreSQL。

---

## 2. 当前项目真实结构

从当前代码来看，项目没有实现真正的数据库层；目前的数据都在内存中维护，主要是以下几部分：

### 2.1 订单数据

文件：`src/ecommerce_assistant/tools/order.py`

当前结构：

- `ORDERS` 是字典：`order_id -> {status, location, shipping_method}`
- `get_order_status(order_id)` 负责解析并返回文本

示例：

- `1001` => `运输中` / `深圳中转站` / `DHL`
- `1002` => `已签收` / `上海市浦东新区` / `FedEx`

这意味着当前“订单”只覆盖：

- 订单号
- 状态
- 当前位置
- 物流方式

没有真正的：

- 客户信息
- 下单时间
- 商品明细
- 付款状态
- 地址、收货人、增值服务

### 2.2 库存数据

文件：`src/ecommerce_assistant/tools/inventory.py`

当前结构：

- `INVENTORY` 是字典：`sku -> {stock, status}`
- `get_inventory_status(sku)` 返回库存数和库存状态

示例：

- `SKU-001` => 24 件、`有货`
- `SKU-002` => 0 件、`缺货`

这对应的业务对象非常简化：

- SKU
- 可用库存
- 预设状态

缺失：

- 仓库/仓位
- 采购量、可售量
- 预留库存、在途库存
- SKU 详情（商品名、品牌、属性）

### 2.3 物流数据

文件：`src/ecommerce_assistant/tools/logistics.py`

当前结构：

- `LOGISTICS` 是字典：`order_id -> shipping`（例如 DHL / FedEx / UPS）
- `get_logistics_status(order_id)` 直接返回物流服务名称

目前的物流模型非常轻量，缺少：

- 物流单号
- 承运商/渠道
- 发货时间、签收时间
- 跟踪事件列表
- 运输节点状态

### 2.4 对话历史与 API

文件：`src/ecommerce_assistant/api/service.py`

当前 `FastAPI` API 在内存中维护：

- `_THREAD_HISTORY: dict[str, list[dict[str, str]]]`

这是线程级历史，不是数据库。

`streamlit_app.py` 也只是：

- 维护 `st.session_state.messages`
- 通过 `AgentClient` 调用后端
- 不包含真实用户/订单数据模型

### 2.5 业务规则与知识库

文件：`src/ecommerce_assistant/rag/retriever.py`

当前是“文档式知识库”，不是数据库表：

- `return_policy`
- `shipping_policy`

这类信息属于售后政策、物流时效等规则，后续可以迁移为数据库表（如 `knowledge_articles`），但不需要作为第一阶段核心工作台表。

---

## 3. 现状与目标的对应关系

当前 MVP 中，三类核心业务对象已经有隐含的关系：

| 当前对象 | 关键字段 | 未来对应表 |
| --- | --- | --- |
| 订单 `order_id` | 订单号、状态、位置、物流 | `orders` |
| 商品 `sku` | SKU、库存、状态 | `inventory` |
| 物流 `order_id` | 物流公司 | `shipments` |
| 对话历史 `thread_id` | 会话上下文 | `chat_threads` / `chat_messages` |
| 退货/物流政策 | 文档内容 | `knowledge_articles` |

核心关联关系：

- `orders.order_id` 是主键；
- `order_items` 通过 `order_id` 关联到 `orders`；
- `inventory` 通过 `sku` 关联到商品/库存；
- `shipments` 通过 `order_id` 关联到订单；
- `tracking_events` 通过 `shipment_id` 关联到 `shipments`；
- `chat_messages` 通过 `thread_id` 关联到 `chat_threads`。

这正是后续“电商工作台”的最小关系闭环。

---

## 4. 目标数据库模型（SQLite 优先）

建议第一版采用 SQLite，兼容本项目已有结构，并且便于未来迁移到 PostgreSQL。模型可按“标准订单中心 + 物流中心 + 库存中心 + 知识中心”拆分。

### 4.1 表：`orders`

订单主表：

```sql
CREATE TABLE orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id TEXT NOT NULL UNIQUE,
    user_id TEXT,
    order_status TEXT NOT NULL,
    payment_status TEXT,
    total_amount REAL,
    currency TEXT DEFAULT 'CNY',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    shipping_address TEXT,
    consignee_name TEXT,
    consignee_phone TEXT,
    notes TEXT
);
```

说明：

- `order_id` 是业务主键，便于现有 `1001`/`1002` 查询格式兼容；
- `order_status` 可存 `待付款 / 已支付 / 已发货 / 运输中 / 已签收 / 取消`；
- 业务上保留 `shipping_address` 等字段，便于后续工作台展示。

### 4.2 表：`order_items`

订单明细：

```sql
CREATE TABLE order_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id TEXT NOT NULL,
    sku TEXT NOT NULL,
    product_name TEXT,
    quantity INTEGER NOT NULL DEFAULT 1,
    unit_price REAL,
    currency TEXT DEFAULT 'CNY',
    status TEXT,
    FOREIGN KEY (order_id) REFERENCES orders(order_id)
);
```

说明：

- 这是从当前 `order.py` 中单订单文本查询，向真实订单拆单推进的重要表；
- `order_id` 和 `sku` 是未来工作台中最关键的业务键；
- `sku` 直接对应库存模型中的商品代码。

### 4.3 表：`inventory`

库存表：

```sql
CREATE TABLE inventory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sku TEXT NOT NULL UNIQUE,
    product_name TEXT,
    warehouse TEXT,
    stock_qty INTEGER NOT NULL DEFAULT 0,
    reserved_qty INTEGER NOT NULL DEFAULT 0,
    available_qty INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'unknown',
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

说明：

- 该表直接承接现有 `INVENTORY` 中的 `sku` 和 `stock` 逻辑；
- `available_qty = stock_qty - reserved_qty` 可作为业务计算字段；
- `status` 针对当前 MVP 可用值：`有货 / 缺货 / 库存充足 / 预警`。

### 4.4 表：`shipments`

物流表：

```sql
CREATE TABLE shipments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    shipment_id TEXT NOT NULL UNIQUE,
    order_id TEXT NOT NULL,
    carrier TEXT,
    tracking_number TEXT,
    shipping_method TEXT,
    shipped_at TEXT,
    delivered_at TEXT,
    status TEXT,
    FOREIGN KEY (order_id) REFERENCES orders(order_id)
);
```

说明：

- 直接对应当前 `LOGISTICS` 中 `order_id -> shipping_method` 的信息；
- 未来每个订单可对应一条或多条物流记录；
- `shipment_id` 作为后续跟踪事件表的关联键。

### 4.5 表：`tracking_events`

物流事件记录：

```sql
CREATE TABLE tracking_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    shipment_id TEXT NOT NULL,
    event_time TEXT NOT NULL,
    event_type TEXT,
    event_description TEXT,
    location TEXT,
    FOREIGN KEY (shipment_id) REFERENCES shipments(shipment_id)
);
```

说明：

- 未来可支持“物流节点追踪”与工作台事件日志；
- 当前工具函数中的 `location`、`shipping_method` 可以由此表/主表聚合得到。

### 4.6 表：`chat_threads`

会话主表：

```sql
CREATE TABLE chat_threads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id TEXT NOT NULL UNIQUE,
    user_id TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

### 4.7 表：`chat_messages`

消息表：

```sql
CREATE TABLE chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system')),
    content TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (thread_id) REFERENCES chat_threads(thread_id)
);
```

说明：

- 这是对当前 `service.py` 中 `_THREAD_HISTORY` 的结构化落地；
- 不影响现有 `thread_id` 请求字段；
- 对服务端来说可完全替代 Python 字典。

### 4.8 表：`knowledge_articles`

知识库文章：

```sql
CREATE TABLE knowledge_articles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT NOT NULL UNIQUE,
    category TEXT NOT NULL,
    title TEXT,
    content TEXT NOT NULL,
    source TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

说明：

- 未来可承接当前 `data/return_policy.md` 与 `data/shipping_policy.md` 的内容；
- `retriever.py` 可改为从数据库中读取，而不是硬编码字典。

---

## 5. 关键关联与语义说明

### 订单-商品

- `orders.order_id` -> `order_items.order_id`
- `order_items.sku` -> `inventory.sku`

这可以支持：

- 某订单有哪几件商品；
- 商品是否库存紧张；
- 订单中的商品是否已缺货/发货。

### 订单-物流

- `orders.order_id` -> `shipments.order_id`
- `shipments.shipment_id` -> `tracking_events.shipment_id`

这能把当前“物流方式”升级为：

- 发货时间
- 当前物流状态
- 跟踪节点事件
- 物流公司、单号、签收状态

### 对话-订单

- `chat_messages.thread_id` -> `chat_threads.thread_id`
- 在未来的工作台中，可追踪某个用户会话查询过谁的订单、哪条 SKU、哪次物流状态。

---

## 6. 建议的索引设计

为支持高频查询，建议在 SQLite 中建立如下索引：

```sql
CREATE INDEX idx_orders_order_id ON orders(order_id);
CREATE INDEX idx_orders_status ON orders(order_status);
CREATE INDEX idx_order_items_order_id ON order_items(order_id);
CREATE INDEX idx_order_items_sku ON order_items(sku);
CREATE INDEX idx_inventory_sku ON inventory(sku);
CREATE INDEX idx_inventory_status ON inventory(status);
CREATE INDEX idx_shipments_order_id ON shipments(order_id);
CREATE INDEX idx_shipments_tracking_number ON shipments(tracking_number);
CREATE INDEX idx_tracking_events_shipment_id ON tracking_events(shipment_id);
CREATE INDEX idx_tracking_events_event_time ON tracking_events(event_time);
CREATE INDEX idx_chat_messages_thread_id ON chat_messages(thread_id);
CREATE INDEX idx_knowledge_articles_category ON knowledge_articles(category);
```

说明：

- 订单查询/库存查询/物流查询是最热路径；
- 这些索引会显著提升 `query_order` / `query_inventory` / `query_logistics` 的性能；
- 对 SQLite 来说，索引成本低且适合中小规模电商演示环境。

---

## 7. 兼容层设计：让现有代码不被打断

为了不影响当前业务运行，推荐新增一个抽象层，而不是直接替换现有工具函数。

### 7.1 目标

将原来的：

- `get_order_status(order_id)`
- `get_inventory_status(sku)`
- `get_logistics_status(order_id)`

升级为“统一数据访问层”的对外接口。

### 7.2 兼容策略

1. 先保留现有函数签名；
2. 让这些函数从 “内存字典” 或 “SQLite 读表” 中读取，优先级为：
   - 真实数据库
   - 兼容缓存/内存落盘
   - 默认演示数据
3. 仅在“数据库未初始化”时回退到当前 demo 数据；
4. 允许 API、agent 和 Streamlit 对外行为完全不变。

示意伪代码：

```python
def get_order_status(order_id: str) -> str:
    if database_ready():
        return query_order_from_db(order_id)
    return legacy_order_demo(order_id)
```

这样可以在不改页面、不改接口、不改 AI 路由逻辑的前提下，慢慢切换到真实数据。

---

## 8. 真实数据与演示数据边界

未来的数据库必须清晰区分：

### 8.1 演示数据（MVP）

包括：

- 测试订单：`1001`/`1002`/`1003`
- 代表性 SKU：`SKU-001`/`SKU-002`/`SKU-003`
- 物流示例：DHL / FedEx / UPS

这些数据用于：

- 生成示例问题
- 验证明明业务链路
- 保持整体功能可演示

### 8.2 真实数据（工作台）

包括：

- 用户真实订单
- 商品价格、库存、仓库位置
- 实际运输单号、签收状态
- 一段时间内的追踪事件
- 真实客服对话数据

建议：

- 真实数据只在“生产/测试环境”中启用；
- 演示数据与真实数据分库或分表管理；
- 先保持默认 `demo` 模式，避免测试环境出现脏数据。

---

## 9. 数据迁移策略

推荐使用“增量迁移 + 兼容期”推进：

### 第 1 阶段：建表但不切换

- 创建 `orders`、`inventory`、`shipments`、`tracking_events`、`chat_threads` 等表；
- 先写入 demo seed 数据；
- 既不改工具函数，也不改页面。

### 第 2 阶段：开放读兼容层

- 修改 `get_order_status()` 等函数，优先访问 SQLite；
- 若表为空，自动回退到当前字典数据。

### 第 3 阶段：实现真实写入

- 订单、库存、物流数据写入数据库；
- 仅对后台管理或工具链开放，不影响前端演示接口。

### 第 4 阶段：逐步替换

- `retriever.py` 改为从 `knowledge_articles` 读取；
- `chat_messages` 替代 `_THREAD_HISTORY`；
- 工作台页可增加对订单/库存/物流的查询视图。

---

## 10. 未来工作台页面与数据库的对应关系

虽然本阶段不做页面，但可预先规划页面所需数据：

- 订单列表页：`orders + order_items`
- 库存页：`inventory`
- 物流页：`shipments + tracking_events`
- 会话页：`chat_threads + chat_messages`
- 退货/政策页：`knowledge_articles`

这样后续前端工作就不会出现“页面先做，数据表后补”的问题。

---

## 11. 9 步实现路线（分阶段）

1. 建立数据库初始化脚本，创建 `orders`、`inventory`、`shipments`、`tracking_events`、`chat_threads`、`chat_messages`、`knowledge_articles`。
2. 加入 SQLite 连接层和启动时自动建表逻辑。
3. 设计 demo seed 数据，保持当前 `1001`/`SKU-001` 等演示场景可用。
4. 让 `get_order_status()`、`get_inventory_status()`、`get_logistics_status()` 走统一数据访问层。
5. 增加 `order_items` 表，并将订单与商品明细进行关联。
6. 增加 `shipments` 和 `tracking_events`，让物流状态从“单值文本”升级到“事件链”。
7. 把 `chat_messages` 从内存历史迁移到数据库，并保留 `thread_id` 兼容。
8. 迁移 `retriever.py` 到 `knowledge_articles` 表，保留 RAG 答案能力。
9. 扩展工作台页面：订单列表、库存看板、物流跟踪、客服对话日志，且不破坏现有 MVP 入口。

---

## 12. 风险与注意事项

### 12.1 数据模型过度设计

当前项目仍处于 MVP 阶段，不能一开始就做过度复杂的 ERP/OMS 设计。建议先做“最小工作台模型”，只覆盖订单、商品、物流、消息、知识五大类。

### 12.2 当前工具函数的文本输出习惯

`get_order_status()` 等函数返回的是自然语言字符串，而不是结构化字段。为了减少破坏风险，兼容层必须先保留字符串输出接口，再在其下层调用数据库。

### 12.3 线程隔离与会话迁移

`thread_id` 是当前多轮对话的关键能力；数据库表必须保留相同语义，不可以把 `user_id` 和 `thread_id` 混用。

### 12.4 真实数据必须受控

工作台的真实数据接入应该在配置开关下启用，而不是直接替换 demo 数据，否则会导致演示逻辑失真。

---

## 13. 结论

目前的项目确实还没有真正的数据库层，所有核心业务数据仍然是内存字典和文件化知识资料。这是合理的 MVP 设计，但它也意味着后续扩展空间很大。

对于“电商工作台”而言，最稳妥的起点不是一次性重构，而是：

- 先正确定义核心表：`orders`、`order_items`、`inventory`、`shipments`、`tracking_events`；
- 保持现有 API、工具函数和 UI 行为不变；
- 通过兼容层逐步替换当前 demo 数据；
- 在真实数据接入前先建立清晰的数据库结构和索引设计。

这能最大化复用当前已验证的 LLM + 工具 + API 架构，同时为后续工作台功能按部就班落地打好基础。
