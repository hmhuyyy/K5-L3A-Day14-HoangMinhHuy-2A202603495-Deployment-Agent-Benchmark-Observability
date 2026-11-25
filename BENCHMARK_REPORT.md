# Benchmark & Observability Report — Day 14

**Họ tên:** Hoàng Minh Huy (MSSV: 2A202603495 · Lớp K5-L3A)  
**Ngày chạy:** 2026-11-25  
**Môi trường:** Windows 11 (16 GB RAM, Python 3.12.9) · Docker Desktop 29.9.3 (WSL2 backend, giới hạn 3 GB RAM)

---

## 1. SLO của agent

| SLI | SLO | Lý do chọn ngưỡng này |
|---|---|---|
| p95 latency `/ask` | ≤ 500 ms | Với mock LLM cơ sở ~120–180 ms + retrieval ~20 ms và 3% tail latency (~1.7 s), 95% request bình thường hoàn thành dưới 500 ms — đảm bảo trải nghiệm tương tác mượt cho người dùng trong khi vẫn chừa dư địa cho jitter. |
| Error rate `/ask` | ≤ 2.0 % | Mock LLM có tỉ lệ lỗi upstream nền 1% (`MOCK_ERROR_RATE=0.01`). Đặt SLO lỗi ≤ 2% (error budget 2%) giúp chấp nhận dao động thống kê nhỏ mà vẫn phát hiện sớm khi upstream gặp sự cố (alert đặt cao hơn ở 5% trong 1 phút để tránh alert fatigue). |
| Accuracy trên golden dataset | ≥ 85 % (mục tiêu 100%, 0 regression) | Đảm bảo chất lượng tri thức của agent trước khi merge/deploy. Chặn cứng mọi PR làm tụt accuracy dưới ngưỡng hoặc gây regression trên câu vốn đã đúng ở phiên bản baseline. |

---

## 2. Benchmark hiệu năng (develop, `load_test.py`)

### 2.1 Concurrency vs latency (agent v2, 300 requests/mức)

Nguồn dữ liệu: [load_v2_c1.json](reports/load_v2_c1.json), [load_v2_c10.json](reports/load_v2_c10.json), [load_v2_c50.json](reports/load_v2_c50.json), [load_v2_c100.json](reports/load_v2_c100.json).

| Concurrency | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Error rate | SLO (p95 ≤ 500 ms, err ≤ 2%) |
|---:|---:|---:|---:|---:|---:|---|
| 1 | 4.21 | 201.9 | 235.9 | 1708.0 | 1.67% | PASS |
| 10 | 38.33 | 202.2 | 444.7 | 1686.1 | 0.67% | PASS |
| 50 | 93.08 | 217.7 | 572.0 | 1743.0 | 1.67% | FAIL (p95 > 500 ms) |
| 100 | 47.78 | 707.2 | 3682.3 | 4079.8 | 1.33% | FAIL (p95 > 500 ms) |

**Nhận xét:** RPS **không** tăng tuyến tính theo concurrency:
- Từ `c=1` → `c=10`, RPS tăng gần tuyến tính (4.21 → 38.33 req/s, gấp ~9.1 lần) do agent dùng `async`/`await` không block event loop khi chờ I/O (`asyncio.sleep`).
- Lên `c=50`, RPS chỉ đạt 93.08 req/s (tăng ~2.4 lần thay vì 5 lần) và p95 vượt ngưỡng SLO lên 572.0 ms.
- Tới `c=100`, hệ thống bước vào vùng bão hoà (saturation): một tiến trình uvicorn đơn trên Windows phải tranh chấp event loop, socket backlog và serialization JSON cùng lúc, khiến hàng đợi phình to — p50 vọt lên 707.2 ms, p95 lên 3682.3 ms, p99 lên 4079.8 ms và **RPS tụt ngược từ 93.08 xuống 47.78 req/s** (điểm gãy theo quy luật Little & hàng đợi).

### 2.2 Tail latency (`--requests 300 --concurrency 20`, agent v2)

Nguồn dữ liệu: [load_v2_slow_0.json](reports/load_v2_slow_0.json), [load_v2_slow_0.03.json](reports/load_v2_slow_0.03.json), [load_v2_slow_0.1.json](reports/load_v2_slow_0.1.json).

