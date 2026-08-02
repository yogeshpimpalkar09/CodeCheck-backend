import json
import os
import re
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, make_response, request, send_from_directory
from flask_cors import CORS
import requests


load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent
API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite").strip()

app = Flask(__name__)
# Allow local testing plus the production site and preview URLs created by Vercel.
CORS(
    app,
    resources={
        r"/*": {
            "origins": [
                r"http://localhost(:\d+)?",
                r"http://127\.0\.0\.1(:\d+)?",
                r"https://.*\.vercel\.app",
            ]
        }
    },
)


def no_cache_response(file_name: str):
    response = make_response(send_from_directory(PROJECT_ROOT, file_name))
    response.headers["Cache-Control"] = "no-store, max-age=0"
    return response


@app.get("/")
def home():
    return no_cache_response("index.html")


@app.get("/app.js")
def serve_js():
    return no_cache_response("app.js")


@app.get("/styles.css")
def serve_css():
    return no_cache_response("styles.css")


@app.get("/health")
def health():
    return jsonify(
        {
            "ok": True,
            "backend": "CodeError",
            "model": GEMINI_MODEL,
            "api_key_loaded": bool(API_KEY),
        }
    )


def mask_key(value: str | None) -> str:
    if not value:
        return "missing"
    value = value.strip()
    if len(value) <= 8:
        return "***"
    return f"{value[:4]}…{value[-4:]}"


def extract_json_payload(text: str):
    if not isinstance(text, str) or not text.strip():
        return None

    candidates = [
        text.strip(),
        re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.IGNORECASE),
    ]
    candidates.append(re.sub(r"\s*```$", "", candidates[-1]).strip())

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed

    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
        if isinstance(parsed, dict):
            return parsed
    return None


