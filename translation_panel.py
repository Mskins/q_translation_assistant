# -*- coding: utf-8 -*-
"""
自动翻译与文本提取UI模块
"""
import bpy
import time
import re
import os
import threading
from bpy.props import StringProperty, CollectionProperty, IntProperty, EnumProperty, BoolProperty
from bpy.types import Panel, Operator, UIList, PropertyGroup

from .text_extractor import TextExtractor
from .translator import LLMTranslator, SEPARATOR
from .preferences import (
    create_translator_from_prefs,
    is_translation_configured,
    draw_translation_settings,
)
from . import polib
from .utils import find_po_entry, MSGCTXT_ITEMS

def update_translation_entry_msgctxt_preset(self, context):
    """当从预设中选择一个上下文时，更新编辑中词条的msgctxt"""
    self.msgctxt = self.msgctxt_preset

def find_translation_entry(entries, source_text, msgctxt):
    """在翻译条目集合中查找词条，返回其索引，如果未找到则返回-1"""
    lookup_msgctxt = msgctxt or ""
    for i, entry in enumerate(entries):
        entry_msgctxt = entry.msgctxt or ""
        if entry.source_text == source_text and entry_msgctxt == lookup_msgctxt:
            return i
    return -1

def add_translation_entry_update(self, context):
    """"添加翻译词条"对话框中属性的更新回调函数"""
    self.info_message = ""
    if self.source_text:
        existing_index = find_translation_entry(context.scene.qta_translation_entries, self.source_text, self.msgctxt)
        if existing_index != -1:
            self.info_message = "警告: 词条已存在！"

# -- 数据结构
class QTA_TranslationEntry(PropertyGroup):
    """用于UIList的翻译条目"""
    source_text: StringProperty(name="原文")
    translated_text: StringProperty(name="译文")
    msgctxt: StringProperty(name="上下文")
    msgctxt_preset: EnumProperty(
        name="上下文预设",
        items=MSGCTXT_ITEMS,
        description="从预设中选择一个上下文",
        update=update_translation_entry_msgctxt_preset
    )
    bl_options = {'DEFAULT_CLOSED'}

# -- UIList
class QTA_UL_TranslationEntries(UIList):
    """翻译条目的UIList"""
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        # 仅展示，不直接编辑
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            row = layout.row()
            row.prop(item, "source_text", text="", emboss=False)
            row.prop(item, "translated_text", text="", emboss=False)
        elif self.layout_type in {'GRID'}:
            layout.alignment = 'CENTER'
            layout.label(text="", icon_value=icon)

    def filter_items(self, context, data, propname):
        """
        列表项的搜索/过滤功能
        """
        items = getattr(data, propname)
        filter_text = context.scene.qta_translation_filter.lower()
        flt_flags = []
        if filter_text:
            for item in items:
                if (filter_text in item.source_text.lower()) or (filter_text in item.translated_text.lower()):
                    flt_flags.append(self.bitflag_filter_item)
                else:
                    flt_flags.append(0)
        else:
            flt_flags = [self.bitflag_filter_item] * len(items)
        return flt_flags, []

# -- 操作符
class QTA_OT_ExtractText(Operator):
    """从目录或.blend文件中提取文本"""
    bl_idname = "qta.extract_text"
    bl_label = "提取文本"
    bl_description = "从指定源提取可翻译的文本"

    @classmethod
    def poll(cls, context):
        scene = context.scene
        if scene.qta_extract_source == 'ADDON':
            return scene.qta_source_directory != ""
        else: # BLEND
            if getattr(scene, 'qta_use_current_blend', False):
                return True
            return scene.qta_source_blend_file != ""

    def execute(self, context):
        scene = context.scene
        scene.qta_translation_entries.clear()
        extractor = TextExtractor()
        all_texts = []
        extract_docstring = getattr(scene, 'qta_extract_docstring', False)
        extract_json = getattr(scene, 'qta_extract_json', False)
        json_keys = None
        if extract_json:
            keys_str = getattr(scene, 'qta_json_keys', "")
            if keys_str.strip():
                json_keys = [k.strip() for k in keys_str.split(',') if k.strip()]
        if scene.qta_extract_source == 'ADDON':
            self.report({'INFO'}, "正在从插件目录中提取...")
            # 构建过滤选项
            filter_options = {
                'filter_variables': getattr(scene, 'qta_filter_variables', True),
                'filter_keywords': getattr(scene, 'qta_filter_keywords', True),
                'filter_tech_ids': getattr(scene, 'qta_filter_tech_ids', True),
                'filter_format_placeholders': getattr(scene, 'qta_filter_format_placeholders', True),
                'filter_paths_urls': getattr(scene, 'qta_filter_paths_urls', True),
                'filter_data_keys': getattr(scene, 'qta_filter_data_keys', True),
                'filter_special_chars': getattr(scene, 'qta_filter_special_chars', True),
                'filter_repetitive': getattr(scene, 'qta_filter_repetitive', True),
            }
            all_texts = extractor.extract_from_directory(
                scene.qta_source_directory,
                extract_docstring=extract_docstring,
                extract_json=extract_json,
                json_keys=json_keys,
                filter_options=filter_options
            )
        else: # BLEND
            # 构建Blend文件提取选项
            extract_options = {
                'extract_objects': getattr(scene, 'qta_extract_objects', True),
                'extract_materials': getattr(scene, 'qta_extract_materials', True),
                'extract_worlds': getattr(scene, 'qta_extract_worlds', True),
                'extract_collections': getattr(scene, 'qta_extract_collections', True),
                'extract_textures': getattr(scene, 'qta_extract_textures', True),
                'extract_images': getattr(scene, 'qta_extract_images', True),
                'extract_node_groups': getattr(scene, 'qta_extract_node_groups', True),
                'extract_node_sockets': getattr(scene, 'qta_extract_node_sockets', True),
                'extract_node_panels': getattr(scene, 'qta_extract_node_panels', True),
            }
            
            if scene.qta_use_current_blend:
                self.report({'INFO'}, "正在从当前Blend文件中提取...")
                all_texts = extractor.extract_from_current_blend(extract_options)
            else:
                self.report({'INFO'}, "正在从.blend文件中提取...")
                all_texts = extractor.extract_from_blend_file(scene.qta_source_blend_file, extract_options)
        unique_texts = extractor.get_unique_texts(all_texts)
        
        # 应用字符串长度过滤
        min_length = getattr(scene, 'qta_min_text_length', 0)
        filtered_texts = []
        for text_obj in unique_texts:
            if len(text_obj.text.strip()) >= min_length:
                filtered_texts.append(text_obj)
        
        for text_obj in filtered_texts:
            new_entry = scene.qta_translation_entries.add()
            new_entry.source_text = text_obj.text
            new_entry.msgctxt = text_obj.context
        
        filtered_count = len(filtered_texts)
        total_count = len(unique_texts)
        if min_length > 0:
            self.report({'INFO'}, f"提取完成，找到 {total_count} 个词条，过滤后保留 {filtered_count} 个（长度≥{min_length}）")
        else:
            self.report({'INFO'}, f"提取完成，找到 {filtered_count} 个独立词条")
        return {'FINISHED'}

