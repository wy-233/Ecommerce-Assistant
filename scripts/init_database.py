"""初始化电商工作台 SQLite 数据库（可重复执行）。

用法：

    uv run python scripts/init_database.py                # 幂等建表 + 空库兜底播种，不覆盖已有数据
    uv run python scripts/init_database.py --reset-demo   # 显式重建：清空业务表和主数据表并重新导入 data/demo/*.csv

两种模式都会在结束时输出表行数与外键、引用完整性报告。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
for candidate in (ROOT_DIR, ROOT_DIR / "src"):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from ecommerce_assistant.db.init_db import (  # noqa: E402
    ALL_BUSINESS_TABLES,
    BUSINESS_TABLES,
    DEFAULT_DB_PATH,
    connect,
    init_db,
    seed_demo_data,
    validate_referential_integrity,
)


def _print_counts(db_path: Path) -> None:
    with connect(db_path) as conn:
        for table in ALL_BUSINESS_TABLES:
            count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            print(f"  {table:18s} {count:4d}")


def _print_integrity(db_path: Path) -> None:
    report = validate_referential_integrity(db_path)
    print(f"  外键强制开启       : {'是' if report['foreign_keys_enabled'] else '否'}")
    print(f"  声明式外键违规行数 : {report['declared_fk_violations']}")
    for label, count in report["checks"].items():
        print(f"  {'OK' if count == 0 else '存在孤儿':8s} {label}: {count}")
    print(f"  完整性结论         : {'通过' if report['ok'] else '不通过'}")


def main() -> None:
    parser = argparse.ArgumentParser(description="初始化电商工作台 SQLite 数据库（可重复执行）")
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH), help="目标 SQLite 数据库路径")
    parser.add_argument(
        "--reset-demo",
        action="store_true",
        help="显式重建演示数据：清空业务表和主数据表并重新导入 data/demo/*.csv",
    )
    args = parser.parse_args()

    target = Path(args.db_path)

    if args.reset_demo:
        from scripts.init_demo_data import initialize_demo_database

        demo_dir = ROOT_DIR / "data" / "demo"
        if not demo_dir.exists():
            raise FileNotFoundError(f"演示 CSV 目录不存在：{demo_dir}")
        summary = initialize_demo_database(db_path=target, reset=True)
        print(f"演示数据已重建（显式 reset）: {summary['db_path']}")
    else:
        db_path = init_db(target)
        # seed_demo_data 只在 5 张业务表全空时写入，已有数据不受影响。
        seed_demo_data(target)
        print(f"数据库已就绪（幂等，已有数据未被覆盖）: {db_path}")

    print()
    print("表行数:")
    _print_counts(target)
    print()
    print("外键与引用完整性:")
    _print_integrity(target)


if __name__ == "__main__":
    main()
