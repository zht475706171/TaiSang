# ============================================================
# Stage 1: 前端构建(node + vite)
# ============================================================
FROM node:20-alpine AS frontend-builder

WORKDIR /build

# 先 copy package 清单,利用 docker layer 缓存
COPY src/taisang/web/frontend/package.json src/taisang/web/frontend/package-lock.json* ./

# 安装依赖(用 npm ci 兜底 lock 没有时回退 npm install)
RUN if [ -f package-lock.json ]; then npm ci --no-audit --no-fund; \
    else npm install --no-audit --no-fund; fi

# copy 源码 + vite 配置,构建到 ../static(相对 frontend/,即 /static)
COPY src/taisang/web/frontend/ ./

# vite outDir=../static 相对 vite.config.ts 所在目录(/build),
# 即输出到 /static
RUN npm run build

# ============================================================
# Stage 2: 运行时(python + 后端 + 前端静态文件)
# ============================================================
FROM python:3.12-slim AS runtime

# 系统依赖:git(Agent 工具 + Plugin 安装要用)+ ca-certificates(HTTPS)
# + tini(容器 init,正确转发信号 + 回收僵尸进程)
RUN apt-get update && apt-get install -y --no-install-recommends \
        git tini ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# 非 root 用户运行容器(安全 + 跟 ~/.taisang 挂载对齐)
RUN useradd --create-home --uid 1000 --shell /bin/bash taisang

# 预创建 ~/.taisang 并改 owner,Docker 声明 VOLUME 后匿名 volume
# 第一次挂时会从镜像继承目录权限,容器内 taisang 用户能读写
RUN mkdir -p /home/taisang/.taisang/sessions /home/taisang/.taisang/logs \
    && chown -R taisang:taisang /home/taisang

WORKDIR /app

# 先 copy pyproject.toml,利用 layer 缓存装依赖
COPY pyproject.toml ./

# copy 源码(不含前端 dist,前端由 stage 1 产出)
COPY src/ ./src/

# 把 stage 1 产出的前端静态文件覆盖到 web/static
# vite outDir=../static,在 frontend-builder 里输出到 /static
COPY --from=frontend-builder /static/ ./src/taisang/web/static/

# 安装项目(web extras 包含 fastapi/uvicorn/mcp)
RUN pip install --no-cache-dir -e ".[web]"

# 切换到非 root 用户
USER taisang
ENV HOME=/home/taisang
ENV PYTHONUNBUFFERED=1
ENV TAISANG_HOST=0.0.0.0
ENV TAISANG_PORT=8765

# ~/.taisang 挂载点(用户配置 / sessions / logs)
VOLUME ["/home/taisang/.taisang"]

# 工作目录默认 /home/taisang/projects,用户可以挂载自己的 repo 到这里
WORKDIR /home/taisang/projects

EXPOSE 8765

# tini 做 PID 1,正确处理 SIGTERM(uvicorn 自己收到 SIGTERM 会优雅关)
ENTRYPOINT ["/usr/bin/tini", "--"]

# 默认起 web 服务;host/port 走环境变量,用户可覆盖
CMD ["sh", "-c", "taisang web --host ${TAISANG_HOST:-0.0.0.0} --port ${TAISANG_PORT:-8765}"]