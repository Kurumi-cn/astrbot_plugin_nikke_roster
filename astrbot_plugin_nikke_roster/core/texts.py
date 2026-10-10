"""面向用户的文案。所有对外文字都放这里，改文案不用翻业务代码。"""
from __future__ import annotations

BOT_NAME = "NIKKE练度统计助手"

INTRO = (
    "NIKKE 练度统计助手：可网页端导出的分享码或json文件导入 至BOT，练度数据按 QQ 各自保存，"
    "之后可以直接在聊天里出角色面板图和练度统计表。"
)

USAGE_NOTE = [
    "· 群聊里使用需要在前面加「/」，例如 /妮姬帮助，私聊则直接发送命令即可；",
    "· 命令整串匹配，命令名和参数之间使用空格分隔。",
    "· 各人的练度数据各自独立。",
    "· 装备词条只能在网页端录入，BOT只负责导入、出图和一定限制内的修改数值。",
]

# 「已实现」区：只列**真能跑通**的命令。新命令接入后往这里加，
# 不做「占位按钮」—— 用户照着帮助敲却报「未知命令」是最差的体验。
COMMAND_GROUPS = [
    ("基础", [
        ("/妮姬帮助", "显示本帮助"),
        ("/妮姬网址", "输出网页端地址"),
        ("/妮姬自检", "检查角色表、素材、字体、数据目录是否就绪"),
    ]),
    ("数据", [
        ("/妮姬导入 <分享码>", "导入分享码（角色数据、表格配置）"),
        ("/妮姬导入json", "可发送 JSON 文件，整档存入练度库"),
        ("/妮姬列表", "查看已经导入了的妮姬"),
    ]),
    ("存档", [
        ("/妮姬存档", "查看当前存档与全部存档"),
        ("/妮姬新建存档 <名字>", "新建一个存档（每人最多 8 个）"),
        ("/妮姬删除存档 <名字>", "删除一个存档"),
        ("/妮姬修改存档 <原名> <新名>", "修改存档名"),
        ("/妮姬切换存档 <名字>", "切换当前使用的存档"),
    ]),
    ("出图", [
        ("/妮姬面板 <角色>", "展示该角色的练度面板图"),
        ("/妮姬练度统计", "展示一张练度统计表"),
        ("/妮姬群排行 <角色>", "展示本群该角色的词条排行表（仅群聊）"),
        ("/妮姬练度统计设置 <角色> <角色> ...",
         "定表格里有谁、按什么顺序排\n（推荐从网页端导入表格配置识别码后再次使用本命令）"),
    ]),
    ("改数值", [
        ("/妮姬同步器 <等级>", "设置自己当前同步器等级（1~2000）"),
        ("/妮姬好感 <角色> <值>", "改好感度（0~40）"),
        ("/妮姬星级 <角色> <值>", "改突破星级（0~3）"),
        ("/妮姬核心 <角色> <值>", "改核心突破（0~7）"),
        ("/妮姬技能1 <角色> <值>", "改技能 1（1~10）"),
        ("/妮姬技能2 <角色> <值>", "改技能 2（1~10）"),
        ("/妮姬爆裂 <角色> <值>", "改爆裂技能（1~10）"),
    ]),
    ("一键：改自己已导入的全部角色", [
        ("/妮姬一键好感度 <值>", "好感度"),
        ("/妮姬一键星级 <值>", "突破星级"),
        ("/妮姬一键核心 <值>", "核心突破"),
        ("/妮姬一键技能1 <值>", "技能 1"),
        ("/妮姬一键技能2 <值>", "技能 2"),
        ("/妮姬一键爆裂 <值>", "爆裂技能"),
    ]),
]

FOOTER = ""


def _all_commands() -> list[tuple[str, str]]:
    return [item for _title, items in COMMAND_GROUPS for item in items]


def web_url_note(web_url: str) -> str:
    return f"网页端：`{web_url}`" if web_url else "网页端：尚未在插件配置里填写地址"


