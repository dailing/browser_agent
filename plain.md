# Browser Agent — 需求与架构文档

> 目标：做一个「AI 控制浏览器」的 work。  
> 核心：Headless Browser 后端截帧 + 前端**只读**实时预览（`**<img>` 即可**）；**Session / Agent 侧输出**用 **Markdown** 渲染（与另一项目对齐：**markdown-it**）。**与浏览器的实际操作只由 LLM（经 backend/agent 编排）发起**；人不操作浏览器，只看会话内容与画面。

---

## 1. 产品目标


| 能力                               | 描述                                                                                                                                          | 优先级 |
| -------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- | --- |
| **Live preview**                 | LLM 控制浏览器时，viewport 截图（JPEG）推到前端，用 `**<img>`** 展示；可用 CSS `zoom` / `devicePixelRatio` 做清晰缩放                                                  | 必须  |
| **Session 与 Agent 输出（Markdown）** | 展示 **Session**（列表、当前会话、步骤时间线等）及 Agent 返回、工具结果等；用 **markdown-it**（及按需插件）渲染——Markdown 作为 Agent 场景下的首选承载格式，与另一项目栈对齐                            | 必须  |
| **观测边界**                         | 前端 **不向** backend 发送浏览器控制类消息；所有 `page.mouse` / `keyboard` / 导航等仅来自 LLM→backend                                                              | 必须  |
| **LLM 页面上下文**                    | 每轮给模型的不是「仅可交互元素扁平列表」，而是 **整页文档式结构**（层次、顺序与视口阅读一致）；在结构中用 **统一标记**标出可交互节点及 **可用操作**（click、fill 等），便于理解位置与层级关系                                 | 必须  |
| **Session**                      | 每次 **talk**、每次 **task**、每次独立 **运行** 均对应一个可持久化的 **Session**（步骤、结果、截图索引、**PDF 等附件**、关联 Skill 等），支撑审计与后续从 LLM 走向规则化                            | 主要  |
| **Skill**                        | 将重复性、定期性、固定浏览器流程固化为可版本化的 **Skill**；运行时可选用某条 Skill，多次运行在同一 Skill 下积累不同 Session                                                               | 主要  |
| **整页 PDF 导出与下载**                 | 提供 **Agent 工具**：将当前页按「打印」语义生成 **整页 PDF**（含可打印区域与分页，由 Playwright `page.pdf()` 等公开 API 实现）；文件落存储后返回 **可下载链接** 或 **Session 附件引用**，用户在前端或链接触发下载 | 必须  |
| **多 Tab 并行**（可选）                 | 同时控制多个浏览器 Tab，分别有独立的截图流                                                                                                                     | 后期  |


---

## 2. 技术方案选择

### 方案：Live preview（截图流）+ Session Markdown UI

预览区**不**重建目标页 DOM（避免 SPA / CORS / 状态丢失）；画面即 **JPEG 位图**，会话与 Agent 侧用 **Markdown** 呈现。

```
LLM / Agent 编排（调用 backend API 或进程内模块）
    │
    │  仅此路径：click、type、navigate 等 Playwright 操作
    ▼
Headless Browser (backend)
    │
    ├─────── JPEG 帧 → WebSocket（或等价通道）→ 前端 <img>
    │
    └─────── Session / 步骤 / Agent 文本 → HTTP·SSE·WS 等 → 前端 markdown-it 渲染
              ▲
Frontend（只读）
    │   ├─ 区块一：Session 列表 + 详情 / 时间线（Markdown）
    │   └─ 区块二：Live preview（仅 <img>，无 Canvas 叠加光标/高亮）
```

**为什么选这个：**

- 预览实现极简；Headless 内页面仍是唯一渲染真相
- Agent 输出与可审计文本走 Markdown，生态成熟、与「另一项目」可复用同一套渲染栈

---

## 3. 架构

### 3.0 分层与解耦原则（浏览器侧）

