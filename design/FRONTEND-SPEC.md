# Ecommerce Assistant 前端实现规格

| 项目 | 内容 |
| --- | --- |
| 文档类型 | 前端实现规格（框架无关） |
| 版本 | v1.0 |
| 上游 | `docs/PRD.md` v0.3、`design/DESIGN.md` |
| 参照实现 | `design/index.html`（可直接运行，含全部状态） |
| Token | `design/tokens.json` |
| 读者 | 前端开发、测试 |

本文档是开发的唯一依据。参照实现用于核对视觉，视觉尺寸以本文档与 `tokens.json` 为准；原型中个别正负 2px 的差异属实现残差，无需还原。

---

## 1. 技术栈状态

当前参照实现与交付版本使用原生 HTML、CSS 和 JavaScript，位于 `design/index.html` 与 `frontend/index.html`。本文档继续保持框架无关，只约定结构、契约与行为；后续迁移到 Vue 或 React 时仍应保持本规格的数据契约。

已明确的约束：

- 前端独立于 Streamlit，不通过 `components.html` 嵌入（PRD v0.2 §4.1）。
- 首期只连 `/ecommerce-assistant/invoke`（非流式）。`/stream` 的接线点见 §7.4。
- 不做用户登录与鉴权，会话标识由前端生成或固定为演示值。

---

## 2. Token 映射

`tokens.json` 落地为 CSS 变量，统一 `--ea-` 前缀（避免与宿主样式冲突）：

```css
:root {
  /* surface */
  --ea-paper: #E7E8E2;
  --ea-card: #FBFBF8;
  --ea-raised: #FFFFFF;

  /* text */
  --ea-ink: #171A1F;
  --ea-ink-2: #3C4046;
  --ea-mute: #63675E;
  --ea-on-ink: #FBFBF8;

  /* line */
  --ea-rule: #C7C9C0;
  --ea-line-strong: #171A1F;

  /* route —— 四条道的编码色 */
  --ea-route-after: #C4400C;
  --ea-route-order: #2F4BC4;
  --ea-route-stock: #3F6B3A;
  --ea-route-ship:  #8F6410;

  /* feedback */
  --ea-fallback-bg: #FBEFE8;
  --ea-fallback-border: #E8C4AE;

  /* type */
  --ea-font-sans: "Archivo", "Noto Sans SC", system-ui, -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif;
  --ea-font-mono: "DM Mono", ui-monospace, Consolas, "Courier New", monospace;

  /* radius —— 除按钮外一律直角 */
  --ea-r-btn: 3px;

  --ea-z-console: 20;
}
```

**硬约束**：不使用任何 box-shadow、渐变、模糊。层级只靠背景色与描边表达。字号阶、间距、断点取值一律查 `tokens.json`。

---

## 3. 布局系统

### 3.1 页面骨架

```
┌────────────────────────────────────────────────────────────────┐
│ ManifestBar              ← 1px 墨色下边线，sticky 可选            │
├────────────────────────────────────────────────────────────────┤
│ Lede                     ← h1 + 说明，左对齐，限宽 22ch / 58ch    │
├────────────────────────────────────────────────────────────────┤
│ SorterBelt               ← 12px 墨色传送带 + 4 个 Chute          │
├────────────────────────────────────────────────────────────────┤
│ ┌──────────────────────────────┐ ┌─────────────────────┐       │
│ │ ThreadList                   │ │ TraceRail           │       │
│ │  Exchange × N                │ │  SessionFacts       │       │
│ │                              │ │  ToolCallTally      │       │
│ │                              │ │  KnowledgeBaseList  │       │
│ │  ← minmax(0,1fr)             │ │  ← 292px, sticky     │       │
│ └──────────────────────────────┘ └─────────────────────┘       │
│                          gap 24px                              │
│                          padding-bottom 156px（预留输入区）      │
├────────────────────────────────────────────────────────────────┤
│ PromptConsole            ← position: fixed; bottom: 0           │
│   QuickChips / PromptField + SendButton                        │
└────────────────────────────────────────────────────────────────┘
```