def _header(web_url: str) -> list[str]:
    lines = [f"【{BOT_NAME}】", "", INTRO, ""]
    lines += USAGE_NOTE
    lines += ["", web_url_note(web_url), ""]
    return lines


def _render_group(title: str, items: list[tuple[str, str]], width: int) -> list[str]:
    lines = [f"▍{title}"]
    lines += [f"  {name.ljust(width)}  {desc}" for name, desc in items]
    return lines


def help_text(web_url: str = "") -> str:
    width = max(len(name) for name, _ in _all_commands())
    lines = _header(web_url)
    for index, (title, items) in enumerate(COMMAND_GROUPS):
        if index:
            lines.append("")
        lines += _render_group(title, items, width)
    if FOOTER:
        lines += ["", FOOTER]
    return "\n".join(lines)


def help_nodes(web_url: str = "") -> list[tuple[str, str]]:
    """合并转发的分节：``[(节点标题, 节点正文), ...]``。

    和纯文本版共用同一份 COMMAND_GROUPS，避免两边文案漂移。
    """
    width = max(len(name) for name, _ in _all_commands())
    nodes = [(f"{BOT_NAME} · 总览", "\n".join(_header(web_url) + _render_group(*COMMAND_GROUPS[0], width)))]
    nodes += [
        (f"{BOT_NAME} · {title}", "\n".join(_render_group(title, items, width)))
        for title, items in COMMAND_GROUPS[1:]
    ]
    return nodes


# ── 错误与提示 ───────────────────────────────────────────────────────

NO_RECORD_HINT = "先在网页端录入并导出分享码，然后使用 /妮姬导入 <分享码> 导入"


def unknown_character(query: str) -> str:
    return f"没找到叫「{query}」的角色。可以使用 /妮姬列表 看自己已导入的妮姬。"


def ambiguous_character(query: str, names: list[str]) -> str:
    return f"「{query}」可匹配的角色较多：{'、'.join(names)}\n本次请将名字补全。"


def not_imported(name: str) -> str:
    return f"{name} 还没导入过数据。{NO_RECORD_HINT}"


def bad_value(label: str, low: int, high: int) -> str:
    return f"{label}要填 {low}~{high} 之间的整数。"


def bad_args(command: str, usage: str) -> str:
    return f"用法：{command} {usage}"


def render_failed(exc: Exception) -> str:
    return f"发送图片失败：{type(exc).__name__}: {exc}"


# ── /妮姬列表 ────────────────────────────────────────────────────────
# 有数据时发成**合并转发**（群聊/私聊都发）：① 查询人（main 负责）② 头部统计
# + 可进名单 ③ 未完善名单（该节为空则不发这个节点）。空档也发合并转发（查询人 + 空档节点）。

def list_empty_text(profile: str) -> str:
    return "\n".join([
        f"当前存档：{profile}",
        "还没有导入任何角色数据。",
        NO_RECORD_HINT,
    ])


def _list_section(title: str, rows: list[dict], with_score: bool) -> list[str]:
    lines = [f"▍{title}（{len(rows)}）"]
    for row in rows:
        element = f" · {row['element']}" if row["element"] else ""
        score = f" · 阶数 {row['tierScore']}" if with_score else ""
        lines.append(f"  {row['name']}{element}{score}")
    return lines


def list_plain_text(profile: str, synchro_level: int, rows: list[dict]) -> str:
    """纯文本版（合并转发不可用时的兜底）。"""
    done = [row for row in rows if row["complete"]]
    todo = [row for row in rows if not row["complete"]]
    lines = [
        f"当前存档：{profile}",
        f"同步器 LV.{synchro_level} · 已导入 {len(rows)} 个角色（装备已录入 {len(done)}）",
    ]
    if done:
        lines += [""] + _list_section("可进练度统计", done, with_score=True)
    if todo:
        lines += [""] + _list_section("未完善装备词条的角色", todo, with_score=False)
    return "\n".join(lines)


