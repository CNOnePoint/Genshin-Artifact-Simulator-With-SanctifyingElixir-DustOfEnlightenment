# -*- coding: utf-8 -*-
"""配置模块：数值表、套装、副本、圣遗物向量布局、概率与消耗参数。

所有内容都可以在 GUI 的「自定义」页里修改，并保存到 config.json。
"""
from __future__ import annotations

import copy
import json
import os

APP_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(APP_DIR)
CONFIG_PATH = os.path.join(ROOT_DIR, "config.json")

# --------------------------------------------------------------------------
# 默认数值表（来自 基础数据.txt）
# 列：名称, 最大值, 沙权重, 头权重, 杯权重, 副词条权重, 命中权重
# 行号即「主词条id」（1 起）
# --------------------------------------------------------------------------
DEFAULT_STAT_ROWS = [
    ("攻击力",         311.0,  0,  0,    0, 6, 1),   # 1  攻击力（小攻击，花羽主词条）
    ("生命值",        4780.0,  0,  0,    0, 6, 1),   # 2  生命值（小生命）
    ("防御力",         370.5,  0,  0,    0, 6, 1),   # 3  防御力（小防御）
    ("攻击力",         0.466,  8, 11,  766, 4, 1),   # 4  攻击力%
    ("生命值",         0.466,  8, 11,  767, 4, 1),   # 5  生命值%
    ("防御力",         0.583,  8, 11,  767, 4, 1),   # 6  防御力%
    ("元素充能效率",    0.518,  3,  0,    0, 4, 1),   # 7
    ("元素精通",       186.5,  3,  2,  100, 4, 1),   # 8
    ("暴击率",         0.311,  0,  5,    0, 3, 1),   # 9
    ("暴击伤害",       0.622,  0,  5,    0, 3, 1),   # 10
    ("治疗加成",       0.359,  0,  5,    0, 0, 0),   # 11
    ("物理伤害加成",    0.583,  0,  0,  200, 0, 0),   # 12
    ("风元素伤害加成",  0.466,  0,  0,  200, 0, 0),   # 13
    ("岩元素伤害加成",  0.466,  0,  0,  200, 0, 0),   # 14
    ("草元素伤害加成",  0.466,  0,  0,  200, 0, 0),   # 15
    ("火元素伤害加成",  0.466,  0,  0,  200, 0, 0),   # 16
    ("水元素伤害加成",  0.466,  0,  0,  200, 0, 0),   # 17
    ("雷元素伤害加成",  0.466,  0,  0,  200, 0, 0),   # 18
    ("冰元素伤害加成",  0.466,  0,  0,  200, 0, 0),   # 19
]

# 概率型词条的判定阈值：最大值小于该值即视为百分比词条
PERCENT_THRESHOLD = 5.0

# 部位下标
SLOT_FLOWER, SLOT_PLUME, SLOT_SANDS, SLOT_GOBLET, SLOT_CIRCLET = 0, 1, 2, 3, 4
DEFAULT_SLOTS = ["生之花", "死之羽", "时之沙", "空之杯", "理之冠"]

# 花/羽的主词条固定
DEFAULT_FIXED_MAIN = {0: 2, 1: 1}   # 生之花 -> 生命值(2)，死之羽 -> 攻击力(1)

