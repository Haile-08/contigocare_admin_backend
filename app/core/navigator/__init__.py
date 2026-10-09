"""InnovaDerm Navigator, run inside the console.

A faithful port of ``innovaderm_v2_handover_2026-06-01``: the same parser, the
same five agents, the same prompts, run in the same order, producing the same
summary, coordinator report and broker kit. Module names follow the handover's
``agents/`` directory one for one, so a change can be checked against the
original by diffing two files.

What differs from the handover, and why:

- **Gemini instead of Claude**, for every agent (``AGENT_MODEL_*``).
- **Six arithmetic and calendar defects are fixed**, each marked ``FIX`` where it
  lives: negative payments, loading-dose units, 30-day months, MetLife's 0%
  coaseguro applied without programación, an invented authorisation, and oral
  JAK inhibitors treated as biológicos. Numbers therefore differ from the
  handover's saved outputs wherever one of those defects touched them.
- **Nothing is written to disk.** The handover wrote JSON, TXT, DOCX and ZIP files
  under ``outputs/``; here the summary is a database row and the report and kit
  are built in memory when downloaded.
- **The report and cover sheet are PDF**, not DOCX: the same sections and
  wording, in a file a coordinator or broker opens without a word processor.
- **Privacy is enforced by the server** rather than by the operator's protocol:
  the policy text is the console's redacted copy, the intake's free text is
  redacted before use, and generated letters are scrubbed.
"""
