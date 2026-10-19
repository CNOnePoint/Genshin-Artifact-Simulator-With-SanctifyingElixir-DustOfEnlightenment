# -*- coding: utf-8 -*-
"""原神圣遗物强化模拟器 —— 图形界面。"""
from __future__ import annotations

import copy
import json
import os
import random
import re
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox, simpledialog, ttk
from tkinter.scrolledtext import ScrolledText

from . import engine, scoring
from .config import (CONFIG_PATH, ROOT_DIR, DEFAULT_SCORE_TEMPLATE, DEFAULT_STAT_ROWS, ROW_KEYS,
                     StatTable, default_config, default_pieces, format_value, load_config,
                     normalize, save_config, validate)
from .model import VEC_SIZE, AppState, Artifact, Inventory, fmt_num

DATA_PATH = os.path.join(ROOT_DIR, "savegame.json")
ANY_DOMAIN = "任意副本（全部套装随机）"


# ==========================================================================
class ScrollFrame(ttk.Frame):
    """可纵向滚动的内容容器。"""

    def __init__(self, master, **kw):
        super().__init__(master, **kw)
        self.canvas = tk.Canvas(self, highlightthickness=0)
        self.vsb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vsb.set)
        self.vsb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.body = ttk.Frame(self.canvas)
        self._win = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.body.bind("<Configure>", self._on_body)
        self.canvas.bind("<Configure>", self._on_canvas)
        self.canvas.bind_all("<MouseWheel>", self._on_wheel)

    def _on_body(self, _e=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas(self, e):
        self.canvas.itemconfigure(self._win, width=e.width)

    def _on_wheel(self, e):
        try:
            if self.canvas.winfo_exists() and self.winfo_ismapped():
                self.canvas.yview_scroll(int(-e.delta / 120), "units")
        except tk.TclError:
            pass


# ==========================================================================
class App(tk.Tk):

    def __init__(self):
        super().__init__()
        self._setup_fonts()
        self.title("原神圣遗物强化模拟器")
        self._fit_to_screen(1280, 880)
        self.minsize(960, 620)

        self.cfg = load_config()
        self.table = StatTable(self.cfg)
        self.rng = random.Random()
        self.state = AppState()
        self.inv = Inventory(self.cfg, self.table)
        self._sel_items: list[Artifact] = []

        self._build_menu()
        self._build_top()
        self._build_notebook()
        self._build_statusbar()
        self._load_game(silent=True)
        self.refresh_all()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------ 外观
    def _fit_to_screen(self, want_w: int, want_h: int):
        """按屏幕尺寸自适应窗口大小并居中。"""
        self.update_idletasks()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        w = max(960, min(want_w, sw - 80))
        h = max(620, min(want_h, sh - 100))
        x = max(0, (sw - w) // 2)
        y = max(0, (sh - h) // 3)
        self.geometry("%dx%d+%d+%d" % (w, h, x, y))

    def _setup_fonts(self):
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
            try:
                f = tkfont.nametofont(name)
                f.configure(family="Microsoft YaHei UI", size=10)
            except Exception:                              # noqa: BLE001
                pass
        try:
            tkfont.nametofont("TkFixedFont").configure(family="Consolas", size=10)
        except Exception:                                  # noqa: BLE001
            pass

    def _build_menu(self):
        bar = tk.Menu(self)
        m_file = tk.Menu(bar, tearoff=0)
        m_file.add_command(label="保存进度", command=self._save_game)
        m_file.add_command(label="读取进度", command=lambda: self._load_game())
        m_file.add_separator()
        m_file.add_command(label="导出配置(config.json)", command=self._export_config)
        m_file.add_command(label="导入配置(config.json)", command=self._import_config)
        m_file.add_separator()
        m_file.add_command(label="恢复默认配置", command=self._reset_config)
        m_file.add_separator()
        m_file.add_command(label="退出", command=self._on_close)
        bar.add_cascade(label="文件", menu=m_file)

        m_help = tk.Menu(bar, tearoff=0)
        m_help.add_command(label="规则说明", command=lambda: self.nb.select(self.tab_help))
        m_help.add_command(label="关于", command=self._about)
        bar.add_cascade(label="帮助", menu=m_help)
        self.config(menu=bar)

    def _build_top(self):
        top = ttk.Frame(self, padding=(8, 6, 8, 2))
        top.pack(fill="x")
        ttk.Label(top, text="当前圣遗物：").pack(side="left")
        self.sel_var = tk.StringVar()
        self.sel_combo = ttk.Combobox(top, textvariable=self.sel_var, state="readonly", width=78)
        self.sel_combo.pack(side="left", padx=4)
        self.sel_combo.bind("<<ComboboxSelected>>", lambda e: self.on_select())
        ttk.Button(top, text="查看详情", command=self._show_detail_dialog).pack(side="left", padx=4)
        ttk.Button(top, text="刷新", command=self.refresh_all).pack(side="left", padx=4)

    def _build_statusbar(self):
        bar = ttk.Frame(self, padding=(8, 2, 8, 6))
        bar.pack(fill="x", side="bottom")
        self.status_var = tk.StringVar()
        ttk.Label(bar, textvariable=self.status_var, anchor="w").pack(fill="x")
        sep = ttk.Separator(self, orient="horizontal")
        sep.pack(fill="x", side="bottom")

    def _build_notebook(self):
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=8, pady=4)
        self.tab_get = ttk.Frame(self.nb, padding=8)
        self.tab_enh = ttk.Frame(self.nb, padding=8)
        self.tab_list = ttk.Frame(self.nb, padding=8)
        self.tab_elixir = ttk.Frame(self.nb, padding=8)
        self.tab_dust = ttk.Frame(self.nb, padding=8)
        self.tab_score = ttk.Frame(self.nb, padding=8)
        self.tab_custom = ttk.Frame(self.nb, padding=8)
        self.tab_help = ttk.Frame(self.nb, padding=8)
        for f, t in ((self.tab_get, "获取圣遗物"), (self.tab_enh, "强化圣遗物"),
                     (self.tab_list, "圣遗物列表"), (self.tab_elixir, "祝圣之霜"),
                     (self.tab_dust, "启圣之尘"), (self.tab_score, "评分"),
                     (self.tab_custom, "自定义"), (self.tab_help, "说明")):
            self.nb.add(f, text=t)
        self._build_get()
        self._build_enhance()
        self._build_list()
        self._build_elixir()
        self._build_dust()
        self._build_score()
        self._build_custom()
        self._build_help()

    # ==================================================================
    # 获取圣遗物
    # ==================================================================
    def _build_get(self):
        f = self.tab_get
        box = ttk.LabelFrame(f, text="获取设置", padding=8)
        box.pack(fill="x")

        ttk.Label(box, text="副本：").grid(row=0, column=0, sticky="w", pady=2)
        self.get_domain = tk.StringVar()
        self.get_domain_combo = ttk.Combobox(box, textvariable=self.get_domain, state="readonly", width=34)
        self.get_domain_combo.grid(row=0, column=1, sticky="w", padx=4)
        self.get_domain_combo.bind("<<ComboboxSelected>>", lambda e: self._update_domain_info())
        self.domain_info = ttk.Label(box, text="", foreground="#315")
        self.domain_info.grid(row=0, column=2, columnspan=4, sticky="w", padx=8)

        ttk.Label(box, text="部位：").grid(row=1, column=0, sticky="w", pady=2)
        self.get_slot = tk.StringVar(value="随机（等概率五选一）")
        ttk.Combobox(box, textvariable=self.get_slot, state="readonly", width=24,
                     values=["随机（等概率五选一）"] + list(self.cfg["slots"])).grid(
            row=1, column=1, sticky="w", padx=4)
        ttk.Label(box, text="数量：").grid(row=1, column=2, sticky="e", padx=(12, 2))
        self.get_count = tk.IntVar(value=1)
        ttk.Spinbox(box, from_=1, to=200, textvariable=self.get_count, width=6).grid(
            row=1, column=3, sticky="w")
        self.get_auto_max = tk.BooleanVar(value=False)
        ttk.Checkbutton(box, text="获取后立即强化至满级", variable=self.get_auto_max).grid(
            row=1, column=4, columnspan=2, sticky="w", padx=12)

        # 获取结果先只显示，点「加入圣遗物列表」才真正进存档。
        self._last_batch: list[Artifact] = []

        btns = ttk.Frame(box)
        btns.grid(row=2, column=0, columnspan=6, sticky="w", pady=(8, 0))
        ttk.Button(btns, text="获取", command=self.do_get).pack(side="left")
        ttk.Button(btns, text="获取 10 次", command=lambda: self.do_get(10)).pack(side="left", padx=6)
        self.get_keep_btn = ttk.Button(btns, text="加入圣遗物列表",
                                       command=self.do_keep_batch, state="disabled")
        self.get_keep_btn.pack(side="left", padx=6)
        ttk.Button(btns, text="清空输出", command=lambda: self._set_text(self.get_out, "")).pack(
            side="left", padx=6)
        self.get_keep_hint = ttk.Label(
            box, text="获取到的圣遗物先只显示，点「加入圣遗物列表」后才保存。",
            foreground="#555")
        self.get_keep_hint.grid(row=3, column=0, columnspan=6, sticky="w", pady=(6, 0))

        # 获取计数：每获取一件就 +1（丢弃的也照算），清空存档时归零。
        self.get_total_label = ttk.Label(box, text="累计获取：0 件", foreground="#0b5fd0")
        self.get_total_label.grid(row=4, column=0, columnspan=6, sticky="w", pady=(4, 0))

        ttk.Label(f, text="获取结果").pack(anchor="w", pady=(10, 2))
        self.get_out = ScrolledText(f, height=24, wrap="word", font=("Consolas", 10))
        self.get_out.pack(fill="both", expand=True)
        self.get_out.configure(state="disabled")

    def _update_domain_info(self):
        name = self.get_domain.get()
        doms = self.cfg.get("domains") or {}
        if name in doms and doms[name]:
            self.domain_info.configure(text="掉落套装：" + "、".join(doms[name]))
        else:
            self.domain_info.configure(text="从全部 %d 个套装中随机。" % len(self.cfg.get("sets", [])))

    def do_get(self, count: int | None = None):
        name = self.get_domain.get()
        doms = self.cfg.get("domains") or {}
        pool = doms.get(name)
        slot_txt = self.get_slot.get()
        slot = None
        if slot_txt in self.cfg["slots"]:
            slot = self.cfg["slots"].index(slot_txt)
        n = int(count if count is not None else self.get_count.get())
        n = max(1, min(500, n))

        entries = []
        made = []
        for _ in range(n):
            set_id = None
            if pool:
                sname = self.rng.choice(pool)
                try:
                    set_id = self.cfg["sets"].index(sname)
                except ValueError:
                    set_id = None
            try:
                art = engine.create_random_artifact(self.cfg, self.table, self.rng,
                                                    slot=slot, set_id=set_id)
            except ValueError as exc:
                messagebox.showerror("无法生成圣遗物", "%s\n\n请到「自定义 → 数值表」检查权重列。" % exc)
                break
            if self.get_auto_max.get():
                engine.advance(art, art.max_level, self.cfg, self.table, self.rng)
            made.append(art)            # 先只放进待定批次，等用户点按钮才入列
        if made:
            self.state.get_count += len(made)       # 获取计数：丢弃的也算获取过
        self._last_batch = made
        self._render_batch()
        self._refresh_keep_btn()

    def _batch_entries(self, made):
        """「获取结果」里这一批待定圣遗物（还没加入列表）的富文本。"""
        entries = []
        for art in made:
            entries.append(("dim", "—" * 30 + "\n"))
            entries += self._artifact_entries(art)
            entries.append(("dim", "向量：%s\n" % art.vector_text()))
        if made:
            entries.append(("score", "—" * 30 + "\n"))
            entries.append(("score", "以上 %d 件尚未加入列表。点「加入圣遗物列表」保存，"
                                     "或直接再获取一批把它们丢弃。\n" % len(made)))
        return entries

    def _render_batch(self):
        """按当前配置重画「获取结果」（显示开关变了要重画）。"""
        made = list(getattr(self, "_last_batch", []))
        self._set_rich(self.get_out, self._batch_entries(made))
        self._refresh_get_count()
        self.refresh_all()
        if made:
            self.set_status("已获取 %d 件圣遗物（尚未加入列表）。" % len(made))
        else:
            self.set_status("没有获取到圣遗物。")

    def _refresh_get_count(self):
        """把「累计获取」标签刷成 state.get_count（含丢弃的）。"""
        lbl = getattr(self, "get_total_label", None)
        if lbl is None:
            return
        n = int(getattr(self.state, "get_count", 0))
        lbl.configure(text="累计获取：%d 件（含未加入列表的；清空存档时归零）" % n)

    def _refresh_keep_btn(self):
        btn = getattr(self, "get_keep_btn", None)
        if btn is None:
            return
        if self._last_batch:
            btn.configure(state="normal")
            self.get_keep_hint.configure(
                text="待定 %d 件：点「加入圣遗物列表」保存，再次获取会丢弃它们。"
                     % len(self._last_batch), foreground="#a60")
        else:
            btn.configure(state="disabled")
            self.get_keep_hint.configure(
                text="获取到的圣遗物先只显示，点「加入圣遗物列表」后才保存。",
                foreground="#555")

    def do_keep_batch(self):
        batch = list(getattr(self, "_last_batch", []))
        if not batch:
            return
        for art in batch:
            self.inv.add(art)
        self._last_batch = []
        self._refresh_keep_btn()
        self.refresh_all()
        last = batch[-1]
        self.select_artifact(last)
        self._append_text(self.get_out,
                          "\n已把这 %d 件圣遗物加入圣遗物列表（编号 %d~%d）。\n"
                          % (len(batch), batch[0].uid, last.uid))
        # 强化页的日志里打一条分界线，标出这是一件新圣遗物
        if len(batch) == 1:
            head = "【加入列表】#%d %s·%s %s +%s" % (
                last.uid, last.set_name, last.slot_name, last.main_name, _n(last.level))
        else:
            head = "【加入列表】#%d~#%d 共 %d 件，当前选中 #%d %s·%s %s +%s" % (
                batch[0].uid, last.uid, len(batch), last.uid,
                last.set_name, last.slot_name, last.main_name, _n(last.level))
        self._append_rich(self.enh_log, [("dim", "─" * 48 + "\n"), ("dim", head + "\n")])
        self.set_status("已加入 %d 件圣遗物到列表。" % len(batch))

    # ==================================================================
    # 强化
    # ==================================================================
    def _build_enhance(self):
        f = self.tab_enh
        box = ttk.LabelFrame(f, text="强化操作", padding=8)
        box.pack(fill="x")
        ttk.Button(box, text="提升 1 级", command=lambda: self.do_enhance(1)).pack(side="left")
        ttk.Button(box, text="提升 4 级", command=lambda: self.do_enhance(4)).pack(side="left", padx=6)
        ttk.Button(box, text="提升至满级", command=self.do_enhance_max).pack(side="left", padx=6)
        self.enh_score_label = ttk.Label(box, text="评分：—（未选中圣遗物）", foreground="#a35c00")
        self.enh_score_label.pack(side="right", padx=8)
        ttk.Label(box, text="每 %d 级进行一次副词条判定（4/8/12/16/20）。" %
                  self.cfg.get("enhance_interval", 4), foreground="#555").pack(side="left", padx=14)

        pane = ttk.Panedwindow(f, orient="horizontal")
        pane.pack(fill="both", expand=True, pady=(10, 0))
        left = ttk.Labelframe(pane, text="当前属性", padding=6)
        right = ttk.Labelframe(pane, text="强化日志", padding=6)
        pane.add(left, weight=1)
        pane.add(right, weight=1)
        self.enh_view = ScrolledText(left, wrap="word", width=52, font=("Microsoft YaHei UI", 10))
        self.enh_view.pack(fill="both", expand=True)
        self.enh_view.configure(state="disabled")
        self.enh_log = ScrolledText(right, wrap="word", width=52, font=("Microsoft YaHei UI", 10))
        self.enh_log.pack(fill="both", expand=True)
        self.enh_log.configure(state="disabled")

    def do_enhance(self, levels: int):
        art = self.current_artifact()
        if art is None:
            messagebox.showinfo("提示", "请先在上方选择一件圣遗物。")
            return
        if art.level >= art.max_level:
            messagebox.showinfo("提示", "这件圣遗物已经是满级了。")
            return
        sc0 = scoring.score_artifact(art, self.cfg, self.table)
        target = min(art.max_level, art.level + levels)
        events = engine.advance(art, target, self.cfg, self.table, self.rng)
        head = "【+%d → +%d】" % (target - levels if target - levels >= 0 else 0, art.level)
        entries = [("score", head + "\n")]
        for ev in events:
            entries.append((None, "  " + ev.get("text", "") + "\n"))
        if not events:
            entries.append(("dim", "  （本级没有到达强化判定点）\n"))
        entries += self._score_delta_entries(art, sc0)
        self._append_rich(self.enh_log, entries)
        self.refresh_all()
        self.set_status("已强化至 +%d。" % art.level)

    def do_enhance_max(self):
        art = self.current_artifact()
        if art is None:
            messagebox.showinfo("提示", "请先在上方选择一件圣遗物。")
            return
        if art.level >= art.max_level:
            messagebox.showinfo("提示", "这件圣遗物已经是满级了。")
            return
        sc0 = scoring.score_artifact(art, self.cfg, self.table)
        start = art.level
        events = engine.advance(art, art.max_level, self.cfg, self.table, self.rng)
        entries = [("score", "【+%d → +%d（满级）】\n" % (start, art.level))]
        for ev in events:
            entries.append((None, "  " + ev.get("text", "") + "\n"))
        entries += self._score_delta_entries(art, sc0)
        self._append_rich(self.enh_log, entries)
        self.refresh_all()
        self.set_status("已强化至满级 +%d。" % art.level)

    def _score_delta_entries(self, art, sc0, tag="hit"):
        """强化前后评分变化的文本。"""
        sc1 = scoring.score_artifact(art, self.cfg, self.table)
        if not sc1.get("enabled", True):
            return [("dim", "  评分已关闭（自定义 → 参数 里可以重新打开）\n")]
        d = sc1["total"] - sc0["total"]
        out = [("dim", "  评分 %.3f → %.3f（%+.3f）　有效词条数 %.2f → %.2f\n"
                % (sc0["total"], sc1["total"], d, sc0["useful_rolls"], sc1["useful_rolls"]))]
        if d > 1e-9:
            hits = self._hit_parts(art, sc1)
            out.append((tag, "  ★ 这一级拿到了评分%s\n"
                        % ("：" + "；".join(hits) if hits else "")))
        return out

    # ==================================================================
    # 圣遗物列表
    # ==================================================================
    def _build_list(self):
        f = self.tab_list
        box = ttk.Frame(f)
        box.pack(fill="x")
        ttk.Button(box, text="刷新", command=self.refresh_list).pack(side="left")
        ttk.Button(box, text="复制选中", command=self._copy_selected).pack(side="left", padx=6)
        ttk.Button(box, text="删除选中", command=self._delete_selected).pack(side="left", padx=6)
        ttk.Button(box, text="清空全部", command=self._clear_all).pack(side="left", padx=6)
        ttk.Button(box, text="全部强化至满级", command=self._max_all).pack(side="left", padx=6)
        ttk.Button(box, text="编辑向量", command=self._edit_vector_dialog).pack(side="left", padx=6)
        ttk.Button(box, text="导出列表(CSV)", command=self._export_csv).pack(side="left", padx=6)
        self.list_info = ttk.Label(box, text="")
        self.list_info.pack(side="right")

        cols = ("uid", "piece", "set", "slot", "main", "mainval", "lv", "score", "subs")
        heads = ("ID", "名称", "套装", "部位", "主词条", "主词条数值", "等级", "评分", "副词条")
        widths = (46, 150, 120, 56, 132, 84, 48, 64, 430)
        self.tree = ttk.Treeview(f, columns=cols, show="headings", height=14)
        for c, h, w in zip(cols, heads, widths):
            self.tree.heading(c, text=h)
            self.tree.column(c, width=w, anchor="w", stretch=(c == "subs"))
        vsb = ttk.Scrollbar(f, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self.tree.pack(fill="both", expand=True, pady=(6, 0))
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        self.tree.bind("<Double-1>", lambda e: self._show_detail_dialog())
        self.tree.bind("<Button-3>", self._on_tree_menu)

        detail = ttk.LabelFrame(f, text="评分明细（选中行；★ = 命中评分词条）", padding=4)
        detail.pack(fill="x", pady=(6, 0))
        self.list_score = ScrolledText(detail, wrap="word", height=7, font=("Consolas", 10))
        self.list_score.pack(fill="both", expand=True)
        self.list_score.configure(state="disabled")

    def _on_tree_menu(self, event):
        iid = self.tree.identify_row(event.y)
        if iid:
            self.tree.selection_set(iid)
            self._on_tree_select()
        m = tk.Menu(self, tearoff=0)
        m.add_command(label="查看详情", command=self._show_detail_dialog)
        m.add_command(label="编辑向量", command=self._edit_vector_dialog)
        m.add_command(label="复制选中", command=self._copy_selected)
        m.add_separator()
        m.add_command(label="删除选中", command=self._delete_selected)
        try:
            m.tk_popup(event.x_root, event.y_root)
        finally:
            m.grab_release()

    def refresh_list(self):
        self.tree.delete(*self.tree.get_children())
        mode = self.cfg.get("score_mode", "growth")
        scores = []
        for a in self.inv.items:
            sc = scoring.score_artifact(a, self.cfg, self.table)
            scores.append(sc["total"])
            main_txt = ("★" if sc["main_hl"] else "") + a.main_name
            self.tree.insert("", "end", iid=str(a.uid), values=(
                a.uid, a.piece_name, a.set_name, a.slot_name, main_txt,
                format_value(a.main_id, a.main_value(), self.table),
                "+%d" % a.level, "%.2f" % sc["total"], self._marked_summary(a, sc),
            ))
        n = len(scores)
        if not scoring.is_enabled(self.cfg):
            self.list_info.configure(text="共 %d 件　评分已关闭（自定义 → 参数 里可以重新打开）" % n)
        else:
            self.list_info.configure(text="共 %d 件　评分模式：%s　最高 %.2f　平均 %.2f"
                                          % (n, "总成长(词条数)" if mode == "growth" else "实际数值",
                                             max(scores) if n else 0.0,
                                             (sum(scores) / n) if n else 0.0))

    def _on_tree_select(self, _e=None):
        sel = self.tree.selection()
        if not sel:
            return
        uid = int(sel[0])
        art = self.inv.get(uid)
        if art:
            self._set_selection(art)

    def _copy_artifact(self, art: Artifact) -> Artifact:
        """深拷贝一件圣遗物：向量、保底信息、来源/备注/历史全部带走，编号留给 add() 重新分配。"""
        return Artifact(list(art.vec), self.cfg, self.table,
                        force_group=list(art.force_group), force_min=art.force_min,
                        force_hits=art.force_hits, source=art.source, note=art.note,
                        history=list(art.history) + ["复制自 #%d" % art.uid])

    def _copy_selected(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("提示", "请先在列表中选择要复制的圣遗物。")
            return
        src = [a for a in (self.inv.get(int(iid)) for iid in sel) if a is not None]
        if not src:
            return
        made = []
        for a in src:
            b = self._copy_artifact(a)
            self.inv.add(b)
            made.append(b)
        self.refresh_all()
        self.select_artifact(made[-1])
        self.set_status("已复制 %d 件圣遗物（新编号 %s）。"
                        % (len(made), "、".join("#%d" % b.uid for b in made)))

    def _delete_selected(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("提示", "请先在列表中选择要删除的圣遗物。")
            return
        for iid in sel:
            art = self.inv.get(int(iid))
            if art:
                self.inv.remove(art)
        self.refresh_all()
        self.set_status("已删除 %d 件。" % len(sel))

    def _clear_all(self):
        if not self.inv.items:
            return
        if messagebox.askyesno("确认", "确定清空全部 %d 件圣遗物？" % len(self.inv.items)):
            self.inv.clear()
            self.refresh_all()

    def _max_all(self):
        n = 0
        for a in self.inv.items:
            if a.level < a.max_level:
                engine.advance(a, a.max_level, self.cfg, self.table, self.rng)
                n += 1
        self.refresh_all()
        self.set_status("已将 %d 件圣遗物强化至满级。" % n)

    def _export_csv(self):
        path = filedialog.asksaveasfilename(defaultextension=".csv", initialfile="圣遗物列表.csv",
                                            filetypes=[("CSV", "*.csv")])
        if not path:
            return
        import csv
        with open(path, "w", encoding="utf-8-sig", newline="") as fp:
            w = csv.writer(fp)
            w.writerow(["ID", "名称", "套装", "部位", "主词条", "主词条数值", "等级", "评分",
                        "副词条1", "副词条2", "副词条3", "副词条4", "向量"])
            for a in self.inv.items:
                sc = scoring.score_artifact(a, self.cfg, self.table)
                w.writerow([a.uid, a.piece_name, a.set_name, a.slot_name,
                            ("★" if sc["main_hl"] else "") + a.main_name,
                            format_value(a.main_id, a.main_value(), self.table),
                            a.level, "%.3f" % sc["total"]] +
                           [a.sub_text(i, "★" if (i < len(sc["sub_hits"]) and sc["sub_hits"][i])
                              else "") for i in range(4)] + [a.vector_text()])
        self.set_status("已导出到 %s" % path)

    # ==================================================================
    # 祝圣之霜
    # ==================================================================
    def _build_elixir(self):
        f = self.tab_elixir
        box = ttk.LabelFrame(f, text="用祝圣之霜定义圣遗物", padding=8)
        box.pack(fill="x")

        ttk.Label(box, text="部位：").grid(row=0, column=0, sticky="w", pady=3)
        self.el_slot = tk.StringVar(value=self.cfg["slots"][0])
        cb = ttk.Combobox(box, textvariable=self.el_slot, state="readonly",
                          values=list(self.cfg["slots"]), width=12)
        cb.grid(row=0, column=1, sticky="w", padx=4)
        cb.bind("<<ComboboxSelected>>", lambda e: self._elixir_slot_changed())

        ttk.Label(box, text="套装：").grid(row=0, column=2, sticky="e", padx=(16, 2))
        self.el_set = tk.StringVar()
        self.el_set_combo = ttk.Combobox(box, textvariable=self.el_set, state="readonly",
                                         values=list(self.cfg["sets"]), width=22)
        self.el_set_combo.grid(row=0, column=3, sticky="w", padx=4)
        self.el_set_combo.bind("<<ComboboxSelected>>", lambda e: self._refresh_elixir_score_hint())

        ttk.Label(box, text="主词条：").grid(row=1, column=0, sticky="w", pady=3)
        self.el_main = tk.StringVar()
        self.el_main_combo = ttk.Combobox(box, textvariable=self.el_main, state="readonly", width=20)
        self.el_main_combo.grid(row=1, column=1, sticky="w", padx=4)
        self.el_main_combo.bind("<<ComboboxSelected>>", lambda e: self._refresh_elixir_score_hint())

        ttk.Label(box, text="定义副词条1：").grid(row=2, column=0, sticky="w", pady=3)
        self.el_sub1 = tk.StringVar()
        self.el_sub1_combo = ttk.Combobox(box, textvariable=self.el_sub1, state="readonly", width=20)
        self.el_sub1_combo.grid(row=2, column=1, sticky="w", padx=4)
        self.el_sub1_combo.bind("<<ComboboxSelected>>", lambda e: self._refresh_elixir_score_hint())
        ttk.Label(box, text="定义副词条2：").grid(row=3, column=0, sticky="w", pady=3)
        self.el_sub2 = tk.StringVar()
        self.el_sub2_combo = ttk.Combobox(box, textvariable=self.el_sub2, state="readonly", width=20)
        self.el_sub2_combo.grid(row=3, column=1, sticky="w", padx=4)
        self.el_sub2_combo.bind("<<ComboboxSelected>>", lambda e: self._refresh_elixir_score_hint())

        self.el_cost_label = ttk.Label(box, text="", foreground="#a30")
        self.el_cost_label.grid(row=2, column=2, columnspan=3, sticky="w", padx=(16, 2))
        ttk.Button(box, text="消耗祝圣之霜并生成", command=self.do_elixir).grid(
            row=3, column=2, columnspan=2, sticky="w", padx=(16, 2))
        self.el_stat_label = ttk.Label(box, text="")
        self.el_stat_label.grid(row=3, column=4, sticky="w", padx=8)

        self.el_score_label = ttk.Label(box, text="", foreground="#a35c00",
                                        wraplength=1000, justify="left")
        self.el_score_label.grid(row=4, column=0, columnspan=5, sticky="w", pady=(6, 0))

        _el = self.cfg["elixir"]
        _forced = int(_el.get("force_initial_sub_count", 0) or 0)
        _w = self.cfg["init_sub_weights"]
        ttk.Label(f, text="说明：定义的两个副词条合计至少会强化命中 %d 次；"
                          "花/羽消耗 1 个霜，沙 2 个，杯 4 个，冠 3 个（个数不限）。\n"
                          "初始副词条数与「获取新圣遗物」同一套分布（初始 3 : 4 = %s : %s）%s。" %
                  (_el["min_total_hits"],
                   _n(_w.get("3")), _n(_w.get("4")),
                   "，但当前被参数强制为 %d 条" % _forced if _forced else ""),
                  foreground="#555").pack(anchor="w", pady=(10, 2))
        self.el_out = ScrolledText(f, wrap="word", height=22, font=("Consolas", 10))
        self.el_out.pack(fill="both", expand=True)
        self.el_out.configure(state="disabled")

    def _elixir_slot_changed(self):
        slot = self.cfg["slots"].index(self.el_slot.get())
        mains = [self.table.display(sid) for sid, _ in self.table.main_candidates(slot)]
        self.el_main_combo.configure(values=mains)
        # 只有当前选择在新部位里不成立时才回到第一个候选——否则每次 refresh_all()
        #（生成完一件祝圣之霜就会走一次）都会把玩家挑好的主词条冲掉。
        if mains and self.el_main.get() not in mains:
            self.el_main.set(mains[0])
        subs = [self.table.display(s["id"]) for s in self.cfg["stats"] if s.get("w_sub", 0) > 0]
        self._elixir_sub_pool = subs
        self.el_sub1_combo.configure(values=subs)
        self.el_sub2_combo.configure(values=subs)
        if len(subs) > 1:
            if self.el_sub1.get() not in subs:
                self.el_sub1.set(subs[0])
            if self.el_sub2.get() not in subs or self.el_sub2.get() == self.el_sub1.get():
                self.el_sub2.set(subs[1])
        cost = (self.cfg["elixir"]["cost"] or {}).get(str(slot), 1)
        self.el_cost_label.configure(text="本次消耗祝圣之霜：%d 个（%s）" %
                                          (cost, self.el_slot.get()))
        self._refresh_elixir_score_hint()

    def _refresh_elixir_score_hint(self):
        """把当前所选 主词条 / 两条定义副词条 的评分权重写出来。"""
        lbl = getattr(self, "el_score_label", None)
        if lbl is None:
            return
        set_name = self.el_set.get()
        wmap = scoring.weight_map(self.cfg, self.table, set_name)
        enabled = scoring.is_enabled(self.cfg)
        hl_main_on = enabled and bool(self.cfg.get("score_hl_main", True))

        def _hit(text):
            key = self.table.resolve_name(text) if text else None
            return wmap.get(key) if key else None

        bits = []
        main_txt = self.el_main.get()
        if main_txt:
            hit = _hit(main_txt)
            bits.append("主词条 %s %s" % (main_txt, (
                "每级 +%s（%s）" % (_n(hit[1]), "★高亮" if (hit[0] > 0 and hl_main_on) else "不高亮"))
                if hit else "无权重"))
        for k, nm in enumerate((self.el_sub1.get(), self.el_sub2.get()), 1):
            if not nm:
                continue
            hit = _hit(nm)
            bits.append("定义副词条%d %s %s" % (k, nm, ("副×%s" % _n(hit[2])) if hit else "无权重"))
        body = "　｜　".join(bits) if bits else "（先选好部位与词条）"
        head = "" if enabled else "评分已关闭（自定义 → 参数 里可以重新打开；下面只是规则里的权重）\n"
        lbl.configure(text=head + "评分权重（%s）：%s\n"
                                   "　计分方式：主词条 = 等级 × 得分系数（+0 时不计分），"
                                   "副词条 = 副权重 × 总成长；★ 标出的就是高亮词条。"
                      % (set_name or "—", body))

    def do_elixir(self):
        slot = self.cfg["slots"].index(self.el_slot.get())
        set_name = self.el_set.get()
        if set_name not in self.cfg["sets"]:
            messagebox.showinfo("提示", "请选择套装。")
            return
        set_id = self.cfg["sets"].index(set_name)
        main_txt = self.el_main.get()
        main_id = 0
        for sid, _ in self.table.main_candidates(slot):
            if self.table.display(sid) == main_txt:
                main_id = sid
                break
        if not main_id:
            messagebox.showinfo("提示", "该部位没有这个主词条，请重新选择。")
            return
        s1 = self._display_to_id(self.el_sub1.get())
        s2 = self._display_to_id(self.el_sub2.get())
        if not s1 or not s2 or s1 == s2:
            messagebox.showinfo("提示", "请选择两个不同的副词条。")
            return
        try:
            art, cost = engine.create_elixir_artifact(
                self.cfg, self.table, self.rng, set_id, slot, main_id, s1, s2, self.state)
        except ValueError as exc:
            messagebox.showerror("错误", str(exc))
            return
        self.inv.add(art)
        entries = [
            ("dim", "消耗祝圣之霜 %d 个（累计 %d 个）。\n" % (cost, self.state.elixir_used)),
            ("dim", "定义：%s / %s / %s / %s / %s\n" % (
                set_name, self.el_slot.get(), self.table.display(main_id),
                self.table.display(s1), self.table.display(s2))),
            ("dim", "—" * 30 + "\n"),
        ]
        entries += self._artifact_entries(art)
        entries.append(("dim", "向量：%s\n" % art.vector_text()))
        self._set_rich(self.el_out, entries)
        self.select_artifact(art)
        self.refresh_all()
        self.set_status("已生成定义圣遗物，消耗祝圣之霜 %d 个。" % cost)

    def _display_to_id(self, text: str) -> int:
        for s in self.cfg["stats"]:
            if self.table.display(s["id"]) == text:
                return s["id"]
        return 0

    # ==================================================================
    # 启圣之尘
    # ==================================================================
    def _build_dust(self):
        f = self.tab_dust
        box = ttk.LabelFrame(f, text="用启圣之尘重新强化满级圣遗物", padding=8)
        box.pack(fill="x")
        ttk.Label(box, text="选择两条副词条（下拉框会跟随上方选中的圣遗物）：").grid(
            row=0, column=0, columnspan=4, sticky="w")
        ttk.Label(box, text="副词条A：").grid(row=1, column=0, sticky="w", pady=3)
        self.dust_a = tk.StringVar()
        self.dust_a_combo = ttk.Combobox(box, textvariable=self.dust_a, state="readonly", width=22)
        self.dust_a_combo.grid(row=1, column=1, sticky="w", padx=4)
        ttk.Label(box, text="副词条B：").grid(row=1, column=2, sticky="e", padx=(16, 2))
        self.dust_b = tk.StringVar()
        self.dust_b_combo = ttk.Combobox(box, textvariable=self.dust_b, state="readonly", width=22)
        self.dust_b_combo.grid(row=1, column=3, sticky="w", padx=4)
        # 记住玩家选的是「第几条副词条」而不是下拉框里那串文字：重塑会改成长数值，
        # 文字跟着变，若按文字记选择就会被打回第一、第二条。
        self.dust_a_idx, self.dust_b_idx = 0, 1
        self.dust_a_combo.bind("<<ComboboxSelected>>", lambda _e: self._sync_dust_sel())
        self.dust_b_combo.bind("<<ComboboxSelected>>", lambda _e: self._sync_dust_sel())

        ttk.Button(box, text="消耗启圣之尘并重塑", command=self.do_dust).grid(
            row=2, column=0, columnspan=2, sticky="w", pady=(8, 0))
        self.dust_cost_label = ttk.Label(box, text="", foreground="#a30")
        self.dust_cost_label.grid(row=2, column=2, columnspan=2, sticky="w", padx=(16, 2))
        self.dust_lock_label = ttk.Label(box, text="", foreground="#036",
                                         wraplength=780, justify="left")
        self.dust_lock_label.grid(row=3, column=0, columnspan=4, sticky="w", pady=(6, 0))

        info = ttk.LabelFrame(f, text="圣言解名进度", padding=8)
        info.pack(fill="x", pady=(10, 0))
        self.dust_prog = ttk.Progressbar(info, orient="horizontal", length=520, maximum=18)
        self.dust_prog.pack(anchor="w")
        self.dust_prog_label = ttk.Label(info, text="")
        self.dust_prog_label.pack(anchor="w", pady=(4, 0))
        d = self.cfg["dust"]
        _t3 = " / ".join(_n(int(x)) for x in (d.get("hit3_thresholds") or [6, 12]))
        ttk.Label(info, foreground="#555", justify="left", text=(
            "进度从 0 起算，每消耗 1 个启圣之尘按部位累加 1 或 2 点。\n"
            "保底只在「本次消耗把进度推过阈值」的那一次生效：\n"
            "　进度 + 消耗数 首次达到 %s → 所选副词条合计至少命中 %d 次；\n"
            "　首次达到 %d → 合计至少命中 %d 次，随后进度减去 %d。\n"
            "阈值之间的消耗不带进度保底。花/羽消耗 1 个，其余部位消耗 2 个。\n"
            "每次使用都至少保底 %d 次命中（祝圣之霜定义件同样适用）。\n"
            "祝圣之霜定义件要重新强化的只能是当初定义的那两条副词条，下拉框会锁死不可改。\n"
            "重塑完成后会弹窗让你选「采用重塑前」还是「采用重塑后」。"
            % (_t3, d.get("hit3_min_total", 3),
               d.get("hit4_threshold", 18), d.get("hit4_min_total", 4),
               d.get("hit4_threshold", 18),
               d.get("min_total_hits", 2))
        )).pack(anchor="w")
        prow = ttk.Frame(info)
        prow.pack(anchor="w", pady=(8, 0))
        ttk.Label(prow, text="手动设置圣言解名进度：").pack(side="left")
        self.dust_set_var = tk.StringVar(value="0")
        self.dust_set_spin = ttk.Spinbox(prow, from_=0, to=max(0, int(d.get("hit4_threshold", 18)) - 1),
                                         width=6, textvariable=self.dust_set_var)
        self.dust_set_spin.pack(side="left", padx=4)
        self.dust_set_spin.bind("<Return>", lambda _e: self._set_dust_progress())
        ttk.Button(prow, text="设为该值", command=self._set_dust_progress).pack(
            side="left", padx=(0, 14))
        ttk.Button(prow, text="清零圣言解名进度",
                   command=self._reset_dust_progress).pack(side="left")
        ttk.Label(info, foreground="#555", justify="left", text=(
            "进度可以直接改：把上面的数字改成想要的点数后点「设为该值」"
            "（只改保底进度，不动累计消耗数与圣遗物）。")).pack(anchor="w", pady=(4, 0))

        ttk.Label(f, text="重塑日志").pack(anchor="w", pady=(10, 2))
        self.dust_out = ScrolledText(f, wrap="word", height=14, font=("Consolas", 10))
        self.dust_out.pack(fill="both", expand=True)
        self.dust_out.configure(state="disabled")

    def _sync_dust_sel(self):
        """把下拉框当前显示的文字反查成下标，记进 dust_a_idx / dust_b_idx。

        只在文字确实出现在当前选项列表里时才改下标；重塑后文字变了就对不上，
        这时保留下标，选择因此不会被重置。
        """
        vals = list(self.dust_a_combo.cget("values") or ())
        for var, attr in ((self.dust_a, "dust_a_idx"), (self.dust_b, "dust_b_idx")):
            txt = var.get()
            if txt in vals:
                setattr(self, attr, vals.index(txt))

    def refresh_dust_choices(self):
        self._sync_dust_sel()       # 先按旧列表把玩家当前的选择记成下标
        art = self.current_artifact()
        vals = []
        if art is not None:
            vals = ["%d. %s" % (i + 1, art.sub_text_plain(i)) for i in art.active_indices()]
        self.dust_a_combo.configure(values=vals)
        self.dust_b_combo.configure(values=vals)
        # 祝圣之霜定义件：两条副词条锁死为当初定义的那两条，不能改
        locked = engine.dust_locked_indices(art)
        if locked and len(vals) > max(locked):
            self.dust_a_idx, self.dust_b_idx = locked[0], locked[1]
            self.dust_a.set(vals[locked[0]])
            self.dust_b.set(vals[locked[1]])
            state = "disabled"
            self.dust_lock_label.configure(
                text="这件是祝圣之霜定义件：只能强化「%s」与「%s」这两条定义词条，不可更改。"
                     % (self.table.display(art.sub_id(locked[0])),
                        self.table.display(art.sub_id(locked[1]))))
        else:
            if vals:
                n = len(vals)
                ai = max(0, min(int(self.dust_a_idx), n - 1))
                bi = max(0, min(int(self.dust_b_idx), n - 1))
                if bi == ai:
                    bi = 0 if ai != 0 else (1 if n > 1 else 0)
                self.dust_a_idx, self.dust_b_idx = ai, bi
                self.dust_a.set(vals[ai])
                self.dust_b.set(vals[bi])
            else:
                self.dust_a.set("")
                self.dust_b.set("")
                self.dust_a_idx = self.dust_b_idx = 0
            state = "readonly"
            self.dust_lock_label.configure(text="")
        self.dust_a_combo.configure(state=state)
        self.dust_b_combo.configure(state=state)
        if art is not None:
            cost = (self.cfg["dust"]["cost"] or {}).get(str(art.slot), 2)
            self.dust_cost_label.configure(
                text="本次消耗启圣之尘：%d 个（%s，当前 +%d）" % (cost, art.slot_name, art.level))
        else:
            self.dust_cost_label.configure(text="")
        d = self.cfg["dust"]
        p = self.state.dust_progress
        h4 = int(d.get("hit4_threshold", 18))
        self.dust_prog.configure(maximum=max(1, h4))
        self.dust_prog["value"] = p
        # 下一个还没被跨过的阈值
        marks = [(int(t), int(d.get("hit3_min_total", 3)))
                 for t in (d.get("hit3_thresholds") or [6, 12])]
        marks.append((h4, int(d.get("hit4_min_total", 4))))
        nxt = "无"
        for t, n in sorted(marks):
            if p < t:
                nxt = "距 %d 次保底还差 %d 点" % (n, t - p)
                break
        self.dust_prog_label.configure(
            text="当前进度：%d / %d　累计消耗启圣之尘：%d 个　下次保底：%s"
                 % (p, h4, self.state.dust_used, nxt))
        if getattr(self, "dust_set_var", None) is not None:
            self.dust_set_var.set(str(p))

    def _set_dust_progress(self):
        """手动设置圣言解名进度（只动进度，不动累计消耗数与圣遗物）。"""
        d = self.cfg.get("dust") or {}
        hi = max(0, int(d.get("hit4_threshold", 18)) - 1)
        txt = str(self.dust_set_var.get()).strip()
        try:
            v = int(txt)
        except (TypeError, ValueError):
            messagebox.showwarning(
                "输入有误", "「%s」不是整数。请输入 0 ~ %d 之间的整数。" % (txt, hi))
            self.dust_set_var.set(str(self.state.dust_progress))
            return
        if v < 0 or v > hi:
            clamped = max(0, min(hi, v))
            if not messagebox.askyesno(
                    "超出范围",
                    "圣言解名进度每 %d 点走完一个循环，所以要填 0 ~ %d。\n是否改成 %d？"
                    % (hi + 1, hi, clamped)):
                self.dust_set_var.set(str(self.state.dust_progress))
                return
            v = clamped
        old = self.state.dust_progress
        self.state.dust_progress = v
        self.refresh_dust_choices()
        self._update_status()
        self.set_status("圣言解名进度：%d → %d。" % (old, v))

    def _reset_dust_progress(self):
        p = self.state.dust_progress
        if p <= 0:
            self.set_status("圣言解名进度已经是 0。")
            return
        if not messagebox.askyesno(
                "确认", "把圣言解名进度从 %d 清零？\n（累计消耗数不受影响，只重置保底进度）" % p):
            return
        self.state.dust_progress = 0
        self.refresh_dust_choices()
        self._update_status()
        self.set_status("圣言解名进度已清零。")

    # ---------------------------------------------------------------- 重塑选择
    def _dust_keep_payload(self, art, info):
        """算出「重塑前 / 重塑后」两份对比展示（用探针，不动原圣遗物）。"""
        out = {}
        for tag in ("before", "after"):
            probe = Artifact(list(art.vec), self.cfg, self.table)
            engine.apply_sub_snapshot(probe, info[tag])
            sc = scoring.score_artifact(probe, self.cfg, self.table)
            out[tag] = (self._artifact_entries(probe, brief=True), sc)
        return out

    def _dust_process_text(self, art, info):
        """把这次重塑的每一次强化判定按顺序列出来。"""
        chosen = [int(i) for i in (info.get("chosen") or [])]
        lines = []
        for k, ev in enumerate(info.get("events") or [], 1):
            i = int(ev.get("index", -1))
            mark = "◆" if i in chosen else "　"
            lines.append("第 %s 次判定　%s 副词条%s（%s）　成长 +%s"
                         % (_n(k), mark, _n(i + 1), self.table.display(ev.get("stat")),
                            _n(float(ev.get("gain", 0.0)))))
        if not lines:
            lines.append("（本次没有产生强化判定）")
        before, after = info.get("before") or {}, info.get("after") or {}
        lines.append("—" * 46)
        for i in chosen:
            b = float((before.get("init_g") or [0] * 4)[i]) + float((before.get("up_g") or [0] * 4)[i])
            a = float((after.get("init_g") or [0] * 4)[i]) + float((after.get("up_g") or [0] * 4)[i])
            lines.append("所选 副词条%s（%s）　总成长 %s → %s"
                         % (_n(i + 1), self.table.display(art.sub_id(i)), _n(b), _n(a)))
        hit_txt = "、".join("副词条%s" % _n(i + 1) for i in chosen)
        lines.append("共 %s 次判定，落在 %s 上的有 %s 次（保底要求 %s 次）"
                     % (_n(len(info.get("events") or [])), hit_txt,
                        _n(int(info.get("hits", 0))), _n(int(info.get("need", 0)))))
        return "\n".join(lines)

    def _build_dust_keep_window(self, art, info):
        """只建窗口，不等待（方便测试）；结果写在 win._choice 上。"""
        payload = self._dust_keep_payload(art, info)
        win = tk.Toplevel(self)
        # 先藏起来：等内容排好、尺寸定死之后再显示，避免开窗时肉眼可见的抖动
        win.withdraw()
        win.title("启圣之尘 · 采用重塑前还是重塑后（#%d）" % art.uid)
        win.transient(self)
        win.minsize(640, 460)
        _sw, _sh = win.winfo_screenwidth(), win.winfo_screenheight()
        _w = min(1000, _sw - 60)          # 先给换行宽度一个估计值，最后按实际尺寸再修一次
        win._choice = "after"
        win.columnconfigure(0, weight=1)
        win.rowconfigure(1, weight=3)
        win.rowconfigure(2, weight=1)
        head = ttk.Label(win, justify="left", wraplength=max(240, _w - 30), padding=(10, 8),
                         foreground="#333",
                         text=("%s\n所属套装：%s　部位：%s\n"
                               "保底命中 %d 次，本次实际命中 %d 次。选一个作为最终结果——"
                               "启圣之尘的消耗与圣言解名进度都已计入，不会因为选「重塑前」而退回。"
                               % (info["text"], art.set_name, art.slot_name,
                                  info["need"], info["hits"])))
        head.grid(row=0, column=0, sticky="ew")
        cols = ttk.Frame(win, padding=(10, 0))
        cols.grid(row=1, column=0, sticky="nsew")
        cols.columnconfigure(0, weight=1, uniform="dustcol")
        cols.columnconfigure(1, weight=1, uniform="dustcol")
        cols.rowconfigure(0, weight=1)
        for ci, (tag, title) in enumerate((("before", "重塑前"), ("after", "重塑后（默认）"))):
            box = ttk.LabelFrame(cols, text=title, padding=6)
            box.grid(row=0, column=ci, sticky="nsew", padx=4)
            body, sc = payload[tag]
            ttk.Label(box, text="评分 %.2f　有效词条数 %.2f" % (sc["total"], sc["useful_rolls"]),
                      foreground="#0a5").pack(anchor="w")
            t = ScrolledText(box, wrap="word", font=("Consolas", 10), width=22, height=10)
            t.pack(fill="both", expand=True, pady=(4, 0))
            self._set_rich(t, body)

        proc = ttk.LabelFrame(
            win, padding=6, text="重塑过程（◆ = 命中的是本次选中的那两条副词条）")
        proc.grid(row=2, column=0, sticky="ew", padx=10, pady=(8, 0))
        pt = ScrolledText(proc, wrap="word", font=("Consolas", 10), width=22, height=6)
        pt.pack(fill="both", expand=True)
        pt.insert("1.0", self._dust_process_text(art, info))
        pt.configure(state="disabled")

        def _rewrap(ev):
            if ev.widget is not win:
                return                    # 只理会本窗口，子控件自身的 Configure 一律忽略
            want = max(240, ev.width - 30)
            if int(head.cget("wraplength")) != want:
                head.configure(wraplength=want)

        win.bind("<Configure>", _rewrap)
        bar = ttk.Frame(win, padding=10)
        bar.grid(row=3, column=0, sticky="ew")

        def pick(tag):
            win._choice = tag
            win.destroy()

        ttk.Button(bar, text="采用重塑前", command=lambda: pick("before")).pack(side="left")
        ttk.Button(bar, text="采用重塑后", command=lambda: pick("after")).pack(side="right")
        win.bind("<Escape>", lambda e: pick("after"))

        win.update_idletasks()      # 先让内容报出自己实际需要的尺寸
        _rw, _rh = win.winfo_reqwidth(), win.winfo_reqheight()
        _w = max(760, min(max(_rw, 900), _sw - 40))
        _h = max(520, min(_rh, _sh - 80))
        win.geometry("%dx%d+%d+%d" % (_w, _h, max(0, (_sw - _w) // 2),
                                      max(0, min(40, (_sh - _h) // 2))))
        head.configure(wraplength=max(240, _w - 30))   # 换行宽度在显示前定好
        win.update_idletasks()
        win.deiconify()             # 再一次性显示，不再有任何重新布局
        return win

    def _dust_keep_dialog(self, art, info) -> str:
        """弹窗让玩家二选一，返回 "before" 或 "after"。"""
        win = self._build_dust_keep_window(art, info)
        win.grab_set()
        win.focus_set()
        self.wait_window(win)
        return getattr(win, "_choice", "after")

    def do_dust(self):
        art = self.current_artifact()
        if art is None:
            messagebox.showinfo("提示", "请先在上方选择一件圣遗物。")
            return
        if art.level < art.max_level:
            messagebox.showinfo("提示", "只有满级（+%d）的圣遗物才能使用启圣之尘。" % art.max_level)
            return
        self._sync_dust_sel()           # 让程序里直接 set 的下拉框文字也能被认出来
        locked = engine.dust_locked_indices(art)
        if len(locked) == 2:
            idxs = list(locked)         # 祝圣之霜定义件：目标就是定义词条，不接受改动
        else:
            n = len(art.active_indices())
            a_i, b_i = int(self.dust_a_idx), int(self.dust_b_idx)
            if not (0 <= a_i < n and 0 <= b_i < n) or a_i == b_i:
                messagebox.showinfo("提示", "请选择两条不同的副词条。")
                return
            idxs = [a_i, b_i]
        before = self._artifact_entries(art)
        sc_before = scoring.score_artifact(art, self.cfg, self.table)["total"]

        def decide(info):
            if not self.cfg["dust"].get("ask_before_apply", True):
                return "after"
            return self._dust_keep_dialog(art, info)

        try:
            res = engine.redeem_dust(art, self.cfg, self.table, self.rng, idxs,
                                     self.state, decide)
        except ValueError as exc:
            messagebox.showerror("错误", str(exc))
            return
        kept = res.get("kept", "after")
        sc_after = scoring.score_artifact(art, self.cfg, self.table)["total"]
        entries = [("score", res["text"] + "\n")]
        if len(locked) == 2:
            entries.append(("dim", "目标副词条（祝圣之霜定义，已锁定不可改）：%s、%s\n" % (
                self.table.display(art.sub_id(locked[0])),
                self.table.display(art.sub_id(locked[1])))))
        entries.append(("score", "采用结果：%s\n" % ("重塑前（已还原）" if kept == "before" else "重塑后")))
        entries.append(("dim", "—" * 30 + "\n"))
        entries.append(("score", "重塑前（评分 %.3f）：\n" % sc_before))
        entries += before
        entries.append(("dim", "—" * 30 + "\n"))
        entries.append(("score", "重塑后（评分 %.3f，%+.3f）：\n" % (sc_after, sc_after - sc_before)))
        entries += self._artifact_entries(art)
        entries.append(("dim", "向量：%s\n\n" % art.vector_text()))
        self._append_rich(self.dust_out, entries)
        self.refresh_all()
        self.set_status("重塑完成：保底 %d 次，实际命中 %d 次，采用%s。" % (
            res["need"], res["hits"], "重塑前" if kept == "before" else "重塑后"))

    # ==================================================================
    # 评分
    # ==================================================================
    def _build_score(self):
        f = self.tab_score
        top = ttk.Frame(f)
        top.pack(fill="x")
        ttk.Label(top, text="编辑套装：").pack(side="left")
        self.sc_set = tk.StringVar(value=(self.cfg.get("sets") or [""])[0])
        self.sc_set_combo = ttk.Combobox(top, textvariable=self.sc_set, state="readonly", width=26)
        self.sc_set_combo.pack(side="left", padx=4)
        self.sc_set_combo.bind("<<ComboboxSelected>>", lambda e: self._load_score_rules())
        ttk.Button(top, text="载入该套装规则", command=self._load_score_rules).pack(side="left", padx=4)
        ttk.Button(top, text="保存当前规则", command=self._save_score_rules).pack(side="left", padx=4)
        ttk.Button(top, text="把当前规则套用到全部套装", command=self._score_apply_all).pack(
            side="left", padx=4)
        ttk.Button(top, text="把内置默认模板套用到全部套装",
                   command=self._score_apply_template).pack(side="left", padx=4)

        opt = ttk.Frame(f)
        opt.pack(fill="x", pady=(6, 0))
        ttk.Label(opt, text="评分模式：").pack(side="left")
        self.sc_mode = tk.StringVar(value=self.cfg.get("score_mode", "growth"))
        ttk.Radiobutton(opt, text="按总成长（等价于词条数）", variable=self.sc_mode,
                        value="growth", command=self._score_mode_changed).pack(side="left")
        ttk.Radiobutton(opt, text="按实际数值", variable=self.sc_mode,
                        value="value", command=self._score_mode_changed).pack(side="left", padx=10)
        self.sc_result = ttk.Label(opt, text="")
        self.sc_result.pack(side="left", padx=16)

        ttk.Label(f, text="规则文本（格式：套装名：词条名 主词条高亮 主词条得分系数 副词条权重）　"
                          "主词条得分 = 等级 × 得分系数；第 2 个数 > 0 才把该词条作为主词条时加 ★ 高亮"
                          ).pack(anchor="w", pady=(8, 2))
        self.sc_text = ScrolledText(f, height=16, wrap="word", font=("Consolas", 10))
        self.sc_text.pack(fill="both", expand=True)

        ttk.Button(f, text="全部规则…（编辑所有套装的规则）",
                   command=self._edit_all_rules).pack(anchor="w", pady=6)
        ttk.Label(f, text="当前圣遗物评分明细").pack(anchor="w")
        self.sc_detail = ScrolledText(f, height=12, wrap="word", font=("Consolas", 10))
        self.sc_detail.pack(fill="both", expand=True)
        self.sc_detail.configure(state="disabled")
        self._load_score_rules()        # 一进页面就能看到当前套装的规则，直接改

    def _score_mode_changed(self):
        self.cfg["score_mode"] = self.sc_mode.get()
        self.refresh_list()
        self.refresh_score_detail()

    def _load_score_rules(self):
        name = self.sc_set.get()
        if not name:
            name = (self.cfg.get("sets") or [""])[0]
            if not name:
                return
            self.sc_set.set(name)
        rules = self.cfg["scoring"]["sets"].get(name)
        if not rules:
            # 没有规则就从默认模板复制一份写进这个套装，方便直接改
            src = self.cfg["scoring"].get("default") or DEFAULT_SCORE_TEMPLATE
            rules = [list(scoring.rule_parts(r) or (r[0], 1.0, 1.0, 1.0)) for r in src]
            self.cfg["scoring"]["sets"][name] = rules
        self.sc_text.delete("1.0", "end")
        self.sc_text.insert("1.0", "%s：%s" % (name, scoring.rules_body(rules)))

    def _save_score_rules(self):
        parsed, warns = scoring.parse_rules(self.sc_text.get("1.0", "end"), self.table)
        if not parsed:
            messagebox.showinfo("提示", "没有解析到任何规则。")
            return
        for set_name, rules in parsed.items():
            if set_name in ("通用", "默认", "default"):
                self.cfg["scoring"]["default"] = rules
            else:
                if set_name not in self.cfg["sets"]:
                    if not messagebox.askyesno("确认", "套装「%s」不在套装列表里，仍然保存？" % set_name):
                        continue
                self.cfg["scoring"]["sets"][set_name] = rules
        if warns:
            messagebox.showwarning("部分内容被忽略", "\n".join(warns[:12]))
        self.refresh_list()
        self.refresh_score_detail()
        self.set_status("评分规则已更新。")

    def _score_apply_all(self):
        self._save_score_rules()
        name = self.sc_set.get()
        rules = self.cfg["scoring"]["sets"].get(name)
        if not rules:
            messagebox.showinfo("提示", "当前套装没有规则。")
            return
        scoring.apply_template_to_all(self.cfg, rules)
        self.refresh_list()
        self.set_status("已把「%s」的规则套用到全部套装。" % name)

    def _score_apply_template(self):
        """把内置的默认模板（四段格式）写进每个套装，方便逐个再改。"""
        tmpl = [list(r) for r in DEFAULT_SCORE_TEMPLATE]
        self.cfg["scoring"]["default"] = [list(r) for r in tmpl]
        scoring.apply_template_to_all(self.cfg, tmpl)
        self._load_score_rules()
        self.refresh_list()
        self.refresh_score_detail()
        self.set_status("已把内置默认模板套用到 %d 个套装。" % len(self.cfg["sets"]))

    def _edit_all_rules(self):
        win = tk.Toplevel(self)
        win.title("全部套装评分规则")
        win.geometry("880x640")
        ttk.Label(win, text="格式：套装名：词条名 主词条高亮 主词条得分系数 副词条权重",
                  foreground="#555").pack(anchor="w", padx=8, pady=6)
        txt = ScrolledText(win, wrap="none", font=("Consolas", 10))
        txt.pack(fill="both", expand=True, padx=8)
        txt.insert("1.0", scoring.rules_to_text(self.cfg["scoring"]["sets"]))

        def ok():
            parsed, warns = scoring.parse_rules(txt.get("1.0", "end"), self.table)
            for set_name, rules in parsed.items():
                if set_name in ("通用", "默认", "default"):
                    self.cfg["scoring"]["default"] = rules
                else:
                    self.cfg["scoring"]["sets"][set_name] = rules
            if warns:
                messagebox.showwarning("部分内容被忽略", "\n".join(warns[:12]), parent=win)
            self.refresh_list()
            self.refresh_score_detail()
            win.destroy()
            self.set_status("评分规则已更新。")

        bar = ttk.Frame(win)
        bar.pack(fill="x", padx=8, pady=8)
        ttk.Button(bar, text="保存", command=ok).pack(side="left")
        ttk.Button(bar, text="取消", command=win.destroy).pack(side="left", padx=8)

    def refresh_score_detail(self):
        self.sc_set_combo.configure(values=list(self.cfg["sets"]))
        if not self.sc_set.get() and self.cfg["sets"]:
            self.sc_set.set(self.cfg["sets"][0])
        art = self.current_artifact()
        if art is None:
            self._set_rich(self.sc_detail, [("dim", "（未选择圣遗物）\n")])
            self.sc_result.configure(text="")
            return
        sc = scoring.score_artifact(art, self.cfg, self.table)
        entries = self._detail_entries(
            art, sc, head="套装：%s　规则来源：套装专属规则　"
                          "主词条得分 = 等级 × 得分系数" % art.set_name)
        entries += self._score_entries(art, sc)
        self._set_rich(self.sc_detail, entries)
        if sc.get("enabled", True):
            self.sc_result.configure(text="当前圣遗物得分：%.3f" % sc["total"])
        else:
            self.sc_result.configure(text="当前圣遗物得分：—（评分已关闭）")

    # ==================================================================
    # 自定义
    # ==================================================================
    def _build_custom(self):
        f = self.tab_custom
        nb = ttk.Notebook(f)
        nb.pack(fill="both", expand=True)
        self._build_custom_table(nb)
        self._build_custom_sets(nb)
        self._build_custom_layout(nb)
        self._build_custom_params(nb)

        bar = ttk.Frame(f)
        bar.pack(fill="x", pady=(6, 0))
        ttk.Button(bar, text="保存配置", command=self._save_config_click).pack(side="left")
        ttk.Button(bar, text="恢复默认配置", command=self._reset_config).pack(side="left", padx=6)
        ttk.Button(bar, text="重新载入 config.json", command=self._reload_config).pack(
            side="left", padx=6)
        ttk.Label(bar, text="配置路径：%s" % CONFIG_PATH, foreground="#555").pack(side="left", padx=12)

    def _build_custom_table(self, nb):
        page = ttk.Frame(nb, padding=8)
        nb.add(page, text="数值表")
        ttk.Label(page, justify="left", foreground="#555", text=(
            "每行：名称 最大值 沙权重 头权重 杯权重 副词条权重 命中权重\n"
            "行号 = 主词条 id（从 1 开始）。名称重复没关系（例如「攻击力」同时表示小攻击和攻击力%%），"
            "程序按最大值是否小于 5 判断百分比。可直接粘贴 基础数据.txt 的内容。"
        )).pack(anchor="w")
        self.tbl_text = ScrolledText(page, wrap="none", height=20, font=("Consolas", 10))
        self.tbl_text.pack(fill="both", expand=True, pady=6)
        bar = ttk.Frame(page)
        bar.pack(fill="x")
        ttk.Button(bar, text="应用数值表", command=self._apply_table_text).pack(side="left")
        ttk.Button(bar, text="从 txt 文件导入", command=self._import_table_txt).pack(side="left", padx=6)
        ttk.Button(bar, text="导出为 txt", command=self._export_table_txt).pack(side="left", padx=6)
        ttk.Button(bar, text="重新载入", command=self._fill_table_text).pack(side="left", padx=6)

    def _fill_table_text(self):
        lines = []
        for s in self.cfg["stats"]:
            lines.append("%s %s %s %s %s %s %s" % (
                s["name"], _n(s["max"]), _n(s.get("w_sand", 0)), _n(s.get("w_head", 0)),
                _n(s.get("w_cup", 0)), _n(s.get("w_sub", 0)), _n(s.get("w_hit", 0))))
        self.tbl_text.delete("1.0", "end")
        self.tbl_text.insert("1.0", "\n".join(lines))

    def _apply_table_text(self, text: str | None = None):
        raw = text if text is not None else self.tbl_text.get("1.0", "end")
        rows = []
        bad = []
        for ln, line in enumerate(raw.splitlines(), 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            tk_ = line.split()
            if len(tk_) < 7:
                bad.append("第 %d 行字段不足：%s" % (ln, line))
                continue
            try:
                name = tk_[0]
                nums = [float(x) for x in tk_[1:7]]
            except ValueError:
                bad.append("第 %d 行数值无法解析：%s" % (ln, line))
                continue
            rows.append((name, nums))
        if not rows:
            messagebox.showerror("错误", "没有解析到有效的数据行。")
            return
        if bad and not messagebox.askyesno("确认", "以下行将被忽略：\n%s\n\n继续？" % "\n".join(bad[:8])):
            return
        stats = []
        for i, (name, nums) in enumerate(rows):
            mx, ws, wh, wc, wsub, whit = nums
            stats.append({
                "id": i + 1,
                "key": ROW_KEYS[i] if i < len(ROW_KEYS) else "stat%d" % (i + 1),
                "name": name, "max": mx, "pct": mx < 5.0,
                "w_sand": int(ws), "w_head": int(wh), "w_cup": int(wc),
                "w_sub": int(wsub), "w_hit": int(whit), "enabled": True,
            })
        # 检查花/羽固定主词条是否还在范围内
        cfg = copy.deepcopy(self.cfg)
        cfg["stats"] = stats
        normalize(cfg)
        problems = validate(cfg)
        if problems and not messagebox.askyesno(
                "数值表有问题",
                "以下问题会导致部分功能不可用：\n\n· " + "\n· ".join(problems) +
                "\n\n仍然应用这张数值表吗？"):
            return
        self._replace_config(cfg)
        self._fill_table_text()
        self.set_status("数值表已更新（%d 行）。" % len(rows))

    def _import_table_txt(self):
        path = filedialog.askopenfilename(filetypes=[("文本文件", "*.txt"), ("全部文件", "*.*")])
        if not path:
            return
        with open(path, "r", encoding="utf-8-sig") as fp:
            self._apply_table_text(fp.read())

    def _export_table_txt(self):
        path = filedialog.asksaveasfilename(defaultextension=".txt", initialfile="基础数据.txt",
                                            filetypes=[("文本文件", "*.txt")])
        if not path:
            return
        with open(path, "w", encoding="utf-8") as fp:
            fp.write(self.tbl_text.get("1.0", "end"))
        self.set_status("已导出 %s" % path)

    # ------------------------------------------------------------------
    def _build_custom_sets(self, nb):
        page = ttk.Frame(nb, padding=8)
        nb.add(page, text="套装与秘境")
        ttk.Label(page, justify="left", foreground="#555", text=(
            "套装与秘境都可以自定义。左边是套装表，右边是秘境掉落表。\n"
            "⚠ 左侧「序号」就是圣遗物向量里存的套装下标——改动顺序（上移/下移/删除）会让"
            "已存档圣遗物的套装名跟着变，重命名则不影响。评分规则会跟着套装名一起搬迁。"
        )).pack(anchor="w")

        body = ttk.Frame(page)
        body.pack(fill="both", expand=True, pady=6)
        body.columnconfigure(0, weight=2, uniform="sets")
        body.columnconfigure(1, weight=3, uniform="sets")
        body.rowconfigure(0, weight=1)

        left = ttk.LabelFrame(body, text="套装（序号 = 向量下标）", padding=6)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        self.sets_tree = ttk.Treeview(left, columns=("i", "name"), show="headings", height=18)
        self.sets_tree.heading("i", text="序号")
        self.sets_tree.heading("name", text="套装名称")
        self.sets_tree.column("i", width=60, anchor="center", stretch=False)
        self.sets_tree.column("name", width=240, anchor="w", stretch=True)
        self.sets_tree.pack(fill="both", expand=True)
        self.sets_tree.bind("<Double-1>", lambda _e: self._rename_set())
        b1 = ttk.Frame(left)
        b1.pack(fill="x", pady=(6, 0))
        for txt, cmd in (("新增", self._add_set), ("重命名", self._rename_set),
                         ("编辑部件名", self._edit_pieces),
                         ("上移", lambda: self._move_set(-1)), ("下移", lambda: self._move_set(1)),
                         ("删除", self._del_set), ("恢复默认", self._reset_sets)):
            ttk.Button(b1, text=txt, command=cmd).pack(side="left", padx=(0, 4))
        ttk.Label(left, foreground="#555", justify="left", text=(
            "「部件名」就是这件圣遗物的名称：\n"
            "生之花 / 死之羽 / 时之沙 / 空之杯 / 理之冠 各一个。\n"
            "双击套装行可改名；改部件名请用「编辑部件名」。"
        )).pack(anchor="w", pady=(6, 0))

        right = ttk.LabelFrame(body, text="秘境（掉落套装）", padding=6)
        right.grid(row=0, column=1, sticky="nsew")
        self.dom_tree = ttk.Treeview(right, columns=("name", "drops"), show="headings", height=18)
        self.dom_tree.heading("name", text="秘境名称")
        self.dom_tree.heading("drops", text="掉落套装（逗号分隔）")
        self.dom_tree.column("name", width=200, anchor="w", stretch=False)
        self.dom_tree.column("drops", width=420, anchor="w", stretch=True)
        self.dom_tree.pack(fill="both", expand=True)
        self.dom_tree.bind("<Double-1>", lambda _e: self._edit_domain())
        b2 = ttk.Frame(right)
        b2.pack(fill="x", pady=(6, 0))
        for txt, cmd in (("新增", self._add_domain), ("重命名", self._rename_domain),
                         ("编辑掉落", self._edit_domain), ("删除", self._del_domain),
                         ("恢复默认", self._reset_domains)):
            ttk.Button(b2, text=txt, command=cmd).pack(side="left", padx=(0, 4))

    def _fill_sets_tree(self):
        self.sets_tree.delete(*self.sets_tree.get_children())
        for i, name in enumerate(self.cfg.get("sets", [])):
            self.sets_tree.insert("", "end", iid=str(i), values=(i, name))
        self.dom_tree.delete(*self.dom_tree.get_children())
        doms = self.cfg.get("domains") or {}
        for name, drops in doms.items():
            self.dom_tree.insert("", "end", iid=name, values=(name, "，".join(drops)))

    def _sets_changed(self, msg: str):
        problems = validate(self.cfg)
        if problems:
            self.set_status("%s　⚠ %s" % (msg, problems[0]))
        else:
            self.set_status(msg)
        self._replace_config(self.cfg)

    def _add_set(self):
        name = simpledialog.askstring("新增套装", "套装名称：", parent=self)
        if not name or not name.strip():
            return
        name = name.strip()
        if name in self.cfg["sets"]:
            messagebox.showwarning("重复", "已经存在同名套装：%s" % name)
            return
        self.cfg["sets"].append(name)
        self.cfg.setdefault("set_pieces", {})[name] = default_pieces(name)
        self._sets_changed("已新增套装「%s」（下标 %d），部件名先按占位补齐，可用「编辑部件名」改。"
                           % (name, len(self.cfg["sets"]) - 1))

    def _rename_set(self):
        sel = self.sets_tree.selection()
        if not sel:
            return
        i = int(sel[0])
        old = self.cfg["sets"][i]
        name = simpledialog.askstring("重命名套装", "新的套装名称：", initialvalue=old, parent=self)
        if name is None or not name.strip() or name.strip() == old:
            return
        name = name.strip()
        if name in self.cfg["sets"]:
            messagebox.showwarning("重复", "已经存在同名套装：%s" % name)
            return
        self.cfg["sets"][i] = name
        # 评分规则跟着改名走
        rule = self.cfg["scoring"]["sets"].pop(old, None)
        if rule is not None:
            self.cfg["scoring"]["sets"][name] = rule
        # 部件名也跟着改名走（占位名里的套装前缀同步换掉）
        pieces = self.cfg.setdefault("set_pieces", {})
        got = pieces.pop(old, None)
        if got is None:
            got = default_pieces(old)
        pieces[name] = [(n.replace(old, name, 1) if n.startswith(old + "·") else n) for n in got]
        for dname, drops in (self.cfg.get("domains") or {}).items():
            self.cfg["domains"][dname] = [name if d == old else d for d in drops]
        self._sets_changed("套装「%s」已改名为「%s」，评分规则、部件名与秘境掉落同步更新。" % (old, name))

    def _del_set(self):
        sel = self.sets_tree.selection()
        if not sel:
            return
        i = int(sel[0])
        name = self.cfg["sets"][i]
        if len(self.cfg["sets"]) <= 1:
            messagebox.showwarning("不能删除", "至少要保留一个套装。")
            return
        used = sum(1 for a in self.inv.items if a.set_id == i)
        extra = ""
        if used:
            extra = ("\n\n注意：存档里有 %d 件圣遗物的套装下标等于 %d，"
                     "删除后它们会整体前移一位、显示成别的套装。" % (used, i))
        if not messagebox.askyesno("确认删除", "删除套装「%s」？%s" % (name, extra)):
            return
        del self.cfg["sets"][i]
        self.cfg["scoring"]["sets"].pop(name, None)
        self.cfg.get("set_pieces", {}).pop(name, None)
        for dname, drops in (self.cfg.get("domains") or {}).items():
            self.cfg["domains"][dname] = [d for d in drops if d != name]
        self._sets_changed("已删除套装「%s」。" % name)

    def _move_set(self, delta: int):
        sel = self.sets_tree.selection()
        if not sel:
            return
        i = int(sel[0])
        j = i + delta
        if not (0 <= j < len(self.cfg["sets"])):
            return
        sets = self.cfg["sets"]
        sets[i], sets[j] = sets[j], sets[i]
        self._replace_config(self.cfg)
        self.sets_tree.selection_set(str(j))
        self.sets_tree.see(str(j))
        self.set_status("已调整套装顺序（下标 %d ↔ %d）。注意已存档圣遗物的套装名会跟着变。"
                        % (i, j))

    def _reset_sets(self):
        from . import dataset
        if not messagebox.askyesno("确认", "恢复默认的 %d 个套装？当前的套装表会被覆盖。"
                                   % len(dataset.SET_NAMES)):
            return
        self.cfg["sets"] = list(dataset.SET_NAMES)
        self.cfg["set_pieces"] = {
            s: [(str((dataset.SET_PIECES.get(s) or default_pieces(s))[k]).strip()
                 or default_pieces(s)[k]) for k in range(len(self.cfg["slots"]))]
            for s in self.cfg["sets"]}
        self._sets_changed("已恢复默认套装表（%d 个）与它们的部件名。" % len(dataset.SET_NAMES))

    def _apply_pieces(self, name: str, values):
        """把「套装 name 的 5 个部件名」写回配置（空串回落成占位名）。"""
        ph = default_pieces(name)
        vals = list(values)
        self.cfg.setdefault("set_pieces", {})[name] = [
            (str(vals[k]).strip() if k < len(vals) else "") or ph[k] for k in range(len(ph))]
        self._sets_changed("套装「%s」的部件名已更新。" % name)

    def _edit_pieces(self):
        """编辑某个套装里 5 个部位各自的「圣遗物名称」（部件名）。"""
        sel = self.sets_tree.selection()
        if not sel:
            messagebox.showinfo("提示", "请先在左边的套装表里选一个套装。")
            return
        name = self.cfg["sets"][int(sel[0])]
        slots = list(self.cfg.get("slots") or [])
        cur = list((self.cfg.get("set_pieces") or {}).get(name) or default_pieces(name))
        while len(cur) < len(slots):
            cur.append("")

        win = tk.Toplevel(self)
        win.title("编辑部件名 · %s" % name)
        win.transient(self)
        body = ttk.Frame(win, padding=10)
        body.pack(fill="both", expand=True)
        ttk.Label(body, justify="left", foreground="#555", text=(
            "「%s」这一套里 5 个部位各自的圣遗物名称。\n"
            "留空会自动回落到「套装名·部位名」。" % name)).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
        vars_ = []
        for k, sname in enumerate(slots):
            ttk.Label(body, text=sname).grid(row=k + 1, column=0, sticky="w", padx=(0, 10), pady=3)
            v = tk.StringVar(value=cur[k] if k < len(cur) else "")
            vars_.append(v)
            ttk.Entry(body, textvariable=v, width=40).grid(row=k + 1, column=1, sticky="ew", pady=3)
        body.columnconfigure(1, weight=1)

        bar = ttk.Frame(body)
        bar.grid(row=len(slots) + 1, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        ttk.Button(bar, text="填入占位名", command=lambda: [
            v.set("%s·%s" % (name, slots[k])) for k, v in enumerate(vars_)]).pack(side="left")
        ttk.Button(bar, text="取消", command=win.destroy).pack(side="right")
        ttk.Button(bar, text="确定",
                   command=lambda: (self._apply_pieces(name, [v.get() for v in vars_]),
                                    win.destroy())).pack(side="right", padx=6)
        win.bind("<Escape>", lambda _e: win.destroy())
        return win

    def _add_domain(self):
        name = simpledialog.askstring("新增秘境", "秘境名称：", parent=self)
        if not name or not name.strip():
            return
        name = name.strip()
        if name in (self.cfg.get("domains") or {}):
            messagebox.showwarning("重复", "已经存在同名秘境：%s" % name)
            return
        self.cfg.setdefault("domains", {})[name] = []
        self._sets_changed("已新增秘境「%s」，请再用「编辑掉落」挑套装。" % name)

    def _rename_domain(self):
        sel = self.dom_tree.selection()
        if not sel:
            return
        old = sel[0]
        name = simpledialog.askstring("重命名秘境", "新的秘境名称：", initialvalue=old, parent=self)
        if name is None or not name.strip() or name.strip() == old:
            return
        name = name.strip()
        if name in self.cfg["domains"]:
            messagebox.showwarning("重复", "已经存在同名秘境：%s" % name)
            return
        drops = self.cfg["domains"].pop(old)
        self.cfg["domains"][name] = drops
        self._sets_changed("秘境「%s」已改名为「%s」。" % (old, name))

    def _edit_domain(self):
        sel = self.dom_tree.selection()
        if not sel:
            return
        name = sel[0]
        cur = "，".join(self.cfg["domains"].get(name) or [])
        text = simpledialog.askstring(
            "编辑掉落", "「%s」掉落的套装（多个用逗号分隔，留空表示从全部套装随机）：" % name,
            initialvalue=cur, parent=self)
        if text is None:
            return
        picked: list[str] = []
        unknown: list[str] = []
        for tok in re.split(r"[，,;；\s]+", text):
            tok = tok.strip()
            if not tok:
                continue
            if tok not in self.cfg["sets"]:
                unknown.append(tok)
            elif tok not in picked:
                picked.append(tok)
        if unknown:
            messagebox.showwarning("有未登记的套装", "以下名字不在套装表里，已忽略：\n%s" % "、".join(unknown))
        self.cfg["domains"][name] = picked
        self._sets_changed("秘境「%s」的掉落已更新为 %d 个套装。" % (name, len(picked)))

    def _del_domain(self):
        sel = self.dom_tree.selection()
        if not sel:
            return
        name = sel[0]
        if not messagebox.askyesno("确认删除", "删除秘境「%s」？" % name):
            return
        self.cfg["domains"].pop(name, None)
        self._sets_changed("已删除秘境「%s」。" % name)

    def _reset_domains(self):
        from . import dataset
        if not messagebox.askyesno("确认", "恢复默认的秘境掉落表？"):
            return
        self.cfg["domains"] = copy.deepcopy(dataset.DOMAINS)
        self._sets_changed("已恢复默认秘境表。")

    # ------------------------------------------------------------------
    def _build_custom_layout(self, nb):
        page = ttk.Frame(nb, padding=8)
        nb.add(page, text="向量布局")
        ttk.Label(page, justify="left", foreground="#555", text=(
            "圣遗物向量的维度定义。可以调整顺序（即调整向量的排布）与显示名称/说明；"
            "「用途(键)」列是程序内部标识，不可更改。共 20 维。"
        )).pack(anchor="w")
        self.layout_tree = ttk.Treeview(page, columns=("i", "key", "label", "kind", "desc"),
                                        show="headings", height=21)
        for c, h, w in (("i", "序号", 50), ("key", "用途(键)", 140), ("label", "显示名称", 170),
                        ("kind", "类型", 70), ("desc", "说明", 560)):
            self.layout_tree.heading(c, text=h)
            self.layout_tree.column(c, width=w, anchor="w", stretch=(c == "desc"))
        self.layout_tree.pack(fill="both", expand=True, pady=6)
        bar = ttk.Frame(page)
        bar.pack(fill="x")
        ttk.Button(bar, text="上移", command=lambda: self._move_layout(-1)).pack(side="left")
        ttk.Button(bar, text="下移", command=lambda: self._move_layout(1)).pack(side="left", padx=6)
        ttk.Button(bar, text="修改名称/说明", command=self._edit_layout_item).pack(side="left", padx=6)
        ttk.Button(bar, text="恢复默认布局", command=self._reset_layout).pack(side="left", padx=6)

    def _fill_layout_tree(self):
        self.layout_tree.delete(*self.layout_tree.get_children())
        for i, d in enumerate(self.cfg["vector_layout"]):
            self.layout_tree.insert("", "end", iid=str(i),
                                    values=(i + 1, d["key"], d["label"], d["kind"], d.get("desc", "")))

    def _move_layout(self, delta: int):
        sel = self.layout_tree.selection()
        if not sel:
            return
        i = int(sel[0])
        j = i + delta
        lay = self.cfg["vector_layout"]
        if not (0 <= j < len(lay)):
            return
        lay[i], lay[j] = lay[j], lay[i]
        self._replace_config(self.cfg)
        self._fill_layout_tree()
        self.layout_tree.selection_set(str(j))

    def _edit_layout_item(self):
        sel = self.layout_tree.selection()
        if not sel:
            return
        i = int(sel[0])
        d = self.cfg["vector_layout"][i]
        label = simpledialog.askstring("显示名称", "新的显示名称：", initialvalue=d["label"], parent=self)
        if label is None:
            return
        desc = simpledialog.askstring("说明", "新的说明：", initialvalue=d.get("desc", ""), parent=self)
        if desc is None:
            desc = d.get("desc", "")
        d["label"] = label
        d["desc"] = desc
        self._replace_config(self.cfg)
        self._fill_layout_tree()

    def _reset_layout(self):
        if messagebox.askyesno("确认", "恢复默认的 20 维向量布局？"):
            self.cfg["vector_layout"] = copy.deepcopy(default_config()["vector_layout"])
            self._replace_config(self.cfg)
            self._fill_layout_tree()

    # ------------------------------------------------------------------
    PARAM_FIELDS = [
        ("主词条公式 · 基础系数", "main_stat_formula.base", "float"),
        ("主词条公式 · 成长系数", "main_stat_formula.span", "float"),
        ("圣遗物最高等级", "main_stat_formula.max_level", "int"),
        ("副词条除数 · 一般词条（数值 = 最大值 × 总成长 ÷ 除数）", "substat_divisor", "float"),
        ("副词条除数 · 攻击力/生命值/防御力", "flat_substat_divisor", "float"),
        ("使用上一条除数的小词条 key（逗号分隔）", "flat_substat_keys", "strlist"),
        ("初始 3 词条权重", "init_sub_weights.3", "float"),
        ("初始 4 词条权重", "init_sub_weights.4", "float"),
        ("初始成长档位（逗号分隔）", "init_growth_tiers", "floatlist"),
        ("初始成长模式 tiers/uniform", "init_growth_mode", "str"),
        ("升级成长档位（逗号分隔）", "upgrade_growth_tiers", "floatlist"),
        ("升级成长模式 tiers/uniform", "upgrade_growth_mode", "str"),
        ("部位概率（5 个，逗号分隔，花/羽/沙/杯/冠）", "slot_prob", "floatlist"),
        ("强化判定间隔（每 N 级）", "enhance_interval", "int"),
        ("祝圣之霜消耗（花,羽,沙,杯,冠）", "elixir.cost", "slotint"),
        ("祝圣之霜 · 初始副词条数（0=跟随获取分布）", "elixir.force_initial_sub_count", "int"),
        ("祝圣之霜 · 保底命中次数", "elixir.min_total_hits", "int"),
        ("启圣之尘消耗（花,羽,沙,杯,冠）", "dust.cost", "slotint"),
        ("启圣之尘 · 3 次保底阈值（逗号分隔）", "dust.hit3_thresholds", "intlist"),
        ("启圣之尘 · 4 次保底阈值", "dust.hit4_threshold", "int"),
        ("启圣之尘 · 3 次保底命中数", "dust.hit3_min_total", "int"),
        ("启圣之尘 · 4 次保底命中数", "dust.hit4_min_total", "int"),
        ("启圣之尘 · 触发 4 次后把进度减去 18(true/false)", "dust.reset_on_hit4", "bool"),
        ("启圣之尘 · 每次的基础保底命中次数（默认 2）", "dust.min_total_hits", "int"),
        ("启圣之尘 · 重塑后弹窗选择前后结果(true/false)", "dust.ask_before_apply", "bool"),
        ("评分模式 growth/value", "score_mode", "str"),
    ]

    def _build_custom_params(self, nb):
        page = ttk.Frame(nb, padding=8)
        nb.add(page, text="参数")
        sf = ScrollFrame(page)
        sf.pack(fill="both", expand=True)
        body = sf.body
        self.param_vars: dict[str, tuple] = {}
        ttk.Label(body, foreground="#555", text="数值规则 / 概率 / 消耗参数。修改后点「应用参数」再「保存配置」。"
                  ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))
        # --- 三个全局评分开关（勾一下立即生效并落盘，不用点「应用参数」）---
        sw = ttk.LabelFrame(body, text="评分开关（全局）", padding=8)
        sw.grid(row=1, column=0, columnspan=2, sticky="we", pady=(0, 10))
        self.score_sw: dict[str, tk.BooleanVar] = {}
        for i, (key, text) in enumerate((
                ("score_enabled", "允许圣遗物评分（关闭后所有评分都按 0 显示，评分模式显示为「关闭评分」）"),
                ("score_hl_main", "允许主词条高亮（★ 只影响显示，不影响得分）"),
                ("score_hl_sub", "允许副词条高亮（★ 只影响显示，不影响得分）"))):
            var = tk.BooleanVar(value=bool(self.cfg.get(key, True)))
            ttk.Checkbutton(sw, text=text, variable=var,
                            command=self._score_switch_changed).grid(row=i, column=0, sticky="w", pady=2)
            self.score_sw[key] = var
        # --- 显示开关（同样勾一下立即生效并落盘）---
        disp = ttk.LabelFrame(body, text="显示设置（全局）", padding=8)
        disp.grid(row=2, column=0, columnspan=2, sticky="we", pady=(0, 10))
        self.show_inactive = tk.BooleanVar(
            value=bool(self.cfg.get("show_inactive_subs", False)))
        ttk.Checkbutton(
            disp,
            text="允许显示未激活词条",
            variable=self.show_inactive,
            command=self._show_inactive_changed).grid(row=0, column=0, sticky="w", pady=2)
        ttk.Label(
            disp, foreground="#555", justify="left", wraplength=740,
            text="初始只有 3 条副词条的圣遗物，会多显示一条灰色的「未激活」词条：它不参与评分，"
                 "但命中评分规则时仍会 ★ 高亮。关掉这个开关时，列表里带未激活词条的圣遗物"
                 "会自动强化到 +4，把那条词条激活。").grid(row=1, column=0, sticky="w", pady=(2, 0))
        for r, (label, path, kind) in enumerate(self.PARAM_FIELDS, start=3):
            ttk.Label(body, text=label).grid(row=r, column=0, sticky="w", pady=2, padx=(0, 8))
            var = tk.StringVar()
            ent = ttk.Entry(body, textvariable=var, width=44)
            ent.grid(row=r, column=1, sticky="w", pady=2)
            self.param_vars[path] = (var, kind)
        n = len(self.PARAM_FIELDS) + 3
        bar = ttk.Frame(body)
        bar.grid(row=n, column=0, columnspan=2, sticky="w", pady=10)
        ttk.Button(bar, text="应用参数", command=self._apply_params).pack(side="left")
        ttk.Button(bar, text="重新载入", command=self._fill_params).pack(side="left", padx=6)
        self._fill_params()

    def _sync_score_switches(self):
        """把配置里的三个评分开关同步到勾选框（不触发 command）。"""
        for key, var in getattr(self, "score_sw", {}).items():
            var.set(bool(self.cfg.get(key, True)))

    def _score_switch_changed(self):
        for key, var in self.score_sw.items():
            self.cfg[key] = bool(var.get())
        try:
            save_config(self.cfg)
        except Exception as exc:                     # noqa: BLE001
            messagebox.showerror("保存失败", "评分开关没能写进配置文件：%s" % exc)
        self.refresh_all()
        state = "开启" if self.cfg.get("score_enabled", True) else "关闭"
        self.set_status("评分开关已更新：评分%s，主词条高亮%s，副词条高亮%s"
                        % (state,
                           "开启" if self.cfg.get("score_hl_main", True) else "关闭",
                           "开启" if self.cfg.get("score_hl_sub", True) else "关闭"))

    def _fill_params(self):
        for path, (var, kind) in self.param_vars.items():
            var.set(_fmt_path(self.cfg, path, kind))
        self._sync_score_switches()
        self._sync_display_switch()

    def _sync_display_switch(self):
        var = getattr(self, "show_inactive", None)
        if var is not None:
            var.set(bool(self.cfg.get("show_inactive_subs", False)))

    def _show_inactive_changed(self):
        """开/关「显示未激活词条」。

        打开：把老存档里还没预生成第 4 条的圣遗物补上（否则没东西可显示）；
        关闭：列表里所有带未激活词条的圣遗物自动强化到 +4，把那条词条激活。
        """
        want = bool(self.show_inactive.get())
        self.cfg["show_inactive_subs"] = want
        batch = list(getattr(self, "_last_batch", []))
        added = 0
        raised = 0
        for art in list(self.inv.items) + batch:
            if want:
                # 老存档 / 手改过的向量可能还没预生成第 4 条，这里补齐
                added += engine.ensure_pending(art, self.cfg, self.table, self.rng)
                continue
            if not art.has_pending():
                continue
            if art.level < 4:
                engine.advance(art, 4, self.cfg, self.table, self.rng)
            engine.activate_pending(art)
            art.history.append("→ 关闭「显示未激活词条」：自动强化至 +%d 以激活第 %d 条副词条"
                               % (art.level, art.cur_sub_count))
            raised += 1
        try:
            save_config(self.cfg)
        except Exception as exc:                     # noqa: BLE001
            messagebox.showerror("保存失败", "显示开关没能写进配置文件：%s" % exc)
        self.refresh_all()
        if batch:
            self._render_batch()        # 获取结果里那批待定圣遗物也要跟着变
        if want:
            self.set_status("已开启「显示未激活词条」：灰色词条不参与评分，但命中时仍会 ★ 高亮"
                            + ("（已为 %d 件补齐预生成词条）" % added if added else ""))
        else:
            self.set_status("已关闭「显示未激活词条」"
                            + ("；%d 件带未激活词条的圣遗物已自动强化到 +4" % raised if raised else ""))
        if not want and raised:
            self._save_game(silent=True)

    def _apply_params(self):
        cfg = copy.deepcopy(self.cfg)
        errs = []
        for path, (var, kind) in self.param_vars.items():
            try:
                _set_path(cfg, path, var.get().strip(), kind)
            except Exception as exc:                        # noqa: BLE001
                errs.append("%s：%s" % (path, exc))
        if errs:
            messagebox.showerror("参数有误", "\n".join(errs))
            return
        cfg = normalize(cfg)
        problems = validate(cfg)
        if problems:
            messagebox.showerror("参数有误", "· " + "\n· ".join(problems))
            return
        self._replace_config(cfg)
        self._fill_params()
        self.set_status("参数已应用。")

    # ==================================================================
    # 说明
    # ==================================================================
    def _build_help(self):
        bar = ttk.Frame(self.tab_help, padding=(0, 6, 0, 0))
        bar.pack(side="bottom", fill="x")
        ttk.Separator(self.tab_help, orient="horizontal").pack(side="bottom", fill="x")
        self.help_wipe_btn = ttk.Button(bar, text="清空存档（恢复出厂设置）",
                                        command=self._wipe_save)
        self.help_wipe_btn.pack(side="left")
        self.help_wipe_hint = ttk.Label(
            bar, foreground="#a60",
            text="删除全部圣遗物、启圣之尘/祝圣之霜计数与圣言解名进度归零、"
                 "评分规则与所有设置回到初始值，并立刻覆盖存档文件。")
        self.help_wipe_hint.pack(side="left", padx=10)
        self.help_view = ScrolledText(self.tab_help, wrap="word", font=("Microsoft YaHei UI", 10))
        self.help_view.pack(side="top", fill="both", expand=True)

    def _fill_help(self):
        lay = self.cfg["vector_layout"]
        lines = []
        lines.append("【圣遗物向量（%d 维）】" % len(lay))
        for i, d in enumerate(lay):
            lines.append("  %2d. %-14s %-6s %s" % (i + 1, d["label"], d["kind"], d.get("desc", "")))
        lines.append("")
        lines.append("【数值表】")
        lines.append("  行号即主词条 id。列：名称 最大值 沙权重 头权重 杯权重 副词条权重 命中权重")
        for s in self.cfg["stats"]:
            lines.append("  %2d. %-16s max=%-8s 沙=%-4s 头=%-4s 杯=%-5s 副词条=%-3s 命中=%s" % (
                s["id"], s["name"], _n(s["max"]), _n(s.get("w_sand", 0)), _n(s.get("w_head", 0)),
                _n(s.get("w_cup", 0)), _n(s.get("w_sub", 0)), _n(s.get("w_hit", 0))))
        lines.append("")
        lines.append("【套装与秘境（可自定义，共 %d 个套装 / %d 个秘境）】"
                     % (len(self.cfg.get("sets", [])), len(self.cfg.get("domains") or {})))
        for i, name in enumerate(self.cfg.get("sets", [])):
            drops = [k for k, v in (self.cfg.get("domains") or {}).items() if name in v]
            lines.append("  %2d. %-16s 出自：%s" % (i, name, "、".join(drops) or "（无秘境掉落）"))
            pieces = (self.cfg.get("set_pieces") or {}).get(name) or []
            if pieces:
                lines.append("      部件名：%s" % " / ".join(str(p) for p in pieces))
        for dname, drops in (self.cfg.get("domains") or {}).items():
            lines.append("  秘境 %-12s → %s" % (dname, "、".join(drops) or "（空，按全部套装随机）"))
        lines.append("")
        lines.append("【规则要点】")
        lines.append("  1. 获取：选定副本 → 在副本掉落的套装里随机一个 → 五个部位等概率随机 → 主词条按沙/头/杯权重随机")
        lines.append("     → 初始副词条数 3:4 = %s:%s → 按副词条权重不重复抽取 → 每条随机一个初始成长档位 %s" % (
            _n(self.cfg["init_sub_weights"].get("3")), _n(self.cfg["init_sub_weights"].get("4")),
            self.cfg["init_growth_tiers"]))
        lines.append("     获取到的圣遗物先只显示在结果里，点「加入圣遗物列表」按钮才进列表；再点「获取」会丢弃上一批。加入后「圣遗物强化」页会跟着切到最后一件，日志里会打一条分界线。")
        lines.append("     第 4 条副词条在获取时就已预生成（名字与初始成长都定好，只是没激活）：默认显示「—」，"
                     "打开「自定义 → 参数 → 显示设置」里的「允许显示未激活词条」后显示成灰色的"
                     "「[未激活 总=初+升] 词条名 +数值」，不计分但命中规则时仍会 ★ 高亮。"
                     "打开时会先给背包里（以及获取结果里待定的那批）没预生成第 4 条的圣遗物补上；"
                     "关掉时，背包与获取结果里带未激活词条的圣遗物都会自动强化到 +4 把它激活。")
        lines.append("     设置区最下面显示「累计获取：%d 件」：每获取一件 +1（丢弃的也算），随存档保存，按「说明」页的「清空存档」归零。" % int(getattr(self.state, "get_count", 0)))
        lines.append("  2. 主词条数值 = 最大值 × (%s + %s ÷ %s × 等级)" % (
            _n(self.cfg["main_stat_formula"]["base"]), _n(self.cfg["main_stat_formula"]["span"]),
            _n(self.cfg["main_stat_formula"]["max_level"])))
        lines.append("  3. 副词条数值 = 该词条（作为主词条时的）最大值 × 总成长 ÷ 除数，总成长 = 初始成长 + 升级成长")
        lines.append("     除数：攻击力 / 生命值 / 防御力 = %s，其余词条 = %s" % (
            _n(self.cfg.get("flat_substat_divisor", 16.0)),
            _n(self.cfg.get("substat_divisor", 8.0))))
        lines.append("  4. 强化：每 %s 级判定一次。未满 4 条则抽一条新副词条（不与已有重复）；已满 4 条则按命中权重"
                     "选一条 +%s。"
                     % (_n(self.cfg.get("enhance_interval", 4)), self.cfg["upgrade_growth_tiers"]))
        lines.append("  5. 评分 = Σ(主词条得分 + 副词条得分)，规则按套装配置，可自定义。")
        lines.append("     规则格式：套装名：词条名 主词条高亮 主词条得分系数 副词条权重")
        lines.append("     例：来歆余响：暴击伤害 1 1.5 7.775 → 主词条每级 1.5 分（+20 = 30 分）且高亮，"
                     "副词条每条权重 7.775。")
        lines.append("     主词条得分 = 等级 × 得分系数；副词条得分 = 副词条权重 × 总成长"
                     "（按实际数值模式则乘数值）。")
        lines.append("     第 2 个数 > 0 才把该词条作为主词条时加 ★ 高亮；写 0 只是不高亮，得分照算。"
                     "默认模板是 暴击率 1 1.5 7.775 / 暴击伤害 1 1.5 7.775 / 各元素伤害加成 1 0 0，"
                     "已经写进每个套装，直接改就行（旧版五条模板会自动迁移）。")
        lines.append("     组名「各元素伤害加成」会展开成 7 个元素伤害加成词条（权重相同），规则里写一行就够。")
        lines.append("     全局开关在「自定义 → 参数」：允许圣遗物评分（关掉后所有评分按 0 显示、"
                     "右下角模式变「关闭评分」）、允许主词条高亮、允许副词条高亮（后两颗只影响 ★，不改分数），"
                     "勾一下立刻生效并落盘。")
        lines.append("     有评分权重（或开了高亮）的词条会被标出来：文字里加 ★ 并变蓝加粗；"
                     "列表的「主词条 / 副词条」列、导出 CSV 也带 ★。")
        lines.append("     各页都能看到评分：列表页底部有「评分明细」+ 最高分/平均分，"
                     "强化页顶部显示当前评分、日志里写每级评分变化，"
                     "祝圣之霜页会列出所挑词条的权重、生成后给出总分与命中的词条。")
        lines.append("  6. 祝圣之霜：定义套装/主词条/两条副词条，其余按规则生成，定义的两条合计至少命中 %s 次；"
                     "初始副词条数与获取新圣遗物同一套分布。" % _n(self.cfg["elixir"]["min_total_hits"]))
        lines.append("  7. 启圣之尘：满级后可选择两条副词条重新强化；消耗计入圣言解名进度。"
                     "若这件是祝圣之霜定义件，则只能重新强化当初定义的那两条副词条（锁定不可改）。"
                     "每次至少保底 %s 次命中；只有本次消耗把进度推过阈值的那一次才额外提高保底："
                     "首次达到 %s → 至少 %s 次；首次达到 %s → 至少 %s 次并减去 %s。"
                     "重塑后会弹窗让你选采用重塑前还是重塑后的结果。"
                     "圣言解名进度可以在界面上直接改成任意点数（不影响累计消耗数）。"
                     % (_n(self.cfg["dust"].get("min_total_hits", 2)),
                        " / ".join(_n(int(x)) for x in self.cfg["dust"]["hit3_thresholds"]),
                        _n(self.cfg["dust"]["hit3_min_total"]),
                        _n(self.cfg["dust"]["hit4_threshold"]), _n(self.cfg["dust"]["hit4_min_total"]),
                        _n(self.cfg["dust"]["hit4_threshold"])))
        lines.append("  8. 圣遗物列表：ID 每次变更都重排为紧凑的 1…N；选中后可在右键菜单里「复制选中」，"
                     "新建一整套向量与历史都相同的副本（只在历史末尾记一条「复制自 #原编号」）。")
        lines.append("")
        lines.append("【文件】")
        lines.append("  配置：%s" % CONFIG_PATH)
        lines.append("  存档：%s" % DATA_PATH)
        lines.append("")
        lines.append("【清空存档】")
        lines.append("  本页左下角的「清空存档（恢复出厂设置）」按钮会一次性：删除全部圣遗物、"
                     "把祝圣之霜/启圣之尘累计消耗与圣言解名进度归零、"
                     "评分规则与全部设置回到初始值，并立刻覆盖上面两个文件。")
        lines.append("  点了会连问两次确认，确认后不可撤销（想留底可以先「文件 → 导出配置」和导出 CSV）。")
        self._set_text(self.help_view, "\n".join(lines))

    # ==================================================================
    # 选中管理 / 刷新
    # ==================================================================
    def current_artifact(self) -> Artifact | None:
        i = self.sel_combo.current()
        if 0 <= i < len(self._sel_items):
            return self._sel_items[i]
        return None

    def select_artifact(self, art: Artifact):
        # 记住对象本身而不是编号：列表变更时会重排编号，编号靠不住
        self._pending_select = art
        self.refresh_selection()
        self.on_select()            # 让「强化圣遗物」页也跟着换成这件

    def _set_selection(self, art: Artifact):
        try:
            i = self._sel_items.index(art)
        except ValueError:
            self.refresh_selection()
            try:
                i = self._sel_items.index(art)
            except ValueError:
                return
        self.sel_combo.current(i)
        self.on_select()

    def refresh_selection(self):
        keep = getattr(self, "_pending_select", None)
        if keep is None:
            keep = self.current_artifact()
        self._sel_items = list(self.inv.items)
        vals = ["#%d %s·%s（%s） %s +%d ｜ %s" % (
            a.uid, a.set_name, a.slot_name, a.piece_name, a.main_name, a.level, a.summary())
            for a in self._sel_items]
        self.sel_combo.configure(values=vals)
        idx = 0
        if keep is not None:
            for i, a in enumerate(self._sel_items):
                if a is keep:
                    idx = i
                    break
        if vals:
            self.sel_combo.current(idx)
        else:
            self.sel_var.set("")
        self._pending_select = None

    def on_select(self):
        art = self.current_artifact()
        if art is None:
            self._set_rich(self.enh_view, [("dim", "（还没有选中圣遗物）\n")])
            self.enh_score_label.configure(text="评分：—（未选中圣遗物）")
            self._refresh_list_detail(None)
        else:
            self._set_rich(self.enh_view, self._artifact_entries(
                art, ["", "向量：%s" % art.vector_text()]))
            sc = scoring.score_artifact(art, self.cfg, self.table)
            if sc.get("enabled", True):
                self.enh_score_label.configure(
                    text="当前评分 %.3f　有效词条数 %.2f　命中 %d 条"
                         % (sc["total"], sc["useful_rolls"],
                            (1 if sc["main_hl"] else 0) + sum(1 for h in sc["sub_hits"] if h)))
            else:
                self.enh_score_label.configure(
                    text="评分已关闭（自定义 → 参数 里可以重新打开）")
            self._refresh_list_detail(art)
        self.refresh_dust_choices()
        self.refresh_score_detail()

    def _refresh_list_detail(self, art=None):
        """列表页底部的评分明细。"""
        w = getattr(self, "list_score", None)
        if w is None:
            return
        if art is None:
            art = self.current_artifact()
        if art is None:
            self._set_rich(w, [("dim", "（未选择圣遗物）\n")])
            return
        self._set_rich(w, self._detail_entries(art))

    def refresh_all(self):
        self.refresh_selection()
        self.on_select()
        self.refresh_list()
        self._fill_table_text()
        self._fill_sets_tree()
        self._fill_layout_tree()
        self._fill_help()
        self._fill_params()
        if self.cfg.get("domains"):
            self.get_domain_combo.configure(values=[ANY_DOMAIN] + list(self.cfg["domains"].keys()))
            if self.get_domain.get() not in list(self.cfg["domains"].keys()) + [ANY_DOMAIN]:
                self.get_domain.set(ANY_DOMAIN)
            self._update_domain_info()
        self.el_set_combo.configure(values=list(self.cfg["sets"]))
        if self.el_set.get() not in self.cfg["sets"] and self.cfg["sets"]:
            self.el_set.set(self.cfg["sets"][0])
        self._elixir_slot_changed()
        # 评分页的两个控件跟着配置走（参数页 / 导入配置改了也要同步）
        if hasattr(self, "sc_mode"):
            self.sc_mode.set(self.cfg.get("score_mode", "growth"))
        self._refresh_get_count()
        self._update_status()

    def _update_status(self):
        self.status_var.set(
            "圣遗物：%d 件　｜　累计获取：%d 件　｜　累计消耗祝圣之霜：%d 个　｜　"
            "累计消耗启圣之尘：%d 个　｜　圣言解名进度：%d　｜　评分模式：%s"
            % (len(self.inv.items), int(getattr(self.state, "get_count", 0)),
               self.state.elixir_used, self.state.dust_used,
               self.state.dust_progress, self._mode_text()))

    def set_status(self, text: str):
        self.status_var.set(text)
        self.after(6000, self._update_status)

    # ------------------------------------------------------------ 配置替换
    def _replace_config(self, cfg: dict):
        self.cfg = normalize(cfg)
        self.table = StatTable(self.cfg)
        for a in self.inv.items:
            a.cfg = self.cfg
            a.table = self.table
            a._rebuild()
        self.refresh_all()

    def _save_config_click(self):
        try:
            save_config(self.cfg)
            self._save_game(silent=True)
            messagebox.showinfo("完成", "配置与进度已保存到\n%s\n%s" % (CONFIG_PATH, DATA_PATH))
        except Exception as exc:                            # noqa: BLE001
            messagebox.showerror("保存失败", str(exc))

    def _reset_config(self):
        if not messagebox.askyesno("确认", "恢复全部默认配置？自定义的数值表、向量布局和评分规则都会丢失。"):
            return
        idx = self.cfg.get("score_mode", "growth")
        cfg = default_config()
        cfg["score_mode"] = idx
        self._replace_config(cfg)
        self.set_status("已恢复默认配置。")

    def _wipe_save(self):
        """清空存档：删掉全部圣遗物、计数归零、配置恢复出厂，并立刻写盘。"""
        if not messagebox.askyesno(
                "清空存档",
                "要清空存档、恢复出厂设置吗？\n\n"
                "· 删除全部 %d 件圣遗物\n"
                "· 获取计数、祝圣之霜 / 启圣之尘 累计消耗、圣言解名进度归零\n"
                "· 评分规则恢复内置默认模板\n"
                "· 数值表、向量布局、套装、秘境、部件名、全部参数回到初始值\n\n"
                "清空后会立刻覆盖：\n%s\n%s"
                % (len(self.inv.items), DATA_PATH, CONFIG_PATH)):
            return
        if not messagebox.askyesno("再确认一次", "真的清空吗？此操作不可撤销。"):
            return
        self.inv.clear()
        self.state = AppState()
        self._last_batch = []
        self._refresh_keep_btn()
        self._replace_config(default_config())      # 内部会 normalize + refresh_all
        for w in (self.get_out, self.enh_log, self.list_score, self.el_out, self.dust_out):
            try:
                self._set_text(w, "")
            except Exception:                           # noqa: BLE001
                pass
        self.refresh_dust_choices()                     # 进度的滑块/标签/输入框归零
        self._save_game(silent=True)
        self.set_status("已清空存档：圣遗物与计数清零，配置恢复初始值，并已写入存档文件。")
        messagebox.showinfo("已清空",
                            "存档已清空并保存。\n\n圣遗物 0 件，获取计数与"
                            "祝圣之霜 / 启圣之尘计数、圣言解名进度归零，全部设置恢复初始值。")

    def _reload_config(self):
        self._replace_config(load_config())
        self.set_status("已重新载入 config.json")

    def _export_config(self):
        path = filedialog.asksaveasfilename(defaultextension=".json", initialfile="config.json",
                                            filetypes=[("JSON", "*.json")])
        if not path:
            return
        save_config(self.cfg, path)
        self.set_status("配置已导出到 %s" % path)

    def _import_config(self):
        path = filedialog.askopenfilename(filetypes=[("JSON", "*.json"), ("全部文件", "*.*")])
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8-sig") as fp:
                user = json.load(fp)
        except Exception as exc:                            # noqa: BLE001
            messagebox.showerror("导入失败", str(exc))
            return
        from .config import _merge
        merged = normalize(_merge(default_config(), user))
        problems = validate(merged)
        if problems and not messagebox.askyesno(
                "配置有问题", "· " + "\n· ".join(problems) + "\n\n仍然导入吗？"):
            return
        self._replace_config(merged)
        self.set_status("已导入 %s" % path)

    # ------------------------------------------------------------ 存档
    def _save_game(self, silent: bool = False):
        try:
            with open(DATA_PATH, "w", encoding="utf-8") as fp:
                json.dump({"state": self.state.to_dict(), "inventory": self.inv.to_dict(),
                           "config": self.cfg}, fp, ensure_ascii=False, indent=2)
            save_config(self.cfg)
            if not silent:
                self.set_status("进度已保存到 %s" % DATA_PATH)
        except Exception as exc:                            # noqa: BLE001
            if not silent:
                messagebox.showerror("保存失败", str(exc))

    def _load_game(self, silent: bool = False):
        if not os.path.exists(DATA_PATH):
            return
        try:
            with open(DATA_PATH, "r", encoding="utf-8-sig") as fp:
                d = json.load(fp)
        except Exception as exc:                            # noqa: BLE001
            if not silent:
                messagebox.showerror("读取失败", str(exc))
            return
        if d.get("config"):
            from .config import _merge
            self.cfg = normalize(_merge(default_config(), d["config"]))
            self.table = StatTable(self.cfg)
            problems = validate(self.cfg)
            if problems:
                print("[启动] 配置存在问题：\n· " + "\n· ".join(problems))
        self.state = AppState.from_dict(d.get("state"))
        self.inv.load(d.get("inventory"), self.cfg, self.table)
        try:
            self.refresh_all()
        except Exception:                                   # noqa: BLE001
            pass
        if not silent:
            self.set_status("已读取 %s（%d 件圣遗物）" % (DATA_PATH, len(self.inv.items)))

    def _on_close(self):
        try:
            self._save_game(silent=True)
        except Exception:                                   # noqa: BLE001
            pass
        self.destroy()

    # ------------------------------------------------------------ 杂项
    # 评分高亮：命中评分词条的行用 hit 标签（蓝 + 粗），评分汇总用 score 标签（橙 + 粗）
    HIT_COLOR = "#0b5fd0"
    SCORE_COLOR = "#a35c00"
    DIM_COLOR = "#666"

    def _text_tags(self, w):
        try:
            bold = str(w.cget("font")) + " bold"
        except tk.TclError:
            bold = "TkDefaultFont"
        w.tag_configure("hit", foreground=self.HIT_COLOR, font=bold)
        w.tag_configure("score", foreground=self.SCORE_COLOR, font=bold)
        w.tag_configure("dim", foreground=self.DIM_COLOR)

    def _set_rich(self, w, entries):
        """entries = [(标签 or None, 文本)]，按顺序写入（文本自带换行）。"""
        self._text_tags(w)
        w.configure(state="normal")
        w.delete("1.0", "end")
        for tag, text in entries:
            w.insert("end", text, (tag,) if tag else ())
        w.configure(state="disabled")

    def _append_rich(self, w, entries):
        self._text_tags(w)
        w.configure(state="normal")
        for tag, text in entries:
            w.insert("end", text, (tag,) if tag else ())
        w.see("end")
        w.configure(state="disabled")

    def _mode_text(self) -> str:
        """状态栏 / 明细里的「评分模式」文字：关掉评分就显示「关闭评分」。"""
        if not scoring.is_enabled(self.cfg):
            return "关闭评分"
        return "总成长" if self.cfg.get("score_mode", "growth") == "growth" else "实际数值"

    def _score_line(self, sc) -> str:
        if not sc.get("enabled", True):
            return "评分已关闭（总分按 0 显示）"
        return "总分 %.3f（%s模式）" % (sc["total"], self._mode_text())

    def _hit_parts(self, art, sc) -> list[str]:
        """命中的词条及权重，例如 ['主词条 暴击率 每级 +0.1', '副词条1 暴击伤害 ×2']。"""
        out = []
        w = sc["weights"]
        if sc["main_scored"]:
            _hl, ms, _sw = w.get(self.table.key_of(art.main_id), (0.0, 0.0, 0.0))
            out.append("主词条 %s 每级 +%s（%s）" % (
                art.main_name, _n(ms), "★高亮" if sc["main_hl"] else "不高亮"))
        for i in range(4):
            if i < len(sc["sub_hits"]) and sc["sub_hits"][i]:
                _hl, _ms, sw = w.get(self.table.key_of(art.sub_id(i)), (0.0, 0.0, 0.0))
                out.append("副词条%d %s ×%s%s"
                           % (i + 1, self.table.display(art.sub_id(i)), _n(sw),
                              "" if art.is_active_sub(i) else "（未激活，不计分）"))
        return out

    def _rule_text(self, set_name: str, limit: int = 12) -> str:
        """规则正文（高亮开关带 ★ 前缀），例如「暴击率★ 主0.1 副2」。"""
        pairs = scoring.rule_pairs(self.cfg, self.table, set_name)
        if not pairs:
            return "（这个套装还没有评分规则，到「评分」页写一条）"
        body = "、".join("%s%s 主%s 副%s" % (nm, "★" if hl > 0 else "", _n(ms), _n(sw))
                         for nm, hl, ms, sw in pairs[:limit])
        if len(pairs) > limit:
            body += "…（共 %d 条）" % len(pairs)
        return body

    def _score_entries(self, art, sc=None, brief: bool = False):
        """圣遗物描述后面的评分块。"""
        sc = sc or scoring.score_artifact(art, self.cfg, self.table)
        if not sc.get("enabled", True):
            return [("dim", "\n【评分】已关闭（自定义 → 参数 里可以重新打开）\n")]
        entries = [("score", "\n【评分】%s　有效词条数 %.2f / 副词条总成长 %.2f\n"
                    % (self._score_line(sc), sc["useful_rolls"], sc["rolls"]))]
        hits = self._hit_parts(art, sc)
        if hits:
            entries.append(("hit", "  ★ 命中：%s\n" % "；".join(hits)))
        else:
            entries.append(("dim", "  ☆ 没有命中任何评分词条（得 0 分）\n"))
        if not brief:
            entries.append(("dim", "  套装规则：%s\n" % self._rule_text(art.set_name)))
        return entries

    def _artifact_entries(self, art, suffix=(), brief: bool = False):
        """圣遗物描述 + 评分块；命中且开了高亮的词条整行用 hit 标签。"""
        sc = scoring.score_artifact(art, self.cfg, self.table)
        hits = {"main": sc["main_hl"]}          # 每条规则自己的第 2 个数决定要不要高亮
        for i, h in enumerate(sc["sub_hits"]):
            hits[i] = h
        lines = art.describe_lines(hits)
        entries = []
        for idx, line in enumerate(lines):
            tag = None
            i = idx - 6
            active = (0 <= i < 4) and art.is_active_sub(i)
            # describe_lines 的顺序：3 = 主词条，6~9 = 副词条1~4
            if idx == 3 and hits["main"]:
                tag = "hit"
            elif 6 <= idx <= 9 and not active:
                # 未激活词条：整行灰色；命中评分规则时 ★ 和词条名仍然高亮
                pre, star, rest = line.partition("★")
                entries.append(("dim", pre))
                entries.append(("hit", "★" + rest) if star else ("dim", ""))
                entries.append((None, "\n"))
                continue
            elif 6 <= idx <= 9 and i < len(sc["sub_hits"]) and sc["sub_hits"][i]:
                tag = "hit"
            elif line.startswith(("祝圣之霜定义", "保底命中")):
                tag = "dim"
            entries.append((tag, line + "\n"))
        entries += self._score_entries(art, sc, brief=brief)
        for line in suffix:
            entries.append(("dim", line + "\n"))
        return entries

    def _detail_entries(self, art, sc=None, head: str = ""):
        """得分拆解（列表页与评分页共用）。"""
        sc = sc or scoring.score_artifact(art, self.cfg, self.table)
        entries = []
        if head:
            entries.append(("dim", head + "\n"))
        entries.append(("score", "%s　有效词条数 %.2f　副词条总成长 %.2f\n"
                        % (self._score_line(sc), sc["useful_rolls"], sc["rolls"])))
        for b in sc["breakdown"]:
            entries.append(("hit" if (b["kind"] == "主词条" and sc["main_hl"]) else None,
                            "  [%s] %-14s %-22s +%.3f\n"
                            % (b["kind"], b["name"], b["detail"], b["score"])))
        if not sc["breakdown"]:
            entries.append(("dim", "  （没有命中任何评分词条，得 0 分）\n"))
        return entries

    def _marked_summary(self, art, sc=None) -> str:
        """列表「副词条」列：命中的副词条前面加 ★。"""
        sc = sc or scoring.score_artifact(art, self.cfg, self.table)
        parts = []
        idxs = list(art.active_indices())
        if art.show_inactive():
            idxs += art.pending_indices()
        for i in idxs:
            mark = "★" if (i < len(sc["sub_hits"]) and sc["sub_hits"][i]) else ""
            parts.append(art.sub_text_plain(i, mark))
        return " / ".join(parts) if parts else "—"

    def _set_text(self, widget: ScrolledText, text: str):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
        widget.configure(state="disabled")

    def _append_text(self, widget: ScrolledText, text: str):
        widget.configure(state="normal")
        widget.insert("end", text)
        widget.see("end")
        widget.configure(state="disabled")

    def _show_detail_dialog(self):
        art = self.current_artifact()
        if art is None:
            messagebox.showinfo("提示", "请先选择一件圣遗物。")
            return
        entries = self._artifact_entries(art)
        entries.append(("dim", "\n向量：%s\n" % art.vector_text()))
        entries += self._detail_entries(art, head="—" * 30)
        entries.append(("dim", "\n历史：\n"))
        entries += [(None, "  " + h + "\n") for h in art.history[-30:]]
        win = tk.Toplevel(self)
        win.title("圣遗物详情 #%d（★ = 命中评分词条）" % art.uid)
        win.geometry("680x640")
        t = ScrolledText(win, wrap="word", font=("Consolas", 10))
        t.pack(fill="both", expand=True, padx=8, pady=8)
        self._set_rich(t, entries)

    # ------------------------------------------------------------------
    # 向量编辑
    # ------------------------------------------------------------------
    def _vector_problems(self, art: Artifact) -> list[str]:
        """检查一条向量是否自洽（编辑向量时用）。"""
        out = []
        n_slot = len(self.cfg["slots"])
        n_set = len(self.cfg["sets"])
        max_sid = max([s["id"] for s in self.table.stats] or [0])
        min_sid = min([s["id"] for s in self.table.stats] or [0])
        if not (0 <= art.slot < n_slot):
            out.append("部位 id 应在 0~%d，当前 %d" % (n_slot - 1, art.slot))
        if not (0 <= art.set_id < n_set):
            out.append("套装 id 应在 0~%d，当前 %d" % (n_set - 1, art.set_id))
        if self.table.get(art.main_id) is None:
            out.append("主词条 id 不是有效词条：%d（有效 %d~%d）" % (art.main_id, min_sid, max_sid))
        lv = art.level
        if not (0 <= lv <= art.max_level):
            out.append("等级应在 0~%d，当前 %s" % (art.max_level, _n(lv)))
        if not (0 <= art.init_sub_count <= 4):
            out.append("初始副词条数应在 0~4，当前 %d" % art.init_sub_count)
        if not (0 <= art.cur_sub_count <= 4):
            out.append("当前副词条数应在 0~4，当前 %d" % art.cur_sub_count)
        if art.cur_sub_count < art.init_sub_count:
            out.append("当前副词条数(%d)不能少于初始条数(%d)" % (art.cur_sub_count, art.init_sub_count))
        seen = []
        for i in range(4):
            sid = art.sub_id(i)
            if sid == 0:
                continue
            if self.table.get(sid) is None:
                out.append("副词条 %d 的 id 不是有效词条：%d" % (i + 1, sid))
            if sid == art.main_id:
                out.append("副词条 %d 与主词条重复" % (i + 1))
            if sid in seen:
                out.append("副词条 %d 与副词条 %d 重复" % (i + 1, seen.index(sid) + 1))
            seen.append(sid)
        # 允许「预生成」的未激活词条：len(seen) 可以是 cur_sub_count，也可以多出来几条
        if art.cur_sub_count > len(seen) or art.cur_sub_count < 0:
            out.append("当前副词条数写的是 %d，但实际只填了 %d 条"
                       % (art.cur_sub_count, len(seen)))
        elif len(seen) > art.cur_sub_count:
            extra = [i + 1 for i in range(len(seen)) if i >= art.cur_sub_count]
            if extra:
                out.append("注意：第 %s 条副词条落在「当前副词条数」之外，"
                           "会被当成未激活词条（不参与评分，强化到 +4 才启用）"
                           % "、".join(str(x) for x in extra))
        for i in range(4):
            for label, v in (("初始", art.init_g(i)), ("升级", art.up_g(i))):
                if v < 0:
                    out.append("副词条 %d 的%s成长不能是负数：%s" % (i + 1, label, _n(v)))
        return out

    def _edit_vector_dialog(self):
        art = self.current_artifact()
        if art is None:
            messagebox.showinfo("提示", "请先在列表（或上方下拉框）中选择一件圣遗物。")
            return
        lay = self.cfg["vector_layout"]
        win = tk.Toplevel(self)
        win.title("编辑向量 #%d（%s · %s）" % (art.uid, art.set_name, art.slot_name))
        win.transient(self)
        win.geometry("860x660")

        ttk.Label(win, text="下面的数值就是这条圣遗物的存储向量，改完按「确定」写入。\n"
                            "整数维度必须填整数；非法组合会被拦下并说明原因。",
                  foreground="#555", justify="left", padding=(10, 8)).pack(anchor="w")

        body = ScrollFrame(win)
        body.pack(fill="both", expand=True, padx=10)
        entries = []
        orig = [art.vec[i] if i < len(art.vec) else 0 for i in range(len(lay))]
        for i, d in enumerate(lay):
            row = ttk.Frame(body.body)
            row.pack(fill="x", pady=1)
            ttk.Label(row, text="%2d." % (i + 1), width=4).pack(side="left")
            ttk.Label(row, text=d["key"], width=13, font=("Consolas", 9)).pack(side="left")
            ttk.Label(row, text=d.get("label", ""), width=16).pack(side="left")
            cur = orig[i]
            var = tk.StringVar(value=(_n(cur) if d.get("kind") == "int" else ("%g" % float(cur or 0))))
            ttk.Entry(row, textvariable=var, width=18, font=("Consolas", 9)).pack(side="left")
            ttk.Label(row, text=d.get("desc", ""), foreground="#777").pack(side="left", padx=(8, 0))
            entries.append((i, d, var))

        raw_row = ttk.Frame(win, padding=(10, 6))
        raw_row.pack(fill="x")
        ttk.Label(raw_row, text="整条向量：").pack(side="left")
        raw_var = tk.StringVar(value=", ".join(_n(v) for v in orig))
        ttk.Entry(raw_row, textvariable=raw_var, font=("Consolas", 9)).pack(
            side="left", fill="x", expand=True, padx=4)

        def load_raw():
            parts = [p for p in raw_var.get().replace("，", ",").replace("[", "").replace("]", "")
                     .replace(" ", ",").split(",") if p.strip()]
            if len(parts) != len(entries):
                messagebox.showerror("无法读入", "需要 %d 个数值，当前给了 %d 个。"
                                     % (len(entries), len(parts)))
                return
            for (i, d, var), txt in zip(entries, parts):
                try:
                    var.set(_n(float(txt)) if d.get("kind") == "int" else ("%g" % float(txt)))
                except ValueError:
                    messagebox.showerror("无法读入", "第 %d 项不是数字：%s" % (i + 1, txt))
                    return

        def restore():
            for (i, d, var), v in zip(entries, orig):
                var.set(_n(v) if d.get("kind") == "int" else ("%g" % float(v or 0)))
            raw_var.set(", ".join(_n(v) for v in orig))

        ttk.Button(raw_row, text="从文本读入", command=load_raw).pack(side="left")

        bar = ttk.Frame(win, padding=10)
        bar.pack(fill="x")

        def apply():
            vals = []
            for i, d, var in entries:
                txt = var.get().strip()
                if txt == "":
                    messagebox.showerror("数值有误", "第 %d 项（%s）不能为空。" % (i + 1, d.get("label")))
                    return
                try:
                    v = float(txt)
                except ValueError:
                    messagebox.showerror("数值有误", "第 %d 项（%s）不是数字：%s"
                                         % (i + 1, d.get("label"), txt))
                    return
                if d.get("kind") == "int":
                    if abs(v - round(v)) > 1e-9:
                        messagebox.showerror("数值有误", "第 %d 项（%s）必须是整数。" % (i + 1, d.get("label")))
                        return
                    v = int(round(v))
                vals.append(v)
            new_vec = list(art.vec)
            for (i, _d, _var), v in zip(entries, vals):
                new_vec[i] = v
            probe = Artifact(list(new_vec), self.cfg, self.table)
            problems = self._vector_problems(probe)
            if problems:
                messagebox.showerror("向量不合法", "· " + "\n· ".join(problems))
                return
            art.vec[:] = new_vec
            art._rebuild()
            art.history.append("手动编辑向量")
            self.refresh_all()
            win.destroy()
            self.set_status("已写入 #%d 的向量。" % art.uid)

        ttk.Button(bar, text="还原", command=restore).pack(side="left")
        ttk.Button(bar, text="取消", command=win.destroy).pack(side="right")
        ttk.Button(bar, text="确定", command=apply).pack(side="right", padx=6)

    def _about(self):
        messagebox.showinfo("关于", "原神圣遗物强化模拟器\n\n"
                                    "数值表来源：基础数据.txt\n"
                                    "所有数值、概率、向量布局、套装秘境与评分规则均可在「自定义」页修改。\n"
                                    "配置：%s\n存档：%s" % (CONFIG_PATH, DATA_PATH))


# ==========================================================================
def _n(x) -> str:
    try:
        f = float(x)
    except (TypeError, ValueError):
        return str(x)
    if f == int(f):
        return str(int(f))
    return ("%g" % f)


def _get_path(cfg: dict, path: str):
    cur = cfg
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def _set_path(cfg: dict, path: str, text: str, kind: str):
    parts = path.split(".")
    cur = cfg
    for p in parts[:-1]:
        cur = cur.setdefault(p, {})
    key = parts[-1]
    if kind == "float":
        cur[key] = float(text)
    elif kind == "int":
        cur[key] = int(float(text))
    elif kind == "str":
        cur[key] = text
    elif kind == "bool":
        cur[key] = text.strip().lower() in ("1", "true", "yes", "y", "是", "真")
    elif kind == "floatlist":
        cur[key] = [float(x) for x in text.replace("，", ",").split(",") if x.strip() != ""]
    elif kind == "intlist":
        cur[key] = [int(float(x)) for x in text.replace("，", ",").split(",") if x.strip() != ""]
    elif kind == "strlist":
        cur[key] = [x.strip() for x in text.replace("，", ",").split(",") if x.strip() != ""]
    elif kind == "slotint":
        vals = [int(float(x)) for x in text.replace("，", ",").split(",") if x.strip() != ""]
        if len(vals) != 5:
            raise ValueError("需要 5 个数值")
        cur[key] = {str(i): v for i, v in enumerate(vals)}
    else:
        cur[key] = text


def _fmt_path(cfg: dict, path: str, kind: str) -> str:
    v = _get_path(cfg, path)
    if v is None:
        return ""
    if kind == "slotint":
        return ", ".join(str(v.get(str(i), 0)) for i in range(5))
    if kind in ("floatlist", "intlist", "strlist"):
        return ", ".join(_n(x) if kind != "strlist" else str(x) for x in v)
    if kind == "float":
        return _n(v)
    if kind == "int":
        return str(int(v))
    return str(v)


def main():
    # 必须在创建 Tk 根窗口之前声明 DPI 感知，否则 Tk 会按虚拟化的屏幕尺寸建窗。
    try:
        from ctypes import windll
        try:
            windll.shcore.SetProcessDpiAwareness(1)      # Win 8.1+
        except Exception:                                # noqa: BLE001
            windll.user32.SetProcessDPIAware()           # Win 7 回退
    except Exception:                                    # noqa: BLE001
        pass
    try:
        app = App()
    except Exception as exc:                                # noqa: BLE001
        import traceback
        traceback.print_exc()
        try:
            tk.Tk().withdraw()
            messagebox.showerror("启动失败", "%s\n\n%s" % (exc, traceback.format_exc()))
        except Exception:                                   # noqa: BLE001
            pass
        raise
    app.mainloop()
