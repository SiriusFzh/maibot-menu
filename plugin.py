"""
菜单插件 — 发送 /菜单 即可查看麦麦的所有功能和指令
"""

import base64
import json
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

def _extract_commands_from_config(plugin_id: str) -> List[Tuple[str, str]]:
    """尝试从插件的 config.toml 中提取命令前缀（用于 @HookHandler 型插件）。"""
    try:
        plugins_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for entry in os.listdir(plugins_dir):
            entry_path = os.path.join(plugins_dir, entry)
            if not os.path.isdir(entry_path):
                continue
            manifest_path = os.path.join(entry_path, "_manifest.json")
            if not os.path.exists(manifest_path):
                continue
            try:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    manifest = json.loads(f.read())
                if manifest.get("id") != plugin_id:
                    continue
            except Exception:
                continue
            config_path = os.path.join(entry_path, "config.toml")
            if not os.path.exists(config_path):
                return []
            try:
                import tomlkit
                with open(config_path, "r", encoding="utf-8") as f:
                    raw = tomlkit.load(f).unwrap()
            except Exception:
                return []
            result = []
            def _find_commands(obj: Any, section: str = ""):
                if isinstance(obj, dict):
                    for k, v in obj.items():
                        _find_commands(v, k)
                elif isinstance(obj, list):
                    for item in obj:
                        if isinstance(item, str) and item.startswith("/"):
                            result.append((item, section))
            _find_commands(raw)
            return result
    except Exception:
        return []


_MANIFEST_CACHE: Dict[str, Dict] = {}

def _read_manifest(plugin_id: str) -> Dict:
    """读取插件 _manifest.json，返回 {name, description}，有缓存"""
    if plugin_id in _MANIFEST_CACHE:
        return _MANIFEST_CACHE[plugin_id]
    try:
        plugins_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for entry in os.listdir(plugins_dir):
            entry_path = os.path.join(plugins_dir, entry)
            if not os.path.isdir(entry_path):
                continue
            manifest_path = os.path.join(entry_path, "_manifest.json")
            if not os.path.exists(manifest_path):
                continue
            try:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    m = json.loads(f.read())
                if m.get("id") == plugin_id:
                    _MANIFEST_CACHE[plugin_id] = {
                        "name": m.get("name", plugin_id),
                        "description": m.get("description", ""),
                    }
                    return _MANIFEST_CACHE[plugin_id]
            except Exception:
                continue
    except Exception:
        pass
    fallback = {"name": plugin_id, "description": ""}
    _MANIFEST_CACHE[plugin_id] = fallback
    return fallback


_ADAPTER_PLUGINS = {"maibot-team.napcat-adapter", "maibot-team.snowluma-adapter"}

_EXCLUDE_BY_NAME = {"Hello World"}


_DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "commands.json")


