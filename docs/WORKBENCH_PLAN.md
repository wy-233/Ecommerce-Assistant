# 电商工作台数据库扩展方案

> 文档版本：v2.12（2026-09-24）
> 覆盖范围：SQLite 表结构现状、工具取数链路、目标模型差异、扩展与迁移策略、索引设计、演示/真实数据边界、后续 9 步实现顺序
> 本轮文档收口约束：**不修改业务行为**。本文档同时记录设计基线、实施状态与真实待办。

## 0. 文档状态说明

本文档的上一版（v1.0）已严重失真，其中「项目没有实现真正的数据库层，数据都在内存字典里」的结论与当前代码不符。v2.0 基于**实测导出**的库结构与**实测调用链**重写，替换原有内容。

事实核对方式：

- 表结构与索引：`SELECT sql FROM sqlite_master` 实际导出（见第 2 章）
- 取数链路：逐文件阅读 `tools/`、`db/`、`api/`、`agents/` 源码
- 数据量：对 `data/ecommerce_assistant.db` 实测计数（见 1.3）

v2.1（2026-09-22）按用户要求落地了**数据层实现**（连接生命周期统一、演示数据单一写入源收敛、索引去重与补齐、引用完整性校验、统一初始化入口），完成情况与剩余缺口见 **8.1 实现状态**。第 1、2 章的索引表已按实现后的实测结果校订。

---

## 1. 现有 SQLite 数据库的表结构

### 1.1 数据库定位

| 项目 | 值 |
| --- | --- |
| 唯一权威库路径 | `data/ecommerce_assistant.db` |
| 路径解析代码 | `src/ecommerce_assistant/db/init_db.py:9-10`，`_PROJECT_ROOT = Path(__file__).resolve().parents[3]` |
| 覆盖开关 | 环境变量 `ECOMMERCE_DB_PATH`（`api/service.py:28`） |
| 建表入口 | `init_db()`（幂等，`CREATE TABLE IF NOT EXISTS` + 列迁移） |
| 演示数据重建入口 | `scripts/init_demo_data.py::initialize_demo_database(reset=...)` |

SQLite 连接统一通过 `db/init_db.py::connect()` 管理：`row_factory = sqlite3.Row`，每条连接开启 `PRAGMA foreign_keys = ON`，退出上下文时提交或回滚并关闭连接。

### 1.2 表清单（共 10 张表）

按职责分为三组：

| 分组 | 表 | 用途 |
| --- | --- | --- |
| 主数据 | `products` / `warehouses` | 商品名称与仓库名称的权威来源 |
| 业务核心（工作台目标模型） | `orders` / `order_items` / `inventory` / `shipments` / `tracking_events` | 订单、明细、库存、包裹、轨迹；库存保留名称兼容快照 |
| 会话 | `chat_threads` / `chat_messages` | 多轮对话持久化，替代内存 `_THREAD_HISTORY` |
| 知识 | `knowledge_articles` | 售后/物流政策结构化落库 |

### 1.3 实测数据量

| 表 | 行数 | 来源 |
| --- | --- | --- |
| `orders` | 20 | `data/demo/orders.csv` |
| `order_items` | 35 | `data/demo/order_items.csv` |
| `products` | 10 | 从 `data/demo/inventory.csv` 派生 |
| `warehouses` | 6 | 从 `data/demo/inventory.csv` 去重派生 |
| `inventory` | 10 | `data/demo/inventory.csv` |
| `shipments` | 15 | `data/demo/shipments.csv` |
| `tracking_events` | 30 | `data/demo/tracking_events.csv` |
| `chat_threads` | 5 | 运行期写入（`ChatThreadDAO`） |
| `chat_messages` | 16 | 运行期写入 |
| `knowledge_articles` | 2 | `init_db` 播种（`return-policy` / `shipping-policy`） |

### 1.4 字段类型总表

所有时间字段统一用 **TEXT 存 ISO 兼容字符串**（非 SQLite `DATETIME`），便于跨库迁移。主数据表和核心业务表均带 `is_demo TEXT NOT NULL DEFAULT 'DEMO'`。

#### products（商品主数据）

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| `id` | INTEGER | PK AUTOINCREMENT | 代理键 |
| `sku` | TEXT | NOT NULL, UNIQUE | 商品业务主键；被 `inventory.sku` 引用 |
| `product_name` | TEXT | 可空 | 商品名称权威来源 |
| `updated_at` | TEXT | NOT NULL | 最后更新时间 |
| `is_demo` | TEXT | NOT NULL, DEFAULT `'DEMO'` | 数据来源标记 |

#### warehouses（仓库主数据）

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| `id` | INTEGER | PK AUTOINCREMENT | 代理键 |
| `warehouse_id` | TEXT | NOT NULL, UNIQUE | 仓库业务主键；被 `inventory.warehouse_id` 引用 |
| `warehouse_name` | TEXT | 可空 | 仓库名称权威来源 |
| `updated_at` | TEXT | NOT NULL | 最后更新时间 |
| `is_demo` | TEXT | NOT NULL, DEFAULT `'DEMO'` | 数据来源标记 |

#### orders（订单主表）

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| `id` | INTEGER | PK AUTOINCREMENT | 代理键 |
| `order_id` | TEXT | NOT NULL, UNIQUE | **业务主键**，沿用 `1001` 格式 |
| `customer_name_masked` | TEXT | NOT NULL, DEFAULT `'***'` | 脱敏客户名 |
| `customer_country` | TEXT | NOT NULL, DEFAULT `'CN'` | ISO 3166-1 alpha-2 **小写口径**（存储 `cn`/`hk`/`us`） |
| `order_status` | TEXT | NOT NULL, DEFAULT `'pending_payment'` | 见 1.5 状态词表 |
| `payment_status` | TEXT | NOT NULL, DEFAULT `'unpaid'` | 见 1.5 |
| `fulfillment_status` | TEXT | NOT NULL, DEFAULT `'pending'` | 见 1.5 |
| `currency` | TEXT | NOT NULL, DEFAULT `'CNY'` | |
| `total_amount` | REAL | NOT NULL, DEFAULT `0` | **硬约束**：须等于明细 `Σ(quantity × unit_price)` |
| `created_at` | TEXT | NOT NULL, DEFAULT CURRENT_TIMESTAMP | |
| `updated_at` | TEXT | NOT NULL, DEFAULT CURRENT_TIMESTAMP | |
| `is_demo` | TEXT | NOT NULL, DEFAULT `'DEMO'` | 演示数据标记 |

#### order_items（订单明细）

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| `id` | INTEGER | PK AUTOINCREMENT | |
| `order_id` | TEXT | NOT NULL, FK → `orders.order_id` | ON DELETE RESTRICT |
| `sku` | TEXT | NOT NULL, FK → `inventory.sku` | ON UPDATE / DELETE RESTRICT；旧库由 `init_db()` 无损迁移 |
| `product_name` | TEXT | 可空 | 冗余快照，允许与 `inventory.product_name` 漂移 |
| `quantity` | INTEGER | NOT NULL, DEFAULT 1 | |
| `unit_price` | REAL | NOT NULL, DEFAULT 0 | |
| `currency` | TEXT | NOT NULL, DEFAULT `'CNY'` | |
| `is_demo` | TEXT | NOT NULL, DEFAULT `'DEMO'` | |

#### inventory（库存）

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| `id` | INTEGER | PK AUTOINCREMENT | |
| `sku` | TEXT | NOT NULL, UNIQUE, FK → `products.sku` | 当前兼容模型仍是一 SKU 一条库存 |
| `product_name` | TEXT | 可空 | 兼容快照；查询以 `products.product_name` 为准 |
| `warehouse_id` | TEXT | 可空, FK → `warehouses.warehouse_id` | 仓库编码，如 `WH-001` |
| `warehouse_name` | TEXT | 可空 | 兼容快照；查询以 `warehouses.warehouse_name` 为准 |
| `on_hand` | INTEGER | NOT NULL, DEFAULT 0 | 实际在库 |
| `reserved` | INTEGER | NOT NULL, DEFAULT 0 | 已预留 |
| `available` | INTEGER | NOT NULL, DEFAULT 0 | 可售，**须满足 `on_hand - reserved = available`** |
| `safety_stock` | INTEGER | NOT NULL, DEFAULT 0 | 安全库存阈值 |
| `status` | TEXT | NOT NULL, DEFAULT `'normal'` | **落库字段**，见 1.5 |
| `updated_at` | TEXT | NOT NULL, DEFAULT CURRENT_TIMESTAMP | |
| `is_demo` | TEXT | NOT NULL, DEFAULT `'DEMO'` | |