- 内容容器：`max-width: 1220px; margin-inline: auto; padding-inline: 24px`（移动端 16px）。
- `ThreadList` / `TraceRail`：`display: grid; grid-template-columns: minmax(0, 1fr) 292px; gap: 24px; align-items: start`。
- `TraceRail`：`position: sticky; top: 20px`（1080px 以下取消 sticky）。
- `PromptConsole` 为 `position: fixed`，因此主体区必须留出 `padding-bottom`，否则最后一条回执会被遮住。预留值见 §3.3。

### 3.2 分拣带

- 4 列等宽网格，`gap: 12px`，`padding-top: 12px`。
- 传送带为 `::before` 伪元素：绝对定位，`top: 0`，高 12px，背景墨色，左右各外扩 24px 做出贯穿感。
- Chute 紧贴传送带下沿：`border-top: 7px solid <route color>`，其余三边 1px `--ea-rule`。
- Chute 内容自上而下：道名（`chuteName`）→ 工具名（`mono`，mute）→ 计数（`metric` + `micro` 文案「次路由」），计数用 `margin-top: auto` 压到底部。

### 3.3 断点行为

| 断点 | 触发值 | 变化 |
| --- | --- | --- |
| railCollapse | ≤ 1080px | 轨迹栏移到正文下方，两列横排（`grid-template-columns: repeat(2, minmax(0,1fr))`），取消 sticky |
| beltWrap | ≤ 760px | 分拣带变 2×2；容器 padding-inline 16px；回执取消限宽；Chute 最小高 108px；预留 192px |
| chipsScroll | ≤ 600px | 快捷问题改为单行横向滚动（`flex-wrap: nowrap; overflow-x: auto`，隐藏滚动条）；轨迹栏回到单列 |

---

## 4. 组件清单

### 4.1 组件树

```
AppShell
├── ManifestBar
├── Lede
├── SorterBelt
│   ├── Chute × 4
│   └── Parcel
├── Deck
│   ├── ThreadList
│   │   └── Exchange × N
│   │       ├── Ask
│   │       └── Receipt
│   │           ├── ReceiptHead
│   │           ├── ReceiptBody
│   │           ├── ToolCallList
│   │           └── SourceList
│   └── TraceRail
│       ├── SessionFacts
│       ├── ToolCallTally
│       └── KnowledgeBaseList
└── PromptConsole
    ├── QuickChips
    └── PromptField + SendButton
```

### 4.2 接口定义

类型仅为契约描述，框架无关。

| 组件 | 输入 | 输出 / 行为 |
| --- | --- | --- |
| `AppShell` | `session: SessionMeta` | 提供 route 色解析上下文 |
| `ManifestBar` | `brand`, `threadId`, `userId`, `agentName`, `status: 'online' \| 'offline'` | — |
| `Lede` | `title`, `body` | — |
| `SorterBelt` | `routes: RouteDef[]`, `counts: Record<RouteKey, number>`, `parcel: { active, targetKey }` | — |
| `Chute` | `routeKey`, `name`, `toolName`, `count`, `active: boolean` | — |
| `Parcel` | `active: boolean`, `targetKey: RouteKey \| null` | — |
| `ThreadList` | `exchanges: ExchangeModel[]`, `empty: boolean` | — |
| `Exchange` | `index`, `question`, `answer: ChatMessage` | — |
| `Ask` | `text` | — |
| `Receipt` | `message: ChatMessage`, `state: 'pending' \| 'ready' \| 'error'` | — |
| `ReceiptHead` | `routeLabel`, `runId` | — |
| `ToolCallList` | `calls: ToolCall[]` | 空数组时整块不渲染 |
| `SourceList` | `sources: Source[]` | 空数组时整块不渲染；默认展开 |
| `TraceRail` | `session: SessionMeta`, `stats`, `tools`, `knowledgeBase: string[]` | — |
| `PromptConsole` | `quickQuestions: string[]`, `disabled: boolean` | `@submit(text)` |

### 4.3 组件视觉规则

