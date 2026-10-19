# -*- coding: utf-8 -*-
"""核心玩法引擎：获取圣遗物、强化、祝圣之霜定义、启圣之尘重塑。"""
from __future__ import annotations

import random

from .config import StatTable, format_value
from .model import VEC_SIZE, AppState, Artifact, fmt_num


# ---------------------------------------------------------------- 随机工具
def weighted_pick(pairs, rng: random.Random):
    """pairs: [(value, weight), ...] -> value"""
    items = [(v, float(w)) for v, w in pairs if float(w) > 0]
    if not items:
        return None
    total = sum(w for _, w in items)
    r = rng.random() * total
    acc = 0.0
    for v, w in items:
        acc += w
        if r <= acc:
            return v
    return items[-1][0]


def _growth_value(cfg: dict, which: str, rng: random.Random) -> float:
    """抽取一次成长数值。which ∈ {init, upgrade}"""
    mode = cfg.get("%s_growth_mode" % which, "tiers")
    tiers = cfg.get("%s_growth_tiers" % which) or [1.0]
    tiers = [float(t) for t in tiers]
    if mode == "uniform" and len(tiers) >= 2:
        lo, hi = min(tiers), max(tiers)
        return rng.uniform(lo, hi)
    return rng.choice(tiers)


def init_growth(cfg, rng):
    return _growth_value(cfg, "init", rng)


def upgrade_growth(cfg, rng):
    return _growth_value(cfg, "upgrade", rng)


def _empty_vec(cfg: dict) -> list:
    return [0] * VEC_SIZE


def _set(art: Artifact, key: str, value):
    art.set(key, value)


# ---------------------------------------------------------------- 主词条
def roll_main_stat(cfg: dict, table: StatTable, slot: int, rng: random.Random) -> int:
    cands = table.main_candidates(slot)
    if not cands:
        raise ValueError("部位 %d 没有可用的主词条，请检查数值表的权重列。" % slot)
    return int(weighted_pick(cands, rng))


def roll_slot(cfg: dict, rng: random.Random) -> int:
    probs = cfg.get("slot_prob") or [0.2] * 5
    return int(weighted_pick(list(enumerate([float(p) for p in probs])), rng))


def roll_initial_sub_count(cfg: dict, rng: random.Random) -> int:
    weights = cfg.get("init_sub_weights") or {"3": 2.0, "4": 1.0}
    pairs = [(int(k), float(v)) for k, v in weights.items()]
    return int(weighted_pick(pairs, rng))


# ---------------------------------------------------------------- 生成
def _fill_substats(art: Artifact, cfg: dict, table: StatTable,
                   presets: list[int], target_count: int, rng: random.Random) -> None:
    """把副词条槽填到 target_count 个；presets 里的词条排在前面。

    4 个槽位**总是填满**（prefill）：多出来的那些就是「未激活词条」——
    它们已经定好了名字和初始成长（这样界面才能显示「未激活：暴击率」并高亮），
    但 cur_sub_count / init_sub_count 仍然只算 target_count，所以不计分、不算成长；
    强化到 +4 时 `_enhance_event` 直接把它们启用，分布与「+4 时才抽」完全一致。
    """
    used = {art.main_id}
    chosen: list[int] = []
    for sid in presets:
        if sid and sid not in used:
            used.add(sid)
            chosen.append(int(sid))
    visible = max(0, min(4, int(target_count)))
    while len(chosen) < 4:
        cands = table.sub_candidates(used)
        if not cands:
            break
        sid = int(weighted_pick(cands, rng))
        if sid in used:
            continue
        used.add(sid)
        chosen.append(sid)
    for i in range(4):
        if i < len(chosen):
            art.set_sub_id(i, chosen[i])
            art.set_init_g(i, init_growth(cfg, rng))
            art.set_up_g(i, 0.0)
        else:
            art.set_sub_id(i, 0)
            art.set_init_g(i, 0.0)
            art.set_up_g(i, 0.0)
    vis = min(visible, len(chosen))
    art.cur_sub_count = vis
    art.set("init_sub_count", vis)


