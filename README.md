# CodeCheck backend

Flask API for sending submitted code to Gemini and returning an AI review.

## Setup

1. Open a terminal in this `backend` folder.
2. Create a virtual environment (optional but recommended):
   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```
3. Install the dependencies:
   ```powershell
   pip install -r requirements.txt
   ```
4. Copy `.env.example` to a new file named `.env`.
5. Put your own Gemini key in `.env`:
   ```env
   GEMINI_API_KEY=your_real_key_here
   ```
6. Start the server:
   ```powershell
   py app.py
   ```

The API runs at `http://127.0.0.1:5000`.

The backend calls Gemini through the HTTP API directly, so you do not need the `google-genai` Python package.

## Analyze code

Send a `POST` request to `/analyze` with JSON like this:

```json
{
  "code": "print('Hello, CodeCheck!')"
}
```

Successful responses have this shape:

```json
{
  "analysis": "AI-generated code review"
}
```

Do not commit your `.env` file or share its API key. The existing frontend was not changed.
