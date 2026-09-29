# agent1旅行 — Agent 部分面试详解

> **文档定位**：本文档面向准备用本项目作为简历项目、且主要负责 Agent 部分的面试者。目标是用“文字 + 条例”把 Agent 的整体设计、每个模块的职责、实现细节、数据流转、工具使用、Prompt 写法、RAG、记忆层、面试要点讲清楚，**不贴代码**。

---

## 一、整体架构：多 Agent 模型选型

### 1.1 一句话定位

本项目采用的是**编排式 Multi-Agent（LangGraph StateGraph）**，而不是 "Main Agent + Sub Agent" 的层级委托模式。整个流程由 11 个职责单一的 Agent 节点按固定顺序串联执行，节点之间通过**共享状态（State）**交换数据。

### 1.2 为什么选编排式，而不是 Main Agent + Sub Agent？

| 对比维度 | 编排式 Multi-Agent | Main Agent + Sub Agent |
|---|---|---|
| 控制权 | 由图编排器统一管理，节点顺序清晰 | 由主 Agent 动态决定调用哪个子 Agent |
| 可观测性 | 每个节点执行什么、输入输出都很明确 | 主 Agent 的决策黑盒较大 |
| 调试难度 | 哪个节点出错就定位哪个节点 | 主 Agent 决策错误会导致子 Agent 被错误调用 |
| 适用场景 | 流程固定、步骤清晰、需要严格兜底 | 流程动态、需要高度灵活决策 |

旅行规划的步骤天然固定：先理解意图 → 再搜景点 → 查天气 → 搜酒店 → 搜餐厅 → 检索攻略 → 算路线 → 生成行程 → 算预算 → 保存。这种“流水线”形态非常适合编排式。如果做成 Main Agent + Sub Agent，主 Agent 需要反复判断下一步该做什么，反而增加不确定性，也不利于前端实时展示进度。

### 1.3 11 个 Agent 节点总览

整个规划流程包含 11 个节点，分成三类：

**信息收集类（6 个）**：
1. **IntentAgent**：把用户表单解析成结构化意图
2. **AttractionAgent**：搜索真实景点
3. **WeatherAgent**：查询旅行期间天气
4. **HotelAgent**：搜索酒店
5. **FoodAgent**：搜索真实餐厅
6. **RAGAgent**：检索城市攻略/背景知识

**决策规划类（2 个）**：
7. **RouteAgent**：计算景点间距离和时间矩阵
8. **PlannerAgent**：核心节点，生成完整多日行程

**校验与收尾类（3 个）**：
9. **BudgetAgent**：统计门票、餐饮、住宿、交通预算
10. **HumanInTheLoop**：人机协同节点（当前自动放行，预留扩展）
11. **Finalize**：把结果写入数据库，更新版本链

### 1.4 编排层的技术实现

虽然使用了 LangGraph 的 `StateGraph` 来定义节点和边，但实际执行时**并没有使用 LangGraph 的 `ainvoke` 自动调度**，而是在 `run_planning_graph` 里手动顺序调用每个节点函数。

**原因**：项目早期使用 `ainvoke` 时发现，当 State 里包含大量 Pydantic 对象（景点列表、酒店列表、路线矩阵等）时，LangGraph 的 Checkpoint 序列化机制会卡住。因此把调度层改成手动 `await node_func(state)`，但保留了 StateGraph 的节点定义方式，方便后续恢复自动调度或切换可视化。

**通俗解释**：就像一条工厂流水线，原本想让传送带自动把零件送到每个工位，但传送带在处理大件零件时会卡死，所以改成由班长按顺序喊每个工位开工。每个工位本身没变，只是启动方式变了。

---

## 二、Agent 之间怎么沟通：共享 State 机制

### 2.1 State 是什么

State 是整条流水线的**公共记事本**，本质上是一个大字典。每个节点从这个字典里读取自己需要的字段，处理完后把产出写回字典。下一个节点再从字典里读新的数据。

State 里包含的关键字段：

| 字段 | 含义 | 由谁写入 | 被谁读取 |
|---|---|---|---|
| `request` | 用户原始表单 | 路由层初始化 | IntentAgent、PlannerAgent |
| `intent_analysis` | 结构化意图 | IntentAgent | 几乎所有后续节点 |
| `attractions` | 候选景点列表 | AttractionAgent | RouteAgent、PlannerAgent |
| `hotels` | 候选酒店列表 | HotelAgent | PlannerAgent |
| `restaurants` | 候选餐厅列表 | FoodAgent | PlannerAgent |
| `weather` | 每日天气 | WeatherAgent | PlannerAgent |
| `route_matrix` | 景点间路线矩阵 | RouteAgent | PlannerAgent |
| `rag_context` | 攻略背景知识 | RAGAgent | PlannerAgent |
| `final_plan` | 最终行程 | PlannerAgent | BudgetAgent、Finalize |
| `logs` | 执行日志 | 每个节点 | SSE 推送给前端 |
| `messages` | LLM 消息上下文 | IntentAgent、PlannerAgent | 后续 LLM 调用 |

### 2.2 节点输入输出不是简单的“上一个输出作为下一个输入”

不是链式调用那样 `A 的输出 → B 的输入`。而是：
- 每个节点拿到**完整的当前 State**
- 节点只读取自己关心的字段
- 节点返回一个**更新字典**，只包含自己修改的字段
- 调度层把更新字典合并回 State