#### shipments（包裹）

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| `id` | INTEGER | PK AUTOINCREMENT | |
| `shipment_id` | TEXT | NOT NULL, UNIQUE | 业务主键，如 `SHP-1001-A`（`-A/-B` 表示拆包序） |
| `order_id` | TEXT | NOT NULL, FK → `orders.order_id` | ON DELETE RESTRICT；**一个订单可对应多个包裹** |
| `carrier` | TEXT | 可空 | DHL / FedEx / UPS / SF / USPS |
| `tracking_number` | TEXT | UNIQUE | 运单号 |
| `shipping_status` | TEXT | NOT NULL, DEFAULT `'pending'` | 见 1.5 |
| `shipped_at` | TEXT | 可空 | |
| `estimated_delivery_at` | TEXT | 可空 | |
| `delivered_at` | TEXT | 可空 | |
| `updated_at` | TEXT | NOT NULL, DEFAULT CURRENT_TIMESTAMP | |
| `is_demo` | TEXT | NOT NULL, DEFAULT `'DEMO'` | |

#### tracking_events（轨迹事件）

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| `id` | INTEGER | PK AUTOINCREMENT | |
| `shipment_id` | TEXT | NOT NULL, FK → `shipments.shipment_id` | ON DELETE RESTRICT |
| `event_time` | TEXT | NOT NULL, DEFAULT CURRENT_TIMESTAMP | |
| `event_status` | TEXT | NOT NULL, DEFAULT `'pending'` | 复用 shipping 词表 |
| `location` | TEXT | 可空 | 如 `深圳中转站` |
| `description` | TEXT | 可空 | 演示文案统一以「演示数据：」开头 |
| `is_demo` | TEXT | NOT NULL, DEFAULT `'DEMO'` | |

#### chat_threads / chat_messages

| 表 | 字段 | 类型 | 约束 |
| --- | --- | --- | --- |
| `chat_threads` | `id` | INTEGER | PK AUTOINCREMENT |
| | `thread_id` | TEXT | NOT NULL, UNIQUE |
| | `user_id` | TEXT | 可空 |
| | `created_at` / `updated_at` | TEXT | NOT NULL, DEFAULT CURRENT_TIMESTAMP |
| `chat_messages` | `id` | INTEGER | PK AUTOINCREMENT |
| | `thread_id` | TEXT | NOT NULL, FK → `chat_threads.thread_id` ON DELETE RESTRICT |
| | `role` | TEXT | NOT NULL, `CHECK(role IN ('user','assistant','system'))` |
| | `content` | TEXT | NOT NULL |
| | `created_at` | TEXT | NOT NULL, DEFAULT CURRENT_TIMESTAMP |

#### knowledge_articles

| 字段 | 类型 | 约束 |
| --- | --- | --- |
| `id` | INTEGER | PK AUTOINCREMENT |
| `slug` | TEXT | NOT NULL, UNIQUE |
| `category` | TEXT | NOT NULL |
| `title` | TEXT | 可空 |
| `content` | TEXT | NOT NULL |
| `source` | TEXT | 可空（指向 `data/*.md`） |
| `updated_at` | TEXT | NOT NULL, DEFAULT CURRENT_TIMESTAMP |

### 1.5 状态词表（唯一口径）

状态码与中文展示名的**单点维护处**为 `src/ecommerce_assistant/schema/statuses.py`：数据库只存英文码，中文仅在展示层生成。

| 词表 | 取值 |
| --- | --- |
| `ORDER_STATUS_LABELS` | `pending_payment` `paid` `processing` `shipped` `delivered` `cancelled` `refund_requested` |
| `PAYMENT_STATUS_LABELS` | `unpaid` `paid` `refunded` `partially_refunded` |
| `FULFILLMENT_STATUS_LABELS` | `pending` `processing` `partial` `fulfilled` `cancelled` `held` |
| `SHIPPING_STATUS_LABELS` | `pending` `shipped` `in_transit` `out_for_delivery` `delivered` `exception` |
| `INVENTORY_STATUS_LABELS` | `normal` `low_stock` `out_of_stock` |
| `COUNTRY_LABELS` | 20 国，地区表述遵循合规口径：`hk` → 「中国香港」、`mo` → 「中国澳门」、`tw` → 「中国台湾」 |

`label_of(labels, code)` 对未知码**原样返回**而非静默兜底，目的是暴露数据问题。

---

## 2. 现有索引现状（实测导出）

| 表 | 索引 | 定义 | 状态 |
| --- | --- | --- | --- |
| `orders` | `idx_orders_order_id_unique` | UNIQUE(`order_id`) | 有效（UNIQUE 约束的显式实现） |
| `orders` | `sqlite_autoindex_orders_1` | UNIQUE(`order_id`) | 约束自动索引（与上条重复，SQLite 行为） |
| `orders` | `idx_orders_status` | (`order_status`) | 有效 |
| `order_items` | `idx_order_items_order_id` | (`order_id`) | 有效 |
| `order_items` | `idx_order_items_sku` | (`sku`) | 有效 |
| `order_items` | `idx_order_items_order_sku_unique` | UNIQUE(`order_id`,`sku`,`product_name`) | 有效 |
| `order_items` | `idx_order_items_demo_identity` | UNIQUE(`order_id`,`sku`,`product_name`) | **完全重复**，v2.1 已删除 |
| `inventory` | `idx_inventory_sku_unique` | UNIQUE(`sku`) | 有效 |
| `inventory` | `sqlite_autoindex_inventory_1` | UNIQUE(`sku`) | 约束自动索引（重复） |
| `inventory` | `idx_inventory_status` | (`status`) | 有效 |
| `inventory` | `idx_inventory_warehouse` | (`warehouse_id`,`warehouse_name`) | 有效 |
| `shipments` | `idx_shipments_shipment_id_unique` | UNIQUE(`shipment_id`) | 有效 |
| `shipments` | `sqlite_autoindex_shipments_1/2` | UNIQUE(`shipment_id`) / UNIQUE(`tracking_number`) | 约束自动索引 |
| `shipments` | `idx_shipments_order_id` | (`order_id`) | 有效 |
| `shipments` | `idx_shipments_tracking_number` | (`tracking_number`) | 有效 |
| `tracking_events` | `idx_tracking_events_shipment_id` | (`shipment_id`) | 有效 |
| `tracking_events` | `idx_tracking_events_event_time` | (`event_time`) | 有效 |
| `tracking_events` | `idx_tracking_events_identity_unique` | UNIQUE(`shipment_id`,`event_time`,`event_status`,`location`,`description`) | 有效 |
| `tracking_events` | `idx_tracking_events_demo_identity` | UNIQUE(`shipment_id`,`event_time`,`event_status`,`location`,`description`) | **完全重复**，v2.1 已删除 |
| `orders` | `idx_orders_created_at` | (`created_at`) | v2.1 新增 |
| `orders` | `idx_orders_is_demo` | (`is_demo`) | v2.1 新增 |
| `shipments` | `idx_shipments_updated_at` | (`updated_at`) | v2.1 新增 |
| `shipments` | `idx_shipments_is_demo` | (`is_demo`) | v2.1 新增 |
| `chat_threads` | `idx_chat_threads_thread_id` | (`thread_id`) | 有效（+ 自动索引重复） |
| `chat_messages` | `idx_chat_messages_thread_id` | (`thread_id`) | 有效 |
| `knowledge_articles` | `idx_knowledge_articles_slug_unique` | UNIQUE(`slug`) | 有效 |

结论：覆盖面已足够。v2.1 已删除两对重复定义的唯一索引，索引定义收敛到 `init_db._ensure_indexes` 单一处（`scripts/init_demo_data.py::_ensure_demo_indexes` 已移除）；缺失的 SKU 关联索引见 6.2。

---

## 3. 现有工具如何查询数据

### 3.1 分层调用链（实测）