- **单一依赖面：只认 Playwright**  
所有与 Chromium 的交互**仅通过** Python `**playwright` 库的公开 API**（如 `page.screenshot()`、`page.evaluate()`、`page.mouse`、`locator`、`keyboard` 等）。**不**在项目代码中直连 **CDP（Chrome DevTools Protocol）**、**不**自行维护 DevTools 会话、**不把浏览器 debug 协议当作一层可编程接口**——避免应用层跨过 Playwright 再下沉到原始协议，层级过多、耦合面散、排错边界模糊。
- **模块之间**  
**浏览器侧**（`BrowserManager`、`ActionExecutor`、`PreviewPublisher`、`PageContextBuilder`）只依赖 **Playwright 抽象**与约定数据结构，**不**泄漏底层协议细节。**运行与数据侧**（`RunCoordinator`、`SessionRecorder`、`SessionStore`、`SkillStore`）依赖浏览器模块的**接口**（如「对某 Page 执行动作」「订阅预览 JPEG 流」「生成当前页结构化观测」），**不**在存储层直接操作 Playwright 对象。与 **LLM/Agent**、**预览 WS**、**Session 查询 API** 通过 `RunCoordinator` / 发布与查询接口分界，降低横向粘连。
- **取舍**  
若公开 API 在性能或能力上弱于直连协议，**优先**用 Playwright 参数、截帧策略、质量与频率调优解决；**不**为局部优化单独引入 CDP 依赖，除非日后明确推翻本条并成文变更。

### 3.1 模块关系

```
                        ┌─────────────────────────────────┐
                        │   Frontend（Vue 3 + Bootstrap）    │
                        │  UI：原生 Bootstrap 5（class 自搭） │
                        │  Session：markdown-it              │
                        │  Preview：<img> live JPEG          │
                        └────────────┬──────────────────────┘
                                     │ WS：预览 JPEG 下行
                                     │ HTTP/SSE/WS：Session 与 Agent 文本
                                     ▼
                        ┌─────────────────────────────────┐
                        │     Python backend service       │
                        │  ┌────────────────────────────┐  │
                        │  │ LLM / Agent 编排            │  │
                        │  └─────────────┬──────────────┘  │
                        │                ▼                 │
                        │  ┌────────────────────────────┐  │
                        │  │ RunCoordinator             │  │
                        │  │ SessionRecorder + stores   │  │
                        │  └─────────────┬──────────────┘  │
                        │                ▼                 │
                        │  ┌────────────────────────────┐  │
                        │  │ browser_agent（包）         │  │
                        │  │  ├─ BrowserManager         │  │
                        │  │  ├─ ActionExecutor         │  │
                        │  │  ├─ PageContextBuilder    │  │
                        │  │  └─ PreviewPublisher       │  │
                        │  └────────────────────────────┘  │
                        │          │                        │
                        │  Playwright 驱动                 │
                        └──────────┼────────────────────────┘
                                   │
                                   ▼
                        ┌──────────────────────┐
                        │ Playwright 驱动        │
                        │ Chromium（headless）   │
                        │ （仅库 API，不直连    │
                        │  CDP / debug 协议）   │
                        └──────────────────────┘
```

### 3.2 Backend（Python）：模块与职责

实现上可为 `browser_agent` **包**（多文件），不必挤在单文件。逻辑上分三层：**运行编排**、**会话与 Skill 数据**、**浏览器与预览**。

**Session / Skill 约定（产品语义）**

- **Session**：粒度为「一次对话回合 / 一次任务 / 一次完整运行」（按你的产品定义映射为 `session_id`）；同一次运行内所有步骤、工具输出、可选 CoT 摘要、截图等资源引用，都挂在这条 Session 下，便于回放、对比分支、日后沉淀规则。
- **Skill**：描述可复用的固定流程（步骤模板、指令片段、参数、适用场景等），可多版本；一次运行可记录 `skill_id`（及版本），便于把大量重复性、定期性工作与「同 Skill 下多 Session」关联起来。

**模块表**


