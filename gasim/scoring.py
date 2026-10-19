# -*- coding: utf-8 -*-
"""评分模块。

规则文本格式（每行一条，也可以一行写完整个套装）::

    套装名：词条名 主词条高亮 主词条得分系数 副词条权重
    例：来歆余响：暴击伤害 1 1.5 7.775

- 主词条高亮：> 0 就把该词条作为主词条时加 ★ / 变色；0 = 不高亮（得分照算）。
- 主词条得分系数：主词条得分 = 等级 × 该系数。
- 副词条权重：每条命中该词条的副词条按它计分。
- 省略时：主词条得分系数按 1，副词条权重按主词条得分系数。
- 词条名也可以写组名「各元素伤害加成」，等于把七种元素伤害加成一次写全。
- 全局开关（自定义 → 参数）：``score_enabled`` 关掉后所有评分都返回 0；
  ``score_hl_main`` / ``score_hl_sub`` 只控制 ★ 高亮，不影响得分。

最终得分 = Σ(主词条得分 + 副词条得分)
- 作为主词条：等级 × 主词条得分系数（与是否高亮无关，+0 时得 0 分）
- 作为副词条：副词条权重 × 总成长（value 模式下乘实际数值）
"""
from __future__ import annotations

SEP_SET = "：:"
SEP_RULE = "，,;；"


def rule_parts(rule) -> tuple[str, float, float, float] | None:
    """把一条规则拆成 (名称, 主词条高亮, 主词条得分系数, 副词条权重)。"""
    if not rule or len(rule) < 2:
        return None
    name = str(rule[0])
    try:
        hl = float(rule[1])
        ms = float(rule[2]) if len(rule) >= 3 else 1.0
        sw = float(rule[3]) if len(rule) >= 4 else ms
    except (TypeError, ValueError):
        return None
    return name, hl, ms, sw


def rules_for_set(cfg: dict, set_name: str) -> list:
    sc = cfg.get("scoring") or {}
    sets = sc.get("sets") or {}
    rules = sets.get(set_name)
    if rules is None:
        rules = sc.get("default") or []
    return rules


def apply_template_to_all(cfg: dict, template: list | None = None) -> None:
    """把默认模板套用到所有套装。"""
    sc = cfg.setdefault("scoring", {"default": [], "sets": {}})
    if template is None:
        template = sc.get("default") or []
    for s in cfg.get("sets", []):
        sc.setdefault("sets", {})[s] = [list(r) for r in template]


def is_enabled(cfg: dict) -> bool:
    """全局开关：关掉后所有评分都按 0 返回。"""
    return bool(cfg.get("score_enabled", True))


def rule_pairs(cfg: dict, table, set_name: str) -> list[tuple[str, float, float, float]]:
    """该套装规则里真正生效的条目 [(显示名, 高亮, 主词条得分系数, 副词条权重)]。"""
    out: list[tuple[str, float, float, float]] = []
    for rule in rules_for_set(cfg, set_name):
        p = rule_parts(rule)
        if p is None:
            continue
        name, hl, ms, sw = p
        keys = table.resolve_keys(name)
        if not keys:
            continue
        disp = table.group_name(name) or table.display(table.by_key[keys[0]]["id"])
        out.append((disp, hl, ms, sw))
    return out


def weight_map(cfg: dict, table, set_name: str) -> dict[str, tuple[float, float, float]]:
    """{词条 key: (高亮, 主词条得分系数, 副词条权重)}，只含这个套装认得的词条。"""
    out: dict[str, tuple[float, float, float]] = {}
    for rule in rules_for_set(cfg, set_name):
        p = rule_parts(rule)
        if p is None:
            continue
        name, hl, ms, sw = p
        for key in table.resolve_keys(name):
            if key in table.by_key:
                out[key] = (hl, ms, sw)
    return out