| 组件 | 关键规则 |
| --- | --- |
| `ManifestBar` | 背景 `--ea-card`，底边 1px 墨色。品牌 17px/700，副标 12px mute，字段用 mono 11.5px，状态灯为 8px 方块（**不是圆点**），在线色 `--ea-route-stock` |
| `Lede` | h1 用 `display` 字号阶，陈述产品动作，**不得重复 ManifestBar 里的品牌名** |
| `Chute` | 顶部 7px 道色；激活态：背景 `--ea-raised`、四边描边换道色、`translateY(-2px)` |
| `Parcel` | 36px 墨色方块，内部居中 10px 道色方块。从传送带上方落向目标 Chute |
| `Ask` | 15.5px/500，左侧 3px 道色竖线，`padding-left: 12px` |
| `Receipt` | 背景 `--ea-card`，1px `--ea-rule`，`padding: 16px`，`max-width: 72ch` |
| `ReceiptHead` | mono 11.5px，route 标签用道色；底边 1px dashed `--ea-rule`，下边距 12px |
| `ToolCallList` | 背景 `--ea-paper`，左侧 2px 道色，mono 12px；标签「调用的工具」为 11px mute |
| `SourceList` | 底边 1px dashed 分隔；用原生 `<details open>`；每条片段背景 `--ea-paper` + 左侧 2px 道色；`cite` 为 mono 11px mute |
| `SessionFacts` | `dl` 键值对，`padding: 8px 0` + 1px 下边框；键 12.5px mute，值 mono 11.5px 右对齐 |
| `KnowledgeBaseList` | 每项前一个 4px 方块（售后道色） |
| `QuickChips` | 12.5px，背景 `--ea-card`，1px `--ea-rule`，圆角 3px，hover 描边转墨色 |
| `PromptField` | 1px 墨色描边，圆角 3px，背景 `--ea-card`，placeholder 用 mute |
| `SendButton` | 墨色底 + `--ea-on-ink` 文字，圆角 3px，hover 转 `#31353C`，disabled 时 `opacity: .45` + `cursor: not-allowed` |

---

## 5. 状态矩阵

每个组件必须实现下列全部状态，缺一不可。

### 5.1 页面级

| 状态 | 触发 | 表现 |
| --- | --- | --- |
| 初始空态 | 新会话，`exchanges` 为空 | 分拣带计数全 0；对话区显示引导文案（见 §5.4）；轨迹栏工具区显示「本次会话还没有调用工具」 |
| 就绪 | 有历史对话 | 正常渲染 |
| 请求中 | 已提交，未返回 | `SendButton` disabled；输入框清空；Parcel 播放投递；目标 Chute 亮起并保持 1400ms |
| 后端不可达 | `fetch` 抛错或非 2xx | 追加一条兜底形态回执，路由标签为「连接失败 · <原因>」，正文说明如何排查 |
| 流式中 | 走 `/stream` 时 | 见 §7.4 |

### 5.2 回执（Receipt）状态

| 状态 | 数据条件 | 表现 |
| --- | --- | --- |
| 命中工具 | `route !== 'unknown'` 且有 `tool_calls` | 渲染 ToolCallList |
| 命中知识库 | `sources.length > 0` | 渲染 SourceList，标签形如「来源 2 条 · return_policy.md」 |
| 兜底 | `route === 'unknown'` | 左侧竖线与 route 标签用 `--ea-route-after`；背景 `--ea-fallback-bg`，描边 `--ea-fallback-border`；正文须说明「不在售后、订单、库存、物流范围内」并给出四种可用问法 |
| 工具返回空 | `tool_calls` 有结果但未命中记录（如 SKU 不存在） | 正文给出明确错误，列出已尝试的参数，不猜测 |
| 超长内容 | `content` 超过 1200 字符 | 折叠正文，显示「展开全部」；折叠阈值与控件文案需在实现时固定，不得静默截断 |

**兜底文案不得道歉**，直接说明范围与下一步：

```
这个问题不在售后、订单、库存、物流的处理范围内，没有调用任何工具。
可以换个问法，例如：退货要满足什么条件、订单 1001 的状态、SKU-001 还有多少库存、订单 1001 用了哪家物流。
```

### 5.3 组件状态

| 组件 | 状态 | 表现 |
| --- | --- | --- |
| `Chute` | 静置 / 激活 | 激活：白底 + 道色描边 + 上移 2px |
| `Chute` | 计数递增 | 数字直接替换，不加动画 |
| `Parcel` | 隐藏 / 移动 / 落袋 | 见 §7.2 |
| `SourceList` | 展开 / 折叠 | 三角箭头旋转 90° |
| `SendButton` | 可用 / 禁用 / hover / focus | 见 §4.3 |
| `QuickChips` | 静置 / hover / focus / 滚动溢出（≤600px） | 见 §3.3 |
| `PromptField` | 静置 / placeholder / 聚焦 | 聚焦时 2px 墨色 ring |

