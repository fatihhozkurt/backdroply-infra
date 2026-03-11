#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import subprocess
import threading
import time
import uuid
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
    signing_input = f"{b64url(json.dumps(header, separators=(',', ':')).encode('utf-8'))}.{b64url(json.dumps(payload, separators=(',', ':')).encode('utf-8'))}"
    signature = hmac.new(secret.encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256).digest()
    return f"{signing_input}.{b64url(signature)}"


def run_psql_insert_user(pg_user: str, pg_db: str) -> tuple[int, str, str]:
    unique = uuid.uuid4().hex[:12]
    google_sub = f"e2e-sub-{unique}"
    email = f"e2e-{unique}@backdroply.local"
    full_name = "E2E Probe User"
    sql = (
        "INSERT INTO users (google_sub, email, full_name, language, token_balance, created_at, updated_at, last_login_at) "
        f"VALUES ('{google_sub}', '{email}', '{full_name}', 'en', 120, NOW(), NOW(), NOW()) RETURNING id;"
    )
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
        raise RuntimeError(f"User seed failed: {proc.stderr.strip()}")
    output = proc.stdout.strip()
    user_id = None
    for line in output.splitlines():
        candidate = line.strip()
        if candidate.isdigit():
            user_id = int(candidate)
            break
    if user_id is None:
        raise RuntimeError(f"User seed returned unexpected id: {output}")
    return user_id, email, full_name


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


def curl_json(
    tmp_dir: Path,
    method: str,
    url: str,
    token: str | None = None,
    body: dict | None = None,
) -> tuple[int, dict]:
    out = tmp_dir / f"resp-{uuid.uuid4().hex}.json"
    args = ["-X", method, url, "-H", "Accept: application/json"]
    if token:
        args += ["-H", f"Authorization: Bearer {token}"]
    if body is not None:
        args += ["-H", "Content-Type: application/json", "--data", json.dumps(body, separators=(",", ":"))]
    code, raw = curl_with_output(args, out)
    out.unlink(missing_ok=True)
    if not raw:
        return code, {}
    try:
        return code, json.loads(raw)
    except json.JSONDecodeError:
        return code, {"_raw": raw}


def curl_multipart(
    tmp_dir: Path,
    url: str,
    file_path: Path,
    token: str,
    fields: dict[str, str] | None = None,
    force_file_meta: str | None = None,
) -> tuple[int, dict]:
    out = tmp_dir / f"resp-{uuid.uuid4().hex}.json"
    args = ["-X", "POST", url, "-H", "Accept: application/json", "-H", f"Authorization: Bearer {token}"]
    if force_file_meta:
        args += ["-F", force_file_meta]
    else:
        args += ["-F", f"file=@{file_path.as_posix()}"]
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


def curl_download(tmp_dir: Path, url: str, token: str, target_path: Path) -> int:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    args = [
        "-L",
        "-X",
        "GET",
        url,
        "-H",
        f"Authorization: Bearer {token}",
    ]
    code, _ = curl_with_output(args, target_path)
    return code


