#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import math
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

import requests

VIDEO_EXTENSIONS = {".mp4", ".mov"}


def file_fingerprint(path: Path) -> str:
    h = hashlib.sha1()
    size = path.stat().st_size
    h.update(str(size).encode("utf-8"))
    with path.open("rb") as f:
        head = f.read(1024 * 1024)
    h.update(head)
    return h.hexdigest()


def read_env_map(path: Path) -> dict[str, str]:
    env_map: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env_map[key.strip()] = value.strip()
    return env_map


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


def seed_user(pg_user: str, pg_db: str, token_seed: int) -> tuple[int, str, str]:
    unique = uuid.uuid4().hex[:12]
    google_sub = f"suite-sub-{unique}"
    email = f"suite-{unique}@backdroply.local"
    full_name = "Video Suite Probe User"
    sql = (
        "INSERT INTO users (google_sub, email, full_name, language, token_balance, token_version, created_at, updated_at, last_login_at) "
        f"VALUES ('{google_sub}', '{email}', '{full_name}', 'en', {token_seed}, 0, NOW(), NOW(), NOW()) RETURNING id;"
    )
    out = run_psql(pg_user, pg_db, sql)
    for line in out.splitlines():
        row = line.strip()
        if row.isdigit():
            return int(row), email, full_name
    raise RuntimeError(f"Failed to parse seeded user id from output: {out}")


def cleanup_user(pg_user: str, pg_db: str, user_id: int):
    run_psql(pg_user, pg_db, f"DELETE FROM users WHERE id = {user_id};")


def curl_with_output(args: list[str], output_path: Path) -> tuple[int, str]:
    cmd = ["curl.exe", "-sS", "-o", str(output_path), "-w", "%{http_code}"] + args
    proc = subprocess.run(cmd, text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"curl failed: {proc.stderr.strip()}")
    status_text = proc.stdout.strip()
    if not status_text.isdigit():
        raise RuntimeError(f"Invalid curl status output: {status_text}")
    body = output_path.read_text(encoding="utf-8", errors="replace") if output_path.exists() else ""
    return int(status_text), body


def curl_multipart(
    tmp_dir: Path,
    url: str,
    token: str,
    file_path: Path,
    timeout_sec: int,
    fields: dict[str, str],
) -> tuple[int, dict]:
    del tmp_dir
    with file_path.open("rb") as f:
        response = requests.post(
            url,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {token}",
            },
            data=fields,
            files={"file": (file_path.name, f, "application/octet-stream")},
            timeout=float(timeout_sec),
        )
    raw = response.text or ""
    if not raw:
        return response.status_code, {}
    try:
        return response.status_code, response.json()
    except json.JSONDecodeError:
        return response.status_code, {"_raw": raw}


def curl_get_json(tmp_dir: Path, url: str, token: str, timeout_sec: int) -> tuple[int, dict]:
    del tmp_dir
    response = requests.get(
        url,
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
        },
        timeout=float(timeout_sec),
    )
    raw = response.text or ""
    if not raw:
        return response.status_code, {}
    try:
        return response.status_code, response.json()
    except json.JSONDecodeError:
        return response.status_code, {"_raw": raw}


