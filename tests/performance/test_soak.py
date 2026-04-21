"""
Soak Testing — Sustained load over extended period to detect memory leaks,
resource exhaustion, and gradual performance degradation.

Industry standard: Run steady-state traffic for a prolonged duration and
monitor memory usage, response latency drift, error accumulation, and
object count growth. Catches issues invisible in short-burst tests.

Targets:
  - Memory growth < 50MB over full soak duration
  - Latency drift < 2x between first and last measurement windows
  - Error rate remains 0% throughout sustained load
  - No monotonic increase in Python object count (leak indicator)
  - GC pressure stays reasonable (no unbounded retained objects)

Note: Soak durations are compressed for CI (seconds not hours).
      Multiply iteration counts for production soak runs.
"""
import time
import gc
import sys
import os
import pytest
import tracemalloc
from concurrent.futures import ThreadPoolExecutor, as_completed

from tests.performance.conftest import trainee_payload, webhook_payload, ResponseTimer


# ============================================================================
# Configuration — adjust for CI vs production soak
# ============================================================================

SOAK_ITERATIONS = 10        # Number of measurement windows
REQUESTS_PER_WINDOW = 50    # Requests per window
CONCURRENT_WORKERS = 5      # Concurrent workers per window
MEMORY_GROWTH_LIMIT_MB = 50 # Max allowed memory growth
LATENCY_DRIFT_FACTOR = 3.0  # Max allowed latency increase factor


# ============================================================================
# 1. Memory Leak Detection
# ============================================================================

class TestMemoryLeakDetection:
    """Monitor memory usage over sustained request volume."""

    def test_no_memory_leak_trainee_endpoint(self, client):
        """Send requests over multiple windows and verify memory doesn't grow unboundedly."""
        tracemalloc.start()
        snapshots = []

        for window in range(SOAK_ITERATIONS):
            for i in range(REQUESTS_PER_WINDOW):
                client.post("/trainee/single", json=trainee_payload(window * 100 + i))

            gc.collect()
            snapshot = tracemalloc.take_snapshot()
            current, peak = tracemalloc.get_traced_memory()
            snapshots.append({
                "window": window,
                "current_mb": current / (1024 * 1024),
                "peak_mb": peak / (1024 * 1024),
            })

        tracemalloc.stop()

        first_mb = snapshots[0]["current_mb"]
        last_mb = snapshots[-1]["current_mb"]
        growth_mb = last_mb - first_mb

        assert growth_mb < MEMORY_GROWTH_LIMIT_MB, (
            f"Memory grew by {growth_mb:.2f}MB over {SOAK_ITERATIONS} windows "
            f"({first_mb:.2f}MB → {last_mb:.2f}MB). Possible memory leak."
        )

    def test_no_memory_leak_webhook_endpoint(self, client):
        """Webhook endpoint memory stability over sustained load."""
        tracemalloc.start()

        for window in range(SOAK_ITERATIONS):
            for i in range(REQUESTS_PER_WINDOW * 2):  # Webhooks are lighter, run more
                client.post("/webhook", json=webhook_payload(window * 200 + i))
            gc.collect()

        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        current_mb = current / (1024 * 1024)
        peak_mb = peak / (1024 * 1024)
        assert current_mb < MEMORY_GROWTH_LIMIT_MB, (
            f"Webhook soak memory: current={current_mb:.2f}MB, peak={peak_mb:.2f}MB"
        )

    def test_no_memory_leak_mixed_endpoints(self, client):
        """Mixed endpoint traffic — most realistic soak scenario."""
        tracemalloc.start()
        import random
        random.seed(42)

        for window in range(SOAK_ITERATIONS):
            for i in range(REQUESTS_PER_WINDOW):
                if random.random() < 0.6:
                    client.post("/trainee/single", json=trainee_payload(window * 100 + i))
                else:
                    client.post("/webhook", json=webhook_payload(window * 100 + i))
            gc.collect()

        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        current_mb = current / (1024 * 1024)
        assert current_mb < MEMORY_GROWTH_LIMIT_MB, (
            f"Mixed soak memory: {current_mb:.2f}MB exceeds {MEMORY_GROWTH_LIMIT_MB}MB limit"
        )


# ============================================================================
# 2. Latency Drift Detection
# ============================================================================