def pending_indices(art: Artifact) -> list[int]:
    """还没激活、但已经预生成好词条的槽位。"""
    return [i for i in range(4) if i >= art.cur_sub_count and art.sub_id(i) > 0]


def has_pending(art: Artifact) -> bool:
    return bool(pending_indices(art))


def ensure_pending(art: Artifact, cfg: dict, table: StatTable, rng: random.Random) -> int:
    """给「未满 4 条、但槽位还空着」的圣遗物补上未激活词条，返回补了几条。

    老存档（或手改过的向量）里可能没有预生成的第 4 条；打开「显示未激活词条」
    时用这个补齐，分布与获取时抽第 4 条完全一致（同样排除主词条和已有副词条）。
    """
    n = 0
    for i in range(4):
        if i < art.cur_sub_count or art.sub_id(i) > 0:
            continue
        used = {art.main_id} | {art.sub_id(j) for j in range(4) if art.sub_id(j) > 0}
        cands = table.sub_candidates(used)
        if not cands:
            break
        sid = int(weighted_pick(cands, rng))
        art.set_sub_id(i, sid)
        art.set_init_g(i, init_growth(cfg, rng))
        art.set_up_g(i, 0.0)
        n += 1
    return n


def activate_pending(art: Artifact) -> int:
    """把已经预生成好的未激活词条直接启用（不改等级），返回启用了几条。"""
    n = 0
    i = int(art.cur_sub_count)
    while i < 4 and art.sub_id(i) > 0:
        i += 1
        n += 1
    art.cur_sub_count = i
    return n


def _total_upgrade_events(cfg: dict, init_sub_count: int) -> int:
    """从 0 级强化到满级，一共会发生多少次「副词条强化判定」。"""
    interval = max(1, int(cfg.get("enhance_interval", 4)))
    maxlv = int(cfg["main_stat_formula"].get("max_level", 20))
    return maxlv // interval


def total_upgrade_rolls(cfg: dict, init_sub_count: int) -> int:
    """其中真正落在「已满 4 条」上的次数（也就是会加成长值的次数）。"""
    return max(0, _total_upgrade_events(cfg, init_sub_count) - (4 - int(init_sub_count)))


def create_random_artifact(cfg: dict, table: StatTable, rng: random.Random,
                           slot: int | None = None,
                           set_id: int | None = None) -> Artifact:
    """按规则随机获取一件圣遗物（0 级）。"""
    if slot is None:
        slot = roll_slot(cfg, rng)
    sets = cfg.get("sets") or ["未知套装"]
    if set_id is None:
        set_id = rng.randrange(len(sets))
    main_id = roll_main_stat(cfg, table, slot, rng)
    n_sub = roll_initial_sub_count(cfg, rng)

    vec = _empty_vec(cfg)
    art = Artifact(vec, cfg, table, source="随机获取")
    art.set("set", int(set_id))
    art.set("slot", int(slot))
    art.set("main", int(main_id))
    art.set("level", 0)
    art.set("define1", 0)
    art.set("define2", 0)
    _fill_substats(art, cfg, table, [], n_sub, rng)
    return art