**举例**：AttractionAgent 读取 `intent_analysis.city` 和 `intent_analysis.preferences`，搜索景点后，返回 `{ "attractions": [...], "logs": [...], "current_step": "attraction_agent" }`。这个返回值被合并进 State，后续 RouteAgent 和 PlannerAgent 就能读到 `attractions`。

### 2.3 列表字段的合并方式

`logs` 和 `messages` 是追加合并，其他字段是覆盖。这样每个节点新产生的日志都会累加到 `logs` 列表里，前端 SSE 才能看到完整执行历史。

### 2.4 修订流程的 State 复用

行程修订时，State 会额外携带 `previous_plan`、`revision_notes`、`structured_feedback`、`parent_revision_id` 等字段。PlannerAgent 在生成新行程时，会把这些修订上下文追加到 Prompt 里，告诉 LLM“这是已有行程，用户要求做这些修改”。

---

## 三、11 个 Agent 逐一详解

### 3.1 IntentAgent（意图理解）

**职责**：把用户填写的表单和自由文本，解析成结构化的旅行意图。

**输入**：
- `state["request"]`：用户表单（城市、日期、偏好、必去景点、预算等级、饮食禁忌等）
- `state["user_id"]`：用于读取历史偏好

**输出**：
- `intent_analysis`：结构化意图对象，包含城市、起止日期、天数、交通方式、住宿类型、偏好标签、必去景点、预算等级、饮食禁忌、节奏、备注

**实现要点**：
1. 先调用 MemoryService 读取用户历史偏好，格式化成文本
2. 把表单 JSON + 偏好文本一起塞进 Prompt
3. 调用 LLM，要求输出严格 JSON
4. 用 `parse_llm_json` 解析并校验为 `IntentAnalysis` 模型
5. 如果解析失败，直接抛 `RuntimeError`，不再静默兜底

**为什么读取历史偏好在第一步？**：因为用户可能本次没有填写预算或节奏，但历史偏好里记录过。把这些信息前置，可以让后续所有节点都基于“完整用户画像”工作。

**面试要点**：这个节点决定了整条流水线的“地基”。如果意图理解错了（比如把“亲子”理解成“情侣”），后面所有节点都会跑偏。所以输出必须严格 JSON，且字段名固定。

---

### 3.2 AttractionAgent（景点检索）

**职责**：根据城市、偏好标签、必去景点，从高德 POI 搜索真实景点。

**输入**：
- `intent_analysis.city`
- `intent_analysis.preferences`
- `intent_analysis.must_visit`

**输出**：
- `attractions`：候选景点列表，最多 10 个

**实现要点**：
1. 构造搜索关键词：`默认关键词"景点" + 偏好标签 + 必去景点`，去重后最多取 4 个关键词
2. **优先单独搜索每个必去景点**，确保用户指定的景点不会因为数量限制被截断
3. 对每个关键词调用高德 POI 搜索，结果去重
4. 把高德返回的原始数据转换成 `Attraction` 模型（包含 ID、名称、经纬度、地址、描述、门票、评分、标签、图片、电话、营业时间、详情链接）
5. 为每个景点补充背景知识：调用 RAGService 的 `batch_search_or_fetch`，先查缓存，未命中则调百度百科，结果写回缓存

**为什么最多 10 个景点？**：因为后续 RouteAgent 要计算两两景点之间的距离，景点数为 N 时路线对数为 N×(N-1)。10 个景点是 90 对路线，已经能产生不少高德 API 调用。再增加会显著拖慢整体耗时。

**必去景点的特殊处理**：对每个 `must_visit` 单独搜索，且一旦找到名称匹配的景点就停止该关键词的搜索。这样可以确保必去景点排在列表前面，后续 PlannerAgent 的强制校验也更容易命中。

---

### 3.3 WeatherAgent（天气查询）

**职责**：获取旅行期间每日天气预报。

**输入**：
- `intent_analysis.city` 或 `request.city`
- `request.start_date`、`request.end_date`

**输出**：
- `weather`：每日天气信息列表（天气描述、温度范围、风力）

**实现要点**：
1. 调用高德天气接口，获取未来几天预报
2. 按日期匹配旅行期间的每一天
3. 如果旅行日期超出预报范围（高德通常只给 3-4 天），用最后一条预报兜底
4. 把白天和夜间天气组合成“晴转多云”这样的描述

**为什么天气要单独一个节点？**：因为天气会影响 PlannerAgent 的决策（雨天优先室内景点）。把天气作为独立字段存入 State，比让 PlannerAgent 自己调接口更可控。

---

### 3.4 HotelAgent（酒店推荐）

**职责**：搜索目标城市的真实酒店。

**输入**：
- `intent_analysis.city`
- `intent_analysis.accommodation`（住宿偏好，如“酒店”“民宿”）

**输出**：
- `hotels`：候选酒店列表，约 6 个

**实现要点**：
1. 如果用户有住宿偏好，用偏好作为关键词；否则默认“酒店”
2. 调用高德 POI 搜索酒店
3. 转换成 `Hotel` 模型（ID、名称、位置、每晚价格、评分、图片、电话、营业时间、详情链接）

**注意点**：酒店不直接绑定到某一天，而是作为候选池交给 PlannerAgent 选择。PlannerAgent 通常会把同一个酒店复用到多天，符合真实旅行习惯。

---

### 3.5 FoodAgent（餐厅搜索）

