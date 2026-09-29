# 旅行规划项目 RAG 架构说明

> 本文档详细说明项目中 RAG（检索增强生成）的整体框架、向量库流程、数据流转、相关技术及对应文件。

## 零、写给新同学的一段话

RAG 全称是 **Retrieval-Augmented Generation（检索增强生成）**。用人话说就是：

> **AI 回答问题之前，先去查一下"小抄"，让回答更真实。**

为什么要这么做？因为 LLM（比如通义千问）有两大短板：
1. **知识可能过时**——它的训练数据有截止时间，新景点、新餐厅它不认识
2. **会"一本正经地编"**——有时会编造听起来对但实际不存在的景点

RAG 的解决方案是：**让 AI 在生成回答前先查知识库，把查到的真实内容塞进 prompt 里**，AI 再基于这些真实内容回答。

本项目的 RAG 不是一个"大而全"的系统，而是一个**轻量、按需查询、越用越聪明**的小模块。下面会一步步讲清楚它是怎么实现的。

---

## 一、RAG 设计思想

### 1.1 为什么需要 RAG？

旅行规划 Agent 需要为景点、酒店、美食提供**背景知识**，例如：

- 赤坎老街有什么历史？
- 金沙湾适合什么时候去？
- 当地有什么特色美食？

这些知识如果全靠 LLM 预训练记忆，会存在两个问题：

1. **知识不新**：LLM 训练数据有截止日期，景点信息可能过时
2. **容易编造**：LLM 可能生成"听起来对但不存在"的景点描述

RAG 的思路是：**用时才检索真实数据源，把检索结果喂给 LLM，让 LLM 基于真实信息生成内容**。

### 1.2 本项目采用的模式：搜索优先，渐进积累

```
┌─────────────────────────────────────────────────────────────┐
│                    搜索优先，渐进积累                         │
├─────────────────────────────────────────────────────────────┤
│  1. 优先查本地向量库缓存                                      │
│     ├── 命中高置信度结果 → 直接返回                           │
│     └── 未命中或置信度低 → 步骤 2                            │
│                                                              │
│  2. 调用外部搜索（百度百科）                                   │
│     ├── 获取词条内容                                          │
│     └── 存入向量库缓存                                        │
│                                                              │
│  3. 下次再搜同样内容 → 直接从缓存命中                         │
└─────────────────────────────────────────────────────────────┘
```

**不预导入**：我们不预先爬取大量攻略数据导入向量库，因为维护成本高、数据易过时。

**渐进积累**：每搜一次，知识库就多一点，越用越聪明。

---

## 二、整体架构

### 2.1 架构分层

```
┌──────────────────────────────────────────────────────────────┐
│                         应用层                                │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐   │
│  │ 前端 Result  │  │ 前端 Planning│  │   Agent 工作流    │   │
│  │   .vue       │  │    .vue      │  │   nodes.py       │   │
│  └──────┬───────┘  └──────┬───────┘  └────────┬─────────┘   │
└─────────┼─────────────────┼───────────────────┼─────────────┘
          │                 │                   │
          ▼                 ▼                   ▼
┌──────────────────────────────────────────────────────────────┐
│                         Agent 层                              │
│  ┌─────────────────┐  ┌─────────────────┐  ┌──────────────┐ │
│  │ AttractionAgent │  │   HotelAgent    │  │ PlannerAgent │ │
│  │   (nodes.py)    │  │    (nodes.py)   │  │  (nodes.py)  │ │
│  └────────┬────────┘  └────────┬────────┘  └──────┬───────┘ │
│           │                    │                   │         │
│           ▼                    ▼                   ▼         │
│  ┌────────────────────────────────────────────────────────┐ │
│  │              RAGService (rag_service.py)                │ │
│  │  ┌─────────────┐  ┌─────────────┐  ┌───────────────┐  │ │
│  │  │   search()  │  │search_or_fetch│ │batch_search_or│  │ │
│  │  │             │  │             │  │    _fetch     │  │ │
│  │  └──────┬──────┘  └──────┬──────┘  └───────┬───────┘  │ │
│  └─────────┼────────────────┼──────────────────┼─────────┘ │
└────────────┼────────────────┼──────────────────┼───────────┘
             │                │                  │
             ▼                ▼                  ▼
┌──────────────────────────────────────────────────────────────┐
│                        基础设施层                             │
│  ┌─────────────────┐  ┌─────────────────┐  ┌──────────────┐ │
│  │  Qdrant 向量库   │  │ Embedding 模型   │  │ 百度百科爬虫  │ │
│  │  (Docker/本地)   │  │ SentenceTransf. │  │baike_service │ │
│  └─────────────────┘  └─────────────────┘  └──────────────┘ │
└──────────────────────────────────────────────────────────────┘
```

