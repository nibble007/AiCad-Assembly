"""
DSL Parser - Rule-based assembly command parser

Syntax (one command per line or separated by ';'):
    INSERT  A <depth>[mm|cm|in] B
    ROTATE  A <deg> <X|Y|Z>
    ALIGN   A B
    DUPLICATE A <count>
    STACK   A B [VERTICAL|HORIZONTAL]
    FASTEN  A B [type]
    OFFSET  A <x> <y> <z>        (each value takes optional mm|cm|in)

Flags (anywhere in the text): //ONLY-AI  //ONLY-RULEB  //RULEAI (default)
"""

import re
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Tuple

UNIT_MM = {"mm": 1.0, "cm": 10.0, "in": 25.4}

NAME = r"[\w.\-]+"
NUM = r"-?\d+(?:\.\d+)?"
DIST = rf"({NUM})\s*(mm|cm|in)?"

FLAG_RE = re.compile(r"//\s*(ONLY-AI|ONLY-RULEB|RULEAI)\b", re.IGNORECASE)


@dataclass
class Command:
    """A single assembly command. All distances are stored in mm."""
    type: str
    obj_a: str = ""
    obj_b: str = ""
    depth: Optional[float] = None
    unit: str = ""
    degrees: Optional[float] = None
    axis: str = ""
    direction: str = ""
    count: Optional[int] = None
    x: Optional[float] = None
    y: Optional[float] = None
    z: Optional[float] = None
    strategy: str = ""

    def to_dict(self) -> Dict:
        return {k: v for k, v in asdict(self).items() if v is not None and v != ""}


def _mm(value: str, unit: Optional[str]) -> float:
    return float(value) * UNIT_MM[(unit or "mm").lower()]


