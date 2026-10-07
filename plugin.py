"""
菜单插件 — 发送 /菜单 即可查看麦麦的所有功能和指令
"""

import asyncio
from functools import wraps
import json
import os
import tempfile
from html import escape
from pathlib import Path
import shutil
from typing import Any, Dict, List, Optional, Tuple

from maibot_sdk import Command, Field, MaiBotPlugin, PluginConfigBase


MAX_DATA_BYTES = 512 * 1024
MAX_GROUPS = 100
MAX_COMMANDS = 500


def _load_custom_commands(data_file: Path) -> Dict[str, List[Tuple[str, str]]]:
    """有损坏或过大的数据时拒绝修改，避免覆盖旧数据。"""
    if not data_file.exists():
        return {}
    with data_file.open("rb") as f:
        raw = f.read(MAX_DATA_BYTES + 1)
    if len(raw) > MAX_DATA_BYTES:
        raise ValueError("菜单数据超过 512 KiB，请先通过文件管理缩减数据")
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("菜单数据格式错误，请先检查 commands.json")
    result = {}
    for name, obj in data.items():
        if not isinstance(obj, dict) or not isinstance(obj.get("items"), list):
            raise ValueError("菜单数据格式错误，请先检查 commands.json")
        result[name] = []
        for item in obj["items"]:
            if not isinstance(item, dict):
                raise ValueError("菜单数据格式错误，请先检查 commands.json")
            cmd, desc = item.get("command", ""), item.get("desc", "")
            if not isinstance(cmd, str) or not isinstance(desc, str):
                raise ValueError("菜单数据格式错误，请先检查 commands.json")
            if cmd:
                result[name].append((cmd, desc))
    return result


def _save_custom_commands(data_file: Path, data: Dict[str, List[Tuple[str, str]]]) -> None:
    """校验容量后原子替换；写入失败不会截断原文件。"""
    if len(data) > MAX_GROUPS or sum(map(len, data.values())) > MAX_COMMANDS:
        raise ValueError("菜单最多包含 100 个分类、500 条指令")
    out = {}
    for name, cmds in data.items():
        if len(name) > 100 or any(len(c) > 100 or len(d) > 500 for c, d in cmds):
            raise ValueError("分类和指令最多 100 字，描述最多 500 字")
        out[name] = {"functionName": name, "items": [{"command": c, "desc": d} for c, d in cmds]}
    raw = json.dumps(out, ensure_ascii=False, indent=2).encode("utf-8")
    if len(raw) > MAX_DATA_BYTES:
        raise ValueError("菜单数据最多 512 KiB")
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(dir=data_file.parent, prefix=".commands-", suffix=".tmp", delete=False) as f:
            temp_path = Path(f.name)
            f.write(raw)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, data_file)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def _can_manage(admin_users: List[str], kwargs: Dict[str, Any]) -> bool:
    # 这些身份字段由 Host 构造，不能从聊天文本提取身份。
    if kwargs.get("is_local_operator") is True:
        return True
    platform = str(kwargs.get("platform", "") or "").strip().lower()
    user_id = str(kwargs.get("user_id", "") or "").strip()
    allowed = set()
    for entry in admin_users:
        prefix, separator, uid = entry.strip().partition(":")
        if separator and prefix.strip() and uid.strip():
            allowed.add(f"{prefix.strip().lower()}:{uid.strip()}")
    return bool(platform and user_id) and f"{platform}:{user_id}" in allowed