**职责**：搜索真实餐厅，供 PlannerAgent 安排三餐。

**输入**：
- `intent_analysis.city`
- `intent_analysis.preferences`

**输出**：
- `restaurants`：候选餐厅列表，约 15 个

**实现要点**：
1. 构造搜索关键词：`默认关键词"餐厅" + 偏好标签`（如“海鲜”“美食”），最多 2 个关键词
2. 对每个关键词调用高德餐饮 POI 搜索
3. 转换成 `Meal` 模型（名称、菜系、预估费用、位置、图片、评分、电话、营业时间、地址、详情链接）
4. 去重并按关键词控制数量

**为什么餐厅必须用真实店铺？**：这是项目的硬性约束。早期版本里 LLM 会编造餐厅名称，导致用户无法导航、无法预约。改成必须从高德 POI 选取后，餐厅信息包含真实地址、电话、图片，可信度和可用性大幅提升。

---

### 3.6 RAGAgent（知识检索）

**职责**：从向量库检索城市攻略和景点背景知识，给 PlannerAgent 提供参考。

**输入**：
- `intent_analysis.city`
- `intent_analysis.preferences`

**输出**：
- `rag_context`：检索到的文本上下文

**实现要点**：
1. 构造查询文本：`"{city}旅游攻略" + 偏好标签`
2. 调用 `search_rag_context` 工具，从 Qdrant 向量库检索 top 5 相关文档
3. 如果检索失败或向量为空，返回空字符串，不影响后续流程

**注意点**：RAGAgent 本身只负责从 Qdrant 检索**已经导入的城市攻略类文档**。它不会主动去百度百科抓取新知识，也不负责把新知识写回向量库。如果库里没数据，这个节点返回空，PlannerAgent 仍然可以正常工作。

**通俗解释**：RAGAgent 像是一个“图书管理员”，只负责在已经整理好的书架上找书。如果书架是空的，它不会跑出去买新书，而是直接告诉你“没有相关资料”。

---

### 3.7 RouteAgent（路线规划）

**职责**：计算所有候选景点两两之间的距离和通行时间。

**输入**：
- `state["attractions"]`：候选景点列表
- `intent_analysis.transportation`：交通方式

**输出**：
- `route_matrix`：路线矩阵，键为 `"景点A|景点B"`，值为距离（米）和时间（秒）

**实现要点**：
1. 根据交通方式选择高德路线规划模式：驾车（默认）、公交/地铁（transit）、步行（walking）
2. 为每对景点构造异步任务，用 `asyncio.gather` 并行调用高德路线接口
3. 如果高德接口失败，用 Haversine 公式计算直线距离，并按交通方式估算时间：
   - 驾车：约 0.5 秒/米
   - 公交：约 1.0 秒/米
   - 步行：约 3.0 秒/米
4. 结果存入路线矩阵

**为什么要算路线矩阵？**：PlannerAgent 安排每天景点时，可以参考“哪些景点离得近”，避免把城市两端的项目排同一天。虽然 PlannerAgent 不一定严格按最短路线排，但矩阵提供了重要约束。

---

### 3.8 PlannerAgent（行程规划，核心节点）

**职责**：综合所有前置信息，生成完整的多日行程计划。

**输入**：
- `intent_analysis`：结构化意图
- `attractions`：候选景点
- `weather`：天气
- `hotels`：候选酒店
- `restaurants`：候选餐厅
- `route_matrix`：路线矩阵
- `rag_context`：攻略背景
- `previous_plan`、`revision_notes`：修订时才有

**输出**：
- `candidate_plans`：候选方案列表（当前只生成一个）
- `final_plan`：最终行程计划

**实现要点**：
1. 拼接 Prompt：系统提示词 + 用户提示词
2. 用户提示词里包含所有前置信息，但候选 POI 会先经过 `_summarize_poi_for_prompt` 压缩，只保留“名称/地址/价格/评分/标签/营业时间”，把 Prompt 长度控制在 5000 字符以内
3. 调用 LLM，要求输出严格 JSON 格式的 `TripPlan`
4. 如果 LLM 调用或解析失败，先重试一次；重试失败则回退到 `_build_fallback_plan`
5. 补齐 `plan_id`、`user_id`、城市、日期、天数等元数据
6. **强制校验 must_visit**：检查用户指定的必去景点是否都在行程中，如果有缺失，从候选景点中匹配并插入到景点最少的那一天；如果候选列表中也没有，构造一个占位景点并插入
7. 为每一天补充地图中心点和路线 polyline

**为什么是最核心节点？**：它是唯一一个把所有信息“拼成完整行程”的节点。其他节点都是为它准备原材料。它的输出质量直接决定用户体验。

**兜底策略**：
- 第一次 LLM 调用设置 5 分钟超时
- 失败后重试一次，超时 3 分钟
- 再失败则使用 fallback plan：基于真实景点均匀分配到每一天，餐厅和酒店用通用描述
- 如果完全没有景点数据，则生成提示性行程，明确告诉用户“未能获取景点数据”

---

### 3.9 BudgetAgent（预算统计）

**职责**：根据最终行程计算预算。

**输入**：
- `state["final_plan"]`：完整行程

**输出**：
- 更新后的 `final_plan.budget`

