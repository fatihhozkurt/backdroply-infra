#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import math
import subprocess
import threading
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


def pick_override(value, fallback):
    return fallback if value is None else value


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


def curl_get_json(
    tmp_dir: Path,
    url: str,
    token: str,
    timeout_sec: int,
) -> tuple[int, dict]:
    out = tmp_dir / f"bench-get-{uuid.uuid4().hex}.json"
    args = [
        "--max-time",
        str(timeout_sec),
        "-X",
        "GET",
        url,
        "-H",
        "Accept: application/json",
        "-H",
        f"Authorization: Bearer {token}",
    ]
    code, raw = curl_with_output(args, out)
    out.unlink(missing_ok=True)
    if not raw:
        return code, {}
    try:
        return code, json.loads(raw)
    except json.JSONDecodeError:
        return code, {"_raw": raw}


def curl_download_binary(
    url: str,
    token: str,
    timeout_sec: int,
    output_path: Path,
) -> tuple[int, str]:
    cmd = [
        "curl.exe",
        "-sS",
        "-L",
        "--max-time",
        str(timeout_sec),
        "-o",
        str(output_path),
        "-w",
        "%{http_code}",
        "-H",
        "Accept: */*",
        "-H",
        f"Authorization: Bearer {token}",
        url,
    ]
    proc = subprocess.run(cmd, text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        return 599, proc.stderr.strip()
    status_text = proc.stdout.strip()
    if not status_text.isdigit():
        return 598, f"invalid http status: {status_text}"
    return int(status_text), ""


def curl_engine_multipart(
    tmp_dir: Path,
    url: str,
    file_path: Path,
    engine_token: str,
    timeout_sec: int,
    fields: dict[str, str] | None = None,
) -> tuple[int, dict]:
    out = tmp_dir / f"bench-engine-resp-{uuid.uuid4().hex}.json"
    args = [
        "--max-time",
        str(timeout_sec),
        "-X",
        "POST",
        url,
        "-H",
        "Accept: application/json",
        "-H",
        f"x-engine-token: {engine_token}",
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


def curl_download_binary_engine(
    url: str,
    engine_token: str,
    timeout_sec: int,
    output_path: Path,
) -> tuple[int, str]:
    cmd = [
        "curl.exe",
        "-sS",
        "-L",
        "--max-time",
        str(timeout_sec),
        "-o",
        str(output_path),
        "-w",
        "%{http_code}",
        "-H",
        "Accept: */*",
        "-H",
        f"x-engine-token: {engine_token}",
        url,
    ]
    proc = subprocess.run(cmd, text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        return 599, proc.stderr.strip()
    status_text = proc.stdout.strip()
    if not status_text.isdigit():
        return 598, f"invalid http status: {status_text}"
    return int(status_text), ""


def docker_cp_to_engine(local_path: Path, container_path: str) -> None:
    cmd = ["docker", "cp", str(local_path), f"bgremover-engine:{container_path}"]
    proc = subprocess.run(cmd, text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"docker cp failed: {proc.stderr.strip()}")


def run_gt_metrics_in_engine(pred_video_container: str, gt_video_container: str) -> dict | None:
    script = r"""
import json
import os
import subprocess
import sys
import tempfile
import cv2
import numpy as np
pred = sys.argv[1]
gt = sys.argv[2]
import imageio_ffmpeg
ff = imageio_ffmpeg.get_ffmpeg_exe()

def to_gray_mp4(src, dst, vf):
    cmd = [
        ff,
        "-y",
        "-v", "error",
        "-i", src,
        "-vf", vf,
        "-an",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-crf", "0",
        "-pix_fmt", "yuv420p",
        dst,
    ]
    subprocess.check_call(cmd)

def summarize(values):
    if not values:
        return {"mean": 0.0, "p95": 0.0, "max": 0.0}
    arr = np.asarray(values, dtype=np.float32)
    return {
        "mean": float(np.mean(arr)),
        "p95": float(np.percentile(arr, 95)),
        "max": float(np.max(arr)),
    }

probe_cap = cv2.VideoCapture(gt)
if not probe_cap.isOpened():
    raise RuntimeError(f"gt video open failed: {gt}")
gt_w = int(probe_cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
gt_h = int(probe_cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
probe_cap.release()
if gt_w <= 0 or gt_h <= 0:
    raise RuntimeError("gt video dimensions unavailable")
with tempfile.TemporaryDirectory() as td:
    pred_gray = os.path.join(td, "pred_gray.mp4")
    gt_gray = os.path.join(td, "gt_gray.mp4")
    to_gray_mp4(pred, pred_gray, f"format=rgba,alphaextract,scale={gt_w}:{gt_h}:flags=bilinear")
    to_gray_mp4(gt, gt_gray, f"format=gray,scale={gt_w}:{gt_h}:flags=bilinear")

    cap_p = cv2.VideoCapture(pred_gray)
    cap_g = cv2.VideoCapture(gt_gray)
    iou_values = []
    sad_values = []
    mad_values = []
    temporal_err_values = []
    prev_p = None
    prev_g = None
    frames = 0

    while True:
        okp, fp = cap_p.read()
        okg, fg = cap_g.read()
        if not okp or not okg:
            break
        pa = fp[:, :, 0].astype(np.uint8)
        ga = fg[:, :, 0].astype(np.uint8)
        if pa.shape != ga.shape:
            ga = cv2.resize(ga, (pa.shape[1], pa.shape[0]), interpolation=cv2.INTER_LINEAR)

        diff = np.abs(pa.astype(np.int16) - ga.astype(np.int16)).astype(np.float32)
        sad = float(np.sum(diff) / (255.0 * pa.shape[0] * pa.shape[1]))
        mad = float(np.mean(diff) / 255.0)
        pb = pa >= 128
        gb = ga >= 128
        inter = float(np.logical_and(pb, gb).sum())
        uni = float(np.logical_or(pb, gb).sum())
        iou = 1.0 if uni <= 0 else (inter / uni)

        iou_values.append(iou)
        sad_values.append(sad)
        mad_values.append(mad)

        if prev_p is not None and prev_g is not None:
            pd = float(np.mean(np.abs(pa.astype(np.float32) - prev_p.astype(np.float32))) / 255.0)
            gd = float(np.mean(np.abs(ga.astype(np.float32) - prev_g.astype(np.float32))) / 255.0)
            temporal_err_values.append(abs(pd - gd))

        prev_p = pa
        prev_g = ga
        frames += 1

    cap_p.release()
    cap_g.release()

result = {
    "frameCount": int(frames),
    "iou": summarize(iou_values),
    "sad": summarize(sad_values),
    "mad": summarize(mad_values),
    "temporalError": summarize(temporal_err_values),
}
print(json.dumps(result))
"""
    cmd = ["docker", "exec", "-i", "bgremover-engine", "python", "-", pred_video_container, gt_video_container]
    proc = subprocess.run(cmd, input=script, text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        stderr = proc.stderr.strip()
        raise RuntimeError(f"gt metrics engine script failed: {stderr[:300]}")
    lines = [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]
    if not lines:
        return None
    try:
        return json.loads(lines[-1])
    except json.JSONDecodeError as ex:
        raise RuntimeError(f"gt metrics parse failed: {lines[-1][:200]}") from ex


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
    gt_alpha_video_container: str | None = None,
    gt_eval_limit: int = 0,
    gt_engine_base_url: str | None = None,
    gt_engine_token: str | None = None,
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
    retry_on_429_max = 8
    retry_backoff_sec = 0.35
    status_poll_interval_sec = 2.0
    gt_lock = threading.Lock()
    gt_count = 0
    gt_metrics_samples: list[dict] = []

    def worker(idx: int) -> tuple[int, float, int | None, str | None, dict | None]:
        nonlocal gt_count
        token = users[idx % len(users)].token
        started = time.perf_counter()
        code = 599
        payload: dict = {}
        attempt = 0
        while True:
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
                return 599, elapsed_ms, None, str(ex), None

            retryable_submit = False
            if code == 429:
                retryable_submit = True
            else:
                raw_err = str(
                    (payload.get("message") if isinstance(payload, dict) else "")
                    or (payload.get("error") if isinstance(payload, dict) else "")
                    or (payload.get("_raw") if isinstance(payload, dict) else payload)
                    or ""
                ).lower()
                if code in {409, 423}:
                    retryable_submit = True
                elif "uq_jobs_single_active_per_media" in raw_err or "already exists" in raw_err:
                    retryable_submit = True

            if not retryable_submit:
                break
            if attempt >= retry_on_429_max:
                break
            if (time.perf_counter() - started) >= timeout_sec:
                break
            sleep_for = min(retry_backoff_sec * (2 ** attempt), 2.5)
            time.sleep(sleep_for)
            attempt += 1

        if code != 200 or not isinstance(payload, dict) or payload.get("jobId") is None:
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            err = str(payload.get("message") or payload.get("error") or payload.get("_raw") or "submit failed")
            return code, elapsed_ms, None, err, None

        job_id = payload.get("jobId")
        if not job_id:
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            return 598, elapsed_ms, None, "submit response missing jobId", None

        deadline = started + timeout_sec
        last_payload: dict = {}
        while True:
            remaining = max(1, int(math.ceil(deadline - time.perf_counter())))
            if remaining <= 0:
                elapsed_ms = (time.perf_counter() - started) * 1000.0
                return 598, elapsed_ms, None, "job terminal status timeout", None

            try:
                status_code, status_payload = curl_get_json(
                    tmp_dir=tmp_dir,
                    url=f"{base_url}/media/jobs/{job_id}/status",
                    token=token,
                    timeout_sec=min(20, remaining),
                )
            except Exception:
                if time.perf_counter() >= deadline:
                    elapsed_ms = (time.perf_counter() - started) * 1000.0
                    return 598, elapsed_ms, None, "job terminal status timeout", None
                time.sleep(1.2)
                continue
            if status_code in {429, 502, 503, 504}:
                time.sleep(1.2)
                continue
            if status_code != 200:
                elapsed_ms = (time.perf_counter() - started) * 1000.0
                err = str(status_payload.get("message") or status_payload.get("error") or status_payload.get("_raw") or "status failed")
                return status_code, elapsed_ms, None, err, None

            last_payload = status_payload if isinstance(status_payload, dict) else {}
            raw_state = str(last_payload.get("status") or "").strip().upper()
            if raw_state == "SUCCESS":
                elapsed_ms = (time.perf_counter() - started) * 1000.0
                raw_qc = last_payload.get("qcSuspectFrames", 0)
                try:
                    qc_value = int(raw_qc)
                except (TypeError, ValueError):
                    qc_value = 0
                gt_metrics = None
                if phase_name == "video" and gt_alpha_video_container and gt_eval_limit > 0:
                    do_eval = False
                    with gt_lock:
                        if gt_count < gt_eval_limit:
                            gt_count += 1
                            do_eval = True
                    if do_eval:
                        try:
                            download_url = str(last_payload.get("downloadUrl") or f"/api/v1/media/jobs/{job_id}/download")
                            if download_url.startswith("/"):
                                download_url = f"{base_url}{download_url}"
                            local_out = tmp_dir / f"bench-out-{job_id}.webm"
                            dl_code = 599
                            dl_err = ""
                            for _attempt in range(5):
                                dl_code, dl_err = curl_download_binary(
                                    url=download_url,
                                    token=token,
                                    timeout_sec=max(60, timeout_sec),
                                    output_path=local_out,
                                )
                                if dl_code == 200 and local_out.exists() and local_out.stat().st_size > 0:
                                    break
                                time.sleep(1.5)
                            if dl_code == 200 and local_out.exists():
                                container_out = f"/tmp/bench-pred-{uuid.uuid4().hex}.webm"
                                try:
                                    docker_cp_to_engine(local_out, container_out)
                                    gt_metrics = run_gt_metrics_in_engine(container_out, gt_alpha_video_container)
                                    if isinstance(gt_metrics, dict):
                                        gt_metrics["source"] = "backend-download"
                                finally:
                                    subprocess.run(
                                        ["docker", "exec", "bgremover-engine", "sh", "-lc", f"rm -f '{container_out}'"],
                                        text=True,
                                        capture_output=True,
                                        check=False,
                                    )
                            else:
                                # Fallback: process once directly on engine and evaluate resulting output.
                                if gt_engine_base_url and gt_engine_token:
                                    eng_code, eng_payload = curl_engine_multipart(
                                        tmp_dir=tmp_dir,
                                        url=f"{gt_engine_base_url}/v1/process/video",
                                        file_path=sample_file,
                                        engine_token=gt_engine_token,
                                        timeout_sec=max(60, timeout_sec),
                                        fields={"quality": quality, "bg_color": bg_color},
                                    )
                                    if eng_code == 200 and isinstance(eng_payload, dict):
                                        eng_download = str(eng_payload.get("download_url") or "")
                                        if eng_download.startswith("/"):
                                            eng_download = f"{gt_engine_base_url}{eng_download}"
                                        if eng_download:
                                            local_fallback = tmp_dir / f"bench-out-{job_id}-engine.webm"
                                            eng_dl_code, eng_dl_err = curl_download_binary_engine(
                                                url=eng_download,
                                                engine_token=gt_engine_token,
                                                timeout_sec=max(60, timeout_sec),
                                                output_path=local_fallback,
                                            )
                                            if eng_dl_code == 200 and local_fallback.exists() and local_fallback.stat().st_size > 0:
                                                container_out = f"/tmp/bench-pred-{uuid.uuid4().hex}.webm"
                                                try:
                                                    docker_cp_to_engine(local_fallback, container_out)
                                                    gt_metrics = run_gt_metrics_in_engine(container_out, gt_alpha_video_container)
                                                    if isinstance(gt_metrics, dict):
                                                        gt_metrics["source"] = "engine-fallback"
                                                finally:
                                                    subprocess.run(
                                                        ["docker", "exec", "bgremover-engine", "sh", "-lc", f"rm -f '{container_out}'"],
                                                        text=True,
                                                        capture_output=True,
                                                        check=False,
                                                    )
                                            else:
                                                gt_metrics = {"error": f"engine fallback download failed http={eng_dl_code} err={eng_dl_err[:120]}"}
                                        else:
                                            gt_metrics = {"error": "engine fallback returned no download_url"}
                                    else:
                                        gt_metrics = {"error": f"engine fallback process failed http={eng_code}"}
                                if gt_metrics is None:
                                    gt_metrics = {"error": f"download failed http={dl_code} err={dl_err[:120]}"}
                        except Exception as ex:  # noqa: BLE001
                            gt_metrics = {"error": str(ex)[:240]}
                return 200, elapsed_ms, qc_value, None, gt_metrics
            if raw_state == "FAILED":
                elapsed_ms = (time.perf_counter() - started) * 1000.0
                err = str(last_payload.get("errorMessage") or "job failed")
                raw_qc = last_payload.get("qcSuspectFrames", 0)
                try:
                    qc_value = int(raw_qc)
                except (TypeError, ValueError):
                    qc_value = None
                return 560, elapsed_ms, qc_value, err, None

            if time.perf_counter() >= deadline:
                elapsed_ms = (time.perf_counter() - started) * 1000.0
                return 598, elapsed_ms, None, "job terminal status timeout", None
            time.sleep(status_poll_interval_sec)

    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        futures = [pool.submit(worker, idx) for idx in range(request_count)]
        for future in as_completed(futures):
            code, elapsed_ms, qc_value, err, gt_metrics = future.result()
            key = str(code)
            statuses[key] = statuses.get(key, 0) + 1
            latencies.append(elapsed_ms)
            if code == 200:
                success += 1
                if qc_value is not None:
                    qc_values.append(qc_value)
                if isinstance(gt_metrics, dict) and gt_metrics:
                    gt_metrics_samples.append(gt_metrics)
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

    valid_gt_samples = [
        x
        for x in gt_metrics_samples
        if isinstance(x, dict)
        and isinstance(x.get("iou"), dict)
        and isinstance(x.get("mad"), dict)
        and isinstance(x.get("temporalError"), dict)
    ]
    gt_iou = [float(x.get("iou", {}).get("mean", 0.0)) for x in valid_gt_samples]
    gt_mad = [float(x.get("mad", {}).get("mean", 0.0)) for x in valid_gt_samples]
    gt_temporal = [float(x.get("temporalError", {}).get("mean", 0.0)) for x in valid_gt_samples]
    gt_errors = [str(x.get("error")) for x in gt_metrics_samples if isinstance(x.get("error"), str)]
    gt_sources = sorted({str(x.get("source")) for x in valid_gt_samples if x.get("source")})

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
        "groundTruth": {
            "evaluatedSamples": len(valid_gt_samples),
            "attemptedSamples": len(gt_metrics_samples),
            "iouMean": round(sum(gt_iou) / len(gt_iou), 6) if gt_iou else 0.0,
            "madMean": round(sum(gt_mad) / len(gt_mad), 6) if gt_mad else 0.0,
            "temporalErrorMean": round(sum(gt_temporal) / len(gt_temporal), 6) if gt_temporal else 0.0,
            "sources": gt_sources,
            "errors": gt_errors[:5],
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
    min_video_gt_iou_mean: float,
    max_video_gt_mad_mean: float,
    max_video_gt_temporal_error_mean: float,
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
            "pass": (combined_requests < 4) or (combined_throughput >= min_combined_throughput_rps),
            "actual": round(combined_throughput, 4),
            "expected": (
                f">= {min_combined_throughput_rps}"
                if combined_requests >= 4
                else "skipped for tiny sample (<4 requests)"
            ),
        },
    ]

    gt = video_phase.get("groundTruth", {}) if isinstance(video_phase, dict) else {}
    gt_samples = int(gt.get("evaluatedSamples", 0) or 0)
    if gt_samples > 0:
        gt_iou_mean = float(gt.get("iouMean", 0.0))
        gt_mad_mean = float(gt.get("madMean", 0.0))
        gt_temporal_mean = float(gt.get("temporalErrorMean", 0.0))
        checks.extend(
            [
                {
                    "name": "video_gt_iou_mean",
                    "pass": gt_iou_mean >= min_video_gt_iou_mean,
                    "actual": round(gt_iou_mean, 6),
                    "expected": f">= {min_video_gt_iou_mean}",
                },
                {
                    "name": "video_gt_mad_mean",
                    "pass": gt_mad_mean <= max_video_gt_mad_mean,
                    "actual": round(gt_mad_mean, 6),
                    "expected": f"<= {max_video_gt_mad_mean}",
                },
                {
                    "name": "video_gt_temporal_error_mean",
                    "pass": gt_temporal_mean <= max_video_gt_temporal_error_mean,
                    "actual": round(gt_temporal_mean, 6),
                    "expected": f"<= {max_video_gt_temporal_error_mean}",
                },
            ]
        )

    gt_bonus = 0.0
    if gt_samples > 0:
        gt_iou_mean = float(gt.get("iouMean", 0.0))
        gt_mad_mean = float(gt.get("madMean", 1.0))
        gt_temporal_mean = float(gt.get("temporalErrorMean", 1.0))
        gt_bonus = max(
            0.0,
            min(25.0, (gt_iou_mean * 18.0) - (gt_mad_mean * 80.0) - (gt_temporal_mean * 90.0)),
        )

    quality_score = max(
        0.0,
        100.0
        - (float(video_phase["qcSuspectFrames"]["mean"]) * 18.0)
        - (int(video_phase["qcSuspectFrames"]["max"]) * 3.0)
        - (float(video_phase["qcSuspectFrames"]["nonZeroRate"]) * 15.0)
        + gt_bonus,
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
    parser.add_argument("--image-file", type=Path, default=None)
    parser.add_argument("--video-file", type=Path, default=None)
    parser.add_argument("--video-gt-alpha-video", type=Path, default=None)
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
    parser.add_argument("--min-video-gt-iou-mean", type=float, default=None)
    parser.add_argument("--max-video-gt-mad-mean", type=float, default=None)
    parser.add_argument("--max-video-gt-temporal-error-mean", type=float, default=None)
    parser.add_argument("--video-gt-eval-limit", type=int, default=None)
    parser.add_argument("--base-url", type=str, default="")
    args = parser.parse_args()

    env_map = read_env_map(args.env_file)
    tmp_dir = args.tmp_dir
    tmp_dir.mkdir(parents=True, exist_ok=True)

    image_requests = pick_override(args.image_requests, env_int(env_map, "PREFLIGHT_BENCH_IMAGE_REQUESTS", 12))
    video_requests = pick_override(args.video_requests, env_int(env_map, "PREFLIGHT_BENCH_VIDEO_REQUESTS", 8))
    concurrency = pick_override(args.concurrency, env_int(env_map, "PREFLIGHT_BENCH_CONCURRENCY", 4))
    user_pool = pick_override(args.user_pool, env_int(env_map, "PREFLIGHT_BENCH_USER_POOL", max(4, concurrency * 2)))
    token_seed = pick_override(args.token_seed, env_int(env_map, "PREFLIGHT_BENCH_SEED_USER_TOKENS", 300))
    image_quality = (pick_override(args.image_quality, env_str(env_map, "PREFLIGHT_BENCH_IMAGE_QUALITY", "balanced"))).lower()
    video_quality = (pick_override(args.video_quality, env_str(env_map, "PREFLIGHT_BENCH_VIDEO_QUALITY", "ultra"))).lower()
    bg_color = pick_override(args.bg_color, env_str(env_map, "PREFLIGHT_BENCH_BG_COLOR", "transparent"))
    request_timeout_sec = pick_override(args.request_timeout_sec, env_int(env_map, "PREFLIGHT_BENCH_REQUEST_TIMEOUT_SEC", 240))

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
    min_video_gt_iou_mean = (
        args.min_video_gt_iou_mean
        if args.min_video_gt_iou_mean is not None
        else env_float(env_map, "PREFLIGHT_GO_MIN_VIDEO_GT_IOU_MEAN", 0.90)
    )
    max_video_gt_mad_mean = (
        args.max_video_gt_mad_mean
        if args.max_video_gt_mad_mean is not None
        else env_float(env_map, "PREFLIGHT_GO_MAX_VIDEO_GT_MAD_MEAN", 0.08)
    )
    max_video_gt_temporal_error_mean = (
        args.max_video_gt_temporal_error_mean
        if args.max_video_gt_temporal_error_mean is not None
        else env_float(env_map, "PREFLIGHT_GO_MAX_VIDEO_GT_TEMPORAL_ERROR_MEAN", 0.06)
    )
    video_gt_eval_limit = pick_override(args.video_gt_eval_limit, env_int(env_map, "PREFLIGHT_BENCH_VIDEO_GT_EVAL_LIMIT", 1))

    backend_port = env_int(env_map, "BACKEND_PORT", 8080)
    web_port = env_int(env_map, "WEB_PORT", 8081)
    engine_port = env_int(env_map, "ENGINE_PORT", 9000)
    engine_shared_token = env_str(env_map, "ENGINE_SHARED_TOKEN", "")
    jwt_secret = env_str(env_map, "BACKEND_JWT_SECRET", "")
    jwt_expires_min = env_int(env_map, "BACKEND_JWT_EXPIRES_MIN", 120)
    pg_user = env_str(env_map, "POSTGRES_USER", "bgadmin")
    pg_db = env_str(env_map, "POSTGRES_DB", "bgremover")

    if len(jwt_secret) < 32:
        raise RuntimeError("BACKEND_JWT_SECRET is too short for benchmark probe.")

    image_path = (args.image_file or (tmp_dir / "sample-image-small.jpg")).resolve()
    video_path = (args.video_file or (tmp_dir / "sample-video-tiny.mp4")).resolve()
    if not image_path.exists():
        raise RuntimeError(f"Image sample file is missing: {image_path}")
    if not video_path.exists():
        raise RuntimeError(f"Video sample file is missing: {video_path}")
    gt_alpha_video = args.video_gt_alpha_video.resolve() if args.video_gt_alpha_video else None
    if gt_alpha_video is not None and not gt_alpha_video.exists():
        raise RuntimeError(f"Video GT alpha file is missing: {gt_alpha_video}")

    backend_base_url = f"http://localhost:{backend_port}/api/v1"
    web_base_url = f"http://localhost:{web_port}/api/v1"
    if args.base_url.strip():
        base_url = args.base_url.strip().rstrip("/")
    else:
        base_url = backend_base_url.rstrip("/")
        for candidate in (backend_base_url, web_base_url):
            normalized = candidate.rstrip("/")
            try:
                probe = requests.get(f"{normalized}/users/me", timeout=8.0)
                if probe.status_code in (200, 401, 403):
                    base_url = normalized
                    break
            except requests.RequestException:
                continue
    engine_base_url = f"http://localhost:{engine_port}"
    run_id = uuid.uuid4().hex[:12]
    gt_alpha_container_path = None
    users: list[BenchUser] = []
    started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    try:
        if gt_alpha_video is not None:
            gt_alpha_container_path = f"/tmp/bench-gt-alpha-{uuid.uuid4().hex}.mp4"
            docker_cp_to_engine(gt_alpha_video, gt_alpha_container_path)
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
            gt_alpha_video_container=gt_alpha_container_path,
            gt_eval_limit=max(0, int(video_gt_eval_limit)),
            gt_engine_base_url=engine_base_url,
            gt_engine_token=engine_shared_token if engine_shared_token else None,
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
            min_video_gt_iou_mean=min_video_gt_iou_mean,
            max_video_gt_mad_mean=max_video_gt_mad_mean,
            max_video_gt_temporal_error_mean=max_video_gt_temporal_error_mean,
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
                "imageFile": str(image_path),
                "videoFile": str(video_path),
                "videoGtAlphaFile": str(gt_alpha_video) if gt_alpha_video else None,
                "videoGtEvalLimit": int(video_gt_eval_limit),
            },
            "thresholds": {
                "maxErrorRate": max_error_rate,
                "maxImageP95Ms": max_image_p95_ms,
                "maxVideoP95Ms": max_video_p95_ms,
                "maxVideoQcMean": max_video_qc_mean,
                "maxVideoQcMax": max_video_qc_max,
                "minCombinedThroughputRps": min_combined_throughput_rps,
                "minVideoGtIouMean": min_video_gt_iou_mean,
                "maxVideoGtMadMean": max_video_gt_mad_mean,
                "maxVideoGtTemporalErrorMean": max_video_gt_temporal_error_mean,
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
        if gt_alpha_container_path:
            subprocess.run(
                ["docker", "exec", "bgremover-engine", "sh", "-lc", f"rm -f '{gt_alpha_container_path}'"],
                text=True,
                capture_output=True,
                check=False,
            )
        if users:
            cleanup_seeded_users(pg_user, pg_db, run_id)


if __name__ == "__main__":
    raise SystemExit(main())
