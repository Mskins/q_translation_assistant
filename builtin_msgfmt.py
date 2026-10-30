# -*- coding: utf-8 -*-
"""
内置msgfmt工具模块
提供内置的msgfmt和msgunfmt工具，避免用户需要单独安装gettext
"""

import os
import sys
import platform
import subprocess
import tempfile
import zipfile
import shutil
from pathlib import Path

# 尝试导入内置工具数据
try:
    from . import builtin_msgfmt_data
    BUILTIN_TOOLS = builtin_msgfmt_data.BUILTIN_TOOLS
except ImportError:
    # 如果没有内置数据，使用空数据
    BUILTIN_TOOLS = {
        'windows': {
            'msgfmt': b'',
            'msgunfmt': b'',
            'msgmerge': b'',
        },
        'darwin': {
            'msgfmt': b'',
            'msgunfmt': b'',
            'msgmerge': b'',
        },
        'linux': {
            'msgfmt': b'',
            'msgunfmt': b'',
            'msgmerge': b'',
        }
    }

def get_platform_key():
    """获取当前平台的键名"""
    system = platform.system().lower()
    if system == 'windows':
        return 'windows'
    elif system == 'darwin':
        return 'darwin'
    else:
        return 'linux'

def get_addon_path():
    """获取插件路径"""
    # 获取当前文件的目录
    current_dir = os.path.dirname(os.path.abspath(__file__))
    return current_dir

def get_tools_dir():
    """获取内置工具目录"""
    addon_path = get_addon_path()
    tools_dir = os.path.join(addon_path, 'tools')
    return tools_dir

def extract_builtin_tools():
    """提取内置工具到临时目录"""
    platform_key = get_platform_key()
    tools_dir = get_tools_dir()
    
    # 确保工具目录存在
    os.makedirs(tools_dir, exist_ok=True)
    
    # 检查工具是否已经存在
    msgfmt_path = os.path.join(tools_dir, 'msgfmt')
    msgunfmt_path = os.path.join(tools_dir, 'msgunfmt')
    msgmerge_path = os.path.join(tools_dir, 'msgmerge')
    
    if platform_key == 'windows':
        msgfmt_path += '.exe'
        msgunfmt_path += '.exe'
        msgmerge_path += '.exe'
    
    # 如果工具已经存在且可执行，直接返回
    if os.path.exists(msgfmt_path) and os.path.exists(msgunfmt_path) and os.path.exists(msgmerge_path):
        try:
            # 测试工具是否可执行
            subprocess.run([msgfmt_path, '--version'], 
                         capture_output=True, timeout=5)
            return True
        except:
            pass
    
    # 从内置数据中提取工具
    try:
        tools_data = BUILTIN_TOOLS.get(platform_key, {})
        
        if not tools_data.get('msgfmt') or not tools_data.get('msgunfmt'):
            print(f"警告: 当前平台 {platform_key} 的内置工具数据为空")
            return False
        
        # 写入msgfmt
        with open(msgfmt_path, 'wb') as f:
            f.write(tools_data['msgfmt'])
        
        # 写入msgunfmt
        with open(msgunfmt_path, 'wb') as f:
            f.write(tools_data['msgunfmt'])
        
        # 写入msgmerge
        with open(msgmerge_path, 'wb') as f:
            f.write(tools_data['msgmerge'])
        
        # 设置执行权限（在Unix系统上）
        if platform_key != 'windows':
            os.chmod(msgfmt_path, 0o755)
            os.chmod(msgunfmt_path, 0o755)
            os.chmod(msgmerge_path, 0o755)
        
        print(f"成功提取内置msgfmt工具到: {tools_dir}")
        return True
        
    except Exception as e:
        print(f"提取内置工具失败: {e}")
        return False

def get_builtin_msgfmt_path():
    """获取内置msgfmt工具的路径"""
    platform_key = get_platform_key()
    tools_dir = get_tools_dir()
    
    if platform_key == 'windows':
        return os.path.join(tools_dir, 'msgfmt.exe')
    else:
        return os.path.join(tools_dir, 'msgfmt')

def get_builtin_msgunfmt_path():
    """获取内置msgunfmt工具的路径"""
    platform_key = get_platform_key()
    tools_dir = get_tools_dir()
    
    if platform_key == 'windows':
        return os.path.join(tools_dir, 'msgunfmt.exe')
    else:
        return os.path.join(tools_dir, 'msgunfmt')

def get_builtin_msgmerge_path():
    """获取内置msgmerge工具的路径"""
    platform_key = get_platform_key()
    tools_dir = get_tools_dir()
    
    if platform_key == 'windows':
        return os.path.join(tools_dir, 'msgmerge.exe')
    else:
        return os.path.join(tools_dir, 'msgmerge')