### 5.4 空态文案

```
问售后政策、订单、库存或物流。
助手会先识别意图，再把问题分拣到对应的处理链；命中知识库的回答会带上来源。
```

参照实现中通过 URL hash `#empty` 可查看此状态。

---

## 6. 数据契约

### 6.1 类型定义

与 PRD v0.2 §6.7 一致。

```ts
type RouteKey = 'after' | 'order' | 'stock' | 'ship' | 'unknown';

interface Source {
  doc: string;              // "data/return_policy.md"
  snippet: string;          // 命中的原文片段
  placeholder?: boolean;    // true 表示占位政策文本，前端须在 cite 行标注
}

interface ToolCall {
  name: string;                          // "order_lookup"
  args: Record<string, unknown>;         // { order_id: "1001" }
  result?: unknown;
}

interface ChatMessage {
  type: 'ai' | 'human' | 'tool';
  content: string;
  tool_calls: ToolCall[];
  run_id: string;
  route: RouteKey;      // v0.2 新增
  sources: Source[];    // v0.2 新增，无来源时为空数组，不得为 null
}
```

### 6.2 字段到界面的映射

| 字段 | 去向 |
| --- | --- |
| `route` | 分拣带计数 +1；`Chute` 高亮目标；`Ask` 与 `Receipt` 的道色；`ReceiptHead` 的标签文本 |
| `content` | `ReceiptBody` 正文，按段落拆分（`\n\n`） |
| `tool_calls[].name` + `.args` | `ToolCallList` 每行渲染为 `name(key="value", ...)`；字符串值带引号，数字与布尔值不带 |
| `tool_calls.length` | 轨迹栏 ToolCallTally 的计数累加 |
| `sources` | `SourceList`；`sources.length > 0` 时轨迹栏「知识库命中」+1 |
| `sources[].doc` | SourceList 摘要行「来源 N 条 · <basename>」 |
| `sources[].placeholder` | 为 true 时在 `cite` 行追加「· 占位文本，待替换」 |
| `run_id` | `ReceiptHead` 右侧 + 轨迹栏「最新 run_id」 |

### 6.3 派生统计口径

| 指标 | 计算方式 |
| --- | --- |
| Chute 计数 | `exchanges.filter(e => e.answer.route === routeKey).length` |
| 已路由 | `exchanges.filter(e => e.answer.route !== 'unknown').length` |
| 知识库命中 | `exchanges.filter(e => e.answer.sources.length > 0).length` |
| 工具调用次数 | 按 `tool_calls[].name` 归并计数 |

统计由前端从消息列表派生，**不额外请求接口**。

参照实现中使用了累加器（每次提问时对计数加一）。在「消息只追加、不删除」的前提下两者等价，但正式实现请采用派生方式，避免消息重渲染或删除历史时计数不同步。

### 6.4 路由色解析

```ts
const ROUTE_COLOR: Record<RouteKey, string> = {
  after:   'var(--ea-route-after)',
  order:   'var(--ea-route-order)',
  stock:   'var(--ea-route-stock)',
  ship:    'var(--ea-route-ship)',
  unknown: 'var(--ea-route-after)',
};
```

前端**不得**自行判断路由。`route` 一律以后端返回为准；原型中的前端关键词匹配仅为脱离后端时可预览的演示手段。

---

## 7. 交互时序

### 7.1 提交提问（非流式）

| 序 | 时机 | 行为 |
| --- | --- | --- |
| 1 | 用户提交 | 清空输入框；`SendButton` 置 disabled |
| 2 | 立即 | 目标 Chute 未知，Parcel 停在起点待命 |
| 3 | 响应到达 | 解出 `route` → Parcel 投递 → 目标 Chute 亮起 |
| 4 | 投递完成 | 追加 Exchange（Ask + Receipt）；更新轨迹栏；滚动到底部 |
| 5 | 结束 | `SendButton` 恢复可用；Chute 退出激活态 |

因为非流式下路由结果与正文同时到达，步骤 3 的 Parcel 无需等待路由判定，投递即为「结果揭示」的动作。

### 7.2 Parcel 时序

