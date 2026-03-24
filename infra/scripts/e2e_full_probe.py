#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import subprocess
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit


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


def run_psql_insert_user(pg_user: str, pg_db: str, full_name: str = "E2E Probe User") -> tuple[int, str, str]:
    unique = uuid.uuid4().hex[:12]
    google_sub = f"e2e-sub-{unique}"
    email = f"e2e-{unique}@backdroply.local"
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


def run_psql_exec(pg_user: str, pg_db: str, sql: str) -> str:
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
        raise RuntimeError(f"psql command failed: {proc.stderr.strip()}")
    return proc.stdout.strip()


def run_cmd(cmd: list[str]) -> tuple[int, str, str]:
    proc = subprocess.run(cmd, text=True, capture_output=True, check=False)
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def curl_with_output(args: list[str], output_path: Path, timeout_sec: int = 45) -> tuple[int, str]:
    cmd = [
        "curl.exe",
        "-sS",
        "--connect-timeout",
        "8",
        "--max-time",
        str(timeout_sec),
        "-o",
        str(output_path),
        "-w",
        "%{http_code}",
    ] + args
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
    timeout_sec: int = 45,
) -> tuple[int, dict]:
    out = tmp_dir / f"resp-{uuid.uuid4().hex}.json"
    args = ["-X", method, url, "-H", "Accept: application/json"]
    if token:
        args += ["-H", f"Authorization: Bearer {token}"]
    if body is not None:
        args += ["-H", "Content-Type: application/json", "--data", json.dumps(body, separators=(",", ":"))]
    code, raw = curl_with_output(args, out, timeout_sec=timeout_sec)
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
    timeout_sec: int = 180,
) -> tuple[int, dict]:
    out = tmp_dir / f"resp-{uuid.uuid4().hex}.json"
    args = ["-X", "POST", url, "-H", "Accept: application/json", "-H", f"Authorization: Bearer {token}"]
    if force_file_meta:
        args += ["-F", force_file_meta]
    else:
        args += ["-F", f"file=@{file_path.as_posix()}"]
    for key, value in (fields or {}).items():
        args += ["-F", f"{key}={value}"]
    code, raw = curl_with_output(args, out, timeout_sec=timeout_sec)
    out.unlink(missing_ok=True)
    if not raw:
        return code, {}
    try:
        return code, json.loads(raw)
    except json.JSONDecodeError:
        return code, {"_raw": raw}


def curl_download(tmp_dir: Path, url: str, token: str, target_path: Path, timeout_sec: int = 180) -> int:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    args = [
        "-L",
        "-X",
        "GET",
        url,
        "-H",
        f"Authorization: Bearer {token}",
    ]
    code, _ = curl_with_output(args, target_path, timeout_sec=timeout_sec)
    return code


def assert_status(name: str, code: int, expected: int) -> None:
    if code != expected:
        raise AssertionError(f"{name} expected HTTP {expected}, got {code}")


def wait_http_contains(url: str, expected_fragment: str, retries: int = 60, sleep_sec: float = 2.0) -> bool:
    for _ in range(retries):
        out = Path.cwd() / f".tmp-http-{uuid.uuid4().hex}.txt"
        try:
            code, body = curl_with_output(["-X", "GET", url], out)
            if code == 200 and expected_fragment in body:
                return True
        except Exception:
            pass
        finally:
            out.unlink(missing_ok=True)
        time.sleep(sleep_sec)
    return False


def token_balance(base: str, tmp_dir: Path, token: str) -> int:
    code, me = curl_json(tmp_dir, "GET", f"{base}/users/me", token=token)
    assert_status("get token balance /users/me", code, 200)
    if "tokens" in me:
        return int(me["tokens"])
    if "tokenBalance" in me:
        return int(me["tokenBalance"])
    raise AssertionError("/users/me payload missing tokens")