# --------------------------------------------------------------------------
# 圣遗物向量布局（默认 20 维）
# key 是程序内部语义，不可改；label/desc 可改；顺序可改（改顺序即改向量排布）
# --------------------------------------------------------------------------
DEFAULT_VECTOR_LAYOUT = [
    {"key": "set",            "label": "套装",           "kind": "id",    "desc": "套装编号（套装列表下标，0 起）"},
    {"key": "slot",           "label": "部位",           "kind": "id",    "desc": "0=生之花 1=死之羽 2=时之沙 3=空之杯 4=理之冠"},
    {"key": "main",           "label": "主词条",         "kind": "id",    "desc": "主词条编号（数值表行号，1 起）"},
    {"key": "level",          "label": "等级",           "kind": "int",   "desc": "0~20"},
    {"key": "init_sub_count", "label": "副词条数",       "kind": "int",   "desc": "初始副词条数量（3 或 4）"},
    {"key": "cur_sub_count",  "label": "目前词条数",     "kind": "int",   "desc": "当前副词条数量（3 或 4）"},
    {"key": "define1",        "label": "祝圣定义词条1",  "kind": "id",    "desc": "0=无，其余为词条编号"},
    {"key": "define2",        "label": "祝圣定义词条2",  "kind": "id",    "desc": "0=无，其余为词条编号"},
    {"key": "sub1",           "label": "副词条1",        "kind": "id",    "desc": "0=空，其余为词条编号"},
    {"key": "sub2",           "label": "副词条2",        "kind": "id",    "desc": "0=空"},
    {"key": "sub3",           "label": "副词条3",        "kind": "id",    "desc": "0=空"},
    {"key": "sub4",           "label": "副词条4",        "kind": "id",    "desc": "0=空"},
    {"key": "init_g1",        "label": "副词条初始成长1", "kind": "float", "desc": "1 / 0.9 / 0.8 / 0.7"},
    {"key": "init_g2",        "label": "副词条初始成长2", "kind": "float", "desc": ""},
    {"key": "init_g3",        "label": "副词条初始成长3", "kind": "float", "desc": ""},
    {"key": "init_g4",        "label": "副词条初始成长4", "kind": "float", "desc": ""},
    {"key": "up_g1",          "label": "副词条升级成长1", "kind": "float", "desc": "每次命中累加 0.7~1.0"},
    {"key": "up_g2",          "label": "副词条升级成长2", "kind": "float", "desc": ""},
    {"key": "up_g3",          "label": "副词条升级成长3", "kind": "float", "desc": ""},
    {"key": "up_g4",          "label": "副词条升级成长4", "kind": "float", "desc": ""},
]

# --------------------------------------------------------------------------
# 词条别名（用于评分规则里手写的词条名）
# --------------------------------------------------------------------------
DEFAULT_ALIASES = {
    "攻击力": "atk_flat", "小攻击": "atk_flat", "攻击": "atk_flat", "atk": "atk_flat",
    "攻击力%": "atk_pct", "攻击力百分比": "atk_pct", "大攻击": "atk_pct", "攻击百分比": "atk_pct",
    "生命值": "hp_flat", "小生命": "hp_flat", "生命": "hp_flat",
    "生命值%": "hp_pct", "生命值百分比": "hp_pct", "大生命": "hp_pct", "生命百分比": "hp_pct",
    "防御力": "def_flat", "小防御": "def_flat", "防御": "def_flat",
    "防御力%": "def_pct", "防御力百分比": "def_pct", "大防御": "def_pct", "防御百分比": "def_pct",
    "元素充能效率": "er", "充能": "er", "充能效率": "er", "元素充能": "er",
    "元素精通": "em", "精通": "em",
    "暴击率": "cr", "暴击": "cr", "暴击率%": "cr",
    "暴击伤害": "cd", "爆伤": "cd", "暴击伤害%": "cd",
    "治疗加成": "heal", "物理伤害加成": "phys", "物伤": "phys", "物理伤害": "phys",
    "风元素伤害加成": "anemo", "风伤": "anemo", "风元素伤害": "anemo",
    "岩元素伤害加成": "geo", "岩伤": "geo", "岩元素伤害": "geo",
    "草元素伤害加成": "dendro", "草伤": "dendro", "草元素伤害": "dendro",
    "火元素伤害加成": "pyro", "火伤": "pyro", "火元素伤害": "pyro",
    "水元素伤害加成": "hydro", "水伤": "hydro", "水元素伤害": "hydro",
    "雷元素伤害加成": "electro", "雷伤": "electro", "雷元素伤害": "electro",
    "冰元素伤害加成": "cryo", "冰伤": "cryo", "冰元素伤害": "cryo",
}

