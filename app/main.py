from fastapi import FastAPI

from .analyzer import analyze, analyze_guarantee, plan_completion, plan_deactivation
from .schemas import (
    CompletionRequest,
    CompletionResponse,
    DeadlockRequest,
    DeadlockResponse,
    DeactivationRequest,
    DeactivationResponse,
    GuaranteeRequest,
    GuaranteeResponse,
)

app = FastAPI(
    title="Offline Two-Party Message Protocol Deadlock Analyzer",
    version="1.3.0",
)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/deadlocks", response_model=DeadlockResponse)
def detect_deadlocks(request: DeadlockRequest) -> dict:
    return analyze(request)


@app.post("/v1/completion-plans", response_model=CompletionResponse)
def plan_completion_endpoint(request: CompletionRequest) -> dict:
    return plan_completion(request)


@app.post("/v1/deactivation-plans", response_model=DeactivationResponse)
def plan_deactivation_endpoint(request: DeactivationRequest) -> dict:
    return plan_deactivation(request)


@app.post("/v1/completion-guarantees", response_model=GuaranteeResponse)
def analyze_completion_guarantee(request: GuaranteeRequest) -> dict:
    return analyze_guarantee(request)