class DSLParser:
    """Parse assembly DSL into structured commands."""

    COMMAND_PATTERN = {
        "INSERT": re.compile(rf"INSERT\s+({NAME})\s+{DIST}\s+({NAME})", re.I),
        "ROTATE": re.compile(rf"ROTATE\s+({NAME})\s+({NUM})\s*(?:deg(?:rees)?)?\s+([XYZ])", re.I),
        "ALIGN": re.compile(rf"ALIGN\s+({NAME})\s+({NAME})", re.I),
        "DUPLICATE": re.compile(rf"DUPLICATE\s+({NAME})\s+(\d+)", re.I),
        "STACK": re.compile(rf"STACK\s+({NAME})\s+({NAME})(?:\s+(VERTICAL|HORIZONTAL))?", re.I),
        "FASTEN": re.compile(rf"FASTEN\s+({NAME})\s+({NAME})(?:\s+({NAME}))?", re.I),
        "OFFSET": re.compile(rf"OFFSET\s+({NAME})\s+{DIST}\s+{DIST}\s+{DIST}", re.I),
    }

    def __init__(self):
        self.commands: List[Command] = []
        self.unknown_parts: List[str] = []
        self.parse_quality = "unknown"
        self.confidence = 0.0

    # ------------------------------------------------------------------
    # Flags
    # ------------------------------------------------------------------
    def extract_flag(self, text: str) -> Tuple[str, str]:
        """Return (flag, text_without_flag). Default flag is RULEAI."""
        m = FLAG_RE.search(text)
        if not m:
            return "RULEAI", text.strip()
        return m.group(1).upper(), FLAG_RE.sub("", text).strip()

    # ------------------------------------------------------------------
    # Part-name handling (supports names with spaces, e.g. "Square Hole")
    # ------------------------------------------------------------------
    @staticmethod
    def _protect(line: str, known: List[str]) -> str:
        """Replace known part names (longest first) with space-free tokens."""
        order = sorted(range(len(known)), key=lambda i: -len(known[i]))
        for i in order:
            pat = rf"(?<![\w.\-]){re.escape(known[i])}(?![\w.\-])"
            line = re.sub(pat, f"__P{i}__", line, flags=re.IGNORECASE)
        return line

    def _restore(self, token: str, known: Optional[List[str]]) -> str:
        if not token:
            return token
        m = re.fullmatch(r"__P(\d+)__", token)
        if m and known:
            return known[int(m.group(1))]
        if known and token.lower() not in (k.lower() for k in known):
            if token not in self.unknown_parts:
                self.unknown_parts.append(token)
        return token

    # ------------------------------------------------------------------
    # Single command
    # ------------------------------------------------------------------
    def parse_single_command(self, line: str, known: Optional[List[str]] = None) -> Optional[Command]:
        line = line.strip()
        if not line or line.startswith(("#", "//")):
            return None

        if known:
            line = self._protect(line, known)

        keyword = line.split(None, 1)[0].upper()
        pattern = self.COMMAND_PATTERN.get(keyword)
        if not pattern:
            return None

        m = pattern.fullmatch(line)
        if not m:
            return None

        return self._create_command(keyword, m.groups(), known)

    def _create_command(self, cmd_type: str, g: tuple, known) -> Command:
        r = lambda t: self._restore(t, known)

        if cmd_type == "INSERT":
            return Command("INSERT", obj_a=r(g[0]), depth=_mm(g[1], g[2]), unit="mm", obj_b=r(g[3]))
        if cmd_type == "ROTATE":
            return Command("ROTATE", obj_a=r(g[0]), degrees=float(g[1]), axis=g[2].upper())
        if cmd_type == "ALIGN":
            return Command("ALIGN", obj_a=r(g[0]), obj_b=r(g[1]))
        if cmd_type == "DUPLICATE":
            return Command("DUPLICATE", obj_a=r(g[0]), count=int(g[1]))
        if cmd_type == "STACK":
            return Command("STACK", obj_a=r(g[0]), obj_b=r(g[1]), direction=(g[2] or "VERTICAL").upper())
        if cmd_type == "FASTEN":
            return Command("FASTEN", obj_a=r(g[0]), obj_b=r(g[1]), strategy=(g[2] or "SCREW").upper())
        if cmd_type == "OFFSET":
            return Command(
                "OFFSET", obj_a=r(g[0]), unit="mm",
                x=_mm(g[1], g[2]), y=_mm(g[3], g[4]), z=_mm(g[5], g[6]),
            )
        raise ValueError(cmd_type)

    # ------------------------------------------------------------------
    # Full parse
    # ------------------------------------------------------------------
    def parse(self, text: str, known_parts: Optional[List[str]] = None) -> Dict:
        """
        Args:
            text: DSL text (optionally with a //FLAG)
            known_parts: names of loaded parts (file stems). Enables names with
                         spaces and case-insensitive matching to the real part name.
        """
        flag, clean = self.extract_flag(text)

        self.commands = []
        self.unknown_parts = []
        self.parse_quality = "rule"

        lines = [l.strip() for l in re.split(r"[;\n]", clean)]
        lines = [l for l in lines if l and not l.startswith(("#", "//"))]

        for line in lines:
            cmd = self.parse_single_command(line, known_parts)
            if cmd:
                self.commands.append(cmd)

        matched = len(self.commands)
        total = len(lines)
        self.confidence = matched / total if total else 1.0

        return {
            "flag": flag,
            "commands": [c.to_dict() for c in self.commands],
            "parse_quality": self.parse_quality,
            "confidence": self.confidence,
            "matched_lines": matched,
            "total_lines": total,
            "unknown_parts": list(self.unknown_parts),
        }


if __name__ == "__main__":
    import json
    p = DSLParser()
    sample = """//ONLY-RULEB
    insert extruded square 5cm Square Hole
    ROTATE Extruded Square -90 x
    ALIGN Square Hole Extruded Square
    garbage line"""
    print(json.dumps(p.parse(sample, ["Square Hole", "Extruded Square"]), indent=2))