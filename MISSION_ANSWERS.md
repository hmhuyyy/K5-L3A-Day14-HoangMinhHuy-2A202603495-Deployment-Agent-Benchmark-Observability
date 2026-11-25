# Day 14 Lab — Mission Answers

> **Học viên:** Hoàng Minh Huy · **MSSV:** 2A202603495 · **Lớp:** K5-L3A

---

## Part 1: Localhost vs Production

### Exercise 1.1: Anti-patterns phát hiện trong `01-localhost-vs-production/develop/app.py`

1. **Hardcode secrets ngay trong mã nguồn** (dòng 17–18): `OPENAI_API_KEY = "sk-hardcoded-fake-key-never-do-this"` và `DATABASE_URL = "postgresql://admin:password123@localhost:5432/mydb"`. Nếu push lên GitHub, bí mật bị lộ vĩnh viễn trong lịch sử commit.
2. **Không có cấu hình tập trung / đọc từ biến môi trường** (dòng 21–22): `DEBUG = True`, `MAX_TOKENS = 500` viết cứng, không thể đổi giữa dev / staging / production mà không sửa code.
3. **Dùng `print()` thay cho structured logging và in thẳng API key ra stdout** (dòng 33–38): `print(f"[DEBUG] Using key: {OPENAI_API_KEY}")` vừa khó tìm kiếm/lọc trên hệ thống log tập trung vừa làm rò rỉ secret ra log.
4. **Không có health check (`/health`) và readiness probe (`/ready`)** (dòng 42–43): nền tảng cloud/load balancer không biết khi nào container chết để restart hoặc chưa sẵn sàng nhận traffic.
5. **Bind `host="localhost"`, cứng `port=8000` và bật `reload=True`** (dòng 49–53): bind `localhost` khiến container không nhận được traffic từ bên ngoài; không đọc biến `PORT` do cloud platform cấp; `reload=True` tốn tài nguyên và mất ổn định ở production.
6. **Không có graceful shutdown và input validation chặt chẽ** (dòng 30–31): nhận `question` qua query param không giới hạn độ dài, không xử lý `SIGTERM` hay `lifespan` nên request đang chạy bị cắt ngang khi tắt tiến trình.

### Exercise 1.2: Kết quả chạy bản `develop` và kiểm thử `production`

Chạy `01-localhost-vs-production/develop/app.py` (nhận `question` qua query string):

```text
GET /
HTTP 200: {"message":"Hello! Agent is running on my machine :)"}

POST /ask?question=Hello
HTTP 200: {"answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic."}
```

Chạy `01-localhost-vs-production/production/app.py` (12-Factor):

```text
GET /health
HTTP 200: {"status":"ok","uptime_seconds":0.4,"version":"1.0.0","environment":"development","timestamp":"2026-11-25T08:27:52.216870+00:00"}

GET /ready
HTTP 200: {"ready":true}

POST /ask  {"question": "Hello"}
HTTP 200: {"question":"Hello","answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic.","model":"gpt-4o-mini"}
```

**Ví dụ anti-pattern đã được sửa trong `production/`:**
- Hardcode config/secret ở `develop/app.py` (dòng 17–22, 51–53) → đã tách sang `production/config.py` (dòng 15–50) đọc hoàn toàn qua `os.getenv(...)` và `validate()` fail-fast khi thiếu `AGENT_API_KEY` ở production; `production/app.py` (dòng 194–199) bind `settings.host` (`0.0.0.0`), `settings.port` (từ `PORT`) và chỉ bật `reload` khi `DEBUG=true`.

### Exercise 1.3: Bảng so sánh `develop` vs `production`