```
Streamlit 页面 / API / Agent
        │
        ├── workbench/queries.py        只读查询层：SQL + 中文展示字段补齐
        │
        └── agents/ecommerce_assistant.py
                │  _detect_intent() 关键词路由
                ├── get_order_status(order_id)        → tools/order.py
                ├── get_inventory_status(sku)         → tools/inventory.py
                ├── get_logistics_status(order_id)    → tools/logistics.py
                └── retrieve_knowledge(question)      → rag/retriever.py
                              │
                              ▼
                    tools/database.py（数据访问层）
                      query_order / query_inventory / query_logistics
                              │
                              ▼
                    db/init_db.py（get_order_by_id / get_inventory_by_sku /
                                   get_order_items_by_order_id / get_tracking_events）
                              │
                              ▼
                    data/ecommerce_assistant.db (SQLite)
```

关键点：`tools/order.py`、`tools/inventory.py`、`tools/logistics.py` **已经是薄封装**——不持有数据，只把 `tools/database.py` 的结构化结果格式化成自然语言。v1.0 文档描述的 `ORDERS` / `INVENTORY` / `LOGISTICS` 内存字典**已不存在**。

### 3.2 统一业务查询层（2026-09-22 改造后现状）

`tools/database.py` 是**唯一**的业务查询入口，Agent 工具、FastAPI 只读端点共用同一套函数。返回结构统一为 `{ok, code, message, data}`。

**错误码词表（5 个）**

| 码 | 语义 | HTTP 映射 |
| --- | --- | --- |
| `OK` | 查询成功 | 200 |
| `INVALID_ARGUMENT` | 参数错误（缺失、为空） | 400 |
| `NOT_FOUND` | 数据不存在（订单 / SKU / 物流单不存在） | 404 |
| `NO_LOGISTICS` | 订单存在但无包裹记录（区别于订单不存在） | 404 |
| `DB_ERROR` | 数据库错误（`sqlite3.Error` 或未预期异常） | 500 |

`_execute()` 统一兜底：任何底层异常都转成 `DB_ERROR`，业务函数**不向外抛异常**。

**订单查询**

| 函数 | 能力 | 关键行为 |
| --- | --- | --- |
| `query_order(order_id)` | 订单主表 + 商品 + 包裹 + 状态 | 返回 `data.items[]`、`data.shipments[]`（全量）、`data.status` |
| `query_order_items(order_id)` | 仅订单商品 | `{order_id, count, items[]}`；订单存在但无明细则 `NOT_FOUND` |
| `query_order_shipments(order_id)` | 仅订单包裹 | 按 `shipment_id ASC`，一单多包裹返回全部；无包裹 `NO_LOGISTICS` |
| `query_order_status(order_id)` | 仅状态 + 计数 | 不返回明细行，供状态类提问走最短路径 |

订单不存在一律返回 `NOT_FOUND` + 「订单 X 不存在，无法查询到对应订单信息。」

**库存查询**

| 函数 | 能力 |
| --- | --- |
| `query_inventory(sku=, product_name=, warehouse_name=, warehouse_id=, keyword=)` | 条件查询，**至少给一个筛选条件**，否则 `INVALID_ARGUMENT` |
| `query_inventory_by_sku(sku)` | 按 SKU 精确查单条（大小写不敏感） |
| `list_inventory_records(...)` | 列表查询，**允许无过滤条件**（供 API 分页端点与页面复用） |

返回字段：`on_hand`、`reserved`、`available`、`safety_stock` 全部转 `int`。

**状态改为规则计算（唯一权威来源）**：

```
available <= 0            -> out_of_stock 缺货
available <= safety_stock -> low_stock    库存不足
available >  safety_stock -> normal       正常
```

落库 `status` 列不再作权威值。若与规则不一致，原值保留在 `stored_status` 并置 `status_mismatch = true`，由展示层显式提示，不静默吞掉。

**物流查询**

| 函数 | 能力 |
| --- | --- |
| `query_logistics(order_id=, shipment_id=, tracking_number=)` | 三选一，优先级 `shipment_id` > `tracking_number` > `order_id` |
| `query_shipment_events(shipment_id)` | 仅轨迹，按 `event_time ASC, id ASC` |

- 按 `order_id` 查询返回该订单**全部**包裹，每个包裹带自己的 `events` 与 `current_status`；顶层 `shipment` / `events` / `current_status` / `shipment_count` 为兼容字段，指向首个包裹
- `tracking_number` 用 `UPPER()` 比较，大小写不敏感
- 轨迹排序加 `id` 作为同 `event_time` 的 tiebreaker
- 订单不存在 → `NOT_FOUND`；订单存在但无包裹 → `NO_LOGISTICS`；物流单/运单号不存在 → `NOT_FOUND`

**消费方**

- `tools/order.py` / `inventory.py` / `logistics.py` 仍是薄封装，只做自然语言格式化；签名 `get_*_status(x, db_path=None) -> str` 保持不变
- `api/service.py` 的 orders/inventory/shipments 列表、详情及 `/dashboard/summary` 均调用本层；API、Agent 与工作台不再各自维护业务 SQL

### 3.3 意图路由

`agents/ecommerce_assistant.py::_detect_intent()` 为纯关键词匹配，**检查顺序为：库存 → 物流 → 订单 → 知识库**。库存/物流先于订单，用于避免「订单 1005 使用了什么物流？」被误判为订单查询。

### 3.4 只读查询层（页面专用）

`workbench/queries.py` 是页面唯一取数入口，页面内不写 SQL；该模块自身也不连接数据库，只调用 `tools/database.py` 并补展示标签：

| 函数 | 作用 |
| --- | --- |
| `list_orders` / `get_order` | 订单列表/详情，补 `country_label` / `order_status_label` / `payment_status_label` / `fulfillment_status_label` |
| `list_order_items` | 明细，补 `subtotal` |
| `list_shipments_by_order` / `list_shipments` | 包裹，补 `shipping_status_label` |
| `list_tracking_events` | 轨迹，补 `event_status_label` |
| `list_inventory` / `list_warehouses` | 库存与仓库清单，补 `status_label` |
| `order_summary` / `inventory_summary` / `shipment_summary` | 指标卡聚合 |
| `dashboard_summary` | 首页与 `/dashboard/summary` 同源的指标、最近订单和预警列表 |
| `DEMO_NOTICE` | 统一演示数据声明文案 |

### 3.5 知识库检索现状

`rag/retriever.py` 已按 `returns` / `shipping` 分类读取 `knowledge_articles` 表。文章正文、标题与来源以数据库为唯一来源，代码不再维护 `DOCS` 正文副本；数据库为空或无匹配文章时返回统一未命中兜底。

v2.5 起返回值由 `{answer, source}` 扩展为 `{answer, source, sources}`：`sources` 为结构化来源数组（每项 `{doc, snippet, placeholder}`），未命中时为空数组且**不得为 None**，供前端渲染来源块；`source` 单值字段保留以兼容既有调用方。未命中返回 `MISS_ANSWER` 常量，两段式文案（按 `\n\n` 分段落渲染），不道歉、不伪造政策文本。文案中的示例问法刻意写成「某个订单号现在到哪里了」而非具体单号——写成「订单 1001 的状态」会让 `test_api.py::test_missing_order_id_is_not_filled_with_default_1001` 把兜底回复误判成订单查询结果。

### 3.6 API 层取数面（只读端点）

`api/service.py` 与 `workbench/queries.py` 均复用 `tools/database.py`，API 不依赖工作台展示层。当前 10 条只读端点：

| 端点 | 处理函数 | 取数对象 |
| --- | --- | --- |
| `GET /info` | `get_info` | 无库访问；`models` 改为读模型候选清单 |
| `GET /models` | `list_models` | 无库访问；返回 `OPENAI_MODELS` 短清单，`include_remote=true` 时合并中转站 `/v1/models` |
| `GET /dashboard/summary` | `get_dashboard_summary` | 聚合：今日订单 / 待处理 / 待发货 / 运输中包裹 / 库存预警 / 物流异常 + 最近订单 5 条 + 库存预警 10 条 + 物流异常 10 条 + 数据更新时间 |
| `GET /orders` | `list_orders` | `orders`，支持 `search` / `status` / `country` / `carrier` / `warehouse_id` |
| `GET /orders/{order_id}` | `get_order_detail` | `orders` + `order_items` + `shipments` |
| `GET /inventory` | `list_inventory` | `inventory`，支持 `search` / `warehouse_id` |
| `GET /inventory/{sku}` | `get_inventory_detail` | `inventory`（SKU 转大写） |
| `GET /shipments` | `list_shipments` | `shipments`，支持 `search` / `carrier` / `status` / `country` / `warehouse_id` |
| `GET /shipments/{shipment_id}` | `get_shipment_detail` | `shipments` + `tracking_events` |
| `GET /shipments/{shipment_id}/events` | `get_shipment_events` | `tracking_events` |