# key -> (默认名称, 是否百分比, 最大值)
KEY_BASE = {
    "atk_flat": ("攻击力", False),
    "hp_flat": ("生命值", False),
    "def_flat": ("防御力", False),
    "atk_pct": ("攻击力", True),
    "hp_pct": ("生命值", True),
    "def_pct": ("防御力", True),
    "er": ("元素充能效率", True),
    "em": ("元素精通", False),
    "cr": ("暴击率", True),
    "cd": ("暴击伤害", True),
    "heal": ("治疗加成", True),
    "phys": ("物理伤害加成", True),
    "anemo": ("风元素伤害加成", True),
    "geo": ("岩元素伤害加成", True),
    "dendro": ("草元素伤害加成", True),
    "pyro": ("火元素伤害加成", True),
    "hydro": ("水元素伤害加成", True),
    "electro": ("雷元素伤害加成", True),
    "cryo": ("冰元素伤害加成", True),
}

# 与 基础数据.txt 行序一致的 key
ROW_KEYS = [
    "atk_flat", "hp_flat", "def_flat",
    "atk_pct", "hp_pct", "def_pct",
    "er", "em", "cr", "cd", "heal", "phys",
    "anemo", "geo", "dendro", "pyro", "hydro", "electro", "cryo",
]

# --------------------------------------------------------------------------
# 默认评分模板（每个套装都会用它初始化）
# 规则四元组：(词条名, 主词条是否高亮, 主词条得分系数, 副词条权重)
# 主词条得分 = 等级 × 系数
# --------------------------------------------------------------------------
DEFAULT_SCORE_TEMPLATE = [
    ("暴击率", 1.0, 1.5, 7.775),
    ("暴击伤害", 1.0, 1.5, 7.775),
    ("各元素伤害加成", 1.0, 0.0, 0.0),
]

# 旧版默认模板：读档时如果某个套装的规则和它完全相同，就自动升级成新模板
OLD_SCORE_TEMPLATE = [
    ["暴击率", 1.0, 0.1, 2.0],
    ["暴击伤害", 1.0, 0.1, 2.0],
    ["攻击力%", 1.0, 0.1, 1.0],
    ["元素精通", 1.0, 0.05, 0.5],
    ["元素充能效率", 1.0, 0.05, 0.5],
]

# 一组词条共用一个权重（评分规则里可以直接写组名，省得七种元素各写一遍）
STAT_GROUPS = {
    "各元素伤害加成": ["anemo", "geo", "dendro", "pyro", "hydro", "electro", "cryo"],
    "所有元素伤害加成": ["anemo", "geo", "dendro", "pyro", "hydro", "electro", "cryo"],
    "元素伤害加成": ["anemo", "geo", "dendro", "pyro", "hydro", "electro", "cryo"],
}


# --------------------------------------------------------------------------
def _default_stats() -> list[dict]:
    out = []
    for i, (name, mx, ws, wh, wc, wsub, whit) in enumerate(DEFAULT_STAT_ROWS):
        key = ROW_KEYS[i] if i < len(ROW_KEYS) else "stat%d" % (i + 1)
        out.append({
            "id": i + 1,
            "key": key,
            "name": name,
            "max": mx,
            "pct": mx < PERCENT_THRESHOLD,
            "w_sand": ws,
            "w_head": wh,
            "w_cup": wc,
            "w_sub": wsub,
            "w_hit": whit,
            "enabled": True,
        })
    return out


def default_pieces(set_name: str) -> list[str]:
    """没有人工作部件名时，用「套装名·部位名」当占位。"""
    return ["%s·%s" % (set_name, s) for s in DEFAULT_SLOTS]


def piece_name(cfg: dict, set_name: str, slot: int) -> str:
    """取某个套装某个部位的「圣遗物名称（部件名）」，取不到就回落到占位名。"""
    try:
        names = (cfg.get("set_pieces") or {}).get(set_name) or []
        n = str(names[int(slot)]).strip()
        if n:
            return n
    except (IndexError, TypeError, ValueError, KeyError):
        pass
    try:
        return "%s·%s" % (set_name, DEFAULT_SLOTS[int(slot)])
    except (IndexError, TypeError, ValueError):
        return set_name


