# backend/Dockerfile
# 后端镜像：FastAPI(API 进程) 与 ARQ Worker 共用一个镜像，通过不同 command 启动。
# 基础镜像与本地 venv 的 Python 版本保持一致（3.12）。

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    # 国内 PyPI 镜像，加速依赖安装
    PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
    # HuggingFace 模型缓存目录（模型由 volume 挂载注入，见 docker-compose.yml）
    HF_HUB_CACHE=/root/.cache/huggingface/hub

WORKDIR /app

# 先装 CPU 版 torch（官方 CPU 源，避免拉到 Linux 默认的 CUDA 大包），
# 再装项目依赖；sentence-transformers 检测到 torch 已满足即不会重复安装
COPY requirements.txt ./
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r requirements.txt

# 再拷贝源码，充分利用构建缓存
COPY . .

EXPOSE 8000

# 默认启动 API 进程；Worker 在 compose 中以 command: python worker.py 复用本镜像
CMD ["python", "run.py"]