| 阶段 | 时长 | 变化 |
| --- | --- | --- |
| 起点 | 40ms | 位于传送带左端上方 42px，`translateX(30px)`，opacity 0 → 1 |
| 移动 | 520ms | `translateX` 到目标 Chute 水平中心；缓动 `cubic-bezier(0.4, 0, 0.2, 1)` |
| 落袋 | 280ms | `top: -2px`，opacity → 0 |
| 目标位置 | — | `targetX = chute.offsetLeft + chute.offsetWidth / 2 - 18`（18 = Parcel 尺寸的一半） |

`prefers-reduced-motion: reduce` 时跳过全部三阶段，直接进入结果态。

### 7.3 入场动画

页面加载时 4 个 Chute 依次淡入上移，每档延迟 60ms，单次 460ms。**全站仅此一次自动动画。**

### 7.4 流式接线点（`/stream`）

调用 `POST /ecommerce-assistant/stream`，按 SSE 事件类型驱动界面。事件格式见 PRD v0.2 §6.7。

| 事件 | 前端行为 |
| --- | --- |
| `start` | 取 `run_id`，追加一条 pending 状态的 Receipt |
| `route` | 启动 Parcel 投递 + Chute 高亮（这正是流式相对非流式的价值：路由先于正文到达） |
| `tool_call` | 向 ToolCallList 追加一行 |
| `token` | 追加到正文；保持滚动贴底 |
| `sources` | 渲染 SourceList |
| `error` | 按兜底形态渲染错误回执，保留已渲染的正文 |
| `[DONE]` | Receipt 转为 ready；恢复输入 |

流式下 `SendButton` 的禁用状态以 `[DONE]` 或 `error` 为准，不以 HTTP 响应结束为准。

---

## 8. 无障碍与响应式

### 8.1 无障碍

- **焦点**：全部可交互元素可 Tab 到达；`:focus-visible` 使用 2px 墨色描边 + 2px 偏移。
- **对比度**：正文 `--ea-ink-2` 在 paper 上约 8.5:1；次级文字 `--ea-mute` 4.7:1；四条道色用作文字时均 ≥ 4.9:1。**新增任何文字颜色必须实测对比度 ≥ 4.5:1。**
- **语义**：对话区 `aria-live="polite"`；分拣带与轨迹栏用具名 `section`/`aside`（`aria-label`）；Parcel 为纯装饰，加 `aria-hidden="true"`。
- **键盘**：SourceList 用原生 `<details>`，保证键盘展开/折叠。
- **触控**：移动端可点击元素最小 44×44px。

### 8.2 动效

- `prefers-reduced-motion: reduce` 下所有 animation 与 transition 时长降为 0.01ms，并跳过 Parcel 投递。
- 不使用滚动驱动的视差、自动轮播、无限循环动效。

### 8.3 内容规范

- 按钮说什么，提示就说什么（「发送」→ 成功后不另起措辞）。
- 一个元素只做一件事；不堆叠装饰。
- 错误与空态声明事实与下一步，不道歉、不模糊。
- 不使用 01/02/03 一类编号标记（四条道是并列通道，不是序列）。
- 不使用全大写英文标签、不在标题中单独高亮某个词、不在按钮与链接末尾追加箭头。

---

## 9. 实现注意事项

1. **CSS 特异性**：`.ask`、`.receipt` 这类类选择器容易在嵌套时互相抵消。样式按组件作用域收口（框架选定后用 scoped style / CSS Modules），避免全局类名冲突。
2. **字体**：三款字体均为 OFL 授权可商用，但需自托管。首屏只预加载拉丁与中文正文所需字重（400/500/700），mono 按需加载，避免 FOIT 期间布局跳动。字体未就绪时用 `font-display: swap`。
3. **输入区遮挡**：`PromptConsole` 为 fixed 定位，其高度随 QuickChips 是否换行变化。主体区 `padding-bottom` 必须用 `ResizeObserver` 或 CSS 变量动态同步，不写死。
4. **滚动**：新消息追加后滚动到底部，平滑滚动在 reduce-motion 下降级为瞬时。
5. **长列表**：单会话超过 100 条消息时考虑虚拟滚动；首期可不做，但消息组件需保持纯展示、无内部状态。
6. **不内联 hex**：所有颜色取自 `--ea-*` 变量。route 色需在组件上以 CSS 变量注入（如 `--rc`），不要为四条道各写一份样式。
