r"""容器内指令冒烟：拿假 event 把 ``main.py`` 的指令从头跑一遍。

    python /AstrBot/data/nikke_tools/command-smoke.py <插件目录> <分享码向量文件>

为什么要有这一层：出图、存档、名字解析各自单测都过了，但**拼成命令**之后最容易
出事的地方是「取参数的切片 / yield 了几条 / event 上到底叫什么属性」，
这些只有真跑一遍才看得见。需要 QQ 才能验的部分（合并转发、协议端发送）这里不碰。

覆盖：导入角色数据与表格配置 → 列表 → 面板出图 → 练度统计出图 →
      单角色改数值 → 一键改数值 → 发档案文件整档导入 → 参数与角色名的各种报错分支 →
      多存档 → 群排行（含 CD 与拆图转发，用假协议端验节点结构）→ 导入窗口（提示主动发送/撤回 + 超时提醒）。

跑完会把这次用的测试 QQ（10001）存档和出图都删掉，不留在服务器上。
"""
from __future__ import annotations

import asyncio
import importlib
import json
import shutil
import sys
import time
from pathlib import Path

from astrbot.api.message_components import File

PLUGIN_DIR = Path(sys.argv[1] if len(sys.argv) > 1 else "/AstrBot/data/plugins/astrbot_plugin_nikke_roster")
VECTOR_FILE = Path(sys.argv[2] if len(sys.argv) > 2 else "/AstrBot/data/nikke_tools/sharecode-vectors.json")
TEST_UID = "10001"

if str(PLUGIN_DIR.parent) not in sys.path:
    sys.path.insert(0, str(PLUGIN_DIR.parent))

MODULE_NAME = "astrbot_plugin_nikke_roster.main"

#: 命令名 → 方法名。下面会断言这张表和帮助里的命令清单严格一致，
#: 加了新命令却忘了加进来会直接报错，不会静默漏测。
METHODS = {
    "妮姬帮助": "nikke_help",
    "妮姬网址": "nikke_url",
    "妮姬自检": "nikke_selftest",
    "妮姬导入": "nikke_import",
    "妮姬导入json": "nikke_import_json",
    "妮姬存档": "nikke_profile",
    "妮姬新建存档": "nikke_profile_create",
    "妮姬删除存档": "nikke_profile_delete",
    "妮姬修改存档": "nikke_profile_rename",
    "妮姬切换存档": "nikke_profile_switch",
    "妮姬列表": "nikke_list",
    "妮姬面板": "nikke_panel",
    "妮姬练度统计": "nikke_stats",
    "妮姬练度统计设置": "nikke_stats_config",
    "妮姬群排行": "nikke_group_rank",
    "妮姬同步器": "nikke_synchro",
    "妮姬好感": "nikke_affection",
    "妮姬星级": "nikke_grade",
    "妮姬核心": "nikke_core",
    "妮姬技能1": "nikke_skill1",
    "妮姬技能2": "nikke_skill2",
    "妮姬爆裂": "nikke_burst",
    "妮姬一键好感度": "nikke_all_affection",
    "妮姬一键星级": "nikke_all_grade",
    "妮姬一键核心": "nikke_all_core",
    "妮姬一键技能1": "nikke_all_skill1",
    "妮姬一键技能2": "nikke_all_skill2",
    "妮姬一键爆裂": "nikke_all_burst",
}


class Reply:
    """假的指令返回值，只为把「文本 / 图片」和内容记下来。"""

    def __init__(self, kind: str, body: str):
        self.kind = kind
        self.body = body

    def __repr__(self) -> str:
        shown = Path(self.body).name if self.kind == "image" else self.body
        return f"<{self.kind} {shown!r}>"


class FakeEvent:
    """只实现指令里实际用到的那几个属性。

    刻意不做成「完整的 AstrMessageEvent」——用到什么就实现什么，
    多出来的能力只会让测试看起来比实际覆盖得多。
    """

    def __init__(self, text: str, uid: str = TEST_UID, group: str = "",
                 messages: list | None = None, bot=None):
        self._text = text
        self._uid = uid
        self._group = group
        self._messages = list(messages or [])
        self.bot = bot
        self.tracked: list[str] = []
        self.message_obj = type("_MsgObj", (), {"self_id": "99999"})()

    @property
    def unified_msg_origin(self) -> str:
        kind = "GroupMessage" if self._group else "FriendMessage"
        return f"aiocqhttp:{kind}:{self._group or self._uid}"

    def get_messages(self) -> list:
        return self._messages

    def get_message_str(self) -> str:
        return self._text

    def get_sender_id(self) -> str:
        return self._uid

    def get_group_id(self) -> str:
        return self._group

    def get_sender_name(self) -> str:
        return "冒烟群名片"

    def plain_result(self, text: str) -> Reply:
        return Reply("text", text)

    def image_result(self, path: str) -> Reply:
        return Reply("image", path)

    def track_temporary_local_file(self, path: str) -> None:
        self.tracked.append(str(path))


