"""
backend/app/agents/tools.py

【模块作用】
Agent 可调用的工具函数模块。

这是 Agent 节点的"手"，负责真正去调外部服务：
- 高德地图：搜索景点、酒店、天气、路线
- Qdrant 向量库：检索城市攻略

Agent 节点本身不直接调 API，而是调用这里的工具函数。
这样设计的好处是：今天用高德，明天想换百度地图，只需要改服务层，节点和工具都不用动。

【核心概念】
- 工具函数：封装外部服务调用的函数，Agent 节点按需使用
- 服务层：AmapService、RAGService，真正去调 REST API 或向量库

【对应技术】
- AmapService：高德地图 REST API 封装
- RAGService：向量检索
"""

import math
from typing import Any

from app.services.amap_service import AmapService


async def search_attractions(
    city: str, keyword: str = "景点", page_size: int = 10
) -> list[dict[str, Any]]:
    """
    【函数作用】根据关键词和城市搜索景点 POI。

    这是 AttractionAgent 节点调用的主要工具，用于获取真实景点数据。

    【参数】
    - city：目标城市，如"湛江"
    - keyword：搜索关键词，如"景点"、"博物馆"、"公园"
    - page_size：返回结果数量，最大 25

    【返回值】
    - List[Dict[str, Any]]：景点列表，每个景点是字典，包含：
      - id：高德 POI ID
      - name：景点名称
      - location：{"longitude": 经度, "latitude": 纬度}
      - address：地址
      - type：类型（如"风景名胜;风景名胜")
      - rating：评分（如果有）
      - tags：推断的标签（如["风景", "观光"]）
      - duration：建议游玩时长（如"2.5 小时"）
      - description：简介

    【核心步骤】
    1. 创建 AmapService 实例
    2. 调用 search_poi 方法，请求高德 API
    3. 对每个 POI 调用 _enrich_attraction，补充默认字段（标签、时长等）
    4. 返回增强后的景点列表
    """
    # 步骤 1：创建高德服务实例
    # AmapService 内部会用 httpx 异步请求高德 REST API
    service = AmapService()

    # 步骤 2：调用 search_poi 方法
    # 这会请求 https://restapi.amap.com/v3/place/text
    pois = await service.search_poi(keyword, city, page_size)

    # 步骤 3：为每个 POI 补充默认字段
    # _enrich_attraction 会根据 POI 类型推断标签和游玩时长
    return [_enrich_attraction(poi) for poi in pois]


async def search_hotels(
    city: str, keyword: str = "酒店", page_size: int = 6
) -> list[dict[str, Any]]:
    """
    【函数作用】根据城市搜索酒店 POI。

    这是 HotelAgent 节点调用的主要工具，用于获取真实酒店数据。

    【参数】
    - city：目标城市
    - keyword：搜索关键词，如"酒店"、"民宿"
    - page_size：返回结果数量

    【返回值】
    - List[Dict[str, Any]]：酒店列表，每个酒店是字典，包含：
      - id、name、location、address
      - price_per_night：预估每晚价格（根据名称关键词推断）

    【核心步骤】
    1. 调用 search_poi 搜索酒店
    2. 为每个 POI 调用 _enrich_hotel，补充价格估算
    """
    service = AmapService()
    pois = await service.search_poi(keyword, city, page_size)
    return [_enrich_hotel(poi) for poi in pois]


async def search_restaurants(
    city: str, keyword: str = "餐厅", page_size: int = 15
) -> list[dict[str, Any]]:
    """
    【函数作用】根据城市搜索真实餐厅 POI。

    这是 FoodAgent 节点调用的主要工具，用于获取带照片、评分、地址的真实店铺。

    【参数】
    - city：目标城市
    - keyword：搜索关键词，如"餐厅"、"美食"、"海鲜"
    - page_size：返回结果数量，最大 25

    【返回值】
    - List[Dict[str, Any]]：餐厅列表，每个餐厅包含：
      - id、name、location、address
      - rating：评分
      - image_url、photos：图片
      - phone：电话
      - business_hours：营业时间
      - estimated_cost：根据名称关键词粗略估算的人均消费
      - detail_url：高德详情页链接
    """
    service = AmapService()
    # 050000 为高德 POI 餐饮服务大类
    pois = await service.search_poi(keyword, city, page_size, poi_type="050000")
    return [_enrich_restaurant(poi) for poi in pois]


async def get_weather(city: str) -> dict[str, Any]:
    """
    【函数作用】查询指定城市的天气信息。

    这是 WeatherAgent 节点调用的主要工具，用于获取旅行期间天气。

    【参数】
    - city：城市名称

    【返回值】
    - Dict[str, Any]：天气信息，结构如下：
      {
        "city": "湛江市",
        "adcode": "440800",
        "report_time": "2026-07-12 10:00:00",
        "forecasts": [
          {
            "date": "2026-07-12",
            "week": "7",
            "day_weather": "雷阵雨",
            "night_weather": "多云",
            "day_temp": "33",
            "night_temp": "26",
            "day_wind": "北",
            "night_wind": "北",
            "day_power": "1-3",
            "night_power": "1-3"
          },
          ...
        ]
      }

    【核心步骤】
    1. 创建 AmapService 实例
    2. 调用 get_weather 方法，请求高德天气接口
    3. 返回天气预报数据
    """
    service = AmapService()
    # forecast=True 表示获取未来几天预报，而不是当前实况
    return await service.get_weather(city, forecast=True)


