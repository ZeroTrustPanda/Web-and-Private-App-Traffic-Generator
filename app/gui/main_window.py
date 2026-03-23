"""Tkinter GUI for the Persona Traffic Generator."""
from __future__ import annotations

import asyncio
import os
import platform
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
from typing import Optional

from app.core.config_manager import ConfigManager
from app.core.run_session import RunSession
from app.models.models import (
    AppState, BehaviorIntensity, FeatureFlags,
    PrivateApp, RunMode, RuntimeStatus,
)


class TrafficGeneratorGUI:
    """Main application window."""

    def __init__(self, config: ConfigManager):
        self.config = config
        self.session: Optional[RunSession] = None
        self._worker_thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

        self.root = tk.Tk()
        self.root.title("Zscaler Lab — Persona Traffic Generator")
        self.root.geometry("1100x750")
        self.root.minsize(900, 600)

        # Style
        style = ttk.Style()
        if "clam" in style.theme_names():
            style.theme_use("clam")

        self._build_ui()
        self._refresh_persona_list()
        self._update_btn_state()

        # Periodic GUI refresh
        self.root.after(1000, self._periodic_refresh)

    # ── UI Construction ───────────────────────────────────────────────

    def _build_ui(self) -> None:
        # Top frame: controls + flags
        top = ttk.Frame(self.root, padding=8)
        top.pack(fill=tk.X)

        self._build_controls(top)
        self._build_flags(top)

        # Middle: private apps
        mid = ttk.LabelFrame(self.root, text="Private Apps", padding=6)
        mid.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)
        self._build_private_apps(mid)

        # Bottom: status
        bot = ttk.LabelFrame(self.root, text="Status & Metrics", padding=6)
        bot.pack(fill=tk.X, padx=8, pady=(0, 8))
        self._build_status(bot)

    def _build_controls(self, parent: ttk.Frame) -> None:
        f = ttk.LabelFrame(parent, text="Run Controls", padding=6)
        f.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 8))

        ttk.Label(f, text="Persona:").grid(row=0, column=0, sticky=tk.W)
        self.persona_var = tk.StringVar()
        self.persona_combo = ttk.Combobox(f, textvariable=self.persona_var, state="readonly", width=18)
        self.persona_combo.grid(row=0, column=1, padx=4, pady=2)
        self.persona_combo.bind("<<ComboboxSelected>>", lambda e: self._update_btn_state())

        ttk.Label(f, text="Run Mode:").grid(row=1, column=0, sticky=tk.W)
        self.mode_var = tk.StringVar(value=RunMode.MIXED_REALISTIC.value)
        ttk.Combobox(
            f, textvariable=self.mode_var, state="readonly", width=18,
            values=[m.value for m in RunMode],
        ).grid(row=1, column=1, padx=4, pady=2)

        ttk.Label(f, text="Intensity:").grid(row=2, column=0, sticky=tk.W)
        self.intensity_var = tk.StringVar(value=BehaviorIntensity.MEDIUM.value)
        ttk.Combobox(
            f, textvariable=self.intensity_var, state="readonly", width=18,
            values=[i.value for i in BehaviorIntensity],
        ).grid(row=2, column=1, padx=4, pady=2)

        btn_frame = ttk.Frame(f)
        btn_frame.grid(row=3, column=0, columnspan=2, pady=6)
        self.start_btn = ttk.Button(btn_frame, text="▶ Start", command=self._on_start)
        self.start_btn.pack(side=tk.LEFT, padx=2)
        self.stop_btn = ttk.Button(btn_frame, text="■ Stop", command=self._on_stop, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="Reset Stats", command=self._on_reset).pack(side=tk.LEFT, padx=2)

    def _build_flags(self, parent: ttk.Frame) -> None:
        f = ttk.LabelFrame(parent, text="Feature Toggles", padding=6)
        f.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 8))

        self.flag_ai = tk.BooleanVar(value=True)
        self.flag_geo = tk.BooleanVar(value=True)
        self.flag_tls = tk.BooleanVar(value=True)
        self.flag_phish = tk.BooleanVar(value=True)
        self.flag_malware = tk.BooleanVar(value=True)
        self.flag_private = tk.BooleanVar(value=True)

        for i, (text, var) in enumerate([
            ("Enable AI tests", self.flag_ai),
            ("Enable Restricted Geo tests", self.flag_geo),
            ("Enable TLS tests", self.flag_tls),
            ("Enable Phishing simulation", self.flag_phish),
            ("Enable Malware tests", self.flag_malware),
            ("Enable Private App tests", self.flag_private),
        ]):
            ttk.Checkbutton(f, text=text, variable=var).grid(row=i, column=0, sticky=tk.W, pady=1)

    def _build_private_apps(self, parent: ttk.Frame) -> None:
        cols = ("enabled", "name", "fqdn", "path", "title", "selector", "personas", "weight")
        self.apps_tree = ttk.Treeview(parent, columns=cols, show="headings", height=6)

        widths = {"enabled": 55, "name": 120, "fqdn": 160, "path": 70,
                  "title": 100, "selector": 80, "personas": 120, "weight": 50}
        for c in cols:
            self.apps_tree.heading(c, text=c.title())
            self.apps_tree.column(c, width=widths.get(c, 80), minwidth=40)

        sb = ttk.Scrollbar(parent, orient=tk.VERTICAL, command=self.apps_tree.yview)
        self.apps_tree.configure(yscrollcommand=sb.set)
        self.apps_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.LEFT, fill=tk.Y)

        btn_panel = ttk.Frame(parent, padding=4)
        btn_panel.pack(side=tk.LEFT, fill=tk.Y)
        ttk.Button(btn_panel, text="Add App", command=self._add_app).pack(fill=tk.X, pady=2)
        ttk.Button(btn_panel, text="Remove App", command=self._remove_app).pack(fill=tk.X, pady=2)
        ttk.Button(btn_panel, text="Save Apps", command=self._save_apps).pack(fill=tk.X, pady=2)

        self._refresh_apps_tree()

    def _build_status(self, parent: ttk.Frame) -> None:
        f = ttk.Frame(parent)
        f.pack(fill=tk.X)

        labels = [
            ("State:", "state_var"),
            ("Persona:", "s_persona_var"),
            ("URL:", "s_url_var"),
            ("Action:", "s_action_var"),
            ("Last Result:", "s_result_var"),
        ]
        for i, (text, attr) in enumerate(labels):
            ttk.Label(f, text=text).grid(row=i // 3, column=(i % 3) * 2, sticky=tk.W, padx=4)
            var = tk.StringVar(value="—")
            setattr(self, attr, var)
            ttk.Label(f, textvariable=var, width=30).grid(row=i // 3, column=(i % 3) * 2 + 1, sticky=tk.W)

        f2 = ttk.Frame(parent)
        f2.pack(fill=tk.X, pady=4)

        counters = [
            ("Actions:", "s_actions_var"),
            ("Blocked:", "s_blocked_var"),
            ("Warnings:", "s_warnings_var"),
            ("Failures:", "s_failures_var"),
            ("Elapsed:", "s_elapsed_var"),
            ("Restarts:", "s_restarts_var"),
        ]
        for i, (text, attr) in enumerate(counters):
            ttk.Label(f2, text=text).grid(row=0, column=i * 2, padx=4)
            var = tk.StringVar(value="0")
            setattr(self, attr, var)
            ttk.Label(f2, textvariable=var, width=8).grid(row=0, column=i * 2 + 1)

        f3 = ttk.Frame(parent)
        f3.pack(fill=tk.X, pady=2)
        ttk.Button(f3, text="Open Logs", command=self._open_logs).pack(side=tk.LEFT, padx=4)
        ttk.Button(f3, text="Open Screenshots", command=self._open_screenshots).pack(side=tk.LEFT, padx=4)

    # ── Actions ───────────────────────────────────────────────────────

    def _on_start(self) -> None:
        name = self.persona_var.get()
        persona = self.config.get_persona(name)
        if not persona:
            messagebox.showerror("Error", "Select a valid persona.")
            return

        mode = next((m for m in RunMode if m.value == self.mode_var.get()), RunMode.MIXED_REALISTIC)
        intensity = next((i for i in BehaviorIntensity if i.value == self.intensity_var.get()),
                         BehaviorIntensity.MEDIUM)
        flags = FeatureFlags(
            enable_ai_tests=self.flag_ai.get(),
            enable_restricted_geo_tests=self.flag_geo.get(),
            enable_tls_tests=self.flag_tls.get(),
            enable_phish_tests=self.flag_phish.get(),
            enable_malware_tests=self.flag_malware.get(),
            enable_private_app_tests=self.flag_private.get(),
        )

        self.session = RunSession(
            persona=persona,
            run_mode=mode,
            intensity=intensity,
            flags=flags,
            private_apps=self.config.private_apps,
            config=self.config,
            status_callback=self._on_status_update,
        )

        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)

        self._worker_thread = threading.Thread(target=self._run_worker, daemon=True)
        self._worker_thread.start()

    def _run_worker(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self.session.run())
        except Exception as exc:
            print(f"[Worker] Unhandled: {exc}")
        finally:
            self._loop.close()
            self._loop = None

    def _on_stop(self) -> None:
        if self.session:
            self.session.request_stop()
        self.stop_btn.config(state=tk.DISABLED)

    def _on_reset(self) -> None:
        if self.session and self.session.sm.state == AppState.RUNNING:
            messagebox.showwarning("Warning", "Stop the session first.")
            return
        self.session = None
        for attr in ("s_actions_var", "s_blocked_var", "s_warnings_var",
                     "s_failures_var", "s_elapsed_var", "s_restarts_var"):
            getattr(self, attr).set("0")
        self.state_var.set("Idle")
        self.s_url_var.set("—")
        self.s_action_var.set("—")
        self.s_result_var.set("—")
        self.s_persona_var.set("—")
        self._update_btn_state()

    def _on_status_update(self, status: RuntimeStatus) -> None:
        """Called from worker thread — schedule GUI update."""
        self.root.after(0, self._apply_status, status)

    def _apply_status(self, s: RuntimeStatus) -> None:
        self.state_var.set(s.state.value)
        self.s_persona_var.set(s.persona_name)
        self.s_url_var.set(s.current_url[:80] if s.current_url else "—")
        self.s_action_var.set(s.current_action[:60] if s.current_action else "—")
        self.s_result_var.set(s.last_result or "—")
        self.s_actions_var.set(str(s.actions_completed))
        self.s_blocked_var.set(str(s.blocked_count))
        self.s_warnings_var.set(str(s.warning_count))
        self.s_failures_var.set(str(s.failure_count))
        self.s_elapsed_var.set(f"{s.elapsed_seconds:.0f}s")
        self.s_restarts_var.set(str(s.browser_restart_count))

        if s.state in (AppState.STOPPED, AppState.ERROR, AppState.IDLE):
            self.start_btn.config(state=tk.NORMAL)
            self.stop_btn.config(state=tk.DISABLED)

    # ── Private apps ──────────────────────────────────────────────────

    def _refresh_apps_tree(self) -> None:
        for item in self.apps_tree.get_children():
            self.apps_tree.delete(item)
        for app in self.config.private_apps:
            self.apps_tree.insert("", tk.END, values=(
                "✓" if app.enabled else "✗",
                app.name, app.fqdn, app.landing_path,
                app.expected_title_substring, app.expected_selector,
                ",".join(app.allowed_personas), app.weight,
            ))

    def _add_app(self) -> None:
        self.config.private_apps.append(PrivateApp(name="New App", fqdn="app.lab.local"))
        self._refresh_apps_tree()

    def _remove_app(self) -> None:
        sel = self.apps_tree.selection()
        if not sel:
            return
        idx = self.apps_tree.index(sel[0])
        if 0 <= idx < len(self.config.private_apps):
            self.config.private_apps.pop(idx)
            self._refresh_apps_tree()

    def _save_apps(self) -> None:
        self.config.save_private_apps()
        messagebox.showinfo("Saved", "Private apps saved.")

    # ── Helpers ────────────────────────────────────────────────────────

    def _refresh_persona_list(self) -> None:
        names = self.config.persona_names()
        display = [self.config.get_persona(n).display_name for n in names]
        self.persona_combo["values"] = names
        if names:
            self.persona_combo.current(0)

    def _update_btn_state(self) -> None:
        has_persona = bool(self.persona_var.get())
        running = self.session and self.session.sm.state == AppState.RUNNING
        self.start_btn.config(state=tk.NORMAL if (has_persona and not running) else tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL if running else tk.DISABLED)

    def _periodic_refresh(self) -> None:
        self._update_btn_state()
        self.root.after(1000, self._periodic_refresh)

    def _open_folder(self, folder: str) -> None:
        path = str(self.config.root / folder)
        if platform.system() == "Windows":
            os.startfile(path)
        elif platform.system() == "Darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])

    def _open_logs(self) -> None:
        self._open_folder("logs")

    def _open_screenshots(self) -> None:
        self._open_folder("screenshots")

    def run(self) -> None:
        self.root.mainloop()