def wait_for_terminal_status(
    base: str,
    tmp_dir: Path,
    token: str,
    job_id: int,
    timeout_sec: int = 240,
    poll_sec: float = 1.0,
) -> tuple[dict, list[str]]:
    deadline = time.time() + timeout_sec
    observed: list[str] = []
    last_status = ""

    while time.time() < deadline:
        code, payload = curl_json(tmp_dir, "GET", f"{base}/media/jobs/{job_id}/status", token=token)
        assert_status(f"poll job status ({job_id})", code, 200)
        status = str(payload.get("status", "")).strip().lower()
        if status and status != last_status:
            observed.append(status)
            last_status = status
        if status in ("success", "failed"):
            return payload, observed
        time.sleep(poll_sec)

    raise TimeoutError(f"Job {job_id} did not reach terminal status in {timeout_sec}s. Observed={observed}")


def submit_and_wait(
    base: str,
    tmp_dir: Path,
    token: str,
    media_type: str,
    file_path: Path,
    fields: dict[str, str],
    expect_async: bool,
    expect_success: bool,
    timeout_sec: int = 240,
) -> tuple[int, dict, list[str]]:
    if media_type not in ("image", "video"):
        raise ValueError("media_type must be image or video")
    code, submit_payload = curl_multipart(tmp_dir, f"{base}/media/{media_type}", file_path, token, fields=fields)
    assert_status(f"submit {media_type}", code, 200)
    if "jobId" not in submit_payload:
        raise AssertionError(f"submit {media_type} payload missing jobId")

    job_id = int(submit_payload["jobId"])
    initial_status = str(submit_payload.get("status", "")).strip().lower()
    observed = [initial_status] if initial_status else []

    if expect_async and initial_status not in ("queued", "processing", "success"):
        raise AssertionError(f"Expected async submit status queued/processing/success, got: {initial_status!r}")

    if initial_status in ("success", "failed"):
        final_payload = submit_payload
    else:
        final_payload, polled_statuses = wait_for_terminal_status(
            base=base,
            tmp_dir=tmp_dir,
            token=token,
            job_id=job_id,
            timeout_sec=timeout_sec,
            poll_sec=1.0,
        )
        for st in polled_statuses:
            if st not in observed:
                observed.append(st)

    final_status = str(final_payload.get("status", "")).lower()
    if expect_success and final_status != "success":
        raise AssertionError(f"{media_type} job expected success, got {final_status}. Payload={final_payload}")
    if not expect_success and final_status != "failed":
        raise AssertionError(f"{media_type} job expected failed, got {final_status}. Payload={final_payload}")
    return job_id, final_payload, observed


def assert_downloadable(base: str, tmp_dir: Path, token: str, job_payload: dict, target_path: Path, label: str) -> None:
    download_rel = job_payload.get("downloadUrl")
    if not download_rel:
        raise AssertionError(f"{label} downloadUrl missing")
    download_url = f"http://localhost:{base.split(':')[-1]}{download_rel}" if download_rel.startswith("/") else str(download_rel)
    code = curl_download(tmp_dir, download_url, token, target_path)
    if code != 200 or not target_path.exists() or target_path.stat().st_size <= 0:
        raise AssertionError(f"{label} download failed (HTTP {code})")


