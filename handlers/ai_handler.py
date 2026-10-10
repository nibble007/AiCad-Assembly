"""
AI handler - Gemini (google-genai SDK) for assembly instruction parsing.

Returns commands in the exact schema the rule-based codegen expects.
Model is configurable: set GEMINI_MODEL in .env (default below).
"""

import os
import re
import json
import time
import difflib
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # cwd
load_dotenv(Path(__file__).resolve().parent.parent / ".env")  # project root

DEFAULT_MODEL = "gemini-3.6-flash"

_client = None
_init_error = None
try:
    from google import genai

    _key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if _key:
        _client = genai.Client(api_key=_key)
    else:
        _init_error = "GEMINI_API_KEY not found (check your .env)"
except ImportError:
    _init_error = "google-genai not installed: pip install -U google-genai"
except Exception as e:  # bad key format etc.
    _init_error = f"Gemini init failed: {e}"


VALID_TYPES = {"INSERT", "ROTATE", "ALIGN", "DUPLICATE", "STACK", "FASTEN", "OFFSET"}
FLAG_RE = re.compile(r"//\s*(ONLY-AI|ONLY-RULEB|RULEAI)\b", re.IGNORECASE)
UNIT_MM = {"mm": 1.0, "cm": 10.0, "in": 25.4}

SYSTEM_PROMPT = """You convert CAD assembly instructions into JSON commands.

Command schema (all distances in millimetres, angles in degrees):
  INSERT    {"type":"INSERT","obj_a":<part>,"obj_b":<part>,"depth":<mm>}
  ROTATE    {"type":"ROTATE","obj_a":<part>,"degrees":<number>,"axis":"X"|"Y"|"Z"}
  ALIGN     {"type":"ALIGN","obj_a":<part>,"obj_b":<part>}
  DUPLICATE {"type":"DUPLICATE","obj_a":<part>,"count":<int, total instances>}
  STACK     {"type":"STACK","obj_a":<part>,"obj_b":<part>,"direction":"VERTICAL"|"HORIZONTAL"}
  FASTEN    {"type":"FASTEN","obj_a":<part>,"obj_b":<part>,"strategy":"SCREW"|"BOLT"|"WELD"}
  OFFSET    {"type":"OFFSET","obj_a":<part>,"x":<mm>,"y":<mm>,"z":<mm>}

Rules:
- obj_a / obj_b MUST be copied exactly from the provided part list. Never invent parts.
- Convert cm/inches to mm. Order commands as they should be executed.
- If part of the instruction is ambiguous or refers to an unknown part, omit that command.
- Output ONLY JSON: {"commands":[...]}. No prose, no markdown."""


def _num(v, default=None):
    """Coerce 20, '20', '2 cm', '1.5in' -> float mm-aware number."""
    if v is None:
        return default
    if isinstance(v, (int, float)):
        return float(v)
    m = re.fullmatch(r"\s*(-?\d+(?:\.\d+)?)\s*(mm|cm|in)?\s*", str(v), re.IGNORECASE)
    if not m:
        return default
    return float(m.group(1)) * UNIT_MM[(m.group(2) or "mm").lower()]


def _extract_json(text: str):
    """Best-effort JSON extraction from model text."""
    text = (text or "").strip()
    candidates = [text]
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if fence:
        candidates.append(fence.group(1).strip())
    if "{" in text and "}" in text:
        candidates.append(text[text.index("{"): text.rindex("}") + 1])
    for c in candidates:
        try:
            data = json.loads(c)
            return {"commands": data} if isinstance(data, list) else data
        except Exception:
            continue
    return None


