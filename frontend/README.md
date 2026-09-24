# Web 前端 · 分拣台

`design/index.html` 的实现版本：跨境电商客服助手的独立 Web 前端。
界面把每条问题「分拣」到四条处理道之一，路由结论由后端给出，前端只负责呈现。

## 1. 运行

需要两个东西：后端服务 + 本页面。

```bash
# 终端 A：启动后端（默认 8084）
python src/run_service.py

# 终端 B：启动静态服务（可选，也可以直接双击 index.html）
python -m http.server 5500 --directory frontend
```

然后浏览器打开 `http://localhost:5500/index.html`，或直接双击 `frontend/index.html`。

后端地址写在 `frontend/index.html` 顶部：

```js
var API_BASE = "http://localhost:8084";
```

改端口时同步改这里。置空则退回页面内置的演示数据，可脱离后端单独预览视觉。

### 后端必须放行 `file://` 来源

直接双击打开页面时，请求的 `Origin` 是 `null`。后端已在 `api/service.py` 注册
`CORSMiddleware`（`allow_origins=["*"]`、`allow_credentials=False`）放行，
否则页面只会显示「连接失败」。新增接口时不要绕过这层中间件。

## 2. 与 Streamlit 的关系

两套前端并存，共用同一个 FastAPI 后端，互不影响：

| | Streamlit（`src/ecommerce_assistant/streamlit_app.py`） | 本页（`frontend/index.html`） |
| --- | --- | --- |
| 定位 | 内部工作台（订单 / 库存 / 物流看板 + 对话） | 对外演示页（路由分拣台） |
| 端口 | 8501 | 任意静态端口或 `file://` |
| 模型选择 | 支持（下拉框，走 `model` 字段） | 暂不提供，用后端 `OPENAI_MODEL` |
| 结构化字段 | 用 `intent` 标注气泡 | 用 `route` / `tool_calls` / `sources` 渲染 |

## 3. 数据契约

渲染逻辑完全由后端响应驱动，不自行判断路由（`design/FRONTEND-SPEC.md` §6.4）。
`POST /ecommerce-assistant/invoke` 返回：

| 字段 | 用途 |
| --- | --- |
| `route` | 分拣带计数 +1；道口高亮；`Ask` 与 `Receipt` 的道色；回执头标签 |
| `content` | 回执正文，按 `\n\n` 拆段 |
| `tool_calls[]` | 「调用的工具」块，渲染为 `name(key="value")` |
| `sources[]` | 来源块（原生 `<details open>`），`placeholder` 为真时在 cite 行标注 |
| `run_id` | 回执头右侧 + 轨迹栏「最新 run_id」 |

统计（各道计数、已路由、知识库命中、工具调用次数）一律由消息列表**派生**
（§6.3），不维护独立累加器。

## 4. 与设计文件的差异

自 `design/index.html` 复制而来，仅改动以下四处，视觉与结构未变：

1. `API_BASE` 指向 `http://localhost:8084`，接入真实后端。
2. 会话数据改为驱动式：预置的 3 组对话由 JS 数据渲染，统计改为派生（§6.3）。
3. 修复后端分支缺少的投递动效：原型的 `handleViaBackend` 只更新计数、
   不播放包裹投递与道口高亮（§7.1 要求响应到达后播放），现已补齐。
4. 连接失败的提示文案改为回显实际 `API_BASE`（原型写死 8080，本项目后端是 8084）。

另有一处后端侧的措辞差异：兜底文案的示例问法用「某个订单号现在到哪里了」
而非规格里的「订单 1001 的状态」。原因见 `rag/retriever.py` 中 `MISS_ANSWER`
处的注释——写具体单号会让
`tests/test_api.py::test_missing_order_id_is_not_filled_with_default_1001`
把兜底回复误判成订单查询结果。

## 5. 未做的部分

- 模型选择（设计稿中没有该控件，加入会破坏版式；需要时再出设计）。
- `/stream` 流式渲染：后端已按 PRD §6.7.2 输出 `start` / `route` / `tool_call` /
  `sources` / `token` / `[DONE]` 事件，前端接线点见 `design/FRONTEND-SPEC.md` §7.4。
- 超长正文折叠（§5.2 `> 1200` 字符折叠并显示「展开全部」）。