**实现要点**：
1. 门票费用：累加所有景点的 `ticket_price`
2. 餐饮费用：累加所有餐食的 `estimated_cost`
3. 住宿费用：酒店每晚价格 ×（旅行天数 - 1）晚
4. 交通费用：固定 50 元/人/天
5. 汇总成 `Budget` 对象

**为什么是固定交通费？**：因为实际交通费用很难精确计算（公交、打车、地铁价格差异大），所以采用简化估算。如果要更精确，可以后续接入高德路径规划的费用接口。

---

### 3.10 HumanInTheLoop（人机协同）

**职责**：在关键决策点暂停，等待用户确认。

**当前实现**：自动放行，返回 `{ "auto_approved": True }`。

**预留扩展**：未来可以在这里实现“生成 2-3 个候选方案，让用户选一个再继续”，或者“遇到高预算时询问用户是否确认”。

---

### 3.11 Finalize（收尾保存）

**职责**：把最终行程写入数据库，维护版本链，固化长期记忆。

**输入**：
- `state["final_plan"]`
- `state["plan_id"]`
- `state["revision_type"]`、`state["parent_revision_id"]`、`state["previous_plan"]`
- `state["structured_feedback"]`、`state["revision_notes"]`

**实现要点**：
1. 把 `TripPlan` 序列化为 JSON，更新 `trip_plans` 表的 `plan_data` 和 `status`
2. 如果是初次规划，创建 `PlanRevision` v1
3. 如果是修订，基于 `parent_revision_id` 创建新版本，并调用 `_compute_plan_diff` 计算新旧行程差异，存入 `diff_summary`
4. 如果是反馈触发的修订，调用 `MemoryService.consolidate_memory` 把反馈中的偏好信号沉淀为长期记忆
5. 推送完成标记到 SSE 队列

**diff_summary 的作用**：前端可以基于这个字段展示“本次重新生成修改了 N 处”，解决“用户感觉行程没变化”的问题。

---

## 四、Agent 内部推理机制：不是 ReAct，是“结构化生成 + 校验”

### 4.1 为什么不使用 ReAct？

ReAct 的核心是“思考 → 行动 → 观察 → 再思考”的循环。它适合需要多步决策、动态选择工具的场景。但本项目的步骤是固定的：每个 Agent 该调什么工具、该输出什么格式，在设计时已经确定。如果让每个 Agent 都自己决定“我要不要调工具、调哪个工具”，会增加不确定性，也不利于前端展示固定进度。

所以本项目采用的是：**代码决定调用链 + LLM 负责结构化生成**。

### 4.2 每个 Agent 的标准推理模式

每个 LLM 驱动的 Agent 都遵循同一套模式：

1. **构造 Prompt**：系统提示词定义角色和输出格式，用户提示词提供具体上下文
2. **调用 LLM**：使用 LangChain 的 `ainvoke`，设置合适的 temperature
3. **解析输出**：用 `parse_llm_json` 从 LLM 返回的文本中提取 JSON 块
4. **Pydantic 校验**：把 JSON 解析成对应的 Pydantic 模型，自动校验字段类型
5. **后置校验/兜底**：比如 PlannerAgent 会强制检查 must_visit 是否遗漏
6. **记录日志**：把输入输出、工具调用、耗时写入 `AgentLog`

### 4.3 错误处理策略

| 层级 | 措施 |
|---|---|
| Prompt 层 | 明确要求输出 JSON，给出完整示例，禁止解释性文字 |
| 解析层 | `parse_llm_json` 会尝试从文本中抠出 JSON 块，处理 markdown 代码块包裹的情况 |
| 校验层 | Pydantic 模型校验字段类型和必填项 |
| 业务层 | PlannerAgent 强制校验 must_visit；AttractionAgent 单独搜索 must_visit |
| 兜底层 | LLM 失败时重试；再失败用 fallback plan；完全无数据时返回提示性行程 |

### 4.4 各节点温度设置

- **IntentAgent**：`temperature=0.3`，需要稳定、可预期的结构化输出
- **PlannerAgent**：`temperature=0.4`，允许一定创造性，但不要太发散
- 其他节点基本不直接调 LLM，所以没有温度参数

---

## 五、Tools 工具详解

项目里的工具分为两类：**外部服务工具**和**内部计算工具**。

### 5.1 外部服务工具

#### 5.1.1 高德 POI 搜索（景点、酒店、餐厅）

**功能**：根据城市 + 关键词搜索真实 POI，返回名称、位置、地址、评分、图片、电话、营业时间、详情链接等。

**内部实现**：
- 调用高德“地点搜索”API
- 根据 POI 类型（景点/酒店/餐饮）做字段映射
- 图片字段可能来自高德图片接口或详情接口
- 对结果做清洗：去掉明显不相关的条目、补默认值

**被哪些 Agent 调用**：
- AttractionAgent：搜景点
- HotelAgent：搜酒店
- FoodAgent：搜餐厅

#### 5.1.2 高德天气接口

**功能**：获取城市未来几天天气预报。

**被谁调用**：WeatherAgent。

#### 5.1.3 高德路线规划接口

**功能**：给定起点和终点经纬度，返回距离、通行时间、路线 polyline。

**支持模式**：驾车、公交、步行。

**被谁调用**：RouteAgent。

#### 5.1.4 Qdrant 向量检索

**功能**：根据查询向量，从向量库中检索最相似的文档片段。

**被谁调用**：RAGAgent。

#### 5.1.5 百度百科搜索

**功能**：当 RAG 缓存中没有景点背景知识时，去百度百科搜索摘要。

