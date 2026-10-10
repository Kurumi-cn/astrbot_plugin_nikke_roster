"""QQ 头像获取：下载 + 按 QQ 号缓存，失败返回 None（调用方回退显示 QQ 号文字）。

用腾讯公开的头像接口（qlogo），不依赖协议端 API——私聊/群聊拿到的 QQ 号都能直接取。
缓存放在用户数据目录（容器持久化），同一个 QQ 只下一次；坏响应不落盘，下次还能重试。
"""
from __future__ import annotations

import urllib.request
from io import BytesIO

from . import paths

#: 头像接口（100×100 足够表格角落用：32 设计单位 @2x = 64px）
_URL = "https://q1.qlogo.cn/g?b=qq&nk={qq}&s=100"
#: 网络超时（出图是交互操作，等不起太久；超时就走降级显示 QQ 号）
_TIMEOUT = 5.0


def cache_dir():
    d = paths.user_data_dir() / "qq_avatars"
    d.mkdir(parents=True, exist_ok=True)
    return d


def qq_avatar(qq: str):
    """取 QQ 头像（PIL Image，RGBA）；取不到返回 None。

    先看磁盘缓存；没有就联网下载，成功才落盘。
    """
    qq = str(qq or "").strip()
    if not qq.isdigit():
        return None

    from PIL import Image

    path = cache_dir() / f"{qq}.png"
    if path.is_file():
        try:
            with Image.open(path) as cached:
                return cached.convert("RGBA")
        except Exception:
            try:
                path.unlink()
            except OSError:
                pass  # 缓存坏了当没有，重新下载

    try:
        with urllib.request.urlopen(_URL.format(qq=qq), timeout=_TIMEOUT) as resp:
            data = resp.read()
        with Image.open(BytesIO(data)) as remote:
            image = remote.convert("RGBA")
    except Exception:
        return None

    try:
        image.save(path, "PNG")
    except Exception:
        pass  # 缓存写不了不影响本次出图
    return image