> 位置列改为函数名而非行号：v2.3 起 `service.py` 顶部多次增删导入与中间件，行号反复漂移，函数名更稳定。

写库端点仅 2 条（`POST /ecommerce-assistant/invoke`、`POST /ecommerce-assistant/stream`），且只写 `chat_threads` / `chat_messages`，不触碰业务表。

### 3.7 模型选择链路（2026-09-22 新增）

模型在改造前是「隐式全局单值」——`llm/client.py::call_llm()` 内部读 `OPENAI_MODEL`，链路任何一层都无法覆盖。v2.3 打通了一条显式透传通道：

| 层 | 文件 | 变更 |
| --- | --- | --- |
| UI | `streamlit_app.py` | 对话区上方 `st.selectbox`（候选来自 `GET /models`）+「拉取全部模型」按钮；选择存入 `st.session_state.selected_model` |
| Client | `client/client.py` | `invoke(..., model=None)`，**model 非空才写入 payload**；`list_models(include_remote)`；invoke 超时 20s → 60s 与 LLM 层对齐 |
| API | `api/service.py` | `MessageRequest.model` 透传到 `agent.invoke({...})`；响应新增 `intent` |
| Agent | `agents/ecommerce_assistant.py` | `handle_question(question, history, model)` → `call_llm(..., model=model)` |
| LLM | `llm/client.py` | `call_llm(prompt, system_prompt, model)`，`model or default_model`；新增 `get_model_candidates()` / `list_remote_models()` |

**作用范围契约**：模型只影响 `rag`（售后政策）与 `llm`（通用问答）两个分支。`order` / `inventory` / `logistics` 三条分支是确定性 SQL 查询，**不调用模型**——这是「不允许大模型猜测业务数据」约束的直接结果，也由 `test_model_selection.py::test_tool_branch_does_not_call_llm` 守住。页面通过响应里的 `intent` 在气泡上方标注「模型：xxx」或「工具查询 · 未使用模型」，避免用户误判功能失效。

**清单来源契约**：`OPENAI_MODELS`（逗号分隔，去重保序）为默认来源，无网络依赖；`include_remote=true` 时由后端实时读取中转站 `/v1/models` 合并，`source` 字段返回 `env` 或 `merged`，拉取失败静默降级为 `env`。

`llm/client.py` 的默认模型回退值同时从 `gpt-5.2` 校正为 `gpt-5.6-sol`，与 `.env.example`、`schema.py` 一致。

### 3.8 前端契约与 CORS（2026-09-23，v2.5）

独立 Web 前端 `frontend/index.html`（源自 `design/index.html`）接入现有后端，`/invoke` 的响应必须完整满足 `docs/PRD.md` v0.2 §6.7.1：

| 字段 | 生产位置 | 说明 |
| --- | --- | --- |
| `route` | `schema/routes.py` 常量 + `agents/ecommerce_assistant.py::answer_question` | 取值 `after`/`order`/`stock`/`ship`/`unknown`；**前端不得自行推断** |
| `tool_calls` | `_tool_answer()`，名字来自 `routes.py::TOOL_CALL_NAMES` | `order_lookup` / `stock_lookup` / `shipping_lookup`；参数缺失时为空数组（确实没有调用工具） |
| `sources` | `rag/retriever.py::_source_of()` | 仅知识库命中时非空 |
| `run_id` | `api/service.py::_chat_message_from_state()` | 形如 `run_a1b2c3`，每条唯一（不再复用 `thread_id`） |

`route` 的判定依据是**回答实际来自哪里**，不是关键词命中了哪一类。两者仅在两处不同：知识库命中时 `intent="rag"` 而 `route="after"`；模型直接作答时 `intent="llm"` 而 `route="after"`。`intent` 字段保留，供 Streamlit 气泡标注「模型：xxx / 工具查询」使用。

`answer_question()` 返回结构化字典 `{content, route, tool_calls, sources, intent}`；`handle_question()` 保留为返回字符串的薄包装，因为有 8 处以上既有断言依赖它返回 `str`。

**正文不再拼接「来源：」**：来源只走 `sources`，否则前端正文与来源块会重复展示同一文档路径。Streamlit 侧同步在气泡下方渲染 `sources`，避免信息丢失。

**CORS**：`api/service.py` 注册 `CORSMiddleware`（`allow_origins=["*"]`、`allow_credentials=False`）。前端以 `file://` 直接打开时 `Origin` 为 `null`，必须放行；`allow_credentials` 保持 `False`，与通配来源同时开启会被浏览器拒绝。

**SSE 协议补齐**：`/stream` 由「只推 token」改为按 PRD §6.7.2 输出 `start` → `route` → `tool_call*` → `sources?` → `token*` → `[DONE]`；`route` 先于正文到达，供前端在正文前播放投递动效。出错时发一条 `error` 后仍以 `[DONE]` 收尾。

---

## 4. 现有表结构与目标模型的差异

目标模型为 5 张表：`orders` / `order_items` / `inventory` / `shipments` / `tracking_events`。

### 4.1 结论：5 张目标表均已存在，字段差异为零

| 目标表 | 现状 | 字段覆盖 | 差异 |
| --- | --- | --- | --- |
| `orders` | 已建、20 行 | `order_id` + 客户脱敏 + 三态状态 + 币种 + 金额 + 时间戳 + `is_demo` | 无缺失 |
| `order_items` | 已建、35 行 | `order_id` / `sku` / `product_name` / `quantity` / `unit_price` / `currency` / `is_demo` | 无缺失 |
| `inventory` | 已建、10 行 | `sku` / 商品 / `warehouse_id`+`warehouse_name` / `on_hand`+`reserved`+`available`+`safety_stock` / `status` / `is_demo` | 无缺失 |
| `shipments` | 已建、15 行 | `shipment_id` / `order_id` / `carrier` / `tracking_number` / `shipping_status` / 三时间戳 / `is_demo` | 无缺失 |
| `tracking_events` | 已建、30 行 | `shipment_id` / `event_time` / `event_status` / `location` / `description` / `is_demo` | 无缺失 |

### 4.2 与 v1.0 设计的字段名对照（说明改名原因）

v1.0 提出的字段与最终落地字段不一致，落地版本为当前实现：

| v1.0 提议 | 实际落地 | 改名原因 |
| --- | --- | --- |
| `inventory.warehouse` | `warehouse_id` + `warehouse_name` | 支持按编码筛选 + 按名称展示 |
| `inventory.stock_qty` | `on_hand` | 与 `reserved`/`available` 构成标准库存三件套 |
| `inventory.available_qty` | `available` | 精简命名 |
| `shipments.status` | `shipping_status` | 与 `orders.order_status` 显式区分，避免跨表歧义 |
| `shipments.shipping_method` | 移除 | 承运商信息已由 `carrier` 表达，`shipping_method` 无独立语义 |
| `tracking_events.event_type` | `event_status` | 与物流状态词表共用一套取值，可直查可筛选 |
| `tracking_events.event_description` | `description` | 精简命名 |
| `orders.shipping_address` / `consignee_name` / `consignee_phone` | **移除** | 敏感个人信息，按合规要求不落库；`api/service.py::_sanitize_order_detail` 亦做二次剔除 |

### 4.3 真正的差异在「模型之外」

字段层面无缺口，剩余差异集中在约束、口径与工程收口，汇总为第 5 章风险清单。

---

## 5. 不兼容风险清单

严重度分级：**P0 = 会破坏数据正确性**；**P1 = 会导致口径分裂或契约不一致**；**P2 = 工程质量与可维护性**。

### 5.1 P0：演示数据第二写入源与导入期初始化 —— v2.8 已关闭