# 添加翻译线程类
class TranslationThread(threading.Thread):
    def __init__(self, entries, translator):
        super().__init__()
        self.entries = entries
        self.translator = translator
        self.progress = 0.0
        self.completed = False
        self.error = None
        self.lock = threading.Lock()
        self.translated_count = 0
        self.warnings = []
        self.daemon = True  # 设置为守护线程，主程序退出时自动结束

    def _split_translation_result(self, dst_text: str, expected_count: int, separator: str) -> list:
        """增强的翻译结果分割方法"""
        import re
        
        # 清理文本
        cleaned_text = dst_text.strip()
        
        # 方法1: 使用标准分隔符分割
        lines = cleaned_text.split(separator)
        if len(lines) == expected_count:
            return [line.strip() for line in lines if line.strip()]
        
        # 方法2: 尝试清理分隔符后再次分割
        # 处理可能的分隔符变体
        separator_variants = [
            separator,  # |||~|||
            '|||~|||',  # 确保格式正确
            '||| ~ |||',  # 带空格的分隔符
            '|||~||| ',  # 末尾有空格
            ' |||~|||',  # 开头有空格
        ]
        
        for sep in separator_variants:
            if sep in cleaned_text:
                lines = cleaned_text.split(sep)
                if len(lines) == expected_count:
                    return [line.strip() for line in lines if line.strip()]
        
        # 方法3: 使用正则表达式查找分隔符模式
        # 匹配 |||~||| 及其变体
        pattern = r'\|\|\|~?\|\|\|'
        lines = re.split(pattern, cleaned_text)
        if len(lines) == expected_count:
            return [line.strip() for line in lines if line.strip()]
        
        # 方法4: 尝试按换行符分割（作为最后手段）
        lines = cleaned_text.split('\n')
        if len(lines) == expected_count:
            return [line.strip() for line in lines if line.strip()]
        
        # 方法5: 如果都失败了，尝试智能分割
        # 基于原文长度比例进行分割
        if expected_count > 1:
            # 简单按长度平均分割（不推荐，但作为最后手段）
            avg_length = len(cleaned_text) // expected_count
            lines = []
            start = 0
            for i in range(expected_count - 1):
                end = start + avg_length
                # 尝试在合适的位置分割（避免在中文中间分割）
                if end < len(cleaned_text):
                    # 寻找最近的标点符号或空格
                    for j in range(end, min(end + 20, len(cleaned_text))):
                        if cleaned_text[j] in '。，！？；：':
                            end = j + 1
                            break
                lines.append(cleaned_text[start:end].strip())
                start = end
            lines.append(cleaned_text[start:].strip())
            return lines
        
        # 如果所有方法都失败，返回原始文本
        return [cleaned_text]

    def run(self):
        try:
            total_entries = len(self.entries)
            chunk_size = 10

            for i in range(0, total_entries, chunk_size):
                # 更新进度
                with self.lock:
                    self.progress = (i / total_entries) * 100

                chunk_entries = self.entries[i:i + chunk_size]

                # 批量翻译
                try:
                    # 使用唯一分隔符连接查询（分隔符由 translator 模块统一定义）
                    queries = [entry.source_text for entry in chunk_entries]
                    query_string = SEPARATOR.join(queries)

                    result = self.translator.translate(query_string, from_lang='en', to_lang='zh')

                    if 'trans_result' in result:
                        # 处理可能返回的单块结果
                        if len(result['trans_result']) == 1 and len(chunk_entries) > 1:
                            dst_text = result['trans_result'][0]['dst']

                            # 增强的分割逻辑
                            translated_lines = self._split_translation_result(dst_text, len(chunk_entries), SEPARATOR)

                            if len(translated_lines) == len(chunk_entries):
                                for k, line in enumerate(translated_lines):
                                    chunk_entries[k].translated_text = line.strip()
                                    with self.lock:
                                        self.translated_count += 1
                            else:
                                # 如果行数不匹配，则将整个结果放入第一个词条的译文处
                                chunk_entries[0].translated_text = dst_text
                                with self.lock:
                                    self.warnings.append(f"返回译文行数与原文不匹配，已将整块结果放入词条 {i+1}")

                        # 处理正常的多行结果
                        else:
                            for j, trans_item in enumerate(result['trans_result']):
                                original_index = i + j
                                if original_index < total_entries:
                                    # 确保源文本能匹配上，避免错位
                                    if chunk_entries[j].source_text == trans_item['src']:
                                        chunk_entries[j].translated_text = trans_item['dst']
                                        with self.lock:
                                            self.translated_count += 1
                                    else:
                                        with self.lock:
                                            self.warnings.append(f"词条 {original_index + 1} 源文本不匹配，跳过应用译文")

                    else:
                        error_msg = result.get('error_msg', '未知错误')
                        with self.lock:
                            self.error = f"翻译失败: {error_msg}"
                        break
                except Exception as e:
                    with self.lock:
                        self.warnings.append(f"批量翻译异常: {str(e)}")

            # 完成
            with self.lock:
                self.progress = 100.0
                self.completed = True
                
        except Exception as e:
            with self.lock:
                self.error = f"翻译过程中发生错误: {str(e)}"
                self.completed = True