def _load_custom_commands() -> Dict[str, List[Tuple[str, str]]]:
    """从 commands.json 加载自定义命令
    格式: {"功能名": {"items": [{"command": "...", "desc": "..."}]}}
    """
    try:
        if os.path.exists(_DATA_FILE):
            with open(_DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            result = {}
            for name, obj in data.items():
                items = obj.get("items", []) if isinstance(obj, dict) else []
                result[name] = []
                for item in items:
                    if isinstance(item, dict):
                        cmd = item.get("command", "")
                        desc = item.get("desc", "")
                        if cmd:
                            result[name].append((cmd, desc))
            return result
    except Exception:
        pass
    return {}


def _save_custom_commands(data: Dict[str, List[Tuple[str, str]]]) -> None:
    """保存到 commands.json
    格式: {"功能名": {"functionName": "功能名", "items": [{"command": "...", "desc": "..."}]}}
    """
    out = {}
    for name, cmds in data.items():
        out[name] = {
            "functionName": name,
            "items": [{"command": c[0], "desc": c[1]} for c in cmds],
        }
    with open(_DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)


def _features_to_dict(features: List[Any]) -> Dict[str, List[Tuple[str, str]]]:
    """把 FeatureItem 列表转成 {name: [(cmd, desc)]} — 解析 commands 里的「命令 : 描述」格式"""
    result = {}
    for feat in features:
        name = getattr(feat, "name", "") or ""
        if not name:
            continue
        cmds = getattr(feat, "commands", []) or []
        result[name] = []
        for line in cmds:
            line = str(line).strip()
            if not line:
                continue
            # 支持 : 和 ：
            parts = line.split(":", 1) if ":" in line else line.split("：", 1)
            cmd = parts[0].strip()
            desc = parts[1].strip() if len(parts) > 1 else ""
            if cmd:
                result[name].append((cmd, desc))
    return result


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


class FeatureItem(PluginConfigBase):
    """一个功能分组 — 命令列表用「命令 | 描述」格式，每行一条"""
    __ui_label__ = "功能"
    __ui_icon__ = "package"

    name: str = Field(
        default="",
        description="功能名称，例如 每日分析",
        json_schema_extra={"label": "功能名称"},
    )
    commands: List[str] = Field(
        default_factory=list,
        description='每行格式: /命令 : 功能描述，例如 /summary : 生成群聊总结',
        json_schema_extra={"label": "指令列表", "hint": "每行格式: /命令 : 描述"},
    )


class MenuSection(PluginConfigBase):
    __ui_label__ = "菜单"
    __ui_order__ = 1

    features: List[FeatureItem] = Field(
        default_factory=list,
        description="手动配置的功能分组和指令",
        json_schema_extra={"label": "功能列表"},
    )
    exclude_plugins: List[str] = Field(
        default_factory=lambda: ["builtin.plugin-management"],
        description="在自动检测中隐藏的插件 ID",
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

    async def on_config_update(self, scope: str, config_data: dict, version: str) -> None:
        """配置热更新时不做特殊处理，配置已通过 self.config 实时生效"""
        pass

    # ==================== 菜单管理命令 ====================

    @Command("menu_add", description="添加一个功能分类", pattern=r"^/菜单添加\s+(?P<args>.+)$")
    async def cmd_menu_add(
        self, stream_id: str = "", group_id: str = "", **kwargs: Any
    ) -> Tuple[bool, str, bool]:
        args = ((kwargs.get("matched_groups") or {}).get("args") or "").strip()
        if not args:
            await self.ctx.send.text("用法: /菜单添加 功能名", stream_id)
            return True, "无参数", True
        data = _load_custom_commands()
        if args in data:
            await self.ctx.send.text(f"功能【{args}】已存在，用 /菜单指令 添加指令吧", stream_id)
            return True, "已存在", True
        data[args] = []
        _save_custom_commands(data)
        await self.ctx.send.text(f"已添加功能【{args}】，用 /菜单指令 给它添加指令吧", stream_id)
        return True, f"已添加 {args}", True

    @Command("menu_cmd", description="给功能添加一条指令",
             pattern=r"^/菜单指令\s+(?P<args>.+)$")
    async def cmd_menu_cmd(
        self, stream_id: str = "", group_id: str = "", **kwargs: Any
    ) -> Tuple[bool, str, bool]:
        args = ((kwargs.get("matched_groups") or {}).get("args") or "").strip()
        parts = args.split(None, 2)
        if len(parts) < 2:
            await self.ctx.send.text("用法: /菜单指令 功能名 指令 [描述]", stream_id)
            return True, "参数不足", True
        name = parts[0]
        cmd = parts[1]
        desc = parts[2] if len(parts) > 2 else ""
        data = _load_custom_commands()
        if name not in data:
            await self.ctx.send.text(f"功能【{name}】不存在，先用 /菜单添加 创建", stream_id)
            return True, "功能不存在", True
        data[name].append((cmd, desc))
        _save_custom_commands(data)
        info = f"{cmd} {'— ' + desc if desc else ''}"
        await self.ctx.send.text(f"已添加: 【{name}】{info}", stream_id)
        return True, f"添加成功 {cmd}", True

    @Command("menu_del", description="删除一个功能分类",
             pattern=r"^/菜单删除\s+(?P<args>.+)$")
    async def cmd_menu_del(
        self, stream_id: str = "", group_id: str = "", **kwargs: Any
    ) -> Tuple[bool, str, bool]:
        args = ((kwargs.get("matched_groups") or {}).get("args") or "").strip()
        if not args:
            await self.ctx.send.text("用法: /菜单删除 功能名", stream_id)
            return True, "无参数", True
        data = _load_custom_commands()
        if args not in data:
            await self.ctx.send.text(f"功能【{args}】不存在", stream_id)
            return True, "不存在", True
        del data[args]
        _save_custom_commands(data)
        await self.ctx.send.text(f"已删除功能【{args}】及其所有指令", stream_id)
        return True, f"已删除 {args}", True

    @Command("menu_delcmd", description="删除一条指令",
             pattern=r"^/菜单删指令\s+(?P<args>.+)$")
    async def cmd_menu_delcmd(
        self, stream_id: str = "", group_id: str = "", **kwargs: Any
    ) -> Tuple[bool, str, bool]:
        args = ((kwargs.get("matched_groups") or {}).get("args") or "").strip()
        parts = args.split(None, 1)
        if len(parts) < 2:
            await self.ctx.send.text("用法: /菜单删指令 功能名 指令", stream_id)
            return True, "参数不足", True
        name = parts[0]
        target = parts[1]
        data = _load_custom_commands()
        if name not in data:
            await self.ctx.send.text(f"功能【{name}】不存在", stream_id)
            return True, "不存在", True
        before = len(data[name])
        data[name] = [(c, d) for c, d in data[name] if c != target]
        if len(data[name]) == before:
            await self.ctx.send.text(f"未找到指令【{target}】", stream_id)
            return True, "未找到", True
        _save_custom_commands(data)
        await self.ctx.send.text(f"已从【{name}】中删除指令【{target}】", stream_id)
        return True, f"已删除 {target}", True

    # ==================== 菜单展示命令 ====================

    @Command("menu", description="显示麦麦所有功能和指令", pattern=r"^/菜单$")
    async def cmd_menu(
        self, stream_id: str = "", group_id: str = "", **kwargs: Any
    ) -> Tuple[bool, str, bool]:
        try:
            # 只读菜单配置，不做任何全局插件扫描
            manual = _load_custom_commands()
            for name, cmds in _features_to_dict(self.config.menu.features).items():
                manual.setdefault(name, []).extend(cmds)

            if not manual:
                await self.ctx.send.text("还没有配置任何功能，去 WebUI 菜单插件配置页添加吧~", stream_id)
                return True, "无配置", True

            menu_items: List[Dict] = []
            total_commands = 0
            for name, cmds in sorted(manual.items()):
                menu_items.append({"name": name, "version": "", "commands": cmds, "desc": ""})
                total_commands += len(cmds)

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
                text += f"\n【{item['name']} v{item.get('version','')}】\n"
                for cmd, desc in item["commands"]:
                    text += f"  {cmd}"
                    if desc:
                        text += f"  ——  {desc}"
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
            name = item["name"]
            version = item.get("version", "")
            desc = item.get("desc", "")
            cmds_html = ""
            for cmd, cmd_desc in item["commands"]:
                desc_part = f'<span class="cmd-desc">{cmd_desc}</span>' if cmd_desc else ""
                cmds_html += f'<div class="cmd-line"><code class="cmd-text">{cmd}</code>{desc_part}</div>\n'

            desc_line = f'<div class="plugin-desc">{desc}</div>' if desc else ""

            cards += f"""
            <div class="plugin-card">
                <div class="plugin-header">
                    <span class="plugin-name">{name}</span>
                    <span class="plugin-version">v{version}</span>
                </div>{desc_line}
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
.plugin-desc {{
    font-size: 13px;
    color: var(--ink-light);
    margin-bottom: 8px;
    font-style: italic;
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