def list_nodes(profile: str, synchro_level: int, rows: list[dict]) -> list[tuple[str, str]]:
    """合并转发的两个正文节点（「查询人」节点由 main 补在最前面）。"""
    done = [row for row in rows if row["complete"]]
    todo = [row for row in rows if not row["complete"]]

    head = [
        f"当前存档：{profile}",
        f"同步器 LV.{synchro_level} · 已导入 {len(rows)} 个角色（装备已录入 {len(done)}）",
    ]
    if done:
        head += [""] + _list_section("可进练度统计", done, with_score=True)
    nodes = [(f"可进练度统计（{len(done)}）", "\n".join(head))]
    if todo:
        nodes.append((f"未完善装备词条的角色（{len(todo)}）",
                      "\n".join(_list_section("未完善装备词条的角色", todo, with_score=False))))
    return nodes


def requester_note(name: str, uid: str) -> str:
    """合并转发里的「谁用的命令」节点（群名片 > QQ 昵称，由事件侧保证）。"""
    return f"查询人：{name}（{uid}）" if name else f"查询人：{uid}"


# ── 导入回执 ─────────────────────────────────────────────────────────

def import_receipt(kind: str, added: int, updated: int, synchro_level: int | None,
                   names: list[str], unknown: list[str], table_rows: int = 0,
                   profile: str = "") -> str:
    if kind == "table":
        lines = [f"收到表格配置：{table_rows} 行。"]
        if profile:
            lines.append(f"本次导入到存档：{profile}")
        lines.append("之后发送 /妮姬练度统计 将按此名单和顺序进行输出。")
        missing = unknown
        if missing:
            shown = "、".join(missing[:8])
            more = f" 等 {len(missing)} 个" if len(missing) > 8 else ""
            lines.append(f"其中 {shown}{more} 你还未导入，输出表单时会跳过。")
        return "\n".join(lines)

    lines = [f"导入完成：新增 {added} 个，更新 {updated} 个。"]
    if profile:
        lines.append(f"本次导入到存档：{profile}")
    if names:
        shown = "、".join(names[:10])
        more = f" 等 {len(names)} 个" if len(names) > 10 else ""
        lines.append(f"本次涉及：{shown}{more}")
    if synchro_level is not None:
        lines.append(f"同步器等级已按分享码设为 LV.{synchro_level}。")
    lines.append("可以发送 /妮姬面板 <角色> 查看指定角色的卡片，/妮姬列表 看你的全部妮姬列表。")
    return "\n".join(lines)


def changed_receipt(label: str, value, count: int | None = None, name: str = "") -> str:
    if count is None:
        return f"已把 {name} 的{label}改成 {value}。"
    if count == 0:
        return f"你还没导入任何角色，没有可改的数据。\n{NO_RECORD_HINT}"
    return f"已把 {count} 个已导入角色的{label}改成 {value}。"


def synchro_receipt(old, new) -> str:
    return f"同步器等级：LV.{old} → LV.{new} 成功。"


# ── /妮姬导入json ────────────────────────────────────────────────────

#: 命令与文件是两条独立的消息事件，中间隔着用户操作的时间，所以只能开一个窗口等。
IMPORT_FILE_WINDOW = 120


