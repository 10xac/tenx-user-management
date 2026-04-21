"""
Simulation Runner
=================
Executes real-time simulation against the deployed user-management API.
Tests every endpoint with proper user data at each tier (100–10000 users).

Saves detailed JSON results for every run to simulation/results/ for
future analysis and visualization.

Usage:
    # Set auth token first
    export SIMULATION_AUTH_TOKEN="your-strapi-jwt-token"

    # Run full simulation
    python -m simulation.runner

    # Run specific tier only
    python -m simulation.runner --tier 100

    # Run specific endpoint only
    python -m simulation.runner --endpoint single

    # Dry run (no actual API calls, just validate setup)
    python -m simulation.runner --dry-run
"""
import argparse
import csv
import io
import json
import sys
import time
import statistics
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx

from simulation.config import (
    BASE_URL, RUN_STAGE, AUTH_TOKEN, USER_TIERS, CONCURRENCY_MAP,
    REQUEST_TIMEOUT, BATCH_CHUNK_SIZE, WEBHOOK_CALLBACK_URL,
    INTER_TIER_DELAY, DEFAULT_BATCH_ID, DEFAULT_GROUP_ID,
    DEFAULT_ROLE, LOGIN_URL, ENDPOINTS, RESULTS_DIR, USER_DATA_DIR,
)
from simulation.generate_users import generate_all, generate_tier, FIELDNAMES


# ============================================================================
# Result collector
# ============================================================================

class SimulationResult:
    """Collects per-request metrics for a single endpoint+tier combination."""

    def __init__(self, endpoint: str, tier: int, concurrency: int):
        self.endpoint = endpoint
        self.tier = tier
        self.concurrency = concurrency
        self.requests = []        # list of per-request dicts
        self.start_time = None
        self.end_time = None

    def record(self, status_code: int, elapsed_sec: float,
               success: bool, response_body: dict | str | None = None,
               error: str | None = None, user_index: int = 0):
        self.requests.append({
            "user_index": user_index,
            "status_code": status_code,
            "elapsed_ms": round(elapsed_sec * 1000, 2),
            "success": success,
            "error": error,
            "response_preview": _truncate(response_body, 300),
        })

    def to_dict(self) -> dict:
        times = [r["elapsed_ms"] for r in self.requests]
        successes = sum(1 for r in self.requests if r["success"])
        errors = sum(1 for r in self.requests if not r["success"])
        status_dist = {}
        for r in self.requests:
            sc = str(r["status_code"])
            status_dist[sc] = status_dist.get(sc, 0) + 1

        return {
            "endpoint": self.endpoint,
            "tier": self.tier,
            "concurrency": self.concurrency,
            "total_requests": len(self.requests),
            "successful": successes,
            "failed": errors,
            "error_rate_pct": round(errors / max(len(self.requests), 1) * 100, 2),
            "status_distribution": status_dist,
            "latency_ms": {
                "min": round(min(times), 2) if times else 0,
                "max": round(max(times), 2) if times else 0,
                "mean": round(statistics.mean(times), 2) if times else 0,
                "median": round(statistics.median(times), 2) if times else 0,
                "p95": round(_percentile(times, 95), 2) if times else 0,
                "p99": round(_percentile(times, 99), 2) if times else 0,
                "stdev": round(statistics.stdev(times), 2) if len(times) > 1 else 0,
            },
            "throughput_rps": round(
                len(self.requests) / max((self.end_time - self.start_time), 0.001), 2
            ) if self.start_time and self.end_time else 0,
            "wall_clock_sec": round(
                (self.end_time - self.start_time), 2
            ) if self.start_time and self.end_time else 0,
            "start_time": datetime.fromtimestamp(self.start_time).isoformat() if self.start_time else None,
            "end_time": datetime.fromtimestamp(self.end_time).isoformat() if self.end_time else None,
            "requests": self.requests,
        }


def _percentile(data: list, p: int) -> float:
    if not data:
        return 0
    s = sorted(data)
    idx = min(int(len(s) * p / 100), len(s) - 1)
    return s[idx]


def _truncate(obj, max_len: int = 300) -> str | None:
    if obj is None:
        return None
    s = json.dumps(obj) if isinstance(obj, (dict, list)) else str(obj)
    return s[:max_len] + "..." if len(s) > max_len else s


# ============================================================================
# HTTP helpers
# ============================================================================

def _headers(auth: bool = False) -> dict:
    h = {"Content-Type": "application/json"}
    if auth and AUTH_TOKEN:
        h["Authorization"] = f"Bearer {AUTH_TOKEN}"
    return h


def _auth_headers_form() -> dict:
    """Headers for multipart form (no Content-Type — httpx sets it)."""
    h = {}
    if AUTH_TOKEN:
        h["Authorization"] = f"Bearer {AUTH_TOKEN}"
    return h