| `MOCK_SLOW_RATE` | avg (ms) | p95 (ms) | p99 (ms) |
|---|---:|---:|---:|
| 0 | 216.3 | 488.8 | 511.8 |
| 0.03 (mặc định) | 249.7 | 482.4 | 1710.4 |
| 0.1 | 352.3 | 1703.3 | 1728.1 |

**Nhận xét:**
- **Chỉ số nhạy nhất với request chậm là các percentile cao (`p99`, sau đó tới `p95`):**
  - Khi tăng `MOCK_SLOW_RATE` từ `0` lên `0.03` (3% request chậm thêm 1500 ms), `avg` chỉ tăng nhẹ **+33.4 ms** (216.3 → 249.7 ms) và `p95` gần như không đổi (~482 ms), nhưng **`p99` nhảy vọt +1198.6 ms** (511.8 → 1710.4 ms).
  - Khi tăng lên `0.1` (10% > 5% request chậm), `avg` mới đạt 352.3 ms (trông vẫn "dưới 500 ms" nếu chỉ nhìn trung bình), trong khi **cả `p95` (1703.3 ms) lẫn `p99` (1728.1 ms) đều bùng lên ~1.7 giây** và vi phạm nặng SLO.
- **Vì sao SLO không nên đặt theo average?** Giá trị trung bình bị chi phối bởi số đông request nhanh nên che giấu hoàn toàn trải nghiệm tệ của nhóm người dùng ở đuôi phân phối (*tail latency*). Đặt SLO theo `p95`/`p99` phản ánh đúng cam kết rằng 95% hoặc 99% người dùng thật nhận được phản hồi nhanh dưới ngưỡng.

---

## 3. Benchmark chất lượng (develop, `eval/run_eval.py`)

Nguồn dữ liệu: [eval_v1.json](reports/eval_v1.json), [eval_v2.json](reports/eval_v2.json), [eval_v2_fixed.json](reports/eval_v2_fixed.json).

| Chỉ số | Agent v1 | Agent v2 | Agent v2 (sau khi sửa KB) |
|---|---:|---:|---:|
| Accuracy | 4.3% (1/23) | 91.3% (21/23) | 100.0% (23/23) |
| Avg tokens / câu | 57.1 | 108.8 | 113.7 |
| Tổng cost (USD) | $0.000404 | $0.000758 | $0.000791 |
| Cost / câu đúng (USD) | $0.00040395 | $0.00003607 | $0.00003438 |
| Quality gate | FAIL | PASS | PASS (0 regression) |

**Những câu v2 trả lời sai ban đầu và cách sửa:**

| ID | Keyword bị thiếu | Đã sửa gì |
|---|---|---|
| `security-02` | `token`, `hết hạn`, `chữ ký` | Thêm entry với trigger `["jwt", "api key"]` vào `KNOWLEDGE_BASE` trong `develop/utils/mock_llm.py` (và đồng bộ sang `production/utils/mock_llm.py`) giải thích sự khác biệt giữa API key cố định và JWT token có chữ ký số & thời điểm hết hạn. |
| `scaling-03` | `cpu`, `memory`, `custom metrics` | Thêm entry với trigger `["hpa", "kubernetes", "autoscal"]` vào `KNOWLEDGE_BASE` mô tả Kubernetes HPA tự động scale pod theo CPU, memory hoặc custom metrics (RPS, độ dài hàng đợi). |

