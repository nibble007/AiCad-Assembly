"""
Rule-based handler - DSL parsing + PythonOCC code generation.

Assembly is exported as a TopoDS_Compound (separate parts, original geometry
preserved). No boolean Fuse/Cut is used.
"""

import os
from dsl_parser import DSLParser


# Runtime helpers written at the top of every generated script.
CODE_HEADER = r'''import math
from pathlib import Path
from OCC.Core.STEPControl import STEPControl_Reader, STEPControl_Writer, STEPControl_AsIs
from OCC.Core.IFSelect import IFSelect_RetDone
from OCC.Core.BRepBuilderAPI import BRepBuilderAPI_Transform, BRepBuilderAPI_Copy
from OCC.Core.BRep import BRep_Builder
from OCC.Core.TopoDS import TopoDS_Compound
from OCC.Core.gp import gp_Trsf, gp_Vec, gp_Ax1, gp_Pnt, gp_Dir
from OCC.Core.Bnd import Bnd_Box
from OCC.Core.BRepBndLib import brepbndlib_Add

OUT = Path("output") / "assembled_model.step"
OUT.parent.mkdir(exist_ok=True)
OUT.unlink(missing_ok=True)

shapes = {}


def _key(s):
    return "".join(c for c in s.lower() if c.isalnum())


def find(name):
    k = _key(name)
    for n in shapes:
        if _key(n) == k:
            return n
    print("[WARN] Part not found: " + name)
    return None


def bbox(shape):
    b = Bnd_Box()
    brepbndlib_Add(shape, b)
    return b.Get()  # xmin, ymin, zmin, xmax, ymax, zmax


def center(bb):
    return ((bb[0] + bb[3]) / 2, (bb[1] + bb[4]) / 2, (bb[2] + bb[5]) / 2)


def load(path, name):
    r = STEPControl_Reader()
    if r.ReadFile(path) != IFSelect_RetDone:
        print("[FAIL] Could not read " + name)
        return
    r.TransferRoots()
    shapes[name] = r.OneShape()
    print("[OK] Loaded: " + name)


def move(n, dx, dy, dz):
    t = gp_Trsf()
    t.SetTranslation(gp_Vec(dx, dy, dz))
    shapes[n] = BRepBuilderAPI_Transform(shapes[n], t, True).Shape()


def op_insert(a, b, depth):
    # Center A on B in XY; A's lower end ends up `depth` mm below B's top face.
    a, b = find(a), find(b)
    if not (a and b):
        return
    ba, bb = bbox(shapes[a]), bbox(shapes[b])
    ca, cb = center(ba), center(bb)
    move(a, cb[0] - ca[0], cb[1] - ca[1], (bb[5] - depth) - ba[2])
    print("[OK] INSERT " + a + " -> " + b)


def op_rotate(a, deg, axis):
    # Rotate about the part's own bounding-box center.
    a = find(a)
    if not a:
        return
    cx, cy, cz = center(bbox(shapes[a]))
    d = {"X": gp_Dir(1, 0, 0), "Y": gp_Dir(0, 1, 0), "Z": gp_Dir(0, 0, 1)}[axis]
    t = gp_Trsf()
    t.SetRotation(gp_Ax1(gp_Pnt(cx, cy, cz), d), math.radians(deg))
    shapes[a] = BRepBuilderAPI_Transform(shapes[a], t, True).Shape()
    print("[OK] ROTATE " + a)


def op_align(a, b):
    # Match bounding-box centers (all three axes).
    a, b = find(a), find(b)
    if not (a and b):
        return
    ca, cb = center(bbox(shapes[a])), center(bbox(shapes[b]))
    move(a, cb[0] - ca[0], cb[1] - ca[1], cb[2] - ca[2])
    print("[OK] ALIGN " + a + " -> " + b)


def op_stack(a, b, direction):
    # Place B on top of A (VERTICAL) or beside A along +X (HORIZONTAL).
    a, b = find(a), find(b)
    if not (a and b):
        return
    ba, bb = bbox(shapes[a]), bbox(shapes[b])
    ca, cb = center(ba), center(bb)
    if direction == "HORIZONTAL":
        move(b, ba[3] - bb[0], ca[1] - cb[1], ca[2] - cb[2])
    else:
        move(b, ca[0] - cb[0], ca[1] - cb[1], ba[5] - bb[2])
    print("[OK] STACK " + b + " on " + a)


def op_duplicate(a, count):
    # `count` = total number of instances (original + count-1 copies).
    a = find(a)
    if not a:
        return
    for i in range(1, count):
        shapes[a + "_copy" + str(i)] = BRepBuilderAPI_Copy(shapes[a]).Shape()
    print("[OK] DUPLICATE " + a + " x" + str(count))


def op_offset(a, x, y, z):
    a = find(a)
    if a:
        move(a, x, y, z)
        print("[OK] OFFSET " + a)


def op_fasten(a, b, kind):
    print("[INFO] FASTEN " + a + " / " + b + " (" + kind + ") - no geometry change yet")

'''