async def plan_route(origin: str, destination: str, mode: str = "driving") -> dict[str, Any]:
    """
    【函数作用】规划从起点到终点的路线。

    这是 RouteAgent 节点调用的主要工具，用于计算景点间距离和通行时间。

    【参数】
    - origin：起点坐标，格式 "经度,纬度"（如"110.3595,21.2707"）
    - destination：终点坐标，格式同上
    - mode：交通方式，可选：
      - driving：驾车
      - transit：公交（需要 key 有对应权限）
      - walking：步行
      - riding：骑行

    【返回值】
    - Dict[str, Any]：路线信息，包含：
      - origin、destination、mode
      - distance：距离（米）
      - duration：预计时间（秒）
      - tolls：过路费（仅驾车，单位元）
      - polyline：路线坐标点列表
      - steps：导航步骤列表

    【核心步骤】
    1. 创建 AmapService 实例
    2. 调用 plan_route 方法，请求高德路线规划接口
    3. 返回路线数据
    """
    service = AmapService()
    return await service.plan_route(origin, destination, mode)


def search_rag_context(query: str, city: str | None = None, top_k: int = 5) -> str:
    """
    【函数作用】从 RAG 知识库检索城市攻略或景点背景。

    这是 RAGAgent 节点调用的主要工具，用于获取额外背景知识。
    当前知识库可能为空，返回空字符串。

    【参数】
    - query：查询文本，如"湛江旅游攻略 美食 海滩"
    - city：可选城市过滤
    - top_k：返回文档片段数量

    【返回值】
    - str：拼接后的上下文文本，格式：
      [1] 湛江旅游攻略: 湛江位于广东省西南部...
      ---
      [2] 湛江美食推荐: 湛江海鲜丰富，推荐...
    - 如果检索失败或无结果，返回空字符串

    【核心步骤】
    1. 创建 RAGService 实例
    2. 调用 search 方法，用 query 向量检索
    3. 将结果拼接成文本返回
    """
    try:
        # 使用全局单例：避免每次调用都新建 Qdrant 连接（远程不可用时白等 3 秒超时），
        # 同时保证内存模式下的缓存可以跨调用复用
        from app.services.rag_service import get_rag_service

        service = get_rag_service()
        # search 方法会用 SentenceTransformer 把 query 编码成向量
        # 然后在 Qdrant 中检索最相似的 top_k 个文档片段
        results = service.search(query=query, city=city, top_k=top_k)

        if not results:
            return ""

        # 将多个文档片段拼接成一段文本
        # 用 --- 分隔，方便 LLM 区分不同来源
        return "\n---\n".join(
            f"[{i + 1}] {r.get('title', '')}: {r.get('content', '')}" for i, r in enumerate(results)
        )
    except Exception:
        # 检索失败时返回空字符串，不影响主流程
        return ""