| 项 | 内容 |
| --- | --- |
| 原问题 | 内联种子与 CSV 曾出现相同 `order_id` 的金额和状态不一致；`api/service.py` 又在模块导入期建库和播种，可能在重建空表窗口写入旧口径数据 |
| 原后果 | 主表金额与明细不自洽，测试导入、`uvicorn --reload` 或普通模块导入也可能产生隐式写库副作用 |
| **v2.8 处置** | 内联种子口径已与 `data/demo/*.csv` 对齐；仅在 5 张业务表全部为空时播种；`initialize_demo_database(reset=True)` 在单事务内清理和重建；FastAPI 改由 `lifespan` 调用 `initialize_database(seed_demo=True)`，模块导入不再写库 |
| 验证 | 重复初始化数据量稳定；导入 `api/service.py` 不创建数据库；lifespan 启动与关闭路径有回归测试 |

### 5.2 P1：API 层自带第二套状态口径 —— v2.4 已关闭

| 项 | 内容 |
| --- | --- |
| 位置 | 原 `api/service.py:272-283`（`list_inventory`）、`296-299`（`get_inventory_detail`） |
| 原问题 | 两个端点在响应里**运行时重算中文状态**（`缺货`/`库存不足`/`正常`），**完全忽略 `inventory.status` 落库列** |
| 原后果 | (1) 违反「DB 存英文码、展示层转中文」的单一词表契约（`schema/statuses.py`）;(2) 与 `tools/database.py` 的库存状态语义相反，同一 SKU 可能得到不同状态;(3) 响应字段混入中文，前端无法按码筛选 |
| 同文件内自相矛盾 | `GET /dashboard/summary` 按落库英文码筛选与返回，而 `GET /inventory` 重算并返回中文。同一字段名 `status` 在两条端点上两套取值 |
| **v2.4 处置** | `list_inventory` 与 `get_inventory_detail` 均调用 `tools.database`，响应返回**英文码**；`/dashboard/summary` 的预警数量和列表也调用公开规则 `inventory_status_from_rule()`，统一以 `available` / `safety_stock` 计算，不再依赖可能漂移的落库 `status`。回归测试覆盖“落库缺货但数量正常”和“落库正常但数量缺货”两个相反漂移场景 |

### 5.3 P1：`order_items.sku` 无外键约束 —— v2.6 已关闭

| 项 | 内容 |
| --- | --- |
| 位置 | `order_items` 表定义 |
| 原问题 | `order_items.sku` 与 `inventory.sku` 仅逻辑关联，无 FK |
| 原后果 | 可写入不存在的 SKU；「订单里的商品是否缺货」类联查会静默丢行；`inventory` 删行不受阻 |
| **v2.6 处置** | 新库直接声明 `order_items.sku → inventory.sku`，ON UPDATE / DELETE RESTRICT；旧库初始化时先查孤儿，再在 SAVEPOINT 内重建 `order_items` 并保留原 id/数据。发现孤儿则列出明细并中止，不自动删除。Demo 与真实 CSV 导入均改为先写 inventory、再写 order_items，导入校验同时支持本批和库内已有 SKU |

### 5.4 P1：一单多包裹时物流工具只返回最新一条 —— v2.2 已关闭

| 项 | 内容 |
| --- | --- |
| 原位置 | `tools/database.py:219-224` |
| 原问题 | `order_id` 查询路径固定 `ORDER BY updated_at DESC LIMIT 1` |
| 原后果 | 拆包订单（演示数据订单 1005）经 Agent 提问时只能看到 1 个包裹，与工作台页面的多包裹展示不一致 |
| **v2.2 处置** | `query_logistics(order_id=)` 改为返回全部包裹（每个带自己的轨迹与当前状态），`query_order(order_id)` 的 `shipments` 同样全量。取数下沉到新增的 `db/init_db.get_shipments_by_order_id()`，`get_shipment_by_order_id()`（单条）保留仅作兼容。工具签名与 `get_logistics_status(order_id) -> str` 返回类型不变，多包裹时文案列出全部包裹 |

### 5.5 P2：索引重复定义 —— v2.1 已关闭

`order_items` 的 `idx_order_items_order_sku_unique` 与 `idx_order_items_demo_identity` 定义完全相同；`tracking_events` 的 `idx_tracking_events_identity_unique` 与 `idx_tracking_events_demo_identity` 完全相同。根因是 `init_db()` 与 `scripts/init_demo_data.py::_ensure_demo_indexes` 各写了一份索引。后果：写放大、`sqlite_master` 噪声、后续 DDL 变更需改两处。

已在 v2.1 关闭：两条重复索引由 `_ensure_indexes` 主动 `DROP INDEX IF EXISTS` 清除，`scripts/init_demo_data.py::_ensure_demo_indexes` 整体移除。

### 5.6 P2：失效查询参数 —— v2.10 已关闭

| 端点 | 声明但未使用 | 状态 |
| --- | --- | --- |
| `GET /orders` | 原 `warehouse_id`、`carrier` | `carrier` 已通过 `orders → shipments` 关联生效；`warehouse_id` 通过 `orders → order_items → inventory → warehouses` 生效，表示订单商品当前关联的库存仓库 |
| `GET /inventory` | 原 `status`、`country`、`carrier` | `status` 与 `warehouse_id` 真实生效；无业务关系的 `country`、`carrier` 已从签名移除 |
| `GET /shipments` | 原 `country`、`warehouse_id` | `country` 已通过 `shipments → orders.customer_country` 关联生效；`warehouse_id` 通过包裹订单的商品库存关联生效，表示订单商品当前关联的库存仓库 |

v2.11 后，OpenAPI 只声明有明确语义的数据关系。订单和物流的 `warehouse_id` 均表示“订单商品当前关联的库存仓库”，查询使用 `EXISTS` 避免多商品和多包裹导致重复；它不表示实际发货仓库。未来增加履约仓库字段时，应另设“实际发货仓库”筛选，不能复用当前语义。

### 5.7 P2：遗留双库残留目录

`src/data/ecommerce_assistant.db` 仍存在（内含旧内联种子：3 订单 / 4 库存 / 3 包裹），属于 `DEFAULT_DB_PATH` 修正为 `parents[3]` 之前的历史产物。当前全部代码路径均已指向项目根 `data/`，实测无代码再写入该文件。该目录被 `*.db` 规则忽略，不在版本控制内。建议确认后清理，避免排查时误连。

### 5.8 P2：`knowledge_articles` 表已建但未被读取 —— v2.7 已关闭

`rag/retriever.py` 已移除硬编码正文，通过 `retrieve_knowledge(query, db_path=None)` 查询表内文章并保留 `{answer, source, sources}` 契约。测试验证修改数据库正文会立即反映到回答，空表不会回退到旧文本。

### 5.9 P2：文档与实现不同步 —— v2.8 已关闭

v2.8 已统一 README、前端说明、PRD、设计参照和本文件中的当前包路径、`8084` 服务端口、SQLite 检索方案、初始化时机与测试基线。历史版本记录中的旧数字作为对应版本快照保留，不代表当前状态。

---

## 6. 索引设计

### 6.1 保留（已验证有效，覆盖热路径）

```sql
-- 订单：主键查 + 状态筛选 + 时间排序
CREATE UNIQUE INDEX idx_orders_order_id_unique ON orders(order_id);
CREATE INDEX idx_orders_status ON orders(order_status);

-- 明细：按订单取明细 / 按 SKU 反查订单
CREATE UNIQUE INDEX idx_order_items_order_sku_unique ON order_items(order_id, sku, product_name);
CREATE INDEX idx_order_items_order_id ON order_items(order_id);
CREATE INDEX idx_order_items_sku ON order_items(sku);

-- 库存：SKU 主键查 + 状态筛选 + 仓库筛选
CREATE UNIQUE INDEX idx_inventory_sku_unique ON inventory(sku);
CREATE INDEX idx_inventory_status ON inventory(status);
CREATE INDEX idx_inventory_warehouse ON inventory(warehouse_id, warehouse_name);

-- 包裹：按订单取包裹 / 运单号反查
CREATE UNIQUE INDEX idx_shipments_shipment_id_unique ON shipments(shipment_id);
CREATE INDEX idx_shipments_order_id ON shipments(order_id);
CREATE INDEX idx_shipments_tracking_number ON shipments(tracking_number);

-- 轨迹：按包裹取轨迹 + 时间排序
CREATE INDEX idx_tracking_events_shipment_id ON tracking_events(shipment_id);
CREATE INDEX idx_tracking_events_event_time ON tracking_events(event_time);
CREATE UNIQUE INDEX idx_tracking_events_identity_unique
  ON tracking_events(shipment_id, event_time, event_status, location, description);

-- 会话与知识
CREATE INDEX idx_chat_threads_thread_id ON chat_threads(thread_id);
CREATE INDEX idx_chat_messages_thread_id ON chat_messages(thread_id);
CREATE UNIQUE INDEX idx_knowledge_articles_slug_unique ON knowledge_articles(slug);
```