def default_config() -> dict:
    """返回一份全新的默认配置。"""
    from . import dataset

    sets = list(dataset.SET_NAMES)
    _tmpl = [list(r) for r in DEFAULT_SCORE_TEMPLATE]
    scoring = {"default": copy.deepcopy(_tmpl), "sets": {}}
    for s in sets:
        scoring["sets"][s] = copy.deepcopy(_tmpl)
    pieces = {}
    for s in sets:
        src = dataset.SET_PIECES.get(s) or default_pieces(s)
        pieces[s] = [(str(src[i]).strip() if i < len(src) else "") or default_pieces(s)[i]
                     for i in range(len(DEFAULT_SLOTS))]

    return {
        "version": 1,
        "slots": list(DEFAULT_SLOTS),
        "fixed_main": {str(k): v for k, v in DEFAULT_FIXED_MAIN.items()},
        "stats": _default_stats(),
        "sets": sets,
        "domains": copy.deepcopy(dataset.DOMAINS),
        "set_pieces": pieces,
        "vector_layout": copy.deepcopy(DEFAULT_VECTOR_LAYOUT),
        "aliases": copy.deepcopy(DEFAULT_ALIASES),
        # --- 数值规则 ---
        "main_stat_formula": {"base": 0.15, "span": 0.85, "max_level": 20},
        "substat_divisor": 8.0,
        # 攻击力 / 生命值 / 防御力 这三条「小词条」的除数与原神一致，取 16
        "flat_substat_divisor": 16.0,
        "flat_substat_keys": ["atk_flat", "hp_flat", "def_flat"],
        "init_sub_weights": {"3": 2.0, "4": 1.0},
        "init_growth_tiers": [1.0, 0.9, 0.8, 0.7],
        "init_growth_mode": "tiers",          # tiers=四档等概率 / uniform=在 min~max 之间均匀
        "upgrade_growth_tiers": [0.7, 0.8, 0.9, 1.0],
        "upgrade_growth_mode": "tiers",
        "slot_prob": [0.2, 0.2, 0.2, 0.2, 0.2],
        "enhance_interval": 4,
        # --- 祝圣之霜 ---
        "elixir": {
            "cost": {"0": 1, "1": 1, "2": 2, "3": 4, "4": 3},
            # 0 = 跟随「获取新圣遗物」的初始副词条分布（推荐）；填 3 或 4 则强制
            "force_initial_sub_count": 0,
            "min_total_hits": 2,
        },
        # --- 启圣之尘 ---
        "dust": {
            "cost": {"0": 1, "1": 1, "2": 2, "3": 2, "4": 2},
            "hit3_thresholds": [6, 12],
            "hit4_threshold": 18,
            "reset_on_hit4": True,
            "hit3_min_total": 3,
            "hit4_min_total": 4,
            "min_total_hits": 2,          # 每次都有的基础保底命中次数
            "ask_before_apply": True,     # 重塑后弹窗让玩家选「重塑前 / 重塑后」
        },
        # --- 评分 ---
        "scoring": scoring,
        "score_mode": "growth",               # growth=按总成长（词条数） / value=按实际数值
        # 三个全局开关：关掉评分 = 全部按 0 显示；两个高亮开关只管 ★，不影响得分
        "score_enabled": True,
        "score_hl_main": True,
        "score_hl_sub": True,
        # 显示：未满 4 条副词条的圣遗物，是否把「预生成但还没激活」的词条也显示出来
        "show_inactive_subs": False,
    }


# --------------------------------------------------------------------------
def _merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def load_config(path: str | None = None) -> dict:
    path = path or CONFIG_PATH
    cfg = default_config()
    if os.path.exists(path):
        try:
            # utf-8-sig：记事本等编辑器存成带 BOM 的 UTF-8 也能正常读取
            with open(path, "r", encoding="utf-8-sig") as f:
                user = json.load(f)
            if isinstance(user, dict):
                cfg = _merge(cfg, user)
        except Exception as exc:                     # noqa: BLE001
            print("[config] 读取 %s 失败：%s，使用默认配置" % (path, exc))
    return normalize(cfg)


def save_config(cfg: dict, path: str | None = None) -> str:
    path = path or CONFIG_PATH
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    return path


