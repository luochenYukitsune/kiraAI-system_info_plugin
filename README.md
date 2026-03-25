# System Info Plugin - 系统信息插件

用于查询 KiraAI 系统状态、配置信息和插件管理的插件。

## 功能特性

- **系统状态查询**：获取硬件、软件、运行时间等系统信息
- **插件信息管理**：查看已加载的插件列表及其状态
- **配置信息查看**：查看系统配置摘要
- **双模式调用**：支持 `/sysinfo` 指令和 LLM 工具调用两种方式
- **合并转发消息**：支持以合并转发（卡片）形式输出系统信息，更美观且不占刷屏

## 调用方式

### 方式一：指令调用

发送以下指令直接获取系统信息：

| 指令 | 说明 |
|------|------|
| `/sysinfo` | 获取基础系统信息 |
| `/sysinfo basic` | 获取基础系统信息 |
| `/sysinfo detailed` | 获取详细系统信息 |

### 方式二：自然语言调用

直接向机器人询问，LLM 会自动调用工具：

- "查看系统状态"
- "系统运行多久了？"
- "有哪些插件？"
- "查看配置信息"

## 工具列表

### 1. system_info - 系统状态查询

**参数**：
- `detail_level`：信息详细程度（`basic` 或 `detailed`）

**返回**：系统状态信息

### 2. plugin_list - 插件列表查询

**参数**：
- `status_filter`：状态过滤（`all`、`enabled` 或 `disabled`）

**返回**：符合条件的插件列表

### 3. config_info - 配置信息查询

**参数**：
- `section`：配置部分（`all`、`bot`、`models` 或 `providers`）

**返回**：指定部分的配置信息

## 配置选项

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `enabled` | boolean | `true` | 是否启用插件 |
| `command_prefix` | string | `/` | 指令前缀符号 |
| `show_full_config` | boolean | `false` | 是否显示完整配置 |
| `max_plugins_list` | integer | `50` | 插件列表最大显示数 |
| `use_forward_message` | boolean | `true` | 是否使用合并转发消息（卡片形式）输出 |
| `verbose_log` | boolean | `true` | 是否输出详细调试日志 |

## 安装方法

1. 将 `system_info_plugin` 文件夹放入 `data/plugins/` 目录
2. 在 KiraAI WebUI 中启用插件
3. 插件将自动加载默认配置

## 文件结构

```
system_info_plugin/
├── __init__.py          # 包入口
├── main.py              # 插件主逻辑
├── manifest.json        # 插件元数据
├── schema.json          # 配置定义
└── README.md            # 本文档
```

## 使用示例

### 指令方式

```
用户: /sysinfo
机器人: # 系统状态信息

## 基础信息
- 系统: Windows 10
- Python: 3.10.11
- 运行时间: 2h 30m
- CPU核心: 8

## 插件信息
- 已加载: 12
  - system_info_plugin (enabled)
  - ban_notice_blocker (enabled)
  ...

## 配置信息
- 机器人: KiraAI
- 模型数: 3
- 提供者数: 2
```

### 自然语言方式

```
用户: 系统运行多久了？
机器人: [调用 system_info 工具]
系统已运行 2小时30分钟...
```

## 注意事项

- 指令调用优先级高于工具调用
- `show_full_config` 设置为 `true` 时可能显示敏感信息
- 所有操作都会记录日志，便于排查问题
- **合并转发消息**：需要适配器支持 `send_forward_message` 方法，如果不支持会自动回退到普通文本消息
- 合并转发消息以卡片形式展示，包含多个节点（系统信息、资源监控、插件管理、配置详情），更美观且不会刷屏