def extract_line_and_column(text: str):
    if not text:
      return None, None

    patterns = [
        r"\bline\s+(\d+)\s*,\s*column\s+(\d+)\b",
        r"\bline\s+(\d+)\s*:\s*column\s+(\d+)\b",
        r"\bline\s+(\d+)\s+column\s+(\d+)\b",
        r":(\d+):(\d+)\b",
        r"\bline\s+(\d+)\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            line = int(match.group(1))
            column = int(match.group(2)) if len(match.groups()) > 1 and match.group(2) else None
            return line, column
    return None, None


def detect_issue_type(text: str):
    lowered = (text or "").lower()
    if any(word in lowered for word in ("referenceerror", "is not defined", "nameerror")):
        return "variable"
    if any(word in lowered for word in ("cannot read properties", "cannot read property", "undefined", "null", "nonetype")):
        return "emptyData"
    if any(word in lowered for word in ("syntaxerror", "unexpected token", "invalid syntax")) or any(q in text for q in ('"', "'")):
        return "syntax"
    if any(word in lowered for word in ("modulenotfounderror", "cannot find module", "module not found")):
        return "package"
    if any(word in lowered for word in ("indentationerror", "expected an indented", "unexpected indent")):
        return "indent"
    return "general"


def local_review(code: str, explanation_language: str = "english"):
    issue_type = detect_issue_type(code)
    is_hindi = explanation_language == "hindi"
    lines = code.splitlines() or [code]

    titles = {
        "general": ("Let’s understand this error", "चलो, इस error को समझते हैं"),
        "variable": ("The variable cannot be found", "Variable नहीं मिला"),
        "emptyData": ("The data is not available yet", "डेटा अभी मौजूद नहीं है"),
        "syntax": ("There is a code grammar mistake", "Code की लिखावट में गलती है"),
        "package": ("A required package is missing", "ज़रूरी package नहीं मिला"),
        "indent": ("The spacing alignment is incorrect", "Spacing alignment गलत है"),
    }

    analysis = {
        "general": (
            "Your program found a problem it cannot solve by itself. Read the file name and line number first.",
            "आपके program को एक ऐसी समस्या मिली है जिसे वह खुद ठीक नहीं कर सकता। पहले file name और line number देखें।",
        ),
        "variable": (
            "Your code is using a name that was never created, or the spelling is different.",
            "आपका code ऐसे name का use कर रहा है जो अभी बनाया नहीं गया है, या spelling अलग है।",
        ),
        "emptyData": (
            "You are trying to use a value that is currently undefined, null, or empty.",
            "आप ऐसी value use कर रहे हैं जो अभी undefined, null, या खाली है।",
        ),
        "syntax": (
            "The code looks like it is missing a bracket, quote, comma, or colon.",
            "Code में bracket, quote, comma, या colon छूट गया लगता है।",
        ),
        "package": (
            "The code is trying to use a library that is not installed or not imported correctly.",
            "Code एक ऐसी library use कर रहा है जो install नहीं है या सही तरह import नहीं हुई है।",
        ),
        "indent": (
            "A Python block needs the next line to be indented correctly.",
            "Python block में अगली line सही indentation के साथ होनी चाहिए।",
        ),
    }

    suggestions = {
        "general": (
            ["Read the file name and line number in the error.", "Check spelling, brackets, and variable names near that line.", "Make one small change and run the program again."],
            ["Error message में file name और line number देखें।", "उस line के पास spelling, brackets और variable names जाँचें।", "एक छोटा बदलाव करें और program फिर चलाएँ।"],
        ),
        "variable": (
            ["Find the name shown in the error.", "Create it before you use it, with const, let, var, or def.", "Check capital letters carefully."],
            ["Error में दिया नाम ढूँढें।", "Use करने से पहले उसे const, let, var, या def से बनाइए।", "Capital letters ध्यान से देखें।"],
        ),
        "emptyData": (
            ["Check whether the value exists first.", "Print the variable before using it.", "Add a condition before reading it."],
            ["पहले जाँचें कि value मौजूद है या नहीं।", "Use करने से पहले variable print करें।", "पढ़ने से पहले condition लगाएँ।"],
        ),
        "syntax": (
            ["Check the line in the error and the line above it.", "Match every opening bracket with a closing one.", "Check quotes and commas carefully."],
            ["Error वाली line और उसके ऊपर वाली line देखें।", "हर opening bracket का closing bracket मिलाएँ।", "Quotes और commas ध्यान से जाँचें।"],
        ),
        "package": (
            ["Read the package name carefully.", "Install that package in your project.", "Check the spelling in the import statement."],
            ["Package का नाम ध्यान से पढ़ें।", "उस package को अपने project में install करें।", "Import statement की spelling जाँचें।"],
        ),
        "indent": (
            ["Align the error line with the block above.", "Do not mix tabs and spaces.", "Use 4 spaces inside blocks."],
            ["Error line को ऊपर वाले block के साथ align करें।", "Tabs और spaces mix न करें।", "Block के अंदर 4 spaces use करें।"],
        ),
    }

    fix_code = {
        "variable": "const name = \"Asha\";\nconsole.log(name);",
        "syntax": "",
        "package": "",
        "indent": "",
        "emptyData": "",
        "general": "",
    }

    line_no, column_no = extract_line_and_column(code)
    if line_no is None and lines:
        line_no = 1
        first_line = lines[0]
    else:
        first_line = lines[line_no - 1] if line_no and 0 < line_no <= len(lines) else lines[0]

    return {
        "title": titles[issue_type][1 if is_hindi else 0],
        "analysis": analysis[issue_type][1 if is_hindi else 0],
        "likely_line": line_no,
        "likely_column": column_no or 1,
        "likely_snippet": first_line.strip(),
        "suggestions": suggestions[issue_type][1 if is_hindi else 0],
        "fixed_code": fix_code[issue_type],
        "source": "local",
    }


def build_prompt(code: str, explanation_language: str):
    prompt_language = "simple Hindi" if explanation_language == "hindi" else "simple English"
    return f"""You are CodeError, a beginner-friendly code reviewer.
Analyze the code below in {prompt_language}.

Return ONLY valid JSON in this exact shape:
{{
  "title": "short issue title",
  "analysis": "beginner-friendly explanation",
  "likely_line": 1,
  "likely_column": 1,
  "likely_snippet": "exact line of code if you can identify it",
  "suggestions": ["step 1", "step 2", "step 3"],
  "fixed_code": "corrected code or empty string if not needed"
}}

Rules:
- If no issue is found, set likely_line to null and fixed_code to an empty string.
- Do not invent errors.
- Keep the answer short and easy to read.

Code to review:
```
{code}
```"""


def call_gemini(code: str, explanation_language: str):
    if not API_KEY:
        return None

    endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": build_prompt(code, explanation_language)}],
            }
        ],
        "generationConfig": {"maxOutputTokens": 512},
    }

    response = requests.post(
        endpoint,
        json=payload,
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": API_KEY,
        },
        timeout=20,
    )
    response.raise_for_status()
    raw = response.text
    response_data = response.json()
    text = (
        response_data.get("candidates", [{}])[0]
        .get("content", {})
        .get("parts", [{}])[0]
        .get("text", "")
    )

    parsed = extract_json_payload(text)
    if not parsed:
        return None

    return {
        "title": parsed.get("title", "AI code review"),
        "analysis": parsed.get("analysis", ""),
        "likely_line": parsed.get("likely_line"),
        "likely_column": parsed.get("likely_column", 1),
        "likely_snippet": parsed.get("likely_snippet", ""),
        "suggestions": parsed.get("suggestions", []),
        "fixed_code": parsed.get("fixed_code", ""),
        "source": "gemini",
    }


