"""
backend/app/utils/validators.py

通用输入校验工具模块。

作用：
- 提供项目中常用的校验函数；
- 如城市名称校验、日期格式校验、手机号/邮箱辅助校验等；
- 可被 Pydantic 模型或路由层调用。

对应技术：
- Python re 标准库
- Pydantic 自定义校验器
"""

import re
from datetime import datetime
from typing import Optional


def is_valid_city_name(city: str) -> bool:
    """
    校验城市名称是否合法。

    规则：至少 2 个字符，只能包含中文字符、英文字母、空格。

    Args:
        city: 城市名称。

    Returns:
        bool: 是否合法。
    """
    if not city or len(city.strip()) < 2:
        return False
    return bool(re.match(r"^[\u4e00-\u9fa5a-zA-Z\s]+$", city.strip()))


def is_valid_date_str(date_str: str, fmt: str = "%Y-%m-%d") -> bool:
    """
    校验日期字符串是否符合指定格式。

    Args:
        date_str: 日期字符串。
        fmt: 日期格式，默认 %Y-%m-%d。

    Returns:
        bool: 是否合法。
    """
    try:
        datetime.strptime(date_str, fmt)
        return True
    except ValueError:
        return False


def calculate_days_between(start_date: str, end_date: str, fmt: str = "%Y-%m-%d") -> Optional[int]:
    """
    计算两个日期之间的天数（包含起止日期）。

    Args:
        start_date: 开始日期字符串。
        end_date: 结束日期字符串。
        fmt: 日期格式。

    Returns:
        Optional[int]: 天数；日期格式错误返回 None。
    """
    try:
        start = datetime.strptime(start_date, fmt)
        end = datetime.strptime(end_date, fmt)
        delta = end - start
        # 包含起止两天，所以 +1
        return delta.days + 1 if delta.days >= 0 else None
    except ValueError:
        return None