class QTA_OT_AutoTranslate(Operator):
    """使用API自动翻译所有提取的词条"""
    bl_idname = "qta.auto_translate"
    bl_label = "一键翻译"
    bl_description = "使用偏好设置中配置的API一键翻译所有词条"

    @classmethod
    def poll(cls, context):
        return len(context.scene.qta_translation_entries) > 0

    def execute(self, context):
        prefs = context.preferences.addons[__package__].preferences

        # 根据偏好设置创建通用大模型翻译器
        try:
            translator = create_translator_from_prefs(prefs)
        except ValueError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}

        # 设置翻译状态
        context.scene.qta_translation_in_progress = True
        context.scene.qta_translation_progress = 0.0

        # 创建翻译线程
        entries = context.scene.qta_translation_entries
        self.translation_thread = TranslationThread(entries, translator)
        self.translation_thread.start()
        
        # 启动定时器来检查翻译进度
        bpy.app.timers.register(self.check_translation_progress)
        
        # 启动UI刷新定时器
        bpy.app.timers.register(self._ui_refresh_timer)
        
        return {'RUNNING_MODAL'}

    def check_translation_progress(self):
        """定时检查翻译进度"""
        if not hasattr(self, 'translation_thread') or not self.translation_thread.is_alive():
            # 线程已完成或不存在
            if hasattr(self, 'translation_thread'):
                with self.translation_thread.lock:
                    if self.translation_thread.completed:
                        # 清理进度条和状态
                        bpy.context.window_manager.progress_end()
                        bpy.context.workspace.status_text_set("")
                        
                        # 清除翻译状态
                        bpy.context.scene.qta_translation_in_progress = False
                        bpy.context.scene.qta_translation_progress = 0.0
                        
                        if self.translation_thread.error:
                            self.report({'ERROR'}, self.translation_thread.error)
                        else:
                            # 显示警告信息
                            for warning in self.translation_thread.warnings:
                                self.report({'WARNING'}, warning)
                            self.report({'INFO'}, f"翻译完成，共处理 {self.translation_thread.translated_count} 个词条")
                        
                        # 强制刷新所有UI区域
                        self._force_ui_refresh()
                        return None  # 停止定时器
            return None  # 停止定时器
        
        # 更新进度条和状态
        with self.translation_thread.lock:
            progress = self.translation_thread.progress
            translated_count = self.translation_thread.translated_count
            total_entries = len(self.translation_thread.entries)
        
        # 更新场景中的翻译状态
        bpy.context.scene.qta_translation_progress = progress
        
        # 更新Blender的进度条
        bpy.context.window_manager.progress_begin(0, 100)
        bpy.context.window_manager.progress_update(progress)
        bpy.context.workspace.status_text_set(f"正在翻译... ({translated_count}/{total_entries})")
        
        # 强制刷新所有UI区域
        self._force_ui_refresh()
        
        return 0.1  # 每0.1秒检查一次

    def _force_ui_refresh(self):
        """强制刷新所有UI区域"""
        # 只刷新3D视图区域，因为我们的面板在那里
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == 'VIEW_3D':
                    area.tag_redraw()

    def _ui_refresh_timer(self):
        """UI刷新定时器，确保面板实时更新"""
        if hasattr(self, 'translation_thread') and self.translation_thread.is_alive():
            # 只刷新3D视图区域，因为我们的面板在那里
            for window in bpy.context.window_manager.windows:
                for area in window.screen.areas:
                    if area.type == 'VIEW_3D':
                        area.tag_redraw()
            return 0.3  # 每0.3秒刷新一次UI
        return None  # 停止定时器

    def modal(self, context, event):
        """模态操作处理"""
        if event.type == 'ESC':
            # 用户取消操作
            if hasattr(self, 'translation_thread') and self.translation_thread.is_alive():
                self.translation_thread.join(timeout=1.0)  # 等待线程结束
            bpy.context.window_manager.progress_end()
            bpy.context.workspace.status_text_set("")
            
            # 清除翻译状态
            context.scene.qta_translation_in_progress = False
            context.scene.qta_translation_progress = 0.0
            
            # 强制刷新UI以显示更新后的状态
            self._force_ui_refresh()
            
            self.report({'INFO'}, "翻译已取消")
            return {'CANCELLED'}
        
        return {'PASS_THROUGH'}

    def cancel(self, context):
        """取消操作时的清理"""
        if hasattr(self, 'translation_thread') and self.translation_thread.is_alive():
            self.translation_thread.join(timeout=1.0)
        bpy.context.window_manager.progress_end()
        bpy.context.workspace.status_text_set("")
        
        # 清除翻译状态
        context.scene.qta_translation_in_progress = False
        context.scene.qta_translation_progress = 0.0
        
        # 强制刷新UI以显示更新后的状态
        self._force_ui_refresh()

