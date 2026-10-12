"""
backend/app/services/amap_service.py

高德地图服务封装模块。

作用：
- 直接调用高德地图 REST API（非 MCP），获取真实 POI、天气、路线数据；
- 为 Agent 工具层提供可复用的异步方法；
- 所有返回数据均来自高德官方接口，不再使用模拟数据。

对应技术：
- httpx：异步 HTTP 客户端
- 高德地图 Web 服务 API：
  - 地点搜索 /v3/place/text
  - 天气查询 /v3/weather/weatherInfo
  - 路径规划 /v3/direction/{driving|walking|transit|riding}
"""

from typing import Any, Dict, List, Optional

import httpx

from app.config import settings


class AmapService:
    """
    高德地图服务类。

    通过官方 REST API 接入真实地图数据。
    """

    BASE_URL = "https://restapi.amap.com/v3"

    def __init__(self):
        """
        初始化高德地图服务。

        检查必要配置（AMAP_API_KEY）是否已设置。
        """
        if not settings.amap_api_key:
            raise ValueError("未配置 AMAP_API_KEY，请在 .env 文件中设置")

    async def _get(self, path: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        发送 GET 请求到高德 API。

        Args:
            path: API 路径（不含 BASE_URL）。
            params: 查询参数。

        Returns:
            Dict[str, Any]: 高德返回的 JSON 数据。

        Raises:
            RuntimeError: 请求失败或高德返回错误码时抛出。
        """
        url = f"{self.BASE_URL}{path}"
        request_params = {"key": settings.amap_api_key, "output": "JSON", **params}

        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(url, params=request_params)
            response.raise_for_status()
            data = response.json()

        status = data.get("status")
        info = data.get("info", "未知错误")
        if status != "1":
            raise RuntimeError(f"高德 API 返回错误：{info}")

        return data

    async def search_poi(
        self, keyword: str, city: str, page_size: int = 10, poi_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        根据关键词和城市搜索 POI（兴趣点）。

        Args:
            keyword: 搜索关键词，如"故宫"。
            city: 城市名称，如"北京"。
            page_size: 返回结果数量，最大 25。
            poi_type: POI 类型编码，可选。

        Returns:
            List[Dict[str, Any]]: POI 列表，每个 POI 包含 id、名称、地址、经纬度、类型等。
        """
        params = {
            "keywords": keyword,
            "city": city,
            "offset": min(page_size, 25),
            "page": 1,
            "citylimit": "true",
            "extensions": "all",
        }
        if poi_type:
            params["types"] = poi_type

        data = await self._get("/place/text", params)
        pois = data.get("pois", []) or []

        results = []
        for poi in pois:
            location_str = poi.get("location", ",")
            longitude, latitude = self._parse_location(location_str)

            # 解析图片列表，高德返回的 photos 可能是 [{"url": "..."}] 或字符串列表
            photos = self._parse_photos(poi.get("photos", []))

            results.append(
                {
                    "id": poi.get("id"),
                    "name": poi.get("name", "").strip(),
                    "address": poi.get("address", "").strip() or None,
                    "location": {
                        "longitude": longitude,
                        "latitude": latitude,
                    },
                    "type": poi.get("type", ""),
                    "typecode": poi.get("typecode", ""),
                    "tel": self._parse_tel(poi.get("tel")),
                    "rating": self._parse_rating(poi.get("biz_ext", {}).get("rating")),
                    "business_hours": poi.get("business_area") or None,
                    "photos": photos,
                    "image_url": photos[0] if photos else None,
                }
            )

        return results

    async def get_weather(self, city: str, forecast: bool = True) -> Dict[str, Any]:
        """
        查询指定城市的天气信息。

        Args:
            city: 城市名称或 adcode。
            forecast: 是否返回未来几天预报，True 返回 forecasts，False 返回实况。

        Returns:
            Dict[str, Any]: 天气信息，包含城市、天气、温度、风力等。
        """
        params = {
            "city": city,
            "extensions": "all" if forecast else "base",
        }
        data = await self._get("/weather/weatherInfo", params)

        if forecast:
            forecasts = data.get("forecasts", [])
            if not forecasts:
                raise RuntimeError("高德天气接口未返回预报数据")
            cast = forecasts[0]
            casts = cast.get("casts", [])
            return {
                "city": cast.get("city", city),
                "adcode": cast.get("adcode", ""),
                "report_time": cast.get("reporttime", ""),
                "forecasts": [
                    {
                        "date": c.get("date"),
                        "week": c.get("week"),
                        "day_weather": c.get("dayweather"),
                        "night_weather": c.get("nightweather"),
                        "day_temp": c.get("daytemp"),
                        "night_temp": c.get("nighttemp"),
                        "day_wind": c.get("daywind"),
                        "night_wind": c.get("nightwind"),
                        "day_power": c.get("daypower"),
                        "night_power": c.get("nightpower"),
                    }
                    for c in casts
                ],
            }

        lives = data.get("lives", [])
        if not lives:
            raise RuntimeError("高德天气接口未返回实况数据")
        live = lives[0]
        return {
            "city": live.get("city", city),
            "adcode": live.get("adcode", ""),
            "weather": live.get("weather", ""),
            "temperature": live.get("temperature", ""),
            "winddirection": live.get("winddirection", ""),
            "windpower": live.get("windpower", ""),
            "humidity": live.get("humidity", ""),
            "report_time": live.get("reporttime", ""),
        }

    async def plan_route(
        self, origin: str, destination: str, mode: str = "driving"
    ) -> Dict[str, Any]:
        """
        规划从起点到终点的路线。

        Args:
            origin: 起点坐标，格式 "经度,纬度"（高德标准）。
            destination: 终点坐标，格式 "经度,纬度"。
            mode: 交通方式，可选 driving/transit/walking/riding。

        Returns:
            Dict[str, Any]: 路线信息，包含距离（米）、时间（秒）、路径等。
        """
        mode = mode.lower()
        if mode not in {"driving", "transit", "walking", "riding"}:
            mode = "driving"

        params = {
            "origin": origin,
            "destination": destination,
        }

        if mode == "transit":
            path = "/direction/transit/integrated"
        else:
            path = f"/direction/{mode}"

        data = await self._get(path, params)
        route = data.get("route", {})
        paths = route.get("paths", [])

        if not paths:
            raise RuntimeError("高德路线规划接口未返回可行路径")

        best = paths[0]
        return {
            "origin": origin,
            "destination": destination,
            "mode": mode,
            "distance": int(best.get("distance", 0)),
            "duration": int(best.get("duration", 0)),
            "tolls": int(best.get("tolls", 0)) if mode == "driving" else 0,
            "polyline": self._decode_polyline(best.get("steps", [])),
            "steps": [
                {
                    "instruction": step.get("instruction", ""),
                    "distance": step.get("distance", ""),
                    "duration": step.get("duration", ""),
                    "road": step.get("road", ""),
                }
                for step in best.get("steps", [])
            ],
        }

    @staticmethod
    def _parse_location(location: str) -> tuple:
        """
        解析高德 location 字符串为 (经度, 纬度)。

        Args:
            location: "经度,纬度" 字符串。

        Returns:
            tuple: (longitude, latitude)，解析失败返回 (0.0, 0.0)。
        """
        if not location or "," not in location:
            return 0.0, 0.0
        try:
            lon, lat = location.split(",")
            return float(lon.strip()), float(lat.strip())
        except ValueError:
            return 0.0, 0.0

    @staticmethod
    def _parse_tel(value: Any) -> Optional[str]:
        """
        解析电话字段为字符串。

        高德 POI 的 tel 有时是字符串，有时是列表（如多个电话）。

        Args:
            value: 原始电话值。

        Returns:
            Optional[str]: 解析后的电话号码，失败返回 None。
        """
        if value is None or value == "":
            return None
        if isinstance(value, list):
            value = value[0] if value else None
        if value is None:
            return None
        return str(value).strip() or None

    @staticmethod
    def _parse_rating(value: Any) -> Optional[float]:
        """
        解析评分字符串为浮点数。

        Args:
            value: 原始评分值。

        Returns:
            Optional[float]: 解析后的评分，失败返回 None。
        """
        if value is None or value == "":
            return None
        try:
            return float(value)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _parse_photos(photos: Any) -> List[str]:
        """
        解析高德 POI 返回的图片字段为 URL 列表。

        Args:
            photos: 原始图片数据，可能是字符串列表或 [{"url": "..."}] 列表。

        Returns:
            List[str]: 图片 URL 列表。
        """
        if not photos:
            return []
        result = []
        for item in photos:
            if isinstance(item, str):
                result.append(item)
            elif isinstance(item, dict):
                url = item.get("url")
                if url:
                    result.append(url)
        return result

    @staticmethod
    def _decode_polyline(steps: List[Dict[str, Any]]) -> List[Dict[str, float]]:
        """
        将高德路径 steps 中的 polyline 解码为坐标点列表。

        Args:
            steps: 高德返回的 steps 数组。

        Returns:
            List[Dict[str, float]]: 经纬度点列表。
        """
        points = []
        for step in steps:
            polyline = step.get("polyline", "")
            if not polyline:
                continue
            for segment in polyline.split(";"):
                if "," not in segment:
                    continue
                lon, lat = segment.split(",")
                try:
                    points.append({"longitude": float(lon), "latitude": float(lat)})
                except ValueError:
                    continue
        return points
