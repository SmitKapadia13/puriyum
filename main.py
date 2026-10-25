import os
from typing import Literal, Optional
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from google import genai
from google.genai import types
from gtts import gTTS
import io
import time
from fastapi.responses import JSONResponse

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
app = FastAPI()

MODELS = [
    os.environ.get("GEMINI_MODEL", "gemini-3.8-flash"),
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-flash-latest",
    "gemini-3.1-flash-lite",
]

class Contact(BaseModel):
    name: Optional[str]
    phone: Optional[str]
    address: Optional[str]

class Action(BaseModel):
    step: str
    by_when: Optional[str]

class DocResult(BaseModel):
    readable: bool
    confidence: float
    doc_type: str
    summary: str
    actions: list[Action]
    deadline: Optional[str]
    urgency: Literal["high", "medium", "low"]
    risk_flags: list[str]
    contact: Contact
    retake_reason: Optional[str]

PROMPT = """You explain official documents to low-literacy readers.

OUTPUT LANGUAGE: {lang}
Use simple words, short sentences. Max Class-5 reading level.

LANGUAGE RULE (CRITICAL — zero exceptions):
Every text field you produce — doc_type, summary, every actions[].step, every actions[].by_when, every risk_flags[] entry, contact.name — MUST be written in {lang}.
Never mix languages. If the document is in another language, translate the meaning into {lang}.
Keep the following as printed on the document (do NOT translate): digits, numbers, units (mg/dL, %, ₹), dates, phone numbers, proper nouns of people/organizations.

READABILITY & CONFIDENCE:
- Read ONLY what is clearly visible. Never invent or guess amounts, dates, names, or phone numbers.
- If the image is blurry, cropped, rotated, not a document, or any text is unclear: set readable=false, confidence below 0.3, set retake_reason explaining what is wrong. Leave all other fields at default/empty.
- confidence must reflect actual text clarity. A sharp, fully legible document may be 0.85-0.95. Partial blur or small unreadable sections: 0.5-0.8. Mostly unreadable: below 0.3. Do NOT default to 0.95.
- If you cannot read every key number clearly, readable=false.

FIELD RULES:
- summary: 2 sentences in {lang}. What is this document, and why does it matter to the person.
- actions: ordered steps the person must do, in {lang}. Include by_when as free text in {lang} if the document states a time frame (e.g., "immediately", "within 30 days"). by_when is display text, NOT a date.
- deadline: YYYY-MM-DD only if an exact calendar date is explicitly printed on the document. Otherwise null. Never compute or infer a deadline.
- urgency: high = payment deadline within 7 days, OR threat of disconnection, penalty, legal action, or abnormal medical values. medium = deadline within 30 days. low = purely informational, no deadline, no threat. If the document threatens disconnection, penalty, or legal action: urgency=high. Never low for those.
- risk_flags: list penalties, fees, legal threats, or abnormal medical values in {lang}. Quote the relevant value from the document (keep original digits and units). Translate the surrounding description into {lang}.
- contact: extract only if printed on the document. name in {lang}, phone/address as printed.

MEDICAL REPORTS — SAFETY (STRICT):
- State which values are marked as high or low ON the document. Quote the value and its reference range as printed.
- The ONLY action for a medical report is: "show this report to your doctor" (translated into {lang}).
- NEVER name a diagnosis, condition, disease, or treatment.
- NEVER say what a value "means" for the person's health. Only say the document marks it as high/low.
- NEVER recommend medication, lifestyle changes, diet, or any remedy.

LEGAL/FINANCIAL REPORTS — SAFETY:
- Do NOT give legal advice. Explain only what the document says.
- Action = "show this document to a legal advisor / the relevant office" (in {lang})."""

@app.post("/api/explain")
async def explain(file: UploadFile = File(...), lang: str = Form("English")):
    img = await file.read()
    last_err = None
    for attempt in range(2):
        for m in MODELS:
            try:
                res = client.models.generate_content(
                    model=m,
                    contents=[
                        types.Part.from_bytes(data=img, mime_type=file.content_type or "image/jpeg"),
                        PROMPT.format(lang=lang),
                    ],
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=DocResult,
                        temperature=0.1,
                    ),
                )
                if res.parsed:
                    return res.parsed
            except Exception as e:
                last_err = e
                print(f"MODEL FAIL {m}: {e}")
        time.sleep(2)
    return JSONResponse(status_code=503, content={"error": "busy", "detail": str(last_err)})

@app.post("/api/tts")
async def tts(text: str = Form(...), lang: str = Form("en")):
    buf = io.BytesIO()
    gTTS(text, lang=lang).write_to_fp(buf)
    return Response(buf.getvalue(), media_type="audio/mpeg")

app.mount("/", StaticFiles(directory="static", html=True), name="static")