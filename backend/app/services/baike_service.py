"""
backend/app/services/baike_service.py

外部知识搜索服务模块。

作用：
- 为景点、酒店等提供真实背景知识补充；
- 聚合多个数据源：百度百科（优先）、必应搜索摘要（兜底）；
- 支持缓存，避免重复请求；
- 不缓存"未找到"结果。

对应技术：
- httpx：异步 HTTP 请求（与 AmapService 统一，避免引入 aiohttp 额外依赖）
- BeautifulSoup：HTML 解析
- urllib.parse：URL 编码
"""

import asyncio
import hashlib
import re
from typing import Any
from urllib.parse import quote

import httpx
from bs4 import BeautifulSoup
from loguru import logger


class BaikeService:
    """
    外部知识搜索服务。

    由于百度百科存在反爬和访问频率限制，本服务采用多源策略：
    1. 百度百科：直接构造词条 URL，内容最权威（但可能触发反爬）
    2. 必应搜索摘要：通过 cn.bing.com 搜索，返回前几条结果的标题和摘要

    不需要 API Key。
    """

    # 百度百科词条详情页 URL 模板
    BAIDU_ITEM_URL = "https://baike.baidu.com/item/{title}"
    # 必应搜索 URL 模板
    BING_SEARCH_URL = "https://cn.bing.com/search"

    # 请求超时时间（秒）
    TIMEOUT = 15
    # 最大重试次数
    MAX_RETRIES = 2
    # 来源间请求间隔（秒）
    SOURCE_INTERVAL = 0.8

    # 请求头，模拟浏览器访问
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }

    def __init__(self):
        """初始化服务，创建延迟会话和内存缓存。"""
        self._cache: dict[str, dict[str, Any]] = {}
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """获取或创建 httpx 异步客户端（follow_redirects 对齐 aiohttp GET 默认行为）。"""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                headers=self.HEADERS, timeout=self.TIMEOUT, follow_redirects=True
            )
        return self._client

    async def close(self) -> None:
        """关闭 HTTP 会话。"""
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    def _cache_key(self, query: str, city: str | None = None) -> str:
        """生成缓存键。"""
        key = f"{city or ''}:{query}"
        return hashlib.md5(key.encode()).hexdigest()

    def _generate_item_name_candidates(self, query: str) -> list[str]:
        """
        生成候选词条名。

        百科词条名通常比 POI 名称更短，例如：
        - "湖光岩风景名胜区" → "湖光岩"
        """
        candidates = [query]

        suffixes = [
            "风景名胜区",
            "风景区",
            "旅游区",
            "旅游度假区",
            "景区",
            "公园",
            "古镇",
            "古城",
            "老街",
            "广场",
            "海滩",
            "湾",
        ]

        for suffix in suffixes:
            if query.endswith(suffix) and len(query) > len(suffix):
                shorter = query[: -len(suffix)]
                if shorter and shorter not in candidates:
                    candidates.append(shorter)

        return [c for c in candidates if c]

    def _is_related(self, query: str, text: str) -> bool:
        """判断文本是否与查询相关。"""
        if not text:
            return False
        query_keywords = [k for k in query.split() if len(k) > 1]
        if not query_keywords:
            query_keywords = [query]
        text_lower = text.lower()
        return any(kw.lower() in text_lower for kw in query_keywords)

    async def search(
        self, query: str, city: str | None = None, use_cache: bool = True
    ) -> dict[str, Any]:
        """
        搜索外部知识并返回摘要。

        Args:
            query: 搜索关键词（如景点名称）。
            city: 城市名（可选）。
            use_cache: 是否使用缓存。

        Returns:
            Dict[str, Any]: 包含 title、summary、url、source_type、from_cache 的字典。
        """
        cache_key = self._cache_key(query, city)
        if use_cache and cache_key in self._cache:
            cached = self._cache[cache_key]
            if not cached.get("summary", "").startswith("未找到"):
                return cached

        result = {
            "title": query,
            "summary": "",
            "url": "",
            "source_type": "unknown",
            "from_cache": False,
        }

        # 策略 1：百度百科
        try:
            baike_item = await self._search_baidu(query, city)
            if baike_item and baike_item.get("summary"):
                result.update(baike_item)
                result["source_type"] = "baidu"
        except Exception as e:
            logger.warning(f"[BaikeService] 百度百科搜索异常: {e}")

        # 策略 2：必应搜索摘要（兜底/补充）
        if not result.get("summary"):
            await asyncio.sleep(self.SOURCE_INTERVAL)
            try:
                bing_item = await self._search_bing(query, city)
                if bing_item and bing_item.get("summary"):
                    result.update(bing_item)
                    result["source_type"] = "bing"
            except Exception as e:
                logger.warning(f"[BaikeService] 必应搜索异常: {e}")

        # 如果全部失败
        if not result.get("summary"):
            result["summary"] = f"未找到 {query} 的外部资料。"

        # 只缓存成功结果
        if use_cache and result.get("summary") and not result["summary"].startswith("未找到"):
            self._cache[cache_key] = result

        return result

    async def _search_baidu(
        self, query: str, city: str | None = None
    ) -> dict[str, Any] | None:
        """通过百度百科搜索词条。"""
        client = await self._get_client()
        candidates = self._generate_item_name_candidates(query)

        for candidate in candidates:
            item_url = self.BAIDU_ITEM_URL.format(title=quote(candidate, safe=""))
            for attempt in range(self.MAX_RETRIES):
                try:
                    response = await client.get(item_url)
                    html = response.text
                    if response.status_code == 200 and "lemma-summary" in html:
                        summary = self._extract_baidu_summary(html)
                        # 校验：摘要中必须出现候选词本身，避免被重定向到城市/行政区划词条
                        if summary and candidate in summary:
                            return {"title": query, "summary": summary, "url": str(response.url)}
                except Exception as e:
                    logger.warning(
                        f"[BaikeService] 百度百科 {candidate} 失败 (尝试 {attempt + 1}): {e}"
                    )
                    await asyncio.sleep(0.5)

        return None

    def _extract_baidu_summary(self, html: str) -> str | None:
        """从百度百科 HTML 提取摘要。"""
        soup = BeautifulSoup(html, "html.parser")
        selectors = [
            ("div", {"class": "lemma-summary"}),
            ("div", {"class": "lemma-summary-container"}),
            ("div", {"class": "main-content"}),
        ]

        for tag, attrs in selectors:
            div = soup.find(tag, attrs)
            if div:
                text = self._clean_text(div.get_text(separator=" ", strip=True))
                if len(text) > 50:
                    return text[:600]

        for para in soup.find_all("div", {"class": "para"}):
            text = self._clean_text(para.get_text(separator=" ", strip=True))
            if len(text) > 50:
                return text[:600]

        return None

    async def _search_bing(
        self, query: str, city: str | None = None
    ) -> dict[str, Any] | None:
        """通过必应搜索获取摘要。"""
        # 构造多个搜索查询变体，提高命中率
        queries = []
        if city:
            # 变体 1：精确匹配 "景点名" 城市
            queries.append(f'"{query}" {city}')
            # 变体 2：城市 + 景点名
            queries.append(f"{city} {query}")
            # 变体 3：景点名 + 城市
            queries.append(f"{query} {city}")
        else:
            queries.append(query)

        async with httpx.AsyncClient(
            headers=self.HEADERS, timeout=self.TIMEOUT, follow_redirects=True
        ) as client:
            for search_query in queries:
                search_url = f"{self.BING_SEARCH_URL}?q={quote(search_query, safe='')}"
                for attempt in range(self.MAX_RETRIES):
                    try:
                        response = await client.get(search_url)
                        if response.status_code != 200:
                            await asyncio.sleep(0.5)
                            continue

                        html = response.text
                        item = self._extract_bing_summary(html, query)
                        if item:
                            return item

                    except Exception as e:
                        logger.warning(f"[BaikeService] 必应搜索失败 (尝试 {attempt + 1}): {e}")
                        await asyncio.sleep(0.5)

                # 变体间稍作间隔
                await asyncio.sleep(0.3)

        return None

    def _extract_bing_summary(self, html: str, query: str) -> dict[str, Any] | None:
        """从必应搜索结果页提取最相关的摘要。"""
        soup = BeautifulSoup(html, "html.parser")
        results = soup.select(".b_algo")[:5]
        logger.info(f"[BaikeService] 必应解析到 {len(results)} 条结果，查询={query}")

        best_item = None
        best_score = 0

        for result in results:
            title_tag = result.find("h2")
            title = title_tag.get_text(strip=True) if title_tag else ""

            caption = result.select_one(".b_caption p")
            if not caption:
                caption = result.find("p")

            summary = caption.get_text(strip=True) if caption else ""
            summary = self._clean_text(summary)

            logger.debug(f"[BaikeService] 必应结果: title={title[:40]}, summary={summary[:60]}")

            if len(summary) < 50:
                continue

            # 相关性评分：标题和摘要中包含查询关键词越多，分数越高
            score = 0
            query_lower = query.lower()
            # 核心词：去除后缀后的最短候选名
            core_keywords = [q for q in self._generate_item_name_candidates(query) if len(q) >= 2]

            for kw in core_keywords:
                if kw.lower() in title.lower():
                    score += 10
                    break
            for kw in core_keywords:
                if kw.lower() in summary.lower():
                    score += 5
                    break

            # 优先选择百科类来源
            if "百科" in title:
                score += 3

            # 只保留确实相关的结果
            if score < 5:
                continue

            if score > best_score:
                best_score = score
                link_tag = title_tag.find("a") if title_tag else None
                url = link_tag["href"] if link_tag and link_tag.get("href") else ""
                best_item = {"title": query, "summary": summary, "url": url}

        return best_item

    def _clean_text(self, text: str) -> str:
        """清理文本中的多余空白和编辑标记。"""
        text = re.sub(r"\s+", " ", text)
        text = text.replace("[编辑]", "").strip()
        return text

    async def batch_search(
        self, queries: list[str], city: str | None = None, use_cache: bool = True
    ) -> list[dict[str, Any]]:
        """批量搜索外部知识。"""
        tasks = [self.search(q, city, use_cache) for q in queries]
        return await asyncio.gather(*tasks)


# 单例模式
_baike_service: BaikeService | None = None


def get_baike_service() -> BaikeService:
    """获取 BaikeService 单例。"""
    global _baike_service
    if _baike_service is None:
        _baike_service = BaikeService()
    return _baike_service