def haversine_distance(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """
    【函数作用】使用 Haversine 公式计算两点间直线距离（米）。

    这是 RouteAgent 在高德路线规划失败时的备选方案，用于估算景点间距离。

    【参数】
    - lon1：起点经度
    - lat1：起点纬度
    - lon2：终点经度
    - lat2：终点纬度

    【返回值】
    - float：两点间距离，单位米

    【核心公式】
    Haversine 公式考虑了地球曲率，适合计算经纬度之间的直线距离：
    a = sin²(Δφ/2) + cos(φ1)·cos(φ2)·sin²(Δλ/2)
    c = 2·atan2(√a, √(1−a))
    d = R · c

    其中：
    - φ1, φ2 是两点的纬度（弧度）
    - Δφ, Δλ 是纬度差和经度差
    - R 是地球半径（约 6371km）
    """
    # 地球平均半径（米）
    radius = 6371000

    # 将角度转换为弧度
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    # Haversine 公式
    a = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return radius * c


# ==================== POI 字段增强函数 ====================
# 这些函数用于为高德 POI 补充默认字段
# 因为高德 API 不直接提供建议游玩时长、门票价格、酒店价格等信息


def _enrich_attraction(poi: dict[str, Any]) -> dict[str, Any]:
    """
    【函数作用】为高德 POI 补充景点相关默认字段。

    高德 POI 返回的数据不包含：
    - 建议游玩时长
    - 门票价格
    - 标签（美食/购物/文化等）

    这个函数根据 POI 类型编码（typecode）推断这些字段，
    供 PlannerAgent 参考。LLM 可在后续规划中根据真实名称进一步修正。

    【参数】
    - poi：高德返回的 POI 字典

    【返回值】
    - 增强后的 POI 字典，新增 tags、duration、description 字段
    """
    # 获取 POI 类型编码，如 "110100" 表示公园
    typecode = poi.get("typecode", "")
    name = poi.get("name", "")

    # 根据 POI 类型编码推断标签和游玩时长
    # 高德 POI 类型编码参考：https://lbs.amap.com/api/webservice/guide/api/search

    if typecode.startswith("110000"):  # 110000-110999：风景名胜
        tags = ["风景", "观光"]
        duration = "2.5 小时"
    elif typecode.startswith("110100"):  # 110100-110199：公园
        tags = ["公园", "休闲"]
        duration = "2 小时"
    elif typecode.startswith("140000") or "博物馆" in name:  # 140000：科教文化服务
        tags = ["文化", "博物馆"]
        duration = "2.5 小时"
    elif typecode.startswith("060000") or "商场" in name or "购物" in name:  # 060000：购物服务
        tags = ["购物", "休闲"]
        duration = "1.5 小时"
    elif typecode.startswith("050000") or "美食" in name or "街" in name:  # 050000：餐饮服务
        tags = ["美食", "街拍"]
        duration = "1.5 小时"
    else:
        # 默认标签
        tags = ["观光"]
        duration = "2 小时"

    # 构造高德详情页搜索链接
    # 使用高德地图搜索链接，前端点击后可查看 POI 详情
    detail_url = f"https://ditu.amap.com/search?query={name}"

    # 返回增强后的 POI
    # **poi 保留原有所有字段，然后添加新字段
    return {
        **poi,
        "tags": tags,
        "duration": duration,
        "description": f"{name} 是 {poi.get('type', '当地')} 的热门地点，地址：{poi.get('address') or '详见地图'}。",
        "detail_url": detail_url,
        "phone": poi.get("tel"),
        "business_hours": poi.get("business_hours"),
    }


def _enrich_hotel(poi: dict[str, Any]) -> dict[str, Any]:
    """
    【函数作用】为高德 POI 补充酒店相关默认字段。

    高德 POI 不直接提供每晚价格。
    这个函数根据酒店名称关键词做粗略区间估计，供预算计算参考。
    实际价格应以预订平台（携程、美团）为准。

    【参数】
    - poi：高德返回的酒店 POI 字典

    【返回值】
    - 增强后的 POI 字典，新增 price_per_night 字段
    """
    name = poi.get("name", "")

    # 根据酒店名称关键词估算每晚价格
    # 这是一个粗略估算，实际价格差异可能很大

    # 五星级/高端酒店
    if any(k in name for k in ["五星", "希尔顿", "万豪", "喜来登", "洲际", "香格里拉"]):
        price_per_night = 800.0
    # 四星级/中高端连锁
    elif any(k in name for k in ["四星", "全季", "亚朵", "桔子", "麗枫", "维也纳"]):
        price_per_night = 400.0
    # 三星级/经济型连锁
    elif any(k in name for k in ["三星", "如家", "汉庭", "7天", "锦江", "格林"]):
        price_per_night = 220.0
    # 民宿/客栈
    elif "民宿" in name or "客栈" in name:
        price_per_night = 180.0
    # 其他：默认中档
    else:
        price_per_night = 350.0

    # 构造高德详情页搜索链接
    detail_url = f"https://ditu.amap.com/search?query={name}"

    return {
        **poi,
        "price_per_night": price_per_night,
        "description": f"{name} 是 {poi.get('type', '当地')} 的住宿选择，地址：{poi.get('address') or '详见地图'}。",
        "detail_url": detail_url,
        "phone": poi.get("tel"),
        "business_hours": poi.get("business_hours"),
    }


def _enrich_restaurant(poi: dict[str, Any]) -> dict[str, Any]:
    """
    【函数作用】为高德 POI 补充餐厅相关字段。

    高德 POI 不直接提供人均消费，本函数根据餐厅名称关键词做粗略估算，
    供预算计算参考。实际价格请以店铺现场菜单为准。
    """
    name = poi.get("name", "")
    detail_url = f"https://ditu.amap.com/search?query={name}"

    return {
        **poi,
        "estimated_cost": _estimate_meal_cost(name),
        "detail_url": detail_url,
        "phone": poi.get("tel"),
        "business_hours": poi.get("business_hours"),
        "address": poi.get("address") or None,
    }


def _estimate_meal_cost(name: str) -> float:
    """
    【函数作用】根据餐厅名称关键词粗略估算人均消费。

    仅用于预算参考，不代表真实价格。
    """
    name = name or ""
    # 高端餐饮/酒楼/海鲜
    if any(k in name for k in ["海鲜", "酒楼", "饭店", "酒家", "烧烤", "火锅", "日料", "西餐"]):
        return 100.0
    # 快餐/小吃
    if any(k in name for k in ["肯德基", "麦当劳", "快餐", "小吃", "粉", "面", "粥"]):
        return 35.0
    # 咖啡/甜品/奶茶
    if any(k in name for k in ["咖啡", "甜品", "奶茶", "蛋糕", "面包"]):
        return 30.0
    # 默认中档
    return 60.0
