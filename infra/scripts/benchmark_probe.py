#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import math
import subprocess
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path


def read_env_map(path: Path) -> dict[str, str]:
    env_map: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env_map[key.strip()] = value.strip()
    return env_map


def env_int(env_map: dict[str, str], key: str, default: int) -> int:
    value = env_map.get(key, "").strip()
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def env_float(env_map: dict[str, str], key: str, default: float) -> float:
    value = env_map.get(key, "").strip()
    if not value:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def env_str(env_map: dict[str, str], key: str, default: str) -> str:
    value = env_map.get(key, "").strip()
    return value if value else default


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def issue_jwt(secret: str, user_id: int, email: str, name: str, expires_min: int) -> str:
    now = int(time.time())
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": str(user_id),
        "email": email,
        "name": name,
        "iat": now,
        "exp": now + (expires_min * 60),
    }
    signing_input = (
        f"{b64url(json.dumps(header, separators=(',', ':')).encode('utf-8'))}"
        f".{b64url(json.dumps(payload, separators=(',', ':')).encode('utf-8'))}"
    )
    signature = hmac.new(secret.encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256).digest()
    return f"{signing_input}.{b64url(signature)}"


def run_psql(pg_user: str, pg_db: str, sql: str) -> str:
    cmd = [
        "docker",
        "exec",
        "bgremover-postgres",
        "psql",
        "-U",
        pg_user,
        "-d",
        pg_db,
        "-t",
        "-A",
        "-c",
        sql,
    ]
    proc = subprocess.run(cmd, text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"psql failed: {proc.stderr.strip()}")
    return proc.stdout.strip()


def curl_with_output(args: list[str], output_path: Path) -> tuple[int, str]:
    cmd = ["curl.exe", "-sS", "-o", str(output_path), "-w", "%{http_code}"] + args
    proc = subprocess.run(cmd, text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"curl failed: {' '.join(cmd)}\n{proc.stderr.strip()}")
    status_text = proc.stdout.strip()
    if not status_text.isdigit():
        raise RuntimeError(f"Invalid HTTP code from curl: {status_text}")
    status = int(status_text)
    body = ""
    if output_path.exists():
        body = output_path.read_text(encoding="utf-8", errors="replace")
    return status, body


def curl_multipart(
    tmp_dir: Path,
    url: str,
    file_path: Path,
    token: str,
    timeout_sec: int,
    fields: dict[str, str] | None = None,
) -> tuple[int, dict]:
    out = tmp_dir / f"bench-resp-{uuid.uuid4().hex}.json"
    args = [
        "--max-time",
        str(timeout_sec),
        "-X",
        "POST",
        url,
        "-H",
        "Accept: application/json",
        "-H",
        f"Authorization: Bearer {token}",
        "-F",
        f"file=@{file_path.as_posix()}",
    ]
    for key, value in (fields or {}).items():
        args += ["-F", f"{key}={value}"]
    code, raw = curl_with_output(args, out)
    out.unlink(missing_ok=True)
    if not raw:
        return code, {}
    try:
        return code, json.loads(raw)
    except json.JSONDecodeError:
        return code, {"_raw": raw}


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    k = (len(ordered) - 1) * p
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return ordered[f]
    return ordered[f] + (ordered[c] - ordered[f]) * (k - f)


@dataclass
class BenchUser:
    user_id: int
    token: str


def seed_users(
    pg_user: str,
    pg_db: str,
    jwt_secret: str,
    jwt_expires_min: int,
    user_pool: int,
    token_seed: int,
    run_id: str,
) -> list[BenchUser]:
    users: list[BenchUser] = []
    for idx in range(user_pool):
        suffix = uuid.uuid4().hex[:8]
        google_sub = f"bench-{run_id}-{idx}-{suffix}"
        email = f"bench-{run_id}-{idx}-{suffix}@backdroply.local"
        full_name = f"Bench User {idx + 1}"
        sql = (
            "INSERT INTO users (google_sub, email, full_name, language, token_balance, created_at, updated_at, last_login_at) "
            f"VALUES ('{google_sub}', '{email}', '{full_name}', 'en', {token_seed}, NOW(), NOW(), NOW()) RETURNING id;"
        )
        out = run_psql(pg_user, pg_db, sql)
        user_id = None
        for line in out.splitlines():
            candidate = line.strip()
            if candidate.isdigit():
                user_id = int(candidate)
                break
        if user_id is None:
            raise RuntimeError(f"Could not parse seeded user id from psql output: {out}")
        token = issue_jwt(jwt_secret, user_id, email, full_name, jwt_expires_min)
        users.append(BenchUser(user_id=user_id, token=token))
    return users