**被谁调用**：RAGService 内部调用，AttractionAgent 间接使用。

### 5.2 内部计算工具

#### 5.2.1 Haversine 距离计算

**功能**：根据两个经纬度计算地球表面直线距离。

**使用场景**：RouteAgent 在高德路线接口失败时做兜底估算。

#### 5.2.2 POI 摘要

**功能**：把 POI 对象压缩成只含关键字段的 JSON 行。

**使用场景**：PlannerAgent 构造 Prompt 前，把景点、酒店、餐厅列表压缩，减少 Prompt 长度 60%-70%。

#### 5.2.3 路线摘要

**功能**：把路线矩阵转成人类可读的文本，如“景点A|景点B: 距离 5000 米，耗时 15 分钟”。

**使用场景**：PlannerAgent Prompt 里提供路线参考。

### 5.3 工具调用记录

每个 Agent 在执行工具调用后，会把调用信息（工具名、关键词、结果数量、错误信息）记录到 `tool_calls` 列表。这个列表最终写入 `AgentLog`，前端 SSE 可以展示“AttractionAgent 搜索了 3 个关键词，找到 10 个景点”。

---

## 六、Prompt 提示词设计与开发

### 6.1 Prompt 写在哪里

所有 Agent 的 Prompt 统一放在 `app/agents/prompts.py` 中，按 Agent 分块管理。这样做的好处是：
- 修改 Prompt 不需要改业务逻辑
- 方便版本控制和 A/B 测试
- 面试时可以说“我们把 Prompt 当作配置文件来管理”

### 6.2 每个 Agent 的 Prompt 特点

#### IntentAgent
- **System Prompt**：定义角色为“旅行需求分析师”，明确要求输出 JSON，给出完整字段示例
- **Human Prompt**：包含用户表单 JSON + 历史偏好文本
- **特点**：字段名固定、预算等级和节奏必须是枚举值

#### PlannerAgent
- **System Prompt**：定义角色为“资深旅行规划师”，列出 10 条硬性约束
- **Human Prompt**：包含意图、景点、天气、酒店、餐厅、路线、攻略
- **特点**：
  - 反复强调“必须使用真实名称，禁止编造”
  - 明确 must_visit 必须全部包含
  - 明确 estimated_cost 必须是纯数字
  - 给出完整 JSON 示例

#### FeedbackExtractorAgent
- **System Prompt**：把自然语言反馈解析成结构化修改指令
- **特点**：
  - 定义 `scope` 只能是 `"day"` 或 `"whole"`
  - 定义 `actions` 数组，每个 action 有 type、day、meal、name、target_name、reason、constraints
  - 判断 `complexity` 是 `"patch"`（局部）还是 `"full"`（全局）

#### PatchPlanAgent
- **System Prompt**：基于当前行程和明确修改动作，生成新的完整行程
- **特点**：
  - 强调必须原样保留用户未提及的天和项目
  - 餐厅/酒店/景点必须从候选池选取
  - 输出完整 TripPlan，不是差异

#### MemoryConsolidatorAgent
- **System Prompt**：从反馈中提取长期偏好信号和事件记忆
- **特点**：区分 `abstract_preferences`（抽象偏好）和 `episodic_memories`（具体事件记忆）

### 6.3 Prompt 中的特殊约束

1. **JSON 输出约束**：每个 Prompt 都明确要求“只输出 JSON，不要解释性文字”
2. **字段名固定**：给出完整 JSON 示例，字段名不能改
3. **占位符转义**：Python 字符串模板里，JSON 的大括号要写成 `{{` 和 `}}`，否则会被 `str.format()` 误解析
4. **枚举值约束**：预算等级只能是 economy/standard/luxury，节奏只能是 relaxed/standard/intensive
5. **重复强调关键约束**：比如“必须用真实餐厅名称”“must_visit 不能遗漏”会在 System Prompt 里反复出现

### 6.4 Prompt 开发方法论

在实际开发中，写一个 Agent 的 Prompt 通常按以下步骤：

1. **定义输出格式**：先确定这个 Agent 要输出什么数据结构，把 JSON 示例写好
2. **写 System Prompt**：定义角色、任务、约束、输出格式
3. **写 Human Prompt**：把需要动态填充的上下文用占位符标出来
4. **本地构造测试输入**：用真实表单数据填充，检查 Prompt 长度是否合适
5. **调 LLM 看输出**：观察 LLM 是否按要求输出，是否编造字段
6. **加固约束**：发现 LLM 经常犯的错误后，在 System Prompt 里加一条明确禁止
7. **加兜底校验**：Prompt 约束不够，代码层再加校验（如 must_visit 强制插入）

**面试时可以说的经验**：
- “我们发现只写 Prompt 不够，LLM 在长上下文下会遗漏约束，所以代码层必须有后置校验。”
- “我们会把 Prompt 版本化，每次调整都记录效果，方便回滚。”
- “对于结构化输出，我们采用 Prompt 约束 + Pydantic 校验双重保险。”

---

## 七、共享记忆图与长期偏好

### 7.1 记忆层的三层结构

项目中的记忆不是单一概念，而是分成三层：

