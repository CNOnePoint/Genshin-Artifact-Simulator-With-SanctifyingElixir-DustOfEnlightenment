# -*- coding: utf-8 -*-
"""圣遗物数据模型。

圣遗物以 20 维向量存储（维度含义见 config.DEFAULT_VECTOR_LAYOUT，可自定义）。
"""
from __future__ import annotations

import json
import os

from .config import StatTable, format_value, piece_name, substat_divisor_for

VEC_SIZE = 20


def fmt_num(x: float, digits: int = 2) -> str:
    """去掉多余小数尾零的数字格式化。"""
    if x is None:
        return "—"
    s = ("%." + str(digits) + "f") % float(x)
    s = s.rstrip("0").rstrip(".")
    return s if s not in ("", "-") else "0"


class Artifact:
    """一件圣遗物。所有数据都落在 20 维向量 self.vec 里。"""

    def __init__(self, vec, cfg: dict, table: StatTable, uid: int = 0,
                 force_group=None, force_min: int = 0, force_hits: int = 0,
                 source: str = "随机获取", note: str = "", history=None):
        self.cfg = cfg
        self.table = table
        self.vec = [0] * VEC_SIZE
        for i, v in enumerate(list(vec)[:VEC_SIZE]):
            self.vec[i] = v
        self.uid = int(uid or 0)
        self.source = source
        self.note = note
        # 保底命中信息（不占向量维度，属于生成时的附加约束）
        self.force_group = [int(x) for x in (force_group or [])]
        self.force_min = int(force_min)
        self.force_hits = int(force_hits)
        self.history = list(history or [])
        self._rebuild()

    # ---------------------------------------------------------------- 索引
    def _rebuild(self):
        self.idx = {d["key"]: i for i, d in enumerate(self.cfg["vector_layout"])}

    def get(self, key, default=0):
        i = self.idx.get(key)
        return self.vec[i] if i is not None else default

    def set(self, key, value):
        i = self.idx.get(key)
        if i is not None:
            self.vec[i] = value

    # ---------------------------------------------------------------- 属性
    @property
    def set_id(self) -> int:
        return int(self.get("set"))

    @property
    def set_name(self) -> str:
        sets = self.cfg.get("sets") or []
        s = self.set_id
        return sets[s] if 0 <= s < len(sets) else "未知套装(%d)" % s

    @property
    def slot(self) -> int:
        return int(self.get("slot"))

    @property
    def slot_name(self) -> str:
        slots = self.cfg.get("slots") or []
        s = self.slot
        return slots[s] if 0 <= s < len(slots) else "部位%d" % s

    @property
    def piece_name(self) -> str:
        """这件圣遗物的「圣遗物名称」（套装里对应部位的部件名）。"""
        return piece_name(self.cfg, self.set_name, self.slot)

    @property
    def main_id(self) -> int:
        return int(self.get("main"))

    @property
    def main_name(self) -> str:
        return self.table.display(self.main_id)

    @property
    def level(self) -> int:
        return int(self.get("level"))

    @level.setter
    def level(self, v):
        self.set("level", int(v))

    @property
    def max_level(self) -> int:
        return int(self.cfg["main_stat_formula"].get("max_level", 20))

    @property
    def init_sub_count(self) -> int:
        return int(self.get("init_sub_count"))

    @property
    def cur_sub_count(self) -> int:
        return int(self.get("cur_sub_count"))

    @cur_sub_count.setter
    def cur_sub_count(self, v):
        self.set("cur_sub_count", int(v))

    @property
    def define_ids(self) -> list[int]:
        """祝圣之霜定义的副词条 id（最多 2 个）。"""
        return [int(x) for x in (self.get("define1"), self.get("define2")) if int(x) > 0]

    @property
    def is_elixir(self) -> bool:
        return bool(self.define_ids)

    def sub_id(self, i: int) -> int:
        return int(self.get("sub%d" % (i + 1)))

    def set_sub_id(self, i: int, sid: int):
        self.set("sub%d" % (i + 1), int(sid))

    def init_g(self, i: int) -> float:
        return float(self.get("init_g%d" % (i + 1)))

    def set_init_g(self, i: int, v: float):
        self.set("init_g%d" % (i + 1), float(v))

    def up_g(self, i: int) -> float:
        return float(self.get("up_g%d" % (i + 1)))

    def add_up_g(self, i: int, v: float):
        self.set("up_g%d" % (i + 1), self.up_g(i) + float(v))

    def set_up_g(self, i: int, v: float):
        self.set("up_g%d" % (i + 1), float(v))

    def total_g(self, i: int) -> float:
        return self.init_g(i) + self.up_g(i)

    @property
    def sub_ids(self) -> list[int]:
        return [self.sub_id(i) for i in range(4)]

    def active_indices(self) -> list[int]:
        n = self.cur_sub_count
        if n <= 0:
            n = sum(1 for i in range(4) if self.sub_id(i) > 0)
        return [i for i in range(min(4, max(0, n))) if self.sub_id(i) > 0]

    def is_active_sub(self, i: int) -> bool:
        """第 i 条副词条是不是「已激活」的（在 cur_sub_count 之内）。"""
        return 0 <= i < self.cur_sub_count and self.sub_id(i) > 0

    def pending_indices(self) -> list[int]:
        """未激活词条的槽位：已经预生成好、但还没启用的那些。"""
        return [i for i in range(4) if i >= self.cur_sub_count and self.sub_id(i) > 0]

    def has_pending(self) -> bool:
        return bool(self.pending_indices())

    def show_inactive(self) -> bool:
        return bool(self.cfg.get("show_inactive_subs", False))

    # ---------------------------------------------------------------- 数值
    def main_value(self) -> float:
        f = self.cfg["main_stat_formula"]
        base = float(f.get("base", 0.15))
        span = float(f.get("span", 0.85))
        mx = float(f.get("max_level", 20)) or 20.0
        return self.table.max_of(self.main_id) * (base + span * self.level / mx)

    def sub_value(self, i: int) -> float:
        sid = self.sub_id(i)
        div = substat_divisor_for(self.cfg, self.table.key_of(sid))
        return self.table.max_of(sid) * self.total_g(i) / div

    def sub_text(self, i: int, mark: str = "") -> str:
        sid = self.sub_id(i)
        if sid <= 0:
            return "—"
        if not self.is_active_sub(i):
            if not self.show_inactive():
                return "—"
            tg0 = self.total_g(i)
            return "[未激活 %s=%s+%s] %s%s +%s" % (
                fmt_num(tg0, 2), fmt_num(self.init_g(i), 2), fmt_num(self.up_g(i), 2),
                mark, self.table.display(sid),
                format_value(sid, self.sub_value(i), self.table))
        tg = self.total_g(i)
        s = "[%s=%s+%s] %s%s +%s" % (
            fmt_num(tg, 2), fmt_num(self.init_g(i), 2), fmt_num(self.up_g(i), 2),
            mark, self.table.display(sid),
            format_value(sid, self.sub_value(i), self.table),
        )
        return s

    def sub_text_plain(self, i: int, mark: str = "") -> str:
        sid = self.sub_id(i)
        if sid <= 0:
            return "—"
        if not self.is_active_sub(i):
            if not self.show_inactive():
                return "—"
            return "未激活·%s%s +%s" % (
                mark, self.table.display(sid),
                format_value(sid, self.sub_value(i), self.table))
        return "%s%s +%s" % (mark, self.table.display(sid),
                             format_value(sid, self.sub_value(i), self.table))

    # ---------------------------------------------------------------- 展示
    def describe_lines(self, hits: dict | None = None) -> list[str]:
        """hits: {"main": bool, 0..3: bool}，命中的词条前面加 ★（默认不加）。

        返回的固定顺序：0-2 类型/名称/套装，3 主词条，4 主词条数值，5 等级，
        6-9 副词条1-4，后面是若干条标记行——界面的高亮按这个位置取。
        """
        def _star(k):
            return "★" if (hits and hits.get(k)) else ""
        out = [
            "圣遗物类型：%s" % self.slot_name,
            "圣遗物名称：%s" % self.piece_name,
            "所属套装：%s" % self.set_name,
            "圣遗物主词条：%s%s" % (_star("main"), self.main_name),
            "圣遗物主词条数值：%s" % format_value(self.main_id, self.main_value(), self.table),
            "圣遗物等级：+%d" % self.level,
        ]
        for i in range(4):
            out.append("副词条%d：%s" % (i + 1, self.sub_text(i, _star(i))))
        flags = []
        if self.is_elixir:
            flags.append("祝圣之霜定义：%s" % "、".join(self.table.display(x) for x in self.define_ids))
        if self.force_group:
            flags.append("保底命中：%s（至少 %d 次，已 %d 次）" % (
                "、".join(self.table.display(self.sub_id(i)) for i in self.force_group if self.sub_id(i) > 0),
                self.force_min, self.force_hits))
        out.extend(flags)
        return out

    def describe(self) -> str:
        return "\n".join(self.describe_lines())

    def summary(self) -> str:
        parts = []
        for i in self.active_indices():
            parts.append(self.sub_text_plain(i))
        if self.show_inactive():
            for i in self.pending_indices():
                parts.append(self.sub_text_plain(i))
        return " / ".join(parts) if parts else "—"

    def vector_text(self) -> str:
        return "[" + ", ".join(
            (fmt_num(v, 3) if isinstance(v, float) and not float(v).is_integer() else str(int(v) if float(v).is_integer() else v))
            for v in self.vec
        ) + "]"

    # ---------------------------------------------------------------- 序列化
    def to_dict(self) -> dict:
        return {
            "uid": self.uid,
            "vec": self.vec,
            "force_group": self.force_group,
            "force_min": self.force_min,
            "force_hits": self.force_hits,
            "source": self.source,
            "note": self.note,
            "history": self.history,
        }

    @classmethod
    def from_dict(cls, d: dict, cfg: dict, table: StatTable) -> "Artifact":
        return cls(
            vec=d.get("vec") or [0] * VEC_SIZE,
            cfg=cfg, table=table,
            uid=d.get("uid", 0),
            force_group=d.get("force_group"),
            force_min=d.get("force_min", 0),
            force_hits=d.get("force_hits", 0),
            source=d.get("source", "随机获取"),
            note=d.get("note", ""),
            history=d.get("history"),
        )