def cleanup_seeded_users(pg_user: str, pg_db: str, run_id: str) -> None:
    sql = f"DELETE FROM users WHERE google_sub LIKE 'bench-{run_id}-%';"
    run_psql(pg_user, pg_db, sql)


def run_phase(
    phase_name: str,
    base_url: str,
    endpoint: str,
    sample_file: Path,
    users: list[BenchUser],
    request_count: int,
    concurrency: int,
    timeout_sec: int,
    quality: str,
    bg_color: str,
    tmp_dir: Path,
) -> dict:
    if request_count <= 0:
        return {
            "phase": phase_name,
            "requests": 0,
            "success": 0,
            "errorRate": 0.0,
            "latencyMs": {"p50": 0.0, "p95": 0.0, "max": 0.0, "mean": 0.0},
            "throughputRps": 0.0,
            "statusHistogram": {},
            "qcSuspectFrames": {"mean": 0.0, "max": 0, "nonZeroRate": 0.0},
            "sampleErrors": [],
        }

    statuses: dict[str, int] = {}
    latencies: list[float] = []
    qc_values: list[int] = []
    sample_errors: list[str] = []
    success = 0
    start_wall = time.perf_counter()

    def worker(idx: int) -> tuple[int, float, int | None, str | None]:
        token = users[idx % len(users)].token
        started = time.perf_counter()
        try:
            code, payload = curl_multipart(
                tmp_dir=tmp_dir,
                url=f"{base_url}{endpoint}",
                file_path=sample_file,
                token=token,
                timeout_sec=timeout_sec,
                fields={"quality": quality, "bgColor": bg_color},
            )
        except Exception as ex:
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            return 599, elapsed_ms, None, str(ex)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        qc_value = None
        err = None
        if code == 200 and isinstance(payload, dict) and payload.get("jobId") is not None:
            raw_qc = payload.get("qcSuspectFrames", 0)
            try:
                qc_value = int(raw_qc)
            except (TypeError, ValueError):
                qc_value = 0
        else:
            err = str(payload.get("message") or payload.get("error") or payload.get("_raw") or "unknown error")
        return code, elapsed_ms, qc_value, err

    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        futures = [pool.submit(worker, idx) for idx in range(request_count)]
        for future in as_completed(futures):
            code, elapsed_ms, qc_value, err = future.result()
            key = str(code)
            statuses[key] = statuses.get(key, 0) + 1
            latencies.append(elapsed_ms)
            if code == 200:
                success += 1
                if qc_value is not None:
                    qc_values.append(qc_value)
            else:
                if err and len(sample_errors) < 8:
                    sample_errors.append(f"HTTP {code}: {err[:240]}")

    duration_sec = max(0.001, time.perf_counter() - start_wall)
    error_rate = (request_count - success) / request_count
    p50 = percentile(latencies, 0.50)
    p95 = percentile(latencies, 0.95)
    mean_latency = sum(latencies) / len(latencies) if latencies else 0.0
    qc_mean = (sum(qc_values) / len(qc_values)) if qc_values else 0.0
    qc_max = max(qc_values) if qc_values else 0
    qc_non_zero_rate = (sum(1 for v in qc_values if v > 0) / len(qc_values)) if qc_values else 0.0

    return {
        "phase": phase_name,
        "requests": request_count,
        "success": success,
        "errorRate": round(error_rate, 6),
        "latencyMs": {
            "p50": round(p50, 2),
            "p95": round(p95, 2),
            "max": round(max(latencies) if latencies else 0.0, 2),
            "mean": round(mean_latency, 2),
        },
        "throughputRps": round(success / duration_sec, 4),
        "statusHistogram": statuses,
        "qcSuspectFrames": {
            "mean": round(qc_mean, 4),
            "max": qc_max,
            "nonZeroRate": round(qc_non_zero_rate, 4),
        },
        "sampleErrors": sample_errors,
    }