class QTA_OT_TranslateSingleEntry(Operator):
    """使用API翻译单个选中的词条"""
    bl_idname = "qta.translate_single_entry"
    bl_label = "翻译当前词条"
    bl_description = "使用偏好设置中配置的API翻译当前选中的词条"
    
    source: EnumProperty(
        items=[
            ('PO_EDITOR', "PO Editor", "从PO编辑器调用"),
            ('TRANSLATION_PANEL', "Translation Panel", "从文本提取与翻译面板调用")
        ],
        name="Source Panel",
        description="指定调用此操作的源面板"
    )

    @classmethod
    def poll(cls, context):
        prefs = context.preferences.addons[__package__].preferences
        # 确保当前翻译服务已配置
        return is_translation_configured(prefs)

    def execute(self, context):
        prefs = context.preferences.addons[__package__].preferences
        scene = context.scene

        # 1. 初始化通用大模型翻译器
        try:
            translator = create_translator_from_prefs(prefs)
        except ValueError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        
        # 2. 获取活动词条和源文本
        active_entry = None
        source_text = ""
        if self.source == 'PO_EDITOR' and scene.qta_po_entries:
            active_entry = scene.qta_po_entries[scene.qta_po_entries_index]
            source_text = active_entry.msgid
        elif self.source == 'TRANSLATION_PANEL' and scene.qta_translation_entries:
            active_entry = scene.qta_translation_entries[scene.qta_translation_entries_index]
            source_text = active_entry.source_text
            
        if not active_entry or not source_text:
            self.report({'WARNING'}, "没有选中的有效词条可供翻译")
            return {'CANCELLED'}
            
        # 3. 执行翻译
        result = translator.translate(source_text, from_lang='en', to_lang='zh')

        # 4. 更新译文
        if 'trans_result' in result and result['trans_result']:
            translated_text = result['trans_result'][0]['dst']
            # 修复大模型单条翻译时分隔符残留和重复问题
            if isinstance(translator, LLMTranslator):
                # 清理分隔符
                translated_text = translated_text.replace('|||~|||', '').strip()
                
                # 自动去除"译文 --- 译文"或"原文: --- 译文"重复
                parts = [p.strip() for p in re.split(r'---+', translated_text)]
                if len(parts) == 2:
                    # 如果两部分内容完全一致，保留一份
                    if parts[0] == parts[1]:
                        translated_text = parts[0]
                    # 如果第一部分是原文，第二部分是译文，且原文以冒号结尾，保留第二部分
                    elif source_text.strip().endswith(':') and parts[0] == source_text.strip():
                        translated_text = parts[1]
                
                # 额外清理：去除可能残留的格式标记
                translated_text = re.sub(r'^[：:]\s*', '', translated_text)  # 去除开头的冒号
                translated_text = re.sub(r'^["""]\s*', '', translated_text)  # 去除开头的引号
                translated_text = re.sub(r'\s*["""]$', '', translated_text)  # 去除结尾的引号
            if self.source == 'PO_EDITOR':
                active_entry.msgstr = translated_text
            else: # TRANSLATION_PANEL
                active_entry.translated_text = translated_text
            self.report({'INFO'}, "翻译成功！")
        else:
            error_msg = result.get('error_msg', '未知错误')
            self.report({'ERROR'}, f"翻译失败: {error_msg}")
            return {'CANCELLED'}

        return {'FINISHED'}

class QTA_OT_EditTranslationEntry(Operator):
    """通过对话框编辑选中的翻译词条"""
    bl_idname = "qta.edit_translation_entry"
    bl_label = "编辑词条"
    bl_options = {'REGISTER', 'UNDO'}

    source_text: StringProperty(name="原文 (msgid)")
    translated_text: StringProperty(name="译文 (msgstr)")
    msgctxt: StringProperty(name="上下文 (msgctxt)")
    msgctxt_preset: EnumProperty(
        name="上下文预设",
        items=MSGCTXT_ITEMS,
        description="从预设中选择一个上下文",
        update=lambda self, context: setattr(self, 'msgctxt', self.msgctxt_preset)
    )

    @classmethod
    def poll(cls, context):
        return (context.scene.qta_translation_entries and 
                context.scene.qta_translation_entries_index >= 0)

    def invoke(self, context, event):
        scene = context.scene
        active_entry = scene.qta_translation_entries[scene.qta_translation_entries_index]
        
        # 预填充当前值
        self.source_text = active_entry.source_text
        self.translated_text = active_entry.translated_text
        self.msgctxt = active_entry.msgctxt
        
        return context.window_manager.invoke_props_dialog(self, width=400)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "source_text")
        layout.prop(self, "translated_text")
        layout.prop(self, "msgctxt")
        layout.prop(self, "msgctxt_preset")

    def execute(self, context):
        scene = context.scene
        active_entry = scene.qta_translation_entries[scene.qta_translation_entries_index]
        
        if not self.source_text:
            self.report({'ERROR'}, "原文不能为空")
            return {'CANCELLED'}
        
        # 更新词条
        active_entry.source_text = self.source_text
        active_entry.translated_text = self.translated_text
        active_entry.msgctxt = self.msgctxt
        
        self.report({'INFO'}, "词条已更新")
        return {'FINISHED'}

class QTA_OT_ExportToFile(Operator):
    """通过对话框将翻译结果导出为PO或MO文件"""
    bl_idname = "qta.export_to_file"
    bl_label = "导出为文件"
    bl_options = {'REGISTER', 'UNDO'}

    filepath: StringProperty(subtype="FILE_PATH", name="文件路径")
    
    export_format: EnumProperty(
        name="导出格式",
        items=[('PO', ".po", "可编辑的文本格式"), ('MO', ".mo", "编译后的二进制格式")],
        default='PO'
    )
    
    @classmethod
    def poll(cls, context):
        return len(context.scene.qta_translation_entries) > 0

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)
        
    def draw(self, context):
        layout = self.layout
        layout.prop(self, "export_format", expand=True)
        layout.prop(self, "filepath")

    def execute(self, context):
        scene = context.scene
        entries = scene.qta_translation_entries
        
        # 确保文件路径有正确的扩展名
        if not self.filepath:
            self.report({'ERROR'}, "请指定文件路径")
            return {'CANCELLED'}
            
        if self.export_format == 'PO' and not self.filepath.endswith('.po'):
            self.filepath += '.po'
        elif self.export_format == 'MO' and not self.filepath.endswith('.mo'):
            self.filepath += '.mo'

        po = polib.POFile(wrapwidth=0)
        po.metadata = {
            'Project-Id-Version': '1.0',
            'Report-Msgid-Bugs-To': 'test@example.com',
            'POT-Creation-Date': time.strftime('%Y-%m-%d %H:%M%z'),
            'PO-Revision-Date': time.strftime('%Y-%m-%d %H:%M%z'),
            'Last-Translator': 'Quick Translation Assistant',
            'Language-Team': 'Chinese',
            'Language': 'zh_CN',
            'MIME-Version': '1.0',
            'Content-Type': 'text/plain; charset=UTF-8',
            'Content-Transfer-Encoding': '8bit',
        }

        for item in entries:
            po.append(polib.POEntry(
                msgid=item.source_text,
                msgstr=item.translated_text,
                msgctxt=item.msgctxt or None
            ))
            
        try:
            if self.export_format == 'PO':
                po.save(self.filepath)
            else: # MO
                po.save_as_mofile(self.filepath)
                
        except Exception as e:
            self.report({'ERROR'}, f"保存文件失败: {e}")
            return {'CANCELLED'}
            
        self.report({'INFO'}, f"文件已成功导出到: {self.filepath}")
        return {'FINISHED'}