def _menu_write(handler):
    """管理命令鉴权并串行化完整的读、改、写事务。"""
    @wraps(handler)
    async def guarded(self, stream_id: str = "", group_id: str = "", **kwargs):
        if not _can_manage(self.config.menu.admin_users, kwargs):
            await self.ctx.send.text("没有菜单管理权限，请在 WebUI 配置 menu.admin_users", stream_id)
            return True, "无管理权限", True
        async with self._commands_lock:
            try:
                return await handler(self, stream_id=stream_id, group_id=group_id, **kwargs)
            except (OSError, ValueError, TypeError):
                self.ctx.logger.warning("菜单修改失败：数据格式、容量或文件写入检查未通过")
                await self.ctx.send.text("菜单修改失败：请检查数据格式及容量限制（100 分类、500 指令；名称/指令 100 字、描述 500 字；文件 512 KiB）", stream_id)
                return False, "菜单数据未更新", True
    return guarded


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

    admin_users: List[str] = Field(
        default_factory=list,
        description="允许管理共用菜单的用户，格式为 平台:用户ID（例如 qq:123456）；空列表仅允许本地操作员",
        json_schema_extra={"label": "菜单管理员"},
    )
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
        self._commands_lock = asyncio.Lock()
        data_dir = Path(self.ctx.paths.data_dir)
        data_dir.mkdir(parents=True, exist_ok=True)
        self._commands_path = data_dir / "commands.json"
        legacy_file = Path(__file__).parent / "commands.json"
        if not self._commands_path.exists() and legacy_file.is_file():
            shutil.copy2(legacy_file, self._commands_path)
            self.ctx.logger.info("已迁移旧版菜单数据到持久化目录")
        self.ctx.logger.info("菜单插件已加载")

    async def on_unload(self) -> None:
        self.ctx.logger.info("菜单插件已卸载")

    async def on_config_update(self, scope: str, config_data: dict, version: str) -> None:
        """配置热更新时不做特殊处理，配置已通过 self.config 实时生效"""
        pass

    # ==================== 菜单管理命令 ====================

    @Command("menu_add", description="添加一个功能分类", pattern=r"^/菜单添加\s+(?P<args>.+)$")
    @_menu_write
    async def cmd_menu_add(
        self, stream_id: str = "", group_id: str = "", **kwargs: Any
    ) -> Tuple[bool, str, bool]:
        args = ((kwargs.get("matched_groups") or {}).get("args") or "").strip()
        if not args:
            await self.ctx.send.text("用法: /菜单添加 功能名", stream_id)
            return True, "无参数", True
        data = _load_custom_commands(self._commands_path)
        if args in data:
            await self.ctx.send.text(f"功能【{args}】已存在，用 /菜单指令 添加指令吧", stream_id)
            return True, "已存在", True
        data[args] = []
        _save_custom_commands(self._commands_path, data)
        await self.ctx.send.text(f"已添加功能【{args}】，用 /菜单指令 给它添加指令吧", stream_id)
        return True, f"已添加 {args}", True

    @Command("menu_cmd", description="给功能添加一条指令",
             pattern=r"^/菜单指令\s+(?P<args>.+)$")
    @_menu_write
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
        data = _load_custom_commands(self._commands_path)
        if name not in data:
            await self.ctx.send.text(f"功能【{name}】不存在，先用 /菜单添加 创建", stream_id)
            return True, "功能不存在", True
        data[name].append((cmd, desc))
        _save_custom_commands(self._commands_path, data)
        info = f"{cmd} {'— ' + desc if desc else ''}"
        await self.ctx.send.text(f"已添加: 【{name}】{info}", stream_id)
        return True, f"添加成功 {cmd}", True

    @Command("menu_del", description="删除一个功能分类",
             pattern=r"^/菜单删除\s+(?P<args>.+)$")
    @_menu_write
    async def cmd_menu_del(
        self, stream_id: str = "", group_id: str = "", **kwargs: Any
    ) -> Tuple[bool, str, bool]:
        args = ((kwargs.get("matched_groups") or {}).get("args") or "").strip()
        if not args:
            await self.ctx.send.text("用法: /菜单删除 功能名", stream_id)
            return True, "无参数", True
        data = _load_custom_commands(self._commands_path)
        if args not in data:
            await self.ctx.send.text(f"功能【{args}】不存在", stream_id)
            return True, "不存在", True
        del data[args]
        _save_custom_commands(self._commands_path, data)
        await self.ctx.send.text(f"已删除功能【{args}】及其所有指令", stream_id)
        return True, f"已删除 {args}", True

    @Command("menu_delcmd", description="删除一条指令",
             pattern=r"^/菜单删指令\s+(?P<args>.+)$")
    @_menu_write
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
        data = _load_custom_commands(self._commands_path)
        if name not in data:
            await self.ctx.send.text(f"功能【{name}】不存在", stream_id)
            return True, "不存在", True
        before = len(data[name])
        data[name] = [(c, d) for c, d in data[name] if c != target]
        if len(data[name]) == before:
            await self.ctx.send.text(f"未找到指令【{target}】", stream_id)
            return True, "未找到", True
        _save_custom_commands(self._commands_path, data)
        await self.ctx.send.text(f"已从【{name}】中删除指令【{target}】", stream_id)
        return True, f"已删除 {target}", True

    # ==================== 菜单展示命令 ====================

    @Command("menu", description="显示麦麦所有功能和指令", pattern=r"^/菜单$")
    async def cmd_menu(
        self, stream_id: str = "", group_id: str = "", **kwargs: Any
    ) -> Tuple[bool, str, bool]:
        try:
            # 只读菜单配置，不做任何全局插件扫描
            manual = _load_custom_commands(self._commands_path)
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
            name = escape(str(item["name"]))
            version = escape(str(item.get("version", "")))
            desc = escape(str(item.get("desc", "")))
            cmds_html = ""
            for cmd, cmd_desc in item["commands"]:
                cmd = escape(str(cmd))
                cmd_desc = escape(str(cmd_desc))
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
<head><meta charset="UTF-8"><style>
:root {{
    --bg: #fdfbf7;
    --card-bg: #fff;
    --ink: #5d4037;
    --ink-light: #8d6e63;
    --accent: #ff7043;
    --tag-bg: #fff3e0;
    --border: #e0d8cc;
    --font-title: 'Microsoft YaHei', 'PingFang SC', sans-serif;
    --font-body: 'Microsoft YaHei', 'PingFang SC', sans-serif;
    --font-hand: 'KaiTi', 'Microsoft YaHei', cursive;
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

        # SDK 返回解包后的结果字典，只读取约定字段。
        if not isinstance(result, dict) or result.get("success") is False:
            return None
        image_base64 = result.get("image_base64")
        return image_base64 if isinstance(image_base64, str) and image_base64 else None


def create_plugin() -> MenuPlugin:
    return MenuPlugin()
