# Distributed Architecture Plan (Professional Baseline)

This document defines the production architecture for Backdroply under high concurrency, while preserving output quality and keeping operational risk manageable for an indie team.

## 1) Target Principles

- Keep quality deterministic: same input + same model profile => same output class.
- Protect tokens and billing integrity: no token burn on incomplete jobs.
- Scale with queue depth, not with HTTP timeouts.
- Keep security strict by default (zero-trust internal network, least privilege, auditable events).

## 2) Authentication Architecture

## Recommended now

- Keep Google OAuth as user identity provider.
- Backend remains source of truth for app users/tokens/plans.
- Issue short-lived app JWT access token + rotate refresh token (HTTP-only secure cookie).
- Validate access tokens at API gateway and backend with asymmetric keys (RS256/ES256 + `kid`).
- Keep token/session state in Redis for fast revocation and distributed logout.

Why this path:
- lower operational overhead than running a full IAM server
- enough for Google-first SaaS launch
- easier to harden and monitor with current team size

## Keycloak decision

Use Keycloak when you need at least two of these:
- enterprise SSO (SAML/OIDC federation, Azure AD/Okta)
- role/realm complexity across many tenants
- centralized policy/admin console for IAM team

If these are not immediate needs, Keycloak adds operational burden (HA, upgrades, CVE patching, backup/restore, realm migration) without near-term product gain.

## 3) Queue and Processing Backbone

## RabbitMQ for job orchestration (recommended)

Use RabbitMQ for media job queueing:
- per-job ACK/NACK
- dead-letter queues (DLQ)
- delayed retries with backoff
- queue priorities for plan tiers
- simpler operational model for task queues

Kafka is not the primary job queue here. Kafka is better for immutable event streams and analytics replay, not for per-job retry/ACK semantics in this workload.

## Kafka usage (optional, later)

Use Kafka as event bus for:
- product analytics
- billing/audit events fan-out
- long-term event replay and BI pipelines

## 4) End-to-End Job Flow

1. Client uploads media to backend.
2. Backend validates file type/signature and security checks.
3. Backend stores input to object storage (S3/MinIO), creates `job_record` as `QUEUED`.
4. Backend reserves tokens transactionally (reservation state, not final spend).
5. Backend publishes `job_id` to RabbitMQ.
6. Worker consumes job, calls engine (GPU-first, CPU fallback).
7. Worker writes output artifact to object storage.
8. Backend marks job `COMPLETED`, commits token spend, emits audit event.
9. If failed/timeout/cancelled: mark `FAILED`, release/refund reserved token.

Critical rule:
- token commit only after durable completion state
- reservation refund on crash/recovery path

## 5) Status and ETA for Frontend

Frontend does not guess. It reads backend job state:
- `QUEUED`
- `PROCESSING`
- `COMPLETED`
- `FAILED`

Expose endpoint:
- `GET /api/v1/jobs/{id}` => state, queuePosition, workerStartedAt, updatedAt, errorCode

Delivery model:
- start with polling (1.5-2.0s)
- upgrade to SSE/WebSocket for high-scale UX

ETA model:
- `eta = (queuePosition * rolling_avg_service_time(profile, media_type, duration_bucket)) + current_processing_remaining_estimate`
- update ETA continuously; show confidence band (low/medium confidence)

This avoids fake static ETA and keeps UX honest under load.

## 6) Scaling Strategy

## Compute

- Engine workers are stateless containers.
- GPU nodes process heavy jobs; CPU nodes handle fallback or low-priority jobs.
- Use separate worker pools by profile:
  - `ultra-gpu`
  - `balanced-gpu`
  - `balanced-cpu-fallback`

## Queue controls

- per-user concurrency cap remains enforced in backend
- per-plan queue priority and max queued jobs
- global backpressure: reject new jobs with explicit message when queue > threshold

## Storage

- S3-compatible object storage with lifecycle rules:
  - raw input TTL
  - output retention by plan
  - encrypted at rest

## 7) Kubernetes Decision

## Recommended progression

Phase A (now): Docker Compose + single VM/2-node setup  
Phase B (growth): k3s or managed Kubernetes (EKS/GKE/AKS) when:
- sustained concurrent jobs > 30-50
- need autoscaling by queue depth
- need rolling upgrades without downtime
- need node pools (GPU/CPU) and stronger SLO enforcement

Kubernetes is valuable, but adopt when operational complexity is justified by load and uptime requirements.

## 8) Security Controls (Must-Have)

- WAF + rate limits at edge
- mTLS or private network isolation between gateway/backend/worker
- signed internal service-to-service tokens with short TTL
- antivirus/content scanning and strict MIME/signature validation
- immutable audit log for auth, billing, token spend/refund
- secrets only in vault/secret manager (no plaintext in repo)

## 9) Observability and SLO

- Metrics: queue depth, job success rate, p50/p95 processing time, GPU utilization, token refund count.
- Tracing: request -> job enqueue -> worker -> artifact upload -> billing commit.
- Alerting: stuck jobs, rising DLQ, auth failures, payment webhook failures.

## 10) Go-Live Decision Rules

- No unresolved P0/P1 security vulnerabilities.
- Token integrity tests pass (no double-spend, no lost refund).
- Queue recovery tests pass after forced worker crash.
- Throughput test meets declared SLO at target concurrency.
- Legal/contact/compliance pages reachable from web + mobile.