class StubBot:
    """假协议端：记录 call_action 收到的参数，群成员名单 / 合并转发用。"""

    def __init__(self, members: list | None = None, fail_members: bool = False):
        self.members = list(members or [])
        self.fail_members = fail_members
        self.calls: list[tuple[str, dict]] = []

    async def call_action(self, action: str, **payload):
        self.calls.append((action, payload))
        if action == "get_group_member_list":
            if self.fail_members:
                raise RuntimeError("模拟：拿不到群成员名单")
            return self.members
        if action in ("send_group_msg", "send_private_msg",
                      "send_group_forward_msg", "send_private_forward_msg"):
            return {"message_id": 1}
        return {}


#: 群排行拆图测试造出来的一批「群友」存档（跑完要删干净）
RANK_UIDS = [str(20000 + index) for index in range(1, 32)]


class StubContext:
    """假框架上下文：记录主动发出去的消息（导入超时提醒用）。"""

    def __init__(self):
        self.sent: list[tuple[str, object]] = []

    async def send_message(self, umo: str, chain) -> bool:
        self.sent.append((umo, chain))
        return True


def main() -> int:
    module = importlib.import_module(MODULE_NAME)
    # 直接用 main 里已经导入好的那几个模块对象，免得两处 import 出两份状态
    texts, store_mod = module.texts, module.store_mod

    # ── 先自检测试脚本本身 ───────────────────────────────────────────
    help_commands = {
        name.split(" ")[0].lstrip("/") for _title, items in texts.COMMAND_GROUPS for name, _desc in items
    }
    assert help_commands == set(METHODS), (
        "帮助里列的命令和冒烟表对不上："
        f"帮助多 {help_commands - set(METHODS)}，冒烟多 {set(METHODS) - help_commands}"
    )
    for method in METHODS.values():
        assert hasattr(module.NikkeRosterPlugin, method), f"插件上没有 {method}"

    plugin = module.NikkeRosterPlugin(None, {"web_base_url": "https://nikke.example.com"})
    asyncio.run(plugin.initialize())

    vectors = json.loads(VECTOR_FILE.read_text(encoding="utf-8"))["vectors"]
    char_vector = max(
        (v for v in vectors if v["expect"]["payloadType"] == 0),
        key=lambda v: len(v["expect"]["characters"]),
    )
    table_vector = next(v for v in vectors if v["expect"]["payloadType"] == 1)

    failures: list[str] = []
    checks = 0

    def check(label: str, ok: bool, detail: str = "") -> None:
        nonlocal checks
        checks += 1
        if ok:
            print(f"  [OK]   {label}")
        else:
            print(f"  [FAIL] {label}" + (f"  <- {detail}" if detail else ""))
            failures.append(label)

    def text_of(replies: list[Reply]) -> str:
        return "\n".join(item.body for item in replies if item.kind == "text")

    def images_of(replies: list[Reply]) -> list[str]:
        return [item.body for item in replies if item.kind == "image"]

    async def call_with_event(text: str, messages: list | None = None, uid: str = TEST_UID,
                              group: str = "", bot=None) -> tuple[list[Reply], FakeEvent]:
        method = METHODS[text.split(" ")[0].lstrip("/")]
        event = FakeEvent(text, uid=uid, group=group, messages=messages, bot=bot)
        return [item async for item in getattr(plugin, method)(event)], event

    async def call_file_import(messages: list) -> tuple[list[Reply], FakeEvent]:
        """直接调**文件**处理器。

        命令处理器和文件处理器是两个方法，而 ``call_with_event`` 是按命令名查表的，
        只可能命中命令那个 —— 文件这条得自己指过去。
        """
        event = FakeEvent("妮姬导入json", messages=messages)
        return [item async for item in plugin.nikke_import_json_file(event)], event

    def call(text: str) -> list[Reply]:
        return asyncio.run(call_with_event(text))[0]

    def text_call(text: str) -> str:
        return text_of(call(text))

    try:
        # ── 1. 静态指令 ─────────────────────────────────────────────
        print("1) 帮助 / 网址 / 自检 / 列表 / 面板（空档）")
        body = text_call("妮姬帮助")
        check("帮助里有新命令",
              "妮姬导入" in body and "妮姬一键爆裂" in body and "妮姬切换存档" in body
              and "妮姬群排行" in body)

        body = text_call("妮姬网址")
        check("网址取到配置里的地址", "https://nikke.example.com" in body, body[:60])

        body = text_call("妮姬自检")
        check("自检跑通并报出自己的存档", "[OK] 你的存档" in body and "[OK] 角色表" in body and "当前存档：" in body)

        body = text_call("妮姬列表")
        check("空档列表给引导语", "还没有导入任何角色数据" in body, body[:60])

        body = text_call("妮姬面板 拉毗")
        check("没导入的角色提示先导入", "还没导入过数据" in body or "没找到叫" in body, body[:80])

        body = text_call("妮姬面板 不存在的名字")
        check("认不出的角色有提示", "没找到叫" in body, body[:80])

        body = text_call("妮姬面板")
        check("面板缺参数报用法", "用法：" in body, body[:60])

        # ── 2. 导入分享码 ───────────────────────────────────────────
        print("2) 导入角色数据")
        body = text_call(f"妮姬导入 {char_vector['code']}")
        check("导入回执有新增数", "导入完成：新增" in body, body[:80])
        check("角色导入回执带存档名", "本次导入到存档：" in body, body[:120])

        store = store_mod.load(TEST_UID)
        codes = sorted(store["characters"])
        expect_count = len(char_vector["expect"]["characters"])
        check("存档里角色数对上", len(codes) == expect_count, f"{len(codes)} vs {expect_count}")
        name = plugin.roster.by_code[codes[0]]["nameCn"]

        body = text_call("妮姬列表")
        check("列表报出导入数量与同步器", "已导入" in body and "同步器 LV." in body and "当前存档：" in body, body[:80])

        # ── 3. 面板出图 ─────────────────────────────────────────────
        print("3) 面板出图")
        replies, event = asyncio.run(call_with_event(f"妮姬面板 {name}"))
        paths = images_of(replies)
        check("返回一条图片", len(paths) == 1, repr(replies)[:120])
        if paths:
            from PIL import Image

            with Image.open(paths[0]) as image:
                check("图片是 2x 卡片尺寸 1472×2192", image.size == (1472, 2192), str(image.size))
            check("出图登记给了框架清理", paths[0] in event.tracked, repr(event.tracked))

        # 随机皮肤：多张立绘的角色会换装，只有一张的退回默认（不随机）
        cardmodel = module.cardmodel
        check("随机皮肤默认开启", plugin._random_skin() is True, repr(plugin.config))
        schema = json.loads((PLUGIN_DIR / "_conf_schema.json").read_text(encoding="utf-8"))
        check("配置里有随机皮肤开关", "random_skin" in schema, repr(list(schema)))

        multi = next((c for c in plugin.roster.characters if len(cardmodel.artwork_entries(c)) > 1), None)
        single = next((c for c in plugin.roster.characters if len(cardmodel.artwork_entries(c)) == 1), None)
        check("角色表里有可随机的角色", multi is not None and single is not None, "")
        if multi:
            allowed = {a["id"] for a in cardmodel.artwork_entries(multi)}
            picks = [cardmodel.random_artwork_id(multi) for _ in range(80)]
            check("随机结果都落在该角色的立绘里", set(picks) <= allowed, repr(set(picks) - allowed))
            check("随机结果确实在变", len(set(picks)) > 1, repr(sorted(set(picks))))
        if single:
            check("只有一张立绘时不随机",
                  all(cardmodel.random_artwork_id(single) is None for _ in range(20)), "应为 None")

        # ── 4. 练度统计 ─────────────────────────────────────────────
        print("4) 练度统计")
        # 先把自己造一个「四件装备全录满」的角色：这才是练度统计的真实使用场景，
        # 而分享码向量里没有这种满配数据（装备词条只能从网页端 OCR/手填进来）
        filled = [[{"functionType": "StatAtk", "level": 15, "value": 14.63} for _ in range(3)] for _ in range(4)]

        def force_complete(store):
            store["characters"][codes[0]] = {**store["characters"][codes[0]], "equipments": filled}
            return None

        store_mod.update(TEST_UID, force_complete)
        replies = call("妮姬练度统计")
        paths = images_of(replies)
        check("出表（有已完善角色）", len(paths) == 1, repr(replies)[:120])
        if paths:
            from PIL import Image

            with Image.open(paths[0]) as image:
                check("统计表比卡片宽（9 列）", image.width > 800 and image.height > 100, str(image.size))
                # 左上角署名：头像或 QQ 号（取不到头像时降级为文字）都算画上了。
                # 只裁第一列的左半（x≤68：不含邻列表头文字），判据用"与表头灰底的差异"，
                # 比亮度阈值对白色头像更稳；无署名时该区域应是纯灰底（差异≈0）
                gray = image.convert("L")
                corner = gray.crop((8, 8, 68, 72))
                ink = sum(1 for px in corner.getdata() if abs(px - 243) > 18)
                check("左上角有署名内容（头像或 QQ 号）", ink > 200, f"ink={ink}")

        body = text_call(f"妮姬练度统计设置 {name}")
        check("设置表格有回执", "表格配置好了" in body, body[:80])
        # 名单里再塞一个装备没录完的：应该照常出表，另外补一条「跳过了谁」
        other = [c for c in codes if c != codes[0]][0]
        other_name = plugin.roster.by_code[other]["nameCn"]
        replies = call(f"妮姬练度统计设置 {name} {other_name}")
        check("配置里掺入没录完的角色也不报错", "表格配置好了" in text_of(replies), repr(replies)[:120])
        replies = call("妮姬练度统计")
        check("出表 + 一条跳过说明",
              len(images_of(replies)) == 1 and "跳过了" in text_of(replies), repr(replies)[:160])

        body = text_call("妮姬练度统计设置 不存在甲乙丙")
        check("全都认不出时报错", "存在名字错误" in body, body[:80])

        body = text_call(f"妮姬导入 {table_vector['code']}")
        check("表格配置载荷被识别", "收到表格配置" in body, body[:80])

        # ── 5. 改数值 ───────────────────────────────────────────────
        print("5) 改数值")
        body = text_call(f"妮姬好感 {name} 35")
        check("改好感度成功", "好感度改成 35" in body, body[:80])
        check("存档里确实是 35", store_mod.load(TEST_UID)["characters"][codes[0]]["affection"] == 35)

        body = text_call(f"妮姬好感 {name} 99")
        check("好感度越界被拦", "0~40" in body, body[:80])

        body = text_call(f"妮姬好感 {name} abc")
        check("非数字被拦", "0~40" in body, body[:80])

        body = text_call("妮姬好感 拉毗 10")
        check("没导入的角色改不动", "还没导入过数据" in body or "没找到叫" in body, body[:80])

        body = text_call(f"妮姬星级 {name} 3")
        check("改星级成功", "星级改成 3" in body, body[:80])

        body = text_call(f"妮姬核心 {name} 7")
        check("改核心成功", "核心改成 7" in body, body[:80])

        skill2_before = store["characters"][codes[0]]["skills"]["skill2"]
        body = text_call(f"妮姬技能1 {name} 10")
        check("改技能1成功", "技能1改成 10" in body, body[:80])
        after = store_mod.load(TEST_UID)["characters"][codes[0]]["skills"]
        check("技能只动自己那个键", after["skill1"] == 10 and after["skill2"] == skill2_before,
              repr(after))

        body = text_call("妮姬爆裂 abc")
        check("爆裂缺数值报用法", "用法：" in body, body[:80])

        body = text_call("妮姬同步器 500")
        check("改同步器成功", "LV.200 → LV.500" in body, body[:80])

        body = text_call("妮姬同步器 9999")
        check("同步器越界被拦", "1~2000" in body, body[:80])

        # ── 6. 一键 ─────────────────────────────────────────────────
        print("6) 一键改数值")
        body = text_call("妮姬一键好感度 20")
        check("一键好感度成功", f"已把 {len(codes)} 个已导入角色" in body, body[:80])
        check("确实全改了",
              all(r["affection"] == 20 for r in store_mod.load(TEST_UID)["characters"].values()))

        body = text_call("妮姬一键星级 5")
        check("一键星级越界被拦", "0~3" in body, body[:80])
        body = text_call("妮姬一键技能2 12")
        check("一键技能越界被拦", "1~10" in body, body[:80])
        body = text_call("妮姬一键爆裂 9")
        check("一键爆裂成功", "爆裂技能改成 9" in body, body[:80])

        # ── 7. 发文件导入整档 ───────────────────────────────────────
        # 「协议端把文件下载到容器」这一段要真 QQ 才能验（与合并转发同理），
        # 这里用「协议端直接给了本地路径」的形式覆盖后面的全部逻辑。
        print("7) 发文件导入整档（/妮姬导入json）")

        # 用图鉴里**还没导入**的角色，顺带验证「新记录原样存、不编默认值」
        spare = [code for code in plugin.roster.by_code if code not in codes]
        fresh, fresh2 = spare[0], spare[1]
        profile = {
            "format": "nikke-photos-profile",
            "version": 1,
            "name": "冒烟测试档",
            "synchroLevel": 321,
            "research": {"class": {"Attacker": 7}, "corporation": {"MISSILIS": 5}},
            "characters": {
                fresh: {
                    "limitBreak": {"grade": 2, "core": 3},
                    "affection": 12,
                    "combat": 34567,
                    "skills": {"skill1": 4, "skill2": 5, "burst": 6},
                    "cube": None,
                    "favoriteItem": None,
                    "equipments": [[None, None, None] for _ in range(4)],
                },
            },
        }
        data_dir = Path(store_mod.paths.user_data_dir())
        profile_file = data_dir / "nikke-smoke-profile.json"
        profile_file.write_text(json.dumps(profile, ensure_ascii=False), encoding="utf-8")
        component = File(name="profile.json", file=str(profile_file))

        origin = FakeEvent("").unified_msg_origin
        gate = module._PendingFileFilter()
        check("没开窗时文件不放行", gate.filter(FakeEvent("", messages=[component]), {}) is False)

        body = text_call("妮姬导入json")
        check("开窗提示有等待时长和「只发文件」", "分钟" in body and "只需发送JSON文件即可" in body and "当前存档为：" in body, body[:80])
        check("窗口记在这个会话上", origin in module._PENDING, repr(list(module._PENDING)))
        check("窗口里发文件才放行",
              gate.filter(FakeEvent("", messages=[component]), {}) is True)

        # 群里：同一个会话、不同的人 —— 只有发命令那个人的文件才该进来
        group_key = FakeEvent("", group="999").unified_msg_origin
        module._PENDING[group_key] = {"sender": TEST_UID, "expires": time.time() + 60}
        check("群里别人发的文件不放行",
              gate.filter(FakeEvent("", uid="10002", group="999", messages=[component]), {}) is False)
        check("群里本人发的文件放行",
              gate.filter(FakeEvent("", group="999", messages=[component]), {}) is True)
        module._PENDING.pop(group_key, None)

        replies, event = asyncio.run(call_file_import([component]))
        body = text_of(replies)
        check("回执是绿灯", "🟢 读取成功！" in body, body[:160])
        check("回执首行合并了存档名", "🟢 读取成功！ 导入到存档：" in body, body[:120])
        check("角色数/新增/更新并成一行",
              "已读取角色：1 个 。新增 1 个，更新 0 个" in body, body[:200])
        check("回执不再带末尾引导语", "可通过" not in body, body[-80:])
        check("文件回执带存档名", "导入到存档：" in body, body[:200])
        check("回执报出存档名", "冒烟测试档" in body, body[:160])
        check("回执报出已读角色数", "已读取角色：1 个" in body, body[:160])
        check("本地文件不登记框架清理（免得删掉原件）", event.tracked == [], repr(event.tracked))
        check("收到一次就关窗", module._PENDING == {}, repr(list(module._PENDING)))

        store = store_mod.load(TEST_UID)
        record = store["characters"][fresh]
        check("同步器按文件改了", store["synchroLevel"] == 321, str(store["synchroLevel"]))
        check("研究等级写进去了", store["research"]["class"]["Attacker"] == 7, repr(store["research"]))
        check("文件里的值原样落库",
              record["affection"] == 12 and record["combat"] == 34567, repr(record)[:160])
        check("文件里写 null 的项没被编出默认值", record["cube"] is None, repr(record["cube"]))

        # 油猴脚本导出的账号数据：形状照 app/public/nikke-photos-import.user.js 写
        account = {
            "format": "nikke-photos-account",
            "version": 1,
            "source": "blablalink",
            "exportedAt": "2026-10-03T00:00:00.000Z",
            "areaId": "84",
            "profileName": "博哥",
            "synchroLevel": 456,
            "outpostLevel": 300,
            "researches": [{"tid": 1101, "lv": 7}, {"tid": 1202, "lv": 5}, {"tid": 1001, "lv": 99}],
            "characters": [
                {
                    "nameCode": fresh2,
                    "level": 200,
                    "grade": 2,
                    "core": 3,
                    # 1_234_567：专门卡旧范围（0~999999）会把它判成越界留空的那个坑
                    "combat": 1234567,
                    "affection": 21,
                    "skills": {"skill1": 4, "skill2": 5, "burst": 6},
                    "cube": {"cubeId": 1000301, "level": 12},
                    "favoriteItem": {"tid": 2001, "level": 1},
                    "equipments": [
                        [
                            {"position": 1, "functionType": "StatAtk", "level": 15, "value": 14.63},
                            {"position": 2, "functionType": "不存在的词条", "level": 3},
                        ],
                        [], [], [],
                    ],
                },
                # 图鉴没有的编号：账号数据这一路应当整条跳过并把编号报出来
                {"nameCode": "9999", "grade": 1},
            ],
        }
        account_file = data_dir / "nikke-smoke-account.json"
        account_file.write_text(json.dumps(account, ensure_ascii=False), encoding="utf-8")

        replies, _ = asyncio.run(call_file_import([File(name=account_file.name, file=str(account_file))]))
        body = text_of(replies)
        check("账号数据也认了（绿灯）", "🟢 读取成功！" in body, body[:200])
        check("区服取自 areaId", "服务器：area 84" in body, body[:200])
        check("角色名取自昵称", "博哥" in body, body[:200])
        check("图鉴没有的编号被跳过并报出", "已读取角色：1 个" in body and "9999" in body, body[:200])

        store = store_mod.load(TEST_UID)
        record = store["characters"][fresh2]
        check("战斗力求值没被旧范围卡掉", record["combat"] == 1234567, repr(record["combat"]))
        check("魔方 cubeId 换成了 resourceId",
              (record["cube"] or {}).get("resourceId") == 10001, repr(record["cube"]))
        check("嵌入式字段成套写对了",
              record["affection"] == 21 and record["limitBreak"] == {"grade": 2, "core": 3}
              and record["skills"] == {"skill1": 4, "skill2": 5, "burst": 6},
              repr(record)[:180])
        check("收藏品 tid 推成 SSR 并夹到 0~2",
              record["favoriteItem"] == {"rarity": "SSR", "level": 1}, repr(record["favoriteItem"]))
        check("词条按档位表换算成百分比",
              record["equipments"][0][0] == {"functionType": "StatAtk", "level": 15, "value": 14.63},
              repr(record["equipments"][0])[:160])
        check("认不出的词条类型留空",
              record["equipments"][0][1] is None and record["equipments"][0][2] is None,
              repr(record["equipments"][0])[:160])
        check("空部位是三条 null",
              record["equipments"][1] == [None, None, None], repr(record["equipments"][1]))
        check("研究所 tid 映射对了",
              store["research"]["class"]["Attacker"] == 7
              and store["research"]["corporation"]["MISSILIS"] == 5
              and store["research"]["class"]["Defender"] == 1,   # 没命中 tid 的保持默认
              repr(store["research"]))
        check("同步器按账号数据改了", store["synchroLevel"] == 456, str(store["synchroLevel"]))
        account_file.unlink()

        # 认不出的文件：要明确报错，不能静默吃掉
        weird = data_dir / "nikke-smoke-weird.json"
        weird.write_text(json.dumps({"format": "someone-else"}), encoding="utf-8")
        replies = asyncio.run(call_file_import([File(name=weird.name, file=str(weird))]))[0]
        check("陌生 format 有红灯提示",
              "🔴 读取失败" in text_of(replies) and "无法识别此文件" in text_of(replies),
              text_of(replies)[:140])
        weird.unlink()

        # 窗口过期
        text_call("妮姬导入json")
        module._PENDING[origin]["expires"] = time.time() - 1
        check("过期窗口不放行", gate.filter(FakeEvent("", messages=[component]), {}) is False)
        check("过期窗口被顺手清掉", origin not in module._PENDING, repr(list(module._PENDING)))
        profile_file.unlink()

        # 超时提醒：到点没等到文件 → @ 发命令的人（只提醒，不处理文件）
        plugin.context = StubContext()
        original_window = texts.IMPORT_FILE_WINDOW
        texts.IMPORT_FILE_WINDOW = 0.3
        try:
            async def timeout_case():
                event = FakeEvent("妮姬导入json", uid=TEST_UID, group="999")
                [item async for item in plugin.nikke_import_json(event)]
                await asyncio.sleep(0.6)

            asyncio.run(timeout_case())
        finally:
            texts.IMPORT_FILE_WINDOW = original_window
        sent = plugin.context.sent
        check("超时后发一条提醒", len(sent) == 1, repr(sent)[:160])
        if sent:
            comps = list(getattr(sent[0][1], "chain", sent[0][1]))
            check("提醒里 @ 了发命令的人",
                  any(str(getattr(component, "qq", "")) == TEST_UID for component in comps),
                  repr(comps)[:160])
            joined = "".join(str(getattr(component, "text", "")) for component in comps)
            check("提醒文案正确",
                  "检测超时" in joined and "妮姬导入json" in joined, joined[:80])
        check("超时后窗口已关", module._PENDING == {}, repr(list(module._PENDING)))

        # 已收到文件的窗口：定时器静默退场，不再发提醒
        plugin.context.sent.clear()
        texts.IMPORT_FILE_WINDOW = 0.3
        try:
            async def consumed_case():
                event = FakeEvent("妮姬导入json", uid=TEST_UID, group="999")
                [item async for item in plugin.nikke_import_json(event)]
                module._PENDING.pop(event.unified_msg_origin, None)  # 相当于文件已收到、窗口被消费
                await asyncio.sleep(0.6)

            asyncio.run(consumed_case())
        finally:
            texts.IMPORT_FILE_WINDOW = original_window
        check("已收到文件的窗口不再发超时提醒", not plugin.context.sent, repr(plugin.context.sent))

        # 提示自己发（拿 message_id）→ 到点前撤回提示 → 到点仍会 @ 提醒
        plugin.context = StubContext()
        prompt_bot = StubBot()
        try:
            texts.IMPORT_FILE_WINDOW = 2.5

            async def recall_case():
                event = FakeEvent("妮姬导入json", uid=TEST_UID, group="999", bot=prompt_bot)
                replies = [item async for item in plugin.nikke_import_json(event)]
                await asyncio.sleep(0.8)
                mid_actions = [name for name, _payload in prompt_bot.calls]
                await asyncio.sleep(2.2)
                return replies, mid_actions

            replies, mid_actions = asyncio.run(recall_case())
        finally:
            texts.IMPORT_FILE_WINDOW = original_window
        check("提示由自己发出（拿到 message_id，不再走普通回复）", replies == [], repr(replies)[:80])
        check("到点前先撤回提示",
              mid_actions[:2] == ["send_group_msg", "delete_msg"], repr(mid_actions))
        if len(prompt_bot.calls) >= 2:
            check("撤回的就是提示那条消息",
                  prompt_bot.calls[1][1].get("message_id") == 1, repr(prompt_bot.calls[1][1]))
            prompt_text = prompt_bot.calls[0][1]["message"][0]["data"]["text"]
            check("提示走群里主动发送",
                  "将档案 JSON 文件发送至此会话" in prompt_text, prompt_text[:60])
        check("到点后仍然发超时提醒", len(plugin.context.sent) == 1, repr(plugin.context.sent)[:120])

        # 读取成功：开窗提示立刻撤回（不用等 118 秒）
        success_bot = StubBot()
        payload = {
            "format": "nikke-photos-profile", "version": 1, "name": "撤回测试档",
            "synchroLevel": 200, "research": {},
            "characters": {spare[0]: {"affection": 1, "equipments": [[None, None, None] for _ in range(4)]}},
        }
        recall_file = data_dir / "nikke-smoke-recall.json"
        recall_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

        async def success_recall_case():
            open_event = FakeEvent("妮姬导入json", uid=TEST_UID, group="999", bot=success_bot)
            [entry async for entry in plugin.nikke_import_json(open_event)]
            file_event = FakeEvent("", uid=TEST_UID, group="999", bot=success_bot,
                                   messages=[File(name=recall_file.name, file=str(recall_file))])
            return [entry async for entry in plugin.nikke_import_json_file(file_event)]

        replies = asyncio.run(success_recall_case())
        recall_file.unlink()
        success_actions = [name for name, _payload in success_bot.calls]
        check("读取成功后立刻撤回开窗提示",
              success_actions == ["send_group_msg", "delete_msg"], repr(success_actions))
        check("撤回后照常发回执",
              "🟢 读取成功！ 导入到存档：" in text_of(replies), text_of(replies)[:100])

        # ── 8. 坏分享码 ─────────────────────────────────────────────
        print("8) 坏分享码")
        body = text_call("妮姬导入 这不是码")
        check("格式不对有提示", "分享码格式不正确" in body, body[:80])
        broken = char_vector["code"][:-6] + "AAAAAA"
        body = text_call(f"妮姬导入 {broken}")
        check("CRC 坏掉有提示", "损坏" in body or "版本" in body, body[:80])

        # ── 9. 多存档 ───────────────────────────────────────────────
        print("9) 多存档（新建/切换/改名/删除/迁移）")
        legacy_uid = "10002"
        legacy_path = store_mod.user_store_path(legacy_uid)
        legacy_path.parent.mkdir(parents=True, exist_ok=True)
        legacy_path.write_text(json.dumps({
            "version": 1, "synchroLevel": 321, "research": {},
            "characters": {"5007": {"affection": 5}}, "statsTable": {"nameCodes": []},
        }, ensure_ascii=False), encoding="utf-8")
        check("旧单档迁移成「存档1」且数据保留",
              store_mod.current_profile_name(legacy_uid) == "存档1"
              and store_mod.load(legacy_uid)["synchroLevel"] == 321)
        check("迁移留了原始备份",
              (legacy_path.parent / (legacy_path.name + ".premigrate.bak")).is_file())

        body = text_call("妮姬存档")
        check("存档命令报出当前档与列表",
              "当前存档：存档1" in body and "▍全部存档" in body, body[:160])

        body = text_call("妮姬新建存档 日服号")
        check("新建成功且提示切档", "已新建存档「日服号」" in body and "切换存档" in body, body[:160])
        check("新建不自动切档", store_mod.current_profile_name(TEST_UID) == "存档1")
        body = text_call("妮姬新建存档 日服号")
        check("重名被拦", "已经有一个叫" in body, body[:120])
        body = text_call("妮姬新建存档 多余 参数")
        check("参数数量不对报用法", "用法：" in body, body[:80])

        # 数据隔离：当前档写个标记，切走看不到
        store_mod.update(TEST_UID, lambda st: st["characters"].__setitem__("9999", {"affection": 1}))
        body = text_call("妮姬切换存档 日服号")
        check("切换成功", "已切换到存档「日服号」" in body, body[:120])
        check("切档后是干净档", "9999" not in store_mod.load(TEST_UID)["characters"])
        body = text_call("妮姬切换存档 不存在的档")
        check("切不存在的档列出可用档名", "没有叫" in body and "现有：" in body, body[:160])

        body = text_call("妮姬修改存档 日服号 日服小号")
        check("改名成功", "改名为「日服小号」" in body, body[:120])
        body = text_call("妮姬修改存档 日服小号 存档1")
        check("改名撞重名被拦", "已经有一个叫" in body, body[:120])
        body = text_call("妮姬修改存档 没这个档 x")
        check("改不存在的档被拦", "没有叫" in body, body[:120])

        body = text_call("妮姬删除存档 日服小号")
        check("删当前档成功且自动切回",
              "已删除存档「日服小号」" in body and "当前存档已切换为「存档1」" in body, body[:160])
        check("删当前档后确实是存档1", store_mod.current_profile_name(TEST_UID) == "存档1")
        body = text_call("妮姬删除存档 存档1")
        check("最后一个档拒绝删除", "最后一个存档" in body, body[:120])

        # ── 10. 群排行 + 列表合并转发 ───────────────────────────────
        print("10) 群排行与列表合并转发")
        body = text_call("妮姬群排行 拉毗")
        check("群排行在私聊里被拦", "只能在群里用" in body, body[:80])

        replies, _ = asyncio.run(call_with_event("妮姬群排行", group="888"))
        check("群排行缺参数报用法", "用法：/妮姬群排行 <角色>" in text_of(replies), repr(replies)[:80])

        replies, _ = asyncio.run(call_with_event("妮姬群排行 不存在甲乙丙", group="888"))
        check("群排行认不出的角色有提示", "没找到叫" in text_of(replies), repr(replies)[:80])

        replies, _ = asyncio.run(call_with_event(
            "妮姬群排行 " + name, group="888", uid="10005", bot=StubBot(fail_members=True)))
        check("拿不到群成员名单有提示", "群成员名单获取失败" in text_of(replies), repr(replies)[:80])

        members = [{"user_id": TEST_UID, "nickname": "路人甲", "card": "冒烟群名片"},
                   {"user_id": "9999999", "nickname": "没数据的人", "card": ""}]
        stub = StubBot(members=members)
        replies, _ = asyncio.run(call_with_event(f"妮姬群排行 {name}", group="888", bot=stub))
        paths = images_of(replies)
        check("群排行出一张图", len(paths) == 1, repr(replies)[:120])
        if paths:
            from PIL import Image

            with Image.open(paths[0]) as image:
                check("群排行图比卡片宽（带序号列）", image.width > 700 and image.height > 100,
                      str(image.size))
        check("查名单走的是 get_group_member_list",
              bool(stub.calls) and stub.calls[0][0] == "get_group_member_list", repr(stub.calls[:1]))

        replies, _ = asyncio.run(call_with_event(f"妮姬群排行 {name}", group="888", bot=stub))
        check("CD 内再发被拦",
              "只能查一次" in text_of(replies) and "秒后再试" in text_of(replies), repr(replies)[:120])

        replies, _ = asyncio.run(call_with_event(
            f"妮姬群排行 {name}", group="888", uid="10006",
            bot=StubBot(members=[{"user_id": "9999999", "nickname": "没数据的人"}])))
        check("本群没人上榜有提示", "还没有人完善" in text_of(replies), repr(replies)[:100])

        # >30 人：拆图 + 合并转发（假协议端只验节点结构，不动真 QQ）
        for rank_uid in RANK_UIDS:
            store_mod.update(rank_uid,
                             lambda st: st["characters"].__setitem__(codes[0], {"equipments": filled}))
        crowd = [{"user_id": TEST_UID, "nickname": "冒烟群名片", "card": "冒烟群名片"}] + [
            {"user_id": rank_uid, "nickname": f"群友{index:02d}", "card": ""}
            for index, rank_uid in enumerate(RANK_UIDS, start=1)
        ]
        flood = StubBot(members=crowd)
        replies, _ = asyncio.run(call_with_event(
            f"妮姬群排行 {name}", group="888", uid="10007", bot=flood))
        forwards = [item for item in flood.calls if item[0] == "send_group_forward_msg"]
        check("32 人被拆成 2 张图、走合并转发",
              len(images_of(replies)) == 0 and len(forwards) == 1
              and len(forwards[0][1]["messages"]) == 2,
              repr(replies)[:100] + repr(flood.calls[:2])[:200])
        if forwards:
            nodes = forwards[0][1]["messages"]
            check("转发节点里是 base64 图片",
                  all(node["data"]["content"][0]["type"] == "image"
                      and node["data"]["content"][0]["data"]["file"].startswith("base64://")
                      for node in nodes),
                  repr(nodes[0]["data"]["content"][0])[:160])
            check("转发挂在群里", forwards[0][1].get("group_id") == "888",
                  repr(forwards[0][1].get("group_id")))

        # 列表：有数据时三个节点（查询人 / 可进名单 / 未完善名单）
        list_stub = StubBot()
        replies, _ = asyncio.run(call_with_event("妮姬列表", group="888", bot=list_stub))
        forwards = [item for item in list_stub.calls if item[0] == "send_group_forward_msg"]
        check("列表走合并转发", len(images_of(replies)) == 0 and len(forwards) == 1, repr(replies)[:100])
        if forwards:
            nodes = forwards[0][1]["messages"]
            first_text = nodes[0]["data"]["content"][0]["data"]["text"]
            head_text = nodes[1]["data"]["content"][0]["data"]["text"]
            last_text = nodes[-1]["data"]["content"][0]["data"]["text"]
            check("列表首节点是查询人（群名片+QQ）",
                  "查询人：冒烟群名片（10001）" in first_text, first_text[:80])
            check("列表第二节点带存档与统计",
                  "当前存档：存档1" in head_text and "同步器 LV." in head_text, head_text[:100])
            check("列表末节点是未完善名单",
                  len(nodes) == 3 and "未完善装备词条的角色" in last_text, repr(len(nodes)))

        print()
        print(f"指令冒烟：{checks - len(failures)}/{checks} 通过")
        for item in failures:
            print(f"  FAILED: {item}")
        return 1 if failures else 0
    finally:
        # 测试 QQ 的存档（含迁移/删除备份）与出图都不留在服务器上
        for uid in (TEST_UID, "10002", *RANK_UIDS):
            path = store_mod.user_store_path(uid)
            targets = [
                path,
                path.with_name(path.name + ".premigrate.bak"),
                path.with_name(path.name + ".tmp"),
            ]
            targets += list(path.parent.glob(path.name + ".deleted-*"))
            for item in targets:
                if item.is_file():
                    item.unlink()
        shutil.rmtree(Path(store_mod.paths.user_data_dir()) / "out", ignore_errors=True)
        print(f"已清理测试数据：{store_mod.user_store_path(TEST_UID).parent}")


if __name__ == "__main__":
    sys.exit(main())