### 2.2 核心组件说明

| 组件 | 文件 | 作用 |
|------|------|------|
| RAGService | `backend/app/services/rag_service.py` | 封装向量检索、文档入库、搜索优先/外部搜索联动 |
| BaikeService | `backend/app/services/baike_service.py` | 百度百科外部搜索，无需 API Key |
| Embedding | `sentence-transformers` | 将文本转为向量 |
| 向量数据库 | `Qdrant` | 存储向量，支持相似度检索 |
| AttractionAgent | `backend/app/agents/nodes.py` | 调用 RAG 为景点补充背景知识 |
| PlannerAgent | `backend/app/agents/nodes.py` | 基于候选景点 + RAG 上下文生成行程 |

---

## 三、向量库工作流程

### 3.1 写入流程（Add Documents）

```
外部搜索结果 / 手动录入文档
        │
        ▼
┌─────────────────┐
│  文本切分        │  RecursiveCharacterTextSplitter
│  chunk_size=500 │  chunk_overlap=100
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  文本 Embedding  │  sentence-transformers
│  768 维向量      │  中文模型（默认 all-MiniLM-L6-v2 或中文模型）
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  存入 Qdrant     │  collection: travel_rag
│  向量 + payload  │  payload: {title, content, city, source_type}
└─────────────────┘
```