| 层级 | 载体 | 内容 | 作用 |
|---|---|---|---|
| 短期记忆 | `trip_plans` 表 + `PlanRevision` 表 | 当前行程、历史版本 | 支持版本链和 diff 展示 |
| 中期记忆 | `PlanFeedback` 表 | 用户对每次行程的反馈 | 支持反馈撤回、编辑、聚合 |
| 长期记忆 | `UserPreference` 表 + `UserMemory` 表 + Qdrant | 抽象偏好、具体事件记忆 | 跨行程影响未来规划 |

### 7.2 长期记忆什么时候构建？

**构建时机**：每次用户提交反馈并触发“重新生成行程”后，在 `Finalize` 节点里调用 `MemoryService.consolidate_memory`。

**构建流程**：
1. `FeedbackExtractorAgent` 把自然语言反馈解析成结构化反馈
2. 重新生成行程（patch 或 full）
3. `Finalize` 节点拿到结构化反馈，调用 `consolidate_memory`
4. `consolidate_memory` 做三件事：
   - 更新 `UserPreference` 的抽象偏好（如 price_sensitivity=high）
   - 把具体动作写入 `UserMemory`（如“用户 dislike 赤坎老街，原因是太商业化”）
   - 把 `UserMemory` 同步到 Qdrant，做向量化存储

### 7.3 长期记忆什么时候使用？

**使用时机**：每次新建行程时，`IntentAgent` 第一步就会读取 `UserPreference`，把历史偏好格式化成文本塞进 Prompt。

**作用**：
- 如果用户上次反馈“想吃海鲜”，下次新建行程时 IntentAgent 会知道
- 如果用户上次 dislike 某个景点，下次 AttractionAgent 可以优先排除（当前实现主要是 IntentAgent 参考偏好）

### 7.4 抽象偏好 vs 具体事件记忆

**抽象偏好（UserPreference）**：
- 结构化的、可泛化的偏好
- 例如：`{"price_sensitivity": "high", "preferred_pace": "relaxed", "food_taste": "海鲜"}`
- 适合直接写进 Prompt

**具体事件记忆（UserMemory + Qdrant）**：
- 记录某个具体实体的正负反馈
- 例如：`{"memory_type": "attraction_dislike", "entity_name": "赤坎老街", "reason": "太商业化"}`
- 通过向量检索，在相似场景下回忆

### 7.5 记忆的向量同步与检索

- 写入：把 `UserMemory` 的文本（类型 + 实体名 + 原因 + 上下文）用 Embedding 模型编码，存入 Qdrant
- 检索：根据当前查询（如城市 + 景点名）生成向量，从 Qdrant 搜相似记忆
- 过滤：检索时按 `user_id` 和 `source_type` 过滤，确保只召回当前用户的记忆

**面试要点**：可以说“我们采用了双轨记忆：抽象偏好直接写进 Prompt，具体事件记忆走向量检索，兼顾了稳定性和场景化召回。”

---

## 八、RAG 系统详解

### 8.1 RAG 在项目中的定位

RAG 不是项目的核心链路，而是**增强链路**。它的作用是为景点和 PlannerAgent 提供背景知识，让生成的推荐理由更真实、更有深度。即使没有 RAG，系统也能正常工作。

### 8.2 RAG 架构

```
数据源（百度百科 / 爬虫文档 / 上传文档）
    ↓
文本分块（Chunk）
    ↓
Embedding 模型编码
    ↓
存入 Qdrant 向量库
    ↓
用户查询 → Embedding → 向量检索 → Top K 相关片段 → 拼成上下文
    ↓
交给 PlannerAgent 或 AttractionAgent 使用
```

### 8.3 两条不同的数据补充路径

项目里实际上有两条不同的“知识补充”路径，不要混淆：

**路径一：景点背景知识（AttractionAgent → RAGService → 百度百科/缓存）**
- 触发时机：AttractionAgent 已经拿到高德景点列表之后
- 流程：
  1. 调用 `RAGService.batch_search_or_fetch`
  2. 先在本地缓存/Qdrant 里查这个景点的背景知识
  3. 如果缓存没有，去百度百科抓摘要
  4. 把结果写回缓存，下次再用同一个景点时直接命中缓存
- 特点：这是**主动抓取 + 缓存**模式，数据来源是百度百科

**路径二：城市攻略检索（RAGAgent → Qdrant）**
- 触发时机：RAGAgent 节点
- 流程：
  1. 构造 `"{city}旅游攻略" + 偏好标签` 的查询文本
  2. 从 Qdrant 向量库检索已经导入的文档
  3. 如果向量库为空，直接返回空字符串，**不会去百度百科抓**
- 特点：这是**纯检索**模式，数据必须提前导入

**其他数据源**：
- **爬虫文档**：`CrawledDocument` 表存储爬取的城市攻略、景点介绍，需要批量导入 Qdrant 后才能被 RAGAgent 检索到
- **用户上传文档**：理论上支持，但当前 MVP 未实现

### 8.4 Embedding 模型

- 默认使用本地 Embedding 模型（通过 `sentence-transformers`）
- 如果本地模型加载失败（例如 torch DLL 加载失败），会降级为纯外部搜索模式
- Embedding 用于把查询文本和文档片段转成向量

### 8.5 检索方式

- 向量相似度搜索：在 Qdrant 中用余弦相似度找最相关的 Top K 片段
- 过滤条件：可以按 `city`、`source_type` 过滤
- 当前 RAGAgent 默认取 Top 5

### 8.6 RAG 在 Agent 中的使用

