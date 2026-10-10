"""整档 JSON 导入：把用户发来的档案文件读成 BOT 存档能用的形状。

为什么单独一个模块
------------------
``store.py`` 管「怎么存」，这里管「怎么认」。认文件这件事有一堆边界
（format 对不对、版本认不认、字段是不是越界），放在一起会把存档层淹掉。

只认 format，不猜
-----------------
与网页端 ``app/src/lib/importSniff.js`` 同一纪律：**认不出就明确报错**，
绝不「看着像档案」就当档案吃进来 —— 用户拖错文件时，沉默或猜错都比报错糟。

两种都认
--------
``nikke-photos-profile``
    网页端「存档管理 → 导出当前档案数据」的整档 JSON。字段名与 BOT 存档**完全一致**
    （``synchroLevel`` / ``research`` / ``characters[code]`` 里的 ``limitBreak``
    / ``affection`` / ``combat`` / ``skills`` / ``cube`` / ``favoriteItem`` /
    ``equipments``），所以这一路是一次搬运，不是一次翻译。

``nikke-photos-account``
    油猴脚本从 BlaBlaLink 抓的原始账号数据。给的是接口原样的 id 和数值
    （``cubeId`` / 研究所 ``tid`` / 收藏品 ``tid`` / 只给档位不给百分比），
    所以要多做一层 **id → 术语** 的映射。这一层是照
    ``app/src/lib/accountImport.js`` 移植的，判据要逐条对齐、别自行发挥 ——
    同一份文件在网页端和 BOT 这边必须得出同一个结果。

纪律：不编值
------------
文件里写 ``null`` 就是「导出时这项没填」，照原样存 ``None``，**不套默认值**。
``core/sharecode.py`` 的 ``apply_defaults`` 之所以补默认值，是因为分享码
**根本没带**这个字段（导出时没勾），补是唯一选择；而档案文件是带了值的，
用户发文件就是想让 BOT 读文件里的内容，这时候补默认值等于编数据。
"""
from __future__ import annotations

import json
import math

from . import gamedata
from . import store as store_mod

#: 网页端「存档管理 → 导出当前档案数据」的格式标识（真源见 app/src/lib/profileStore.js）
PROFILE_FORMAT = "nikke-photos-profile"
#: 油猴脚本导出的原始账号数据（真源见 app/public/nikke-photos-import.user.js）
ACCOUNT_FORMAT = "nikke-photos-account"

#: 与网页端一致的存档版本、账号数据版本与存档名长度上限
STORE_VERSION = 1
ACCOUNT_VERSION = 1
NAME_MAX = 30

#: 研究所等级：接口的 ``tid`` → 存档表里的 ``(组, 键)``。
#: ``1001``（通用研究）我们这边没有对应项，直接丢弃 —— 与网页端同一张表。
RESEARCH_BY_TID = {
    1101: ("class", "Attacker"),
    1102: ("class", "Defender"),
    1103: ("class", "Supporter"),
    1201: ("corporation", "ELYSION"),
    1202: ("corporation", "MISSILIS"),
    1203: ("corporation", "TETRA"),
    1204: ("corporation", "PILGRIM"),
    1205: ("corporation", "ABNORMAL"),
}

#: 正文字符数上限。QQ 上什么文件都可能发过来，先挡住明显不像档案的。
MAX_CHARS = 4 * 1024 * 1024


class ImportFileError(ValueError):
    """文件不可用。消息可以直接回给用户。"""