def build_go_checks(
    image_phase: dict,
    video_phase: dict,
    max_error_rate: float,
    max_image_p95_ms: float,
    max_video_p95_ms: float,
    max_video_qc_mean: float,
    max_video_qc_max: int,
    min_combined_throughput_rps: float,
) -> tuple[bool, list[dict], dict]:
    combined_requests = int(image_phase["requests"]) + int(video_phase["requests"])
    combined_success = int(image_phase["success"]) + int(video_phase["success"])
    combined_error_rate = 0.0 if combined_requests == 0 else (combined_requests - combined_success) / combined_requests
    combined_throughput = float(image_phase["throughputRps"]) + float(video_phase["throughputRps"])

    checks = [
        {
            "name": "combined_error_rate",
            "pass": combined_error_rate <= max_error_rate,
            "actual": round(combined_error_rate, 6),
            "expected": f"<= {max_error_rate}",
        },
        {
            "name": "image_p95_ms",
            "pass": float(image_phase["latencyMs"]["p95"]) <= max_image_p95_ms,
            "actual": float(image_phase["latencyMs"]["p95"]),
            "expected": f"<= {max_image_p95_ms}",
        },
        {
            "name": "video_p95_ms",
            "pass": float(video_phase["latencyMs"]["p95"]) <= max_video_p95_ms,
            "actual": float(video_phase["latencyMs"]["p95"]),
            "expected": f"<= {max_video_p95_ms}",
        },
        {
            "name": "video_qc_mean",
            "pass": float(video_phase["qcSuspectFrames"]["mean"]) <= max_video_qc_mean,
            "actual": float(video_phase["qcSuspectFrames"]["mean"]),
            "expected": f"<= {max_video_qc_mean}",
        },
        {
            "name": "video_qc_max",
            "pass": int(video_phase["qcSuspectFrames"]["max"]) <= max_video_qc_max,
            "actual": int(video_phase["qcSuspectFrames"]["max"]),
            "expected": f"<= {max_video_qc_max}",
        },
        {
            "name": "combined_throughput_rps",
            "pass": combined_throughput >= min_combined_throughput_rps,
            "actual": round(combined_throughput, 4),
            "expected": f">= {min_combined_throughput_rps}",
        },
    ]

    quality_score = max(
        0.0,
        100.0
        - (float(video_phase["qcSuspectFrames"]["mean"]) * 18.0)
        - (int(video_phase["qcSuspectFrames"]["max"]) * 3.0)
        - (float(video_phase["qcSuspectFrames"]["nonZeroRate"]) * 15.0),
    )
    performance_score = max(
        0.0,
        100.0
        - (combined_error_rate * 250.0)
        - (float(image_phase["latencyMs"]["p95"]) / 900.0)
        - (float(video_phase["latencyMs"]["p95"]) / 2500.0),
    )
    overall_score = round((quality_score * 0.65) + (performance_score * 0.35), 2)

    go = all(bool(chk["pass"]) for chk in checks)
    summary = {
        "combinedErrorRate": round(combined_error_rate, 6),
        "combinedThroughputRps": round(combined_throughput, 4),
        "score": {
            "quality": round(quality_score, 2),
            "performance": round(performance_score, 2),
            "overall": overall_score,
        },
    }
    return go, checks, summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Backdroply benchmark + go/no-go probe")
    parser.add_argument("--env-file", required=True, type=Path)
    parser.add_argument("--tmp-dir", required=True, type=Path)
    parser.add_argument("--output-json", type=Path, default=None)
    parser.add_argument("--image-requests", type=int, default=None)
    parser.add_argument("--video-requests", type=int, default=None)
    parser.add_argument("--concurrency", type=int, default=None)
    parser.add_argument("--user-pool", type=int, default=None)
    parser.add_argument("--token-seed", type=int, default=None)
    parser.add_argument("--image-quality", type=str, default=None)
    parser.add_argument("--video-quality", type=str, default=None)
    parser.add_argument("--bg-color", type=str, default=None)
    parser.add_argument("--request-timeout-sec", type=int, default=None)
    parser.add_argument("--max-error-rate", type=float, default=None)
    parser.add_argument("--max-image-p95-ms", type=float, default=None)
    parser.add_argument("--max-video-p95-ms", type=float, default=None)
    parser.add_argument("--max-video-qc-mean", type=float, default=None)
    parser.add_argument("--max-video-qc-max", type=int, default=None)
    parser.add_argument("--min-combined-throughput-rps", type=float, default=None)
    args = parser.parse_args()

    env_map = read_env_map(args.env_file)
    tmp_dir = args.tmp_dir
    tmp_dir.mkdir(parents=True, exist_ok=True)

    image_requests = args.image_requests or env_int(env_map, "PREFLIGHT_BENCH_IMAGE_REQUESTS", 12)
    video_requests = args.video_requests or env_int(env_map, "PREFLIGHT_BENCH_VIDEO_REQUESTS", 8)
    concurrency = args.concurrency or env_int(env_map, "PREFLIGHT_BENCH_CONCURRENCY", 4)
    user_pool = args.user_pool or env_int(env_map, "PREFLIGHT_BENCH_USER_POOL", max(4, concurrency * 2))
    token_seed = args.token_seed or env_int(env_map, "PREFLIGHT_BENCH_SEED_USER_TOKENS", 300)
    image_quality = (args.image_quality or env_str(env_map, "PREFLIGHT_BENCH_IMAGE_QUALITY", "balanced")).lower()
    video_quality = (args.video_quality or env_str(env_map, "PREFLIGHT_BENCH_VIDEO_QUALITY", "ultra")).lower()
    bg_color = args.bg_color or env_str(env_map, "PREFLIGHT_BENCH_BG_COLOR", "transparent")
    request_timeout_sec = args.request_timeout_sec or env_int(env_map, "PREFLIGHT_BENCH_REQUEST_TIMEOUT_SEC", 240)

    max_error_rate = args.max_error_rate if args.max_error_rate is not None else env_float(env_map, "PREFLIGHT_GO_MAX_ERROR_RATE", 0.08)
    max_image_p95_ms = (
        args.max_image_p95_ms if args.max_image_p95_ms is not None else env_float(env_map, "PREFLIGHT_GO_MAX_IMAGE_P95_MS", 25000.0)
    )
    max_video_p95_ms = (
        args.max_video_p95_ms if args.max_video_p95_ms is not None else env_float(env_map, "PREFLIGHT_GO_MAX_VIDEO_P95_MS", 100000.0)
    )
    max_video_qc_mean = (
        args.max_video_qc_mean if args.max_video_qc_mean is not None else env_float(env_map, "PREFLIGHT_GO_MAX_VIDEO_QC_MEAN", 1.5)
    )
    max_video_qc_max = args.max_video_qc_max if args.max_video_qc_max is not None else env_int(env_map, "PREFLIGHT_GO_MAX_VIDEO_QC_MAX", 6)
    min_combined_throughput_rps = (
        args.min_combined_throughput_rps
        if args.min_combined_throughput_rps is not None
        else env_float(env_map, "PREFLIGHT_GO_MIN_COMBINED_THROUGHPUT_RPS", 0.08)
    )

    backend_port = env_int(env_map, "BACKEND_PORT", 8080)
    jwt_secret = env_str(env_map, "BACKEND_JWT_SECRET", "")
    jwt_expires_min = env_int(env_map, "BACKEND_JWT_EXPIRES_MIN", 120)
    pg_user = env_str(env_map, "POSTGRES_USER", "bgadmin")
    pg_db = env_str(env_map, "POSTGRES_DB", "bgremover")

    if len(jwt_secret) < 32:
        raise RuntimeError("BACKEND_JWT_SECRET is too short for benchmark probe.")

    image_path = tmp_dir / "sample-image-small.jpg"
    video_path = tmp_dir / "sample-video-tiny.mp4"
    if not image_path.exists() or not video_path.exists():
        raise RuntimeError(f"Sample files are missing under {tmp_dir}")

    base_url = f"http://localhost:{backend_port}/api/v1"
    run_id = uuid.uuid4().hex[:12]
    users: list[BenchUser] = []
    started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    try:
        users = seed_users(
            pg_user=pg_user,
            pg_db=pg_db,
            jwt_secret=jwt_secret,
            jwt_expires_min=jwt_expires_min,
            user_pool=user_pool,
            token_seed=token_seed,
            run_id=run_id,
        )

        print(
            "[bench] run_id={} image_requests={} video_requests={} concurrency={} user_pool={}".format(
                run_id,
                image_requests,
                video_requests,
                concurrency,
                user_pool,
            )
        )

        image_phase = run_phase(
            phase_name="image",
            base_url=base_url,
            endpoint="/media/image",
            sample_file=image_path,
            users=users,
            request_count=image_requests,
            concurrency=concurrency,
            timeout_sec=request_timeout_sec,
            quality=image_quality,
            bg_color=bg_color,
            tmp_dir=tmp_dir,
        )
        print(
            "[bench] image success={}/{} p95={}ms errRate={}".format(
                image_phase["success"],
                image_phase["requests"],
                image_phase["latencyMs"]["p95"],
                image_phase["errorRate"],
            )
        )

        video_phase = run_phase(
            phase_name="video",
            base_url=base_url,
            endpoint="/media/video",
            sample_file=video_path,
            users=users,
            request_count=video_requests,
            concurrency=concurrency,
            timeout_sec=request_timeout_sec,
            quality=video_quality,
            bg_color=bg_color,
            tmp_dir=tmp_dir,
        )
        print(
            "[bench] video success={}/{} p95={}ms errRate={} qcMean={} qcMax={}".format(
                video_phase["success"],
                video_phase["requests"],
                video_phase["latencyMs"]["p95"],
                video_phase["errorRate"],
                video_phase["qcSuspectFrames"]["mean"],
                video_phase["qcSuspectFrames"]["max"],
            )
        )

        go, checks, summary = build_go_checks(
            image_phase=image_phase,
            video_phase=video_phase,
            max_error_rate=max_error_rate,
            max_image_p95_ms=max_image_p95_ms,
            max_video_p95_ms=max_video_p95_ms,
            max_video_qc_mean=max_video_qc_mean,
            max_video_qc_max=max_video_qc_max,
            min_combined_throughput_rps=min_combined_throughput_rps,
        )

        result = {
            "runId": run_id,
            "startedAtUtc": started_at,
            "config": {
                "imageRequests": image_requests,
                "videoRequests": video_requests,
                "concurrency": concurrency,
                "userPool": user_pool,
                "tokenSeed": token_seed,
                "imageQuality": image_quality,
                "videoQuality": video_quality,
                "bgColor": bg_color,
                "requestTimeoutSec": request_timeout_sec,
            },
            "thresholds": {
                "maxErrorRate": max_error_rate,
                "maxImageP95Ms": max_image_p95_ms,
                "maxVideoP95Ms": max_video_p95_ms,
                "maxVideoQcMean": max_video_qc_mean,
                "maxVideoQcMax": max_video_qc_max,
                "minCombinedThroughputRps": min_combined_throughput_rps,
            },
            "phases": {"image": image_phase, "video": video_phase},
            "goNoGo": {"result": "GO" if go else "NO_GO", "checks": checks, **summary},
        }

        if args.output_json:
            args.output_json.parent.mkdir(parents=True, exist_ok=True)
            args.output_json.write_text(json.dumps(result, indent=2), encoding="utf-8")
            print(f"[bench] report written: {args.output_json}")

        print(f"[bench] FINAL: {result['goNoGo']['result']}")
        if not go:
            for check in checks:
                if not check["pass"]:
                    print(
                        f"[bench] FAIL {check['name']} actual={check['actual']} expected={check['expected']}"
                    )
            return 2
        return 0
    finally:
        if users:
            cleanup_seeded_users(pg_user, pg_db, run_id)


if __name__ == "__main__":
    raise SystemExit(main())