class AIHandler:
    def __init__(self):
        self.client = _client
        self.init_error = _init_error
        self.model = os.getenv("GEMINI_MODEL", DEFAULT_MODEL)

    # ------------------------------------------------------------------
    def generate(self, user_input: str, rule_result: dict = None, known_parts: list = None):
        """
        Args:
            user_input: raw text from the GUI (flags are stripped before sending)
            rule_result: rule-based parse result to improve on (optional)
            known_parts: loaded part names (file stems) - strongly recommended
        """
        fallback = self._fallback(rule_result)

        if not self.client:
            return {**fallback, "error": self.init_error or "Gemini not configured"}

        prompt = self._build_prompt(user_input, rule_result, known_parts)
        config = {
            "system_instruction": SYSTEM_PROMPT,
            "response_mime_type": "application/json",
            "temperature": 0,
        }

        text, last_err = "", None
        for attempt in range(2):
            try:
                resp = self.client.models.generate_content(
                    model=self.model, contents=prompt, config=config
                )
                text = (resp.text or "").strip()
                if text:
                    last_err = None
                    break
                last_err = "Empty response (possibly blocked by safety filters)"
            except Exception as e:
                last_err = f"{type(e).__name__}: {e}"
            time.sleep(1.0)

        if last_err:
            return {**fallback, "error": f"{self.model}: {last_err}"}

        data = _extract_json(text)
        if data is None:
            return {**fallback, "error": "AI did not return valid JSON", "raw": text}

        raw_cmds = data.get("commands", [])
        commands, warnings = self._normalize(raw_cmds, known_parts)

        if not commands:
            return {
                **fallback,
                "error": "AI returned no valid commands",
                "warnings": warnings,
                "raw": text,
            }

        kept_ratio = len(commands) / max(len(raw_cmds), 1)
        return {
            "method": "rule_ai" if rule_result else "ai_only",
            "commands": commands,
            "confidence": round(0.9 * kept_ratio, 2),
            "warnings": warnings,
            "model": self.model,
            "raw": text,
        }

    # ------------------------------------------------------------------
    @staticmethod
    def _fallback(rule_result):
        """Used when AI fails: keep whatever the rule parser produced."""
        return {
            "method": "ai_error",
            "commands": (rule_result or {}).get("commands", []),
            "confidence": (rule_result or {}).get("confidence", 0.0),
        }

    @staticmethod
    def _build_prompt(user_input, rule_result, known_parts):
        instruction = FLAG_RE.sub("", user_input).strip()
        parts = "\n".join(f"- {p}" for p in (known_parts or [])) or "(none provided)"
        draft = ""
        if rule_result and rule_result.get("commands"):
            draft = (
                "\nRule-based draft (may be incomplete or wrong - fix and complete it):\n"
                + json.dumps(rule_result["commands"], indent=1)
            )
        return f"Available parts:\n{parts}\n\nInstruction:\n{instruction}\n{draft}"

    # ------------------------------------------------------------------
    @staticmethod
    def _snap(name, known):
        """Map an AI-provided name to a real part name (case/fuzzy). None if no match."""
        if not name:
            return None
        name = str(name).strip()
        if not known:
            return name
        lower = {k.lower(): k for k in known}
        if name.lower() in lower:
            return lower[name.lower()]
        close = difflib.get_close_matches(name.lower(), list(lower), n=1, cutoff=0.6)
        return lower[close[0]] if close else None

    def _normalize(self, raw_cmds, known):
        """Validate AI output into the schema codegen expects. Drops bad commands."""
        out, warns = [], []
        if not isinstance(raw_cmds, list):
            return out, ["'commands' was not a list"]

        for i, c in enumerate(raw_cmds, 1):
            if not isinstance(c, dict):
                warns.append(f"cmd {i}: not an object")
                continue

            t = str(c.get("type", "")).upper().strip()
            if t not in VALID_TYPES:
                warns.append(f"cmd {i}: unknown type '{c.get('type')}'")
                continue

            a = self._snap(c.get("obj_a"), known)
            if not a:
                warns.append(f"cmd {i} ({t}): unknown part '{c.get('obj_a')}'")
                continue

            cmd = {"type": t, "obj_a": a}

            if t in {"INSERT", "ALIGN", "STACK", "FASTEN"}:
                b = self._snap(c.get("obj_b"), known)
                if not b:
                    warns.append(f"cmd {i} ({t}): unknown part '{c.get('obj_b')}'")
                    continue
                cmd["obj_b"] = b

            if t == "INSERT":
                depth = _num(c.get("depth"))
                if depth is None:
                    warns.append(f"cmd {i} (INSERT): missing depth")
                    continue
                cmd.update(depth=depth, unit="mm")
            elif t == "ROTATE":
                deg = _num(c.get("degrees"))
                axis = str(c.get("axis", "")).upper().strip()
                if deg is None or axis not in {"X", "Y", "Z"}:
                    warns.append(f"cmd {i} (ROTATE): bad degrees/axis")
                    continue
                cmd.update(degrees=deg, axis=axis)
            elif t == "DUPLICATE":
                n = _num(c.get("count"))
                if n is None or n < 1:
                    warns.append(f"cmd {i} (DUPLICATE): bad count")
                    continue
                cmd["count"] = int(n)
            elif t == "STACK":
                d = str(c.get("direction", "VERTICAL")).upper().strip()
                cmd["direction"] = d if d in {"VERTICAL", "HORIZONTAL"} else "VERTICAL"
            elif t == "FASTEN":
                cmd["strategy"] = str(c.get("strategy") or "SCREW").upper().strip()
            elif t == "OFFSET":
                cmd.update(
                    x=_num(c.get("x"), 0.0), y=_num(c.get("y"), 0.0),
                    z=_num(c.get("z"), 0.0), unit="mm",
                )

            out.append(cmd)

        return out, warns