def assert_status(name: str, code: int, expected: int) -> None:
    if code != expected:
        raise AssertionError(f"{name} expected HTTP {expected}, got {code}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Backdroply full E2E API probe")
    parser.add_argument("--env-file", required=True, type=Path)
    parser.add_argument("--tmp-dir", required=True, type=Path)
    args = parser.parse_args()

    env_map = read_env_map(args.env_file)
    backend_port = int(env_map.get("BACKEND_PORT", "8080"))
    jwt_secret = env_map.get("BACKEND_JWT_SECRET", "")
    jwt_expires_min = int(env_map.get("BACKEND_JWT_EXPIRES_MIN", "120"))
    pg_user = env_map.get("POSTGRES_USER", "bgadmin")
    pg_db = env_map.get("POSTGRES_DB", "bgremover")
    storage_enabled = env_map.get("STORAGE_ENABLED", "false").lower() == "true"

    if len(jwt_secret) < 32:
        raise RuntimeError("BACKEND_JWT_SECRET is too short for E2E probe.")

    tmp_dir = args.tmp_dir
    tmp_dir.mkdir(parents=True, exist_ok=True)
    image_path = tmp_dir / "sample-image-small.jpg"
    video_path = tmp_dir / "sample-video-tiny.mp4"
    if not image_path.exists() or not video_path.exists():
        raise RuntimeError(f"Sample files are missing under {tmp_dir}")

    base = f"http://localhost:{backend_port}/api/v1"
    print(f"[e2e] Base API: {base}")

    code, _ = curl_json(tmp_dir, "GET", f"{base}/users/me")
    assert_status("unauth /users/me", code, 401)
    print("[e2e] Unauthorized guard OK")

    user_id, email, full_name = run_psql_insert_user(pg_user, pg_db)
    token = issue_jwt(jwt_secret, user_id, email, full_name, jwt_expires_min)
    print(f"[e2e] Seeded user id={user_id}")

    code, me = curl_json(tmp_dir, "GET", f"{base}/users/me", token=token)
    assert_status("auth /users/me", code, 200)
    if int(me.get("id", -1)) != user_id:
        raise AssertionError("Authenticated /users/me returned unexpected user id")
    print("[e2e] Authenticated profile fetch OK")

    code, image_job = curl_multipart(
        tmp_dir,
        f"{base}/media/image",
        image_path,
        token,
        fields={"quality": "balanced", "bgColor": "transparent"},
    )
    assert_status("process image", code, 200)
    image_job_id = int(image_job["jobId"])
    image_download_url = f"http://localhost:{backend_port}{image_job['downloadUrl']}"
    image_out = tmp_dir / "e2e-image-output.png"
    if curl_download(tmp_dir, image_download_url, token, image_out) != 200 or image_out.stat().st_size == 0:
        raise AssertionError("Image output download failed")
    print(f"[e2e] Image processing OK (jobId={image_job_id})")

    code, video_job = curl_multipart(
        tmp_dir,
        f"{base}/media/video",
        video_path,
        token,
        fields={"quality": "balanced", "bgColor": "transparent"},
    )
    assert_status("process video", code, 200)
    video_job_id = int(video_job["jobId"])
    video_download_url = f"http://localhost:{backend_port}{video_job['downloadUrl']}"
    video_out = tmp_dir / "e2e-video-output.webm"
    if curl_download(tmp_dir, video_download_url, token, video_out) != 200 or video_out.stat().st_size == 0:
        raise AssertionError("Video output download failed")
    print(f"[e2e] Video processing OK (jobId={video_job_id})")

    code, frame_payload = curl_multipart(
        tmp_dir,
        f"{base}/media/video/frame",
        video_path,
        token,
        fields={"timeSec": "0.3"},
    )
    assert_status("extract frame", code, 200)
    frame_data = str(frame_payload.get("frameDataUrl", ""))
    if not frame_data.startswith("data:image/png;base64,"):
        raise AssertionError("Frame extraction payload is invalid")
    print("[e2e] Frame extraction OK")

    payload_path = tmp_dir / "e2e-malicious.js"
    payload_path.write_text("<script>alert('x')</script>", encoding="utf-8")
    code, _ = curl_multipart(
        tmp_dir,
        f"{base}/media/image",
        payload_path,
        token,
        fields={"quality": "balanced"},
        force_file_meta=f"file=@{payload_path.as_posix()};filename=evil.png;type=image/png",
    )
    assert_status("malicious payload block", code, 400)
    print("[e2e] Malicious payload block OK")

    concurrent_ok = False
    for attempt in range(1, 5):
        statuses: list[int] = []
        lock = threading.Lock()
        barrier = threading.Barrier(3)

        def worker() -> None:
            barrier.wait()
            code_local, _ = curl_multipart(
                tmp_dir,
                f"{base}/media/video",
                video_path,
                token,
                fields={"quality": "ultra", "bgColor": "transparent"},
            )
            with lock:
                statuses.append(code_local)

        t1 = threading.Thread(target=worker, daemon=True)
        t2 = threading.Thread(target=worker, daemon=True)
        t1.start()
        t2.start()
        barrier.wait()
        t1.join()
        t2.join()
        if 429 in statuses:
            concurrent_ok = True
            print(f"[e2e] Concurrency limit OK (attempt={attempt}, statuses={statuses})")
            break
        print(f"[e2e] Concurrency probe retry (attempt={attempt}, statuses={statuses})")
        time.sleep(0.5)

    if not concurrent_ok:
        raise AssertionError("Concurrency limit was not observed during parallel video processing.")

    if storage_enabled:
        for idx in range(11):
            code, _ = curl_multipart(
                tmp_dir,
                f"{base}/media/image",
                image_path,
                token,
                fields={"quality": "balanced", "bgColor": "transparent"},
            )
            assert_status(f"my-media fill iteration {idx + 1}", code, 200)
        code, my_media = curl_json(tmp_dir, "GET", f"{base}/media/my-media", token=token)
        assert_status("get my-media", code, 200)
        if not isinstance(my_media, list):
            raise AssertionError("my-media payload is not a list")
        if len(my_media) != 10:
            raise AssertionError(f"my-media cap must be 10, got {len(my_media)}")
        print("[e2e] My Media cap enforcement OK")

    code, history = curl_json(tmp_dir, "GET", f"{base}/users/history", token=token)
    assert_status("get history", code, 200)
    if not isinstance(history, list) or len(history) == 0:
        raise AssertionError("History must contain processed jobs")
    print("[e2e] History endpoint OK")

    code, _ = curl_json(tmp_dir, "DELETE", f"{base}/users/me", token=token)
    assert_status("delete account", code, 200)
    code, _ = curl_json(tmp_dir, "GET", f"{base}/users/me", token=token)
    if code not in (401, 404):
        raise AssertionError(f"/users/me after delete expected 401 or 404, got {code}")
    print("[e2e] Account deletion flow OK")

    print("[e2e] Full probe finished successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
