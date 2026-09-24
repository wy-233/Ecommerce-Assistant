from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_PATH = PROJECT_ROOT / "src/ecommerce_assistant/streamlit_app.py"
INVENTORY_PAGE_PATH = PROJECT_ROOT / "src/ecommerce_assistant/pages/2_库存看板.py"


def test_streamlit_dashboard_renders_core_sections_without_error():
    app = AppTest.from_file(APP_PATH, default_timeout=20).run()

    assert not app.exception
    assert [metric.label for metric in app.metric] == [
        "今日订单",
        "待处理订单",
        "待发货订单",
        "运输中包裹",
        "库存预警",
        "物流异常",
    ]
    assert len(app.dataframe) == 3
    assert len(app.get("page_link")) == 3
    assert len(app.chat_input) == 1
    assert len(app.selectbox) == 1


def test_streamlit_dashboard_uses_native_components_instead_of_css_theme_hacks():
    source = APP_PATH.read_text(encoding="utf-8")

    assert "unsafe_allow_html=True" not in source
    assert "<style>" not in source
    assert "st.chat_message" in source
    assert "st.metric(" in source


def test_inventory_dashboard_renders_inventory_comparison_without_error():
    app = AppTest.from_file(INVENTORY_PAGE_PATH, default_timeout=20).run()

    assert not app.exception
    assert [metric.label for metric in app.metric[-3:]] == [
        "当前筛选 SKU",
        "需补货 SKU",
        "最大库存缺口",
    ]
    assert len(app.get("vega_lite_chart")) == 1


def test_inventory_comparison_uses_non_stacked_threshold_visualization():
    source = INVENTORY_PAGE_PATH.read_text(encoding="utf-8")

    assert "st.bar_chart" not in source
    assert "mark_bar" in source
    assert "mark_tick" in source
    assert "安全库存线" in source
