from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

DetectorName = Literal["auto", "ensemble", "robust_z", "ewma", "seasonal", "iforest"]
MAX_POINTS = 200_000


class AnalyzeRequest(BaseModel):
    values: list[float] = Field(..., min_length=3, max_length=MAX_POINTS)
    timestamps: list[str] | None = None
    labels: list[bool] | None = None
    detector: DetectorName = "auto"
    sensitivity: float = Field(1.0, gt=0.05, le=10)
    period: int | None = Field(None, ge=2)

    @model_validator(mode="after")
    def _lengths(self) -> AnalyzeRequest:
        n = len(self.values)
        if self.timestamps is not None and len(self.timestamps) != n:
            raise ValueError("timestamps must have the same length as values")
        if self.labels is not None and len(self.labels) != n:
            raise ValueError("labels must have the same length as values")
        return self


class Anomaly(BaseModel):
    index: int
    timestamp: str | None
    value: float
    score: float
    reason: str


class AnalyzeResponse(BaseModel):
    detector: str
    params: dict
    n_points: int
    timestamps: list[str] | None
    values: list[float]
    scores: list[float]
    anomalies: list[Anomaly]
    metrics: dict | None = None
    detected_period: int | None = None


class StreamCreate(BaseModel):
    name: str = Field("my-metric", max_length=100)
    detector: Literal["robust_z", "ewma"] = "robust_z"
    threshold: float = Field(4.0, gt=0.5, le=50)
    window: int = Field(60, ge=10, le=10_000)
    webhook_url: str | None = Field(None, max_length=500)


class Point(BaseModel):
    value: float
    ts: str | None = None


class IngestRequest(BaseModel):
    points: list[Point] = Field(..., min_length=1, max_length=10_000)