class AppState:
    """全局状态：获取计数、祝圣之霜 / 启圣之尘用量与圣言解名进度。"""

    def __init__(self, elixir_used: int = 0, dust_used: int = 0, dust_progress: int = 0,
                 get_count: int = 0):
        self.elixir_used = int(elixir_used)      # 累计消耗的祝圣之霜
        self.dust_used = int(dust_used)          # 累计消耗的启圣之尘
        self.dust_progress = int(dust_progress)  # 圣言解名进度
        self.get_count = int(get_count)          # 累计获取到的圣遗物件数

    def to_dict(self) -> dict:
        return {
            "elixir_used": self.elixir_used,
            "dust_used": self.dust_used,
            "dust_progress": self.dust_progress,
            "get_count": self.get_count,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "AppState":
        d = d or {}
        return cls(d.get("elixir_used", 0), d.get("dust_used", 0),
                   d.get("dust_progress", 0), d.get("get_count", 0))


class Inventory:
    """圣遗物列表。"""

    def __init__(self, cfg: dict, table: StatTable, items=None, next_uid: int = 1):
        self.cfg = cfg
        self.table = table
        self.items: list[Artifact] = list(items or [])
        self.next_uid = int(next_uid)
        for a in self.items:
            a.cfg = cfg
            a.table = table
            a._rebuild()
        self.renumber()

    def renumber(self):
        """把编号重排成 1..N。

        列表一旦发生变更（新增 / 删除 / 读档）就重新编码，编号永远是紧凑的
        1..N，不会因为反复增删而越滚越大。
        """
        for i, a in enumerate(self.items, 1):
            a.uid = i
        self.next_uid = len(self.items) + 1

    def add(self, art: Artifact) -> Artifact:
        self.items.append(art)
        self.renumber()
        return art

    def remove(self, art: Artifact):
        try:
            self.items.remove(art)
        except ValueError:
            return
        self.renumber()

    def clear(self):
        self.items.clear()
        self.renumber()

    def get(self, uid: int) -> Artifact | None:
        for a in self.items:
            if a.uid == uid:
                return a
        return None

    def to_dict(self) -> dict:
        return {"next_uid": self.next_uid, "items": [a.to_dict() for a in self.items]}

    @classmethod
    def from_dict(cls, d: dict, cfg: dict, table: StatTable) -> "Inventory":
        d = d or {}
        items = [Artifact.from_dict(x, cfg, table) for x in d.get("items", [])]
        return cls(cfg, table, items, d.get("next_uid", 1))

    def load(self, d: dict, cfg: dict, table: StatTable):
        d = d or {}
        self.cfg = cfg
        self.table = table
        self.items = [Artifact.from_dict(x, cfg, table) for x in d.get("items", [])]
        self.renumber()
