# 真实业务 CSV 导入说明

本项目支持从授权且脱敏后的 CSV 文件导入业务数据，导入逻辑用于补充本地 SQLite 工作台的数据源，不用于生产环境真实客户数据落库。

## 适用范围

支持导入以下文件：

- orders.csv
- order_items.csv
- inventory.csv
- shipments.csv
- tracking_events.csv

## 目录约定

真实数据目录必须放在：

- data/real/

本目录默认被忽略，不会被 `git status` 显示。导出目录和客户数据目录也会被忽略：

- exports/
- customer_data/

## 允许的数据类型要求

1. 所有字段必须存在，不能缺失。
2. 订单号、SKU、包裹号和物流单号必须满足业务格式约束。
3. 数字字段必须为合法整型或浮点文本，例如：`1`, `528.00`, `0`。
4. 日期字段必须是 ISO 兼容格式，例如：`2024-01-15T10:00:00Z`。
5. 任何个人敏感信息都不能被导入，包括但不限于：姓名、手机号、邮箱、完整地址。
6. 如果字段名中出现 `customer_name`、`phone`、`email`、`address` 等敏感关键字，导入会直接拒绝。

## 业务关联校验

导入时会执行以下关联检查：

- `inventory.sku` 会同步写入 `products.sku`
- `inventory.warehouse_id` 会同步写入 `warehouses.warehouse_id`
- `order_items.order_id` 必须存在于 `orders.order_id`
- `order_items.sku` 必须存在于 `inventory.sku`
- `shipments.order_id` 必须存在于 `orders.order_id`
- `tracking_events.shipment_id` 必须存在于 `shipments.shipment_id`

导入顺序固定为 `orders → products/warehouses（由 inventory 派生）→ inventory → order_items → shipments → tracking_events`。关联既可以来自同批 CSV，也可以引用数据库中已经存在的订单、SKU 或包裹。

当前继续兼容原 `inventory.csv` 格式，不要求额外提供 `products.csv` 或 `warehouses.csv`。商品名和仓库名会写入主数据表；`inventory.product_name`、`inventory.warehouse_name` 暂时保留为兼容快照字段。

## 事务与幂等行为

- 所有导入在单个事务内执行。
- 任何一行错误都会触发回滚，确保数据库不会留下半成品。
- 重复导入时，按唯一键执行 `INSERT ... ON CONFLICT ... DO UPDATE`，不会产生重复订单/商品/发货记录。

## 运行方式

示例：

```bash
uv run python scripts/import_data.py \
  --orders data/real/orders.csv \
  --order-items data/real/order_items.csv \
  --inventory data/real/inventory.csv \
  --shipments data/real/shipments.csv \
  --tracking-events data/real/tracking_events.csv
```

仅检查不写库：

```bash
uv run python scripts/import_data.py --dry-run \
  --orders data/real/orders.csv \
  --order-items data/real/order_items.csv \
  --inventory data/real/inventory.csv \
  --shipments data/real/shipments.csv \
  --tracking-events data/real/tracking_events.csv
```

## 错误输出格式

错误会输出为：

```text
orders.csv:12: 缺少必填字段 'order_id'
```

其中包含：

- 文件名
- 行号
- 原因说明

## .gitignore 要求

必须保证以下内容存在：

```gitignore
.env
*.sqlite
*.db
data/real/
exports/
customer_data/
```