**Nhận xét về trade-off chất lượng / chi phí / latency giữa v1 và v2:**
- **Chất lượng:** v2 (có bước retrieval/RAG) nâng accuracy từ **4.3% (1/23)** lên **91.3% (21/23)** và **100.0% (23/23)** sau khi bổ sung tài liệu thiếu, không gây bất kỳ regression nào so với baseline.
- **Chi phí:** v2 tốn gần gấp đôi số token/câu (108.8–113.7 so với 57.1 ở v1) và tổng chi phí bộ 23 câu gần gấp đôi ($0.000791 so với $0.000404) do phải nhồi tài liệu truy xuất được vào prompt. Tuy nhiên xét theo **chi phí trên mỗi câu trả lời đúng (`cost_per_correct_usd`)**, v2 sau khi sửa chỉ tốn **$0.00003438/câu đúng — rẻ hơn ~11.7 lần** so với v1 ($0.00040395/câu đúng).
- **Latency:** v2 tăng p50 khoảng ~30 ms so với v1 (202.2 ms so với 170.8 ms) do thêm bước retrieval (~20 ms) và prompt dài hơn; đây là đánh đổi hoàn toàn xứng đáng cho mức tăng chất lượng +95.7 điểm %.

**Quality gate trong CI/CD:**
- Khi chạy thử chiều ngược (đánh giá v1 với `--baseline reports/eval_v2.json`), `run_eval.py` phát hiện **20 câu bị regression**, in `Quality gate: ❌ FAIL` và thoát với **exit code 1**.
- Workflow GitHub Actions đã được thiết lập tại [.github/workflows/eval.yml](.github/workflows/eval.yml): trên mỗi `pull_request`, CI khởi chạy agent v2 và gọi `python eval/run_eval.py --url http://localhost:8002 --min-accuracy 0.85 --baseline ../../../reports/eval_v2.json`. Nếu accuracy tụt dưới 85% hoặc xuất hiện dù chỉ 1 câu regression, `run_eval.py` trả về **exit code 1**, làm step CI fail và GitHub branch protection sẽ tự động chặn merge PR.

---

## 4. Observability stack (production)

### 4.1 Screenshot & Trả lời Exercise 7.4

- [x] Dashboard Grafana khi đang có tải (30 users, 2 instances): [grafana-dashboard.png](screenshots/grafana-dashboard.png)
- [x] Một trace chậm trong Jaeger (span `chat mock-llm-small` chiếm 1683.17 ms): [jaeger-slow-trace.png](screenshots/jaeger-slow-trace.png)
- [x] Một trace lỗi trong Jaeger (`503`, đánh dấu lỗi trên các span): [jaeger-error-trace.png](screenshots/jaeger-error-trace.png)
- [x] Trang Alerts của Prometheus với **4/4 alert đang firing** đồng thời: [prometheus-alert-firing.png](screenshots/prometheus-alert-firing.png)

**Kết quả quan sát & Trả lời câu hỏi Exercise 7.4 (30 users, 2 instances, đo từ Prometheus & Grafana):**
1. **p95 và avg:** Đo tại thời điểm chạy ổn định 30 users, `p95 = 298.91 ms` (trên Grafana tại thời điểm chụp: `290.69 ms`), `avg = 259.63 ms`, trong khi `p99` trên biểu đồ duy trì quanh `~1.7–1.8 s`. Khoảng cách nhỏ giữa `avg` và `p95` (~39 ms) cho thấy >95% request xử lý rất ổn định, nhưng khoảng cách cực lớn giữa `avg` (~260 ms) và `p99` (~1.8 s) phản ánh rõ hiện tượng **tail latency** từ 3% request LLM chậm bất thường.
2. **Panel "Requests/s theo instance":** Nginx chia tải **rất đều** giữa 2 instance theo round-robin: `172.18.0.5:8000` nhận **8.36 req/s** và `172.18.0.8:8000` nhận **8.02 req/s** (tỉ lệ ~51% / 49%). Khi gọi `POST /ask` liên tiếp qua `localhost:8080`, header `X-Served-By` luân phiên chính xác giữa `172.18.0.8:8000` và `172.18.0.5:8000`.
3. **Vì sao `input tokens/s` lớn hơn `output tokens/s`?** Thực đo từ Prometheus: `input = 1264.54 tokens/s`, `output = 665.15 tokens/s` (gấp ~1.9 lần). Nguyên nhân là ở kiến trúc RAG (agent v2), prompt đầu vào phải chứa đồng thời `SYSTEM_PROMPT` + tài liệu context truy xuất từ knowledge base + câu hỏi người dùng, trong khi câu trả lời đầu ra ngắn gọn hơn nhiều.
4. **`curl -i http://localhost:8080/metrics` trả về gì và vì sao?** Trả về **`HTTP/1.1 404 Not Found`**. Trong `nginx/nginx.conf` có rule `location = /metrics { return 404; }` nhằm chặn truy cập công khai từ bên ngoài vì `/metrics` có thể làm lộ thông tin nội bộ (danh sách route, lưu lượng, model đang dùng, chi phí). Chỉ Prometheus bên trong mạng nội bộ Docker (`obs_net`) mới scrape trực tiếp `agent:8000/metrics`.