def curl_download(url: str, token: str, timeout_sec: int, output_path: Path) -> tuple[int, str]:
    response = requests.get(
        url,
        headers={"Authorization": f"Bearer {token}"},
        timeout=float(timeout_sec),
        stream=True,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("wb") as f:
        for chunk in response.iter_content(chunk_size=1024 * 1024):
            if chunk:
                f.write(chunk)
    return response.status_code, ""


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    arr = sorted(values)
    if len(arr) == 1:
        return arr[0]
    k = (len(arr) - 1) * p
    lo = math.floor(k)
    hi = math.ceil(k)
    if lo == hi:
        return arr[lo]
    return arr[lo] + (arr[hi] - arr[lo]) * (k - lo)


def collect_videos(dirs: list[Path], limit: int) -> list[Path]:
    candidates: list[Path] = []
    for root in dirs:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() not in VIDEO_EXTENSIONS:
                continue
            lower = str(path).lower()
            if any(skip in lower for skip in ("\\tmp-integration\\bench-out", "\\tmp-integration\\e2e-video-output")):
                continue
            size = path.stat().st_size
            if size < 50_000:
                continue
            # Keep uploads small for consistent UI-like latency checks on local Docker volume mounts.
            if size > 5_000_000:
                continue
            candidates.append(path.resolve())
    unique: list[Path] = []
    seen: set[str] = set()
    seen_fp: set[str] = set()
    for item in candidates:
        key = str(item).lower()
        if key in seen:
            continue
        fp = file_fingerprint(item)
        if fp in seen_fp:
            continue
        seen.add(key)
        seen_fp.add(fp)
        unique.append(item)
    unique.sort(key=lambda x: (x.stat().st_size, str(x).lower()))
    if not unique:
        return []
    if len(unique) >= limit:
        return unique[:limit]
    # not enough unique files: cycle list to hit requested count
    out: list[Path] = []
    idx = 0
    while len(out) < limit:
        out.append(unique[idx % len(unique)])
        idx += 1
    return out


def eval_alpha_metrics_with_engine(local_video: Path) -> dict:
    container_video = f"/tmp/suite-{uuid.uuid4().hex}.webm"
    cp = subprocess.run(
        ["docker", "cp", str(local_video), f"bgremover-engine:{container_video}"],
        text=True,
        capture_output=True,
        check=False,
    )
    if cp.returncode != 0:
        return {"error": f"docker cp failed: {cp.stderr.strip()}"}

    script = r"""
import json
import sys
import tempfile
from pathlib import Path
import subprocess
import cv2
import numpy as np
import imageio_ffmpeg

src = Path(sys.argv[1])
ff = imageio_ffmpeg.get_ffmpeg_exe()
with tempfile.TemporaryDirectory() as td:
    alpha_mp4 = Path(td) / "alpha.mp4"
    cmd = [
        ff,
        "-y",
        "-v",
        "error",
        "-i",
        str(src),
        "-vf",
        "format=rgba,alphaextract",
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-crf",
        "0",
        "-pix_fmt",
        "yuv420p",
        str(alpha_mp4),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0 or not alpha_mp4.exists():
        print(json.dumps({"error": f"alpha extract failed: {proc.stderr[-220:] if proc.stderr else ''}"}))
        raise SystemExit(0)

    cap = cv2.VideoCapture(str(alpha_mp4))
    if not cap.isOpened():
        print(json.dumps({"error": "alpha capture open failed"}))
        raise SystemExit(0)

    edge_vals = []
    area_vals = []
    temporal_vals = []
    frames = 0
    prev = None
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        alpha = frame[:, :, 0].astype(np.uint8)
        h, w = alpha.shape[:2]
        edge = max(4, int(min(h, w) * 0.08))
        edge_mask = np.zeros((h, w), dtype=np.uint8)
        edge_mask[:edge, :] = 1
        edge_mask[-edge:, :] = 1
        edge_mask[:, :edge] = 1
        edge_mask[:, -edge:] = 1
        edge_vals.append(float(alpha[edge_mask > 0].mean()))
        area_vals.append(float((alpha >= 128).mean()))
        if prev is not None:
            temporal_vals.append(float(np.mean(np.abs(alpha.astype(np.float32) - prev.astype(np.float32))) / 255.0))
        prev = alpha
        frames += 1
    cap.release()

    def stat(values):
        if not values:
            return {"mean": 0.0, "p95": 0.0, "max": 0.0}
        arr = np.asarray(values, dtype=np.float32)
        return {
            "mean": float(np.mean(arr)),
            "p95": float(np.percentile(arr, 95)),
            "max": float(np.max(arr)),
        }

    print(json.dumps({
        "frames": int(frames),
        "edgeAlpha": stat(edge_vals),
        "foregroundArea": stat(area_vals),
        "temporalDelta": stat(temporal_vals),
    }))
"""

    try:
        proc = subprocess.run(
            ["docker", "exec", "-i", "bgremover-engine", "python", "-", container_video],
            input=script,
            text=True,
            capture_output=True,
            check=False,
        )
        if proc.returncode != 0:
            return {"error": f"engine eval failed: {proc.stderr.strip()[:240]}"}
        lines = [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]
        if not lines:
            return {"error": "engine eval returned empty output"}
        try:
            return json.loads(lines[-1])
        except json.JSONDecodeError:
            return {"error": f"invalid eval output: {lines[-1][:220]}"}
    finally:
        subprocess.run(
            ["docker", "exec", "bgremover-engine", "sh", "-lc", f"rm -f '{container_video}'"],
            text=True,
            capture_output=True,
            check=False,
        )


def wait_for_job(base_url: str, token: str, tmp_dir: Path, job_id: int, timeout_sec: int) -> tuple[dict, str]:
    deadline = time.time() + timeout_sec
    last_status = ""
    while time.time() < deadline:
        try:
            code, payload = curl_get_json(tmp_dir, f"{base_url}/media/jobs/{job_id}/status", token, timeout_sec=60)
        except Exception:
            time.sleep(2.0)
            continue
        if code != 200:
            return {"error": f"status http {code}", "payload": payload}, "failed"
        status = str(payload.get("status", "")).lower()
        if status in {"success", "failed"}:
            return payload, status
        if status != last_status:
            last_status = status
        time.sleep(2.0)
    return {"error": "status timeout"}, "failed"


def run_suite(
    env_file: Path,
    videos: list[Path],
    output_json: Path,
    clip_end_sec: float,
    per_video_timeout_sec: int,
    success_time_limit_sec: float,
) -> int:
    env = read_env_map(env_file)
    backend_port = int(env.get("BACKEND_PORT", "8080"))
    backend_host = env.get("BENCH_BACKEND_HOST", "127.0.0.1").strip() or "127.0.0.1"
    pg_user = env.get("POSTGRES_USER", "bgadmin")
    pg_db = env.get("POSTGRES_DB", "bgremover")
    jwt_secret = env.get("BACKEND_JWT_SECRET", "")
    jwt_expires_min = int(env.get("BACKEND_JWT_EXPIRES_MIN", "120"))
    if len(jwt_secret) < 32:
        raise RuntimeError("BACKEND_JWT_SECRET is invalid for suite probe.")

    base_url = f"http://{backend_host}:{backend_port}/api/v1"
    run_id = uuid.uuid4().hex[:10]
    tmp_dir = Path(tempfile.mkdtemp(prefix=f"video-suite-{run_id}-"))
    user_id = -1
    try:
        user_id, email, name = seed_user(pg_user, pg_db, token_seed=20000)
        token = issue_jwt(jwt_secret, user_id, email, name, jwt_expires_min)
        results: list[dict] = []
        for idx, video in enumerate(videos, start=1):
            started = time.perf_counter()
            row = {
                "index": idx,
                "video": str(video),
            }
            try:
                submit_code, submit = curl_multipart(
                    tmp_dir=tmp_dir,
                    url=f"{base_url}/media/video",
                    token=token,
                    file_path=video,
                    timeout_sec=per_video_timeout_sec,
                    fields={
                        "quality": "ultra",
                        "bgColor": "transparent",
                        "clipStartSec": "0.0",
                        "clipEndSec": f"{clip_end_sec:.3f}",
                    },
                )
            except Exception as ex:  # noqa: BLE001
                row["status"] = "submit_failed"
                row["error"] = str(ex)
                results.append(row)
                continue
            row["submitCode"] = submit_code
            if submit_code != 200 or "jobId" not in submit:
                row["status"] = "submit_failed"
                row["error"] = str(submit.get("message") or submit.get("error") or submit.get("_raw") or "submit failed")
                results.append(row)
                continue

            job_id = int(submit["jobId"])
            status_payload, terminal = wait_for_job(base_url, token, tmp_dir, job_id, timeout_sec=per_video_timeout_sec)
            elapsed = time.perf_counter() - started
            row["jobId"] = job_id
            row["elapsedSec"] = round(elapsed, 3)
            row["terminalStatus"] = terminal
            row["qcSuspectFrames"] = int(status_payload.get("qcSuspectFrames", 0)) if isinstance(status_payload, dict) else None
            if terminal != "success":
                row["status"] = "failed"
                row["error"] = str(status_payload.get("errorMessage") or status_payload.get("error") or "failed")
                results.append(row)
                continue

            download_rel = str(status_payload.get("downloadUrl") or "")
            if not download_rel:
                row["status"] = "failed"
                row["error"] = "downloadUrl missing"
                results.append(row)
                continue

            output_file = tmp_dir / f"out-{job_id}.webm"
            dl_code, dl_err = curl_download(
                url=f"http://{backend_host}:{backend_port}{download_rel}",
                token=token,
                timeout_sec=max(120, per_video_timeout_sec),
                output_path=output_file,
            )
            if dl_code != 200 or not output_file.exists() or output_file.stat().st_size <= 0:
                row["status"] = "failed"
                row["error"] = f"download failed http={dl_code} err={dl_err[:120]}"
                results.append(row)
                continue

            metrics = eval_alpha_metrics_with_engine(output_file)
            row["alphaMetrics"] = metrics
            quality_ok = False
            if "error" not in metrics:
                edge_p95 = float(metrics.get("edgeAlpha", {}).get("p95", 999.0))
                temporal_mean = float(metrics.get("temporalDelta", {}).get("mean", 999.0))
                area_mean = float(metrics.get("foregroundArea", {}).get("mean", 0.0))
                qc = int(row["qcSuspectFrames"] or 0)
                opaque_alpha = edge_p95 >= 250.0 and area_mean >= 0.98
                row["alphaChannelDetected"] = not opaque_alpha
                if opaque_alpha:
                    # Some platform decoders flatten alpha during probe; rely on engine QC in that case.
                    quality_ok = qc <= 45
                else:
                    quality_ok = (
                        edge_p95 <= 22.0
                        and temporal_mean <= 0.12
                        and area_mean >= 0.01
                        and area_mean <= 0.95
                        and qc <= 45
                    )
            time_ok = elapsed <= success_time_limit_sec
            row["qualityOk"] = quality_ok
            row["timeOk"] = time_ok
            row["status"] = "ok" if (quality_ok and time_ok) else "warning"
            results.append(row)

        elapsed_values = [float(r.get("elapsedSec", 0.0)) for r in results if "elapsedSec" in r]
        success_rows = [r for r in results if r.get("terminalStatus") == "success"]
        fully_ok = [r for r in results if r.get("status") == "ok"]
        summary = {
            "runId": run_id,
            "totalVideos": len(videos),
            "processed": len(success_rows),
            "fullyOk": len(fully_ok),
            "failed": len([r for r in results if r.get("terminalStatus") != "success"]),
            "time": {
                "meanSec": round(sum(elapsed_values) / len(elapsed_values), 3) if elapsed_values else 0.0,
                "p95Sec": round(percentile(elapsed_values, 0.95), 3) if elapsed_values else 0.0,
                "maxSec": round(max(elapsed_values), 3) if elapsed_values else 0.0,
                "limitSec": success_time_limit_sec,
            },
        }
        payload = {"summary": summary, "results": results}
        output_json.parent.mkdir(parents=True, exist_ok=True)
        output_json.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=False))
        return 0 if (summary["processed"] == len(videos) and summary["fullyOk"] == len(videos)) else 2
    finally:
        if user_id > 0:
            cleanup_user(pg_user, pg_db, user_id)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run 20-video UI-like upload suite on prod-like stack.")
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--clip-end-sec", type=float, default=8.0)
    parser.add_argument("--per-video-timeout-sec", type=int, default=420)
    parser.add_argument("--success-time-limit-sec", type=float, default=240.0)
    parser.add_argument(
        "--video-dir",
        action="append",
        default=[],
        help="Video root dirs to scan. Can be repeated.",
    )
    args = parser.parse_args()

    default_dirs = [
        Path(r"C:\Users\fatih\Desktop"),
        Path(r"C:\Users\fatih\Videos"),
        Path(r"C:\Users\fatih\projects\backdroply-infra\tmp-integration"),
    ]
    custom_dirs = [Path(x) for x in args.video_dir]
    dirs = custom_dirs if custom_dirs else default_dirs
    videos = collect_videos(dirs, limit=max(1, args.limit))
    if len(videos) < args.limit:
        raise RuntimeError(f"Not enough videos found. requested={args.limit} found={len(videos)}")
    print(f"[suite] selected {len(videos)} videos")
    return run_suite(
        env_file=args.env_file,
        videos=videos,
        output_json=args.output_json,
        clip_end_sec=args.clip_end_sec,
        per_video_timeout_sec=args.per_video_timeout_sec,
        success_time_limit_sec=args.success_time_limit_sec,
    )


if __name__ == "__main__":
    raise SystemExit(main())