### 6.2 建议新增

```sql
-- 工作台订单列表默认排序（created_at DESC），当前无索引支撑
CREATE INDEX idx_orders_created_at ON orders(created_at DESC);

-- 物流列表默认排序（updated_at DESC）
CREATE INDEX idx_shipments_updated_at ON shipments(updated_at DESC);

-- 库存预警看板：状态 + 可售，配合 idx_inventory_status 减少回表
CREATE INDEX idx_inventory_status_available ON inventory(status, available);

-- 拆包订单识别：按订单统计包裹数
CREATE INDEX idx_shipments_order_status ON shipments(order_id, shipping_status);

-- 演示/真实数据隔离筛选
CREATE INDEX idx_orders_is_demo ON orders(is_demo);
CREATE INDEX idx_shipments_is_demo ON shipments(is_demo);
```

### 6.3 建议删除（冗余）

```sql
DROP INDEX IF EXISTS idx_order_items_demo_identity;      -- 与 idx_order_items_order_sku_unique 完全重复
DROP INDEX IF EXISTS idx_tracking_events_demo_identity;  -- 与 idx_tracking_events_identity_unique 完全重复
```

删除后需保证 `init_db()` 与 `scripts/init_demo_data.py` 只保留一处索引定义，避免重建时回流。

---

## 7. 演示数据与真实数据的目录边界

### 7.1 目录职责

```
data/
├── demo/                      # 演示数据：纳入版本控制，是演示数据的唯一权威源
│   ├── orders.csv             # 20 行
│   ├── order_items.csv        # 35 行
│   ├── inventory.csv          # 10 行
│   ├── shipments.csv          # 15 行
│   └── tracking_events.csv    # 30 行
├── real/                      # 真实（授权脱敏）数据：.gitignore 忽略，不随仓库分发
├── ecommerce_assistant.db     # 运行库：单一权威库，被 *.db 规则忽略
├── return_policy.md           # 知识库源文件
└── shipping_policy.md         # 知识库源文件
```

### 7.2 边界规则

| 规则 | 说明 |
| --- | --- |
| R1 单一权威库 | 只有 `data/ecommerce_assistant.db`。禁止出现 `src/data/` 等第二路径（5.7） |
| R2 演示数据源 | `data/demo/*.csv` 是唯一源；`initialize_demo_database(reset=True)` 是唯一推荐重建入口 |
| R3 真实数据源 | `data/real/*.csv` 只经 `scripts/import_data.py` 导入，**不参与自动播种** |
| R4 隔离标记 | 每行数据带 `is_demo`。演示数据固定 `'DEMO'`；真实数据导入时写 `'REAL'` |
| R5 界面声明 | 页面统一展示 `workbench/queries.py::DEMO_NOTICE`（"演示数据，不代表真实商家业务数据"） |
| R6 敏感信息 | 真实数据导入拒绝 `customer_name`/`phone`/`email`/`address` 等敏感字段（`scripts/import_data.py::SENSITIVE_FIELD_NAMES`） |
| R7 版本控制 | `.gitignore` 必须包含 `.env`、`*.db`、`*.sqlite`、`data/real/`、`exports/`、`customer_data/`（当前已满足） |
| R8 容器路径 | 容器内库文件走 `ECOMMERCE_DB_PATH=/app/data/db/ecommerce_assistant.db`，由 named volume `ea-data` 承载；`.db` 不进镜像（`.dockerignore` 排除 `**/*.db`），首次启动仍由 lifespan 从镜像内的 `data/demo/*.csv` 播种。**卷必须挂 `/app/data/db` 而非 `/app/data`**，否则会连镜像里的播种源 CSV 一起遮住（详见 README 第 8 节） |

### 7.3 导入校验链（`scripts/import_data.py`）

1. 必填字段完整性
2. 敏感字段名黑名单
3. 数值/日期格式（ISO 兼容）
4. 关联校验：`order_items.order_id` → `orders`；`shipments.order_id` → `orders`；`tracking_events.shipment_id` → `shipments`
5. 单事务执行，任一行失败整体回滚
6. 幂等：唯一键 `INSERT ... ON CONFLICT ... DO UPDATE`
7. `--dry-run` 只校验不写库
8. 错误格式：`orders.csv:12: 缺少必填字段 'order_id'`

### 7.4 待补

- `data/real/` 目前为空目录（未被 git 跟踪），可考虑放入 `.gitkeep` 以固定目录语义。
- 真实数据导入后工作台尚无 `is_demo` 筛选开关，会与演示数据混显；需在第 7 步补齐。

---

## 8. 后续 9 步实现顺序

每步保持「接口契约不变、工具签名不变、页面入口不变」。**一步验收通过后再启动下一步**。

| 步 | 目标 | 涉及文件 | 验收标准 |
| --- | --- | --- | --- |
| 1 | **收敛演示数据单一写入源**：内联种子与 CSV 口径对齐或删除；`reset=True` 改单事务；建库/播种移入 FastAPI lifespan | `db/init_db.py`、`api/service.py`、`scripts/init_demo_data.py` | 空表窗口下重建不再抛 `ValueError`；`pytest tests/` 全绿；重复导入 3 次金额恒自洽 |
| 2 | **索引清理与补齐** | `db/init_db.py`、`scripts/init_demo_data.py` | 冗余索引删除；新增索引生效；索引定义收敛到单一处 |
| 3 | **API 状态口径接入 `schema/statuses.py`** | `api/service.py` | `/inventory`、`/inventory/{sku}` 返回落库英文码；中文只在展示层生成；词表无第二份 |
| 4 | **补齐失效查询参数** | `api/service.py` | `status`/`country`/`carrier`/`warehouse_id` 在对应端点真实生效，或从签名移除 |
| 5 | **抽取主数据表 `warehouses` / `products`** | 新建迁移 + `inventory` 回填 | `warehouse_id` 可 JOIN 取名称；`product_name` 单一来源；旧字段保留兼容期 |
| 6 | **`knowledge_articles` 接管检索**：`retriever.py` 改为读表，保留 `source` 引用 | `rag/retriever.py`、`db/init_db.py` | 售后问答仍返回来源；未命中仍回「知识库暂未覆盖」；表与字典不再双份 |
| 7 | **演示/真实数据边界固化**：`is_demo` 筛选开关 + `data/real` 导入联调 | `workbench/queries.py`、`api/service.py`、`scripts/import_data.py` | 真实数据导入后可按 `is_demo` 隔离筛选；界面声明持续可见 |
| 8 | **工作台页面统一走查询层**：分页、状态筛选统一由 `workbench/queries.py` 提供；`/dashboard/summary` 与页面指标口径对齐（同一指标不得出现两个 SQL 版本） | `pages/*.py`、`workbench/queries.py`、`api/service.py` | 页面零 SQL；状态全部来自 `label_of`；筛选与 API 语义一致；首页指标与 `/dashboard/summary` 数值一致 |
| 9 | **回归与文档收口** | `README.md`、`docs/*`、`tests/*` | `pytest tests/` 全绿；README 结构与实际包路径一致；文档与实现契约一致 |

### 依赖关系

```
1 ──┐
2 ──┼──► 3 ───────► 4 ──► 8 ──► 9
    │               ▲     ▲
5 ──┴──► 6 ─────────┘     │
7 ────────────────────────┘
```

