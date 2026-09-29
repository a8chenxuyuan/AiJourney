"""
backend/app/utils/json_parser.py

JSON 安全解析与修复工具模块。

作用：
- 安全解析 LLM 返回的 JSON 字符串；
- 当 LLM 输出包含 Markdown 代码块或多余文本时，尝试提取其中的 JSON；
- 解析失败时返回 None 或抛出异常，避免程序崩溃。

对应技术：
- Python json 标准库
- 正则表达式提取
"""

import json
import re
from typing import Any, Optional, Type, TypeVar

from loguru import logger
from pydantic import BaseModel, ValidationError


T = TypeVar("T", bound=BaseModel)


def extract_json_from_text(text: str) -> Optional[str]:
    """
    从文本中提取 JSON 字符串。

    处理场景：
    1. LLM 返回被 ```json ... ``` 包裹的 JSON；
    2. LLM 返回被 ``` ... ``` 包裹的 JSON；
    3. 文本中嵌套在其他内容里的 JSON 对象/数组。

    Args:
        text: 原始文本，可能包含 Markdown 代码块。

    Returns:
        Optional[str]: 提取到的 JSON 字符串，未找到返回 None。
    """
    # 先尝试匹配 ```json ... ``` 或 ``` ... ``` 代码块
    code_block_pattern = r"```(?:json)?\s*([\s\S]*?)\s*```"
    matches = re.findall(code_block_pattern, text)
    if matches:
        return matches[-1].strip()

    # 再尝试匹配最外层的大括号对象或中括号数组
    brace_pattern = r"(\{[\s\S]*\}|\[[\s\S]*\])"
    matches = re.findall(brace_pattern, text)
    if matches:
        return matches[-1].strip()

    return None


def safe_json_parse(text: str) -> Optional[Any]:
    """
    安全解析 JSON 字符串。

    Args:
        text: 待解析的字符串。

    Returns:
        Optional[Any]: 解析成功返回 Python 对象；失败返回 None。
    """
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 尝试从文本中提取 JSON 后再解析
    extracted = extract_json_from_text(text)
    if extracted:
        try:
            return json.loads(extracted)
        except json.JSONDecodeError:
            pass

    return None


def try_repair_json(text: str) -> Optional[str]:
    """
    尝试修复常见的 LLM JSON 输出问题。

    修复内容：
    - 去掉尾部的逗号（如 {"a": 1,}）
    - 处理单引号（如 {'a': 1}）
    - 处理无引号键（如 {a: 1}）

    Args:
        text: 可能损坏的 JSON 字符串。

    Returns:
        Optional[str]: 修复后的 JSON 字符串；无法修复返回 None。
    """
    repaired = text.strip()

    # 去掉对象/数组尾部多余的逗号
    repaired = re.sub(r",\s*\}", "}", repaired)
    repaired = re.sub(r",\s*\]", "]", repaired)

    # 单引号替换为双引号（简单场景）
    repaired = repaired.replace("'", '"')

    return repaired if repaired else None


def parse_llm_json(text: str, model_class: Type[T]) -> Optional[T]:
    """
    解析 LLM 输出并校验为指定 Pydantic 模型。

    【容错策略】
    1. 先直接 model_validate
    2. 失败时尝试 try_repair_json 修复 LLM 输出
    3. 还失败时尝试"宽松模式"校验（model_validate with strict=False，
       加上 None → 默认值的兜底），这一步能解决 LLM 把 float 字段填成 null 的问题
    4. 实在不行返回 None

    Args:
        text: LLM 返回的原始文本。
        model_class: 目标 Pydantic 模型类。

    Returns:
        Optional[T]: 解析并校验成功返回模型实例；失败返回 None。
    """
    # 第一次尝试直接解析
    data = safe_json_parse(text)
    if data is not None:
        try:
            return model_class.model_validate(data)
        except ValidationError as e:
            logger.warning(f"[parse_llm_json] ValidationError (第一次): {e}")

    # 第二次尝试修复后解析
    repaired = try_repair_json(text)
    if repaired:
        data = safe_json_parse(repaired)
        if data is not None:
            try:
                return model_class.model_validate(data)
            except ValidationError as e:
                logger.warning(f"[parse_llm_json] ValidationError (修复后): {e}")

    # 第三次尝试：把 data 里的 None 替换成字段默认类型对应的空值
    # 解决 LLM 把 float/int 字段填成 null 的问题（Pydantic v2 严格模式不允许）
    if data is not None:
        try:
            cleaned = _replace_none_with_defaults(data)
            return model_class.model_validate(cleaned)
        except ValidationError as e:
            logger.error(f"[parse_llm_json] ValidationError (宽松模式): {e}")
            logger.error(f"[parse_llm_json] 兜底失败详情: {str(e)[:600]}")

    # 三种方式都失败，打印原始内容供调试
    logger.error(f"[parse_llm_json] 解析失败，原始文本前 500 字符: {text[:500] if text else '(空)'}")

    return None


def _replace_none_with_defaults(obj):
    """
    递归遍历 dict/list，把 None 值替换成对应类型的"空值"。

    规则：
    - 字段名包含 "price"/"cost"/"rating"/"amount"/"lat"/"lng"/"longitude"/"latitude"/"count"
      → 0.0（浮点数字段）
    - 字段名包含 "duration"/"hours"/"days"/"num"
      → 0（整数字段）
    - 其他 None
      → ""（字符串）/ []（列表）

    这样模型再校验时就不会因为 LLM 输出 null 而失败。
    """
    NUMERIC_KEYS = (
        "price", "cost", "rating", "amount", "lat", "lng",
        "longitude", "latitude", "duration", "hours", "days",
        "count", "score", "weight", "score",
    )
    if isinstance(obj, dict):
        cleaned = {}
        for k, v in obj.items():
            if v is None:
                k_lower = k.lower()
                if any(s in k_lower for s in NUMERIC_KEYS):
                    cleaned[k] = 0.0
                elif k_lower in ("tags", "highlights", "items", "images", "photos"):
                    cleaned[k] = []
                elif "is_" in k_lower or "has_" in k_lower or "can_" in k_lower:
                    cleaned[k] = False
                else:
                    cleaned[k] = ""
            else:
                cleaned[k] = _replace_none_with_defaults(v)
        return cleaned
    if isinstance(obj, list):
        return [_replace_none_with_defaults(item) for item in obj]
    return obj