# ============================================================================
# Endpoint simulators
# ============================================================================

def simulate_single(user: dict, idx: int, result: SimulationResult):
    """POST /trainee/single — create a single trainee (no auth)."""
    payload = {
        "config": {
            "run_stage": RUN_STAGE,
            "batch": DEFAULT_BATCH_ID,
            "role": DEFAULT_ROLE,
            "group_id": DEFAULT_GROUP_ID,
            "is_mock": True,
        },
        "trainee": {
            "name": user["name"],
            "email": user["email"],
            "password": user.get("password", "SimPass10!"),
            "nationality": user.get("nationality", ""),
            "gender": user.get("gender", ""),
            "date_of_birth": user.get("date_of_birth", ""),
            "vulnerable": user.get("vulnerable", ""),
            "city_of_residence": user.get("city_of_residence", ""),
            "bio": user.get("bio", ""),
        },
    }
    try:
        start = time.perf_counter()
        with httpx.Client(timeout=REQUEST_TIMEOUT) as client:
            resp = client.post(
                f"{BASE_URL}/trainee/single",
                json=payload,
                headers=_headers(auth=False),
            )
        elapsed = time.perf_counter() - start
        body = _safe_json(resp)
        success = resp.status_code == 200 and (isinstance(body, dict) and body.get("success", False))
        result.record(resp.status_code, elapsed, success, body, user_index=idx)
    except Exception as e:
        result.record(0, 0, False, error=str(e), user_index=idx)


def simulate_admin_single(user: dict, idx: int, result: SimulationResult):
    """POST /trainee/admin-single — create trainee as admin (auth required)."""
    payload = {
        "config": {
            "run_stage": RUN_STAGE,
            "batch": DEFAULT_BATCH_ID,
            "role": DEFAULT_ROLE,
            "group_id": DEFAULT_GROUP_ID,
            "is_mock": True,
        },
        "trainee": {
            "name": user["name"],
            "email": user["email"],
            "password": user.get("password", "SimPass10!"),
            "nationality": user.get("nationality", ""),
            "gender": user.get("gender", ""),
            "date_of_birth": user.get("date_of_birth", ""),
            "vulnerable": user.get("vulnerable", ""),
        },
    }
    try:
        start = time.perf_counter()
        with httpx.Client(timeout=REQUEST_TIMEOUT) as client:
            resp = client.post(
                f"{BASE_URL}/trainee/admin-single",
                json=payload,
                headers=_headers(auth=True),
            )
        elapsed = time.perf_counter() - start
        body = _safe_json(resp)
        success = resp.status_code == 200 and (isinstance(body, dict) and body.get("success", False))
        result.record(resp.status_code, elapsed, success, body, user_index=idx)
    except Exception as e:
        result.record(0, 0, False, error=str(e), user_index=idx)


def simulate_batch(users: list[dict], tier: int, result: SimulationResult):
    """POST /trainee/batch — upload CSV chunk as batch (auth required)."""
    # Split users into chunks and upload each chunk
    chunk_size = BATCH_CHUNK_SIZE
    chunks = [users[i:i + chunk_size] for i in range(0, len(users), chunk_size)]

    for chunk_idx, chunk in enumerate(chunks):
        # Build CSV in memory
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(chunk)
        csv_bytes = buf.getvalue().encode("utf-8")

        try:
            start = time.perf_counter()
            with httpx.Client(timeout=REQUEST_TIMEOUT * 2) as client:
                resp = client.post(
                    f"{BASE_URL}/trainee/batch",
                    headers=_auth_headers_form(),
                    data={
                        "run_stage": RUN_STAGE,
                        "batch": f"{DEFAULT_BATCH_ID}-chunk{chunk_idx}",
                        "role": DEFAULT_ROLE,
                        "group_id": DEFAULT_GROUP_ID,
                        "is_mock": "true",
                        "chunk_size": str(chunk_size),
                        "login_url": LOGIN_URL,
                    },
                    files={"file": (f"batch_{tier}_chunk{chunk_idx}.csv", csv_bytes, "text/csv")},
                )
            elapsed = time.perf_counter() - start
            body = _safe_json(resp)
            success = resp.status_code == 200 and (isinstance(body, dict) and body.get("success", False))
            result.record(resp.status_code, elapsed, success, body, user_index=chunk_idx)
        except Exception as e:
            result.record(0, 0, False, error=str(e), user_index=chunk_idx)


