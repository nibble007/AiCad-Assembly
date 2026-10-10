import os
import io
import threading
import traceback
import contextlib
import tkinter as tk
from tkinter import filedialog, ttk, scrolledtext

from handlers.rule_based_handler import RuleBasedHandler
from handlers.ai_handler import AIHandler


class CADAssemblyGUI:
    def __init__(self, root):
        self.root = root
        self.step_files = []

        self.rule_handler = RuleBasedHandler()
        self.ai_handler = AIHandler()

        self.root.title("AI-Assisted CAD Assembly System")
        self.root.geometry("1100x820")
        self.root.configure(bg="#0a0a0a")

        self.setup_ui()

    def setup_ui(self):
        """Setup the GUI"""

        # Header
        tk.Label(
            self.root, text="AI-Assisted CAD Assembly",
            font=("Arial", 18, "bold"), fg="#10b981", bg="#0a0a0a"
        ).pack(pady=(14, 2))

        tk.Label(
            self.root, text="Upload STEP files  •  Describe in plain language  •  AI-powered",
            font=("Arial", 9), fg="#888", bg="#0a0a0a"
        ).pack(pady=(0, 10))

        # Main split
        split = tk.Frame(self.root, bg="#0a0a0a")
        split.pack(fill="both", expand=True, padx=12, pady=6)

        left = tk.Frame(split, bg="#0a0a0a", width=540)
        right = tk.Frame(split, bg="#0a0a0a")
        left.pack(side="left", fill="both", expand=False, padx=(0, 8))
        left.pack_propagate(False)
        right.pack(side="right", fill="both", expand=True)

        # Left panel - Files
        pf = tk.LabelFrame(
            left, text="  Loaded Parts  ",
            font=("Arial", 10, "bold"), fg="white", bg="#2a2a2e",
            bd=1, relief="groove", padx=8, pady=6
        )
        pf.pack(fill="x", pady=(0, 8))

        lf = tk.Frame(pf, bg="#2a2a2e")
        lf.pack(fill="both")

        self.file_list = tk.Listbox(
            lf, width=65, height=5, font=("Consolas", 9),
            bg="#0a0a0a", fg="#e0e0e0", selectbackground="#10b981",
            bd=0, highlightthickness=0
        )
        self.file_list.pack(side="left", fill="both", expand=True)

        sb = tk.Scrollbar(lf, bg="#2a2a2e")
        sb.pack(side="right", fill="y")
        self.file_list.config(yscrollcommand=sb.set)
        sb.config(command=self.file_list.yview)

        self.count_var = tk.StringVar(value="No files loaded")
        tk.Label(
            pf, textvariable=self.count_var,
            font=("Arial", 8), fg="#666", bg="#2a2a2e", anchor="w"
        ).pack(fill="x", pady=(4, 0))

        # File buttons
        br = tk.Frame(pf, bg="#2a2a2e")
        br.pack(fill="x", pady=(6, 0))

        tk.Button(
            br, text="📂 Add STEP Files", command=self.upload_files,
            font=("Arial", 10), bg="#10b981", fg="white",
            relief="flat", padx=8, pady=3, cursor="hand2"
        ).pack(side="left", padx=(0, 4))

        tk.Button(
            br, text="✕ Remove", command=self.remove_selected,
            font=("Arial", 10), bg="#666", fg="white",
            relief="flat", padx=8, pady=3, cursor="hand2"
        ).pack(side="left", padx=(0, 4))

        tk.Button(
            br, text="🗑 Clear", command=self.clear_files,
            font=("Arial", 10), bg="#444", fg="white",
            relief="flat", padx=8, pady=3, cursor="hand2"
        ).pack(side="left", padx=(0, 4))

        # Prompt
        promptf = tk.LabelFrame(
            left, text="  Assembly Instructions  ",
            font=("Arial", 10, "bold"), fg="white", bg="#2a2a2e",
            bd=1, relief="groove", padx=8, pady=6
        )
        promptf.pack(fill="x", pady=(0, 8))

        # Flags
        flag_frame = tk.Frame(promptf, bg="#2a2a2e")
        flag_frame.pack(fill="x", pady=(0, 3))

        tk.Label(
            flag_frame, text="Flags:", font=("Arial", 8), fg="#666", bg="#2a2a2e"
        ).pack(side="left", padx=(0, 4))

        for flag_text in ["//ONLY-AI", "//ONLY-RULEB", "//RULEAI"]:
            tk.Button(
                flag_frame, text=flag_text,
                command=lambda f=flag_text: self._insert_text(f + "\n"),
                font=("Arial", 7), bg="#1a1a1a", fg="#10b981",
                relief="flat", padx=4, pady=2, cursor="hand2"
            ).pack(side="left", padx=(0, 2))

        # Commands
        cmd_frame = tk.Frame(promptf, bg="#2a2a2e")
        cmd_frame.pack(fill="x", pady=(0, 4))

        tk.Label(
            cmd_frame, text="Cmds:", font=("Arial", 8), fg="#666", bg="#2a2a2e"
        ).pack(side="left", padx=(0, 4))

        for cmd in ["INSERT", "ROTATE", "ALIGN", "DUPLICATE", "STACK", "FASTEN"]:
            tk.Button(
                cmd_frame, text=cmd,
                command=lambda c=cmd: self._insert_text(c + " "),
                font=("Arial", 7), bg="#1a1a1a", fg="#64b5f6",
                relief="flat", padx=4, pady=2, cursor="hand2"
            ).pack(side="left", padx=(0, 2))

        # Dynamic Parts Frame
        self.parts_frame = tk.Frame(promptf, bg="#2a2a2e")
        self.parts_frame.pack(fill="x", pady=(0, 4))

        tk.Label(
            self.parts_frame, text="Parts:", font=("Arial", 8), fg="#666", bg="#2a2a2e"
        ).pack(side="left", padx=(0, 4))

        self.parts_button_frame = tk.Frame(self.parts_frame, bg="#2a2a2e")
        self.parts_button_frame.pack(side="left", fill="x")

        # Text box for assembly instructions
        text_frame = tk.Frame(promptf, bg="#2a2a2e")
        text_frame.pack(fill="both", expand=True, pady=(3, 4))

        self.prompt_text = scrolledtext.ScrolledText(
            text_frame, font=("Consolas", 10), bg="#0a0a0a", fg="#e0e0e0",
            insertbackground="#10b981", relief="flat", bd=2,
            height=6, wrap="word"
        )
        self.prompt_text.pack(side="left", fill="both", expand=True, padx=(0, 4))

        tk.Button(
            text_frame, text="✕\nClear",
            command=self._clear_prompt,
            font=("Arial", 8), bg="#444", fg="white",
            relief="flat", padx=4, pady=2, cursor="hand2"
        ).pack(side="left", fill="y")

        self.api_status_var = tk.StringVar(value="")
        tk.Label(
            promptf, textvariable=self.api_status_var,
            font=("Arial", 8), fg="#10b981", bg="#2a2a2e"
        ).pack(anchor="w", pady=(3, 0))

        # Progress
        pgf = tk.Frame(left, bg="#0a0a0a")
        pgf.pack(fill="x", pady=(0, 6))

        self.progress_var = tk.IntVar(value=0)
        style = ttk.Style()
        style.theme_use("default")
        style.configure(
            "G.Horizontal.TProgressbar",
            troughcolor="#1a1a1a", background="#10b981", thickness=16
        )
        ttk.Progressbar(
            pgf, variable=self.progress_var, maximum=100,
            style="G.Horizontal.TProgressbar"
        ).pack(side="left", fill="x", expand=True)

        self.status_var = tk.StringVar(value="Waiting…")
        tk.Label(
            pgf, textvariable=self.status_var,
            font=("Arial", 9), fg="#10b981", bg="#0a0a0a",
            width=20, anchor="w"
        ).pack(side="left", padx=8)

        # Results tree
        mf = tk.LabelFrame(
            left, text="  Assembly Results  ",
            font=("Arial", 10, "bold"), fg="white", bg="#2a2a2e",
            bd=1, relief="groove", padx=6, pady=4
        )
        mf.pack(fill="both", expand=True, pady=(0, 8))

        cols = ("Pair", "Strategy", "Fit", "Conf", "Status")
        self.result_tree = ttk.Treeview(mf, columns=cols, show="headings", height=5)
        for c, w in zip(cols, [190, 90, 110, 55, 50]):
            self.result_tree.heading(c, text=c)
            self.result_tree.column(c, width=w, anchor="w")
        self.result_tree.pack(fill="both", expand=True)

        style.configure(
            "Treeview", background="#0a0a0a", foreground="#e0e0e0",
            fieldbackground="#0a0a0a", rowheight=22
        )
        style.configure("Treeview.Heading", background="#1a1a1a", foreground="#10b981")
        style.map("Treeview", background=[("selected", "#10b981")])

        # Action buttons
        act = tk.Frame(left, bg="#0a0a0a")
        act.pack(pady=8)

        self.assemble_btn = tk.Button(
            act, text="⚙  Run Assembly",
            font=("Arial", 12, "bold"), bg="#10b981", fg="white",
            relief="flat", padx=16, pady=8, cursor="hand2",
            command=self.assemble
        )
        self.assemble_btn.pack(side="left", padx=4)

        self.viewer_btn = tk.Button(
            act, text="🔭  3D Viewer",
            font=("Arial", 10, "bold"), bg="#1a1a1a", fg="#888",
            relief="flat", padx=10, pady=8, state="disabled", cursor="hand2"
        )
        self.viewer_btn.pack(side="left", padx=4)

        self.report_btn = tk.Button(
            act, text="📄  Report",
            font=("Arial", 10), bg="#1a1a1a", fg="#888",
            relief="flat", padx=10, pady=8, state="disabled", cursor="hand2"
        )
        self.report_btn.pack(side="left", padx=4)

        # Log
        lf2 = tk.LabelFrame(
            right, text="  Assembly Log  ",
            font=("Arial", 10, "bold"), fg="white", bg="#2a2a2e",
            bd=1, relief="groove", padx=8, pady=6
        )
        lf2.pack(fill="both", expand=True)

        self.log_box = scrolledtext.ScrolledText(
            lf2, font=("Consolas", 9), bg="#0a0a0a", fg="#e0e0e0",
            bd=0, highlightthickness=0, state="disabled", wrap="word"
        )
        self.log_box.pack(fill="both", expand=True)

        for tag, col in [
            ("ok", "#10b981"), ("err", "#ff6b6b"), ("info", "#64b5f6"),
            ("warn", "#ffd93d"), ("sep", "#333"), ("dim", "#666"), ("ai", "#10b981")
        ]:
            self.log_box.tag_config(tag, foreground=col)

        # Footer
        tk.Label(
            self.root, text="AI-Assisted CAD Assembly  •  PythonOCC  •  Gemini-Powered",
            font=("Arial", 8), fg="#333", bg="#0a0a0a"
        ).pack(side="bottom", pady=6)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _log(self, msg, tag=""):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", msg + "\n", tag)
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _insert_text(self, text):
        """Insert text at cursor position in prompt text box"""
        self.prompt_text.insert("end", text)
        self.prompt_text.focus()

    def _clear_prompt(self):
        """Clear prompt text box"""
        self.prompt_text.delete("1.0", "end")

    def _part_names(self):
        return [os.path.splitext(os.path.basename(f))[0] for f in self.step_files]

    # ------------------------------------------------------------------
    # File management
    # ------------------------------------------------------------------
    def upload_files(self):
        files = filedialog.askopenfilenames(
            title="Select STEP Files",
            filetypes=[("STEP", "*.step *.stp"), ("All", "*.*")]
        )
        if files:
            added = 0
            for f in files:
                f = os.path.abspath(f)
                if f not in self.step_files:
                    self.step_files.append(f)
                    added += 1
            self._refresh_list()
            self._log(f"Added {added} file(s). Total: {len(self.step_files)}", "info")

    def clear_files(self):
        self.step_files.clear()
        self.file_list.delete(0, "end")
        self.count_var.set("No files loaded")
        self._update_parts_buttons()

    def remove_selected(self):
        sel = self.file_list.curselection()
        if sel:
            self.step_files.pop(sel[0])
            self._refresh_list()

    def _refresh_list(self):
        self.file_list.delete(0, "end")
        for i, f in enumerate(self.step_files, 1):
            name = os.path.basename(f)
            folder = os.path.dirname(f)
            if len(folder) > 40:
                folder = "…" + folder[-35:]
            self.file_list.insert("end", f"  {i:2d}.  {name:<24} {folder}")
        n = len(self.step_files)
        self.count_var.set(f"{n} file(s)" + (" — need ≥1" if n < 1 else " — ready ✓"))
        self._update_parts_buttons()

    def _update_parts_buttons(self):
        """Update parts buttons based on loaded files"""
        for widget in self.parts_button_frame.winfo_children():
            widget.destroy()

        part_names = self._part_names()
        if part_names:
            for part in part_names:
                tk.Button(
                    self.parts_button_frame, text=part,
                    command=lambda p=part: self._insert_text(p + " "),
                    font=("Arial", 7), bg="#1a1a1a", fg="#c9d1d9",
                    relief="flat", padx=3, pady=2, cursor="hand2"
                ).pack(side="left", padx=(0, 2))
        else:
            tk.Label(
                self.parts_button_frame, text="(add STEP files)",
                font=("Arial", 7), fg="#555", bg="#2a2a2e"
            ).pack(side="left")

    # ------------------------------------------------------------------
    # Assembly
    # ------------------------------------------------------------------
    def assemble(self):
        if not self.step_files:
            self._log("⚠  Add at least 1 STEP file.", "warn")
            return

        self.assemble_btn.config(state="disabled")
        self.progress_var.set(0)
        self.result_tree.delete(*self.result_tree.get_children())
        self._log("─" * 60, "sep")

        user_input = self.prompt_text.get("1.0", "end").strip()
        if not user_input:
            self._log("⚠  Enter assembly instructions.", "warn")
            self.assemble_btn.config(state="normal")
            return

        self._log(f'Input: "{user_input}"', "info")

        def _run():
            try:
                # ── Parse ────────────────────────────────────────────
                self.progress_var.set(20)
                self.status_var.set("Parsing…")

                result = self.rule_handler.parse(user_input, self._part_names())
                flag = result["flag"]

                self.api_status_var.set(f"Flag: {flag}")
                self._log(f"Flag: {flag}", "dim")
                self._log(f"Rule parse: {result['matched']}/{result['total']} lines ({result['confidence']:.0%})", "dim")

                if result.get("unknown_parts"):
                    self._log(f"⚠ Not loaded parts: {', '.join(result['unknown_parts'])}", "warn")

                for i, cmd in enumerate(result["commands"], 1):
                    self._log(f"  Cmd{i}: {cmd}", "ai")

                # ── AI routing by flag ───────────────────────────────
                #   ONLY-RULEB : never call AI
                #   ONLY-AI    : always AI, ignore rule result
                #   RULEAI     : AI only when rules are not confident
                use_ai = flag == "ONLY-AI" or (flag == "RULEAI" and result["confidence"] < 0.7)

                if use_ai:
                    self.progress_var.set(40)
                    self.status_var.set("Calling AI…")
                    ai_result = self.ai_handler.generate(
                        user_input, None if flag == "ONLY-AI" else result
                    )
                    if ai_result.get("error"):
                        self._log(f"⚠ AI error: {ai_result['error']}", "warn")
                    self._log(f"AI: {len(ai_result.get('commands', []))} cmds", "info")
                    ai_result["flag"] = flag
                    result = ai_result

                # ── Generate code ────────────────────────────────────
                self.progress_var.set(60)
                self.status_var.set("Generating code…")
                self._log("Generating PythonOCC code…", "dim")

                code = self.rule_handler.generate_code(result, self.step_files)
                self._log(f"✓ Generated {len(code)} bytes", "ok")

                os.makedirs("output", exist_ok=True)
                code_file = "output/generated_assembly.py"
                with open(code_file, "w", encoding="utf-8") as f:
                    f.write(code)
                self._log(f"✓ Saved: {code_file}", "dim")

                # ── Execute ──────────────────────────────────────────
                self.progress_var.set(80)
                self.status_var.set("Executing…")
                self._log("Executing assembly…", "dim")

                buf = io.StringIO()
                exec_ok = True
                try:
                    with contextlib.redirect_stdout(buf):
                        exec(compile(code, code_file, "exec"), {"__name__": "__main__"})
                except Exception:
                    exec_ok = False
                    self._log(traceback.format_exc(), "err")

                for line in buf.getvalue().splitlines():
                    tag = ("err" if line.startswith("[FAIL]")
                           else "warn" if line.startswith("[WARN]")
                           else "ok" if line.startswith("[OK]")
                           else "dim")
                    self._log("  " + line, tag)

                # ── Result ───────────────────────────────────────────
                out_file = "output/assembled_model.step"
                if exec_ok and os.path.exists(out_file):
                    self._log(f"✓ STEP file: {out_file}", "ok")
                    status = "Executed"
                else:
                    self._log("✗ No STEP file generated", "err")
                    status = "Failed"

                self.progress_var.set(100)
                self.status_var.set("Complete ✓" if status == "Executed" else "Failed ✗")
                self.api_status_var.set("")
                self._log("─" * 60, "sep")

                for cmd in result.get("commands", [])[:20]:
                    obj = cmd.get("obj_a", "?")
                    if cmd.get("obj_b"):
                        obj += f" → {cmd['obj_b']}"
                    self.result_tree.insert("", "end", values=(
                        obj, cmd.get("type", "?"), status,
                        f"{result.get('confidence', 0):.0%}",
                        "✓" if status == "Executed" else "✗"
                    ))

                if status == "Executed":
                    self.viewer_btn.config(state="normal")
                    self.report_btn.config(state="normal")

            except Exception as e:
                self._log(f"✗ Error: {e}", "err")
                self._log(traceback.format_exc(), "err")
            finally:
                self.assemble_btn.config(state="normal")

        threading.Thread(target=_run, daemon=True).start()


if __name__ == "__main__":
    root = tk.Tk()
    app = CADAssemblyGUI(root)
    root.mainloop()