| 使用点 | 路径 | 作用 |
|---|---|---|
| AttractionAgent | 景点背景知识路径 | 为每个景点补充背景描述，先查缓存，缓存未命中则调百度百科，结果写回缓存 |
| RAGAgent | 城市攻略检索路径 | 从 Qdrant 检索已导入的城市攻略，拼进 PlannerAgent 的 Prompt |
| MemoryService | 记忆向量路径 | 把 UserMemory 向量化存入 Qdrant，支持相似场景召回 |

### 8.7 降级策略

- 如果 Qdrant 没启动，`RAGService` 会捕获异常，使用内存模式或返回空字符串
- 如果 Embedding 模型加载失败，会降级为纯外部搜索（如百度百科）
- 这些降级都不会阻断主流程，只是背景知识可能没那么丰富

### 8.8 RAG 带来的收益

1. 景点描述不再是“XXX 是热门景点”这种模板化句子，而是有历史文化背景
2. PlannerAgent 可以参考城市攻略，生成更有针对性的整体建议
3. 长期记忆的 episodic 记忆可以通过向量检索跨场景复用

---

## 九、SSE 实时进度推送

### 9.1 为什么需要 SSE？

生成一份完整行程可能需要几分钟（调多次高德 API + LLM）。如果让用户一直转圈等待，体验很差。SSE（Server-Sent Events）可以让后端把每个 Agent 的执行状态实时推给前端，用户能看到“正在理解意图…正在搜索景点…正在规划路线…”等进度。

### 9.2 实现机制

1. 后端为每个 `plan_id` 维护一个异步队列
2. 每个 Agent 节点执行完后，把 `AgentLog` 放入队列
3. 前端通过 `GET /api/agent/stream/{plan_id}` 建立 SSE 连接
4. 后端从队列里取日志，通过 SSE 推送给前端
5. 全部节点执行完后，推送 `completed` 或 `failed` 标记

### 9.3 AgentLog 包含什么

- `step`：步骤名称
- `agent_name`：Agent 名称
- `input_preview`：输入摘要
- `output_preview`：输出摘要
- `tool_calls`：工具调用记录
- `duration_ms`：执行耗时
- `timestamp`：时间戳

### 9.4 为什么不是模拟进度条？

早期版本曾用模拟进度条（每几秒涨一点），但会导致“进度条走完了，实际还没生成好”或“已经生成好了，进度条还没满”的问题。改成真实队列推送后，前端展示的状态和后端实际执行完全一致。

---

## 十、反馈迭代与版本链

### 10.1 反馈流程

1. 用户在结果页对某天或整体提交反馈（标签 + 文字）
2. 反馈只保存到 `PlanFeedback` 表，**不立即触发重算**
3. 用户可以提交多条反馈，也可以撤回或编辑
4. 用户点“根据所有反馈重新生成行程”后，后端聚合所有有效反馈
5. 后端调用 `FeedbackExtractorAgent` 把聚合后的反馈解析成结构化指令
6. 根据 `complexity` 判断走 patch 还是 full：
   - **patch**：只修改单天的景点/餐厅/酒店，调用 `PatchPlanAgent`
   - **full**：重新跑完整 11 节点流程，PlannerAgent 基于修订上下文生成新行程
7. 生成新版本，计算 diff_summary，保存到 `PlanRevision`
8. 前端自动刷新，展示新版本和修改摘要

### 10.2 版本链设计

- 每个 `plan_id` 对应一条版本链
- `PlanRevision` 表记录每次生成的版本，包含 `version`、`parent_revision_id`、`source`（initial/patch/full）、`diff_summary`
- 只有 `is_current=True` 的版本是前端默认展示的
- 版本链让“时光机回退”成为可能，当前实现只展示最新版本

### 10.3 per-plan 互斥锁

同一 `plan_id` 同时只能有一个修订任务在执行。如果用户连续点击两次“重新生成”，第二个请求会被直接拒绝，避免数据库冲突和重复计算。

---

## 十一、面试高频问题与回答要点

### Q1：你们用的是 Multi-Agent 吗？具体是什么模式？

**答**：是的，用的是编排式 Multi-Agent。我们把旅行规划拆成 11 个职责单一的 Agent 节点，用 LangGraph 的 StateGraph 定义节点和边，节点之间通过共享 State 传递数据。不是 Main Agent + Sub Agent 的层级模式，因为旅行规划的步骤比较固定，编排式更可控、更可观测。

### Q2：Agent 之间是怎么通信的？

**答**：通过共享 State 通信。每个节点读取 State 中自己需要的字段，处理完后返回一个更新字典，调度层把更新合并回 State。列表字段如 `logs` 是追加合并，其他字段是覆盖。这样每个节点都能看到完整的上下文，而不是只拿到上一个节点的输出。

### Q3：每个 Agent 内部是怎么推理的？是 ReAct 吗？

**答**：不是 ReAct。我们的每个 Agent 内部是“Prompt + LLM 结构化生成 + Pydantic 校验”的模式。因为每个 Agent 该调什么工具、输出什么格式是设计时就确定的，不需要让 LLM 自己决定。这样更稳定，也更容易调试。

### Q4：你们用了哪些 Tools？

**答**：外部工具包括高德 POI 搜索（景点/酒店/餐厅）、高德天气接口、高德路线规划接口、Qdrant 向量检索、百度百科搜索。内部工具包括 Haversine 距离计算、POI 摘要压缩、路线摘要生成。每个 Agent 调用的工具是代码决定的，比如 AttractionAgent 调高德 POI 和 RAG，RouteAgent 调高德路线和 Haversine 兜底。

