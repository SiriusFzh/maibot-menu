"""
菜单插件 — 发送 /菜单 即可查看麦麦的所有功能和指令
"""

import base64
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from maibot_sdk import Command, Field, MaiBotPlugin, PluginConfigBase


# ==================== 字体加载 ====================

_FONTS_DIR = os.path.join(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
), "khiqwq_daily_analysis", "fonts")

_FONT_FACE_CSS = ""


def _build_font_face_css() -> str:
    bundled = [
        ("ZCOOL KuaiLe", "ZCOOLKuaiLe-Regular.woff2"),
        ("Patrick Hand", "PatrickHand-Regular.woff2"),
    ]
    faces = []
    for family, filename in bundled:
        path = os.path.join(_FONTS_DIR, filename)
        try:
            with open(path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("utf-8")
            faces.append(
                f"@font-face{{font-family:'{family}';"
                f"src:url(data:font/woff2;base64,{b64}) format('woff2');"
                f"font-weight:normal;font-style:normal;font-display:swap;}}"
            )
        except Exception:
            pass
    if not faces:
        return ""
    return "<style>" + "".join(faces) + "</style>"


_FONT_FACE_CSS = _build_font_face_css()

# ==================== 指令 pattern 可读化 ====================


def _simplify_pattern(pattern: str) -> str:
    """把正则 pattern 转成人类可读的指令格式。

    ^/summary  ->  /summary [参数]
    ^/菜单     ->  /菜单
    """
    if not pattern:
        return ""
    s = pattern.strip()
    # 去头尾锚点
    if s.startswith("^"):
        s = s[1:]
    if s.endswith("$"):
        s = s[:-1]
    # 去掉命名捕获组，替换为 [参数]
    s = re.sub(r"\(\?P<\w+>.*?\)", "[参数]", s)
    # 去掉非捕获组标记
    s = s.replace("(?:", "(")
    # 去掉 ? 量词
    s = re.sub(r"\)\?", "]", s)
    # 清理残留正则语法
    s = s.replace("\\s+", " ")
    s = s.replace("\\s", " ")
    s = re.sub(r"\\.", "", s)  # 去掉剩余转义
    s = re.sub(r"[()[\]{}|]", "", s)  # 去括号
    s = re.sub(r"\s+", " ", s).strip()
    return s


# ==================== 配置模型 ====================


class PluginSection(PluginConfigBase):
    __ui_label__ = "插件"
    __ui_order__ = 0

    enabled: bool = Field(default=True, description="是否启用插件",
                          json_schema_extra={"label": "启用插件"})
    config_version: str = Field(default="1.0.0", description="配置版本",
                                json_schema_extra={"label": "配置版本", "disabled": True})


class MenuSection(PluginConfigBase):
    __ui_label__ = "菜单"
    __ui_order__ = 1

    exclude_plugins: List[str] = Field(
        default_factory=lambda: ["builtin.plugin-management"],
        description="在菜单中隐藏的这些插件 ID",
        json_schema_extra={"label": "排除插件"},
    )


class MenuConfig(PluginConfigBase):
    plugin: PluginSection = Field(default_factory=PluginSection)
    menu: MenuSection = Field(default_factory=MenuSection)


# ==================== 插件主类 ====================


class MenuPlugin(MaiBotPlugin):

    config_model = MenuConfig

    async def on_load(self) -> None:
        self.ctx.logger.info("菜单插件已加载")

    async def on_unload(self) -> None:
        self.ctx.logger.info("菜单插件已卸载")

    # ==================== 命令 ====================

    @Command("menu", description="显示麦麦所有功能和指令", pattern=r"^/菜单$")
    async def cmd_menu(
        self, stream_id: str = "", group_id: str = "", **kwargs: Any
    ) -> Tuple[bool, str, bool]:
        try:
            result = await self.ctx.component.get_all_plugins()
            if not isinstance(result, dict) or not result.get("success"):
                await self.ctx.send.text("获取插件列表失败了，稍后再试吧~", stream_id)
                return True, "get_all_plugins 失败", True

            all_plugins = result.get("plugins", {})
            exclude_ids = set(str(p) for p in self.config.menu.exclude_plugins)

            menu_items: List[Dict] = []
            total_commands = 0

            for pid, pinfo in sorted(all_plugins.items()):
                if not isinstance(pinfo, dict):
                    continue
                # 跳过内置和排除的插件
                if pid.startswith("builtin.") or pid in exclude_ids:
                    continue
                if not pinfo.get("enabled", True):
                    continue

                components = pinfo.get("components", [])
                if not isinstance(components, list):
                    continue

                commands = []
                for comp in components:
                    if not isinstance(comp, dict):
                        continue
                    # 只取 TOOL 类型的命令组件
                    if comp.get("type") != "TOOL" or not comp.get("enabled", True):
                        continue
                    meta = comp.get("metadata")
                    if not isinstance(meta, dict):
                        continue
                    pattern = meta.get("pattern", "")
                    description = meta.get("description", "")
                    if not pattern and not description:
                        continue

                    cmd = _simplify_pattern(str(pattern))
                    desc = str(description or "")
                    if not cmd and not desc:
                        continue
                    if not cmd:
                        cmd = desc  # 没 pattern 就用描述当指令名
                    commands.append((cmd, desc))
                    total_commands += 1

                if commands:
                    menu_items.append({
                        "id": pid,
                        "version": pinfo.get("version", ""),
                        "commands": commands,
                    })

            if not menu_items:
                await self.ctx.send.text("目前还没有可用的指令哦~", stream_id)
                return True, "无可用指令", True

            html = self._build_menu_html(menu_items, total_commands)
            image_base64 = await self._render_image(html)

            if image_base64:
                await self.ctx.send.image(image_base64, stream_id)
                return True, "菜单图片已发送", True

            # 渲染失败，降级为纯文本
            text = "当前可用指令：\n"
            for item in menu_items:
                text += f"\n【{item['id']} v{item['version']}】\n"
                for cmd, desc in item["commands"]:
                    text += f"  {cmd}"
                    if desc:
                        text += f" — {desc}"
                    text += "\n"
            await self.ctx.send.text(text, stream_id)
            return True, "菜单文本已发送", True

        except Exception as e:
            self.ctx.logger.error(f"执行 /菜单 出错: {e}", exc_info=True)
            await self.ctx.send.text("菜单生成失败了，待会再试试吧~", stream_id)
            return False, str(e), True

    # ==================== 图片渲染 ====================

    def _build_menu_html(self, menu_items: List[Dict], total_commands: int) -> str:
        cards = ""
        for item in menu_items:
            pid = item["id"]
            version = item.get("version", "")
            cmds_html = ""
            for cmd, desc in item["commands"]:
                desc_part = f'<span class="cmd-desc">{desc}</span>' if desc else ""
                cmds_html += f'<div class="cmd-line"><code class="cmd-text">{cmd}</code>{desc_part}</div>\n'

            cards += f"""
            <div class="plugin-card">
                <div class="plugin-header">
                    <span class="plugin-name">{pid}</span>
                    <span class="plugin-version">v{version}</span>
                </div>
                <div class="plugin-commands">{cmds_html}</div>
            </div>"""

        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8">{_FONT_FACE_CSS if _FONT_FACE_CSS else ""}<style>
:root {{
    --bg: #fdfbf7;
    --card-bg: #fff;
    --ink: #5d4037;
    --ink-light: #8d6e63;
    --accent: #ff7043;
    --tag-bg: #fff3e0;
    --border: #e0d8cc;
    --font-title: 'ZCOOL KuaiLe', 'Microsoft YaHei', 'PingFang SC', sans-serif;
    --font-body: 'Microsoft YaHei', 'PingFang SC', sans-serif;
    --font-hand: 'Patrick Hand', 'KaiTi', 'Microsoft YaHei', cursive;
}}
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{
    font-family: var(--font-body);
    color: var(--ink);
    background: var(--bg);
    background-image: radial-gradient(#ddd 2px, transparent 2px);
    background-size: 20px 20px;
    padding: 32px 24px;
    min-height: 100vh;
}}
.header {{
    text-align: center;
    margin-bottom: 28px;
}}
.header h1 {{
    font-family: var(--font-title);
    font-size: 32px;
    color: var(--accent);
    margin-bottom: 4px;
}}
.header .subtitle {{
    font-family: var(--font-hand);
    font-size: 18px;
    color: var(--ink-light);
}}
.plugin-card {{
    background: var(--card-bg);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 16px 20px;
    margin-bottom: 14px;
    box-shadow: 0 2px 6px rgba(0,0,0,0.04);
}}
.plugin-header {{
    display: flex;
    align-items: baseline;
    gap: 10px;
    margin-bottom: 10px;
    border-bottom: 1px dashed var(--border);
    padding-bottom: 8px;
}}
.plugin-name {{
    font-family: var(--font-title);
    font-size: 18px;
    color: var(--ink);
}}
.plugin-version {{
    font-size: 13px;
    color: var(--ink-light);
    background: var(--tag-bg);
    padding: 2px 8px;
    border-radius: 8px;
}}
.plugin-commands {{
    display: flex;
    flex-direction: column;
    gap: 6px;
}}
.cmd-line {{
    display: flex;
    align-items: baseline;
    gap: 8px;
    flex-wrap: wrap;
}}
.cmd-text {{
    font-family: 'Consolas', 'Courier New', monospace;
    font-size: 14px;
    font-weight: 600;
    color: var(--accent);
    background: #fff8f0;
    padding: 2px 8px;
    border-radius: 5px;
    white-space: nowrap;
}}
.cmd-desc {{
    font-size: 14px;
    color: var(--ink-light);
}}
.footer {{
    text-align: center;
    margin-top: 28px;
    font-family: var(--font-hand);
    font-size: 14px;
    color: var(--ink-light);
}}
</style></head>
<body>
<div class="header">
    <h1>麦麦功能菜单</h1>
    <div class="subtitle">{len(menu_items)} 个插件 · {total_commands} 条指令</div>
</div>
{cards}
<div class="footer">发送指令即可使用对应功能</div>
</body></html>"""

    async def _render_image(self, html: str) -> Optional[str]:
        """把 HTML 渲染成 PNG base64，失败返回 None"""
        try:
            result = await self.ctx.render.html2png(
                html=html,
                selector="body",
                viewport={"width": 800, "height": 600},
                device_scale_factor=2.0,
                full_page=True,
                wait_until="load",
                allow_network=False,
                render_timeout_ms=15000,
            )
        except Exception as e:
            self.ctx.logger.error(f"菜单图片渲染异常: {e}", exc_info=True)
            return None

        return self._extract_base64(result)

    @staticmethod
    def _extract_base64(result: Any) -> Optional[str]:
        if isinstance(result, str):
            return result or None
        if not isinstance(result, dict):
            return None
        if result.get("success") is False:
            return None
        direct = result.get("image_base64")
        if isinstance(direct, str) and direct:
            return direct
        for key in ("result", "data", "value"):
            nested = result.get(key)
            if isinstance(nested, dict):
                b64 = nested.get("image_base64")
                if isinstance(b64, str) and b64:
                    return b64
            elif isinstance(nested, str) and nested and key != "result":
                return nested
        return None


def create_plugin() -> MenuPlugin:
    return MenuPlugin()
