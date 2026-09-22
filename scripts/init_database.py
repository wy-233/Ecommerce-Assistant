from __future__ import annotations

from ecommerce_assistant.db.init_db import init_db, seed_demo_data


if __name__ == "__main__":
    db_path = init_db(seed_demo=True)
    print(f"数据库已初始化: {db_path}")
    print("演示数据已写入，且不覆盖已有记录。")
