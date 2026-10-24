# Devin-Hackathon — Cold Plate Requirements Intake (ITherm 2027)

`stage1_intake/` is a Gradio chatbot that collects and validates the inputs for a
cold-plate simulation. It writes `requirements_final.json` for a later optimizer
stage, which is not implemented here.

- Python owns the field list, unit conversion, validation and checks C1–C8; the LLM
  only phrases questions and extracts values via tool calls.
- Defaults are never confirmed silently: each group is confirmed explicitly, and
  warnings (e.g. C5 coolant rise) must be acknowledged before finalizing.
- Each session writes `sessions/<id>/requirements.json` and `notes.txt` (with the
  user's exact quotes) as it goes, and `requirements_final.json` once finalized.

## Run

```bash
cd stage1_intake
uv venv --python 3.11 .venv          # or: python3.11 -m venv .venv
uv pip install -r requirements.txt   # or: .venv/bin/pip install -r requirements.txt
cp .env.example .env                 # then paste your GEMINI_API_KEY into .env
.venv/bin/python app.py              # open http://127.0.0.1:7860
```

Without a key (or with `--provider mock`) it runs a scripted mock bot that only
understands "yes" and choice names.

## Demo script

1. Click **Load ITherm 2027 preset**.
2. `Yes those limits are right, but over 4 psi is a penalty, not disqualification.`
3. `Use 2 L/min nominal, 30 C inlet, sweep flow only at 30 C.`
4. `Actually make the TIM 0.08 cm2K/W.`
5. `Yes, use those.` for each remaining group.
6. Acknowledge the C5 coolant-rise warning, then `yes` on the final summary.

## Tests

```bash
cd stage1_intake
.venv/bin/python -m pytest -q                  # offline, mock LLM
RUN_LIVE=1 .venv/bin/python -m pytest -q tests/test_live_gemini.py   # real Gemini
```
