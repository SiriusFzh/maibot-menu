# MaiBot 菜单插件

发送 `/菜单` 即可生成一张精美的菜单图片，列出当前麦麦所有可用功能和指令。

## 功能

- 自动发现所有已启用的第三方插件及其命令
- 以卡片式图片展示，风格统一美观
- 指令支持参数提示，一目了然
- 图片渲染失败时自动降级为纯文本

## 安装

在 MaiBot WebUI 插件市场搜索 `maibot.menu` 安装，或手动将本仓库克隆到 `plugins/` 目录。

## 使用

在任何群聊中发送：

```
/菜单
```

麦麦会生成一张图片，列出当前所有可用指令。

## 配置

```toml
[plugin]
enabled = true

[menu]
# 在菜单中隐藏这些插件（插件 ID）
exclude_plugins = ["builtin.plugin-management"]
```

## 许可

MIT