| Feature | Develop (`develop/app.py`) | Production (`production/app.py` + `config.py`) | Tại sao quan trọng? |
|---|---|---|---|
| Config & Secrets | Hardcode API key, DB password, `DEBUG=True`, port `8000` trong code | Đọc tập trung qua `Settings` từ biến môi trường (`os.getenv`), fail-fast nếu thiếu key ở production | Tránh lộ bí mật lên Git; cùng một artifact/image chạy được trên dev, staging, production chỉ bằng đổi env vars (12-Factor). |
| Binding & Port | `host="localhost"`, cứng `port=8000`, `reload=True` | `host="0.0.0.0"`, `port=int(os.getenv("PORT", 8000))`, `reload=settings.debug` | Trong container/cloud, `localhost` chặn kết nối từ bên ngoài; cloud platform (Render/Railway/Cloud Run) cấp cổng động qua biến `PORT`. |
| Health / Readiness | Không có | `GET /health` (liveness + uptime/version) và `GET /ready` (readiness trả 503 khi chưa sẵn sàng) | Platform biết tự restart khi tiến trình treo (`/health`) và Load Balancer chỉ đẩy traffic khi app đã sẵn sàng (`/ready`). |
| Logging | `print()` plain text, còn in cả `OPENAI_API_KEY` | `logging` định dạng JSON có `time`, `level`, `event`, tuyệt đối không log secret | Log JSON dễ thu thập, tìm kiếm và lọc trong Loki/Datadog/Cloud Logging, đồng thời đảm bảo an toàn dữ liệu nhạy cảm. |
| Shutdown | Tắt đột ngột, không giải phóng tài nguyên | `lifespan` chuyển `is_ready = False` + chờ hoàn thành request, đăng ký xử lý `SIGTERM` | Ngăn cắt ngang request đang xử lý (zero-downtime deploy) và đóng gọn kết nối DB/Redis. |
| CORS & Validation | Không có CORS, query param không kiểm tra rỗng | `CORSMiddleware` theo `ALLOWED_ORIGINS`, trả 422 rõ ràng khi thiếu `question` | Kiểm soát nguồn gọi hợp lệ từ trình duyệt và từ chối sớm dữ liệu đầu vào sai chuẩn. |

---

## Part 2: Docker Containerization

### Exercise 2.1: Trả lời 4 câu hỏi về `02-docker/develop/Dockerfile`

1. **Base image là gì?** `python:3.11` (bản Debian đầy đủ kèm toàn bộ toolchain build và thư viện hệ thống, kích thước nền ~1 GB).
2. **Working directory là gì?** `/app` (`WORKDIR /app` — mọi lệnh `COPY`, `RUN`, `CMD` sau đó thực thi tương đối trong thư mục này).
3. **Tại sao `COPY requirements.txt` đứng trước `COPY app.py`?** Để tận dụng **Docker layer cache**. Mã nguồn thay đổi thường xuyên hơn nhiều so với danh sách thư viện; nếu copy `requirements.txt` và chạy `pip install` trước, mỗi lần sửa code Docker chỉ rebuild từ bước copy code trở đi mà không phải tải & cài lại toàn bộ dependencies.
4. **`CMD` vs `ENTRYPOINT` khác nhau thế nào?** `ENTRYPOINT` định nghĩa tiến trình chính cố định của container (khó bị ghi đè trừ khi dùng cờ `--entrypoint`), còn `CMD` cung cấp lệnh hoặc tham số mặc định có thể dễ dàng ghi đè khi chạy `docker run <image> <custom-cmd>`. Khi kết hợp cả hai, `CMD` đóng vai trò là tham số mặc định truyền vào `ENTRYPOINT`.

### Exercise 2.2 & 2.3: So sánh kích thước image `develop` vs `production` (Multi-stage)

Lệnh build từ gốc repo:
```bash
docker build -f 02-docker/develop/Dockerfile -t my-agent:develop .
docker build -f 02-docker/production/Dockerfile -t my-agent:advanced .
docker images my-agent
```

Kết quả đo trực tiếp bằng `docker images` và `docker image inspect`:

```text
REPOSITORY:TAG      SIZE      IMAGE ID
my-agent:advanced   240MB     f9eadeba01a1
my-agent:develop    1.67GB    d229be072199
develop_bytes=1667784149
advanced_bytes=239815212
```