### 4.2 Thí nghiệm "phá hệ thống" & Alert rules

Unit test alert rules bằng `promtool`:
```bash
docker run --rm -v "$PWD/prometheus:/p" --entrypoint promtool prom/prometheus:v3.16.0 test rules /p/alert_rules_test.yml
# Output: Processing test file: /p/alert_rules_test.yml → SUCCESS (exit code 0)
```

Kết quả 5 thí nghiệm chaos (giữ tải 30 users bằng Locust):

| # | Thay đổi | Alert nào firing | Thời gian từ lúc đổi → firing | Panel nào phản ánh rõ nhất |
|---|---|---|---|---|
| A | `MOCK_ERROR_RATE=0.2` | `AgentHighErrorRate` | **85 giây** (chuyển `pending` ở 25s + `for: 1m`) | `Error rate`, `Requests/s theo status code` (503 tăng mạnh), `LLM calls theo kết quả` |
| B | `MOCK_SLOW_RATE=0.3` | `AgentHighLatencyP95` | **140 giây** (chuyển `pending` ở 20s + `for: 2m`) | `Latency p95`, `Latency /ask — p50 / p95 / p99`, `LLM latency p95 theo model` |
| C | `LLM_MODEL=mock-llm-large` | `LLMCostBurnRateHigh` | **Đang firing sẵn (0s)** từ phiên benchmark trước do cửa sổ `[5m]` đã vượt `$2/giờ`, và tiếp tục duy trì firing liên tục khi chi phí tăng ~16× (nếu khởi động mới từ 0 sẽ mất ~2m15s do `for: 2m`) | `Cost burn rate (USD/giờ)`, `LLM cost (1h)`, bảng `Phiên bản đang chạy` |
| D | `docker pause` 1 instance (`agent-1`) | `AgentInstanceDown` | **40 giây** (chuyển `pending` sau ~10s + `for: 30s`) | `Instances up` (giảm từ 2 → 1), `Requests/s theo instance` |
| E | `AGENT_VERSION=v1` | **Không có alert mới nào cho suy giảm chất lượng** | Không kích hoạt (với lỗi/latency bình thường sẽ không bao giờ firing) | `Retrieval hit ratio (agent v2)` mất dữ liệu (rỗng), `Tokens/s` giảm mạnh (input 1264.5 → 480.3 tok/s, output 665.2 → 261.9 tok/s), bảng `Phiên bản đang chạy` đổi sang `v1` |

**Phân tích thí nghiệm D (`docker pause` & lỗi 504):**
- Dùng `docker pause` (thay vì `docker stop`) vì Prometheus khám phá target qua `dns_sd_configs`: container bị `stop` sẽ bị xoá khỏi Docker DNS nên Prometheus không còn target để báo `up == 0`, còn container bị `pause` vẫn tồn tại trong DNS nhưng treo không trả lời `/metrics` nên kích hoạt `AgentInstanceDown`.
- Trong lúc `agent-1` bị pause, Locust ghi nhận **28 lỗi `HTTP 504 Gateway Time-out`** trên `POST /ask` (do Nginx chờ quá `proxy_read_timeout 10s`), nhưng panel `Error rate` của agent không đếm các lỗi 504 này vì request bị treo không bao giờ hoàn tất qua middleware của agent. Do đó production bắt buộc phải giám sát cả ở tầng Load Balancer / Nginx hoặc dùng synthetic check từ bên ngoài.

