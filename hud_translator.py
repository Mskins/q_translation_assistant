"""
HUD翻译模块
通过重写blf_draw函数实现实时HUD翻译
"""

import bpy
import blf
import re
import gettext
import os
from bpy.props import StringProperty, BoolProperty
from bpy.types import AddonPreferences, Operator

# 全局变量
_original_blf_draw = None
_translation_func = None
_translation_cache = {}
_log_history_found = set()
_log_history_not_found = set()
_log_batch_size = 100
_log_counter = 0
_hud_translation_enabled = False

# 预编译正则表达式，用于匹配带前缀后缀的文本
_compiled_regex = re.compile(r"^([^A-Za-z0-9\s]*)([\w\s]+)([^A-Za-z0-9\s]*)$")


def setup_hud_translation(mo_file_path):
    """设置HUD翻译函数"""
    if not mo_file_path or not os.path.exists(mo_file_path):
        return lambda text: text
    try:
        # 使用独立的文件句柄，避免影响全局翻译环境
        with open(mo_file_path, "rb") as f:
            lang = gettext.GNUTranslations(f)
        
        # 创建一个完全独立的翻译函数，不修改全局环境
        def safe_gettext(text):
            # 检查Blender的语言设置
            try:
                if not bpy.context.preferences.view.use_translate_interface:
                    return text  # 如果禁用翻译，直接返回原始文本
            except:
                pass  # 如果无法获取设置，继续翻译
            
            # 跳过空字符串（通常是header）
            if not text or text.strip() == "":
                return text
            
            # 跳过看起来像header的文本（包含常见的header字段）
            header_fields = [
                "Project-Id-Version:", "Report-Msgid-Bugs-To:", "PO-Revision-Date:",
                "Last-Translator:", "Language-Team:", "Language:", "MIME-Version:",
                "Content-Type:", "Content-Transfer-Encoding:", "Plural-Forms:",
                "X-Generator:", "X-Poedit-KeywordsList:", "X-Poedit-Basepath:",
                "X-Poedit-SearchPath-0:", "X-Poedit-SearchPath-1:", "X-Poedit-SearchPath-2:"
            ]
            
            # 检查是否包含header字段
            for field in header_fields:
                if field in text:
                    return text
            
            # 检查是否是多行header格式（包含多个key: value对）
            if text.count('\n') > 2 and ':' in text:
                lines = text.split('\n')
                header_line_count = 0
                for line in lines:
                    if ':' in line and not line.strip().startswith('"'):
                        header_line_count += 1
                
                # 如果大部分行都是header格式，则跳过翻译
                if header_line_count >= len(lines) * 0.7:
                    return text
            
            # 使用独立的翻译对象，不修改全局环境
            try:
                return lang.gettext(text)
            except Exception:
                # 如果翻译失败，返回原始文本
                return text
        
        return safe_gettext
    except Exception:
        return lambda text: text


def translated_blf_draw(font_id, text, *args, **kwargs):
    """重写的blf_draw函数，支持实时翻译"""
    global _translation_func, _original_blf_draw, _hud_translation_enabled
    global _log_history_found, _log_history_not_found, _log_counter, _translation_cache

    # 如果HUD翻译未启用，直接使用原始函数
    if not _hud_translation_enabled:
        _original_blf_draw(font_id, text, *args, **kwargs)
        return

    if not _translation_func:
        _translation_func = lambda x: x

    if not isinstance(text, str):
        _original_blf_draw(font_id, text, *args, **kwargs)
        return
    
    # 检查Blender的语言设置，如果禁用翻译则直接显示原始文本
    try:
        if not bpy.context.preferences.view.use_translate_interface:
            _original_blf_draw(font_id, text, *args, **kwargs)
            return
    except:
        # 如果无法获取语言设置，继续翻译
        pass

    # 检查翻译缓存（但允许强制刷新）
    cache_key = f"{text}_{id(_translation_func)}"  # 包含翻译函数ID，确保语言切换时缓存失效
    if cache_key in _translation_cache:
        _original_blf_draw(font_id, _translation_cache[cache_key], *args, **kwargs)
        return

    # 使用预编译的正则表达式匹配带前缀后缀的文本
    match = _compiled_regex.match(text)
    final_text = text

    if match:
        prefix, main_text, suffix = match.groups()
        stripped_text = main_text.strip()
        
        # 检查主文本的翻译缓存
        if stripped_text in _translation_cache:
            translated_main_text = _translation_cache[stripped_text]
        else:
            translated_main_text = _translation_func(stripped_text)
            _translation_cache[stripped_text] = translated_main_text

        if translated_main_text != stripped_text:
            final_text = f"{prefix}{translated_main_text}{suffix}"
            if stripped_text not in _log_history_found:
                _log_counter += 1
                if _log_counter >= _log_batch_size:
                    _log_counter = 0
                _log_history_found.add(stripped_text)
        else:
            if stripped_text not in _log_history_not_found:
                _log_history_not_found.add(stripped_text)
    else:
        # 检查整个文本的翻译缓存
        translated_text = _translation_func(text)
        if translated_text != text:
            final_text = translated_text
            if text not in _log_history_found:
                _log_counter += 1
                if _log_counter >= _log_batch_size:
                    _log_counter = 0
                _log_history_found.add(text)
        else:
            if text not in _log_history_not_found:
                _log_history_not_found.add(text)

    # 缓存最终结果（使用包含翻译函数ID的键）
    _translation_cache[cache_key] = final_text
    _original_blf_draw(font_id, final_text, *args, **kwargs)