- 第 1、2 步必须先做：它们是数据正确性前提，其余步骤的验收都依赖一个自洽的库。
- 第 3、4 步共用 `api/service.py`，串行执行避免冲突。
- 第 5 步先固化商品/仓库主数据，再处理第 4 步中的 `warehouse_id` 语义；当前订单/物流筛选明确表示商品库存仓库，不冒充实际履约仓库。
- 第 6 步可在第 1、2 步后独立进行。
- 第 8 步依赖 3、5、7。

### 8.1 实现状态（截至 2026-09-24）

| 步 | 状态 | 落地内容 / 剩余缺口 |
| --- | --- | --- |
| 1 收敛演示数据单一写入源 | **完成** | `seed_demo_data` 仅在 5 张业务表全空时播种；内联种子金额与状态对齐 CSV；`reset=True` 在单事务内重建；FastAPI 通过 lifespan 初始化，导入 `api/service.py` 不再写库。风险 5.1 关闭。 |
| 2 索引清理与补齐 | **完成** | 删除 `order_items` / `tracking_events` 上成对重复的 `*_demo_identity` 索引；新增 `idx_orders_created_at`、`idx_orders_is_demo`、`idx_shipments_updated_at`、`idx_shipments_is_demo`；索引定义收敛到 `init_db._ensure_indexes` 单一处（`scripts/init_demo_data.py` 的 `_ensure_demo_indexes` 已移除）。风险 5.5 关闭。 |
| 3 API 状态口径接入 `statuses.py` | **完成** | `/inventory`、`/inventory/{sku}` 与 `/dashboard/summary` 均复用工具层库存规则，统一返回英文状态码；Dashboard 预警统计与列表不再读取落库 `status` 判断，状态漂移回归测试已覆盖 |
| 4 补齐失效查询参数 | **完成** | 实现 `/orders?carrier=`、`/shipments?country=` 及订单/物流 `warehouse_id`；后者明确为“订单商品当前关联的库存仓库”，使用 `EXISTS` 去重。保留 `/inventory?status=`、`/inventory?warehouse_id=`，移除库存无业务关系的 `country`/`carrier`；OpenAPI 与同源测试已覆盖。 |
| 5 抽取主数据表 | **完成** | 新增 `products` / `warehouses`；旧库初始化从 `inventory` 无损回填并补齐双外键；库存查询 JOIN 主数据取名称；名称更新触发器同步兼容快照；Demo/真实导入先写主数据再写库存。暂不把库存仓库推断为包裹实际发货仓库。 |
| 6 `knowledge_articles` 接管检索 | **完成** | `retrieve_knowledge()` 从数据库读取正文和来源，保留旧调用方式与结构化 sources；数据库内容变化、空表未命中均有回归测试 |
| 7 演示/真实数据边界固化 | **部分完成** | 已有 `is_demo` 字段、Demo/Real 导入校验和敏感字段拒绝；API 与工作台尚未提供完整 `is_demo` 筛选，混合数据联调与 `data/real/.gitkeep` 仍待完成。 |
| 8 工作台页面统一走查询层 | **完成** | `workbench/queries.py` 已移除数据库连接与 SQL，仅调用 `tools/database.py` 并补中文标签；订单、库存、物流列表/详情/汇总均同源；`/dashboard/summary` 与 Streamlit 首页共同调用 `query_dashboard_summary()`，同一指标不再维护两个 SQL 版本。 |
| 9 回归与文档收口 | **完成** | README 结构、启动命令与初始化说明已对齐；PRD、前端说明、设计参照和本文件已统一当前包路径、端口、检索方案与实施状态；当前测试基线已记录。风险 5.9 关闭。 |

本轮数据层额外落地（不在原 9 步表内）：

- **连接生命周期统一**：`db/init_db.py` 新增 `connect()` 上下文管理器，`commit`/`rollback` 之外**无条件 `close()`**，并默认开启 `PRAGMA foreign_keys`。原 `with sqlite3.connect(...) as conn` 用法只提交事务、不关闭连接，已在 `tools/database.py`、`api/service.py`、`workbench/queries.py`、`scripts/import_data.py` 四处替换。
- **引用完整性校验**：`validate_referential_integrity()` 输出外键强制状态、声明式外键违规行数与 4 项孤儿检查；`order_items.sku`→`inventory.sku` 已由逻辑检查升级为声明式外键并保留显式报告。
- **统一初始化入口**：`scripts/init_database.py` 提供幂等默认模式与 `--reset-demo` 显式重建，结束打印表行数与完整性报告。

v2.1 当时的实测验收证据（历史快照）：

- `uv run python scripts/init_database.py` 连跑 2 次，行数稳定不变（orders 20 / order_items 35 / inventory 10 / shipments 15 / tracking_events 30）；
- 外键强制开启 = 是，声明式外键违规 0 行，4 项孤儿检查全部 0 条；
- `pytest tests/ -q` → **40 passed**（测试基线由 39 升至 40）。其中 `tests/test_api.py::test_missing_order_id_is_not_filled_with_default_1001` 依赖 LLM 可达性，无网络时会回落到知识库分支而失败，属既有外部用例，不在数据层范围内。

### 8.2 工具层统一改造（2026-09-22，v2.2）

用户要求「统一订单、库存和物流查询逻辑」，并明确 Agent 查询与 API 查询复用同一套业务查询函数、LLM 不得猜测数据、结构化返回、兼容旧调用、错误区分参数/不存在/数据库三类、每个工具补单元测试。

| 文件 | 改动 |
| --- | --- |
| `db/init_db.py` | 新增 `get_shipments_by_order_id()`（全量包裹，按 `shipment_id ASC`）；`get_tracking_events()` 排序加 `id` tiebreaker；`get_shipment_by_order_id()` 保留仅作兼容 |
| `tools/database.py` | 升格为唯一业务查询层。错误码新增 `NO_LOGISTICS`；新增 `query_order_items` / `query_order_shipments` / `query_order_status` / `query_inventory_by_sku` / `query_shipment_events` / `list_inventory_records`；`query_inventory` 支持 `warehouse_id` 与 `keyword`；库存状态改为规则权威 + `stored_status` / `status_mismatch` 暴露漂移；物流按 `order_id` 返回全包；`_execute()` 统一兜底异常 |
| `tools/order.py` | 改用 `query_order_status`（最短路径）；签名与 `str` 返回不变 |
| `tools/inventory.py` | 改用 `query_inventory_by_sku`；文案新增状态漂移提示；签名与 `str` 返回不变 |
| `tools/logistics.py` | 多包裹时列出全部包裹与各自状态；单包裹文案不变；签名与 `str` 返回不变 |
| `api/service.py` | `/orders/{id}`、`/inventory`、`/inventory/{sku}`、`/shipments/{id}`、`/shipments/{id}/events` 改调业务查询层；新增 `_raise_for_result()` 做错误码 → HTTP 状态码映射 |
| `tests/conftest.py` | 新增 `seeded_db` / `demo_db` 两个 tmp_path 夹具，**不含 autouse**，既有用例行为不变 |
| `tests/test_query_layer.py` | 新增 50 条：三组查询的全部能力点、5 个错误码、一单多包裹、6 个无物流订单、库存规则三个边界与漂移暴露 |
| `tests/test_api_query_consistency.py` | 新增 11 条：断言 API 端点与业务查询层返回同源（状态码、包裹清单、明细、轨迹顺序） |
| `tests/test_query_layer_acceptance.py` | 新增 24 条：把用户指定的 8 条「必须满足」固化为回归测试（来自 SQLite、不虚构状态、不存在 SKU 不误判零库存、缺货/库存不足、轨迹升序、无物流提示、Agent 与工具一致） |

v2.2 当时的实测验收证据（历史快照）：

- `pytest tests/ -q` → 共 **125 条**，最近一次 **124 passed**；唯一的 F 是已知 LLM 依赖间歇用例 `test_api.py::test_missing_order_id_is_not_filled_with_default_1001`（`call_llm` 无网络返回 `None` → 回落知识库分支；LLM 可达时通过）
- 逐项验证脚本（对默认库实测）：**PASS 96 / FAIL 0**，覆盖 8 条验收条件的展开项
- 库存规则逐 SKU 实测：10 个 SKU 的规则计算值、落库值、期望值**三者完全一致**（SKU-002 零库存→缺货；SKU-003/004/006/009 库存不足；其余 5 个正常）
- Agent 三条链路实测：订单 1020 →「已发货 / 中国香港 / 3 商品 1 包裹」；SKU-002 →「缺货」；订单 1005 →「共 2 个包裹：SHP-1005-A 运输中、SHP-1005-B 派送中」（改造前只返回 B 包）；订单 1003 →「订单存在但暂无物流记录」；订单 999999 →「订单不存在」
- `uv run python scripts/init_database.py --reset-demo` 后行数回到基线 20/35/10/15/30，SKU-004 回到 `available=6 / safety_stock=12`

