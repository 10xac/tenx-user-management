"""
Load Testing — Simulate normal-to-high concurrent user traffic.
Measures response times, throughput, and error rates under expected load.

Industry standard: Verify the system handles expected peak traffic with
acceptable latency (p95 < SLA threshold) and zero server errors.

SLA Targets:
  - Single trainee:  p95 < 500ms, error rate < 1%
  - Webhook:         p95 < 200ms, error rate < 1%
  - Batch upload:    p95 < 2000ms (acceptance), error rate < 1%
"""
import time
import pytest
from concurrent.futures import ThreadPoolExecutor, as_completed

from tests.performance.conftest import trainee_payload, webhook_payload, make_csv, ResponseTimer


# ============================================================================
# Single Trainee Endpoint — Load Tests
# ============================================================================

class TestSingleTraineeLoad:
    """Simulate multiple users creating trainees concurrently."""

    def test_sequential_50_requests(self, client, timer):
        """Baseline: 50 sequential requests to measure per-request latency."""
        for i in range(50):
            start = time.perf_counter()
            resp = client.post("/trainee/single", json=trainee_payload(i))
            timer.record(time.perf_counter() - start, resp.status_code)

        summary = timer.summary()
        assert timer.error_rate == 0, f"Errors detected: {summary}"
        assert timer.p95 < 0.5, f"p95 {summary['p95_ms']}ms exceeds 500ms SLA"
        assert timer.count == 50

    def test_concurrent_20_users(self, client, timer):
        """Simulate 20 concurrent users hitting /trainee/single."""
        def make_request(idx):
            start = time.perf_counter()
            resp = client.post("/trainee/single", json=trainee_payload(idx))
            return time.perf_counter() - start, resp.status_code

        with ThreadPoolExecutor(max_workers=20) as pool:
            futures = [pool.submit(make_request, i) for i in range(20)]
            for f in as_completed(futures):
                elapsed, status = f.result()
                timer.record(elapsed, status)

        summary = timer.summary()
        assert timer.error_rate == 0, f"Errors under concurrent load: {summary}"
        assert timer.count == 20

    def test_concurrent_50_users(self, client, timer):
        """Simulate 50 concurrent users — moderate load."""
        def make_request(idx):
            start = time.perf_counter()
            resp = client.post("/trainee/single", json=trainee_payload(idx))
            return time.perf_counter() - start, resp.status_code

        with ThreadPoolExecutor(max_workers=50) as pool:
            futures = [pool.submit(make_request, i) for i in range(50)]
            for f in as_completed(futures):
                elapsed, status = f.result()
                timer.record(elapsed, status)

        summary = timer.summary()
        assert timer.error_rate == 0, f"Errors at 50 concurrent users: {summary}"
        assert timer.p95 < 1.0, f"p95 {summary['p95_ms']}ms too high at 50 concurrent users"

    def test_burst_100_requests(self, client, timer):
        """Burst: 100 requests in rapid succession with 10 concurrent workers."""
        def make_request(idx):
            start = time.perf_counter()
            resp = client.post("/trainee/single", json=trainee_payload(idx))
            return time.perf_counter() - start, resp.status_code

        with ThreadPoolExecutor(max_workers=10) as pool:
            futures = [pool.submit(make_request, i) for i in range(100)]
            for f in as_completed(futures):
                elapsed, status = f.result()
                timer.record(elapsed, status)

        summary = timer.summary()
        assert timer.error_rate < 1.0, f"Error rate {summary['error_rate_pct']}% exceeds 1% SLA"
        assert timer.count == 100

    def test_throughput_measurement(self, client):
        """Measure requests per second (RPS) throughput."""
        count = 50
        start = time.perf_counter()
        for i in range(count):
            client.post("/trainee/single", json=trainee_payload(i))
        total_time = time.perf_counter() - start

        rps = count / total_time
        # Should handle at least 10 requests/sec with mocked externals
        assert rps > 10, f"Throughput {rps:.1f} RPS below minimum 10 RPS"


# ============================================================================
# Webhook Endpoint — Load Tests
# ============================================================================

class TestWebhookLoad:
    """Webhook endpoint should be extremely fast (lightweight JSON echo)."""

    def test_sequential_100_webhooks(self, client, timer):
        for i in range(100):
            start = time.perf_counter()
            resp = client.post("/webhook", json=webhook_payload(i))
            timer.record(time.perf_counter() - start, resp.status_code)

        summary = timer.summary()
        assert timer.error_rate == 0, f"Webhook errors: {summary}"
        assert timer.p95 < 0.2, f"Webhook p95 {summary['p95_ms']}ms exceeds 200ms SLA"

    def test_concurrent_50_webhooks(self, client, timer):
        def send_webhook(idx):
            start = time.perf_counter()
            resp = client.post("/webhook", json=webhook_payload(idx))
            return time.perf_counter() - start, resp.status_code

        with ThreadPoolExecutor(max_workers=50) as pool:
            futures = [pool.submit(send_webhook, i) for i in range(50)]
            for f in as_completed(futures):
                elapsed, status = f.result()
                timer.record(elapsed, status)

        assert timer.error_rate == 0
        assert timer.count == 50

    def test_webhook_throughput(self, client):
        count = 100
        start = time.perf_counter()
        for i in range(count):
            client.post("/webhook", json=webhook_payload(i))
        total_time = time.perf_counter() - start

        rps = count / total_time
        assert rps > 50, f"Webhook throughput {rps:.1f} RPS below minimum 50 RPS"


