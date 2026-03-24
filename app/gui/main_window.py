"""Tkinter GUI v2.0 for the Persona Traffic Generator.

Changes from v1.0:
  - Tabbed notebook layout (Run / Private Apps / Site Import / Status)
  - Private App editor: full inline form with Name, FQDN, Port, Path,
    Title, Selector, multi-select persona checkboxes, Weight, Enabled toggle
  - Double-click a row to edit it in the form
  - CSV site import with persona picker and category dropdown
  - All private app fields are editable without touching JSON files
"""
from __future__ import annotations

import asyncio
import csv
import os
import platform
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk, messagebox, filedialog
from typing import Optional

from app.core.config_manager import ConfigManager, SITE_CATEGORIES
from app.core.run_session import RunSession
from app.models.models import (
    AppState, BehaviorIntensity, FeatureFlags,
    PrivateApp, RunMode, RuntimeStatus,
)


class TrafficGeneratorGUI:
    """Main application window — v2.0."""

    def __init__(self, config: ConfigManager):
        self.config = config
        self.session: Optional[RunSession] = None
        self._worker_thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._editing_app_idx: Optional[int] = None  # index being edited

        self.root = tk.Tk()
        self.root.title("Zscaler Lab — Persona Traffic Generator  v2.0")
        self.root.geometry("1200x820")
        self.root.minsize(1000, 700)

        style = ttk.Style()
        if "clam" in style.theme_names():
            style.theme_use("clam")

        self._build_ui()
        self._refresh_persona_list()
        self._update_btn_state()
        self.root.after(1000, self._periodic_refresh)

    # ══════════════════════════════════════════════════════════════════
    #  UI CONSTRUCTION
    # ══════════════════════════════════════════════════════════════════

    def _build_ui(self) -> None:
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

        # Tab 1: Run Controls
        tab_run = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(tab_run, text="  Run Controls  ")
        self._build_run_tab(tab_run)

        # Tab 2: Private Apps
        tab_apps = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(tab_apps, text="  Private Apps  ")
        self._build_apps_tab(tab_apps)

        # Tab 3: Site Import
        tab_import = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(tab_import, text="  Site Import  ")
        self._build_import_tab(tab_import)

        # Tab 4: Status
        tab_status = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(tab_status, text="  Status & Logs  ")
        self._build_status_tab(tab_status)

    # ──────────────────────────────────────────────────────────────────
    #  TAB 1: RUN CONTROLS
    # ──────────────────────────────────────────────────────────────────

    def _build_run_tab(self, parent: ttk.Frame) -> None:
        top = ttk.Frame(parent)
        top.pack(fill=tk.X)

        # Left: persona / mode / intensity
        ctrl = ttk.LabelFrame(top, text="Run Configuration", padding=10)
        ctrl.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 12))

        ttk.Label(ctrl, text="Persona:").grid(row=0, column=0, sticky=tk.W, pady=3)
        self.persona_var = tk.StringVar()
        self.persona_combo = ttk.Combobox(ctrl, textvariable=self.persona_var, state="readonly", width=20)
        self.persona_combo.grid(row=0, column=1, padx=4, pady=3)
        self.persona_combo.bind("<<ComboboxSelected>>", lambda e: self._update_btn_state())

        ttk.Label(ctrl, text="Run Mode:").grid(row=1, column=0, sticky=tk.W, pady=3)
        self.mode_var = tk.StringVar(value=RunMode.MIXED_REALISTIC.value)
        ttk.Combobox(ctrl, textvariable=self.mode_var, state="readonly", width=20,
                     values=[m.value for m in RunMode]).grid(row=1, column=1, padx=4, pady=3)

        ttk.Label(ctrl, text="Intensity:").grid(row=2, column=0, sticky=tk.W, pady=3)
        self.intensity_var = tk.StringVar(value=BehaviorIntensity.MEDIUM.value)
        ttk.Combobox(ctrl, textvariable=self.intensity_var, state="readonly", width=20,
                     values=[i.value for i in BehaviorIntensity]).grid(row=2, column=1, padx=4, pady=3)

        btn_f = ttk.Frame(ctrl)
        btn_f.grid(row=3, column=0, columnspan=2, pady=10)
        self.start_btn = ttk.Button(btn_f, text="▶  Start", command=self._on_start, width=12)
        self.start_btn.pack(side=tk.LEFT, padx=4)
        self.stop_btn = ttk.Button(btn_f, text="■  Stop", command=self._on_stop, state=tk.DISABLED, width=12)
        self.stop_btn.pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_f, text="Reset Stats", command=self._on_reset, width=12).pack(side=tk.LEFT, padx=4)

        # Right: feature flags
        flags = ttk.LabelFrame(top, text="Feature Toggles", padding=10)
        flags.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 12))

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
            ttk.Checkbutton(flags, text=text, variable=var).grid(row=i, column=0, sticky=tk.W, pady=2)

        # Quick status strip at bottom of run tab
        qs = ttk.LabelFrame(parent, text="Quick Status", padding=6)
        qs.pack(fill=tk.X, pady=(12, 0))
        self.quick_status_var = tk.StringVar(value="Idle — select a persona and click Start")
        ttk.Label(qs, textvariable=self.quick_status_var, font=("", 10)).pack(anchor=tk.W)

    # ──────────────────────────────────────────────────────────────────
    #  TAB 2: PRIVATE APPS
    # ──────────────────────────────────────────────────────────────────

    def _build_apps_tab(self, parent: ttk.Frame) -> None:
        # ── Top: Treeview ─────────────────────────────────────────────
        tree_frame = ttk.Frame(parent)
        tree_frame.pack(fill=tk.BOTH, expand=True)

        cols = ("enabled", "name", "fqdn", "port", "path", "title", "selector", "personas", "weight")
        self.apps_tree = ttk.Treeview(tree_frame, columns=cols, show="headings", height=8)

        widths = {"enabled": 50, "name": 120, "fqdn": 150, "port": 50, "path": 60,
                  "title": 90, "selector": 70, "personas": 140, "weight": 50}
        for c in cols:
            self.apps_tree.heading(c, text=c.replace("_", " ").title())
            self.apps_tree.column(c, width=widths.get(c, 80), minwidth=40)

        sb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.apps_tree.yview)
        self.apps_tree.configure(yscrollcommand=sb.set)
        self.apps_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.LEFT, fill=tk.Y)

        self.apps_tree.bind("<Double-1>", self._on_app_double_click)

        # ── Middle: action buttons ────────────────────────────────────
        btn_bar = ttk.Frame(parent)
        btn_bar.pack(fill=tk.X, pady=6)
        ttk.Button(btn_bar, text="New App", command=self._new_app_form).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_bar, text="Delete Selected", command=self._delete_selected_app).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_bar, text="Save All to Disk", command=self._save_apps_disk).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_bar, text="Reload from Disk", command=self._reload_apps_disk).pack(side=tk.LEFT, padx=4)

        # ── Bottom: inline edit form ──────────────────────────────────
        form_lf = ttk.LabelFrame(parent, text="App Editor  (double-click a row above to edit, or click New App)", padding=10)
        form_lf.pack(fill=tk.X, pady=(0, 4))
        self._build_app_form(form_lf)

        self._refresh_apps_tree()

    def _build_app_form(self, parent: ttk.Frame) -> None:
        """Build the inline editable form for a single PrivateApp."""
        # Row 0: enabled, name, fqdn, port
        r = 0
        ttk.Label(parent, text="Enabled:").grid(row=r, column=0, sticky=tk.W, padx=2)
        self.f_enabled = tk.BooleanVar(value=True)
        ttk.Checkbutton(parent, variable=self.f_enabled).grid(row=r, column=1, sticky=tk.W)

        ttk.Label(parent, text="Name:").grid(row=r, column=2, sticky=tk.W, padx=(12, 2))
        self.f_name = tk.StringVar()
        ttk.Entry(parent, textvariable=self.f_name, width=20).grid(row=r, column=3, sticky=tk.W)

        ttk.Label(parent, text="FQDN:").grid(row=r, column=4, sticky=tk.W, padx=(12, 2))
        self.f_fqdn = tk.StringVar()
        ttk.Entry(parent, textvariable=self.f_fqdn, width=24).grid(row=r, column=5, sticky=tk.W)

        ttk.Label(parent, text="Port:").grid(row=r, column=6, sticky=tk.W, padx=(12, 2))
        self.f_port = tk.StringVar(value="443")
        ttk.Entry(parent, textvariable=self.f_port, width=6).grid(row=r, column=7, sticky=tk.W)

        # Row 1: path, expected title, expected selector, weight
        r = 1
        ttk.Label(parent, text="Path:").grid(row=r, column=0, sticky=tk.W, padx=2, pady=(6, 0))
        self.f_path = tk.StringVar(value="/")
        ttk.Entry(parent, textvariable=self.f_path, width=14).grid(row=r, column=1, sticky=tk.W, pady=(6, 0))

        ttk.Label(parent, text="Expected Title:").grid(row=r, column=2, sticky=tk.W, padx=(12, 2), pady=(6, 0))
        self.f_title = tk.StringVar()
        ttk.Entry(parent, textvariable=self.f_title, width=20).grid(row=r, column=3, sticky=tk.W, pady=(6, 0))

        ttk.Label(parent, text="Selector:").grid(row=r, column=4, sticky=tk.W, padx=(12, 2), pady=(6, 0))
        self.f_selector = tk.StringVar(value="body")
        ttk.Entry(parent, textvariable=self.f_selector, width=14).grid(row=r, column=5, sticky=tk.W, pady=(6, 0))

        ttk.Label(parent, text="Weight:").grid(row=r, column=6, sticky=tk.W, padx=(12, 2), pady=(6, 0))
        self.f_weight = tk.StringVar(value="10")
        ttk.Entry(parent, textvariable=self.f_weight, width=6).grid(row=r, column=7, sticky=tk.W, pady=(6, 0))

        # Row 2: Persona checkboxes (one per loaded persona)
        r = 2
        ttk.Label(parent, text="Allowed Personas:").grid(row=r, column=0, columnspan=2, sticky=tk.W, padx=2, pady=(8, 0))
        persona_frame = ttk.Frame(parent)
        persona_frame.grid(row=r, column=2, columnspan=6, sticky=tk.W, pady=(8, 0))

        self.f_persona_vars: dict[str, tk.BooleanVar] = {}
        for i, name in enumerate(self.config.persona_names()):
            var = tk.BooleanVar(value=False)
            self.f_persona_vars[name] = var
            display = self.config.get_persona(name)
            label = display.display_name if display else name
            ttk.Checkbutton(persona_frame, text=label, variable=var).pack(side=tk.LEFT, padx=6)

        # Row 3: Save / Cancel buttons
        r = 3
        btn_f = ttk.Frame(parent)
        btn_f.grid(row=r, column=0, columnspan=8, pady=(10, 0))
        self.form_save_btn = ttk.Button(btn_f, text="Save App", command=self._save_app_from_form, width=16)
        self.form_save_btn.pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_f, text="Clear Form", command=self._clear_app_form, width=12).pack(side=tk.LEFT, padx=4)

        self.form_status_var = tk.StringVar(value="")
        ttk.Label(btn_f, textvariable=self.form_status_var, foreground="green").pack(side=tk.LEFT, padx=12)

    # ──────────────────────────────────────────────────────────────────
    #  TAB 3: SITE IMPORT
    # ──────────────────────────────────────────────────────────────────

    def _build_import_tab(self, parent: ttk.Frame) -> None:
        info = ttk.Label(parent, text=(
            "Import websites from a CSV file into a persona's site list.\n"
            "The CSV needs a header row.  For most categories use a column named 'url'.\n"
            "For search_queries use 'query'.  For restricted_geo_sites also include 'country_code' and 'label'.\n"
            "Duplicates are automatically skipped."
        ), justify=tk.LEFT, wraplength=800)
        info.pack(anchor=tk.W, pady=(0, 10))

        f = ttk.LabelFrame(parent, text="Import Settings", padding=10)
        f.pack(fill=tk.X)

        # Row 0: persona + category
        ttk.Label(f, text="Target Persona:").grid(row=0, column=0, sticky=tk.W, padx=4, pady=4)
        self.import_persona_var = tk.StringVar()
        self.import_persona_combo = ttk.Combobox(f, textvariable=self.import_persona_var,
                                                  state="readonly", width=20)
        self.import_persona_combo.grid(row=0, column=1, sticky=tk.W, padx=4, pady=4)

        ttk.Label(f, text="Site Category:").grid(row=0, column=2, sticky=tk.W, padx=(20, 4), pady=4)
        self.import_cat_var = tk.StringVar()
        cat_display = [c.replace("_", " ").title() for c in SITE_CATEGORIES]
        self.import_cat_combo = ttk.Combobox(f, textvariable=self.import_cat_var,
                                              state="readonly", width=22, values=cat_display)
        self.import_cat_combo.grid(row=0, column=3, sticky=tk.W, padx=4, pady=4)
        if cat_display:
            self.import_cat_combo.current(0)

        # Row 1: file path + browse
        ttk.Label(f, text="CSV File:").grid(row=1, column=0, sticky=tk.W, padx=4, pady=4)
        self.import_file_var = tk.StringVar()
        ttk.Entry(f, textvariable=self.import_file_var, width=50).grid(row=1, column=1, columnspan=2,
                                                                        sticky=tk.W, padx=4, pady=4)
        ttk.Button(f, text="Browse...", command=self._browse_csv).grid(row=1, column=3, sticky=tk.W, padx=4, pady=4)

        # Row 2: import button
        btn_f = ttk.Frame(f)
        btn_f.grid(row=2, column=0, columnspan=4, pady=8)
        ttk.Button(btn_f, text="Import CSV", command=self._do_csv_import, width=18).pack(side=tk.LEFT, padx=4)
        self.import_status_var = tk.StringVar(value="")
        ttk.Label(btn_f, textvariable=self.import_status_var).pack(side=tk.LEFT, padx=12)

        # Preview area
        prev_lf = ttk.LabelFrame(parent, text="CSV Preview (first 20 rows)", padding=6)
        prev_lf.pack(fill=tk.BOTH, expand=True, pady=(10, 0))

        self.preview_tree = ttk.Treeview(prev_lf, show="headings", height=10)
        prev_sb = ttk.Scrollbar(prev_lf, orient=tk.VERTICAL, command=self.preview_tree.yview)
        self.preview_tree.configure(yscrollcommand=prev_sb.set)
        self.preview_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        prev_sb.pack(side=tk.LEFT, fill=tk.Y)

    # ──────────────────────────────────────────────────────────────────
    #  TAB 4: STATUS & LOGS
    # ──────────────────────────────────────────────────────────────────

    def _build_status_tab(self, parent: ttk.Frame) -> None:
        # Labels
        lf = ttk.LabelFrame(parent, text="Runtime Metrics", padding=8)
        lf.pack(fill=tk.X)

        labels = [
            ("State:", "state_var"),
            ("Persona:", "s_persona_var"),
            ("URL:", "s_url_var"),
            ("Action:", "s_action_var"),
            ("Last Result:", "s_result_var"),
        ]
        for i, (text, attr) in enumerate(labels):
            ttk.Label(lf, text=text, font=("", 9, "bold")).grid(row=i, column=0, sticky=tk.W, padx=4, pady=2)
            var = tk.StringVar(value="---")
            setattr(self, attr, var)
            ttk.Label(lf, textvariable=var, width=80, anchor=tk.W).grid(row=i, column=1, sticky=tk.W, padx=4)

        # Counters
        cf = ttk.LabelFrame(parent, text="Counters", padding=8)
        cf.pack(fill=tk.X, pady=(8, 0))

        counters = [
            ("Actions:", "s_actions_var"),
            ("Blocked:", "s_blocked_var"),
            ("Warnings:", "s_warnings_var"),
            ("Failures:", "s_failures_var"),
            ("Elapsed:", "s_elapsed_var"),
            ("Browser Restarts:", "s_restarts_var"),
        ]
        for i, (text, attr) in enumerate(counters):
            ttk.Label(cf, text=text, font=("", 9, "bold")).grid(row=0, column=i * 2, padx=6)
            var = tk.StringVar(value="0")
            setattr(self, attr, var)
            ttk.Label(cf, textvariable=var, width=8).grid(row=0, column=i * 2 + 1)

        # Buttons
        bf = ttk.Frame(parent)
        bf.pack(fill=tk.X, pady=(10, 0))
        ttk.Button(bf, text="Open Logs Folder", command=self._open_logs).pack(side=tk.LEFT, padx=4)
        ttk.Button(bf, text="Open Screenshots Folder", command=self._open_screenshots).pack(side=tk.LEFT, padx=4)

    # ══════════════════════════════════════════════════════════════════
    #  PRIVATE APP EDITOR LOGIC
    # ══════════════════════════════════════════════════════════════════

    def _refresh_apps_tree(self) -> None:
        for item in self.apps_tree.get_children():
            self.apps_tree.delete(item)
        for app in self.config.private_apps:
            self.apps_tree.insert("", tk.END, values=(
                "Y" if app.enabled else "N",
                app.name, app.fqdn, app.port, app.landing_path,
                app.expected_title_substring, app.expected_selector,
                ", ".join(app.allowed_personas), app.weight,
            ))

    def _on_app_double_click(self, event) -> None:
        sel = self.apps_tree.selection()
        if not sel:
            return
        idx = self.apps_tree.index(sel[0])
        if 0 <= idx < len(self.config.private_apps):
            self._load_app_into_form(idx)

    def _load_app_into_form(self, idx: int) -> None:
        app = self.config.private_apps[idx]
        self._editing_app_idx = idx
        self.f_enabled.set(app.enabled)
        self.f_name.set(app.name)
        self.f_fqdn.set(app.fqdn)
        self.f_port.set(str(app.port))
        self.f_path.set(app.landing_path)
        self.f_title.set(app.expected_title_substring)
        self.f_selector.set(app.expected_selector)
        self.f_weight.set(str(app.weight))
        for pname, var in self.f_persona_vars.items():
            var.set(pname in app.allowed_personas)
        self.form_status_var.set(f"Editing: {app.name} (index {idx})")
        self.form_save_btn.config(text="Update App")

    def _clear_app_form(self) -> None:
        self._editing_app_idx = None
        self.f_enabled.set(True)
        self.f_name.set("")
        self.f_fqdn.set("")
        self.f_port.set("443")
        self.f_path.set("/")
        self.f_title.set("")
        self.f_selector.set("body")
        self.f_weight.set("10")
        for var in self.f_persona_vars.values():
            var.set(False)
        self.form_status_var.set("")
        self.form_save_btn.config(text="Save App")

    def _new_app_form(self) -> None:
        self._clear_app_form()
        self.f_name.set("New App")
        self.f_fqdn.set("app.lab.local")
        self.form_status_var.set("Fill in the fields and click Save App")

    def _save_app_from_form(self) -> None:
        # Validate
        name = self.f_name.get().strip()
        fqdn = self.f_fqdn.get().strip()
        if not name:
            messagebox.showerror("Validation", "Name is required.")
            return
        if not fqdn:
            messagebox.showerror("Validation", "FQDN is required.")
            return
        try:
            port = int(self.f_port.get().strip())
            if port < 1 or port > 65535:
                raise ValueError
        except ValueError:
            messagebox.showerror("Validation", "Port must be a number between 1 and 65535.")
            return
        try:
            weight = int(self.f_weight.get().strip())
        except ValueError:
            weight = 10

        allowed = [pname for pname, var in self.f_persona_vars.items() if var.get()]

        app = PrivateApp(
            enabled=self.f_enabled.get(),
            name=name,
            fqdn=fqdn,
            port=port,
            landing_path=self.f_path.get().strip() or "/",
            expected_title_substring=self.f_title.get().strip(),
            expected_selector=self.f_selector.get().strip() or "body",
            allowed_personas=allowed,
            weight=weight,
        )

        if self._editing_app_idx is not None and 0 <= self._editing_app_idx < len(self.config.private_apps):
            self.config.private_apps[self._editing_app_idx] = app
            self.form_status_var.set(f"Updated: {name}")
        else:
            self.config.private_apps.append(app)
            self.form_status_var.set(f"Added: {name}")

        self._refresh_apps_tree()
        self._editing_app_idx = None
        self.form_save_btn.config(text="Save App")

    def _delete_selected_app(self) -> None:
        sel = self.apps_tree.selection()
        if not sel:
            return
        idx = self.apps_tree.index(sel[0])
        if 0 <= idx < len(self.config.private_apps):
            removed = self.config.private_apps.pop(idx)
            self._refresh_apps_tree()
            self._clear_app_form()
            self.form_status_var.set(f"Deleted: {removed.name}")

    def _save_apps_disk(self) -> None:
        self.config.save_private_apps()
        messagebox.showinfo("Saved", f"Saved {len(self.config.private_apps)} private apps to disk.")

    def _reload_apps_disk(self) -> None:
        self.config._load_private_apps()
        self._refresh_apps_tree()
        self._clear_app_form()
        messagebox.showinfo("Reloaded", f"Loaded {len(self.config.private_apps)} private apps from disk.")

    # ══════════════════════════════════════════════════════════════════
    #  CSV IMPORT LOGIC
    # ══════════════════════════════════════════════════════════════════

    def _browse_csv(self) -> None:
        path = filedialog.askopenfilename(
            title="Select CSV file",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if path:
            self.import_file_var.set(path)
            self._preview_csv(path)

    def _preview_csv(self, path: str) -> None:
        """Load the first 20 rows into the preview treeview."""
        # Clear
        self.preview_tree.delete(*self.preview_tree.get_children())
        for c in self.preview_tree["columns"]:
            self.preview_tree.heading(c, text="")

        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                if not reader.fieldnames:
                    return
                cols = [n.strip() for n in reader.fieldnames]
                self.preview_tree["columns"] = cols
                for c in cols:
                    self.preview_tree.heading(c, text=c)
                    self.preview_tree.column(c, width=max(80, len(c) * 10), minwidth=60)
                for i, row in enumerate(reader):
                    if i >= 20:
                        break
                    vals = [row.get(c, "").strip() for c in reader.fieldnames]
                    self.preview_tree.insert("", tk.END, values=vals)
        except Exception as exc:
            self.import_status_var.set(f"Preview error: {exc}")

    def _do_csv_import(self) -> None:
        csv_path = self.import_file_var.get().strip()
        if not csv_path or not Path(csv_path).is_file():
            messagebox.showerror("Error", "Select a valid CSV file first.")
            return

        persona_name = self.import_persona_var.get()
        if not persona_name:
            messagebox.showerror("Error", "Select a target persona.")
            return

        cat_display = self.import_cat_var.get()
        # Map display name back to key
        cat_key = ""
        for c in SITE_CATEGORIES:
            if c.replace("_", " ").title() == cat_display:
                cat_key = c
                break
        if not cat_key:
            messagebox.showerror("Error", "Select a valid site category.")
            return

        added, skipped, errors = self.config.import_sites_csv(csv_path, persona_name, cat_key)

        msg = f"Added {added} sites, skipped {skipped} duplicates."
        if errors:
            msg += f"\n\nWarnings ({len(errors)}):\n" + "\n".join(errors[:10])
        self.import_status_var.set(f"Done: +{added}, skipped {skipped}")
        messagebox.showinfo("Import Complete", msg)

    # ══════════════════════════════════════════════════════════════════
    #  RUN / STOP / RESET
    # ══════════════════════════════════════════════════════════════════

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
        self.quick_status_var.set(f"Running -- {persona.display_name} / {mode.value} / {intensity.value}")

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
        self.quick_status_var.set("Stopping...")

    def _on_reset(self) -> None:
        if self.session and self.session.sm.state == AppState.RUNNING:
            messagebox.showwarning("Warning", "Stop the session first.")
            return
        self.session = None
        for attr in ("s_actions_var", "s_blocked_var", "s_warnings_var",
                     "s_failures_var", "s_elapsed_var", "s_restarts_var"):
            getattr(self, attr).set("0")
        self.state_var.set("Idle")
        self.s_url_var.set("---")
        self.s_action_var.set("---")
        self.s_result_var.set("---")
        self.s_persona_var.set("---")
        self.quick_status_var.set("Idle -- select a persona and click Start")
        self._update_btn_state()

    # ══════════════════════════════════════════════════════════════════
    #  STATUS CALLBACKS
    # ══════════════════════════════════════════════════════════════════

    def _on_status_update(self, status: RuntimeStatus) -> None:
        self.root.after(0, self._apply_status, status)

    def _apply_status(self, s: RuntimeStatus) -> None:
        self.state_var.set(s.state.value)
        self.s_persona_var.set(s.persona_name)
        self.s_url_var.set(s.current_url[:100] if s.current_url else "---")
        self.s_action_var.set(s.current_action[:80] if s.current_action else "---")
        self.s_result_var.set(s.last_result or "---")
        self.s_actions_var.set(str(s.actions_completed))
        self.s_blocked_var.set(str(s.blocked_count))
        self.s_warnings_var.set(str(s.warning_count))
        self.s_failures_var.set(str(s.failure_count))
        self.s_elapsed_var.set(f"{s.elapsed_seconds:.0f}s")
        self.s_restarts_var.set(str(s.browser_restart_count))

        self.quick_status_var.set(
            f"{s.state.value} -- {s.persona_name} | "
            f"Actions: {s.actions_completed}  Blocked: {s.blocked_count}  "
            f"Elapsed: {s.elapsed_seconds:.0f}s"
        )

        if s.state in (AppState.STOPPED, AppState.ERROR, AppState.IDLE):
            self.start_btn.config(state=tk.NORMAL)
            self.stop_btn.config(state=tk.DISABLED)

    # ══════════════════════════════════════════════════════════════════
    #  HELPERS
    # ══════════════════════════════════════════════════════════════════

    def _refresh_persona_list(self) -> None:
        names = self.config.persona_names()
        self.persona_combo["values"] = names
        self.import_persona_combo["values"] = names
        if names:
            self.persona_combo.current(0)
            self.import_persona_combo.current(0)

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
