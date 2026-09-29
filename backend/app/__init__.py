"""
backend/app/__init__.py

agent1旅行 后端应用包初始化文件。

作用：
- 标识 app 目录为一个 Python 包；
- 定义包级别版本号；
- 【关键】在任何 app 子模块导入之前设置 HuggingFace 离线开关。

注意：
- 不要在本文件中引入过多依赖，避免循环导入；
- 真正的应用创建逻辑在 app/api/main.py 中。
"""

import os

# HuggingFace 离线开关（必须设置在这里，即所有 app 子模块导入之前）：
# langchain_core 会在导入期连带导入 transformers -> huggingface_hub，
# 而 huggingface_hub 在【导入时刻】就把 HF_HUB_OFFLINE 读取为模块常量。
# 如果等到 rag_service.py 里再设置就太晚了（langchain 已抢先导入），
# 嵌入模型加载时会联网重试（每文件 5 次 × 21 秒超时），拖垮规划流程。
# - 模型有本地缓存 → 离线直接读缓存；
# - 模型无本地缓存 → 快速抛错，RAG 降级，规划主流程不受影响。
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

__version__ = "0.1.0"