def main() -> int:
    parser = argparse.ArgumentParser(description="Backdroply full E2E API probe")
    parser.add_argument("--env-file", required=True, type=Path)
    parser.add_argument("--tmp-dir", required=True, type=Path)
    parser.add_argument("--base-url", default="", help="Optional API base URL, e.g. http://localhost:8081/api/v1")
    parser.add_argument("--request-timeout-sec", type=int, default=45)
    parser.add_argument("--upload-timeout-sec", type=int, default=180)
    args = parser.parse_args()

    env_map = read_env_map(args.env_file)
    backend_port = int(env_map.get("BACKEND_PORT", "8080"))
    web_port = int(env_map.get("WEB_PORT", "8081"))
    jwt_secret = env_map.get("BACKEND_JWT_SECRET", "")
    jwt_expires_min = int(env_map.get("BACKEND_JWT_EXPIRES_MIN", "120"))
    pg_user = env_map.get("POSTGRES_USER", "bgadmin")
    pg_db = env_map.get("POSTGRES_DB", "bgremover")
    storage_enabled = env_map.get("STORAGE_ENABLED", "false").lower() == "true"
    queue_enabled = env_map.get("QUEUE_ENABLED", "false").lower() == "true"
    expect_async = queue_enabled and storage_enabled

    if len(jwt_secret) < 32:
        raise RuntimeError("BACKEND_JWT_SECRET is too short for E2E probe.")

    tmp_dir = args.tmp_dir
    tmp_dir.mkdir(parents=True, exist_ok=True)
    image_path = tmp_dir / "sample-image-small.jpg"
    video_path = tmp_dir / "sample-video-tiny.mp4"
    if not image_path.exists() or not video_path.exists():
        raise RuntimeError(f"Sample files are missing under {tmp_dir}")

    base_backend = f"http://localhost:{backend_port}/api/v1"
    base_web = f"http://localhost:{web_port}/api/v1"
    if args.base_url.strip():
        base = args.base_url.strip().rstrip("/")
    else:
        selected = None
        for candidate in (base_backend, base_web):
            try:
                code, _ = curl_json(tmp_dir, "GET", f"{candidate}/users/me", timeout_sec=10)
                if code in (200, 401, 403):
                    selected = candidate
                    break
            except Exception:
                pass
        base = selected or base_backend
    split = urlsplit(base)
    base_origin = f"{split.scheme}://{split.netloc}"
    print(f"[e2e] Base API: {base}")
    print(f"[e2e] Async queue expected: {expect_async}")

    code, _ = curl_json(tmp_dir, "GET", f"{base}/users/me", timeout_sec=args.request_timeout_sec)
    assert_status("unauth /users/me", code, 401)
    print("[e2e] Unauthorized guard OK")

    user_id, email, full_name = run_psql_insert_user(pg_user, pg_db, "E2E Probe User A")
    token = issue_jwt(jwt_secret, user_id, email, full_name, jwt_expires_min)
    print(f"[e2e] Seeded user id={user_id}")

    user2_id, email2, full_name2 = run_psql_insert_user(pg_user, pg_db, "E2E Probe User B")
    token2 = issue_jwt(jwt_secret, user2_id, email2, full_name2, jwt_expires_min)
    print(f"[e2e] Seeded secondary user id={user2_id}")

    code, me = curl_json(tmp_dir, "GET", f"{base}/users/me", token=token, timeout_sec=args.request_timeout_sec)
    assert_status("auth /users/me", code, 200)
    if int(me.get("id", -1)) != user_id:
        raise AssertionError("Authenticated /users/me returned unexpected user id")
    print("[e2e] Authenticated profile fetch OK")

    image_job_id, image_job, image_observed = submit_and_wait(
        base=base,
        tmp_dir=tmp_dir,
        token=token,
        media_type="image",
        file_path=image_path,
        fields={"quality": "balanced", "bgColor": "transparent"},
        expect_async=expect_async,
        expect_success=True,
        timeout_sec=180,
    )
    if expect_async and not any(st in ("queued", "processing") for st in image_observed):
        raise AssertionError(f"Image async lifecycle not observed. statuses={image_observed}")
    image_out = tmp_dir / "e2e-image-output.png"
    image_download_url = f"{base_origin}{image_job['downloadUrl']}"
    if curl_download(tmp_dir, image_download_url, token, image_out) != 200 or image_out.stat().st_size <= 0:
        raise AssertionError("Image output download failed")
    print(f"[e2e] Image processing OK (jobId={image_job_id}, statuses={image_observed})")

    video_job_id, video_job, video_observed = submit_and_wait(
        base=base,
        tmp_dir=tmp_dir,
        token=token,
        media_type="video",
        file_path=video_path,
        fields={"quality": "balanced", "bgColor": "transparent"},
        expect_async=expect_async,
        expect_success=True,
        timeout_sec=360,
    )
    if expect_async and not any(st in ("queued", "processing") for st in video_observed):
        raise AssertionError(f"Video async lifecycle not observed. statuses={video_observed}")
    video_out = tmp_dir / "e2e-video-output.webm"
    video_download_url = f"{base_origin}{video_job['downloadUrl']}"
    if curl_download(tmp_dir, video_download_url, token, video_out) != 200 or video_out.stat().st_size <= 0:
        raise AssertionError("Video output download failed")
    print(f"[e2e] Video processing OK (jobId={video_job_id}, statuses={video_observed})")

    code, _ = curl_json(
        tmp_dir,
        "GET",
        f"{base}/media/jobs/{image_job_id}/status",
        token=token2,
        timeout_sec=args.request_timeout_sec,
    )
    if code not in (403, 404):
        raise AssertionError(f"IDOR status guard failed. expected 403/404, got {code}")
    code = curl_download(
        tmp_dir,
        f"{base_origin}/api/v1/media/jobs/{image_job_id}/download",
        token2,
        tmp_dir / "e2e-idor.bin",
        timeout_sec=args.request_timeout_sec,
    )
    if code not in (403, 404):
        raise AssertionError(f"IDOR download guard failed. expected 403/404, got {code}")
    print("[e2e] IDOR guards OK")

    code, _ = curl_json(tmp_dir, "POST", f"{base}/auth/logout", token=token2, timeout_sec=args.request_timeout_sec)
    assert_status("logout secondary user", code, 200)
    code, _ = curl_json(tmp_dir, "GET", f"{base}/users/me", token=token2, timeout_sec=args.request_timeout_sec)
    if code != 401:
        raise AssertionError(f"Logout token revocation failed, expected 401 got {code}")
    run_psql_exec(pg_user, pg_db, f"DELETE FROM users WHERE id = {user2_id};")
    print("[e2e] Logout token revocation OK")

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

    if expect_async:
        before_balance = token_balance(base, tmp_dir, token)
        print(f"[e2e] Refund probe start token balance={before_balance}")

        rc, _, err = run_cmd(["docker", "stop", "bgremover-engine"])
        if rc != 0:
            raise RuntimeError(f"Failed to stop engine for refund probe: {err}")
        try:
            failed_job_id, failed_job, failed_observed = submit_and_wait(
                base=base,
                tmp_dir=tmp_dir,
                token=token,
                media_type="image",
                file_path=image_path,
                fields={"quality": "ultra", "bgColor": "transparent"},
                expect_async=True,
                expect_success=False,
                timeout_sec=180,
            )
            print(f"[e2e] Failure path observed (jobId={failed_job_id}, statuses={failed_observed})")
            if failed_job.get("errorMessage") in (None, ""):
                raise AssertionError("Failed job must contain errorMessage")
        finally:
            rc, _, err = run_cmd(["docker", "start", "bgremover-engine"])
            if rc != 0:
                raise RuntimeError(f"Failed to restart engine after refund probe: {err}")
            if not wait_http_contains("http://localhost:9000/health", '"status":"ok"', retries=80, sleep_sec=2.0):
                raise RuntimeError("Engine did not become healthy after restart.")

        after_balance = token_balance(base, tmp_dir, token)
        if after_balance != before_balance:
            raise AssertionError(
                f"Token refund failed after processing failure. before={before_balance}, after={after_balance}"
            )
        print("[e2e] Token refund on failure OK")

    if storage_enabled:
        for idx in range(11):
            _, _, _ = submit_and_wait(
                base=base,
                tmp_dir=tmp_dir,
                token=token,
                media_type="image",
                file_path=image_path,
                fields={"quality": "balanced", "bgColor": "transparent"},
                expect_async=expect_async,
                expect_success=True,
                timeout_sec=180,
            )
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
