# Deployment Information

## Public URL
https://k5-day14-ai-agent.onrender.com

## Platform
**Render** — Blueprint (`render.yaml` & `06-lab-complete/render.yaml`):
- **Web Service:** `k5-day14-ai-agent` (Docker runtime, `rootDir: 06-lab-complete`, Singapore region, Free plan)
- **Managed Redis / Key Value:** `k5-day14-agent-redis` (Valkey 8 / Redis-compatible, Singapore region, Free plan)

## Test Commands

Đặt biến môi trường trước khi kiểm thử (không ghi secret thật vào file hay commit):

```bash
export BASE="https://k5-day14-ai-agent.onrender.com"
export AGENT_API_KEY="<key-tu-render-dashboard>"

# 1. Health check (liveness) → 200
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/health"
curl -sS "$BASE/health"

# 2. Readiness check (kiểm tra kết nối Redis trên Render) → 200
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/ready"
curl -sS "$BASE/ready"

# 3. Gọi /ask không có X-API-Key → 401
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" \
  -H 'Content-Type: application/json' \
  -d '{"question":"Hello"}'

# 4. Gọi /ask có X-API-Key hợp lệ → 200
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" \
  -H 'Content-Type: application/json' \
  -H "X-API-Key: $AGENT_API_KEY" \
  -d '{"question":"Hello"}'
```

### Kết quả kiểm thử thực tế

```text
GET  /health               → 200  {"status":"ok","environment":"production","uptime_seconds":244.5}
GET  /ready                → 200  {"status":"ready","redis":"connected"}
POST /ask (không có key)   → 401  {"detail":"Invalid or missing X-API-Key header"}
POST /ask (có X-API-Key)   → 200  {"question":"Hello","answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận.","user_id":"anonymous","usage":{"input_tokens":1,"output_tokens":17,"cost_usd":1e-05}}
POST /ask (input sai)      → 422  {"error":"Validation error","detail":[{"loc":["body","question"],"msg":"Field required","type":"missing"}]}
```

## Environment Variables Set (trên Render Dashboard / Blueprint)

| Biến môi trường | Nguồn / Giá trị | Ghi chú |
|---|---|---|
| `PORT` | Render tự inject (`10000`) | `Dockerfile` lắng nghe động theo `${PORT:-8000}` |
| `ENVIRONMENT` | `production` | Ẩn `/docs`, bật structured JSON logging |
| `LOG_LEVEL` | `INFO` | Mức log JSON |
| `AGENT_API_KEY` | `generateValue: true` trên Render | Secret tự sinh trên nền tảng, không lưu trong mã nguồn |
| `REDIS_URL` | `fromService` → `k5-day14-agent-redis` (`connectionString`) | Kết nối nội bộ tới Managed Redis trên Render |
| `RATE_LIMIT_PER_MINUTE` | `10` | Giới hạn 10 req/phút/API key lưu trong Redis |
| `DAILY_BUDGET_USD` | `1.0` | Ngân sách LLM theo ngày |
| `MONTHLY_BUDGET_USD` | `10.0` | Ngân sách LLM theo tháng |

## Screenshots
- [Deployment dashboard](screenshots/dashboard.png)
- [Service running](screenshots/running.png)
- [Test results](screenshots/test.png)