### Q5：Prompt 是怎么写的？有什么经验？

**答**：所有 Prompt 集中在 `prompts.py` 管理，按 Agent 分块。写 Prompt 时我们有几条原则：
1. 明确角色和任务；
2. 给出完整 JSON 示例，字段名固定；
3. 反复强调关键约束，比如“禁止编造景点/餐厅名称”“must_visit 必须包含”；
4. Python 模板里的 JSON 大括号要转义；
5. 只让 LLM 输出 JSON，不要解释性文字。
另外，我们发现 Prompt 约束不够，代码层必须有后置校验，比如 PlannerAgent 会强制检查 must_visit 是否遗漏。

### Q6：RAG 是怎么实现的？在 Agent 里怎么用的？

**答**：RAG 使用 Qdrant 向量库。数据源包括百度百科、爬虫文档。文本经过分块和 Embedding 编码后存入向量库。使用时把查询文本也编码成向量，做相似度检索，取 Top K 片段拼成上下文。RAGAgent 把检索到的城市攻略交给 PlannerAgent；AttractionAgent 也会用 RAG 为景点补充背景描述。如果 Qdrant 没启动或 Embedding 模型加载失败，会降级，不影响主流程。

### Q7：记忆层是怎么设计的？

**答**：记忆分三层：短期记忆是行程版本链和反馈记录；长期记忆是 UserPreference 抽象偏好和 UserMemory 具体事件记忆。每次用户反馈并重新生成后，FeedbackExtractor 会解析出偏好信号，Finalize 节点把这些信号固化到 UserPreference，同时把具体事件写入 UserMemory 并同步到 Qdrant。新建行程时，IntentAgent 会读取 UserPreference 并写进 Prompt。

### Q8：怎么保证生成的餐厅、景点是真实的？

**答**：两条防线：
1. 所有 POI 必须来自高德 API，不允许 LLM 编造；
2. PlannerAgent 的 Prompt 里反复强调“必须从候选列表中选取真实名称”，并且候选列表是压缩后的真实 POI 数据。如果 LLM 仍然编造，Pydantic 校验会暴露字段问题，但主要靠 Prompt 约束和候选池限制。

### Q9：如果 LLM 输出不稳定或超时，你们怎么处理？

**答**：分多层处理：
1. Prompt 明确要求 JSON 格式和固定字段；
2. `parse_llm_json` 会尝试从文本中抠出 JSON；
3. Pydantic 校验字段类型；
4. PlannerAgent 设置 5 分钟超时，失败后重试一次；
5. 重试失败用 fallback plan 兜底；
6. 完全无数据时返回提示性行程，而不是编造景点。

### Q10：项目里遇到的最大挑战是什么？

**答**（可选）：
1. LangGraph 的 `ainvoke` 在复杂 Pydantic 状态下会卡住，我们改成手动顺序调用节点；
2. Prompt 过长（曾经 23K 字符）导致 LLM 注意力分散，我们加了 POI 摘要机制，控制在 5K 以内；
3. 用户反馈原来立即触发修订，导致无法提交多条反馈，改成聚合后统一处理；
4. 修订后用户看不出变化，我们加了 diff_summary 和前端高亮。

---

## 十二、补充细节：开发 Agent 时的整体思路

如果你是负责 Agent 部分的开发者，面试时可以这样描述你的工作流程：

1. **拆步骤**：先把旅行规划这个复杂任务拆成不可再拆的原子步骤（意图理解、搜景点、查天气、算路线、生成行程等）。
2. **定输入输出**：每个步骤明确输入字段和输出数据结构，用 Pydantic 模型固化。
3. **选工具**：根据每个步骤的需求选外部 API（高德）或内部算法（Haversine）。
4. **写 Prompt**：给 LLM 驱动的节点写 System Prompt 和 Human Prompt，重点是输出格式和约束。
5. **加校验**：Prompt 不是万能的，代码层必须校验关键业务规则（如 must_visit）。
6. **串流程**：用 StateGraph 或手动顺序把节点串起来，通过 State 传递数据。
7. **做观测**：每个节点写日志，通过 SSE 推给前端，方便用户感知进度，也方便排查问题。
8. **做迭代**：支持用户反馈 → 结构化提取 → 局部或全局修订 → 版本链 + diff 展示。
9. **做记忆**：把反馈中的长期偏好沉淀下来，影响未来行程。
10. **做兜底**：任何外部依赖（LLM、高德、Qdrant）都可能失败，必须有不编造的降级方案。

---

## 十三、写在最后

本项目的 Agent 部分核心可以概括为：**“编排式 Multi-Agent + 真实 POI 数据 + 结构化生成 + 多层校验 + 长期记忆”**。面试时不需要背诵代码，但要能讲清楚：
- 为什么这样设计架构
- 每个 Agent 做什么、输入输出是什么
- Agent 之间怎么传递数据
- Tools 有哪些、怎么实现
- Prompt 怎么写、怎么约束
- RAG 和记忆层在哪里用、怎么用
- 遇到 LLM 不稳定、外部服务失败时怎么处理

把这些点用条例化的方式讲出来，配合项目中的真实案例（如 must_visit 强制校验、POI 摘要、diff_summary），就能给面试官留下“对项目很熟悉”的印象。
