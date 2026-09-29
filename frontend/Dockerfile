# frontend/Dockerfile
# 前端镜像：两阶段构建 —— Node 编译产物 + Nginx 托管静态文件并反向代理 API。

# ---------- 阶段 1：构建 ----------
FROM node:20-alpine AS build

WORKDIR /app

# 使用国内 npm 镜像加速；有 lock 文件时用 npm ci 保证依赖可重现
COPY package.json package-lock.json ./
RUN npm config set registry https://registry.npmmirror.com && npm ci

COPY . .

# 关键：容器化部署时前端与后端同源（经 Nginx 反代），API 基地址改为相对路径 /api
ARG VITE_API_BASE_URL=/api
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL

RUN npm run build

# ---------- 阶段 2：运行 ----------
FROM nginx:alpine

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
