# Deployment Information

## Public URL
*(Chờ cập nhật sau khi hoàn tất Render Blueprint deploy — dạng `https://k5-day14-ai-agent.onrender.com`)*

## Platform
**Render** (Docker Web Service + Managed Redis Blueprint từ `render.yaml` và `06-lab-complete/render.yaml`)

## Test Commands

Đặt biến môi trường trước khi kiểm thử (không ghi secret vào repo):

```bash
export BASE="https://<your-render-service>.onrender.com"
export AGENT_API_KEY="<key-tu-render-dashboard>"

# 1. Health check (liveness) → 200
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/health"

# 2. Readiness check (kiểm tra kết nối Redis trên cloud) → 200
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/ready"

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

## Environment Variables Set (trên Render Dashboard / Blueprint)

| Biến môi trường | Nguồn / Giá trị | Ghi chú |
|---|---|---|
| `PORT` | Render tự inject | `Dockerfile` dùng `${PORT:-8000}` |
| `ENVIRONMENT` | `production` | Ẩn `/docs`, bật structured logging production |
| `LOG_LEVEL` | `INFO` | Mức log JSON |
| `AGENT_API_KEY` | `generateValue: true` trên Render | Secret tự sinh trên nền tảng, không lưu trong code |
| `REDIS_URL` | `fromService` → `k5-day14-agent-redis` (`connectionString`) | Kết nối nội bộ tới Managed Redis trên Render |
| `RATE_LIMIT_PER_MINUTE` | `10` | Giới hạn 10 req/phút/API key lưu trên Redis |
| `DAILY_BUDGET_USD` | `1.0` | Ngân sách LLM theo ngày |
| `MONTHLY_BUDGET_USD` | `10.0` | Ngân sách LLM theo tháng |

## Screenshots
- [Deployment dashboard](screenshots/dashboard.png)
- [Service running](screenshots/running.png)
- [Test results](screenshots/test.png)