def is_builtin_msgfmt_available():
    """检查内置msgfmt工具是否可用"""
    try:
        msgfmt_path = get_builtin_msgfmt_path()
        msgunfmt_path = get_builtin_msgunfmt_path()
        msgmerge_path = get_builtin_msgmerge_path()
        
        if not os.path.exists(msgfmt_path) or not os.path.exists(msgunfmt_path) or not os.path.exists(msgmerge_path):
            # 尝试提取内置工具
            if not extract_builtin_tools():
                return False
        
        # 测试工具是否可执行
        subprocess.run([msgfmt_path, '--version'], 
                      capture_output=True, timeout=5)
        subprocess.run([msgunfmt_path, '--version'], 
                      capture_output=True, timeout=5)
        subprocess.run([msgmerge_path, '--version'], 
                      capture_output=True, timeout=5)
        
        return True
    except Exception as e:
        # print(f"内置msgfmt工具不可用: {e}")  # 移除调试信息
        return False

# 缓存工具查找结果
_tools_cache = None
_tools_cache_time = 0
_info_cache = None
_info_cache_time = 0

def find_msgfmt_tools():
    """查找msgfmt工具，优先使用内置工具"""
    global _tools_cache, _tools_cache_time
    
    # 检查缓存是否有效（5秒内）
    import time
    current_time = time.time()
    if _tools_cache is not None and (current_time - _tools_cache_time) < 5:
        return _tools_cache
    
    tools = {}
    
    # 首先尝试内置工具
    if is_builtin_msgfmt_available():
        tools['msgfmt'] = get_builtin_msgfmt_path()
        tools['msgunfmt'] = get_builtin_msgunfmt_path()
        tools['msgmerge'] = get_builtin_msgmerge_path()
        # print("使用内置msgfmt工具")  # 移除调试信息
        _tools_cache = tools
        _tools_cache_time = current_time
        return tools
    
    # 如果内置工具不可用，尝试系统工具
    import shutil
    
    # 常见的msgfmt路径
    possible_paths = [
        'msgfmt',
        'msgunfmt',
        '/usr/bin/msgfmt',
        '/usr/bin/msgunfmt',
        '/usr/local/bin/msgfmt',
        '/usr/local/bin/msgunfmt',
        'C:/gettext/bin/msgfmt.exe',
        'C:/gettext/bin/msgunfmt.exe',
    ]
    
    # 在Windows上，也检查Program Files
    platform_key = get_platform_key()
    if platform_key == 'windows':
        program_files = os.environ.get('PROGRAMFILES', 'C:/Program Files')
        possible_paths.extend([
            f'{program_files}/gettext/bin/msgfmt.exe',
            f'{program_files}/gettext/bin/msgunfmt.exe',
        ])
    
    for tool in ['msgfmt', 'msgunfmt', 'msgmerge']:
        # 首先尝试在PATH中查找
        tool_path = shutil.which(tool)
        if tool_path:
            tools[tool] = tool_path
        else:
            # 尝试可能的路径
            for path in possible_paths:
                if tool in path and os.path.exists(path):
                    tools[tool] = path
                    break
    
    if tools:
        # print("使用系统msgfmt工具")  # 移除调试信息
        pass
    
    _tools_cache = tools
    _tools_cache_time = current_time
    return tools

def is_msgfmt_available():
    """检查msgfmt工具是否可用（内置或系统）"""
    tools = find_msgfmt_tools()
    return 'msgfmt' in tools and 'msgunfmt' in tools

def is_msgmerge_available():
    """检查msgmerge工具是否可用（内置或系统）"""
    tools = find_msgfmt_tools()
    return 'msgmerge' in tools

def convert_with_msgfmt(input_path, output_path, mode):
    """使用msgfmt工具进行文件转换"""
    tools = find_msgfmt_tools()
    
    if mode == 'PO_TO_MO':
        cmd = [tools['msgfmt'], '-o', output_path, input_path]
    elif mode == 'MO_TO_PO':
        cmd = [tools['msgunfmt'], '-o', output_path, input_path]
    else:
        raise ValueError(f"不支持的转换模式: {mode}")
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30  # 30秒超时
        )
        
        if result.returncode != 0:
            raise RuntimeError(f"msgfmt执行失败: {result.stderr}")
        
        return True
    except subprocess.TimeoutExpired:
        raise RuntimeError("msgfmt执行超时")
    except FileNotFoundError:
        raise RuntimeError("找不到msgfmt工具")
    except Exception as e:
        raise RuntimeError(f"msgfmt执行错误: {str(e)}")

def clean_duplicate_entries(po_path):
    """清理PO文件中的重复条目"""
    try:
        from . import polib
        
        # 读取PO文件
        po = polib.pofile(po_path)
        
        # 用于跟踪已见过的msgid+msgctxt组合
        seen_entries = {}
        cleaned_entries = []
        duplicate_count = 0
        
        for entry in po:
            # 创建唯一键：msgid + msgctxt
            key = (entry.msgid, entry.msgctxt or "")
            
            if key in seen_entries:
                # 发现重复项，保留第一个，跳过后续的
                duplicate_count += 1
                continue
            else:
                seen_entries[key] = True
                cleaned_entries.append(entry)
        
        if duplicate_count > 0:
            # 创建新的PO文件
            cleaned_po = polib.POFile()
            cleaned_po.header = po.header
            cleaned_po.metadata = po.metadata
            
            for entry in cleaned_entries:
                cleaned_po.append(entry)
            
            # 备份原文件
            backup_path = po_path + '.backup'
            import shutil
            shutil.copy2(po_path, backup_path)
            
            # 保存清理后的文件
            cleaned_po.save(po_path)
            
            return duplicate_count
        else:
            return 0
            
    except Exception as e:
        raise RuntimeError(f"清理重复条目失败: {str(e)}")