- **Develop (`my-agent:develop`):** **1.67 GB** (`1,667.8 MB` decimal / `1,590.5 MiB`)
- **Production (`my-agent:advanced`):** **240 MB** (`239.8 MB` decimal / `228.7 MiB`)
- **Chênh lệch:** giảm **1,428 MB** tương đương **−85.6%**!

**Phân tích Multi-stage build (`02-docker/production/Dockerfile`):**
- **Stage 1 (`builder`, `python:3.11-slim`):** cài trình biên dịch (`gcc`, `libpq-dev`) và chạy `pip install --no-cache-dir --user -r requirements.txt` để biên dịch/cài thư viện vào `/root/.local`.
- **Stage 2 (`runtime`, `python:3.11-slim`):** tạo user non-root (`appuser`), chỉ `COPY --from=builder /root/.local /home/appuser/.local` cùng mã nguồn (`main.py`, `utils/mock_llm.py`), khai báo `HEALTHCHECK` và chạy uvicorn dưới quyền `appuser`.
- **Tại sao image nhỏ hơn?** Loại bỏ hoàn toàn base image Debian full và toàn bộ công cụ biên dịch (`gcc`, header files, apt cache) của Stage 1 khỏi image cuối cùng; vừa nhẹ hơn 85.6% (pull/deploy nhanh hơn) vừa giảm bề mặt tấn công bảo mật.

### Exercise 2.4: Kiến trúc Docker Compose stack (`02-docker/production/`)

**Sơ đồ kiến trúc:**
```text
Client ──▶ Nginx (:80 / :443, Reverse Proxy + Rate Limit + Security Headers)
                │  (Docker bridge network: internal)
                ▼
           Agent (:8000, FastAPI / Uvicorn — không mở port ra host)
              ├──▶ Redis (:6379, session cache & rate limit, volume: redis_data)
              └──▶ Qdrant (:6333, vector database cho RAG, volume: qdrant_data)
```

**Các service khởi chạy (`docker compose -p k5-day14-docker ps`):**
```text
NAME                       IMAGE                   SERVICE   STATUS                            PORTS
k5-day14-docker-agent-1    k5-day14-docker-agent   agent     Up (healthy)                      8000/tcp
k5-day14-docker-nginx-1    nginx:alpine            nginx     Up                                0.0.0.0:80->80/tcp, 0.0.0.0:443->443/tcp
k5-day14-docker-qdrant-1   qdrant/qdrant:v1.9.0    qdrant    Up (healthy)                      6333-6334/tcp
k5-day14-docker-redis-1    redis:7-alpine          redis     Up (healthy)                      6379/tcp
```

Các service giao tiếp với nhau qua mạng nội bộ Docker (`internal`) bằng tên service (Docker DNS: `agent:8000`, `redis:6379`, `qdrant:6333`); `agent` chỉ khởi chạy sau khi cả `redis` và `qdrant` báo `service_healthy`.

**Kết quả test qua Nginx (`http://localhost/health`):**
```http
HTTP/1.1 200 OK
Server: nginx
Content-Type: application/json
X-Frame-Options: DENY
X-Content-Type-Options: nosniff
X-XSS-Protection: 1; mode=block

{"status":"ok","uptime_seconds":1.5,"version":"2.0.0","timestamp":"2026-11-25T08:54:11.134679"}
```

---

## Part 3: Cloud Deployment

### Exercise 3.1 / 3.2: Triển khai Agent Part 6 (`06-lab-complete/`) lên Render

- **Nền tảng chính:** Render (Docker Web Service + Managed Redis / Key Value)
- **Public URL:** *(Đang hoàn tất deploy trên Render — xem chi tiết và kết quả 4 lệnh tự kiểm trong [DEPLOYMENT.md](DEPLOYMENT.md))*
- **Screenshots:** [dashboard.png](screenshots/dashboard.png), [running.png](screenshots/running.png), [test.png](screenshots/test.png)

**So sánh `railway.toml` vs `render.yaml`:**