def normalize(cfg: dict) -> dict:
    """补齐派生字段并做一些基本校正。"""
    from . import dataset

    # 主词条 id 与行号保持一致
    for i, st in enumerate(cfg.get("stats", [])):
        st["id"] = i + 1
        st.setdefault("key", ROW_KEYS[i] if i < len(ROW_KEYS) else "stat%d" % (i + 1))
        st["pct"] = bool(st.get("max", 0) < PERCENT_THRESHOLD)
        st.setdefault("enabled", True)
    # 花/羽固定主词条
    fm = cfg.get("fixed_main") or {}
    cfg["fixed_main"] = {int(k): int(v) for k, v in fm.items()}
    if 0 not in cfg["fixed_main"]:
        cfg["fixed_main"][0] = 2
    if 1 not in cfg["fixed_main"]:
        cfg["fixed_main"][1] = 1
    # 固定主词条若指向了不存在的行号，回退到默认行号；仍无效则取消固定
    valid_ids = {s["id"] for s in cfg.get("stats", [])}
    for slot in list(cfg["fixed_main"]):
        if cfg["fixed_main"][slot] not in valid_ids:
            fallback = DEFAULT_FIXED_MAIN.get(slot)
            if fallback in valid_ids:
                cfg["fixed_main"][slot] = fallback
            else:
                del cfg["fixed_main"][slot]
    # 向量布局
    layout = cfg.get("vector_layout") or []
    keys = [d.get("key") for d in layout]
    if len(layout) != 20 or sorted(keys) != sorted(d["key"] for d in DEFAULT_VECTOR_LAYOUT):
        cfg["vector_layout"] = copy.deepcopy(DEFAULT_VECTOR_LAYOUT)
    # 套装与秘境：去空、去重、保序；秘境的掉落必须指向已登记的套装
    sets: list[str] = []
    for s in (cfg.get("sets") or []):
        s = str(s).strip()
        if s and s not in sets:
            sets.append(s)
    if not sets:
        sets = list(dataset.SET_NAMES)
    cfg["sets"] = sets
    doms_in = cfg.get("domains")
    if not isinstance(doms_in, dict):
        doms_in = copy.deepcopy(dataset.DOMAINS)
    doms: dict[str, list[str]] = {}
    for name, drops in doms_in.items():
        name = str(name).strip()
        if not name or name in doms:
            continue
        picked: list[str] = []
        for d in (drops or []):
            if d in sets and d not in picked:
                picked.append(d)
        doms[name] = picked
    if not doms:
        doms = {k: [d for d in v if d in sets] for k, v in dataset.DOMAINS.items()}
        doms = {k: v for k, v in doms.items() if v}
    if not doms:
        doms = {"任意套装": list(sets)}
    cfg["domains"] = doms
    # 套装部件名（圣遗物名称）：每个套装固定 5 个，顺序 = 生之花/死之羽/时之沙/空之杯/理之冠
    pieces_in = cfg.get("set_pieces")
    if not isinstance(pieces_in, dict):
        pieces_in = {}
    pieces: dict[str, list[str]] = {}
    for name in sets:
        src = pieces_in.get(name)
        if not isinstance(src, (list, tuple)):
            src = dataset.SET_PIECES.get(name) or []
        ph = default_pieces(name)
        pieces[name] = [((str(src[i]).strip() if i < len(src) else "") or ph[i])
                        for i in range(len(DEFAULT_SLOTS))]
    cfg["set_pieces"] = pieces
    # 评分：默认模板直接放进每个套装里（这样逐个套装改就行，不用先「套用到全部」）
    _tmpl = [list(r) for r in DEFAULT_SCORE_TEMPLATE]
    sc = cfg.setdefault("scoring", {"default": copy.deepcopy(_tmpl), "sets": {}})
    sc.setdefault("default", copy.deepcopy(_tmpl))
    sc.setdefault("sets", {})
    for name in sets:
        sc["sets"].setdefault(name, copy.deepcopy(_tmpl))
    for gone in [k for k in sc["sets"] if k not in sets]:
        del sc["sets"][gone]
    cfg.setdefault("score_mode", "growth")
    # 三个全局评分开关（关掉评分 → 所有评分按 0；两个高亮开关只管 ★）
    cfg["show_inactive_subs"] = bool(cfg.get("show_inactive_subs", False))
    for _k in ("score_enabled", "score_hl_main", "score_hl_sub"):
        cfg[_k] = bool(cfg.get(_k, True))
    # 旧版默认模板逐字升级成新版（只在规则和旧默认完全相同时替换，改过的不动）
    _new_tmpl = [list(r) for r in DEFAULT_SCORE_TEMPLATE]

    def _is_old_template(rules) -> bool:
        try:
            got = [[str(r[0]).strip()] + [float(x) for x in r[1:4]] for r in (rules or [])]
        except (TypeError, ValueError, IndexError, KeyError):
            return False
        return got == OLD_SCORE_TEMPLATE

    if _is_old_template(sc.get("default")):
        sc["default"] = copy.deepcopy(_new_tmpl)
    for _name in list(sc.get("sets") or {}):
        if _is_old_template(sc["sets"][_name]):
            sc["sets"][_name] = copy.deepcopy(_new_tmpl)
    # 副词条除数（小攻击/小生命/小防御 用 16，其余用 substat_divisor）
    if not cfg.get("flat_substat_keys"):
        cfg["flat_substat_keys"] = ["atk_flat", "hp_flat", "def_flat"]
    cfg.setdefault("flat_substat_divisor", 16.0)
    cfg.setdefault("substat_divisor", 8.0)
    # 启圣之尘
    du = cfg.setdefault("dust", {})
    du.setdefault("min_total_hits", 2)
    du.setdefault("ask_before_apply", True)
    du.setdefault("hit3_min_total", 3)
    du.setdefault("hit4_min_total", 4)
    du.setdefault("hit4_threshold", 18)
    du.setdefault("hit3_thresholds", [6, 12])
    du.setdefault("reset_on_hit4", True)
    return cfg