class QTA_OT_AppendToEditor(Operator):
    """将新词条追加到PO编辑器中"""
    bl_idname = "qta.append_to_editor"
    bl_label = "追加到编辑器"
    bl_description = "将已翻译的新词条（在编辑器中不存在的）追加到PO编辑器"

    @classmethod
    def poll(cls, context):
        return len(context.scene.qta_translation_entries) > 0 and context.scene.qta_po_filepath != ""

    def execute(self, context):
        scene = context.scene
        translation_entries = scene.qta_translation_entries
        po_entries = scene.qta_po_entries
        
        # 创建PO编辑器中现有词条的字典索引，优化查找性能
        existing_po_entries = {}
        for entry in po_entries:
            key = (entry.msgctxt or "", entry.msgid)
            existing_po_entries[key] = True
        
        appended_count = 0
        for tentry in translation_entries:
            # 只追加有译文且在PO编辑器中不存在的新词条
            if tentry.translated_text:
                key = (tentry.msgctxt or "", tentry.source_text)
                if key not in existing_po_entries:
                    new_po_entry = po_entries.add()
                    new_po_entry.msgid = tentry.source_text
                    new_po_entry.msgstr = tentry.translated_text
                    new_po_entry.msgctxt = tentry.msgctxt
                    appended_count += 1
                
        self.report({'INFO'}, f"追加了 {appended_count} 个新词条到PO编辑器")
        return {'FINISHED'}

class QTA_OT_AddTranslationEntry(Operator):
    """通过对话框在翻译列表中添加一个新词条"""
    bl_idname = "qta.add_translation_entry"
    bl_label = "添加翻译词条"
    bl_options = {'REGISTER', 'UNDO'}

    source_text: StringProperty(name="原文 (msgid)", default="", update=add_translation_entry_update)
    msgstr: StringProperty(name="译文 (msgstr)", default="")
    msgctxt: StringProperty(name="上下文 (msgctxt)", default="", update=add_translation_entry_update)
    msgctxt_preset: EnumProperty(
        name="上下文预设",
        items=MSGCTXT_ITEMS,
        description="从预设中选择一个上下文",
        update=lambda self, context: setattr(self, 'msgctxt', self.msgctxt_preset)
    )
    info_message: StringProperty(name="", default="")

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=400)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "source_text")
        layout.prop(self, "msgstr")
        layout.prop(self, "msgctxt")
        layout.prop(self, "msgctxt_preset")

        if self.info_message:
            row = layout.row()
            row.label(text=self.info_message, icon='ERROR')

    def execute(self, context):
        scene = context.scene
        entries = scene.qta_translation_entries
        
        if not self.source_text:
            self.report({'WARNING'}, "原文不能为空")
            return {'CANCELLED'}

        # 检查词条是否已存在
        existing_index = find_translation_entry(entries, self.source_text, self.msgctxt)
        if existing_index != -1:
            # 如果存在，则选中它，不添加新的
            scene.qta_translation_entries_index = existing_index
            self.report({'INFO'}, "词条已存在，已为您选中")
            return {'FINISHED'}
            
        # 如果不存在，添加新词条
        new_entry = entries.add()
        new_entry.source_text = self.source_text
        new_entry.translated_text = self.msgstr
        new_entry.msgctxt = self.msgctxt
        
        # 选中新添加的词条
        context.scene.qta_translation_entries_index = len(entries) - 1
        
        # 强制UI刷新
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                for region in area.regions:
                    if region.type == 'UI':
                        region.tag_redraw()
                        
        self.report({'INFO'}, "新词条已添加")
        return {'FINISHED'}

class QTA_OT_RemoveTranslationEntry(Operator):
    """从翻译列表中移除选中的词条"""
    bl_idname = "qta.remove_translation_entry"
    bl_label = "移除翻译词条"
    bl_options = {'REGISTER', 'UNDO'}

    index_to_remove: IntProperty(name="要移除的索引", options={'HIDDEN'})

    @classmethod
    def poll(cls, context):
        return context.scene.qta_translation_entries_index >= 0 and len(context.scene.qta_translation_entries) > 0

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        scene = context.scene
        index = self.index_to_remove
        if index < 0 or index >= len(scene.qta_translation_entries):
            self.report({'ERROR'}, "无效的索引，无法移除")
            return {'CANCELLED'}
        scene.qta_translation_entries.remove(index)
        if len(scene.qta_translation_entries) > 0:
            scene.qta_translation_entries_index = min(max(0, index - 1), len(scene.qta_translation_entries) - 1)
        else:
            scene.qta_translation_entries_index = 0
        return {'FINISHED'}

class QTA_OT_DeduplicateAgainstEditor(Operator):
    """从提取列表中，移除在PO编辑器中已存在的条目"""
    bl_idname = "qta.deduplicate_against_editor"
    bl_label = "与编辑器比对去重"
    bl_description = "移除此列表中在下方PO编辑器里已存在的词条"

    @classmethod
    def poll(cls, context):
        return len(context.scene.qta_translation_entries) > 0 and len(context.scene.qta_po_entries) > 0

    def execute(self, context):
        scene = context.scene
        translation_entries = scene.qta_translation_entries
        po_entries = scene.qta_po_entries
        
        # 创建PO编辑器中现有词条的字典索引，优化查找性能
        existing_po_entries = {}
        for entry in po_entries:
            key = (entry.msgctxt or "", entry.msgid)
            existing_po_entries[key] = True
        
        # 为了安全地在迭代时移除，我们从后往前遍历
        indices_to_remove = []
        for i, tentry in enumerate(translation_entries):
            key = (tentry.msgctxt or "", tentry.source_text)
            if key in existing_po_entries:
                indices_to_remove.append(i)
        
        removed_count = len(indices_to_remove)
        for i in reversed(indices_to_remove):
            translation_entries.remove(i)

        # 调整选中索引
        if scene.qta_translation_entries_index >= len(translation_entries) and len(translation_entries) > 0:
            scene.qta_translation_entries_index = len(translation_entries) - 1

        self.report({'INFO'}, f"去重完成，移除了 {removed_count} 个已存在的词条")
        return {'FINISHED'}