def import_file_prompt(seconds: int, profile: str = "", characters: int = 0) -> str:
    minutes = max(1, seconds // 60)
    lines = [
        f"请在 {minutes} 分钟内将档案 JSON 文件发送至此会话，BOT 将自动读取",
        "· 只需发送JSON文件即可。可以识别：网页端「存档管理 → 导出当前档案数据」的档案 JSON以及油猴脚本导出的blablalink账号数据",
    ]
    if profile:
        lines += [
            "",
            f"当前存档为：{profile}，已有数据 角色 {characters} 名，请注意核查！"
            "若要新开存档请及时使用/妮姬新建存档 和/妮姬切换存档 以防止原存档丢失！",
        ]
    return "\n".join(lines)


def import_file_timeout() -> str:
    return "检测超时！请重新使用/妮姬导入json 进行导入"


def import_file_receipt(kind: str, name: str, source: str, count: int, added: int,
                        updated: int, level_changed: tuple | None, unknown: list[str],
                        profile: str = "") -> str:
    """整档导入的回执。``source`` 未知时传空串，会显示成「—」。

    档案 JSON 里没有区服字段（只有油猴导出的账号数据才带 area），
    所以这里不去猜一个「服务器」出来。

    ``unknown`` 两种文件含义不同，说法也就不同：账号数据那一路上，图鉴没有的
    角色是**整条跳过**的；档案那一路是**存下但出不了图**。
    """
    lines = ["🟢 读取成功！" + (f" 导入到存档：{profile}" if profile else "")]
    lines += [
        f"服务器：{source or '—'}  角色：{name or '未命名档案'}",
        f"已读取角色：{count} 个 。新增 {added} 个，更新 {updated} 个",
    ]
    if level_changed is not None:
        lines.append(f"同步器等级：LV.{level_changed[0]} → LV.{level_changed[1]}")
    if unknown:
        shown = "、".join(unknown[:8])
        more = f" 等 {len(unknown)} 个" if len(unknown) > 8 else ""
        if kind == "account":
            lines.append(f"图鉴里还没有，已跳过：{shown}{more}")
        else:
            lines.append(f"这些编号图鉴里还没有，已存下但出不了图：{shown}{more}")
    return "\n".join(lines)


def import_file_failed(reason: str) -> str:
    return f"🔴 读取失败：{reason}"


def import_file_no_url() -> str:
    return "🔴 收到了文件消息，但没拿到下载地址，协议端未返回 url。"


def table_config_receipt(rows: int, skipped: list[str], missing: list[str]) -> str:
    lines = [f"表格配置好了：{rows} 行。现在可以使用 /妮姬练度统计 查看了。"]
    if missing:
        shown = "、".join(missing[:8])
        lines.append(f"没找到：{shown}")
    if skipped:
        shown = "、".join(skipped[:8])
        more = f" 等 {len(skipped)} 个" if len(skipped) > 8 else ""
        lines.append(f"装备还没录完，出表时会跳过：{shown}{more}")
    return "\n".join(lines)


# ── 多存档管理 ───────────────────────────────────────────────────────

def profile_overview_text(current: str, status: str, rows: list[tuple[str, int]],
                          max_count: int) -> str:
    """``/妮姬存档``：当前档 + 全部档一览。``rows`` 为 ``[(名字, 角色数), ...]``（顺序即创建顺序）。"""
    lines = [f"当前存档：{current}", status, "", f"▍全部存档（{len(rows)}/{max_count}）"]
    for name, count in rows:
        mark = "（当前）" if name == current else ""
        detail = f"{count} 个角色" if count else "还没导入"
        lines.append(f"  {name}{mark} · {detail}")
    return "\n".join(lines)


def profile_created(name: str, count: int, max_count: int) -> str:
    return f"已新建存档「{name}」（共 {count}/{max_count} 个）。发 /妮姬切换存档 {name} 可切换过去。"


def profile_deleted(name: str, current: str, switched: bool) -> str:
    if switched:
        return f"已删除存档「{name}」。\n当前存档已切换为「{current}」。"
    return f"已删除存档「{name}」。"


def profile_renamed(old: str, new: str) -> str:
    if old == new:
        return "新旧名字相同，未做修改。"
    return f"已把存档「{old}」改名为「{new}」。"


def profile_switched(name: str) -> str:
    return f"已切换到存档「{name}」。"


# ── /妮姬群排行 ──────────────────────────────────────────────────────

def group_rank_private_hint() -> str:
    return "「妮姬群排行」只能在群里用。"


def group_rank_cd(seconds: int) -> str:
    return f"群排行 15 秒内只能查一次，{seconds} 秒后再试。"


def group_rank_no_members() -> str:
    return "群成员名单获取失败，请稍后再试。"


def group_rank_empty(name: str) -> str:
    return f"本群还没有人完善「{name}」的练度（四件装备都录满才能进榜）。"
