"""
系统信息插件

提供系统状态查询、配置信息查看和插件管理功能的 KiraAI 插件。
支持 /sysinfo 指令调用和工具调用两种方式。
支持合并转发消息输出。
"""

import os
import platform
import time
import re
import json
import traceback
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field

from core.plugin import BasePlugin, logger, register_tool as tool, on, Priority
from core.chat.message_utils import KiraMessageEvent, KiraMessageBatchEvent
from core.chat.message_elements import Text
from core.utils.path_utils import get_data_path


@dataclass
class NodeElement:
    """合并转发消息节点元素"""
    content: List[Any] = field(default_factory=list)
    user_id: Optional[str] = None
    nickname: Optional[str] = None
    id: Optional[str] = None

    def to_dict(self):
        data = {}
        if self.id:
            data["id"] = self.id
        if self.user_id:
            data["user_id"] = self.user_id
        if self.nickname:
            data["nickname"] = self.nickname
        if self.content:
            data["content"] = [self._element_to_dict(e) for e in self.content]
        return {"type": "node", "data": data}

    def _element_to_dict(self, element):
        if hasattr(element, 'to_dict'):
            return element.to_dict()
        elif isinstance(element, dict):
            return element
        elif isinstance(element, Text):
            return {"type": "text", "data": {"text": element.text}}
        return {"type": "text", "data": {"text": str(element)}}


@dataclass
class ForwardElement:
    """合并转发消息元素"""
    nodes: List[NodeElement] = field(default_factory=list)
    id: Optional[str] = None

    def to_dict(self):
        data = {}
        if self.id:
            data["id"] = self.id
        if self.nodes:
            data["content"] = [node.to_dict() for node in self.nodes]
        return {"type": "forward", "data": data}