**Thí nghiệm E không làm alert nào firing. Cách phát hiện loại sự cố này trong production:**
1. **Chạy Eval tự động (Quality Gate) trong CI/CD** trước mỗi lần deploy (như `.github/workflows/eval.yml`) để chặn sớm thay đổi làm tụt accuracy trên golden dataset.
2. **Giám sát metric nghiệp vụ / RAG riêng của AI Agent:** đặt alert khi `retrieval_hit_ratio` tụt đột ngột (vd < 50% hoặc mất series), khi `agent_info{version=...}` thay đổi ngoài kế hoạch, hoặc khi phân bố `input_tokens` thay đổi bất thường (như ở thí nghiệm E giảm từ ~1265 xuống ~480 tok/s).
3. **Online Evaluation trên traffic thật:** lấy mẫu (sampling) một tỉ lệ nhỏ request production (vd 1–5%) để chấm điểm liên tục bằng LLM-as-a-judge hoặc theo dõi phản hồi người dùng (thumbs up/down, tỉ lệ hỏi lại).

### 4.3 Debug bằng trace

**Trace chậm nhất đã phân tích (từ Jaeger & agent JSON logs):**
- `trace_id`: `9edf11f0f65f9b520ebce3adbf596f99`
- Tổng thời gian (`POST /ask`): **2278.55 ms** (gồm `agent.run`: 1781.32 ms, `agent.retrieve_context`: 98.00 ms, `chat mock-llm-small`: 1683.17 ms)
- Span chiếm nhiều thời gian nhất: **`chat mock-llm-small`** (**1683.17 ms**, chiếm **73.9%** tổng thời gian request và **94.5%** thời gian của `agent.run`) — chứng minh nút thắt nằm ở lời gọi LLM upstream chứ không phải bước retrieval hay code nghiệp vụ.
- Dòng log JSON tương ứng (grep theo `trace_id` `9edf11f0f65f9b520ebce3adbf596f99`):

```json
{"ts": "2026-11-25T09:27:44.222547+00:00", "level": "INFO", "service": "observable-agent", "instance": "2a933a7a09c2", "event": "llm_call", "trace_id": "9edf11f0f65f9b520ebce3adbf596f99", "span_id": "7daea6dd56c22e2f", "request_id": "dd4cd7b8a382", "model": "mock-llm-small", "agent_version": "v2", "input_tokens": 74, "output_tokens": 37, "cost_usd": 3.3e-05, "llm_ms": 1681.9}
{"ts": "2026-11-25T09:27:44.222894+00:00", "level": "INFO", "service": "observable-agent", "instance": "2a933a7a09c2", "event": "http_request", "trace_id": "9edf11f0f65f9b520ebce3adbf596f99", "span_id": "7daea6dd56c22e2f", "request_id": "dd4cd7b8a382", "method": "POST", "route": "/ask", "status": 200, "ms": 2278.0}
```

**Trace lỗi đã đối chiếu (`llm_error`):**
- `trace_id`: `d5f35af311513ad707ca7dff3cee62fb` (xem [jaeger-error-trace.png](screenshots/jaeger-error-trace.png))
- Dòng log JSON tương ứng:

```json
{"ts": "2026-11-25T09:30:26.812287+00:00", "level": "INFO", "service": "observable-agent", "instance": "2a933a7a09c2", "event": "llm_error", "trace_id": "d5f35af311513ad707ca7dff3cee62fb", "span_id": "fc732d926ae61087", "request_id": "28bc56cca5c6", "error": "Upstream LLM error: 503 Service Unavailable (mock)"}
```

---

## 5. Benchmark scaling (production, Locust headless, 100 users, 2 phút)

Nguồn dữ liệu: [scale_1_stats.csv](benchmark-results/scale_1_stats.csv), [scale_3_stats.csv](benchmark-results/scale_3_stats.csv).

**Theo endpoint chính `POST /ask`:**

| Số instance | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
|---:|---:|---:|---:|---:|---:|
| 1 | 58.45 | 200 | 610 | 1700 | 68 / 7000 (0.97%) |
| 3 | 59.50 | 200 | 310 | 1700 | 57 / 7125 (0.80%) |

**Tổng hợp (`Aggregated` — gồm `POST /ask` + `GET /health`):**

