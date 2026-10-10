r"""立绘自动对齐的前后对比：把「按躯干重心对齐」前后的角色卡并排出图，供人工确认。

    python bot/tools/art-align-compare.py [输出目录] [--top 8] [--controls 3] [--scale 1]

不改命令行出图行为，纯粹是给眼睛看的验证工具。挑选规则：扫描角色表里所有立绘，
按「躯干重心偏离中线」排序，取最偏的若干张（另加几张几乎不偏的作对照）——
偏得厉害的正是肉眼能看出「偏左/偏右」的那些。

用的素材与 render-preview.py 一致（app/public + 插件字体），所以看到的就是真实出图。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

BOT_DIR = Path(__file__).resolve().parent.parent
PLUGIN_DIR = BOT_DIR / "astrbot_plugin_nikke_roster"
if str(PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(PLUGIN_DIR))

from PIL import Image, ImageDraw  # noqa: E402

from core import card, gamedata, imaging, paths, roster as roster_mod  # noqa: E402

paths.FALLBACK_ASSETS_DIR = BOT_DIR.parent / "app" / "public"
if not paths.FALLBACK_ASSETS_DIR.is_dir():
    print(f"备用素材目录不存在：{paths.FALLBACK_ASSETS_DIR}")
    sys.exit(1)

ART_ROOT = "ui-assets/nikke/character-artwork"


def _equipment(name: str, tiers: list[int | None]) -> list[dict | None]:
    return [
        {"functionType": name, "level": tier, "value": gamedata.affix_tier_value(name, tier)} if tier else None
        for tier in tiers
    ]


# 对照档案：中等练度即可，卡片 UI 不是这次要看的重点
RECORD = {
    "limitBreak": {"grade": 2, "core": 4},
    "affection": 20,
    "combat": 98765,
    "skills": {"skill1": 8, "skill2": 7, "burst": 9},
    "cube": {"resourceId": 10004, "level": 10},
    "favoriteItem": {"rarity": "R", "level": 1},
    "equipments": [
        _equipment("IncElementDmg", [15, 12, 10]),
        _equipment("StatAtk", [15, 15, 9]),
        _equipment("StatCritical", [13, 7, None]),
        _equipment("StatCriticalDamage", [10, 5, 3]),
    ],
}


def collect(table: roster_mod.Roster) -> list[dict]:
    """每个立绘算一次躯干重心，按偏离中线从大到小排。

    同一角色只留**最偏的那张**（渡鸦有 3 张 c851 变体，不裁的话会占满榜单），
    这样取 top N 能覆盖 N 个不同角色。同一文件也只留一条。
    """
    seen: dict[str, dict] = {}
    for char in table.characters:
        for art in (char.get("artworks") or []):
            file = art.get("file")
            if not file or file in seen:
                continue
            image = imaging.load_asset(f"{ART_ROOT}/{file}")
            if image is None:
                continue
            anchor = imaging.art_h_anchor(image)
            if anchor is None:
                continue
            seen[file] = {"char": char, "artwork_id": art.get("id"), "file": file, "anchor": anchor}

    ordered = sorted(seen.values(), key=lambda item: abs(item["anchor"] - 0.5), reverse=True)
    picked: dict[str, dict] = {}
    for item in ordered:
        picked.setdefault(str(item["char"]["nameCode"]), item)
    return list(picked.values())


def compose(before: Image.Image, after: Image.Image, case: dict, scale: int) -> Image.Image:
    width, height = before.size
    gap, head = 14 * scale, 88 * scale
    sheet = Image.new("RGB", (width * 2 + gap, height + head), (255, 255, 255))
    # 先画参考线再贴图是会被盖住的，所以贴完再画（半透明红虚线 = 卡片中线）
    sheet.paste(before, (0, head))
    sheet.paste(after, (width + gap, head))

    draw = ImageDraw.Draw(sheet, "RGBA")
    for origin in (0, width + gap):
        x = origin + width // 2
        for y in range(head, head + height, 12 * scale):
            draw.line([(x, y), (x, y + 7 * scale)], fill=(230, 40, 40, 190), width=max(1, scale))

    font = imaging.font("cn", 24 * scale)
    name = case["char"].get("nameCn") or case["char"]["nameCode"]
    draw.text(
        (10 * scale, 10 * scale),
        f'{name} · {case["file"]} · 重心 {case["anchor"]:.3f}（偏 {case["anchor"] - 0.5:+.1%}）',
        font=font, fill=(30, 30, 30),
    )
    draw.text((10 * scale, head - 32 * scale), "对齐前（画布居中）", font=font, fill=(184, 62, 62))
    draw.text((width + gap + 10 * scale, head - 32 * scale), "对齐后（躯干重心居中）", font=font, fill=(38, 122, 64))
    return sheet


def contact(sheets: list[Image.Image], target_width: int = 620, gap: int = 8) -> Image.Image:
    thumbs = []
    for sheet in sheets:
        ratio = target_width / sheet.width
        thumbs.append(sheet.resize((target_width, round(sheet.height * ratio)), Image.LANCZOS))
    total = sum(t.height for t in thumbs) + gap * max(0, len(thumbs) - 1)
    canvas = Image.new("RGB", (target_width, total), (225, 225, 225))
    y = 0
    for thumb in thumbs:
        canvas.paste(thumb, (0, y))
        y += thumb.height + gap
    return canvas


def main() -> int:
    parser = argparse.ArgumentParser(description="立绘自动对齐前后对比")
    parser.add_argument("out_dir", nargs="?", default=str(BOT_DIR / "seed" / "art-align"))
    parser.add_argument("--top", type=int, default=8, help="取偏离最厉害的几张")
    parser.add_argument("--controls", type=int, default=3, help="额外取几乎不偏的几张作对照")
    parser.add_argument("--scale", type=int, default=1, help="渲染倍数（1 → 736×1096）")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    candidates = collect(roster_mod.load())
    if not candidates:
        print("角色表里没有可用立绘")
        return 1

    cases = list(candidates[: args.top])
    picked = {case["file"] for case in cases}
    for case in reversed(candidates[-args.controls:] if args.controls else []):
        if case["file"] not in picked:
            cases.append(case)
            picked.add(case["file"])

    print(f"{'角色':<14} {'立绘':<26} {'重心':>7} {'偏移':>8}   输出")
    sheets: list[Image.Image] = []
    for index, case in enumerate(cases, 1):
        before = card.render_card(case["char"], RECORD, scale=args.scale,
                                  artwork_id=case["artwork_id"], art_auto_align=False)
        after = card.render_card(case["char"], RECORD, scale=args.scale,
                                 artwork_id=case["artwork_id"], art_auto_align=True)
        sheet = compose(before, after, case, args.scale)
        target = out_dir / f"{index:02d}_{case['file']}.png"
        sheet.save(target)
        sheets.append(sheet)
        name = case["char"].get("nameCn") or case["char"]["nameCode"]
        print(f"{name:<14} {case['file']:<26} {case['anchor']:7.3f} "
              f"{case['anchor'] - 0.5:+8.1%}   {target.name}")

    contact(sheets).save(out_dir / "_汇总.png")

    missing = card.missing_assets()
    if missing:
        print(f"\n读不到的素材 {len(missing)} 个：{missing[:10]}")
    print(f"\n输出目录：{out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