def simulate_webhook(users: list[dict], tier: int, result: SimulationResult):
    """POST /webhook — simulate batch processing callbacks."""
    # Send one webhook per batch chunk to simulate realistic webhook traffic
    chunk_size = BATCH_CHUNK_SIZE
    num_chunks = max(1, len(users) // chunk_size)

    for chunk_idx in range(num_chunks):
        payload = {
            "status": "success",
            "batch": f"{DEFAULT_BATCH_ID}-chunk{chunk_idx}",
            "errors": [],
            "total_processed": min(chunk_size, len(users) - chunk_idx * chunk_size),
            "successful": min(chunk_size, len(users) - chunk_idx * chunk_size),
            "failed": 0,
        }
        try:
            start = time.perf_counter()
            with httpx.Client(timeout=REQUEST_TIMEOUT) as client:
                resp = client.post(
                    f"{BASE_URL}/webhook",
                    json=payload,
                    headers=_headers(auth=False),
                )
            elapsed = time.perf_counter() - start
            body = _safe_json(resp)
            success = resp.status_code == 200
            result.record(resp.status_code, elapsed, success, body, user_index=chunk_idx)
        except Exception as e:
            result.record(0, 0, False, error=str(e), user_index=chunk_idx)


def simulate_env_check(result: SimulationResult):
    """POST /env/check_env_cache — check environment cache (auth required)."""
    payload = {"run_stage": RUN_STAGE, "sname": "tenx/env/vars"}
    try:
        start = time.perf_counter()
        with httpx.Client(timeout=REQUEST_TIMEOUT) as client:
            resp = client.post(
                f"{BASE_URL}/env/check_env_cache",
                json=payload,
                headers=_headers(auth=True),
            )
        elapsed = time.perf_counter() - start
        body = _safe_json(resp)
        success = resp.status_code == 200
        result.record(resp.status_code, elapsed, success, body, user_index=0)
    except Exception as e:
        result.record(0, 0, False, error=str(e), user_index=0)


def simulate_env_refresh(result: SimulationResult):
    """POST /env/refresh_env_vars — refresh secrets (auth required)."""
    payload = {"run_stage": RUN_STAGE, "sname": "tenx/env/vars"}
    try:
        start = time.perf_counter()
        with httpx.Client(timeout=REQUEST_TIMEOUT) as client:
            resp = client.post(
                f"{BASE_URL}/env/refresh_env_vars",
                json=payload,
                headers=_headers(auth=True),
            )
        elapsed = time.perf_counter() - start
        body = _safe_json(resp)
        success = resp.status_code == 200
        result.record(resp.status_code, elapsed, success, body, user_index=0)
    except Exception as e:
        result.record(0, 0, False, error=str(e), user_index=0)


def _safe_json(resp) -> dict | str:
    try:
        return resp.json()
    except Exception:
        return resp.text[:500]


# ============================================================================
# Tier runner (orchestrates concurrent requests)
# ============================================================================

def run_single_tier(users: list[dict], tier: int, endpoint: str,
                    concurrency: int) -> SimulationResult:
    """Run simulation for a single endpoint at a single tier."""
    result = SimulationResult(endpoint, tier, concurrency)
    result.start_time = time.time()

    print(f"    [{endpoint}] tier={tier}, concurrency={concurrency}, users={len(users)}")

    if endpoint == "single":
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = [pool.submit(simulate_single, u, i, result) for i, u in enumerate(users)]
            for f in as_completed(futures):
                f.result()

    elif endpoint == "admin_single":
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = [pool.submit(simulate_admin_single, u, i, result) for i, u in enumerate(users)]
            for f in as_completed(futures):
                f.result()

    elif endpoint == "batch":
        simulate_batch(users, tier, result)

    elif endpoint == "webhook":
        simulate_webhook(users, tier, result)

    elif endpoint == "env_check":
        simulate_env_check(result)

    elif endpoint == "env_refresh":
        simulate_env_refresh(result)

    result.end_time = time.time()

    summary = result.to_dict()
    print(f"      → {summary['total_requests']} requests, "
          f"{summary['successful']} ok, {summary['failed']} err, "
          f"p95={summary['latency_ms']['p95']}ms, "
          f"throughput={summary['throughput_rps']} RPS, "
          f"wall={summary['wall_clock_sec']}s")

    return result


# ============================================================================
# Full simulation orchestrator
# ============================================================================

def run_simulation(
    tiers: list[int] | None = None,
    endpoints: list[str] | None = None,
    dry_run: bool = False,
) -> dict:
    """
    Run the full simulation across all tiers and endpoints.
    Returns the complete results dict (also saved to JSON).
    """
    tiers = tiers or USER_TIERS
    endpoints = endpoints or list(ENDPOINTS.keys())

    # Validate auth token for protected endpoints
    auth_endpoints = [e for e in endpoints if ENDPOINTS[e]["auth"]]
    if auth_endpoints and not AUTH_TOKEN:
        print("=" * 70)
        print("WARNING: SIMULATION_AUTH_TOKEN is not set.")
        print(f"  Authenticated endpoints will be skipped: {auth_endpoints}")
        print("  Set it with: export SIMULATION_AUTH_TOKEN='your-jwt-token'")
        print("=" * 70)
        endpoints = [e for e in endpoints if not ENDPOINTS[e]["auth"]]

    # Ensure user data CSVs exist
    _ensure_user_data()

    # Build run metadata
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_meta = {
        "run_id": run_id,
        "base_url": BASE_URL,
        "run_stage": RUN_STAGE,
        "timestamp": datetime.now().isoformat(),
        "tiers": tiers,
        "endpoints": endpoints,
        "has_auth_token": bool(AUTH_TOKEN),
        "dry_run": dry_run,
    }

    print("\n" + "=" * 70)
    print(f"  SIMULATION RUN: {run_id}")
    print(f"  Target: {BASE_URL}")
    print(f"  Run stage: {RUN_STAGE}")
    print(f"  Tiers: {tiers}")
    print(f"  Endpoints: {endpoints}")
    print(f"  Auth token: {'SET' if AUTH_TOKEN else 'NOT SET'}")
    print("=" * 70 + "\n")

    if dry_run:
        print("DRY RUN — no API calls will be made.\n")
        return {"metadata": run_meta, "results": []}

    all_results = []

    for tier in tiers:
        print(f"\n  ── Tier {tier} users ─────────────────────────────")
        users = _load_users(tier)
        concurrency = CONCURRENCY_MAP.get(tier, 10)

        for ep in endpoints:
            result = run_single_tier(users, tier, ep, concurrency)
            all_results.append(result.to_dict())

        if tier != tiers[-1]:
            print(f"    (cooling down {INTER_TIER_DELAY}s...)")
            time.sleep(INTER_TIER_DELAY)

    # Build final output
    output = {
        "metadata": run_meta,
        "summary": _build_summary(all_results),
        "results": all_results,
    }

    # Save to JSON
    out_path = RESULTS_DIR / f"simulation_{run_id}.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2, default=str)

    print(f"\n{'=' * 70}")
    print(f"  SIMULATION COMPLETE")
    print(f"  Results saved to: {out_path}")
    print(f"  Total endpoint-tier combinations: {len(all_results)}")
    print(f"{'=' * 70}\n")

    return output


def _build_summary(results: list[dict]) -> dict:
    """Build a high-level summary across all endpoint/tier combos."""
    total_requests = sum(r["total_requests"] for r in results)
    total_success = sum(r["successful"] for r in results)
    total_failed = sum(r["failed"] for r in results)
    all_latencies = []
    for r in results:
        all_latencies.extend([req["elapsed_ms"] for req in r["requests"]])

    return {
        "total_endpoint_tier_combos": len(results),
        "total_requests": total_requests,
        "total_successful": total_success,
        "total_failed": total_failed,
        "overall_error_rate_pct": round(total_failed / max(total_requests, 1) * 100, 2),
        "overall_latency_ms": {
            "min": round(min(all_latencies), 2) if all_latencies else 0,
            "max": round(max(all_latencies), 2) if all_latencies else 0,
            "mean": round(statistics.mean(all_latencies), 2) if all_latencies else 0,
            "median": round(statistics.median(all_latencies), 2) if all_latencies else 0,
            "p95": round(_percentile(all_latencies, 95), 2) if all_latencies else 0,
            "p99": round(_percentile(all_latencies, 99), 2) if all_latencies else 0,
        },
    }


def _ensure_user_data():
    """Generate user CSVs if they don't exist."""
    missing = [t for t in USER_TIERS if not (USER_DATA_DIR / f"users_{t}.csv").exists()]
    if missing:
        print(f"  Generating missing user data for tiers: {missing}")
        generate_all()


def _load_users(tier: int) -> list[dict]:
    """Load users from CSV for a given tier."""
    filepath = USER_DATA_DIR / f"users_{tier}.csv"
    if not filepath.exists():
        # Generate on the fly
        users = generate_tier(tier)
        from simulation.generate_users import write_csv
        write_csv(users, filepath)
        return users

    with open(filepath, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return list(reader)


# ============================================================================
# CLI
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Run real-time simulation against deployed user-management API"
    )
    parser.add_argument(
        "--tier", type=int, nargs="+",
        help=f"Specific tier(s) to run. Options: {USER_TIERS}",
    )
    parser.add_argument(
        "--endpoint", type=str, nargs="+",
        help=f"Specific endpoint(s) to test. Options: {list(ENDPOINTS.keys())}",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Validate setup without making API calls",
    )
    args = parser.parse_args()

    run_simulation(
        tiers=args.tier,
        endpoints=args.endpoint,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