| 模块                     | 职责                                                                                                                                                                                                                                                                      | 依赖边界                                                                |
| ---------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------- |
| **RunCoordinator**     | **单次运行的总线**：创建并收口一条 Session；可选从 **SkillStore** 载入 Skill 上下文；向 **Agent/LLM** 暴露「当前 Page + **PageContextBuilder 观测** + 工具调用 → **ActionExecutor** + 写 Session」；协调 **ActionExecutor**、**PageContextBuilder**、**PreviewPublisher**、**SessionRecorder**，**不**内含 Playwright 细节 | 依赖各模块接口，不直接持有底层协议                                                   |
| **SessionRecorder**    | 与同一次运行绑定：按步骤追加记录（动作请求与结果、错误、可选推理摘要、截图/**PDF** 等附件在存储中的键、路径或下载令牌）；**只写领域模型**，不操作 Playwright                                                                                                                                                                              | 调用 **SessionStore** 持久化                                             |
| **SessionStore**       | Session 及子步骤、附件索引的持久化与查询（实现可为 DB、文件、对象存储路径等）                                                                                                                                                                                                                            | **不** import Playwright                                             |
| **SkillStore**         | Skill 定义的持久化、列表、版本与读取                                                                                                                                                                                                                                                   | **不** import Playwright                                             |
| **BrowserManager**     | Playwright 浏览器 / 上下文 / `Page` 的生命周期；可按「每 Session 独立上下文」或「池化复用」选型，对上层隐藏                                                                                                                                                                                                  | 仅 Playwright 公开 API                                                 |
| **ActionExecutor**     | 将 **Agent 工具**对应的结构化动作（导航、点击、输入、等待等）落实为 Playwright 调用；返回统一结果结构供 **SessionRecorder** 与 Agent 消费                                                                                                                                                                          | 只接收 `Page` 或受控句柄，与 WS 预览解耦                                          |
| **PageContextBuilder** | 从当前 `Page` 生成供 LLM 的 **整页结构化观测**：保留 **DOM/阅读顺序与层次**（与视口内上下、嵌套关系一致），**不**以「仅输出扁平可点击列表」为唯一观测；在可交互节点处嵌入约定 **标记** 与 **允许的操作集合**；过长可截断时优先保留标记节点与近 viewport 分支                                                                                                                | 仅 Playwright 公开 API（如 `page.evaluate`、无障碍 / accessibility 快照等，实现再定） |
| **PreviewPublisher**   | 只读 **Live preview**：向订阅方（如 WebSocket）推送 **viewport JPEG 帧**，供前端 `**<img>`** 更新；**不**为前端提供光标/元素框等叠加元数据（前端不做 Canvas 叠加）                                                                                                                                                   | 依赖 **BrowserManager** 提供的 `Page`；可与 Session 归档共用截帧来源或分路             |


**与后续 §8 的衔接**：方向二中的「规则 + Browser」依赖 **Session** 长期积累；方向一的 Skill 生成依赖 **Session** 内「指令—动作」对与 **SkillStore** 中的模板演进。本表把坑位预留好，具体表结构与时序实现迭代即可。

### 3.3 Frontend（Vue）

前端两大块：**Session（Markdown）** 与 **Live preview（`<img>`）**，**不使用** Canvas 做光标、元素高亮或任何「伪浏览器操作」反馈——操作全部由 LLM 经 backend 完成，人只读。

**UI 与样式**：采用**原生 Bootstrap 5**（CSS，按需其 JS 插件），**不**使用 bootstrap-vue、bootstrap-vue-next 等封装好的 Vue 组件库。在 Vue 里用模板 + **class 绑定**、自有 `.vue` 组件拼装布局与交互，直接挂 Bootstrap 的 utility / 组件 class，保留最大自由度与可控性。


| 组件 / 能力                       | 职责                                                                                                                                                  |
| ----------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Markdown 渲染**               | 使用 **markdown-it**（及项目内与另一仓库对齐的插件、主题、代码高亮等）；渲染 Agent 回复、工具输出摘要、Session 步骤说明、系统提示等一切适合 Markdown 的文本                                                  |
| **Session UI**                | Session 列表、当前 Session 详情、步骤时间线；数据来自 backend（REST / SSE / WS 等实现时再定），展示层统一走 Markdown 或「结构化字段 + 内嵌 Markdown 片段」；步骤中若含 **PDF** 等附件则提供 **下载** 入口（链接或按钮） |
| `**BrowserPreview.vue`（或等价）** | **仅** `<img>`：订阅预览 WS，收到 JPEG（如 base64 JSON 或二进制帧）后更新 `src` 或 blob URL；可选 CSS `zoom` / `devicePixelRatio` 做清晰缩放                                     |
| **预览 WS client**              | 连接如 `ws://localhost:8765/browser`（示例）；**仅下行**帧数据；**不**向 backend 发送浏览器控制类消息                                                                          |


### 3.4 Agent 工具集与 LLM 页面上下文（Observation）

整体形态接近 **OpenAI Computer use**、**[browser-use](https://github.com/browser-use/browser-use)** 等：**模型在「观测 → 选工具 → 看结果」循环中驱动浏览器**。与常见「只给模型一份可点击元素编号列表」的做法不同，本项目的 **观测（observation）** 设计如下。

#### 页面上下文：整页结构 + 特殊标记

- **每次**（或按策略每轮）向 LLM 提供 **整页文档式结构**，体现 **层次**（父子、嵌套）与 **顺序**（与视口阅读、布局位置一致），避免模型只看到零散按钮链接而丢失「在表单哪一块、在列表第几项下」等空间与语义关系。
- 在结构表示中，对 **可交互节点** 用项目约定的 **特殊标记** 包裹（实现可为自定义分隔标签、带属性的块、或统一前缀行等），并在标记内或并列字段中注明 **节点 id**（供工具引用）与 **允许的操作**（如 `click`、`fill`、`select`、`check` 等），而不是把交互信息完全拆成另一张与正文脱节的表。
- **截断**：页面极大时允许折叠深分支或视口外次要内容，但 **带标记的可交互节点** 与 **当前任务相关路径** 应优先保留；必要时配合 **截图**（多模态）与结构交叉验证（工具见下表「截图」行）。

`PageContextBuilder`（§3.2）专职生成该字符串/结构化块；**Agent 编排**将其注入 system/user 上下文，与 **markdown-it** 渲染给人类的 Session 展示可复用同源或派生视图（实现再定）。

#### 工具集（参考 browser-use，名称以实现为准）

下列与 [browser-use 文档](https://docs.browser-use.com/) 中「导航、点击、输入、等待、截图、标签页」等能力**同族**，并按产品增加 **整页 PDF 导出**；可按需裁剪。**工具参数应能引用 `PageContextBuilder` 输出的节点 id / 标记**，而非仅依赖裸 CSS（裸 selector 可作为后续 escape hatch）。


| 工具（示意名）                                       | 作用                                                                                                                                                     |
| --------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **navigate** / **go_to_url**                  | 打开指定 URL                                                                                                                                               |
| **go_back**                                   | 后退                                                                                                                                                     |
| **click**                                     | 在标记节点上点击（或等价坐标/定位，由 ActionExecutor 落实）                                                                                                                 |
| **fill** / **type**                           | 在可输入标记节点填入文本                                                                                                                                           |
| **press_key** / **send_keys**                 | 特殊键、快捷键                                                                                                                                                |
| **scroll**                                    | 视口或元素内滚动                                                                                                                                               |
| **select_option**                             | 下拉/选择框                                                                                                                                                 |
| **wait** / **wait_for**                       | 等待时间、网络空闲或某标记出现                                                                                                                                        |
| **screenshot**                                | 当前 viewport 截图（供多模态模型或 debug；与 **PreviewPublisher** 可共用截帧管道）                                                                                           |
| **print_to_pdf** / **export_page_pdf**        | 将**当前整页**按打印排版生成 **PDF**（Playwright `page.pdf()` 等，仍属库公开 API，不直连 CDP）；写入 **SessionStore** 或对象存储，返回 **下载 URL** 或 **attachment_id**，供前端展示「下载 PDF」或用户直链下载 |
| **get_marked_page** / **refresh_observation** | 重新拉取整页结构化观测（与首轮 `PageContextBuilder` 输出同形）                                                                                                             |
| **done** / **task_complete**                  | 声明任务完成并附摘要（可选结构化）                                                                                                                                      |


可扩展：**upload_file**、**switch_tab** / **new_tab**、**evaluate_script**（慎用，需白名单）等，与 browser-use 自定义工具思路一致；**不**在项目内为工具暴露 CDP 直连。

#### 与 `ActionExecutor` 的映射

每个工具对应 **ActionExecutor** 内一组 Playwright 公开 API 调用（含 `**page.pdf()`** 生成 PDF）；工具返回的文本/错误码/附件引用写回 **SessionRecorder**，并进入下一轮 LLM 上下文。

---

## 4. 技术栈


| 层                    | 选择                                                                  | 说明                                                          |
| -------------------- | ------------------------------------------------------------------- | ----------------------------------------------------------- |
| **Headless Browser** | **Playwright**（Chromium）                                            | 仅用 Python `playwright` 公开 API；**不**在项目内直连 CDP；比 Selenium 轻量 |
| **Backend**          | Python 3.11+，asyncio                                                | 独立 Python 服务或与现有 API 同进程部署（任选）                              |
| **WebSocket**        | `websockets` 库 或 FastAPI starlette WebSocket                        |                                                             |
| **Frontend**         | Vue 3 + **原生 Bootstrap 5** + **markdown-it** + `<img>` live preview | 样式用 Bootstrap class 自搭，**无**现成 Vue 组件库封装；**无** Canvas 叠加层   |
| **图片格式**             | **JPEG**（base64 编码在 JSON 内）                                         | 轻量；暂不用 MJPEG 流（复杂）                                          |
| **缩放/高清**            | CSS `zoom` + `devicePixelRatio`                                     | 前端自由控制，不动 headless 窗口尺寸                                     |


---

## 5. 分阶段计划


| 阶段          | 内容                                                                                                                                                           | 交付                                                  |
| ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------- |
| **Phase A** | Playwright 启动 headless Chromium、打开 URL、截一张 JPEG 保存本地                                                                                                         | 可验证 backend 截图链路通                                   |
| **Phase B** | Phase A + WS server；截图以 base64 JSON 帧发出；前端 `<img>` 接收显示                                                                                                      | 截图流贯通                                               |
| **Phase C** | Session UI：**markdown-it** 接入；拉取或推送 Session / Agent 文本并与 **SessionStore** 对齐展示                                                                               | 会话与 Agent 输出可读、可审计                                  |
| **Phase D** | LLM/Agent 经 **RunCoordinator** 挂接 **PageContextBuilder**（整页结构 + 标记观测）、工具集与 `ActionExecutor`、`PreviewPublisher`；**仍无**前端→browser 的控制回传                        | 自动化操作 + 结构化观测 + Live preview + Session Markdown 端到端 |
| **Phase E** | 与宿主应用集成：独立 WS path（如 `/browser`）、路由与鉴权按需接入；组件化封装预览区                                                                                                          | 可嵌入任意壳                                              |
| **Phase F** | **SessionStore** / **SkillStore** 落地；每次 talk/task/运行创建 Session，运行中 **SessionRecorder** 落盘；可选关联 Skill；**PDF** 作为附件存储 + **下载接口**（与 §3.4 **print_to_pdf** 工具衔接） | 重复性任务可复用 Skill，运行可审计，PDF 可下载                        |


---

## 6. 风险与注意事项


| 风险               | 说明                                                                                              |
| ---------------- | ----------------------------------------------------------------------------------------------- |
| **Headless 分辨率** | 初始 viewport 设置要合理（建议 1280×720 或更高），不然控件过小影响 agent 点击/可读性                                        |
| **预览与归档负载**      | 实时预览与 Session 截图归档都会占用 CPU/带宽；在 **PreviewPublisher** / 存储策略上调参，**仅用** Playwright 公开 API，不引入 CDP |
| **CORS**         | 页面内 CDN 资源在 headless 里能加载，前端 iframe 展示时注意                                                       |
| **SPA**          | 不影响——截图是 DOM + 渲染后的 raster，不依赖 JS 状态                                                            |
| **带宽**           | JPEG base64 在 WS 内传输，大截图帧会大；考虑压缩率 + 按需截帧（只在变化时）                                                 |


---

## 7. 参考

- [browser-use/web.py](https://github.com/browser-use/browser-use)（WebAgent preview 部分）
- [Playwright Python](https://playwright.dev/python/)
- [Screenshots（Playwright）](https://playwright.dev/python/docs/screenshots)（与 §3.0「仅公开 API」一致）
- [PDF（Playwright）](https://playwright.dev/python/docs/api/class-page#page-pdf)（`page.pdf()`，整页导出）
- 预览用 WebSocket **下行 JPEG**；Session / 流式 Agent 文本可与预览分通道（HTTP、SSE、或独立 WS）；实现时再定
- [markdown-it](https://github.com/markdown-it/markdown-it)
- [Bootstrap 5](https://getbootstrap.com/)（文档与 CSS / JS；与 Vue 仅通过 class 与自有组件结合）
- [browser-use](https://github.com/browser-use/browser-use) / [文档](https://docs.browser-use.com/)（工具与 Agent 循环的参考，实现上仅用 Playwright 公开 API，不跟其 CDP 工具面）

---

## 8. 后续发展方向（勿优先实现）

> **重要：本节为长期产品/技术构想，不是当前里程碑目标。**  
> 与上文第 5 节「分阶段计划」无执行关系；**现阶段不要按本节排期或落地实现**，待核心浏览器代理与预览闭环稳定后再单独立项讨论。

### 8.1 方向一：基于 Instruction 的 Skill 录制与生成

设想用**多条、分步的 instructions**（可配合统一的 PRO prompt）驱动 language model / browser agent：**逐步**打开网页、完成目标工作；在每一步中，同时保留「用户给的 instruction」与「该步实际调用的浏览器工具、具体操作」。

由模型把这些成对信息 **summarize 成可复用的 step-by-step 流程**，并进一步 **固化成 Skill**。与常见「browser use」类路径（用户自己在浏览器里点一圈，再事后总结步骤）相比：

- **Instruction 驱动**：每一步的**业务目的**在输入里就是明确的，agent 不是从纯行为反推意图。
- **工具与页面状态对齐**：在调用工具时更容易关联**应查找的元素**、当前 **browser / 页面** 长什么样，减少「只看操作录像、猜目的」的歧义。

因此预期：同样称为 Skill，**由「分步 instruction + 每步操作」归纳出来的 Skill**，会比「仅由人工操作浏览器再总结」得到的 Skill **更可执行、更稳、更可维护**，作为一种更先进、更偏「语义对齐」的录制/沉淀方式。

### 8.2 方向二：Session 归档与从「LLM + Browser」到「规则 + Browser」

Skill 不会永远以「每次从零让 LLM 想一遍」的方式重复执行。设想：

- **每次**执行某一 Skill（或完成一类任务）都落成一个 **Session**；
- 在数据库或 Session 列表中**结构化记录**：每一步的运行结果、推理链（CoT）、截图、关键中间状态等可审计材料；
- 同一 Skill **多次运行**会碰到不同页面状态、服务波动、分支与突发情况——这些数据持续沉淀，用于补全、修正一条**不断演进的「完整运行 flow」**。

长期演进目标（概念上）：

1. **早期**：人在环多指**任务/策略层**的监督与确认（**非**通过预览面向浏览器直接点按）；与第 1 节「只读预览」一致。
2. **中期**：仍以 **LLM + Browser** 为主自动跑，但已有可复用片段与经验。
3. **后期**：由 LLM 与历史 Session **归纳出明确规则**，形成 **workflow / 流程图式**的执行路径；**多数步骤按规则走**，仅在需要真实交互或异常处理时再 **按需调用 LLM**；理想情况下 **大部分路径不依赖 LLM**，从而 **减少人工介入、降低 LLM 调用与成本**。

这一条线可视为整个构想里**资源与可控性**方面的核心：从「靠 LLM 盯着跑」过渡到「主要靠规则 + 浏览器就能跑完」，LLM 退居为**按需**组件。

---