def create_elixir_artifact(cfg: dict, table: StatTable, rng: random.Random,
                           set_id: int, slot: int, main_id: int,
                           sub_a: int, sub_b: int,
                           state: AppState | None = None) -> tuple[Artifact, int]:
    """用祝圣之霜定义一件圣遗物。返回 (圣遗物, 消耗霜数)。"""
    el = cfg.get("elixir") or {}
    cost = int((el.get("cost") or {}).get(str(slot), 1))
    if state is not None:
        state.elixir_used += cost

    if slot in cfg["fixed_main"]:
        main_id = cfg["fixed_main"][slot]
    presets = [int(sub_a), int(sub_b)]
    presets = [x for x in presets if x > 0 and x != main_id]
    if len(presets) < 2:
        raise ValueError("必须定义两个与主词条不同的副词条。")
    presets = presets[:2]

    # 初始副词条数：默认与「获取新圣遗物」用同一套分布；
    # 只有在 elixir.force_initial_sub_count 填了 3/4 时才强制。
    forced = int(el.get("force_initial_sub_count", 0) or 0)
    target = forced if forced else roll_initial_sub_count(cfg, rng)
    target = max(len(presets), min(4, target))

    art = Artifact(_empty_vec(cfg), cfg, table, source="祝圣之霜定义")
    art.set("set", int(set_id))
    art.set("slot", int(slot))
    art.set("main", int(main_id))
    art.set("level", 0)
    art.set("define1", int(presets[0]))
    art.set("define2", int(presets[1]))
    _fill_substats(art, cfg, table, presets, target, rng)

    # 保底：定义的两个副词条合计至少命中 N 次
    art.force_group = [0, 1] if target >= 2 else [0]
    art.force_min = int(el.get("min_total_hits", 2))
    art.force_hits = 0
    art.note = "祝圣之霜：%s / %s" % (table.display(presets[0]), table.display(presets[1]))
    return art, cost