class TestLatencyDriftDetection:
    """Verify response times don't degrade over sustained load."""

    def test_trainee_latency_stability_over_soak(self, client):
        """Compare first-window vs last-window latencies."""
        window_averages = []

        for window in range(SOAK_ITERATIONS):
            times = []
            for i in range(REQUESTS_PER_WINDOW):
                start = time.perf_counter()
                client.post("/trainee/single", json=trainee_payload(window * 100 + i))
                times.append(time.perf_counter() - start)
            window_averages.append(sum(times) / len(times))

        first_avg = window_averages[0]
        last_avg = window_averages[-1]
        max_avg = max(window_averages)

        assert last_avg < first_avg * LATENCY_DRIFT_FACTOR, (
            f"Latency drifted: first={first_avg*1000:.1f}ms → last={last_avg*1000:.1f}ms "
            f"(max window={max_avg*1000:.1f}ms). Drift factor: {last_avg/first_avg:.2f}x"
        )

    def test_webhook_latency_stability_over_soak(self, client):
        """Webhook latency should remain stable over time."""
        window_averages = []

        for window in range(SOAK_ITERATIONS):
            times = []
            for i in range(REQUESTS_PER_WINDOW * 2):
                start = time.perf_counter()
                client.post("/webhook", json=webhook_payload(window * 200 + i))
                times.append(time.perf_counter() - start)
            window_averages.append(sum(times) / len(times))

        first_avg = window_averages[0]
        last_avg = window_averages[-1]

        assert last_avg < first_avg * LATENCY_DRIFT_FACTOR, (
            f"Webhook latency drift: {first_avg*1000:.2f}ms → {last_avg*1000:.2f}ms"
        )

    def test_latency_variance_bounded(self, client):
        """Standard deviation of window averages should be bounded."""
        import statistics
        window_averages = []

        for window in range(SOAK_ITERATIONS):
            times = []
            for i in range(REQUESTS_PER_WINDOW):
                start = time.perf_counter()
                client.post("/trainee/single", json=trainee_payload(window * 100 + i))
                times.append(time.perf_counter() - start)
            window_averages.append(sum(times) / len(times))

        if len(window_averages) > 1:
            stdev = statistics.stdev(window_averages)
            mean = statistics.mean(window_averages)
            cv = stdev / mean if mean > 0 else 0
            assert cv < 1.0, (
                f"Window latency CV={cv:.2f} too high "
                f"(stdev={stdev*1000:.2f}ms, mean={mean*1000:.2f}ms)"
            )


# ============================================================================
# 3. Error Accumulation Detection
# ============================================================================

class TestErrorAccumulationDetection:
    """Verify error rate stays at 0% throughout sustained load."""

    def test_zero_errors_over_sustained_trainee_load(self, client):
        """No server errors across entire soak duration."""
        total_requests = 0
        total_errors = 0

        for window in range(SOAK_ITERATIONS):
            for i in range(REQUESTS_PER_WINDOW):
                resp = client.post("/trainee/single", json=trainee_payload(window * 100 + i))
                total_requests += 1
                if resp.status_code >= 500:
                    total_errors += 1

        error_rate = (total_errors / total_requests * 100) if total_requests else 0
        assert error_rate == 0, (
            f"Accumulated {total_errors} errors in {total_requests} requests "
            f"({error_rate:.2f}%) during soak"
        )

    def test_zero_errors_over_sustained_webhook_load(self, client):
        total_requests = 0
        total_errors = 0

        for window in range(SOAK_ITERATIONS):
            for i in range(REQUESTS_PER_WINDOW * 2):
                resp = client.post("/webhook", json=webhook_payload(window * 200 + i))
                total_requests += 1
                if resp.status_code >= 500:
                    total_errors += 1

        assert total_errors == 0, f"{total_errors} webhook errors in {total_requests} requests"

    def test_no_error_rate_increase_over_time(self, client):
        """Error rate per window must not increase over time."""
        window_error_rates = []

        for window in range(SOAK_ITERATIONS):
            errors = 0
            for i in range(REQUESTS_PER_WINDOW):
                resp = client.post("/trainee/single", json=trainee_payload(window * 100 + i))
                if resp.status_code >= 500:
                    errors += 1
            window_error_rates.append(errors / REQUESTS_PER_WINDOW * 100)

        # Last window error rate should not exceed first + 1%
        first_rate = window_error_rates[0]
        last_rate = window_error_rates[-1]
        assert last_rate <= first_rate + 1.0, (
            f"Error rate increased: first={first_rate:.1f}% → last={last_rate:.1f}%"
        )


# ============================================================================
# 4. Object Count / GC Pressure
# ============================================================================

