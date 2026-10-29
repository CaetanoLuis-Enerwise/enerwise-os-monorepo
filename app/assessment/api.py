"""HTTP entry for the paid assessment. The report math stays in this package."""

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse

from app.assessment.analysis import run_assessment
from app.assessment.errors import AssessmentInputError
from app.assessment.html_report import render_html

router = APIRouter(prefix="/assessment", tags=["Assessment"])
_MAX_BYTES = 50 * 1024 * 1024


async def _read_upload(upload: UploadFile, label: str) -> str:
    payload = await upload.read()
    if len(payload) > _MAX_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"{label} is larger than 50 MB.",
        )
    if not payload:
        raise HTTPException(status_code=400, detail=f"{label} is empty.")
    try:
        return payload.decode("utf-8-sig")
    except UnicodeDecodeError:
        return payload.decode("cp1252")


@router.post("/report", response_class=HTMLResponse)
async def assessment_report(
    load_csv: UploadFile = File(..., description="15-minute load CSV."),
    omie_file: UploadFile = File(..., description="OMIE marginalpdbc file. MarginalPT, column 5."),
    site_id: str = Form("unspecified"),
    shiftable_fraction: float | None = Form(default=None),
    example_data: bool = Form(default=False),
):
    load_text = await _read_upload(load_csv, "Load CSV")
    omie_text = await _read_upload(omie_file, "OMIE file")
    try:
        result = run_assessment(
            load_text=load_text,
            omie_text=omie_text,
            site_id=site_id,
            shiftable_fraction=shiftable_fraction,
            example_data=example_data,
        )
    except AssessmentInputError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return HTMLResponse(render_html(result))