# ---------------------------------------------------------------- 强化
def _remaining_upgrade_events(art: Artifact, cfg: dict) -> int:
    """本次判定之后还会发生多少次「已满 4 条」的判定。"""
    interval = max(1, int(cfg.get("enhance_interval", 4)))
    maxlv = int(cfg["main_stat_formula"].get("max_level", 20))
    return max(0, (maxlv - art.level) // interval)


def choose_upgrade_target(art: Artifact, cfg: dict, table: StatTable, rng: random.Random) -> int:
    """选择这一次强化命中哪一条副词条（考虑保底）。"""
    n = max(1, min(4, art.cur_sub_count))
    idxs = [i for i in range(n) if art.sub_id(i) > 0]
    if not idxs:
        return 0
    weights = {}
    for i in idxs:
        s = table.get(art.sub_id(i))
        weights[i] = float(s.get("w_hit", 1) or 0) if s else 1.0
        if weights[i] <= 0:
            weights[i] = 1.0

    group = [i for i in art.force_group if i in idxs]
    need = art.force_min - art.force_hits
    remain_after = _remaining_upgrade_events(art, cfg)

    if group and need > remain_after:
        pool = group
    else:
        pool = idxs
    target = int(weighted_pick([(i, weights[i]) for i in pool], rng))
    if target is None:
        target = idxs[0]
    if target in group:
        art.force_hits += 1
    return target


def _enhance_event(art: Artifact, cfg: dict, table: StatTable, rng: random.Random) -> dict:
    """处理一次「每 4 级」的副词条判定。"""
    lvl = art.level
    if art.cur_sub_count < 4:
        i = int(art.cur_sub_count)
        if art.sub_id(i) > 0:
            # 这条词条在获取时就预生成了（「未激活词条」），这里直接启用
            sid = art.sub_id(i)
            art.cur_sub_count = i + 1
            return {
                "level": lvl, "kind": "new", "index": i, "stat": sid,
                "text": "+%d：新增副词条 %s（初始成长 %s）" % (
                    lvl, table.display(sid), fmt_num(art.init_g(i), 2)),
            }
        used = {art.main_id} | {art.sub_id(k) for k in range(4) if art.sub_id(k) > 0}
        cands = table.sub_candidates(used)
        if not cands:
            return {"level": lvl, "kind": "none", "text": "+%d：没有可抽取的副词条" % lvl}
        sid = int(weighted_pick(cands, rng))
        art.set_sub_id(i, sid)
        art.set_init_g(i, init_growth(cfg, rng))
        art.set_up_g(i, 0.0)
        art.cur_sub_count = i + 1
        return {
            "level": lvl, "kind": "new", "index": i, "stat": sid,
            "text": "+%d：新增副词条 %s（初始成长 %s）" % (
                lvl, table.display(sid), fmt_num(art.init_g(i), 2)),
        }
    i = choose_upgrade_target(art, cfg, table, rng)
    g = upgrade_growth(cfg, rng)
    art.add_up_g(i, g)
    return {
        "level": lvl, "kind": "up", "index": i, "stat": art.sub_id(i), "gain": g,
        "text": "+%d：%s 成长 +%s（总成长 %s）" % (
            lvl, table.display(art.sub_id(i)), fmt_num(g, 2), fmt_num(art.total_g(i), 2)),
    }


def advance(art: Artifact, target_level: int, cfg: dict, table: StatTable,
            rng: random.Random) -> list[dict]:
    """把圣遗物强化到 target_level 级，返回过程中发生的事件。"""
    interval = max(1, int(cfg.get("enhance_interval", 4)))
    maxlv = int(cfg["main_stat_formula"].get("max_level", 20))
    target_level = int(min(max(target_level, art.level), maxlv))
    events = []
    while art.level < target_level:
        art.level = art.level + 1
        if art.level % interval == 0:
            ev = _enhance_event(art, cfg, table, rng)
            ev["text"] = ev.get("text", "")
            events.append(ev)
            art.history.append(ev["text"])
    if events:
        art.history.append("→ 强化至 +%d" % art.level)
    return events


# ---------------------------------------------------------------- 启圣之尘
def dust_guarantee(art: Artifact, cfg: dict, state: AppState, cost: int) -> tuple[int, bool]:
    """消耗启圣之尘后，本次重塑的保底次数与是否触发进度回退。

    保底只在「本次消耗把进度推过阈值」的那一次生效：

    * 进度 + 消耗数 首次达到 6 / 12 → 所选两条合计至少命中 3 次
    * 进度 + 消耗数 首次达到 18     → 至少命中 4 次，随后进度减去 18

    阈值之间的那些消耗不带进度保底（只有祝圣之霜定义的圣遗物仍带 2 次）。
    """
    d = cfg.get("dust") or {}
    state.dust_used += cost
    before = int(state.dust_progress)
    after = before + int(cost)
    state.dust_progress = after

    hit4 = int(d.get("hit4_threshold", 18))
    hit3s = sorted(int(x) for x in (d.get("hit3_thresholds") or [6, 12]))

    def crossed(t: int) -> bool:
        return t > 0 and before < t <= after

    reset = False
    if crossed(hit4):
        need = int(d.get("hit4_min_total", 4))
        reset = True
    elif any(crossed(t) for t in hit3s):
        need = int(d.get("hit3_min_total", 3))
    else:
        # 每次使用启圣之尘都至少带这么多命中保底（祝圣之霜定义件同样适用）
        need = int(d.get("min_total_hits", 2))

    # 减去 18（多出的部分顺延到下一轮），保证进度始终落在 [0, 18)
    if hit4 > 0 and d.get("reset_on_hit4", True) and state.dust_progress >= hit4:
        state.dust_progress -= hit4 * (state.dust_progress // hit4)
    return need, reset


def sub_snapshot(art: Artifact) -> dict:
    """记录一件圣遗物当前的四条副词条与成长（不占向量维度）。"""
    return {
        "sub_ids": [art.sub_id(i) for i in range(4)],
        "init_g": [art.init_g(i) for i in range(4)],
        "up_g": [art.up_g(i) for i in range(4)],
        "force_group": list(art.force_group),
        "force_min": art.force_min,
        "force_hits": art.force_hits,
    }


def apply_sub_snapshot(art: Artifact, snap: dict) -> None:
    """把一份副词条快照写回圣遗物（不改历史）。"""
    for i in range(4):
        art.set_sub_id(i, snap["sub_ids"][i])
        art.set_init_g(i, snap["init_g"][i])
        art.set_up_g(i, snap["up_g"][i])
    art.force_group = list(snap.get("force_group") or [])
    art.force_min = int(snap.get("force_min") or 0)
    art.force_hits = int(snap.get("force_hits") or 0)


def dust_locked_indices(art: Artifact) -> list[int]:
    """祝圣之霜定义件被锁定的那两条副词条下标；不是定义件（或对不上）就返回 []。"""
    if art is None or not art.is_elixir:
        return []
    defs = set(art.define_ids)
    got = [i for i in art.active_indices() if art.sub_id(i) in defs]
    return got if len(got) == 2 else []


def redeem_dust(art: Artifact, cfg: dict, table: StatTable, rng: random.Random,
                chosen: list[int], state: AppState, decide=None) -> dict:
    """使用启圣之尘重新强化一件满级圣遗物上指定的两条副词条。

    ``decide`` 是可选回调，签名为 ``decide(info) -> "before" | "after"``；
    它在重掷完成后、结果落定之前被调用，用来让调用方（界面）选择
    采用重塑前还是重塑后的副词条。返回 ``"before"`` 时会把副词条还原。
    """
    maxlv = art.max_level
    if art.level < maxlv:
        raise ValueError("只有满级（+%d）的圣遗物才能使用启圣之尘。" % maxlv)
    chosen = sorted({int(i) for i in chosen if 0 <= int(i) < 4 and art.sub_id(int(i)) > 0})
    if len(chosen) != 2:
        raise ValueError("请选择两条副词条。")

    # 祝圣之霜定义件：要重新强化的必然就是当初定义的那两条，不接受外部指定
    locked = dust_locked_indices(art)
    if len(locked) == 2:
        chosen = list(locked)

    d = cfg.get("dust") or {}
    cost = int((d.get("cost") or {}).get(str(art.slot), 2))
    need, reset = dust_guarantee(art, cfg, state, cost)

    n_rolls = total_upgrade_rolls(cfg, art.init_sub_count)
    need = max(0, min(need, n_rolls))

    before = sub_snapshot(art)
    n_hist = len(art.history)

    # 清空升级成长，重新分配命中
    for i in range(4):
        art.set_up_g(i, 0.0)
    art.force_group = list(chosen)
    art.force_min = need
    art.force_hits = 0

    hits = []
    for k in range(n_rolls):
        art.level = maxlv           # 让 _remaining_upgrade_events 计算出正确的剩余次数
        remain_after = n_rolls - k - 1
        group = [i for i in chosen if i in art.active_indices()]
        deficit = need - art.force_hits
        pool = group if (group and deficit > remain_after) else art.active_indices()
        if not pool:
            break
        i = int(weighted_pick([(x, 1.0) for x in pool], rng))
        g = upgrade_growth(cfg, rng)
        art.add_up_g(i, g)
        if i in chosen:
            art.force_hits += 1
        hits.append({"level": maxlv, "kind": "up", "index": i, "stat": art.sub_id(i), "gain": g})

    text = "启圣之尘重塑：消耗 %d 个，保底命中 %d 次，实际命中 %d 次" % (
        cost, need, art.force_hits)
    if reset:
        text += "；圣言解名进度达到 %d，已减去 %d" % (
            int(d.get("hit4_threshold", 18)), int(d.get("hit4_threshold", 18)))
    art.history.append(text)

    after = sub_snapshot(art)
    info = {"cost": cost, "need": need, "hits": art.force_hits, "rolls": n_rolls,
            "reset": reset, "events": hits, "text": text, "chosen": list(chosen),
            "before": before, "after": after, "kept": "after"}

    if decide is not None:
        keep = str(decide(info) or "after").strip().lower()
        if keep.startswith("before"):
            apply_sub_snapshot(art, before)
            del art.history[n_hist:]
            art.history.append("启圣之尘重塑：保留了重塑前的结果（"
                               "本次消耗 %d 个，圣言解名进度已计入）" % cost)
            info["kept"] = "before"
    return info


def simulate_to_max(cfg: dict, table: StatTable, rng: random.Random, art: Artifact) -> Artifact:
    advance(art, art.max_level, cfg, table, rng)
    return art