def score_artifact(art, cfg: dict, table, rules: list | None = None) -> dict:
    """计算一件圣遗物的得分，返回含明细的字典。"""
    if rules is None:
        rules = rules_for_set(cfg, art.set_name)
    mode = cfg.get("score_mode", "growth")
    enabled = is_enabled(cfg)
    hl_main_on = bool(cfg.get("score_hl_main", True))
    hl_sub_on = bool(cfg.get("score_hl_sub", True))
    by_key = table.by_key

    total = 0.0
    breakdown: list[dict] = []
    scoring_keys: set[str] = set()      # 高亮或得分为正，算「算分词条」
    useful_keys: set[str] = set()       # 副权重 > 0，算「有效词条」
    weights: dict[str, tuple[float, float, float]] = {}

    for rule in ([ ] if not enabled else rules):
        p = rule_parts(rule)
        if p is None:
            continue
        name, hl, ms, sw = p
        for key in table.resolve_keys(name):
            if key not in by_key:
                continue
            weights[key] = (hl, ms, sw)
            if hl > 0 or ms or sw > 0:
                scoring_keys.add(key)
            if sw > 0:
                useful_keys.add(key)
            sid = by_key[key]["id"]

            if art.main_id == sid and ms:
                # 主词条得分 = 等级 × 主词条得分系数（与高亮开关无关）
                part = ms * art.level
                if part:
                    total += part
                    breakdown.append({"kind": "主词条", "key": key, "name": table.display(sid),
                                      "detail": "等级 %d × %s" % (art.level, _n(ms)),
                                      "score": part})

            if sw > 0:
                for i in art.active_indices():
                    if art.sub_id(i) != sid:
                        continue
                    part = sw * (art.sub_value(i) if mode == "value" else art.total_g(i))
                    if part:
                        total += part
                        breakdown.append({"kind": "副词条", "key": key, "name": table.display(sid),
                                          "detail": "第%d条 总成长 %s" % (i + 1, art.total_g(i)),
                                          "score": part})

    all_rolls = sum(art.total_g(i) for i in art.active_indices())
    useful_rolls = sum(art.total_g(i) for i in art.active_indices()
                       if table.key_of(art.sub_id(i)) in useful_keys)
    sub_hits = [bool(enabled and hl_sub_on and art.sub_id(i) > 0
                     and table.key_of(art.sub_id(i)) in useful_keys)
                for i in range(4)]
    main_hl, main_ms, _main_sw = weights.get(table.key_of(art.main_id), (0.0, 0.0, 0.0))
    return {
        "total": total,
        "breakdown": breakdown,
        "rolls": all_rolls,
        "useful_rolls": useful_rolls if enabled else 0.0,
        "mode": mode,
        "set_name": art.set_name,
        "rules": rules,
        "enabled": enabled,                     # 全局开关
        # 下面几项给界面显示用：
        "weights": weights,                     # key -> (高亮, 主得分系数, 副权重)
        "scoring_keys": sorted(scoring_keys),
        "useful_keys": sorted(useful_keys),
        # 这件圣遗物的主词条要不要高亮（规则第 2 个数 + 全局开关）
        "main_hl": bool(enabled and hl_main_on and main_hl > 0),
        "main_scored": bool(main_ms != 0),      # 主词条是否计分
        "sub_hits": sub_hits,
    }


# ---------------------------------------------------------------- 解析 / 输出
def parse_rules(text: str, table) -> tuple[dict, list[str]]:
    """解析规则文本，返回 ({套装名: [[名, 高亮, 主得分系数, 副权重], ...]}, 警告列表)。"""
    out: dict[str, list] = {}
    warns: list[str] = []
    if not text:
        return out, warns
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        # 拆出套装名
        cut = -1
        for ch in SEP_SET:
            p = line.find(ch)
            if p >= 0 and (cut < 0 or p < cut):
                cut = p
        if cut < 0:
            warns.append("缺少冒号，整行按「通用」处理：%s" % line)
            set_name, rest = "通用", line
        else:
            set_name = line[:cut].strip()
            rest = line[cut + 1:].strip()
        # 拆出多条规则
        parts = [rest]
        for ch in SEP_RULE:
            newparts = []
            for p in parts:
                newparts.extend(p.split(ch))
            parts = newparts
        rules = out.setdefault(set_name, [])
        for p in parts:
            p = p.strip()
            if not p:
                continue
            tokens = p.replace("\t", " ").split(" ")
            tokens = [t for t in tokens if t != ""]
            if len(tokens) < 2:
                warns.append("规则片段无法解析（需要「词条名 高亮 主得分系数 [副权重]」）：%s" % p)
                continue
            name = tokens[0]
            try:
                hl = float(tokens[1])
                ms = float(tokens[2]) if len(tokens) >= 3 else None
                sw = float(tokens[3]) if len(tokens) >= 4 else None
            except ValueError:
                warns.append("权重不是数字：%s" % p)
                continue
            if len(tokens) > 4:
                warns.append("多出的数字被忽略（最多 4 个）：%s" % p)
            if not table.resolve_keys(name):
                warns.append("未知词条名：%s（已保留，评分时会忽略）" % name)
            ms = 1.0 if ms is None else ms
            rules.append([name, hl, ms, ms if sw is None else sw])
    return out, warns


def rules_to_text(rules_by_set: dict) -> str:
    lines = []
    for set_name, rules in rules_by_set.items():
        if not rules:
            continue
        lines.append("%s：%s" % (set_name, rules_body(rules)))
    return "\n".join(lines)


def rules_body(rules) -> str:
    """一组规则拼成「暴击率 1 0.1 2，暴击伤害 1 0.1 2」这样的正文。"""
    return "，".join(_rule_text(r) for r in (rules or []))


def _rule_text(rule) -> str:
    p = rule_parts(rule)
    if p is None:
        return str(rule[0])
    name, hl, ms, sw = p
    return "%s %s %s %s" % (name, _n(hl), _n(ms), _n(sw))


def _n(x) -> str:
    f = float(x)
    return str(int(f)) if f == int(f) else ("%g" % f)
