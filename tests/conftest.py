"""共享测试夹具。

只提供按需取用的临时库，**不使用 autouse**，因此既有依赖项目根真实库的用例
（tests/test_api.py、test_workbench_data.py 等）行为不受影响。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ecommerce_assistant.db.init_db import init_db, seed_demo_data
from scripts.init_demo_data import initialize_demo_database


@pytest.fixture
def seeded_db(tmp_path: Path) -> Path:
    """内联种子临时库：订单 1001-1003、库存 SKU-001~004、包裹 SHP-1001-A / SHP-1002-A。

    订单 1003 没有包裹，可用于「订单存在但无物流记录」用例；不含一单多包裹。
    """
    db_file = tmp_path / "seeded.db"
    init_db(db_file)
    seed_demo_data(db_file)
    return db_file


@pytest.fixture
def demo_db(tmp_path: Path) -> Path:
    """由 data/demo/*.csv 导入的完整演示库（20/35/10/15/30）。

    含一单多包裹（订单 1005）与 6 个无物流订单（1003/1004/1011/1016/1018/1019）。
    """
    db_file = tmp_path / "demo.db"
    initialize_demo_database(db_path=db_file, reset=True)
    return db_file