| Tiêu chí | `railway.toml` (Railway) | `render.yaml` (Render Blueprint) |
|---|---|---|
| Phạm vi khai báo | Cấu hình cho **1 service** (cách build, startCommand, healthcheck, restart policy). | **Infrastructure as Code (IaC)** cho **cả cụm dịch vụ** (Web Service + Redis/Database + liên kết `fromService`). |
| Định dạng | TOML (`[build]`, `[deploy]`), gọn nhẹ, trực quan. | YAML (`services:` list), đầy đủ thuộc tính hạ tầng (`region`, `plan`, `autoDeploy`, `disk`, `envVars`). |
| Quản lý Redis & biến môi trường | Thường tạo add-on Redis và gắn biến môi trường (`AGENT_API_KEY`, `REDIS_URL`) qua Railway Dashboard hoặc CLI (`railway variables set`). | Khai báo trực tiếp service Redis và ánh xạ `REDIS_URL` bằng `fromService`, secret hỗ trợ `generateValue: true` hoặc `sync: false` ngay trong file mà không lộ giá trị. |
| Chiến lược deploy | Build qua `builder = "DOCKERFILE"` hoặc `NIXPACKS`, hỗ trợ push trực tiếp từ CLI (`railway up`). | Đồng bộ tự động từ GitHub (GitOps Blueprint): mỗi lần push lên nhánh chính sẽ tự động `autoDeploy`. |

### Exercise 3.3: Phân tích CI/CD pipeline GCP Cloud Run (`03-cloud-deployment/production-cloud-run/`)

Đọc `cloudbuild.yaml` và `service.yaml`, pipeline CI/CD trên Google Cloud đi qua 4 bước tuần tự khi có commit mới lên `main`:
1. **Test (`python:3.11-slim`):** cài dependencies và chạy `pytest tests/ -v`; nếu test fail sẽ dừng pipeline ngay lập tức.
2. **Build (`gcr.io/cloud-builders/docker`, `waitFor: [test]`):** build Docker image từ `Dockerfile`, gắn cả hai tag `$COMMIT_SHA` (bất biến để rollback) và `latest`, tận dụng `--cache-from` để tăng tốc.
3. **Push (`waitFor: [build]`):** đẩy toàn bộ tag image vừa build lên Google Container Registry (`gcr.io/$PROJECT_ID/ai-agent`).
4. **Deploy (`gcr.io/cloud-builders/gcloud`, `waitFor: [push]`):** triển khai image theo `$COMMIT_SHA` lên Cloud Run (`asia-southeast1`), cấu hình tài nguyên (`1 CPU`, `512Mi RAM`, `concurrency=80`), scale `min-instances=1` (tránh cold start) tới `max-instances=10`, nạp secret an toàn từ **Secret Manager** (`secretKeyRef` trong `service.yaml`) và kiểm tra sống/sẵn sàng qua `livenessProbe` (`/health`) + `startupProbe` (`/ready`).

---

## Part 4: API Security

### Exercise 4.1: API Key Authentication (`04-api-gateway/develop/`)

- API key được kiểm tra trong dependency `verify_api_key` dùng `APIKeyHeader(name="X-API-Key", auto_error=False)` và gắn vào `/ask` qua `Depends(verify_api_key)`.
- Thiếu key trả **401 Unauthorized**; sai key trả **403 Forbidden** (trong Part 6 chuẩn hoá cả hai thành **401** theo hợp đồng script chấm).
- **Rotate key:** đọc key từ biến môi trường `AGENT_API_KEY`; khi xoay vòng có thể hỗ trợ tạm thời danh sách 2 key (key cũ + key mới) qua env var, cập nhật client sang key mới rồi gỡ key cũ mà không gián đoạn dịch vụ.

**Kết quả test thực tế (`AGENT_API_KEY=secret-key-123`):**
```http
# 1. Không có X-API-Key → 401
HTTP/1.1 401 Unauthorized
content-type: application/json
{"detail":"Missing API key. Include header: X-API-Key: <your-key>"}

# 2. Sai X-API-Key → 403
HTTP/1.1 403 Forbidden
content-type: application/json
{"detail":"Invalid API key."}

# 3. Đúng X-API-Key → 200
HTTP/1.1 200 OK
content-type: application/json
{"question":"Hello","answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic."}
```