def merge_po_files(template_path, translation_path, output_path, update_mode='merge', priority_mode='A_PRIORITY'):
    """合并PO文件，使用字典去重方式
    
    Args:
        template_path: PO文件A路径
        translation_path: PO文件B路径
        output_path: 输出PO文件路径
        update_mode: 更新模式 ('update', 'merge', 'backup')
        priority_mode: 优先级模式 ('A_PRIORITY', 'B_PRIORITY')
        
    注意：此函数使用字典去重方式，根据优先级模式处理重复项
    """
    try:
        from . import polib
        import datetime
        
        # 读取模板文件
        template_po = polib.pofile(template_path)
        
        # 读取翻译文件
        translation_po = polib.pofile(translation_path)
        
        # 创建合并字典，根据优先级模式处理重复项
        merged_dict = {}
        duplicates = 0
        
        if priority_mode == 'A_PRIORITY':
            # 以A文件为准：先添加A文件，再添加B文件
            # 首先添加PO文件A中的条目（作为基础）
            for entry in template_po:
                if entry.msgid and not entry.obsolete:
                    key = (entry.msgctxt or "*", entry.msgid)
                    if key not in merged_dict:
                        merged_dict[key] = entry
            
            # 然后添加PO文件B中的条目，如果有重复则跳过
            for entry in translation_po:
                if entry.msgid and not entry.obsolete:
                    key = (entry.msgctxt or "*", entry.msgid)
                    if key in merged_dict:
                        duplicates += 1
                        # 如果A文件中没有翻译，使用B文件中的翻译
                        existing_entry = merged_dict[key]
                        if not existing_entry.msgstr and entry.msgstr:
                            existing_entry.msgstr = entry.msgstr
                    else:
                        merged_dict[key] = entry
        else:
            # 以B文件为准：先添加B文件，再添加A文件
            # 首先添加PO文件B中的条目（作为基础）
            for entry in translation_po:
                if entry.msgid and not entry.obsolete:
                    key = (entry.msgctxt or "*", entry.msgid)
                    if key not in merged_dict:
                        merged_dict[key] = entry
            
            # 然后添加PO文件A中的条目，如果有重复则跳过
            for entry in template_po:
                if entry.msgid and not entry.obsolete:
                    key = (entry.msgctxt or "*", entry.msgid)
                    if key in merged_dict:
                        duplicates += 1
                        # 如果B文件中没有翻译，使用A文件中的翻译
                        existing_entry = merged_dict[key]
                        if not existing_entry.msgstr and entry.msgstr:
                            existing_entry.msgstr = entry.msgstr
                    else:
                        merged_dict[key] = entry
        
        # 创建新的PO文件
        merged_po = polib.POFile()
        
        # 复制头部信息
        if template_po.header:
            merged_po.header = template_po.header
        else:
            merged_po.header = translation_po.header
        
        # 复制元数据
        if template_po.metadata:
            merged_po.metadata = template_po.metadata
        else:
            merged_po.metadata = translation_po.metadata
        
        # 添加合并后的条目
        for key, entry in merged_dict.items():
            merged_po.append(entry)
        
        # 保存合并后的文件
        merged_po.save(output_path)
        
        if duplicates > 0:
            priority_text = "A文件" if priority_mode == 'A_PRIORITY' else "B文件"
            print(f"合并完成，检测到 {duplicates} 个重复项，已以{priority_text}为准")
        
        return True
        
    except Exception as e:
        raise RuntimeError(f"合并PO文件失败: {str(e)}")

def get_msgfmt_info():
    """获取msgfmt工具的详细信息"""
    global _info_cache, _info_cache_time
    
    # 检查缓存是否有效（5秒内）
    import time
    current_time = time.time()
    if _info_cache is not None and (current_time - _info_cache_time) < 5:
        return _info_cache
    
    tools = find_msgfmt_tools()
    
    if not tools:
        info = {
            'available': False,
            'type': 'none',
            'msgfmt_path': None,
            'msgunfmt_path': None
        }
    else:
        # 判断是内置工具还是系统工具
        builtin_msgfmt = get_builtin_msgfmt_path()
        if tools['msgfmt'] == builtin_msgfmt:
            tool_type = 'builtin'
        else:
            tool_type = 'system'
        
        info = {
            'available': True,
            'type': tool_type,
            'msgfmt_path': tools['msgfmt'],
            'msgunfmt_path': tools['msgunfmt'],
            'msgmerge_path': tools.get('msgmerge')
        }
    
    _info_cache = info
    _info_cache_time = current_time
    return info 