CODE_FOOTER = r'''
if shapes:
    builder = BRep_Builder()
    compound = TopoDS_Compound()
    builder.MakeCompound(compound)
    for s in shapes.values():
        builder.Add(compound, s)
    writer = STEPControl_Writer()
    writer.Transfer(compound, STEPControl_AsIs)
    if writer.Write(str(OUT)) == IFSelect_RetDone:
        print("[OK] Saved: " + str(OUT) + " (" + str(len(shapes)) + " parts)")
    else:
        print("[FAIL] STEP write failed")
else:
    print("[FAIL] No shapes loaded")
'''


class RuleBasedHandler:
    def __init__(self):
        self.parser = DSLParser()

    def parse(self, user_input: str, known_parts=None):
        """
        Returns dict: flag, method, commands, confidence, matched, total, unknown_parts.
        known_parts: list of loaded part names (file stems).
        """
        result = self.parser.parse(user_input, known_parts)
        return {
            "flag": result["flag"],
            "method": "rule_only",
            "commands": result["commands"],
            "confidence": result["confidence"],
            "matched": result["matched_lines"],
            "total": result["total_lines"],
            "unknown_parts": result["unknown_parts"],
        }

    def generate_code(self, parse_result: dict, step_files: list) -> str:
        """Build the PythonOCC script from parsed commands + loaded STEP files."""
        out = [CODE_HEADER]

        for path in step_files:
            stem = os.path.splitext(os.path.basename(path))[0]
            out.append(f"load({path!r}, {stem!r})")
        out.append("")

        for cmd in parse_result.get("commands", []):
            t = str(cmd.get("type", "")).upper()
            a, b = cmd.get("obj_a", ""), cmd.get("obj_b", "")

            if t == "INSERT":
                out.append(f"op_insert({a!r}, {b!r}, {float(cmd.get('depth') or 0)})")
            elif t == "ROTATE":
                out.append(f"op_rotate({a!r}, {float(cmd.get('degrees') or 0)}, {str(cmd.get('axis') or 'Z').upper()!r})")
            elif t == "ALIGN":
                out.append(f"op_align({a!r}, {b!r})")
            elif t == "STACK":
                out.append(f"op_stack({a!r}, {b!r}, {str(cmd.get('direction') or 'VERTICAL').upper()!r})")
            elif t == "DUPLICATE":
                out.append(f"op_duplicate({a!r}, {int(cmd.get('count') or 2)})")
            elif t == "OFFSET":
                out.append(f"op_offset({a!r}, {float(cmd.get('x') or 0)}, {float(cmd.get('y') or 0)}, {float(cmd.get('z') or 0)})")
            elif t == "FASTEN":
                out.append(f"op_fasten({a!r}, {b!r}, {str(cmd.get('strategy') or 'SCREW')!r})")

        out.append(CODE_FOOTER)
        return "\n".join(out)