**代码位置：** [rag_service.py → add_documents()](file:///d%3A/agent1/backend/app/services/rag_service.py#L103-L137)

```python
def add_documents(self, documents, city=None):
    self._ensure_collection()
    points = []
    point_id = 0
    for doc in documents:
        chunks = self.split_text(doc["content"])
        for chunk in chunks:
            vector = self.embed_texts([chunk])[0]
            points.append({
                "id": point_id,
                "vector": vector,
                "payload": {
                    "title": doc.get("title", ""),
                    "content": chunk,
                    "city": city,
                    "source_type": doc.get("source_type", "manual")
                }
            })
            point_id += 1
    if points:
        self.client.upsert(collection_name=self.collection_name, points=points)
```

### 3.2 检索流程（Search）

```
用户查询 / Agent 查询
        │
        ▼
┌─────────────────┐
│  查询文本 Embedding │
│  同一模型编码      │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Qdrant 相似度搜索 │
│  Cosine 距离     │
│  可选 city 过滤   │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  返回 top_k 结果  │
│  {content, title, score} │
└─────────────────┘
```

**代码位置：** [rag_service.py → search()](file:///d%3A/agent1/backend/app/services/rag_service.py#L138-L181)

```python
def search(self, query, city=None, top_k=None):
    self._ensure_collection()
    top_k = top_k or settings.rag_top_k
    query_vector = self.embed_texts([query])[0]

    filter_condition = None
    if city:
        filter_condition = {"must": [{"key": "city", "match": {"value": city}}]}

    results = self.client.search(
        collection_name=self.collection_name,
        query_vector=query_vector,
        limit=top_k,
        query_filter=filter_condition
    )

    return [
        {"content": r.payload.get("content", ""), "title": r.payload.get("title", ""), "score": r.score}
        for r in results
    ]
```

### 3.3 集合创建策略

```python
def _ensure_collection(self):
    collections = self.client.get_collections().collections
    exists = any(c.name == self.collection_name for c in collections)
    if not exists:
        sample_embedding = self.embedding_model.encode("示例文本")
        vector_size = len(sample_embedding)
        self.client.create_collection(
            collection_name=self.collection_name,
            vectors_config={"size": vector_size, "distance": "Cosine"}
        )
```

**说明：**
- 首次写入时自动创建 Qdrant 集合
- 向量维度由 Embedding 模型动态决定
- 距离度量使用 Cosine（适合语义相似度）

---

## 四、搜索优先 + 外部搜索联动流程

### 4.1 核心方法：search_or_fetch

```python
async def search_or_fetch(
    self,
    query: str,
    city: Optional[str] = None,
    source_type: str = "attraction",
    external_fetcher: Optional[Callable] = None,
    min_score: float = 0.75,
    top_k: int = None
) -> Dict[str, Any]:
```

**代码位置：** [rag_service.py → search_or_fetch()](file:///d%3A/agent1/backend/app/services/rag_service.py#L183-L281)

### 4.2 流程时序

```
Agent 调用 search_or_fetch("赤坎老街", city="湛江")
            │
            ▼
    ┌──────────────────┐
    │ 1. 检索本地缓存    │
    │ search("赤坎老街") │
    │ city="湛江" 过滤   │
    └────────┬─────────┘
             │
        ┌────┴────┐
        ▼         ▼
    命中高置信      未命中 / 低置信
    (score>=0.75)   (score<0.75)
        │             │
        │             ▼
        │      ┌──────────────────┐
        │      │ 2. 调用外部搜索   │
        │      │ 默认百度百科      │
        │      │ baike.search()   │
        │      └────────┬─────────┘
        │               │
        │               ▼
        │      ┌──────────────────┐
        │      │ 3. 存入向量库     │
        │      │ add_documents()  │
        │      └────────┬─────────┘
        │               │
        ▼               ▼
    ┌──────────────────────────────┐
    │ 4. 返回结果                    │
    │ {content, title, score,       │
    │  from_cache, source_type, url} │
    └──────────────────────────────┘
```

### 4.3 关键逻辑代码

```python
async def search_or_fetch(self, query, city=None, source_type="attraction",
                          external_fetcher=None, min_score=0.75, top_k=None):
    # 1. 先查本地缓存
    cached_results = self.search(query, city=city, top_k=top_k)

    if cached_results:
        best = cached_results[0]
        if best.get("score", 0) >= min_score:
            best["from_cache"] = True
            return best

    # 2. 缓存未命中，调外部搜索
    if external_fetcher is None:
        from app.services.baike_service import get_baike_service
        external_fetcher = get_baike_service().search

    external_result = await external_fetcher(query, city)

    # 3. 存入缓存
    if external_result and external_result.get("summary"):
        self.add_documents(documents=[{
            "title": external_result.get("title", query),
            "content": external_result.get("summary", ""),
            "source_type": source_type
        }], city=city)

        return {
            "content": external_result.get("summary", ""),
            "title": external_result.get("title", query),
            "score": 1.0,
            "from_cache": False,
            "source_type": source_type,
            "url": external_result.get("url", "")
        }

    # 4. 外部搜索失败，返回次优缓存
    if cached_results:
        best = cached_results[0]
        best["from_cache"] = True
        return best

    # 5. 完全无结果
    return {"content": "", "title": query, "score": 0.0, "from_cache": False, "source_type": source_type}
```

### 4.4 批量版本

```python
async def batch_search_or_fetch(self, queries, city=None, source_type="attraction",
                                external_fetcher=None, min_score=0.75):
    tasks = [
        self.search_or_fetch(q, city, source_type, external_fetcher, min_score)
        for q in queries
    ]
    return await asyncio.gather(*tasks)
```

**使用场景：** `attraction_agent_node` 一次搜索 5~10 个景点的背景知识。

---

## 五、百度百科外部搜索（BaikeService）

### 5.1 设计原因

选择百度百科的原因：

1. **无需 API Key**：公开网页可直接爬取
2. **中文景点覆盖广**：国内景点基本都有词条
3. **内容质量稳定**：摘要通常包含历史背景和特色介绍

### 5.2 爬虫流程

```
查询 "赤坎老街 湛江"
        │
        ▼
┌─────────────────────┐
│ 1. 百度百科搜索页    │
│ https://baike.baidu.com/search?word=... │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ 2. 解析第一个词条链接│
│ class="result-title" │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ 3. 访问词条详情页    │
│ https://baike.baidu.com/item/... │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ 4. 提取摘要          │
│ class="lemma-summary" │
│ id="J-lemma-summary"  │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ 5. 返回结构化结果    │
│ {title, summary, url} │
└─────────────────────┘
```

### 5.3 关键代码

**文件：** [baike_service.py](file:///d%3A/agent1/backend/app/services/baike_service.py)

```python
async def search(self, query, city=None, use_cache=True):
    search_query = f"{city} {query}" if city else query

    # 内存缓存
    cache_key = self._cache_key(query, city)
    if use_cache and cache_key in self._cache:
        return self._cache[cache_key]

    # 搜索词条
    item_url = await self._search_item(search_query)
    if not item_url:
        return {"title": query, "summary": f"未找到 {query} 的百科词条。", "url": "", "source_type": "baike"}

    # 获取摘要
    summary = await self._fetch_item_summary(item_url)

    result = {
        "title": query,
        "summary": summary or "",
        "url": item_url,
        "source_type": "baike",
        "from_cache": False
    }

    if use_cache:
        self._cache[cache_key] = result

    return result
```

### 5.4 两层缓存

| 缓存层级 | 位置 | 作用 | 生命周期 |
|---------|------|------|---------|
| 内存缓存 | `BaikeService._cache` | 避免同一进程内重复请求百度百科 | 进程内 |
| 向量库缓存 | Qdrant | 跨请求、跨进程复用已检索内容 | 持久化 |

---

## 六、RAG 在 Agent 工作流中的位置

### 6.1 当前接入点

```
用户提交表单
    │
    ▼
┌─────────────────┐
│ IntentAgent     │ 解析城市、偏好、必去景点
└────────┬────────┘
         │
         ▼
┌─────────────────────────────────────────────────────┐
│ AttractionAgent                                       │
│                                                       │
│  1. 高德 POI 搜索 → 获取基础信息（名称/地址/评分）      │
│  2. RAG 搜索      → batch_search_or_fetch()          │
│     ├── 优先查 Qdrant 缓存                           │
│     ├── 未命中 → 百度百科搜索                        │
│     └── 合并背景知识到 description                    │
└────────┬────────────────────────────────────────────┘
         │
         ▼
┌─────────────────┐
│ RouteAgent      │ 计算景点间路线
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ PlannerAgent    │ 基于候选景点 + RAG 上下文生成行程
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ BudgetAgent     │ 统计预算
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ FinalizeAgent   │ 保存结果
└─────────────────┘
```

### 6.2 AttractionAgent 中 RAG 调用代码

**文件：** [nodes.py → attraction_agent_node](file:///d%3A/agent1/backend/app/agents/nodes.py#L596-L637)

```python
if attractions:
    from app.services.rag_service import RAGService
    rag = RAGService()

    attraction_names = [a.name for a in attractions]
    background_results = await rag.batch_search_or_fetch(
        queries=attraction_names,
        city=city,
        source_type="attraction",
        min_score=0.75
    )

    for i, attraction in enumerate(attractions):
        if i < len(background_results):
            bg = background_results[i]
            if bg.get("content") and len(bg["content"]) > len(attraction.description or ""):
                attraction.description = bg["content"]
            if bg.get("url") and not attraction.detail_url:
                attraction.detail_url = bg["url"]
```

---

## 七、数据模型与 Payload 设计

### 7.1 向量库中的 Point 结构

```json
{
  "id": 0,
  "vector": [0.12, -0.05, ..., 0.08],
  "payload": {
    "title": "赤坎老街",
    "content": "赤坎老街是湛江市历史最悠久的街区之一...",
    "city": "湛江",
    "source_type": "attraction"
  }
}
```

### 7.2 payload 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| title | string | 词条/景点标题 |
| content | string | 文本片段（切分后） |
| city | string | 所属城市，用于过滤 |
| source_type | string | 数据来源：attraction / hotel / food / city_guide |

### 7.3 未来可扩展字段

```json
{
  "payload": {
    "title": "...",
    "content": "...",
    "city": "湛江",
    "source_type": "attraction",
    "url": "https://baike.baidu.com/item/...",
    "create_time": "2026-07-14T10:00:00",
    "hit_count": 5,
    "user_ratings": ["like", "like", "dislike"]
  }
}
```

---

## 八、配置参数

### 8.1 相关配置项

**文件：** [backend/app/config.py](file:///d%3A/agent1/backend/app/config.py)（假设路径）

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `qdrant_url` | `http://localhost:6333` | Qdrant 服务地址 |
| `qdrant_collection` | `travel_rag` | 集合名称 |
| `embedding_model_name` | `all-MiniLM-L6-v2` | Embedding 模型 |
| `rag_top_k` | `5` | 默认返回条数 |

### 8.2 超参数

**`search_or_fetch` 中的 `min_score=0.75`：**
- 含义：缓存命中的最小 Cosine 相似度阈值
- 调高：更依赖外部搜索，缓存命中率降低，但准确性高
- 调低：更多使用缓存，速度更快，但可能返回不相关内容

---

## 九、完整调用时序

以用户搜索"湛江 赤坎老街"为例：

```
时间轴 ──────────────────────────────────────────────────────────►

Agent              RAGService         Qdrant           BaikeService
  │                  │                  │                   │
  │  batch_search_or_fetch("赤坎老街", "湛江") │                   │
  │─────────────────>│                  │                   │
  │                  │                  │                   │
  │                  │  search("赤坎老街", city="湛江")       │
  │                  │─────────────────>│                   │
  │                  │                  │                   │
  │                  │  返回 top_k 结果  │                   │
  │                  │<─────────────────│                   │
  │                  │                  │                   │
  │                  │  判断 score < 0.75 │                   │
  │                  │  决定外部搜索      │                   │
  │                  │                  │                   │
  │                  │  baike.search("赤坎老街", "湛江")      │
  │                  │──────────────────────────────────────>│
  │                  │                  │                   │
  │                  │                  │                   │ 搜索百度百科
  │                  │                  │                   │ 解析摘要
  │                  │                  │                   │
  │                  │  返回 {summary, url}                 │
  │                  │<──────────────────────────────────────│
  │                  │                  │                   │
  │                  │  add_documents({title, content, city}) │
  │                  │─────────────────>│                   │
  │                  │                  │ 写入向量库         │
  │                  │<─────────────────│                   │
  │                  │                  │                   │
  │  返回结果 {content, from_cache=False} │                  │
  │<─────────────────│                  │                   │
  │                  │                  │                   │

第二次搜索同一景点：
  │  batch_search_or_fetch("赤坎老街", "湛江") │               │
  │─────────────────>│                  │                   │
  │                  │  search(...)     │                   │
  │                  │─────────────────>│                   │
  │                  │  score >= 0.75   │                   │
  │                  │<─────────────────│                   │
  │  返回 {content, from_cache=True}    │                   │
  │<─────────────────│                  │                   │
```

---

## 十、与 LLM 的协作方式

### 10.1 RAG 上下文如何进入 PlannerAgent

当前实现中，RAG 主要在 `AttractionAgent` 阶段发挥作用：

1. `AttractionAgent` 为每个景点获取背景知识
2. 将背景知识写入景点的 `description` 字段
3. `PlannerAgent` 看到带有丰富描述的候选景点列表
4. LLM 基于这些真实信息生成行程

**优点：**
- 实现简单，不增加 PlannerAgent 的上下文长度
- 每个景点自带背景，LLM 直接使用

**未来改进：**
- 可在 `PLANNER_HUMAN_TEMPLATE` 中增加独立的 `【城市攻略背景】` 段落
- 由 `RAGAgent` 单独检索城市级攻略，供 PlannerAgent 参考

---

## 十一、当前局限与改进方向

### 11.1 当前局限

下面这些"坑"是实际开发中真的遇到的——不是说理论上有问题，而是说本地开发时**几乎必然会触发**，需要知道怎么绕过去：

1. **百度百科稳定性**：依赖网页结构，若百度改版需要更新解析规则。
   - **通俗解释**：我们的爬虫用 CSS 选择器（`class="lemma-summary"`）去取摘要，一旦百度改版，这些选择器就失效了，得手动修。
2. **图片缺失**：百度百科的摘要不含图片，景点图片仍依赖高德 POI。
   - **通俗解释**：RAG 只能补文字描述，景点图片还得走另一条路（高德 POI 的 photo 字段）。
3. **来源单一**：目前只用百度百科，可扩展马蜂窝、携程等。
   - **通俗解释**：知识库"营养单一"，理想情况应该接多个数据源做交叉验证。
4. **city 过滤**：向量库按城市过滤，但同一景点跨城市可能重复存储。
   - **通俗解释**："北京路"这种常见名字可能在多个城市都有词条，目前按城市过滤会漏掉其他城市的同名词条。

5. **torch DLL 加载失败**（本地开发常见）★**真实遇到过**
   - **现象**：每次启动后端日志都会出现 `Error loading ... torch\lib\c10.dll` 错误
   - **原因**：sentence-transformers 依赖 torch，BGE Embedding 模型需要 torch 才能把文字转成向量
   - **后果**：BGE 模型加载失败，**RAG 实际回退到"仅依赖百度百科原文"**——直接用拿到的网页摘要，不经过向量编码
   - **影响**：**功能仍然能用**（因为有百度百科兜底），但失去了"语义检索"能力（向量相似度匹配变成关键词匹配）
   - **绕开方法**：在 `rag_service.py` 里加 try/except，加载失败就只用 `baike_service` 返回的原文

6. **Qdrant 未启动**（本地开发常见）★**真实遇到过**
   - **现象**：如果 Qdrant 容器没起，会出现 `[WinError 10061] 由于目标计算机积极拒绝，无法连接`
   - **原因**：Qdrant 是另一个服务（用 Docker 启动的），不是 Python 包，所以 `pip install` 不会自动起
   - **后果**：RAG 自动回退到**纯内存模式**——进程内字典缓存（重启后丢失）
   - **影响**：**系统仍可工作**，但失去跨重启复用（重启后所有缓存失效，又得重新爬百度百科）
   - **绕开方法**：`RAGService.__init__` 里加连接失败捕获，失败就置为 `_use_memory_mode=True`，所有读写走内存字典

### 11.2 改进方向

1. **多数据源融合**
   - 百度百科：历史背景
   - 马蜂窝/携程：游玩攻略、开放时间
   - 大众点评：美食推荐

2. **酒店/美食 RAG**
   - 为酒店补充周边设施、交通便利性
   - 为餐饮补充特色菜、人均消费

3. **用户偏好学习**
   - 记录用户点赞/收藏的景点
   - 根据偏好调整检索排序

4. **检索增强**
   - 引入重排序模型（Reranker）
   - 混合检索：向量检索 + 关键词检索

5. **环境加固**（**解决上面局限 5、6**）
   - 修复 torch DLL 加载问题：安装 Visual C++ Redistributable 2015-2022 + 升级 torch 2.x CPU 版
   - Docker Compose 一键起 Qdrant（目前 docker-compose.yml 还未创建）
   - 加 Qdrant 健康检查 + 自动重连

### 11.3 已实施的鲁棒性策略

虽然有上述局限，代码里已经做了**优雅降级**，保证核心功能可用：

| 异常情况 | 代码处理 | 用户感知 |
|----------|----------|----------|
| torch 加载失败 | `try: self.embedding_model = SentenceTransformer(...) except: self.embedding_mode = "fallback"` | 完全无感，RAG 仍能用 |
| Qdrant 连接失败 | `try: self.client = QdrantClient(...) except: self._memory_mode = True` | 完全无感，重启后缓存失效 |
| 百度百科返回空 | 兜底返回 `{"content": "", "title": query, "score": 0.0}` | 景点 description 为空，但行程仍生成 |
| 外部搜索超时 | 30 秒超时，失败就用缓存或空结果 | 单个景点没背景，其他景点不受影响 |

**设计原则**：**RAG 是"锦上添花"而非"雪中送炭"**——核心行程生成（高德 POI + LLM）不依赖 RAG，RAG 只是让描述更丰富。

---
## 十二、相关文件清单

| 文件 | 作用 |
|------|------|
| `backend/app/services/rag_service.py` | RAG 核心服务，向量检索 + 外部搜索联动 |
| `backend/app/services/baike_service.py` | 百度百科外部搜索服务 |
| `backend/app/agents/nodes.py` | AttractionAgent、PlannerAgent 调用 RAG |
| `backend/app/agents/prompts.py` | PlannerAgent 提示词 |
| `backend/app/models/schemas.py` | Attraction 等数据模型 |
| `backend/app/config.py` | Qdrant、Embedding 模型配置 |
| `docs/项目改进计划.md` | 项目改进记录 |
| `docs/问题排查记录.md` | 问题排查记录（含 RAG 相关问题） |

### 12.1 关联数据表（用于跨重启持久化）

虽然 RAG 主用 Qdrant，但**用户偏好和反馈**有独立的持久化路径：

| 表 | 用途 | 关键字段 |
|---|---|---|
| `user_preferences` | 用户结构化偏好 | `food_taste`, `price_sensitivity`, `travel_pace` 等 |
| `user_memories` | 用户事件级记忆 | `event_type` (feedback/preference/visit), `payload` JSON |
| `plan_revisions` | 行程历史版本 | `trip_plan_json`, `diff_summary`, `source` (initial/full/patch) |
| `plan_feedbacks` | 用户对行程的反馈 | `raw_text`, `tags`, `structured_feedback`, `is_withdrawn` |

详细见 [项目结构与实现说明.md](file:///d:/agent1/docs/项目结构与实现说明.md) 第三章「数据模型」。

---

## 十三、总结

本项目的 RAG 架构是一个**轻量级、搜索优先、渐进积累**的知识增强系统：

- **不预存海量数据**，而是根据用户查询实时检索
- **优先使用缓存**，相同查询第二次直接命中
- **外部搜索自动入库**，知识库随使用自动增长
- **与 Agent 工作流深度集成**，为景点生成真实、丰富的背景描述

这个架构的优点是**维护成本低、数据新鲜、实现简单**，适合从 0 到 1 快速搭建旅行规划的 RAG 能力。

---

## 十四、一图看懂 RAG 调用全流程

下面这张图把"用户提问 → RAG 检索 → 返回内容"完整串起来，可以作为调试 RAG 时的参考图：

```
┌────────────────────────────────────────────────────────────────────┐
│                        RAG 调用全流程                                │
└────────────────────────────────────────────────────────────────────┘

  AttractionAgent 节点
       │
       │ 拿到 5~10 个景点名，比如 ["赤坎老街", "金沙湾", ...]
       │
       ▼
  rag.batch_search_or_fetch(queries, city="湛江")
       │
       │  并发 5~10 次 asyncio.gather
       ▼
  ┌──────────────────────────────────────────────────────────────┐
  │                search_or_fetch("赤坎老街")                    │
  │                                                              │
  │  ┌─ Step 1: search() 查本地缓存 ───────────────────────────┐ │
  │  │   - 如果 Qdrant 启动：转 query 为向量，搜 Top-K         │ │
  │  │   - 如果 Qdrant 没起：搜内存字典（重启会丢）             │ │
  │  └─────────────────────────────┬────────────────────────────┘ │
  │                                │                              │
  │              ┌─────────────────┴─────────────────┐            │
  │              ▼                                   ▼            │
  │     score >= 0.75                         score < 0.75       │
  │     命中缓存 ✅                            缓存未命中 ❌        │
  │              │                                   │            │
  │              │                                   ▼            │
  │              │                    ┌──────────────────────────┐│
  │              │                    │ Step 2: baike.search()  ││
  │              │                    │ - 搜 baike.baidu.com     ││
  │              │                    │ - 解析 result-title      ││
  │              │                    │ - 进词条详情页           ││
  │              │                    │ - 抽 lemma-summary       ││
  │              │                    └─────────────┬────────────┘│
  │              │                                  │             │
  │              │                                  ▼             │
  │              │                    ┌──────────────────────────┐│
  │              │                    │ Step 3: add_documents()  ││
  │              │                    │ - 切分文本               ││
  │              │                    │ - 如果 torch 可用: 编码   ││
  │              │                    │   → 入 Qdrant            ││
  │              │                    │ - 如果 torch 失败:       ││
  │              │                    │   → 入内存字典            ││
  │              │                    └─────────────┬────────────┘│
  │              │                                  │             │
  │              ▼                                  ▼             │
  │       ┌──────────────────────────────────────────────┐        │
  │       │   返回结果：{title, content, score,           │        │
  │       │             from_cache, source_type, url}     │        │
  │       └──────────────────────────────────────────────┘        │
  └──────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
  AttractionAgent 把结果塞到 attraction.description
                                  │
                                  ▼
  PlannerAgent 看到带背景的景点列表，LLM 生成行程
```

---

## 十五、阅读路线建议

- **只想了解"是什么"**：看零、一、十三节（一分钟读懂）
- **想了解"怎么调"**：看二、三、四、六节（架构 + 流程）
- **想了解"代码在哪"**：看十二节（文件清单）
- **踩到坑了/想 debug**：看十一节（局限 + 鲁棒性）