def _as_int(value):
    """与网页端 ``accountImport.asInt`` 同一判据：空 → ``None``，否则截断取整。

    ``'abc'`` / ``NaN`` / ``Infinity`` 一样给 ``None``（对应 JS 的
    ``Number.isFinite`` 那一关）。这样「接口给了个怪值」只会让这一项留空，
    不会污染别的字段。
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return int(number) if math.isfinite(number) else None


def _int_in_range(value, low: int, high: int) -> int | None:
    """受范围约束的整数；缺失或越界都返回 ``None``（不夹取、不编值）。"""
    number = _as_int(value)
    return number if number is not None and low <= number <= high else None


def _clean_name(raw) -> str:
    """存档名：去掉控制字符（会让回执排版乱掉）并截断到网页端同款上限。"""
    text = "".join(ch for ch in str(raw or "") if ch.isprintable()).strip()
    return text[:NAME_MAX]


def _ensure_shape(record: dict) -> dict:
    """补上渲染必需的**容器**字段（字典 / 列表），一律不动取值。

    手改过的文件可能少了 ``equipments`` 这类键，出图时就会炸；
    但容器里该是 ``None`` 的地方仍然是 ``None``。
    """
    for key in ("limitBreak", "skills"):
        if not isinstance(record.get(key), dict):
            record[key] = {}
    if not isinstance(record.get("equipments"), list):
        record["equipments"] = [[None, None, None] for _ in range(4)]
    return record


def _favorite_rarity(tid) -> str:
    """收藏品品质：从 ``favorite_item_tid`` 的位数规律推。

    规则移植自 NIKKE Workshop（那里是唯一验证过的实现），与网页端
    ``accountImport.favoriteRarityOf`` 逐字对齐：首位 2 → SSR；
    首位 1 且末位 1 → R、末位 2 → SR；其余（含 0 / 缺失）→ 不写这一项。
    """
    value = _as_int(tid)
    if value is None:
        return ""
    text = str(value)
    if not text or text == "0":
        return ""
    if text[0] == "2":
        return "SSR"
    if text[0] == "1" and text[-1] == "1":
        return "R"
    if text[0] == "1" and text[-1] == "2":
        return "SR"
    return ""


def _cube_by_cube_id(cube_id: int) -> dict | None:
    """``cubeId``（1000301…）→ ``assets/data/cubes.json`` 里那一条。

    两套编号都在表里，别用错：存档和出图认的是 ``resourceId``（10001…），
    拿 ``cubeId`` 去查资源永远查不到。表只有 17 条，线性扫足够。
    """
    for item in gamedata.cubes().values():
        if item.get("cubeId") == cube_id:
            return item
    return None


def _slot_lines(equipments, slot: int) -> list:
    """一个部位的三条词条，按 ``position`` 排进 3 槽数组。

    ``value`` 用**我们自己的档位表**推导（不采信接口给的那个百分比）：
    接口的数值和档位有时对不上，而卡片和练度统计都按档位表算合计，
    采信接口的值会让「有档位没有数值」的词条被算成不完整、卡片显示「—」。
    """
    source = equipments[slot] if isinstance(equipments, list) and slot < len(equipments) else []
    if not isinstance(source, list):
        source = []

    by_position: dict[int, dict] = {}
    for index, line in enumerate(source):
        if not isinstance(line, dict):
            continue
        position = _as_int(line.get("position"))
        if position is None:
            position = index + 1
        # 位置越界的不算词条；同一位置出现多条留首条（与网页端同一取向）
        if not 1 <= position <= 3 or position in by_position:
            continue
        by_position[position] = line

    lines: list = []
    for position in (1, 2, 3):
        line = by_position.get(position)
        function_type = str((line or {}).get("functionType") or "").strip()
        tier = _int_in_range((line or {}).get("level"),
                             store_mod.AFFIX_TIER_MIN, store_mod.AFFIX_TIER_MAX)
        value = gamedata.affix_tier_value(function_type, tier) if tier is not None else None
        lines.append(
            {"functionType": function_type, "level": tier, "value": value}
            if line is not None and gamedata.AFFIX_LABELS.get(function_type) and value is not None
            else None
        )
    return lines


def _account_record(entry: dict) -> dict:
    """一条账号记录 → 存档里的角色记录（对应 ``accountImport.toCharacterRecord``）。

    接口给的是 id 和原始数值，这里做 id → 术语的映射。越界一律写 ``None``，
    让「没填」和「填了 0」分得开 —— 网页端也是这个取向。
    """
    skills = entry.get("skills") if isinstance(entry.get("skills"), dict) else {}
    record = {
        "limitBreak": {
            "grade": _int_in_range(entry.get("grade"),
                                   store_mod.GRADE_MIN, store_mod.GRADE_MAX),
            "core": _int_in_range(entry.get("core"),
                                  store_mod.CORE_MIN, store_mod.CORE_MAX),
        },
        "affection": _int_in_range(entry.get("affection"),
                                   store_mod.AFFECTION_MIN, store_mod.AFFECTION_MAX),
        "combat": _int_in_range(entry.get("combat"),
                                store_mod.COMBAT_MIN, store_mod.COMBAT_MAX),
        "skills": {
            key: _int_in_range(skills.get(key), store_mod.SKILL_MIN, store_mod.SKILL_MAX)
            for key in store_mod.SKILL_KEYS
        },
    }

    # 魔方：接口给 cubeId，我们存 resourceId + 名字
    cube = entry.get("cube") if isinstance(entry.get("cube"), dict) else {}
    cube_id = _as_int(cube.get("cubeId"))
    if cube_id is not None and cube_id > 0:
        info = _cube_by_cube_id(cube_id)
        if info is not None:
            record["cube"] = {
                "resourceId": info.get("resourceId"),
                "nameCn": info.get("nameCn"),
                "nameEn": info.get("nameEn"),
                "level": _int_in_range(cube.get("level"),
                                       store_mod.CUBE_LEVEL_MIN, store_mod.CUBE_LEVEL_MAX),
            }
        # 认不出的 cubeId：整条魔方留空（网页端也是「跳过该魔方」）

    # 收藏品：品质由 tid 推；等级两边语义不同 —— SSR 内部是 0~2（界面 1~3），
    # R/SR 就是原值。所以 SSR 不走范围表，直接夹到 0~2。
    favorite = entry.get("favoriteItem") if isinstance(entry.get("favoriteItem"), dict) else {}
    rarity = _favorite_rarity(favorite.get("tid"))
    if rarity == "SSR":
        raw_level = _as_int(favorite.get("level"))
        record["favoriteItem"] = {
            "rarity": rarity,
            "level": None if raw_level is None else max(0, min(2, raw_level)),
        }
    elif rarity:
        record["favoriteItem"] = {
            "rarity": rarity,
            "level": _int_in_range(favorite.get("level"),
                                   store_mod.FAVORITE_LEVEL_MIN, store_mod.FAVORITE_LEVEL_MAX),
        }

    equipments = entry.get("equipments")
    record["equipments"] = [_slot_lines(equipments, slot) for slot in range(4)]
    return record


def _parse_account(raw: dict, known_codes: set[str] | None) -> dict:
    """油猴脚本导出的账号数据。

    图鉴里**没有**的角色整条跳过（不是留个空壳）：这一路要拿角色表才能判
    收藏品是不是珍藏品，认不出的编号在 BOT 这边也出不了图，留个空壳只会
    让「已读取 N 个」和 /妮姬列表 对不上。
    """
    version = _as_int(raw.get("version"))
    if version is None or not 1 <= version <= ACCOUNT_VERSION:
        raise ImportFileError(f"暂不支持该文件版本（version={raw.get('version')}）")

    entries = raw.get("characters")
    if not isinstance(entries, list):
        raise ImportFileError("文件里未含有角色数据")

    known = None if known_codes is None else {str(code) for code in known_codes}
    characters: dict[str, dict] = {}
    unmatched: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        code = str(entry.get("nameCode") or "").strip()
        if not code:
            continue
        if known is not None and code not in known:
            unmatched.append(code)
            continue
        characters[code] = _account_record(entry)

    if not characters:
        raise ImportFileError(
            f"文件里的 {len(entries)} 个角色，图鉴里未收录，无法导入。\n"
            "如果游戏刚出了新角色，请等待 BOT 这边更新角色表之后再次尝试。"
        )

    # 研究所等级：tid 命中就写，没命中的保持默认值 1
    research = store_mod.default_research()
    for item in raw.get("researches") or []:
        if not isinstance(item, dict):
            continue
        target = RESEARCH_BY_TID.get(_as_int(item.get("tid")))
        level = _int_in_range(item.get("lv"), store_mod.RESEARCH_MIN, store_mod.RESEARCH_MAX)
        if target and level is not None:
            research[target[0]][target[1]] = level

    area = str(raw.get("areaId") or "").strip()
    return {
        "kind": "account",
        "name": _clean_name(raw.get("profileName")),
        # 区服只有账号数据这一路有；档案 JSON 里没有这个字段，那边给空串
        "source": f"area {area}" if area else "",
        "synchroLevel": _int_in_range(
            raw.get("synchroLevel"), store_mod.SYNCHRO_MIN, store_mod.SYNCHRO_MAX),
        "research": research,
        "characters": characters,
        "unknown": unmatched,
    }


def sniff(text: str, known_codes: set[str] | None = None) -> dict:
    """按 ``format`` 认一个整档 JSON。

    :param known_codes: 图鉴里的角色编号集合，用来统计「图鉴未收录」；``None`` 表示不统计。
    :raises ImportFileError: 认不出或结构不对，``str(exc)`` 可直接回给用户。

    返回的字典可直接交给 :func:`core.store.merge_file_import`。
    """
    if len(text) > MAX_CHARS:
        raise ImportFileError(f"文件太大了（{len(text) // 1024} KB），无法读取")

    try:
        raw = json.loads(text)
    except Exception:
        raise ImportFileError("不是有效的 JSON 文件") from None
    if not isinstance(raw, dict):
        raise ImportFileError("文件内容不是一个对象")

    fmt = str(raw.get("format") or "")
    if fmt == PROFILE_FORMAT:
        return _parse_profile(raw, known_codes)
    if fmt == ACCOUNT_FORMAT:
        return _parse_account(raw, known_codes)
    raise ImportFileError(
        f"无法识别此文件（format={fmt or '缺失'}）。\n"
        "支持两种：网页端「存档管理 → 导出当前档案数据」的档案 JSON，以及油猴脚本导出的blablalink账号数据。"
    )


def _parse_profile(raw: dict, known_codes: set[str] | None) -> dict:
    """网页端导出的整档 JSON。字段名与 BOT 存档一致，搬过来就行。"""
    version = _as_int(raw.get("version"))
    if version is None or not 1 <= version <= STORE_VERSION:
        raise ImportFileError(f"暂不支持该文件版本（version={raw.get('version')}）")

    characters = raw.get("characters")
    if not isinstance(characters, dict):
        raise ImportFileError("档案未含有角色记录")
    records = {
        str(code): _ensure_shape(record)
        for code, record in characters.items()
        if isinstance(record, dict)
    }
    if not records:
        raise ImportFileError("档案未含有角色记录")

    known = None if known_codes is None else {str(code) for code in known_codes}
    research = raw.get("research")
    return {
        "kind": "profile",
        "name": _clean_name(raw.get("name")),
        # 档案 JSON 里没有区服字段，回执那一格就只能显示「—」
        "source": "",
        "synchroLevel": _int_in_range(
            raw.get("synchroLevel"), store_mod.SYNCHRO_MIN, store_mod.SYNCHRO_MAX),
        # normalize_research 自己会把缺项补默认、越界夹回范围；这里只挡非字典
        "research": store_mod.normalize_research(research) if isinstance(research, dict) else None,
        "characters": records,
        # 这一路图鉴没有的编号**留着**：档案是本工具自己导出的，认不出的
        # 多半是刚出的新角色，数据留着等角色表更新就能直接用
        "unknown": [] if known is None else [code for code in records if code not in known],
    }