class SystemInfoPlugin(BasePlugin):
    """系统信息插件"""

    def __init__(self, ctx, cfg: dict):
        super().__init__(ctx, cfg)
        self.enabled = bool(cfg.get("enabled", True))
        self.verbose_log = bool(cfg.get("verbose_log", True))
        self.show_full_config = bool(cfg.get("show_full_config", False))
        self.max_plugins_list = int(cfg.get("max_plugins_list", 50))
        self.include_env_vars = bool(cfg.get("include_env_vars", False))
        self.use_forward_message = bool(cfg.get("use_forward_message", True))
        self.start_time = time.time()
        self.command_prefix = cfg.get("command_prefix", "/")

    def _log(self, level: str, msg: str):
        """统一日志输出"""
        if level == "debug" and self.verbose_log:
            logger.debug(f"[SystemInfo] {msg}")
        elif level == "info":
            logger.info(f"[SystemInfo] {msg}")
        elif level == "error":
            logger.error(f"[SystemInfo] {msg}")
        if self.verbose_log:
            logger.debug(f"[SystemInfo] [TRACE] {msg}")

    def _log_detail(self, msg: str):
        """详细日志输出（仅在 verbose_log 开启时）"""
        if self.verbose_log:
            logger.debug(f"[SystemInfo] [DETAIL] {msg}")

    async def initialize(self):
        try:
            logger.info(f"[SystemInfo] 初始化完成 | 启用:{self.enabled} | 详细日志:{self.verbose_log} | 合并转发:{self.use_forward_message}")
            if self.verbose_log:
                logger.debug(f"[SystemInfo] 配置详情: 前缀={self.command_prefix}, 完整配置={self.show_full_config}, 最大插件数={self.max_plugins_list}, 环境变量={self.include_env_vars}")
        except Exception as e:
            logger.error(f"[SystemInfo] 初始化失败: {e}")
            if self.verbose_log:
                logger.debug(f"[SystemInfo] 初始化异常堆栈:\n{traceback.format_exc()}")
            self.enabled = False

    async def terminate(self):
        logger.info("[SystemInfo] 已卸载")

    def _get_message_text(self, event: KiraMessageEvent) -> str:
        self._log_detail(f"开始提取消息文本, event类型: {type(event).__name__}")
        try:
            if hasattr(event.message, 'chain') and event.message.chain:
                self._log_detail(f"消息chain存在, 长度: {len(event.message.chain)}")
                parts = []
                for i, elem in enumerate(event.message.chain):
                    self._log_detail(f"chain[{i}] 类型: {type(elem).__name__}")
                    if isinstance(elem, Text):
                        parts.append(elem.text)
                        self._log_detail(f"chain[{i}] Text内容: {elem.text[:50]}...")
                    elif hasattr(elem, 'text'):
                        parts.append(elem.text)
                        self._log_detail(f"chain[{i}] text属性: {elem.text[:50] if elem.text else 'None'}...")
                if parts:
                    result = "".join(parts)
                    self._log_detail(f"从chain提取文本成功, 长度: {len(result)}")
                    return result
        except Exception as e:
            self._log("error", f"从chain提取文本失败: {e}")
            if self.verbose_log:
                logger.debug(f"[SystemInfo] 异常堆栈:\n{traceback.format_exc()}")
        
        result = event.message.message_str or ""
        self._log_detail(f"从message_str获取文本, 长度: {len(result)}")
        return result

    def _get_system_info(self) -> Dict[str, Any]:
        self._log_detail("开始获取系统信息")

        # 获取内存信息
        memory_info = {}
        storage_info = {}
        process_memory = None
        cpu_info = {}
        try:
            import psutil
            mem = psutil.virtual_memory()
            memory_info = {
                "total_gb": round(mem.total / (1024**3), 2),
                "available_gb": round(mem.available / (1024**3), 2),
                "percent": mem.percent
            }

            # 获取磁盘信息
            disk = psutil.disk_usage(os.getcwd())
            storage_info = {
                "total_gb": round(disk.total / (1024**3), 2),
                "free_gb": round(disk.free / (1024**3), 2),
                "percent": disk.percent
            }

            # 获取当前项目进程内存占用
            try:
                process = psutil.Process(os.getpid())
                mem_info = process.memory_info()
                process_memory = {
                    "rss_mb": round(mem_info.rss / (1024**2), 2),
                    "vms_mb": round(mem_info.vms / (1024**2), 2)
                }
                self._log_detail(f"项目内存占用: RSS={process_memory['rss_mb']}MB, VMS={process_memory['vms_mb']}MB")
            except Exception as e:
                self._log_detail(f"获取项目内存占用失败: {e}")

            # 获取CPU详细信息
            try:
                cpu_info = {
                    "logical_count": psutil.cpu_count(logical=True),
                    "physical_count": psutil.cpu_count(logical=False),
                    "percent": psutil.cpu_percent(interval=0.1)
                }
                # 获取CPU频率信息
                try:
                    freq = psutil.cpu_freq()
                    if freq:
                        cpu_info["current_mhz"] = round(freq.current, 0)
                        cpu_info["max_mhz"] = round(freq.max, 0) if freq.max else None
                except Exception:
                    pass
                self._log_detail(f"CPU信息: 逻辑核心={cpu_info.get('logical_count')}, 物理核心={cpu_info.get('physical_count')}")
            except Exception as e:
                self._log_detail(f"获取CPU信息失败: {e}")

        except ImportError:
            self._log_detail("psutil 未安装，跳过内存和存储信息")
        except Exception as e:
            self._log_detail(f"获取内存/存储信息失败: {e}")

        info = {
            "platform": {
                "system": platform.system(),
                "release": platform.release(),
                "version": platform.version(),
                "machine": platform.machine(),
                "processor": platform.processor(),
                "python": {
                    "version": platform.python_version(),
                    "implementation": platform.python_implementation()
                }
            },
            "runtime": {
                "uptime": time.time() - self.start_time,
                "current_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "pid": os.getpid(),
                "cwd": os.getcwd()
            },
            "cpu_count": os.cpu_count(),
            "cpu_info": cpu_info,
            "memory": memory_info,
            "storage": storage_info,
            "process_memory": process_memory
        }
        self._log_detail(f"系统信息获取完成: system={info['platform']['system']}, python={info['platform']['python']['version']}")
        return info

    def _get_plugins_info(self) -> List[Dict[str, str]]:
        self._log_detail("开始获取插件信息")
        plugins = []
        plugins_config = {}
        
        try:
            config_dir = get_data_path() / "config"
            plugins_config_file = config_dir / "plugins.json"
            
            if plugins_config_file.exists():
                with open(plugins_config_file, 'r', encoding='utf-8') as f:
                    plugins_config = json.load(f)
                self._log_detail(f"从plugins.json读取到 {len(plugins_config)} 个插件配置")
            
            builtin_plugins_dir = Path(__file__).parent.parent.parent / "core" / "plugin" / "builtin_plugins"
            self._log_detail(f"内置插件目录: {builtin_plugins_dir}")
            
            if builtin_plugins_dir.exists():
                for plugin_dir in builtin_plugins_dir.iterdir():
                    if plugin_dir.is_dir() and (plugin_dir / "main.py").exists():
                        plugin_id = plugin_dir.name
                        is_enabled = plugins_config.get(plugin_id, True)
                        plugins.append({
                            "plugin_id": plugin_id,
                            "status": "enabled" if is_enabled else "disabled",
                            "type": "builtin"
                        })
                        self._log_detail(f"内置插件: {plugin_id} -> {'enabled' if is_enabled else 'disabled'}")
            
            user_plugins_dir = get_data_path() / "plugins"
            self._log_detail(f"用户插件目录: {user_plugins_dir}")
            
            if user_plugins_dir.exists():
                for plugin_dir in user_plugins_dir.iterdir():
                    if plugin_dir.is_dir() and (plugin_dir / "main.py").exists():
                        plugin_id = plugin_dir.name
                        if plugin_id in plugins_config:
                            is_enabled = plugins_config.get(plugin_id, False)
                            status = "enabled" if is_enabled else "disabled"
                        else:
                            status = "unknown"
                        plugins.append({
                            "plugin_id": plugin_id,
                            "status": status,
                            "type": "user"
                        })
                        self._log_detail(f"用户插件: {plugin_id} -> {status}")
            
            self._log_detail(f"插件总数: {len(plugins)}")
            if len(plugins) > self.max_plugins_list:
                plugins = plugins[:self.max_plugins_list]
                self._log_detail(f"插件列表已截断至 {self.max_plugins_list}")
                
        except Exception as e:
            self._log("error", f"获取插件信息失败: {e}")
            if self.verbose_log:
                logger.debug(f"[SystemInfo] 异常堆栈:\n{traceback.format_exc()}")
            
        return plugins

    def _get_config_info(self) -> Dict[str, Any]:
        self._log_detail("开始获取配置信息")
        config_info = {}
        if hasattr(self.ctx, 'config') and self.ctx.config:
            self._log_detail(f"ctx.config存在, 类型: {type(self.ctx.config).__name__}")
            try:
                if 'bot_config' in self.ctx.config:
                    config_info['bot_config'] = {
                        'bot': {'name': self.ctx.config.get('bot_config', {}).get('bot', {}).get('name', 'N/A')}
                    }
                    self._log_detail(f"bot_config.name: {config_info['bot_config']['bot']['name']}")
                if 'models' in self.ctx.config:
                    config_info['models'] = {'count': len(self.ctx.config.get('models', {}))}
                    self._log_detail(f"models count: {config_info['models']['count']}")
                if 'providers' in self.ctx.config:
                    config_info['providers'] = {'count': len(self.ctx.config.get('providers', {}))}
                    self._log_detail(f"providers count: {config_info['providers']['count']}")
            except Exception as e:
                self._log("error", f"获取配置信息失败: {e}")
                if self.verbose_log:
                    logger.debug(f"[SystemInfo] 异常堆栈:\n{traceback.format_exc()}")
        else:
            self._log_detail("ctx.config不存在或为空")
        return config_info

    def _build_system_info_text(self, detail_level: str = "basic") -> str:
        self._log_detail(f"开始构建系统信息文本, detail_level={detail_level}")
        try:
            info = self._get_system_info()
            plugins = self._get_plugins_info()
            config = self._get_config_info()

            parts = []
            parts.append("【系统状态信息】\n")

            parts.append("【基础信息】")
            parts.append(f"系统: {info['platform']['system']} {info['platform']['release']}")
            parts.append(f"Python: {info['platform']['python']['version']}")
            uptime_h = int(info['runtime']['uptime'] // 3600)
            uptime_m = int((info['runtime']['uptime'] % 3600) // 60)
            parts.append(f"运行时间: {uptime_h}h {uptime_m}m")

            # CPU信息
            if info['cpu_info']:
                cpu = info['cpu_info']
                cpu_text = f"CPU: {cpu.get('logical_count', '?')}线程 / {cpu.get('physical_count', '?')}核心"
                if cpu.get('current_mhz'):
                    cpu_text += f" @ {cpu['current_mhz']:.0f}MHz"
                parts.append(cpu_text)
            else:
                parts.append(f"CPU核心: {info['cpu_count']}")
            
            # 内存信息
            if info['memory']:
                mem = info['memory']
                used_mem_gb = round(mem['total_gb'] - mem['available_gb'], 1)
                parts.append(f"内存: {used_mem_gb}GB / {mem['total_gb']}GB ({mem['percent']}% 已用)")

            # 存储信息
            if info['storage']:
                storage = info['storage']
                used_storage_gb = round(storage['total_gb'] - storage['free_gb'], 1)
                parts.append(f"存储: {used_storage_gb}GB / {storage['total_gb']}GB ({storage['percent']}% 已用)")

            # 项目内存占用
            if info['process_memory']:
                proc_mem = info['process_memory']
                parts.append(f"项目占用: {proc_mem['rss_mb']}MB (RSS) / {proc_mem['vms_mb']}MB (VMS)")

            parts.append("")

            parts.append("【插件信息】")
            enabled_count = sum(1 for p in plugins if p['status'] == 'enabled')
            disabled_count = sum(1 for p in plugins if p['status'] == 'disabled')
            unknown_count = sum(1 for p in plugins if p['status'] == 'unknown')
            if unknown_count > 0:
                parts.append(f"已加载: {len(plugins)} (启用:{enabled_count} / 禁用:{disabled_count} / 未配置:{unknown_count})")
            else:
                parts.append(f"已加载: {len(plugins)} (启用:{enabled_count} / 禁用:{disabled_count})")
            parts.append("")

            parts.append("【配置信息】")
            if 'models' in config:
                parts.append(f"模型数: {config['models']['count']}")
            if 'providers' in config:
                parts.append(f"提供商数: {config['providers']['count']}")

            if detail_level == "detailed":
                parts.append("")
                parts.append("【详细信息】")
                parts.append(f"进程ID: {info['runtime']['pid']}")
                parts.append(f"工作目录: {info['runtime']['cwd']}")
                parts.append(f"处理器: {info['platform']['processor']}")
                parts.append(f"机器架构: {info['platform']['machine']}")
                if info['cpu_info']:
                    cpu = info['cpu_info']
                    parts.append(f"CPU使用率: {cpu.get('percent', '?')}%")
                    if cpu.get('max_mhz'):
                        parts.append(f"CPU最大频率: {cpu['max_mhz']:.0f}MHz")

            parts.append(f"\n更新时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            result = "\n".join(parts)
            self._log_detail(f"系统信息文本构建完成, 长度: {len(result)}")
            return result

        except Exception as e:
            self._log("error", f"构建系统信息失败: {e}")
            if self.verbose_log:
                logger.debug(f"[SystemInfo] 异常堆栈:\n{traceback.format_exc()}")
            return f"获取系统信息失败: {e}"

    def _build_system_info_forward(self, detail_level: str = "basic") -> Optional[ForwardElement]:
        """构建系统信息的合并转发消息"""
        self._log_detail(f"开始构建合并转发消息, detail_level={detail_level}")
        try:
            info = self._get_system_info()
            plugins = self._get_plugins_info()
            config = self._get_config_info()

            nodes = []
            bot_name = "KiraAI"
            if config.get('bot_config', {}).get('bot', {}).get('name'):
                bot_name = config['bot_config']['bot']['name']

            # 节点1: 标题和基础信息
            node1_parts = ["【系统状态信息】\n", "【基础信息】"]
            node1_parts.append(f"系统: {info['platform']['system']} {info['platform']['release']}")
            node1_parts.append(f"Python: {info['platform']['python']['version']}")
            uptime_h = int(info['runtime']['uptime'] // 3600)
            uptime_m = int((info['runtime']['uptime'] % 3600) // 60)
            node1_parts.append(f"运行时间: {uptime_h}h {uptime_m}m")

            # CPU信息
            if info['cpu_info']:
                cpu = info['cpu_info']
                cpu_text = f"CPU: {cpu.get('logical_count', '?')}线程 / {cpu.get('physical_count', '?')}核心"
                if cpu.get('current_mhz'):
                    cpu_text += f" @ {cpu['current_mhz']:.0f}MHz"
                node1_parts.append(cpu_text)
            else:
                node1_parts.append(f"CPU核心: {info['cpu_count']}")

            nodes.append(NodeElement(
                content=[Text("\n".join(node1_parts))],
                user_id="system_info",
                nickname=f"{bot_name} 系统信息"
            ))

            # 节点2: 内存和存储信息
            node2_parts = ["【资源信息】"]
            if info['memory']:
                mem = info['memory']
                used_mem_gb = round(mem['total_gb'] - mem['available_gb'], 1)
                node2_parts.append(f"内存: {used_mem_gb}GB / {mem['total_gb']}GB ({mem['percent']}% 已用)")
            if info['storage']:
                storage = info['storage']
                used_storage_gb = round(storage['total_gb'] - storage['free_gb'], 1)
                node2_parts.append(f"存储: {used_storage_gb}GB / {storage['total_gb']}GB ({storage['percent']}% 已用)")
            if info['process_memory']:
                proc_mem = info['process_memory']
                node2_parts.append(f"项目占用: {proc_mem['rss_mb']}MB (RSS) / {proc_mem['vms_mb']}MB (VMS)")

            if len(node2_parts) > 1:
                nodes.append(NodeElement(
                    content=[Text("\n".join(node2_parts))],
                    user_id="system_info",
                    nickname=f"{bot_name} 资源监控"
                ))

            # 节点3: 插件信息
            enabled_count = sum(1 for p in plugins if p['status'] == 'enabled')
            disabled_count = sum(1 for p in plugins if p['status'] == 'disabled')
            unknown_count = sum(1 for p in plugins if p['status'] == 'unknown')
            node3_parts = [f"【插件信息】", f"总数: {len(plugins)}"]
            if unknown_count > 0:
                node3_parts.append(f"启用: {enabled_count} | 禁用: {disabled_count} | 未配置: {unknown_count}")
            else:
                node3_parts.append(f"启用: {enabled_count} | 禁用: {disabled_count}")
            nodes.append(NodeElement(
                content=[Text("\n".join(node3_parts))],
                user_id="system_info",
                nickname=f"{bot_name} 插件管理"
            ))

            # 节点4: 配置信息
            node4_parts = ["【配置信息】"]
            if 'models' in config:
                node4_parts.append(f"模型数: {config['models']['count']}")
            if 'providers' in config:
                node4_parts.append(f"提供商数: {config['providers']['count']}")

            if detail_level == "detailed":
                node4_parts.append("")
                node4_parts.append("【详细信息】")
                node4_parts.append(f"进程ID: {info['runtime']['pid']}")
                node4_parts.append(f"工作目录: {info['runtime']['cwd']}")
                node4_parts.append(f"处理器: {info['platform']['processor']}")
                node4_parts.append(f"机器架构: {info['platform']['machine']}")
                if info['cpu_info']:
                    cpu = info['cpu_info']
                    node4_parts.append(f"CPU使用率: {cpu.get('percent', '?')}%")
                    if cpu.get('max_mhz'):
                        node4_parts.append(f"CPU最大频率: {cpu['max_mhz']:.0f}MHz")

            node4_parts.append(f"\n更新时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            nodes.append(NodeElement(
                content=[Text("\n".join(node4_parts))],
                user_id="system_info",
                nickname=f"{bot_name} 配置详情"
            ))

            self._log_detail(f"合并转发消息构建完成, 共 {len(nodes)} 个节点")
            return ForwardElement(nodes=nodes)

        except Exception as e:
            self._log("error", f"构建合并转发消息失败: {e}")
            if self.verbose_log:
                logger.debug(f"[SystemInfo] 异常堆栈:\n{traceback.format_exc()}")
            return None

    @on.im_message(priority=Priority.HIGH)
    async def handle_command(self, event: KiraMessageEvent):
        """处理 /sysinfo 指令"""
        if not self.enabled:
            return

        try:
            self._log_detail(f"收到消息事件, 类型: {type(event).__name__}")
            message_text = self._get_message_text(event).strip()
            self._log_detail(f"消息文本: '{message_text}'")

            pattern = rf"^{re.escape(self.command_prefix)}sysinfo(\s+(basic|detailed))?$"
            match = re.match(pattern, message_text, re.IGNORECASE)

            self._log_detail(f"正则匹配结果: {match}")
            
            if match:
                detail_level = match.group(2) if match.group(2) else "basic"
                self._log("info", f"收到指令: {message_text}, 详细程度: {detail_level}")

                result = self._build_system_info_text(detail_level)
                self._log_detail(f"生成回复长度: {len(result)}")

                # 发送回复消息
                try:
                    # 获取当前会话ID
                    sid = getattr(event, 'sid', None)
                    self._log_detail(f"event.sid: {sid}")
                    
                    if not sid and hasattr(event, 'message') and event.message:
                        # 尝试从 message 构造 sid
                        if hasattr(event, 'adapter') and event.adapter:
                            adapter_name = getattr(event.adapter, 'name', 'unknown')
                            if event.message.group:
                                sid = f"{adapter_name}:gm:{event.message.group.group_id}"
                            elif event.message.sender:
                                sid = f"{adapter_name}:dm:{event.message.sender.user_id}"
                            self._log_detail(f"从message构造sid: {sid}")
                    
                    if sid:
                        # 尝试使用合并转发消息发送
                        if self.use_forward_message:
                            try:
                                forward_element = self._build_system_info_forward(detail_level)
                                if forward_element:
                                    self._log_detail("尝试发送合并转发消息")
                                    sent = await self._send_forward_message(sid, forward_element)
                                    if sent:
                                        self._log_detail(f"合并转发消息已发送到会话: {sid}")
                                    else:
                                        self._log_detail("合并转发发送失败，回退到普通消息")
                                        await self._send_text_message(sid, result)
                                else:
                                    await self._send_text_message(sid, result)
                            except Exception as forward_err:
                                self._log_detail(f"合并转发发送异常: {forward_err}, 回退到普通消息")
                                await self._send_text_message(sid, result)
                        else:
                            await self._send_text_message(sid, result)
                    else:
                        self._log_detail("无法确定会话ID，无法发送回复")
                        
                except Exception as send_err:
                    self._log("error", f"发送回复失败: {send_err}")
                    if self.verbose_log:
                        logger.debug(f"[SystemInfo] 发送异常堆栈:\n{traceback.format_exc()}")

                if hasattr(event, 'stop'):
                    event.stop()
                    self._log_detail("已调用 event.stop()")
            else:
                self._log_detail("消息不匹配 sysinfo 指令")

        except Exception as e:
            self._log("error", f"处理指令失败: {e}")
            if self.verbose_log:
                logger.debug(f"[SystemInfo] 异常堆栈:\n{traceback.format_exc()}")

    async def _send_text_message(self, sid: str, text: str):
        """发送普通文本消息"""
        from core.chat import MessageChain
        from core.chat.message_elements import Text
        reply_chain = MessageChain([Text(text)])

        if hasattr(self.ctx, 'message_processor') and self.ctx.message_processor:
            await self.ctx.message_processor.send_message_chain(session=sid, chain=reply_chain)
            self._log_detail(f"文本消息已发送到会话: {sid}")
        else:
            self._log_detail("message_processor 不可用，尝试使用 publish_notice")
            await self.ctx.publish_notice(session=sid, chain=reply_chain)
            self._log_detail(f"通过 publish_notice 发送到: {sid}")

    async def _send_forward_message(self, sid: str, forward_element: ForwardElement) -> bool:
        """发送合并转发消息

        尝试通过适配器直接发送合并转发消息。
        如果适配器不支持，返回 False 让调用方回退到普通消息。
        """
        try:
            # 解析会话ID获取适配器名称和群号/用户ID
            parts = sid.split(":")
            if len(parts) < 3:
                self._log_detail(f"无法解析会话ID: {sid}")
                return False

            adapter_name = parts[0]
            session_type = parts[1]  # 'gm' 或 'dm'
            target_id = parts[2]

            # 获取适配器
            if not hasattr(self.ctx, 'adapter_mgr') or not self.ctx.adapter_mgr:
                self._log_detail("adapter_mgr 不可用")
                return False

            adapter = None
            try:
                adapter = await self.ctx.adapter_mgr.get_adapter(adapter_name)
            except Exception as e:
                self._log_detail(f"获取适配器失败: {e}")
                return False

            if not adapter:
                self._log_detail(f"适配器 {adapter_name} 不存在")
                return False

            # 检查适配器是否有发送合并转发消息的方法
            if not hasattr(adapter, 'send_forward_message'):
                self._log_detail(f"适配器 {adapter_name} 不支持 send_forward_message")
                return False

            # 构建合并转发消息数据
            forward_data = forward_element.to_dict()
            self._log_detail(f"发送合并转发消息数据: {forward_data}")

            # 调用适配器发送合并转发消息
            if session_type == 'gm':
                await adapter.send_forward_message(
                    group_id=target_id,
                    messages=forward_data.get('data', {}).get('content', [])
                )
            else:
                await adapter.send_forward_message(
                    user_id=target_id,
                    messages=forward_data.get('data', {}).get('content', [])
                )

            self._log_detail("合并转发消息发送成功")
            return True

        except Exception as e:
            self._log_detail(f"发送合并转发消息失败: {e}")
            if self.verbose_log:
                logger.debug(f"[SystemInfo] 发送合并转发异常堆栈:\n{traceback.format_exc()}")
            return False

    @tool(
        name="system_info",
        description="获取系统状态信息，包括硬件、软件、运行时间、插件列表等。用户询问系统状态、运行时间、系统信息时调用。",
        params={
            "type": "object",
            "properties": {
                "detail_level": {
                    "type": "string",
                    "enum": ["basic", "detailed"],
                    "description": "信息详细程度"
                }
            },
            "required": ["detail_level"]
        }
    )
    async def system_info(self, event: KiraMessageBatchEvent, detail_level: str = "basic") -> str:
        self._log("info", f"工具调用: system_info, detail_level={detail_level}")
        return self._build_system_info_text(detail_level)

    @tool(
        name="plugin_list",
        description="获取当前加载的所有插件列表及其状态。用户询问插件列表、已加载插件时调用。",
        params={
            "type": "object",
            "properties": {
                "status_filter": {
                    "type": "string",
                    "enum": ["all", "enabled", "disabled"],
                    "description": "状态过滤"
                }
            },
            "required": ["status_filter"]
        }
    )
    async def plugin_list(self, event: KiraMessageBatchEvent, status_filter: str = "all") -> str:
        self._log("info", f"工具调用: plugin_list, status_filter={status_filter}")
        try:
            plugins = self._get_plugins_info()

            if status_filter == "enabled":
                plugins = [p for p in plugins if p['status'] == "enabled"]
                self._log_detail(f"过滤后enabled插件数: {len(plugins)}")
            elif status_filter == "disabled":
                plugins = [p for p in plugins if p['status'] == "disabled"]
                self._log_detail(f"过滤后disabled插件数: {len(plugins)}")

            parts = [f"# 插件列表 ({len(plugins)}个)\n"]
            for plugin in plugins:
                parts.append(f"- **{plugin['plugin_id']}** ({plugin['status']})")
            parts.append(f"\n*更新时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

            return "\n".join(parts)
        except Exception as e:
            self._log("error", f"获取插件列表失败: {e}")
            if self.verbose_log:
                logger.debug(f"[SystemInfo] 异常堆栈:\n{traceback.format_exc()}")
            return f"获取插件列表失败: {e}"

    @tool(
        name="config_info",
        description="查看系统配置信息。用户询问配置、机器人配置时调用。",
        params={
            "type": "object",
            "properties": {
                "section": {
                    "type": "string",
                    "enum": ["all", "bot", "models", "providers"],
                    "description": "配置部分"
                }
            },
            "required": ["section"]
        }
    )
    async def config_info(self, event: KiraMessageBatchEvent, section: str = "all") -> str:
        self._log("info", f"工具调用: config_info, section={section}")
        try:
            config = self._get_config_info()
            parts = ["# 配置信息\n"]

            if not config:
                return "无配置信息"

            if section in ["all", "bot"] and 'bot_config' in config:
                parts.append(f"- 机器人名称: {config['bot_config']['bot']['name']}")
            if section in ["all", "models"] and 'models' in config:
                parts.append(f"- 模型数量: {config['models']['count']}")
            if section in ["all", "providers"] and 'providers' in config:
                parts.append(f"- 提供商数量: {config['providers']['count']}")

            return "\n".join(parts)
        except Exception as e:
            self._log("error", f"获取配置信息失败: {e}")
            if self.verbose_log:
                logger.debug(f"[SystemInfo] 异常堆栈:\n{traceback.format_exc()}")
            return f"获取配置信息失败: {e}"


__all__ = ['SystemInfoPlugin']