@app.post("/analyze")
def analyze():
    print("ANALYZE HIT", flush=True)
    data = request.get_json(silent=True) or {}

    code = data.get("code", "")
    if not isinstance(code, str) or not code.strip():
        return jsonify({"error": "Send a JSON body with a non-empty 'code' field."}), 400

    explanation_language = data.get("explanationLanguage", "english")
    if explanation_language not in {"english", "hindi"}:
        explanation_language = "english"

    local = local_review(code, explanation_language)

    if not API_KEY:
        print(f"LOCAL ONLY: Gemini key missing, using fallback. model={GEMINI_MODEL}", flush=True)
        return jsonify(local)

    try:
        gemini = call_gemini(code, explanation_language)
        if gemini:
            print(f"GEMINI OK: model={GEMINI_MODEL} key={mask_key(API_KEY)}", flush=True)
            return jsonify(gemini)
        print("GEMINI EMPTY OR UNPARSEABLE: using local fallback", flush=True)
        local["source"] = "local_fallback"
        local["note"] = "Gemini returned no usable JSON, so a local review was used."
        return jsonify(local)
    except requests.HTTPError as exc:
        response = exc.response
        body = response.text if response is not None else str(exc)
        status_code = response.status_code if response is not None else None
        app.logger.warning("Gemini HTTP error %s: %s", status_code, body)
        print(f"GEMINI HTTP ERROR {status_code} body={body}", flush=True)
        local["source"] = "local_fallback"
        local["note"] = f"Gemini HTTP {status_code}, so a local review was used."
        return jsonify(local)
    except requests.RequestException as exc:
        app.logger.exception("Gemini request failed")
        print(f"GEMINI FAILED: {exc!r}", flush=True)
        local["source"] = "local_fallback"
        local["note"] = "Gemini failed, so a local review was used."
        return jsonify(local)
    except Exception as exc:
        app.logger.exception("Gemini request failed")
        print(f"GEMINI FAILED: {exc!r}", flush=True)
        local["source"] = "local_fallback"
        local["note"] = "Gemini failed, so a local review was used."
        return jsonify(local)


if __name__ == "__main__":
    app.logger.info("CodeError backend starting on http://127.0.0.1:5000")
    app.logger.info("GEMINI_MODEL=%s", GEMINI_MODEL)
    app.logger.info("GEMINI_API_KEY=%s", mask_key(API_KEY))
    app.run(host="127.0.0.1", port=5000, debug=True, use_reloader=False)