def register_hud_translation():
    """注册HUD翻译"""
    global _original_blf_draw, _translation_func, _hud_translation_enabled
    prefs = bpy.context.preferences.addons.get("q_translation_assistant")
    
    # 只有在HUD翻译启用时才注册
    if prefs and prefs.preferences.hud_enabled:
        mo_file_path = prefs.preferences.hud_mo_file_path
        _translation_func = setup_hud_translation(mo_file_path)
        _hud_translation_enabled = True
        
        # 只有在未注册时才替换blf.draw
        if _original_blf_draw is None:
            _original_blf_draw = blf.draw
            blf.draw = translated_blf_draw
    else:
        # 如果HUD翻译未启用，确保状态正确
        _hud_translation_enabled = False
        _translation_func = None


def unregister_hud_translation():
    """取消注册HUD翻译"""
    global _original_blf_draw, _translation_func, _hud_translation_enabled
    
    # 如果blf.draw已经被我们替换，恢复原始函数
    if _original_blf_draw is not None:
        blf.draw = _original_blf_draw
        _original_blf_draw = None
    elif hasattr(blf.draw, '__name__') and blf.draw.__name__ == 'translated_blf_draw':
        # 如果_original_blf_draw为None但blf.draw仍然是我们的函数，
        # 这意味着可能有问题，尝试获取真正的原始函数
        import importlib
        importlib.reload(blf)
    
    # 清理翻译函数和缓存
    _translation_func = None
    _hud_translation_enabled = False
    clear_hud_cache()
    
    # 强制清理可能影响全局翻译环境的变量
    try:
        # 清理gettext模块的全局状态
        import gettext
        # 重置gettext的全局状态
        gettext._translations.clear()
    except Exception:
        pass


def update_hud_translation():
    """更新HUD翻译"""
    global _translation_func, _hud_translation_enabled
    prefs = bpy.context.preferences.addons.get("q_translation_assistant")
    
    if prefs and prefs.preferences.hud_enabled:
        mo_file_path = prefs.preferences.hud_mo_file_path
        _translation_func = setup_hud_translation(mo_file_path)
        _hud_translation_enabled = True
    else:
        _translation_func = lambda x: x
        _hud_translation_enabled = False


def clear_hud_cache():
    """清除HUD翻译缓存"""
    global _translation_cache, _log_history_found, _log_history_not_found, _log_counter
    _translation_cache.clear()
    _log_history_found.clear()
    _log_history_not_found.clear()
    _log_counter = 0

def force_refresh_hud():
    """强制刷新HUD翻译"""
    global _translation_func, _translation_cache, _hud_translation_enabled
    # 清理缓存
    clear_hud_cache()
    # 重新设置翻译函数
    update_hud_translation()

def get_hud_status():
    """获取HUD翻译状态信息"""
    global _hud_translation_enabled, _translation_func, _original_blf_draw
    return {
        'enabled': _hud_translation_enabled,
        'translation_func_loaded': _translation_func is not None and _translation_func.__name__ != '<lambda>',
        'blf_hooked': _original_blf_draw is not None,
        'cache_size': len(_translation_cache)
    }



def update_hud_enabled(self, context):
    """当HUD翻译开关状态改变时自动处理注册/取消注册"""
    if hasattr(self, 'hud_enabled') and self.hud_enabled:
        register_hud_translation()
    else:
        # 完全取消注册HUD翻译，恢复原始blf.draw
        unregister_hud_translation()


def update_hud_settings(self, context):
    """当HUD翻译设置改变时更新翻译"""
    if hasattr(self, 'hud_enabled') and self.hud_enabled:
        update_hud_translation()
        clear_hud_cache()


