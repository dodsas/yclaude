FROM python:3.12-slim

# Claude CLI(Node.js 패키지) 구동을 위해 Node + 기본 진단도구 + curl(헬스체크용) 설치
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        curl ca-certificates iputils-ping nodejs npm \
 && rm -rf /var/lib/apt/lists/*

# Claude CLI 전역 설치 (subprocess 호출 대상)
RUN npm install -g @anthropic-ai/claude-code && npm cache clean --force

WORKDIR /app

COPY server/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY server/ ./

RUN mkdir -p /app/data /app/logs /app/secrets \
 && useradd -u 1000 -m -d /home/app app \
 && chown -R app:app /app /home/app

USER app

ENV HOST=0.0.0.0
ENV PORT=9090
ENV PYTHONUNBUFFERED=1

EXPOSE 9090

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD curl -fsS http://localhost:9090/health >/dev/null 2>&1 || exit 1

CMD ["python", "main.py"]