class QTA_OT_ReplaceInTranslations(Operator):
    """批量替换所有译文中的指定文本"""
    bl_idname = "qta.replace_in_translations"
    bl_label = "文本替换"
    bl_options = {'REGISTER', 'UNDO'}

    find_text: StringProperty(name="要替换的内容", default="")
    replace_text: StringProperty(name="替换为", default="")

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=400)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "find_text")
        layout.prop(self, "replace_text")

    def execute(self, context):
        scene = context.scene
        count = 0
        for entry in scene.qta_translation_entries:
            if self.find_text in entry.translated_text:
                entry.translated_text = entry.translated_text.replace(self.find_text, self.replace_text)
                count += 1
        self.report({'INFO'}, f"已替换 {count} 处")
        return {'FINISHED'}

class QTA_OT_LoadPOToPanel(Operator):
    """加载PO文件到翻译面板"""
    bl_idname = "qta.load_po_to_panel"
    bl_label = "加载PO文件"
    bl_description = "将PO文件内容加载到翻译面板列表"

    filepath: StringProperty(subtype="FILE_PATH", name="PO文件路径")

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        scene = context.scene
        if not self.filepath or not self.filepath.endswith('.po'):
            self.report({'ERROR'}, "请选择.po文件")
            return {'CANCELLED'}
        try:
            from . import polib
            po = polib.pofile(self.filepath)
            scene.qta_translation_entries.clear()
            for entry in po:
                new_entry = scene.qta_translation_entries.add()
                new_entry.source_text = entry.msgid
                new_entry.translated_text = entry.msgstr
                new_entry.msgctxt = entry.msgctxt or ""
            scene.qta_translation_entries_index = 0
            self.report({'INFO'}, f"已加载 {len(po)} 条PO词条")
        except Exception as e:
            self.report({'ERROR'}, f"加载失败: {e}")
            return {'CANCELLED'}
        return {'FINISHED'}

# -- 主面板
class QTA_PT_AutoTranslation(Panel):
    """文本提取与翻译面板"""
    bl_label = "文本提取与翻译"
    bl_idname = "QTA_PT_AutoTranslation"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "翻译助手"

    @classmethod
    def poll(cls, context):
        # 如果翻译正在进行，强制面板重绘
        if context.scene.qta_translation_in_progress:
            # 触发面板重绘
            for area in context.screen.areas:
                if area.type == 'VIEW_3D':
                    area.tag_redraw()
        return True

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        # --- 提取操作 ---
        box = layout.box()
        row = box.row(align=True)
        row.prop_enum(scene, "qta_extract_source", 'ADDON', text="插件", icon='SCRIPT')
        row.prop_enum(scene, "qta_extract_source", 'BLEND', text="Blend文件", icon='FILE_BLEND')
        if scene.qta_extract_source == 'ADDON':
            box.prop(scene, "qta_source_directory", text="插件目录")
            # 插件特有的提取选项
            box.prop(scene, "qta_extract_docstring", text="提取多行注释")
            box.prop(scene, "qta_extract_json", text="提取JSON")
            if scene.qta_extract_json:
                box.prop(scene, "qta_json_keys", text="JSON提取key（逗号分隔）")
        else: # 'BLEND'
            row = box.row(align=True)
            row.prop(scene, "qta_use_current_blend", text="当前文件")
            if not scene.qta_use_current_blend:
                box.prop(scene, "qta_source_blend_file", text=".blend文件")
            else:
                box.label(text="将从当前打开的Blend文件提取", icon='INFO')
        
        # 字符串长度过滤设置
        row = box.row()
        row.prop(scene, "qta_min_text_length", text="最小字符串长度")
        if scene.qta_min_text_length > 0:
            row.label(text=f"≥{scene.qta_min_text_length}字符", icon='INFO')
        
        # 智能过滤选项（折叠面板）
        filter_box = box.box()
        row = filter_box.row()
        
        if scene.qta_extract_source == 'ADDON':
            filter_title = "智能过滤选项"
        else:  # BLEND
            filter_title = "内容类型选择"
            
        row.prop(
            scene, 
            "qta_show_filter_options", 
            text=filter_title, 
            icon="TRIA_DOWN" if scene.qta_show_filter_options else "TRIA_RIGHT", 
            emboss=False
        )
        
        if scene.qta_show_filter_options:
            col = filter_box.column(align=True)
            
            if scene.qta_extract_source == 'ADDON':
                # 插件文本过滤选项
                col.prop(scene, "qta_filter_variables", text="过滤变量名和函数名")
                col.prop(scene, "qta_filter_keywords", text="过滤代码关键字")
                col.prop(scene, "qta_filter_tech_ids", text="过滤技术标识符")
                col.prop(scene, "qta_filter_format_placeholders", text="过滤格式占位符")
                col.prop(scene, "qta_filter_paths_urls", text="过滤路径和URL")
                col.prop(scene, "qta_filter_data_keys", text="过滤数据键名")
                col.prop(scene, "qta_filter_special_chars", text="过滤特殊字符")
                col.prop(scene, "qta_filter_repetitive", text="过滤重复性文本")
            else:  # BLEND
                # Blend文件内容类型选择
                col.label(text="数据块类型:", icon='OUTLINER')
                col.prop(scene, "qta_extract_objects", text="物体名称")
                col.prop(scene, "qta_extract_materials", text="材质名称")
                col.prop(scene, "qta_extract_worlds", text="世界名称")
                col.prop(scene, "qta_extract_collections", text="集合名称")
                col.prop(scene, "qta_extract_textures", text="纹理名称")
                col.prop(scene, "qta_extract_images", text="图像名称")
                col.prop(scene, "qta_extract_node_groups", text="节点组名称")
                
                col.separator()
                col.label(text="节点组接口:", icon='NODETREE')
                col.prop(scene, "qta_extract_node_sockets", text="接口名称")
                col.prop(scene, "qta_extract_node_panels", text="面板名称")
        
        box.operator("qta.extract_text", text="提取文本", icon='LINENUMBERS_ON')
        box.operator("qta.load_po_to_panel", text="加载PO文件", icon='TEXT')

        # --- 词条列表与搜索 ---
        box = layout.box()
        box.prop(scene, "qta_translation_filter", text="", icon='VIEWZOOM')
        box.template_list("QTA_UL_TranslationEntries", "", scene, "qta_translation_entries", scene, "qta_translation_entries_index")

        # --- 列表操作 ---
        row = box.row(align=True)
        row.operator("qta.add_translation_entry", text="添加", icon='ADD')
        remove_op = row.operator("qta.remove_translation_entry", text="移除", icon='REMOVE')
        remove_op.index_to_remove = scene.qta_translation_entries_index if hasattr(remove_op, 'index_to_remove') else 0
        row.operator("qta.replace_in_translations", text="文本替换", icon='SORTALPHA')
        row.operator("qta.deduplicate_against_editor", text="去重", icon='UV_SYNC_SELECT')

        # --- 词条详情编辑 ---
        if scene.qta_translation_entries and scene.qta_translation_entries_index >= 0:
            active_index = scene.qta_translation_entries_index
            if 0 <= active_index < len(scene.qta_translation_entries):
                box = layout.box()
                box.label(text="词条详情:", icon='WORDWRAP_ON')
                item = scene.qta_translation_entries[active_index]
                
                # 显示当前值（只读）
                col = box.column()
                col.label(text=f"原文: {item.source_text}")
                col.label(text=f"译文: {item.translated_text}")
                col.label(text=f"上下文: {item.msgctxt or '无'}")
                
                # 操作按钮行
                row = col.row(align=True)
                row.operator("qta.edit_translation_entry", text="编辑", icon='GREASEPENCIL')
                op = row.operator(QTA_OT_TranslateSingleEntry.bl_idname, text="翻译", icon='WORLD')
                op.source = 'TRANSLATION_PANEL'

        # --- 可折叠的API设置 ---
        settings_box = layout.box()
        row = settings_box.row()
        row.prop(
            scene, 
            "qta_show_api_settings", 
            text="翻译API设置", 
            icon="TRIA_DOWN" if scene.qta_show_api_settings else "TRIA_RIGHT", 
            emboss=False
        )

        if scene.qta_show_api_settings:
            prefs = context.preferences.addons[__package__].preferences
            draw_translation_settings(settings_box, prefs)

        # --- 主要操作按钮 ---
        action_box = layout.box()
        
        # 检查是否有正在进行的翻译
        translation_in_progress = scene.qta_translation_in_progress
        translation_progress = scene.qta_translation_progress
        
        if translation_in_progress:
            # 显示翻译状态
            status_box = action_box.box()
            status_box.label(text="翻译状态:", icon='TIME')
            status_box.label(text=f"正在翻译中... {translation_progress:.1f}%")
            status_box.label(text="按ESC键可取消翻译", icon='INFO')
        else:
            # 正常显示操作按钮
            row = action_box.row(align=True)
            row.operator("qta.auto_translate", icon='TEXT')
            row.operator("qta.export_to_file", icon='EXPORT')
            
            action_box.operator("qta.append_to_editor", icon='ADD')