# 操作器类
class HUD_TRANSLATION_OT_toggle(Operator):
    """切换HUD翻译开关"""
    bl_idname = "hud_translation.toggle"
    bl_label = "切换HUD翻译"
    bl_description = "开启或关闭HUD翻译功能"

    def execute(self, context):
        prefs = context.preferences.addons["q_translation_assistant"].preferences
        
        if prefs.hud_enabled:
            # 关闭HUD翻译
            unregister_hud_translation()
            prefs.hud_enabled = False
            self.report({'INFO'}, "HUD翻译已关闭")
        else:
            # 开启HUD翻译
            register_hud_translation()
            prefs.hud_enabled = True
            self.report({'INFO'}, "HUD翻译已开启")
        
        return {'FINISHED'}


class HUD_TRANSLATION_OT_reload(Operator):
    """重新加载HUD翻译"""
    bl_idname = "hud_translation.reload"
    bl_label = "重新加载翻译"
    bl_description = "重新加载HUD翻译文件"

    def execute(self, context):
        update_hud_translation()
        clear_hud_cache()
        self.report({'INFO'}, "HUD翻译已重新加载")
        return {'FINISHED'}


class HUD_TRANSLATION_OT_clear_cache(Operator):
    """清除HUD翻译缓存"""
    bl_idname = "hud_translation.clear_cache"
    bl_label = "清除缓存"
    bl_description = "清除HUD翻译缓存"

    def execute(self, context):
        clear_hud_cache()
        self.report({'INFO'}, "HUD翻译缓存已清除")
        return {'FINISHED'}


class HUD_TRANSLATION_OT_refresh(Operator):
    """刷新HUD翻译"""
    bl_idname = "hud_translation.refresh"
    bl_label = "刷新翻译"
    bl_description = "强制刷新HUD翻译，重新加载翻译文件并清除缓存"

    def execute(self, context):
        force_refresh_hud()
        self.report({'INFO'}, "HUD翻译已刷新")
        return {'FINISHED'}




# 首选项扩展
def draw_hud_preferences(self, context):
    """绘制HUD翻译首选项"""
    layout = self.layout
    prefs = context.preferences.addons["q_translation_assistant"].preferences
    
    # HUD翻译设置
    box = layout.box()
    box.label(text="HUD翻译设置", icon='FONTPREVIEW')
    
    # 启用开关
    row = box.row()
    row.prop(prefs, "hud_enabled", text="启用HUD翻译")
    
    if prefs.hud_enabled:
        # MO文件路径
        row = box.row()
        row.prop(prefs, "hud_mo_file_path", text="翻译文件")
        
        # 操作按钮
        row = box.row(align=True)
        row.operator("hud_translation.reload", text="重新加载", icon='FILE_REFRESH')
        row.operator("hud_translation.clear_cache", text="清除缓存", icon='X')
        
        # 刷新按钮
        row = box.row(align=True)
        row.operator("hud_translation.refresh", text="刷新翻译", icon='ARROW_LEFTRIGHT')
        
        # 状态信息
        status = get_hud_status()
        if status['enabled'] and status['translation_func_loaded']:
            box.label(text="✓ HUD翻译已启用并加载", icon='CHECKMARK')
        elif status['enabled']:
            box.label(text="⚠ HUD翻译已启用但未加载", icon='ERROR')
        else:
            box.label(text="✗ HUD翻译未启用", icon='CANCEL')
        
        # 详细状态信息
        info_box = box.box()
        info_box.label(text=f"状态: {'启用' if status['enabled'] else '禁用'}")
        info_box.label(text=f"翻译函数: {'已加载' if status['translation_func_loaded'] else '未加载'}")
        info_box.label(text=f"BLF钩子: {'已安装' if status['blf_hooked'] else '未安装'}")
        info_box.label(text=f"缓存大小: {status['cache_size']}")
    else:
        box.label(text="HUD翻译已禁用", icon='INFO')


# 注册和取消注册函数
def register():
    """注册HUD翻译模块"""
    # 注册操作器
    bpy.utils.register_class(HUD_TRANSLATION_OT_toggle)
    bpy.utils.register_class(HUD_TRANSLATION_OT_reload)
    bpy.utils.register_class(HUD_TRANSLATION_OT_clear_cache)
    bpy.utils.register_class(HUD_TRANSLATION_OT_refresh)


def unregister():
    """取消注册HUD翻译模块"""
    # 取消注册HUD翻译
    unregister_hud_translation()
    
    # 取消注册操作器
    classes_to_unregister = [
        HUD_TRANSLATION_OT_toggle,
        HUD_TRANSLATION_OT_reload,
        HUD_TRANSLATION_OT_clear_cache,
        HUD_TRANSLATION_OT_refresh,
    ]
    
    for cls in classes_to_unregister:
        try:
            bpy.utils.unregister_class(cls)
        except (ValueError, RuntimeError):
            # 如果类未注册或已经取消注册，忽略错误
            pass 