### Exercise 4.2 & 4.3: JWT Authentication & Rate Limiting (`04-api-gateway/production/`)

- **Thuật toán Rate Limiting (`rate_limiter.py`):** **Sliding Window Log** (lưu `deque` các timestamp request của từng user trong cửa sổ 60 giây, xoá các timestamp quá hạn `now - 60`, kiểm tra `len(window) >= max_requests`).
- **Giới hạn:** Role `user` (`student`) bị giới hạn **10 requests/phút**; role `admin` (`teacher`) được **100 requests/phút** (chọn `rate_limiter_admin if role == "admin" else rate_limiter_user` theo claim `role` giải mã từ JWT — hoặc bỏ qua bước gọi `limiter.check()` nếu muốn bypass hẳn cho admin).

**Kết quả test thực tế (đã che token):**
```http
# 1. Gọi /ask không có Authorization header → 401
HTTP/1.1 401 Unauthorized
www-authenticate: Bearer
x-content-type-options: nosniff
x-frame-options: DENY
{"detail":"Authentication required. Include: Authorization: Bearer <token>"}

# 2. Đăng nhập POST /auth/token (student / demo123) → 200
HTTP/1.1 200 OK
access_token: eyJhbGciOiJIUzI1...<REDACTED>

# 3. Vòng lặp 20 request liên tiếp với Authorization: Bearer <REDACTED>
Req  1..10: HTTP 200 OK   (requests_remaining giảm dần từ 9 → 0)
Req 11..20: HTTP 429 Too Many Requests
  x-ratelimit-limit: 10
  x-ratelimit-remaining: 0
  retry-after: 59
  body: {"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":59}}
```

### Exercise 4.4: Cách triển khai Cost Guard

- **Tại sao cần cả Rate Limit lẫn Cost Guard?** Rate limit chỉ bảo vệ **tốc độ** (số request/phút) chống spam/DDoS, còn Cost Guard bảo vệ **tiền** (tổng chi phí USD theo số token thực tế). Một client gửi chậm 5 req/phút nhưng mỗi prompt dài hàng chục nghìn token vẫn có thể vượt rate limit không hề bị chặn nhưng đốt cạn ngân sách LLM.
- **Cách triển khai stateless với Redis (áp dụng trong Part 6 `app/cost_guard.py`):**
  1. Lưu tổng chi phí trong Redis theo khoá có kỳ hạn: `cost:daily:YYYY-MM-DD` (TTL 2 ngày) và `cost:monthly:YYYY-MM` (TTL 35 ngày) để tự động reset sang ngày/tháng mới và dùng chung giữa mọi worker/instance.
  2. **Trước khi gọi LLM (`check_budget()`):** đọc giá trị chi tiêu hiện tại; nếu `>= DAILY_BUDGET_USD` hoặc `>= MONTHLY_BUDGET_USD` thì chặn ngay với **HTTP 402 Payment Required**.
  3. **Sau khi gọi LLM (`record_cost(input_tokens, output_tokens)`):** tính chi phí theo đơn giá token đầu vào/đầu ra rồi cộng nguyên tử vào Redis bằng `INCRBYFLOAT` + đặt `EXPIRE`.

---

## Part 5: Scaling & Reliability

### Exercise 5.1 & 5.2: Health Checks & Graceful Shutdown (`05-scaling-reliability/develop/`)

- **Phân biệt Liveness (`/health`) vs Readiness (`/ready`):**
  - `/health` (Liveness): kiểm tra tiến trình còn sống hay không (luôn trả 200 khi process chạy, kể cả khi Redis/DB tạm gián đoạn để tránh platform restart vòng lặp vô ích).
  - `/ready` (Readiness): kiểm tra instance có sẵn sàng nhận traffic hay không (kiểm tra cờ `_is_ready`, kết nối Redis/DB; trả **503** khi đang khởi động, đang shutdown hoặc mất Redis để Load Balancer ngừng đẩy traffic mới vào mà **không** kill container).