# -- 注册与注销
def register():
    bpy.utils.register_class(QTA_TranslationEntry)
    bpy.utils.register_class(QTA_UL_TranslationEntries)
    bpy.utils.register_class(QTA_OT_ExtractText)
    bpy.utils.register_class(QTA_OT_AutoTranslate)
    bpy.utils.register_class(QTA_OT_TranslateSingleEntry)
    bpy.utils.register_class(QTA_OT_EditTranslationEntry)
    bpy.utils.register_class(QTA_OT_ExportToFile)
    bpy.utils.register_class(QTA_OT_AppendToEditor)
    bpy.utils.register_class(QTA_OT_AddTranslationEntry)
    bpy.utils.register_class(QTA_OT_RemoveTranslationEntry)
    bpy.utils.register_class(QTA_OT_DeduplicateAgainstEditor)
    bpy.utils.register_class(QTA_OT_ReplaceInTranslations)
    bpy.utils.register_class(QTA_OT_LoadPOToPanel)
    bpy.utils.register_class(QTA_PT_AutoTranslation)
    
    bpy.types.Scene.qta_translation_entries = CollectionProperty(type=QTA_TranslationEntry)
    bpy.types.Scene.qta_translation_entries_index = IntProperty()
    bpy.types.Scene.qta_translation_filter = StringProperty(name="Search", default="")
    bpy.types.Scene.qta_source_directory = StringProperty(
        name="插件源目录",
        description="包含要提取文本的.py文件的插件目录",
        subtype='DIR_PATH',
        default=os.path.join(bpy.utils.resource_path('USER'), "scripts", "addons")
    )
    bpy.types.Scene.qta_source_blend_file = StringProperty(
        name=".blend文件",
        description="要提取文本的.blend文件",
        subtype='FILE_PATH',
        default=""
    )
    bpy.types.Scene.qta_extract_source = EnumProperty(
        name="提取源",
        items=[('ADDON', "插件", "从.py文件提取"), ('BLEND', "Blend文件", "从.blend文件提取")],
        default='ADDON'
    )
    bpy.types.Scene.qta_show_api_settings = BoolProperty(name="显示API设置", default=False)
    bpy.types.Scene.qta_use_current_blend = BoolProperty(
        name="使用当前文件", default=False, description="直接从当前打开的Blend文件提取"
    )
    bpy.types.Scene.qta_translation_in_progress = BoolProperty(
        name="翻译进行中", default=False, description="标记是否有翻译任务正在进行"
    )
    bpy.types.Scene.qta_translation_progress = bpy.props.FloatProperty(
        name="翻译进度", default=0.0, min=0.0, max=100.0, description="当前翻译进度百分比"
    )
    bpy.types.Scene.qta_extract_docstring = bpy.props.BoolProperty(
        name="提取多行注释", default=False, description="是否提取py文件中的多行docstring注释")
    bpy.types.Scene.qta_extract_json = bpy.props.BoolProperty(
        name="提取JSON", default=False, description="是否提取json文件中的字符串内容")
    bpy.types.Scene.qta_json_keys = bpy.props.StringProperty(
        name="JSON提取key（逗号分隔）", default="", description="只提取这些key对应的字符串内容，留空为全部")
    bpy.types.Scene.qta_min_text_length = bpy.props.IntProperty(
        name="最小字符串长度", default=0, min=0, max=1000, description="过滤掉长度小于此值的字符串，0表示不过滤")
    
    # Blend文件提取内容类型选择
    bpy.types.Scene.qta_extract_objects = bpy.props.BoolProperty(
        name="提取物体名称", default=True, description="提取场景中所有物体的名称")
    bpy.types.Scene.qta_extract_materials = bpy.props.BoolProperty(
        name="提取材质名称", default=True, description="提取所有材质的名称")
    bpy.types.Scene.qta_extract_worlds = bpy.props.BoolProperty(
        name="提取世界名称", default=True, description="提取世界环境的名称")
    bpy.types.Scene.qta_extract_collections = bpy.props.BoolProperty(
        name="提取集合名称", default=True, description="提取所有集合的名称")
    bpy.types.Scene.qta_extract_textures = bpy.props.BoolProperty(
        name="提取纹理名称", default=True, description="提取所有纹理的名称")
    bpy.types.Scene.qta_extract_images = bpy.props.BoolProperty(
        name="提取图像名称", default=True, description="提取所有图像的名称")
    bpy.types.Scene.qta_extract_node_groups = bpy.props.BoolProperty(
        name="提取节点组名称", default=True, description="提取所有节点组的名称")
    bpy.types.Scene.qta_extract_node_sockets = bpy.props.BoolProperty(
        name="提取节点接口名称", default=True, description="提取节点组的输入输出接口名称")
    bpy.types.Scene.qta_extract_node_panels = bpy.props.BoolProperty(
        name="提取节点面板名称", default=True, description="提取节点组中的面板名称")
    
    # 智能过滤选项折叠面板
    bpy.types.Scene.qta_show_filter_options = bpy.props.BoolProperty(
        name="显示智能过滤选项", default=False, description="展开/折叠智能过滤选项面板")
    
    # 智能过滤选项
    bpy.types.Scene.qta_filter_variables = bpy.props.BoolProperty(
        name="过滤变量名和函数名", default=True,
        description="过滤普通列表/元组中的变量名、函数名等代码标识符（text=、bl_label= 等界面文本不受影响）")
    bpy.types.Scene.qta_filter_keywords = bpy.props.BoolProperty(
        name="过滤代码关键字", default=True, description="过滤Python关键字和保留字")
    bpy.types.Scene.qta_filter_tech_ids = bpy.props.BoolProperty(
        name="过滤技术标识符", default=True,
        description="过滤普通列表/元组中的bl_idname、正则表达式等技术标识符（界面文本不受影响）")
    bpy.types.Scene.qta_filter_format_placeholders = bpy.props.BoolProperty(
        name="过滤格式占位符", default=True,
        description="仅过滤单独的%s、{0}等纯占位符，保留包含占位符的完整句子")
    bpy.types.Scene.qta_filter_paths_urls = bpy.props.BoolProperty(
        name="过滤路径和URL", default=True, description="过滤文件路径、URL等技术性路径")
    bpy.types.Scene.qta_filter_data_keys = bpy.props.BoolProperty(
        name="过滤数据键名", default=True, description="过滤JSON、XML等数据文件的键名")
    bpy.types.Scene.qta_filter_special_chars = bpy.props.BoolProperty(
        name="过滤特殊字符", default=True,
        description="过滤几乎全是符号的文本，保留含括号、快捷键等正常界面文本")
    bpy.types.Scene.qta_filter_repetitive = bpy.props.BoolProperty(
        name="过滤重复性文本", default=True, description="过滤重复性过高的文本")