# ============================================================================
# Batch Upload Endpoint — Load Tests
# ============================================================================

class TestBatchUploadLoad:
    """Batch upload acceptance (HTTP response) should be fast; processing is async."""

    def test_sequential_10_batch_uploads(self, authed_client, timer):
        for i in range(10):
            csv_data = make_csv(5)
            start = time.perf_counter()
            resp = authed_client.post(
                "/trainee/batch",
                files={"file": (f"batch_{i}.csv", csv_data, "text/csv")},
                data={"run_stage": "dev", "batch": str(i), "is_mock": "true",
                      "login_url": "https://10academy.org/login"},
            )
            timer.record(time.perf_counter() - start, resp.status_code)

        summary = timer.summary()
        assert timer.error_rate == 0, f"Batch upload errors: {summary}"
        assert timer.p95 < 2.0, f"Batch upload p95 {summary['p95_ms']}ms exceeds 2000ms SLA"

    def test_concurrent_5_batch_uploads(self, authed_client, timer):
        def upload_batch(idx):
            csv_data = make_csv(5)
            start = time.perf_counter()
            resp = authed_client.post(
                "/trainee/batch",
                files={"file": (f"batch_{idx}.csv", csv_data, "text/csv")},
                data={"run_stage": "dev", "batch": str(idx), "is_mock": "true",
                      "login_url": "https://10academy.org/login"},
            )
            return time.perf_counter() - start, resp.status_code

        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = [pool.submit(upload_batch, i) for i in range(5)]
            for f in as_completed(futures):
                elapsed, status = f.result()
                timer.record(elapsed, status)

        assert timer.error_rate == 0
        assert timer.count == 5


# ============================================================================
# Mixed Endpoint Load Test
# ============================================================================

class TestMixedEndpointLoad:
    """Simulate realistic traffic pattern: 60% trainee, 30% webhook, 10% other."""

    def test_mixed_traffic_100_requests(self, client, timer):
        import random
        random.seed(42)

        def make_mixed_request(idx):
            roll = random.random()
            start = time.perf_counter()
            if roll < 0.6:
                resp = client.post("/trainee/single", json=trainee_payload(idx))
            elif roll < 0.9:
                resp = client.post("/webhook", json=webhook_payload(idx))
            else:
                resp = client.get("/openapi.json")
            return time.perf_counter() - start, resp.status_code

        with ThreadPoolExecutor(max_workers=20) as pool:
            futures = [pool.submit(make_mixed_request, i) for i in range(100)]
            for f in as_completed(futures):
                elapsed, status = f.result()
                timer.record(elapsed, status)

        summary = timer.summary()
        assert timer.error_rate < 1.0, f"Mixed load error rate: {summary}"
        assert timer.count == 100


# ============================================================================
# Latency Consistency Tests
# ============================================================================

class TestLatencyConsistency:
    """Verify response times are consistent (low variance)."""

    def test_response_time_stability(self, client, timer):
        """Standard deviation of response times should be reasonable."""
        import statistics as stats

        for i in range(30):
            start = time.perf_counter()
            resp = client.post("/trainee/single", json=trainee_payload(i))
            timer.record(time.perf_counter() - start, resp.status_code)

        if len(timer.times) > 1:
            stdev = stats.stdev(timer.times)
            mean = timer.mean
            cv = stdev / mean if mean > 0 else 0  # coefficient of variation
            # CV under 1.0 means reasonable consistency
            assert cv < 1.5, f"Response time CV {cv:.2f} too high (stdev={stdev*1000:.1f}ms, mean={mean*1000:.1f}ms)"

    def test_no_degradation_over_time(self, client):
        """Response times should not degrade significantly over sequential requests."""
        first_10 = []
        last_10 = []

        for i in range(50):
            start = time.perf_counter()
            client.post("/trainee/single", json=trainee_payload(i))
            elapsed = time.perf_counter() - start
            if i < 10:
                first_10.append(elapsed)
            if i >= 40:
                last_10.append(elapsed)

        avg_first = sum(first_10) / len(first_10)
        avg_last = sum(last_10) / len(last_10)
        # Last 10 should not be more than 3x slower than first 10
        assert avg_last < avg_first * 3, (
            f"Performance degraded: first_10_avg={avg_first*1000:.1f}ms, "
            f"last_10_avg={avg_last*1000:.1f}ms"
        )