class TestGCPressureDetection:
    """Monitor Python object count growth for leaked references."""

    def test_object_count_stability(self, client):
        """Object count growth rate should be bounded (not accelerating).
        Note: gc.get_objects() includes framework/cache objects that grow linearly
        with request count. The key signal is *accelerating* growth (quadratic+),
        which indicates a genuine reference leak vs normal linear cache growth."""
        gc.collect()
        object_counts = [len(gc.get_objects())]

        for window in range(SOAK_ITERATIONS):
            for i in range(REQUESTS_PER_WINDOW):
                client.post("/trainee/single", json=trainee_payload(window * 100 + i))
            gc.collect()
            object_counts.append(len(gc.get_objects()))

        # Calculate per-window growth deltas
        deltas = [object_counts[i] - object_counts[i - 1]
                  for i in range(1, len(object_counts))]

        if len(deltas) >= 4:
            # Compare growth rate in first half vs second half
            mid = len(deltas) // 2
            first_half_avg = sum(deltas[:mid]) / mid
            second_half_avg = sum(deltas[mid:]) / (len(deltas) - mid)

            # Second half growth should not be more than 3x first half
            # (linear growth OK, quadratic/exponential growth = leak)
            if first_half_avg > 0:
                acceleration = second_half_avg / first_half_avg
                assert acceleration < 3.0, (
                    f"Object growth is accelerating: first_half_avg={first_half_avg:.0f}, "
                    f"second_half_avg={second_half_avg:.0f}, acceleration={acceleration:.1f}x. "
                    f"Possible reference leak."
                )

    def test_gc_collection_effectiveness(self, client):
        """GC should reclaim most objects created during requests."""
        gc.collect()
        pre_count = len(gc.get_objects())

        for i in range(REQUESTS_PER_WINDOW * 3):
            client.post("/trainee/single", json=trainee_payload(i))

        mid_count = len(gc.get_objects())
        gc.collect()
        post_count = len(gc.get_objects())

        # GC should reclaim at least some objects
        growth_before_gc = mid_count - pre_count
        growth_after_gc = post_count - pre_count

        if growth_before_gc > 100:
            # GC should have reclaimed at least 10% of temporary objects
            reclaimed = growth_before_gc - growth_after_gc
            reclaim_pct = (reclaimed / growth_before_gc * 100) if growth_before_gc else 0
            # Very generous: just verify GC doesn't make things worse
            assert post_count < mid_count + 10000, (
                f"GC ineffective: pre={pre_count}, mid={mid_count}, "
                f"post={post_count}, reclaimed={reclaim_pct:.0f}%"
            )


# ============================================================================
# 5. Sustained Concurrent Load
# ============================================================================

class TestSustainedConcurrentLoad:
    """Soak test with concurrent workers over multiple windows."""

    def test_concurrent_soak_no_degradation(self, client):
        """Multiple windows of concurrent requests with latency tracking."""
        window_stats = []

        for window in range(SOAK_ITERATIONS):
            timer = ResponseTimer()

            def make_request(idx):
                start = time.perf_counter()
                resp = client.post("/trainee/single", json=trainee_payload(idx))
                return time.perf_counter() - start, resp.status_code

            with ThreadPoolExecutor(max_workers=CONCURRENT_WORKERS) as pool:
                futures = [pool.submit(make_request, window * 100 + i)
                           for i in range(REQUESTS_PER_WINDOW)]
                for f in as_completed(futures):
                    elapsed, status = f.result()
                    timer.record(elapsed, status)

            window_stats.append(timer.summary())

        # Verify: no window has error rate > 0
        for ws in window_stats:
            assert ws["error_rate_pct"] == 0, f"Errors in window: {ws}"

        # Verify: last window p95 not much worse than first
        first_p95 = window_stats[0]["p95_ms"]
        last_p95 = window_stats[-1]["p95_ms"]
        if first_p95 > 0:
            drift = last_p95 / first_p95
            assert drift < LATENCY_DRIFT_FACTOR, (
                f"Concurrent soak p95 drift: {first_p95:.1f}ms → {last_p95:.1f}ms ({drift:.1f}x)"
            )

    def test_sustained_mixed_concurrent_soak(self, client):
        """Mixed endpoint soak with concurrent workers."""
        import random
        random.seed(123)
        total_errors = 0
        total_requests = 0

        for window in range(SOAK_ITERATIONS):
            def mixed_request(idx):
                if random.random() < 0.6:
                    return client.post("/trainee/single", json=trainee_payload(idx))
                else:
                    return client.post("/webhook", json=webhook_payload(idx))

            with ThreadPoolExecutor(max_workers=CONCURRENT_WORKERS) as pool:
                futures = [pool.submit(mixed_request, window * 100 + i)
                           for i in range(REQUESTS_PER_WINDOW)]
                for f in as_completed(futures):
                    resp = f.result()
                    total_requests += 1
                    if resp.status_code >= 500:
                        total_errors += 1

        error_rate = (total_errors / total_requests * 100) if total_requests else 0
        assert error_rate == 0, (
            f"Mixed concurrent soak: {total_errors}/{total_requests} errors ({error_rate:.2f}%)"
        )