def unregister():
    # 定义所有需要取消注册的类
    classes_to_unregister = [
        QTA_PT_AutoTranslation,
        QTA_OT_DeduplicateAgainstEditor,
        QTA_OT_RemoveTranslationEntry,
        QTA_OT_AddTranslationEntry,
        QTA_OT_AppendToEditor,
        QTA_OT_ExportToFile,
        QTA_OT_EditTranslationEntry,
        QTA_OT_TranslateSingleEntry,
        QTA_OT_AutoTranslate,
        QTA_OT_ExtractText,
        QTA_OT_ReplaceInTranslations,
        QTA_OT_LoadPOToPanel,
        QTA_UL_TranslationEntries,
        QTA_TranslationEntry,
    ]
    
    # 安全地取消注册所有类
    for cls in classes_to_unregister:
        try:
            bpy.utils.unregister_class(cls)
        except (ValueError, RuntimeError) as e:
            # 如果类未注册或已经取消注册，忽略错误
            print(f"Warning: Could not unregister class {cls.__name__}: {e}")
            pass

    del bpy.types.Scene.qta_show_api_settings
    del bpy.types.Scene.qta_extract_source
    del bpy.types.Scene.qta_source_blend_file
    del bpy.types.Scene.qta_source_directory
    del bpy.types.Scene.qta_translation_filter
    del bpy.types.Scene.qta_translation_entries_index
    del bpy.types.Scene.qta_translation_entries
    del bpy.types.Scene.qta_use_current_blend 
    del bpy.types.Scene.qta_translation_in_progress
    del bpy.types.Scene.qta_translation_progress 
    del bpy.types.Scene.qta_extract_docstring 
    del bpy.types.Scene.qta_extract_json 
    del bpy.types.Scene.qta_json_keys
    del bpy.types.Scene.qta_min_text_length
    
    # 删除Blend文件提取内容类型选择
    del bpy.types.Scene.qta_extract_objects
    del bpy.types.Scene.qta_extract_materials
    del bpy.types.Scene.qta_extract_worlds
    del bpy.types.Scene.qta_extract_collections
    del bpy.types.Scene.qta_extract_textures
    del bpy.types.Scene.qta_extract_images
    del bpy.types.Scene.qta_extract_node_groups
    del bpy.types.Scene.qta_extract_node_sockets
    del bpy.types.Scene.qta_extract_node_panels
    
    # 删除智能过滤选项折叠面板
    del bpy.types.Scene.qta_show_filter_options
    
    # 删除智能过滤选项
    del bpy.types.Scene.qta_filter_variables
    del bpy.types.Scene.qta_filter_keywords
    del bpy.types.Scene.qta_filter_tech_ids
    del bpy.types.Scene.qta_filter_format_placeholders
    del bpy.types.Scene.qta_filter_paths_urls
    del bpy.types.Scene.qta_filter_data_keys
    del bpy.types.Scene.qta_filter_special_chars
    del bpy.types.Scene.qta_filter_repetitive 