| Số instance | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
|---:|---:|---:|---:|---:|---:|
| 1 | 64.69 | 200 | 560 | 1700 | 68 / 7747 (0.88%) |
| 3 | 65.42 | 200 | 290 | 1700 | 57 / 7833 (0.73%) |

**Giải thích kết quả:**
- **p95 cải thiện rõ rệt (giảm gần một nửa từ 610 ms → 310 ms trên `/ask`, và `/health` p95 giảm từ 100 ms → 27 ms):** Ở mức 100 users song song với giới hạn CPU `0.5 vCPU/container`, 1 instance đơn bắt đầu bị nghẽn vòng lặp sự kiện (event loop queueing), kéo p95 vượt 600 ms. Scale lên 3 instance phân tán tải đều giúp triệt tiêu độ trễ xếp hàng ở tầng ứng dụng.
- **Tuy nhiên `p50` (200 ms), `p99` (1700 ms) và `RPS` (~59.5 req/s trên `/ask`) gần như không đổi:**
  1. **Nút thắt latency nằm ở upstream LLM (`mock_llm`):** độ trễ cơ sở ~120–180 ms + retrieval ~20 ms quyết định sàn `p50 = 200 ms`, còn 3% request chậm thêm 1500 ms quyết định trần `p99 = 1700 ms`. Thêm bao nhiêu replica agent cũng không làm LLM trả lời nhanh hơn.
  2. **Giới hạn tải đầu vào (closed-loop workload):** 100 Locust user nghỉ `0.5–2.0s` (trung bình 1.25 s) giữa mỗi request, cộng thời gian xử lý ~0.25 s → tối đa ~100 / 1.5 ≈ 66 req/s tổng cộng. Muốn tối ưu latency sâu hơn cần tối ưu tầng LLM (caching, streaming, prompt ngắn hơn, model nhanh hơn hoặc fallback provider).

---

## 6. Kết luận

- **3 điều rút ra về benchmark & observability:**
  1. **Luôn đo bằng phân vị (`p95`/`p99`) và `cost/câu đúng`:** giá trị trung bình che giấu tail latency (khi `MOCK_SLOW_RATE=0.1`, avg chỉ 352 ms nhưng p95 đã vọt lên 1703 ms), còn `cost/câu đúng` mới phản ánh đúng hiệu quả kinh tế của RAG (v2 đắt gấp đôi token nhưng rẻ hơn ~11.7 lần trên mỗi câu đúng).
  2. **Liên kết 3 trụ cột Metrics → Traces → Logs giúp rút ngắn MTTR:** Prometheus/Grafana phát hiện *có vấn đề gì*, Jaeger chỉ đích xác *chậm ở span nào* (`chat mock-llm-small` chiếm 73.9%), và `trace_id` trong JSON log nối thẳng tới chi tiết lỗi/payload.
  3. **Observability hạ tầng không thay thế được đánh giá chất lượng AI:** thí nghiệm E chứng minh khi chuyển sang `v1`, toàn bộ chỉ số hạ tầng vẫn xanh trong khi độ chính xác sụp từ 100% xuống 4.3% — cần kết hợp CI eval quality gate và giám sát metric nghiệp vụ LLM/RAG.
- **Nếu đưa agent lên production thật, sẽ bổ sung thêm các metric & alert sau:**
  - **Metric & Alert tầng Load Balancer / Synthetic probe:** theo dõi tỉ lệ `502`/`504` tại Nginx/Ingress để bắt lỗi khi backend treo (khắc phục điểm mù ở thí nghiệm D).
  - **Time-To-First-Token (TTFT) & Tokens-per-second (TPS)** cho streaming response để đo cảm nhận tốc độ thật của người dùng.
  - **Retrieval quality & Empty/Fallback response rate:** cảnh báo khi `agent_retrieval_total{result="miss"}` vượt ngưỡng (vd > 30% trong 5 phút) hoặc khi tỉ lệ câu trả lời fallback/từ chối tăng đột biến.
  - **Redis & Rate-limit / Budget metrics:** theo dõi số lần trả `429` (rate limit), `402` (vượt ngân sách) và latency kết nối Redis để phát hiện sớm hành vi lạm dụng hoặc cạn budget trước khi người dùng bị chặn hàng loạt.