行为变更（需注意）：

1. 库存 `status` 改为规则计算值，落库列不再作权威值（当前 10 个 SKU 两者一致，本次无实际差异）
2. `GET /inventory` 与 `GET /inventory/{sku}` 返回英文码，不再返回中文
3. `GET /inventory?status=xxx` 由「忽略」变为真实过滤
4. 物流按订单查询返回全部包裹；单包裹时代的 `data.shipment` / `events` / `current_status` 兼容字段保留，指向首个包裹（原为最新包裹）
5. `query_logistics(order_id=不存在)` 的文案改为物流域专属「订单 X 不存在，无法查询到该订单的物流记录。」

---

## 9. 结论

目标 5 张表（`orders` / `order_items` / `inventory` / `shipments` / `tracking_events`）**已全部落地并通过真实查询验证**，字段层面无缺口；工具链也已通过 `tools/database.py` 接入 SQLite，`tools/*.py` 退化为格式化薄封装。

因此本方案的性质已从 v1.0 的「从内存字典迁移到数据库」变为**收敛与治理**。截至 v2.9：

1. **已关闭**——演示数据单一写入源与 lifespan 初始化（5.1）、库存状态口径（5.2）、SKU 外键（5.3）、多包裹语义（5.4）、重复索引（5.5）、商品/仓库主数据、第 6 步数据库知识库检索和文档同步（5.9）；
2. **已关闭**——失效查询参数（5.6）已完成；订单/物流 `warehouse_id` 明确表示商品库存仓库，实际发货仓库仍未在当前模型中虚构；
3. **仍待处理**——遗留 `src/data/ecommerce_assistant.db`（5.7）需人工确认后清理，不在本轮文档任务中删除；
4. **后续计划**——Demo/Real 筛选隔离；实际发货仓库需等待 `shipments` 的履约仓库数据来源明确后单独建模。

当前全量回归基线为 `199 passed`。Starlette 已升级至 `1.7.0`，原 AnyIO `BlockingPortal` 弃用 warning 已消除。

---

## 10. 变更记录

| 版本 | 日期 | 变更 |
| --- | --- | --- |
| v1.0 | 2026-09-21 | 首版。基于「项目无数据库层、数据在内存字典」的前提撰写，该前提与实现不符 |
| v2.0 | 2026-09-22 | 依据实测库结构、真实调用链、真实索引与数据量重写。补充 P0/P1/P2 风险清单、索引去重与补齐方案、演示/真实数据边界规则、9 步顺序与依赖图 |
| v2.1 | 2026-09-22 | 数据层落地。新增 8.1 实现状态（第 1、2 步完成或部分完成，第 3–8 步待做）；记录连接生命周期统一、引用完整性校验、统一初始化入口三项额外落地；5.5 索引重复风险关闭；测试基线 39 → 40 |
| v2.2 | 2026-09-22 | 工具层统一改造。第 3.2 节改写为统一业务查询层契约（5 个错误码、8 个查询函数、库存状态规则、物流全包语义）；5.2 / 5.6 部分关闭，5.4 关闭；新增 8.2 改造记录与行为变更清单；新增 8 条验收条件的回归测试模块；测试基线 40 → 125 |
| v2.3 | 2026-09-22 | 工作台模型选择。新增 3.7 节记录模型透传链路与「模型只作用于 rag/llm 分支」的作用范围契约；API 层新增 `GET /models`（只读端点 9 → 10）；`ChatMessage` 新增 `intent`；`llm/client.py` 默认回退值 `gpt-5.2` → `gpt-5.6-sol`；新增 `tests/test_model_selection.py` 23 用例；测试基线 125 → 148 |
| v2.4 | 2026-09-23 | 库存状态口径收口。公开 `inventory_status_from_rule()` 作为统一业务规则；Dashboard 预警数量和列表改为按 `available` / `safety_stock` 计算；新增状态漂移回归测试；测试基线 148 → 149 |
| v2.5 | 2026-09-23 | 前端契约对齐。`/invoke` 补齐 `route` / `sources` / `tool_calls`（PRD v0.2 §6.7.1），新增 `schema/routes.py` 作为 route 枚举与工具名映射的唯一来源；`/stream` 补齐 `start` / `route` / `tool_call` / `sources` / `error` 事件（§6.7.2）；`answer_question()` 提供结构化返回、`handle_question()` 保留为字符串薄包装；来源只走 `sources`（正文不再拼接「来源：」）；注册 `CORSMiddleware` 放行 `file://` 来源；新增独立 Web 前端 `frontend/index.html`（源自 `design/index.html`）；`design/` 与 `docs/PRD.md` 随实现同仓；新增 `tests/test_frontend_contract.py` 26 用例；测试基线 149 → 175 |
| v2.6 | 2026-09-24 | SKU 引用约束收口。默认库孤儿检查为 0；新增旧库事务式外键迁移和孤儿中止保护；Demo/真实数据导入调整为 inventory 先于 order_items；真实数据导入增加本批及库内 SKU 引用校验；新增 5 条迁移与导入回归测试；测试基线 175 → 180 |
| v2.7 | 2026-09-24 | 知识库检索接管。`rag/retriever.py` 移除硬编码 `DOCS`，按分类从 `knowledge_articles` 读取正文与来源；新增数据库内容变更和空表未命中测试；测试基线 180 → 182 |
| v2.8 | 2026-09-24 | 文档全面收口。确认 FastAPI lifespan 初始化已完成并关闭 5.1；统一 README、PRD、前端说明与设计参照的包路径、8084 端口、SQLite 检索方案和当前实施状态；将历史测试数字标为版本快照，记录当前基线 `182 passed, 1 warning`；明确第 4、5、7、8 步及遗留双库文件仍待处理。 |
| v2.9 | 2026-09-24 | 商品/仓库主数据落地。新增 `products`、`warehouses` 表及索引；旧库从库存安全回填并为 `inventory.sku/warehouse_id` 建外键；查询名称以 JOIN 主数据为准，兼容字段由触发器同步；Demo/真实导入同步主数据；新增 3 条迁移/约束/名称权威测试；测试基线 182 → 185。 |
| v2.10 | 2026-09-24 | HTTP 列表筛选参数收口。新增统一订单/物流列表查询函数；实现订单承运商和物流目的国家筛选；移除无业务关系或缺少履约数据的筛选参数；保留库存仓库筛选；新增 5 条业务层、API 同源及 OpenAPI 契约测试；测试基线 185 → 190。 |
| v2.11 | 2026-09-24 | 启用订单/物流 `warehouse_id`（商品库存仓库语义，`EXISTS` 去重）；工作台移除全部直接 SQL并完全复用统一业务查询层；Dashboard API 与 Streamlit 首页改用同一汇总函数；新增同源、汇总与源码边界测试；测试基线 190 → 199。 |
| v2.12 | 2026-09-24 | 将 Starlette 1.6.0 升级为 1.7.0，消除其对 AnyIO 已弃用 `BlockingPortal` 别名的引用；全量测试保持 `199 passed`，不再产生该 warning。 |

### 附录：v2.0 写作时的外部并发变更

撰写期间 `api/service.py`、`schema/schema.py`、`tests/test_api.py` 被并发修改（新增 `GET /dashboard/summary` 端点及 `DashboardSummaryResponse` 等 4 个响应模型）。v2.0 已按改动后的代码校订，关键影响：

- 新增第 3.6 节「API 层取数面」，列为第 9 条只读端点
- 5.2 的 P1 判定**加强**：同文件内 `/dashboard/summary` 用落库英文码、`/inventory` 用重算中文码，`status` 字段一名两义
- 5.6 的 `GET /inventory` 的 `status` 参数失效问题升级说明
- 第 8 步新增「指标口径对齐」验收项
- 测试基线由 38 用例变为 39 用例
