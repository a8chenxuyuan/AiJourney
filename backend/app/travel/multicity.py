"""travel（领域层）：多城拆分规则。纯领域逻辑，禁止依赖 planning/services/接口层。"""

from datetime import datetime

from app.models.schemas import TripRequest


def split_cities(request: TripRequest) -> tuple[list[str], dict[str, int]]:
    """从请求解析城市序列与停留天数。

    优先读取 request.cities（多城联游）；为空时退化为单城：
    [request.city] 独占全部旅行天数（含起止日）。
    """
    city_stays = getattr(request, "cities", None) or []
    if city_stays:
        cities = [stay.city for stay in city_stays]
        city_days = {stay.city: stay.days for stay in city_stays}
        return cities, city_days

    start = datetime.strptime(request.start_date, "%Y-%m-%d")
    end = datetime.strptime(request.end_date, "%Y-%m-%d")
    total_days = (end - start).days + 1
    return [request.city], {request.city: total_days}