# --------------------------------------------------------------------------
def substat_divisor_for(cfg: dict, key: str) -> float:
    """返回某个词条作为副词条时的除数。

    攻击力 / 生命值 / 防御力（内部 key 为 *_flat）按原神使用 16，
    其余词条使用 substat_divisor（默认 8）。
    """
    flat_keys = cfg.get("flat_substat_keys")
    if flat_keys is None:
        flat_keys = ["atk_flat", "hp_flat", "def_flat"]
    if key in flat_keys:
        div = float(cfg.get("flat_substat_divisor", 16.0) or 16.0)
    else:
        div = float(cfg.get("substat_divisor", 8.0) or 8.0)
    return div or 8.0


# --------------------------------------------------------------------------
def validate(cfg: dict) -> list[str]:
    """检查配置是否有硬性问题（返回问题描述列表，空列表表示可用）。"""
    problems: list[str] = []
    stats = cfg.get("stats") or []
    if not stats:
        return ["数值表为空，至少需要一行数据。"]
    table = StatTable(cfg)
    slots = cfg.get("slots") or DEFAULT_SLOTS
    for slot in range(min(5, len(slots))):
        if not table.main_candidates(slot):
            problems.append("部位「%s」没有任何可用的主词条：请检查数值表的沙/头/杯权重列"
                            "（花与死之羽则检查 fixed_main 指向的行号）。" % slots[slot])
    if not any(float(s.get("w_sub", 0) or 0) > 0 for s in stats):
        problems.append("没有任何词条带有「副词条权重」，无法生成副词条。")
    if not any(float(s.get("w_hit", 0) or 0) > 0 for s in stats):
        problems.append("没有任何词条带有「命中权重」，强化时会退化为按副词条权重选择。")
    if not cfg.get("sets"):
        problems.append("套装列表为空，无法确定副本掉落。")
    empty = [k for k, v in (cfg.get("domains") or {}).items() if not v]
    if empty:
        problems.append("副本「%s」没有配置任何掉落套装，选它时只能从全部套装里随机。"
                        % "」「".join(empty[:5]))
    return problems


