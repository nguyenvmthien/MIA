# Scalability & Deployment

## Kiến trúc deployment (Docker Compose / K8s)

```
┌──────────────────────────────────────────────────────────┐
│                  App Cluster                             │
│  [api-gateway]      [worker-1]        [worker-2]        │
│  FastAPI:8000        Celery worker     Celery worker     │
│  2 CPU / 4GB         1 GPU / 16GB      1 GPU / 16GB     │
└──────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────┐
│                  Data Cluster                            │
│  [postgres:5432]   [redis:6379]   [ollama:11434]         │
└──────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────┐
│                  Observability Cluster                   │
│  [prometheus:9090]  [grafana:3000]  [langsmith]          │
└──────────────────────────────────────────────────────────┘
```

---

## Chạy hệ thống

```bash
# Local (CPU-only, không cần GPU)
docker compose up

# Với NVIDIA GPU
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d
```

| Service | URL |
|---------|-----|
| Streamlit UI | http://localhost:8501 |
| API | http://localhost:8000 |
| API Docs | http://localhost:8000/docs |
| Grafana | http://localhost:3000 |
| Prometheus | http://localhost:9090 |

---

## Distributed Inference — Scale-out LLM

```env
# .env — thêm nhiều Ollama instances
OLLAMA_ENDPOINTS=http://gpu1:11434,http://gpu2:11434,http://gpu3:11434
OLLAMA_ROUTING_STRATEGY=least_loaded  # hoặc round_robin
```

Router tự động:
- Health check mỗi 30 giây
- Failover khi endpoint lỗi
- Track in-flight requests per endpoint

---

## Chiến lược cost optimization

| Vấn đề | Giải pháp |
|--------|-----------|
| Re-process cùng chunk | Redis cache theo (meeting_id + chunk_hash) |
| Token overflow | `CHUNK_TOKEN_BUDGET = 2048` tokens max |
| GPU đắt | GGUF Q4_K_M chạy tốt trên CPU |
| Nhiều meetings cùng lúc | Celery queue, rate limit 10 concurrent jobs |