- **Graceful Shutdown:** khi nhận `SIGTERM`, đặt trạng thái không sẵn sàng (`/ready` → 503), ngừng nhận request mới, chờ toàn bộ request đang xử lý (`in-flight`) hoàn tất, đóng connection pool rồi thoát với exit code `0`. Nếu tự đăng ký handler `signal.SIGTERM`, bắt buộc gọi lại handler cũ của uvicorn để uvicorn thực hiện quy trình shutdown.

**Kết quả test `05-scaling-reliability/develop/app.py`:**
```text
GET /health → HTTP 200 {"status":"degraded","uptime_seconds":1.1,"version":"1.0.0","environment":"development","checks":{"memory":{"status":"degraded","used_percent":95.9}}}
GET /ready  → HTTP 200 {"ready":true,"in_flight_requests":1}
```

### Exercise 5.3–5.5: Stateless Design, Load Balancing & Test thực tế (`05-scaling-reliability/production/`)

- **Tại sao state trong RAM bị hỏng khi scale ngang?** Mỗi container/worker có vùng nhớ RAM độc lập. Khi Nginx chia các request cùng một người dùng tới các instance khác nhau, dữ liệu hội thoại lưu trong `dict` ở RAM của instance 1 sẽ không tồn tại trên instance 2 hoặc biến mất hoàn toàn khi container restart. Chuyển toàn bộ session/rate-limit/budget sang **Redis** giúp mọi instance đều stateless và thay thế lẫn nhau được.

**Khởi chạy stack 3 instances (`docker compose -p k5-day14-scaling up -d --build --scale agent=3`):**
```text
NAME                       IMAGE                    SERVICE   STATUS                    PORTS
k5-day14-scaling-agent-1   k5-day14-scaling-agent   agent     Up 14 seconds (healthy)   8000/tcp
k5-day14-scaling-agent-2   k5-day14-scaling-agent   agent     Up 13 seconds (healthy)   8000/tcp
k5-day14-scaling-agent-3   k5-day14-scaling-agent   agent     Up 13 seconds (healthy)   8000/tcp
k5-day14-scaling-nginx-1   nginx:alpine             nginx     Up 13 seconds             0.0.0.0:8080->80/tcp
k5-day14-scaling-redis-1   redis:7-alpine           redis     Up 24 seconds (healthy)   6379/tcp
```

**Kết quả chạy `python test_stateless.py` (cổng 8080, `POST /chat`):**
```text
============================================================
Stateless Scaling Demo
============================================================

Session ID: f029b842-4b78-49a4-9fa0-6374823311a7

Request 1: [instance-d3143e]  Q: What is Docker?
Request 2: [instance-04557b]  Q: Why do we need containers?
Request 3: [instance-d3143e]  Q: What is Kubernetes?
Request 4: [instance-5c7754]  Q: How does load balancing work?
Request 5: [instance-04557b]  Q: What is Redis used for?

------------------------------------------------------------
Total requests: 5
Instances used: {'instance-d3143e', 'instance-5c7754', 'instance-04557b'}
✅ All requests served despite different instances!

--- Conversation History ---
Total messages: 10
✅ Session history preserved across all instances via Redis!
```
**Giải thích:** Cả 5 câu hỏi thuộc cùng 1 `session_id` được Nginx phân phối đều qua cả 3 container khác nhau (`instance-d3143e`, `instance-04557b`, `instance-5c7754`), nhưng lịch sử cuộc trò chuyện vẫn đầy đủ cả **10 messages** (5 user + 5 assistant) vì toàn bộ trạng thái được đọc/ghi tập trung tại Redis.

---

## Part 6: Final Project — Kết quả kiểm tra tự động (`06-lab-complete/`)

Chạy `python check_production_ready.py` đầy đủ trong môi trường POSIX (`os.name == 'posix'`) kèm Docker 29.9.3:

```text
================================================================
  📋 Checklist Deliverable
     ✅ Dockerfile (multi-stage, < 500 MB)
     ✅ docker-compose.yml (agent + redis)
     ✅ .dockerignore
     ✅ Health check endpoint (GET /health)
     ✅ Readiness endpoint (GET /ready)
     ✅ API Key authentication
     ✅ Rate limiting
     ✅ Cost guard
     ✅ Config từ environment variables
     ✅ Structured logging
     ✅ Graceful shutdown
     ✅ Public URL ready (Railway / Render config)
----------------------------------------------------------------
  Result: 12/12 tiêu chí đạt · 43/43 checks passed
  🎉 PASS 12/12 — PRODUCTION READY! Deploy nào!
================================================================
```

**Thông số thực đo nổi bật từ script chấm:**
- Docker image size: **271 MB** (< 500 MB), multi-stage `python:3.11-slim`, user non-root `appuser`, có `HEALTHCHECK`.
- Rate limiting: trả `429` kèm header `Retry-After` sau 5 request (`RATE_LIMIT_PER_MINUTE=5`), sau khi restart agent vẫn trả `429` (state lưu trong Redis ZSET).
- Cost guard: trả `402` ngay khi chi phí vượt ngân sách.
- Readiness: Redis mất kết nối → `/ready` trả `503` trong khi `/health` vẫn trả `200`.
- Structured logging: **17/17 dòng log JSON hợp lệ**.
- Graceful shutdown: gửi `SIGTERM` lúc đang có request → request vẫn trả `200`, process thoát `exit code 0`; `docker stop` thoát `exit code 0` trong **0.9s** (< 10s).

---

## AI Log

1. **Triển khai Part 6 (`06-lab-complete/`):**
   - *Hỏi gì:* Nhờ trợ lý AI (Antigravity / Gemini) phân tích toàn bộ hợp đồng kiểm thử của `check_production_ready.py`, viết khung cài đặt cho `app/config.py`, `app/redis_client.py`, `app/auth.py`, `app/rate_limiter.py`, `app/cost_guard.py`, `app/main.py`, `Dockerfile` multi-stage, `docker-compose.yml`, `.dockerignore`, `.env.example`, `railway.toml`, `render.yaml`.
   - *Nhận gì:* Code dùng virtual environment `/opt/venv` trong Dockerfile multi-stage, `secrets.compare_digest` cho `X-API-Key`, Redis sorted set sliding window cho rate limit, Redis `INCRBYFLOAT` theo ngày/tháng cho cost guard, `JsonFormatter` và `SIGTERM` forwarding trong `lifespan`.
   - *Tự kiểm tra & xác minh:* Chạy toàn bộ `check_production_ready.py` trong môi trường POSIX + Docker (không sửa script chấm), đạt **PASS 12/12 (43/43 checks passed)** với kích thước image 271 MB và `docker stop` 0.9s.
2. **Gỡ lỗi Docker & thực nghiệm Part 2, 5, 7:**
   - *Hỏi gì:* Phân tích nguyên nhân lỗi `ModuleNotFoundError: No module named 'uvicorn'` ở `06-lab-complete/benchmark-observability/production/Dockerfile` và lỗi hết dung lượng ổ đĩa ảo WSL2 khi chạy nhiều stack Docker.
   - *Nhận gì:* Phát hiện `useradd -d /app agent` khiến `HOME=/app` nên Python không tìm thấy gói `--user` ở `/home/agent/.local` → bổ sung `ENV PYTHONUSERBASE=/home/agent/.local`; đồng thời giới hạn RAM WSL2 và dọn cache giữa các bài.
   - *Tự kiểm tra & xác minh:* Tự chạy toàn bộ kịch bản thật (`load_test.py`, `run_eval.py`, Locust headless `scale_1` & `scale_3`, `promtool test rules`, 5 thí nghiệm chaos) và đối chiếu 100% số liệu trong `BENCHMARK_REPORT.md` khớp chính xác với các file JSON/CSV và ảnh chụp thật trong `reports/`, `benchmark-results/`, `screenshots/`.