# --------------------------------------------------------------------------
class StatTable:
    """数值表的便捷访问封装。"""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.stats: list[dict] = cfg["stats"]
        self.by_key: dict[str, dict] = {s["key"]: s for s in self.stats}
        self.by_id: dict[int, dict] = {s["id"]: s for s in self.stats}

    # --- 基础 ---
    def get(self, sid: int) -> dict | None:
        return self.by_id.get(int(sid))

    def key_of(self, sid: int) -> str:
        s = self.by_id.get(int(sid))
        return s["key"] if s else "?"

    def display(self, sid: int) -> str:
        s = self.by_id.get(int(sid))
        if not s:
            return "—"
        name = s["name"]
        if s.get("pct") and name in ("攻击力", "生命值", "防御力"):
            name += "%"
        return name

    def max_of(self, sid: int) -> float:
        s = self.by_id.get(int(sid))
        return float(s["max"]) if s else 0.0

    def is_pct(self, sid: int) -> bool:
        s = self.by_id.get(int(sid))
        return bool(s and s.get("pct"))

    def alias_map(self) -> dict:
        amap = {}
        for s in self.stats:
            amap[s["name"]] = s["key"]
            if s.get("pct") and s["name"] in ("攻击力", "生命值", "防御力"):
                amap[s["name"] + "%"] = s["key"]
        for k, v in (self.cfg.get("aliases") or {}).items():
            amap[k] = v
        return amap

    def resolve_name(self, text: str) -> str | None:
        """把用户写的词条名解析成内部 key。"""
        t = (text or "").strip().replace("％", "%")
        if not t:
            return None
        amap = self.alias_map()
        if t in amap:
            return amap[t]
        if t in self.by_key:
            return t
        # 模糊：忽略空格
        t2 = t.replace(" ", "")
        for k, v in amap.items():
            if k.replace(" ", "") == t2:
                return v
        return None

    def group_name(self, text: str) -> str | None:
        """组名的规范写法（如「各元素伤害加成」）；不是组名返回 None。"""
        t = (text or "").strip().replace("％", "%").replace(" ", "")
        if not t:
            return None
        for gname in STAT_GROUPS:
            if gname.replace(" ", "") == t:
                return gname
        return None

    def group_keys(self, text: str) -> list[str] | None:
        """「各元素伤害加成」这类组名 → 该组包含的 key 列表；不是组名返回 None。"""
        gname = self.group_name(text)
        if gname is None:
            return None
        return [k for k in STAT_GROUPS[gname] if k in self.by_key]

    def resolve_keys(self, text: str) -> list[str]:
        """词条名 / 组名 → 内部 key 列表（组名会展开成多条；数值表里没有的行不算）。"""
        keys = self.group_keys(text)
        if keys is not None:
            return keys
        key = self.resolve_name(text)
        return [key] if (key and key in self.by_key) else []

    # --- 主词条候选 ---
    def main_candidates(self, slot: int) -> list[tuple[int, float]]:
        """返回该部位可出的主词条 [(stat_id, 权重)]。"""
        fixed = self.cfg["fixed_main"]
        if slot in fixed:
            sid = fixed[slot]
            return [(sid, 1.0)] if sid in self.by_id else []
        field = {2: "w_sand", 3: "w_cup", 4: "w_head"}.get(slot)
        if field is None:
            return []
        out = []
        for s in self.stats:
            if not s.get("enabled", True):
                continue
            w = float(s.get(field, 0) or 0)
            if w > 0:
                out.append((s["id"], w))
        return out

    # --- 副词条候选 ---
    def sub_candidates(self, exclude_ids: set[int]) -> list[tuple[int, float]]:
        out = []
        for s in self.stats:
            if not s.get("enabled", True):
                continue
            if s["id"] in exclude_ids:
                continue
            w = float(s.get("w_sub", 0) or 0)
            if w > 0:
                out.append((s["id"], w))
        return out


# --------------------------------------------------------------------------
def format_value(sid: int, value: float, table: "StatTable", digits: int = 2) -> str:
    """按词条类型格式化数值。"""
    if table.is_pct(sid):
        return ("%." + str(digits) + "f%%") % (value * 100.0)
    if abs(value - round(value)) < 1e-9:
        return "%d" % round(value)
    return ("%." + str(digits) + "f") % value
