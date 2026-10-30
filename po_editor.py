# -*- coding: utf-8 -*-
"""
PO文件编辑器模块
"""

import bpy
import os
import json
import shutil
import threading
import time
from bpy.props import (
    StringProperty,
    IntProperty,
    BoolProperty,
    CollectionProperty,
    PointerProperty,
    EnumProperty,
)
from bpy.types import Panel, Operator, UIList, PropertyGroup

from . import polib
from .utils import MSGCTXT_ITEMS, find_po_entry
from .translation_panel import QTA_OT_TranslateSingleEntry
from .global_translation_panel import get_blender_datafiles_dir
from . import builtin_msgfmt

# -- 通用数据
MSGCTXT_ITEMS = [
    ('', "无 (None)", "清除上下文"),
    ('Operator', "Operator", "用于操作的名称"),
    ('Tooltip', "Tooltip", "用于鼠标悬停时的工具提示"),
    ('Panel', "Panel", "用于面板的标题"),
    ('Menu', "Menu", "用于菜单项"),
    ('Property', "Property", "用于属性的标签"),
    ('Node', "Node", "用于节点编辑器中的节点名称/标签"),
]

# -- 辅助函数
def add_entry_update(self, context):
    """"添加词条"对话框中属性的更新回调函数"""
    self.info_message = ""
    if self.msgid:
        existing_index = find_po_entry(context.scene.qta_po_entries, self.msgid, self.msgctxt)
        if existing_index != -1:
            self.info_message = "警告: 词条已存在，将被覆盖！"

def update_entry_msgctxt_preset(self, context):
    """当从预设中选择一个上下文时，更新编辑中词条的msgctxt"""
    self.msgctxt = self.msgctxt_preset

def update_save_filepath(self, context):
    """当导出格式改变时，动态更新保存文件对话框中的文件名后缀"""
    if self.filepath:
        base_path, _ = os.path.splitext(self.filepath)
        if self.export_format == 'PO':
            self.filepath = base_path + '.po'
        else: # MO
            self.filepath = base_path + '.mo'

# -- 数据结构
class QTA_POEntry(PropertyGroup):
    """用于在UI列表中显示的PO词条"""
    msgid: StringProperty(name="原文 (msgid)")
    msgstr: StringProperty(name="译文 (msgstr)")
    msgctxt: StringProperty(name="上下文 (msgctxt)")
    msgctxt_preset: EnumProperty(
        name="上下文预设",
        items=MSGCTXT_ITEMS,
        description="从预设中选择一个上下文",
        update=update_entry_msgctxt_preset
    )
    export_format: EnumProperty(
        name="导出格式",
        items=[('PO', ".po", "可编辑的文本格式"), ('MO', ".mo", "编译后的二进制格式")],
        default='PO',
        update=update_save_filepath
    )

# -- UIList
class QTA_UL_POEntries(UIList):
    """PO词条的UIList"""
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        # 我们需要用一种方式来显示列表项
        # item是PropertyGroup的实例
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            row = layout.row()
            row.prop(item, "msgid", text="", emboss=False)
            row.prop(item, "msgstr", text="", emboss=False)
        elif self.layout_type in {'GRID'}:
            layout.alignment = 'CENTER'
            layout.label(text="", icon_value=icon)

    def filter_items(self, context, data, propname):
        """根据搜索字符串过滤项目"""
        entries = getattr(data, propname)
        search_term = context.scene.qta_po_search.lower()

        # 返回值是过滤器标志列表和新顺序列表。
        # 我们只进行过滤，不重新排序，所以第二个列表为空。
        flt_flags = []
        flt_neworder = []

        if search_term:
            # 创建一个过滤标志列表
            for entry in entries:
                if search_term in entry.msgid.lower() or search_term in entry.msgstr.lower():
                    flt_flags.append(self.bitflag_filter_item)
                else:
                    flt_flags.append(0)  # 隐藏
        else:
            # 没有过滤器，全部显示
            flt_flags = [self.bitflag_filter_item] * len(entries)

        return flt_flags, flt_neworder

# -- 操作符 (Operators)
class QTA_OT_LoadPOFile(Operator):
    """从文件加载PO词条"""
    bl_idname = "qta.load_po_file"
    bl_label = "加载PO文件"
    bl_description = "加载一个PO文件进行编辑"

    filepath: StringProperty(subtype="FILE_PATH")
    filter_glob: StringProperty(default="*.po;*.pot", options={'HIDDEN'})

    def execute(self, context):
        scene = context.scene
        
        # 清空现有词条
        scene.qta_po_entries.clear()
        
        # 加载文件
        try:
            po = polib.pofile(self.filepath)
            scene.qta_po_filepath = self.filepath
        except Exception as e:
            self.report({'ERROR'}, f"无法加载或解析文件: {e}")
            return {'CANCELLED'}

        # 填充集合
        for entry in po:
            new_item = scene.qta_po_entries.add()
            new_item.msgid = entry.msgid
            new_item.msgstr = entry.msgstr
            new_item.msgctxt = entry.msgctxt if entry.msgctxt is not None else ""
        
        scene.qta_po_header = po.header
        scene.qta_po_metadata_json = json.dumps(po.metadata)
        
        self.report({'INFO'}, f"成功加载 {len(scene.qta_po_entries)} 个词条")
        return {'FINISHED'}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

class QTA_OT_SavePOFile(Operator):
    """保存当前词条到PO或MO文件"""
    bl_idname = "qta.save_po_file"
    bl_label = "保存为..."
    bl_description = "将所有更改保存到PO或MO文件"
    bl_options = {'REGISTER', 'UNDO'}

    filepath: StringProperty(
        subtype="FILE_PATH",
        name="文件路径",
    )
    
    export_format: EnumProperty(
        name="导出格式",
        items=[('PO', ".po", "可编辑的文本格式"), ('MO', ".mo", "编译后的二进制格式")],
        default='PO',
        update=update_save_filepath
    )
    
    use_msgfmt: BoolProperty(
        name="使用msgfmt（更快）",
        description="使用内置msgfmt工具编译MO文件，比polib更快",
        default=True
    )

    @classmethod
    def poll(cls, context):
        return context.scene.qta_po_filepath != ""

    def execute(self, context):
        scene = context.scene
        
        if not self.filepath:
            self.report({'ERROR'}, "请指定文件路径")
            return {'CANCELLED'}

        # 确保文件路径有正确的扩展名(最终确认)
        base_path, _ = os.path.splitext(self.filepath)
        if self.export_format == 'PO':
            final_filepath = base_path + '.po'
        else: # MO
            final_filepath = base_path + '.mo'

        # 通过设置wrapwidth=0来禁用自动换行，以保持多行字符串的一致性
        po = polib.POFile(wrapwidth=0)
        po.header = scene.qta_po_header
        if scene.qta_po_metadata_json:
            po.metadata = json.loads(scene.qta_po_metadata_json)
        
        for item in scene.qta_po_entries:
            entry = polib.POEntry(
                msgid=item.msgid,
                msgstr=item.msgstr,
                msgctxt=item.msgctxt or None,
            )
            po.append(entry)
            
        try:
            if self.export_format == 'PO':
                po.save(final_filepath)
                # 如果保存的是当前打开的文件，则更新路径
                if os.path.normcase(final_filepath) == os.path.normcase(context.scene.qta_po_filepath):
                    context.scene.qta_po_filepath = final_filepath
                self.report({'INFO'}, f"PO文件已保存: {final_filepath}")
            else: # MO
                # 根据用户选择使用msgfmt或polib
                if self.use_msgfmt and builtin_msgfmt.is_msgfmt_available():
                    try:
                        # 先保存PO文件到临时位置
                        temp_po_path = final_filepath.replace('.mo', '_temp.po')
                        po.save(temp_po_path)
                        
                        # 使用msgfmt编译
                        builtin_msgfmt.convert_with_msgfmt(temp_po_path, final_filepath, 'PO_TO_MO')
                        
                        # 删除临时PO文件
                        if os.path.exists(temp_po_path):
                            os.remove(temp_po_path)
                        
                        msgfmt_info = builtin_msgfmt.get_msgfmt_info()
                        tool_type = msgfmt_info['type']
                        self.report({'INFO'}, f"使用{tool_type}msgfmt成功编译MO文件: {final_filepath}")
                    except Exception as e:
                        self.report({'WARNING'}, f"msgfmt编译失败，回退到polib: {str(e)}")
                        # 使用多线程编译MO文件（polib方式）
                        self.compile_mo_file(po, final_filepath, context)
                        return {'RUNNING_MODAL'}
                else:
                    # 使用多线程编译MO文件（polib方式）
                    self.compile_mo_file(po, final_filepath, context)
                    return {'RUNNING_MODAL'}
        except Exception as e:
            self.report({'ERROR'}, f"保存文件失败: {e}")
            return {'CANCELLED'}
        
        return {'FINISHED'}

    def compile_mo_file(self, po_file, output_path, context):
        """使用多线程编译MO文件"""
        # 设置编译状态
        context.scene.qta_mo_compile_in_progress = True
        context.scene.qta_mo_compile_progress = 0.0
        
        # 创建编译线程
        self.compile_thread = MOCompileThread(po_file, output_path)
        self.compile_thread.start()
        
        # 启动进度检查定时器
        bpy.app.timers.register(self.check_compile_progress)
        
        # 启动UI刷新定时器
        bpy.app.timers.register(self._ui_refresh_timer)
        
        # 如果保存的是当前打开的文件，则更新路径
        if os.path.normcase(output_path.replace('.mo', '.po')) == os.path.normcase(context.scene.qta_po_filepath):
            context.scene.qta_po_filepath = output_path.replace('.mo', '.po')

    def check_compile_progress(self):
        """检查MO编译进度"""
        if not hasattr(self, 'compile_thread') or not self.compile_thread.is_alive():
            # 编译已完成
            if hasattr(self, 'compile_thread'):
                with self.compile_thread.lock:
                    if self.compile_thread.completed:
                        # 清理状态
                        bpy.context.scene.qta_mo_compile_in_progress = False
                        bpy.context.scene.qta_mo_compile_progress = 0.0
                        
                        if self.compile_thread.error:
                            self.report({'ERROR'}, self.compile_thread.error)
                        else:
                            self.report({'INFO'}, f"MO文件编译完成: {self.compile_thread.output_path}")
                        
                        # 强制刷新UI
                        self._force_ui_refresh()
                        return None  # 停止定时器
            return None  # 停止定时器
        
        # 更新进度
        with self.compile_thread.lock:
            progress = self.compile_thread.progress
        
        # 更新场景中的编译进度
        bpy.context.scene.qta_mo_compile_progress = progress
        
        # 强制刷新UI
        self._force_ui_refresh()
        
        return 0.1  # 每0.1秒检查一次

    def _ui_refresh_timer(self):
        """UI刷新定时器，确保面板实时更新"""
        if hasattr(self, 'compile_thread') and self.compile_thread.is_alive():
            # 只刷新3D视图区域，因为我们的面板在那里
            for window in bpy.context.window_manager.windows:
                for area in window.screen.areas:
                    if area.type == 'VIEW_3D':
                        area.tag_redraw()
            return 0.15  # 每0.15秒刷新一次UI，更流畅
        return None  # 停止定时器

    def modal(self, context, event):
        """模态操作处理"""
        if event.type == 'ESC':
            # 用户取消编译
            if hasattr(self, 'compile_thread') and self.compile_thread.is_alive():
                self.compile_thread.join(timeout=1.0)
            
            # 清除编译状态
            context.scene.qta_mo_compile_in_progress = False
            context.scene.qta_mo_compile_progress = 0.0
            
            # 强制刷新UI
            self._force_ui_refresh()
            
            self.report({'INFO'}, "MO编译已取消")
            return {'CANCELLED'}
        
        return {'PASS_THROUGH'}

    def cancel(self, context):
        """取消操作时的清理"""
        if hasattr(self, 'compile_thread') and self.compile_thread.is_alive():
            self.compile_thread.join(timeout=1.0)
        
        # 清除编译状态
        context.scene.qta_mo_compile_in_progress = False
        context.scene.qta_mo_compile_progress = 0.0
        
        # 强制刷新UI
        self._force_ui_refresh()

    def _force_ui_refresh(self):
        """强制刷新UI"""
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == 'VIEW_3D':
                    area.tag_redraw()

    def invoke(self, context, event):
        # 默认保存路径为当前打开的文件路径
        self.filepath = context.scene.qta_po_filepath
        # 初始调用时也确保后缀正确
        self.update(context)
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "export_format", expand=True)
        layout.prop(self, "filepath")
        
        # 添加msgfmt选项（仅对MO格式显示）
        if self.export_format == 'MO':
            msgfmt_info = builtin_msgfmt.get_msgfmt_info()
            row = layout.row()
            row.prop(self, "use_msgfmt", text="使用msgfmt（更快）")
            
            if not msgfmt_info['available']:
                row.label(text="⚠️ msgfmt未找到", icon='ERROR')
                row.operator("qta.install_msgfmt_help", text="", icon='HELP')
            else:
                # 显示工具类型
                tool_type = msgfmt_info['type']
                if tool_type == 'builtin':
                    row.label(text="✓ 内置工具", icon='CHECKMARK')
                else:
                    row.label(text="✓ 系统工具", icon='CHECKMARK')

    def update(self, context):
        """手动调用更新函数"""
        update_save_filepath(self, context)

class QTA_OT_MergePOFile(Operator):
    """从另一个PO文件合并词条"""
    bl_idname = "qta.merge_po_file"
    bl_label = "合并PO文件"
    bl_description = "从另一个PO文件加载词条，并合并到当前编辑器中"
    bl_options = {'REGISTER', 'UNDO'}

    filepath: StringProperty(
        name="要合并的文件",
        subtype="FILE_PATH",
    )
    filter_glob: StringProperty(default="*.po;*.pot", options={'HIDDEN'})
    
    merge_mode: EnumProperty(
        name="合并模式",
        description="当词条已存在时如何处理",
        items=[
            ('OVERWRITE', "覆盖", "用新文件中的译文覆盖现有译文"),
            ('IGNORE', "忽略", "保留现有译文，不作任何更改"),
        ],
        default='OVERWRITE'
    )

    @classmethod
    def poll(cls, context):
        return context.scene.qta_po_filepath != ""

    def execute(self, context):
        scene = context.scene
        
        if not self.filepath:
            self.report({'ERROR'}, "未选择要合并的文件")
            return {'CANCELLED'}

        try:
            merge_po = polib.pofile(self.filepath)
        except Exception as e:
            self.report({'ERROR'}, f"无法加载或解析要合并的文件: {e}")
            return {'CANCELLED'}

        # 创建现有词条的字典索引，优化查找性能
        existing_entries = {}
        for i, entry in enumerate(scene.qta_po_entries):
            key = (entry.msgctxt or "", entry.msgid)
            existing_entries[key] = i

        added_count = 0
        updated_count = 0

        for entry in merge_po:
            key = (entry.msgctxt or "", entry.msgid)
            
            if key in existing_entries:
                # 词条已存在
                if self.merge_mode == 'OVERWRITE':
                    # 更新译文
                    existing_index = existing_entries[key]
                    existing_entry = scene.qta_po_entries[existing_index]
                    existing_entry.msgstr = entry.msgstr
                    updated_count += 1
                else: # IGNORE
                    pass # 什么都不做
            else:
                # 词条不存在，添加新词条
                new_item = scene.qta_po_entries.add()
                new_item.msgid = entry.msgid
                new_item.msgstr = entry.msgstr
                new_item.msgctxt = entry.msgctxt if entry.msgctxt is not None else ""
                added_count += 1
        
        self.report({'INFO'}, f"合并完成: 新增 {added_count} 个词条, 更新 {updated_count} 个词条")
        return {'FINISHED'}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=400)
    
    def draw(self, context):
        layout = self.layout
        layout.prop(self, "filepath")
        layout.prop(self, "merge_mode")

class QTA_OT_AddPOEntry(Operator):
    """通过对话框添加或替换一个词条"""
    bl_idname = "qta.add_po_entry"
    bl_label = "添加翻译词条"
    bl_options = {'REGISTER', 'UNDO'}

    msgid: StringProperty(name="原文 (msgid)", update=add_entry_update)
    msgstr: StringProperty(name="译文 (msgstr)")
    msgctxt: StringProperty(name="上下文 (msgctxt)", update=add_entry_update)
    msgctxt_preset: EnumProperty(
        name="上下文预设",
        items=MSGCTXT_ITEMS,
        description="从预设中选择一个上下文",
        update=lambda self, context: setattr(self, 'msgctxt', self.msgctxt_preset)
    )
    
    info_message: StringProperty(name="", default="")

    @classmethod
    def poll(cls, context):
        return context.scene.qta_po_filepath != ""

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=400)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "msgid")
        layout.prop(self, "msgstr")
        
        col = layout.column()
        col.prop(self, "msgctxt")
        col.prop(self, "msgctxt_preset", text="预设")
        
        if self.info_message:
            row = layout.row(align=True)
            row.alert = True
            row.label(text=self.info_message, icon='ERROR')

    def execute(self, context):
        scene = context.scene
        
        if not self.msgid:
            self.report({'ERROR'}, "原文(msgid)不能为空")
            return {'CANCELLED'}
        
        existing_index = find_po_entry(scene.qta_po_entries, self.msgid, self.msgctxt)
            
        if existing_index != -1:
            # 替换现有词条
            entry_to_replace = scene.qta_po_entries[existing_index]
            entry_to_replace.msgstr = self.msgstr
            scene.qta_po_entries_index = existing_index
            self.report({'INFO'}, f"词条已在索引 {existing_index} 处被替换")
        else:
            # 添加为新词条
            new_item = scene.qta_po_entries.add()
            new_item.msgid = self.msgid
            new_item.msgstr = self.msgstr
            new_item.msgctxt = self.msgctxt
            scene.qta_po_entries_index = len(scene.qta_po_entries) - 1
            self.report({'INFO'}, "已添加新词条")
            
        return {'FINISHED'}

class QTA_OT_RemovePOEntry(Operator):
    """通过确认对话框移除选中的词条"""
    bl_idname = "qta.remove_po_entry"
    bl_label = "移除词条"
    bl_options = {'REGISTER', 'UNDO'}

    index_to_remove: IntProperty(name="要移除的索引", options={'HIDDEN'})

    @classmethod
    def poll(cls, context):
        return context.scene.qta_po_entries_index >= 0 and len(context.scene.qta_po_entries) > 0

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        scene = context.scene
        
        # 安全地获取要移除的索引
        index = self.index_to_remove
        if index < 0 or index >= len(scene.qta_po_entries):
            self.report({'ERROR'}, "无效的索引，无法移除")
            return {'CANCELLED'}
            
        scene.qta_po_entries.remove(index)
        
        # 安全地更新活动索引
        if len(scene.qta_po_entries) > 0:
            scene.qta_po_entries_index = min(max(0, index - 1), len(scene.qta_po_entries) - 1)
        else:
            scene.qta_po_entries_index = 0
            
        return {'FINISHED'}

class QTA_OT_EditPOEntry(Operator):
    """通过对话框编辑选中的PO词条"""
    bl_idname = "qta.edit_po_entry"
    bl_label = "编辑词条"
    bl_options = {'REGISTER', 'UNDO'}

    msgid: StringProperty(name="原文 (msgid)")
    msgstr: StringProperty(name="译文 (msgstr)")
    msgctxt: StringProperty(name="上下文 (msgctxt)")
    msgctxt_preset: EnumProperty(
        name="上下文预设",
        items=MSGCTXT_ITEMS,
        description="从预设中选择一个上下文",
        update=lambda self, context: setattr(self, 'msgctxt', self.msgctxt_preset)
    )

    @classmethod
    def poll(cls, context):
        return (context.scene.qta_po_filepath != "" and 
                context.scene.qta_po_entries and 
                context.scene.qta_po_entries_index >= 0)

    def invoke(self, context, event):
        scene = context.scene
        active_entry = scene.qta_po_entries[scene.qta_po_entries_index]
        
        # 预填充当前值
        self.msgid = active_entry.msgid
        self.msgstr = active_entry.msgstr
        self.msgctxt = active_entry.msgctxt
        
        return context.window_manager.invoke_props_dialog(self, width=400)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "msgid")
        layout.prop(self, "msgstr")
        
        col = layout.column()
        col.prop(self, "msgctxt")
        col.prop(self, "msgctxt_preset", text="预设")

    def execute(self, context):
        scene = context.scene
        active_entry = scene.qta_po_entries[scene.qta_po_entries_index]
        
        if not self.msgid:
            self.report({'ERROR'}, "原文(msgid)不能为空")
            return {'CANCELLED'}
        
        # 更新词条
        active_entry.msgid = self.msgid
        active_entry.msgstr = self.msgstr
        active_entry.msgctxt = self.msgctxt
        
        self.report({'INFO'}, "词条已更新")
        return {'FINISHED'}

class QTA_OT_ReplaceGlobalDict(Operator):
    bl_idname = "qta.replace_global_dict"
    bl_label = "替换全局词典"
    bl_description = "将当前blender.po编译为blender.mo并替换到全局简体中文词典目录"
    
    use_msgfmt: BoolProperty(
        name="使用msgfmt（更快）",
        description="使用内置msgfmt工具编译MO文件，比polib更快",
        default=True
    )

    def execute(self, context):
        scene = context.scene
        po_path = scene.qta_po_filepath
        if not po_path or not os.path.basename(po_path).lower() == "blender.po":
            self.report({'ERROR'}, "仅支持blender.po文件")
            return {'CANCELLED'}
        
        # 目标目录
        target_dir = os.path.join(get_blender_datafiles_dir(), "locale", "zh_HANS", "LC_MESSAGES")
        
        # 根据用户选择使用msgfmt或polib
        if self.use_msgfmt and builtin_msgfmt.is_msgfmt_available():
            try:
                # 使用msgfmt直接编译
                mo_path = os.path.splitext(po_path)[0] + ".mo"
                builtin_msgfmt.convert_with_msgfmt(po_path, mo_path, 'PO_TO_MO')
                
                # 复制到目标目录
                if not os.path.exists(target_dir):
                    os.makedirs(target_dir, exist_ok=True)
                target_file = os.path.join(target_dir, "blender.mo")
                shutil.copyfile(mo_path, target_file)
                
                msgfmt_info = builtin_msgfmt.get_msgfmt_info()
                tool_type = msgfmt_info['type']
                self.report({'INFO'}, f"使用{tool_type}msgfmt成功替换全局词典")
                
                # 弹窗提示
                bpy.ops.qta.global_translation_popup('INVOKE_DEFAULT', enable=True)
                return {'FINISHED'}
            except Exception as e:
                self.report({'WARNING'}, f"msgfmt编译失败，回退到polib: {str(e)}")
                # 使用多线程处理全局词典替换（polib方式）
                self.replace_global_dict(po_path, target_dir, context)
                return {'RUNNING_MODAL'}
        else:
            # 使用多线程处理全局词典替换（polib方式）
            self.replace_global_dict(po_path, target_dir, context)
            return {'RUNNING_MODAL'}

    def replace_global_dict(self, po_path, target_dir, context):
        """使用多线程处理全局词典替换"""
        # 设置替换状态
        context.scene.qta_global_dict_replace_in_progress = True
        context.scene.qta_global_dict_replace_progress = 0.0
        
        # 创建替换线程
        self.replace_thread = GlobalDictReplaceThread(po_path, target_dir)
        self.replace_thread.start()
        
        # 启动进度检查定时器
        bpy.app.timers.register(self.check_replace_progress)
        
        # 启动UI刷新定时器
        bpy.app.timers.register(self._ui_refresh_timer)

    def check_replace_progress(self):
        """检查全局词典替换进度"""
        if not hasattr(self, 'replace_thread') or not self.replace_thread.is_alive():
            # 替换已完成
            if hasattr(self, 'replace_thread'):
                with self.replace_thread.lock:
                    if self.replace_thread.completed:
                        # 清理状态
                        bpy.context.scene.qta_global_dict_replace_in_progress = False
                        bpy.context.scene.qta_global_dict_replace_progress = 0.0
                        
                        if self.replace_thread.error:
                            self.report({'ERROR'}, self.replace_thread.error)
                        else:
                            self.report({'INFO'}, "全局词典替换完成")
                            # 弹窗提示
                            bpy.ops.qta.global_translation_popup('INVOKE_DEFAULT', enable=True)
                        
                        # 强制刷新UI
                        self._force_ui_refresh()
                        return None  # 停止定时器
            return None  # 停止定时器
        
        # 更新进度
        with self.replace_thread.lock:
            progress = self.replace_thread.progress
        
        # 更新场景中的替换进度
        bpy.context.scene.qta_global_dict_replace_progress = progress
        
        # 强制刷新UI
        self._force_ui_refresh()
        
        return 0.1  # 每0.1秒检查一次

    def _ui_refresh_timer(self):
        """UI刷新定时器，确保面板实时更新"""
        if hasattr(self, 'replace_thread') and self.replace_thread.is_alive():
            # 只刷新3D视图区域，因为我们的面板在那里
            for window in bpy.context.window_manager.windows:
                for area in window.screen.areas:
                    if area.type == 'VIEW_3D':
                        area.tag_redraw()
            return 0.15  # 每0.15秒刷新一次UI
        return None  # 停止定时器

    def modal(self, context, event):
        """模态操作处理"""
        if event.type == 'ESC':
            # 用户取消替换
            if hasattr(self, 'replace_thread') and self.replace_thread.is_alive():
                self.replace_thread.join(timeout=1.0)
            
            # 清除替换状态
            context.scene.qta_global_dict_replace_in_progress = False
            context.scene.qta_global_dict_replace_progress = 0.0
            
            # 强制刷新UI
            self._force_ui_refresh()
            
            self.report({'INFO'}, "全局词典替换已取消")
            return {'CANCELLED'}
        
        return {'PASS_THROUGH'}

    def cancel(self, context):
        """取消操作时的清理"""
        if hasattr(self, 'replace_thread') and self.replace_thread.is_alive():
            self.replace_thread.join(timeout=1.0)
        
        # 清除替换状态
        context.scene.qta_global_dict_replace_in_progress = False
        context.scene.qta_global_dict_replace_progress = 0.0
        
        # 强制刷新UI
        self._force_ui_refresh()

    def _force_ui_refresh(self):
        """强制刷新UI"""
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == 'VIEW_3D':
                    area.tag_redraw()

class QTA_OT_InstallMsgfmtHelp(Operator):
    """显示如何安装msgfmt的帮助信息"""
    bl_idname = "qta.install_msgfmt_help"
    bl_label = "安装msgfmt帮助"
    bl_description = "显示如何安装msgfmt工具"
    
    def execute(self, context):
        import platform
        current_platform = platform.system().lower()
        
        if current_platform == 'windows':
            help_text = (
                "在Windows上安装msgfmt:\n\n"
                "1. 下载gettext工具包:\n"
                "   - 访问: https://mlocati.github.io/articles/gettext-icon-windows.html\n"
                "   - 或使用Chocolatey: choco install gettext\n"
                "   - 或使用Scoop: scoop install gettext\n\n"
                "2. 安装后确保gettext/bin目录在系统PATH中\n\n"
                "3. 重启Blender后即可使用msgfmt功能"
            )
        elif current_platform == 'darwin':  # macOS
            help_text = (
                "在macOS上安装msgfmt:\n\n"
                "1. 使用Homebrew安装:\n"
                "   brew install gettext\n\n"
                "2. 确保gettext在PATH中:\n"
                "   export PATH=\"/usr/local/opt/gettext/bin:$PATH\"\n\n"
                "3. 重启Blender后即可使用msgfmt功能"
            )
        else:  # Linux
            help_text = (
                "在Linux上安装msgfmt:\n\n"
                "Ubuntu/Debian:\n"
                "   sudo apt-get install gettext\n\n"
                "CentOS/RHEL:\n"
                "   sudo yum install gettext\n\n"
                "Arch Linux:\n"
                "   sudo pacman -S gettext\n\n"
                "安装后重启Blender即可使用msgfmt功能"
            )
        
        # 显示帮助信息
        bpy.ops.ui.popup('INVOKE_DEFAULT', message=help_text, title="msgfmt安装帮助")
        return {'FINISHED'}

class QTA_OT_POReplaceInTranslations(Operator):
    bl_idname = "qta.po_replace_in_translations"
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
        for entry in scene.qta_po_entries:
            if self.find_text and self.find_text in entry.msgstr:
                entry.msgstr = entry.msgstr.replace(self.find_text, self.replace_text)
                count += 1
        self.report({'INFO'}, f"已替换 {count} 处")
        return {'FINISHED'}

# -- 主面板
class QTA_PT_POEditor(Panel):
    """PO文件编辑器面板"""
    bl_label = "PO文件编辑器"
    bl_idname = "QTA_PT_POEditor"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "翻译助手"


    def draw(self, context):
        layout = self.layout
        scene = context.scene

        # --- 文件操作 ---
        box = layout.box()
        row = box.row(align=True)
        row.operator("qta.load_po_file", text="加载 PO 文件", icon='TEXT')
        row.operator("qta.save_po_file", text="保存为...", icon='FILE_TICK')
        # 新增：仅blender.po时显示替换全局词典按钮
        if scene.qta_po_filepath and os.path.basename(scene.qta_po_filepath).lower() == "blender.po":
            box.operator("qta.replace_global_dict", icon='FILE_REFRESH')
        
        if scene.qta_po_filepath:
            box.label(text=f"当前文件: {os.path.basename(scene.qta_po_filepath)} ({len(scene.qta_po_entries)}条)", icon='FILE_TEXT')
        
        # --- MO编译状态显示 ---
        if scene.qta_mo_compile_in_progress:
            compile_box = layout.box()
            compile_box.label(text="MO编译状态:", icon='TIME')
            compile_box.label(text=f"正在编译MO文件... {scene.qta_mo_compile_progress:.1f}%")
            compile_box.label(text="按ESC键可取消编译", icon='INFO')
        
        # --- 全局词典替换状态显示 ---
        if scene.qta_global_dict_replace_in_progress:
            replace_box = layout.box()
            replace_box.label(text="全局词典替换状态:", icon='TIME')
            replace_box.label(text=f"正在替换全局词典... {scene.qta_global_dict_replace_progress:.1f}%")
            replace_box.label(text="按ESC键可取消替换", icon='INFO')
        
        # --- 词条列表与搜索 ---
        box = layout.box()
        box.prop(scene, "qta_po_search", text="", icon='VIEWZOOM')
        box.template_list("QTA_UL_POEntries", "", scene, "qta_po_entries", scene, "qta_po_entries_index")

        # --- 列表操作 ---
        row = box.row(align=True)
        row.operator("qta.add_po_entry", text="添加", icon='ADD')
        
        remove_op = row.operator("qta.remove_po_entry", text="移除", icon='REMOVE')
        remove_op.index_to_remove = scene.qta_po_entries_index
        row.operator("qta.po_replace_in_translations", text="文本替换", icon='SORTALPHA')
        row.operator("qta.merge_po_file", text="合并", icon='AREA_JOIN_UP')


        # --- 词条详情编辑 ---
        if scene.qta_po_filepath and scene.qta_po_entries and scene.qta_po_entries_index >= 0:
            active_index = scene.qta_po_entries_index
            box = layout.box()
            box.label(text="词条详情:", icon='WORDWRAP_ON')
            
            item = scene.qta_po_entries[active_index]
            
            # 显示当前值（只读）
            col = box.column()
            col.label(text=f"原文: {item.msgid}")
            col.label(text=f"译文: {item.msgstr}")
            col.label(text=f"上下文: {item.msgctxt or '无'}")
            
            # 操作按钮行
            row = col.row(align=True)
            row.operator("qta.edit_po_entry", text="编辑", icon='GREASEPENCIL')
            op = row.operator(QTA_OT_TranslateSingleEntry.bl_idname, text="翻译", icon='WORLD')
            op.source = 'PO_EDITOR'

    def draw_header(self, context):
        layout = self.layout

# -- 注册
classes = (
    QTA_POEntry,
    QTA_UL_POEntries,
    QTA_OT_LoadPOFile,
    QTA_OT_SavePOFile,
    QTA_OT_MergePOFile,
    QTA_OT_AddPOEntry,
    QTA_OT_RemovePOEntry,
    QTA_OT_EditPOEntry,
    QTA_OT_ReplaceGlobalDict,
    QTA_OT_InstallMsgfmtHelp,
    QTA_OT_POReplaceInTranslations,
    QTA_PT_POEditor,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    
    # 场景属性
    bpy.types.Scene.qta_po_entries = CollectionProperty(type=QTA_POEntry)
    bpy.types.Scene.qta_po_entries_index = IntProperty(name="选中词条索引", default=0)
    bpy.types.Scene.qta_po_filepath = StringProperty(name="PO文件路径", subtype='FILE_PATH')
    bpy.types.Scene.qta_po_search = StringProperty(
        name="搜索",
        description="用于过滤PO词条列表"
    )
    
    # 用于存储非词条数据
    bpy.types.Scene.qta_po_header = StringProperty(name="PO Header")
    bpy.types.Scene.qta_po_metadata_json = StringProperty(name="PO Metadata JSON")
    
    # MO编译状态属性
    bpy.types.Scene.qta_mo_compile_in_progress = BoolProperty(
        name="MO编译进行中", default=False, description="标记是否有MO编译任务正在进行"
    )
    bpy.types.Scene.qta_mo_compile_progress = bpy.props.FloatProperty(
        name="MO编译进度", default=0.0, min=0.0, max=100.0, description="当前MO编译进度百分比"
    )
    
    # 全局词典替换状态属性
    bpy.types.Scene.qta_global_dict_replace_in_progress = BoolProperty(
        name="全局词典替换进行中", default=False, description="标记是否有全局词典替换任务正在进行"
    )
    bpy.types.Scene.qta_global_dict_replace_progress = bpy.props.FloatProperty(
        name="全局词典替换进度", default=0.0, min=0.0, max=100.0, description="当前全局词典替换进度百分比"
    )


def unregister():
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except (ValueError, RuntimeError) as e:
            # 如果类未注册或已经取消注册，忽略错误
            print(f"Warning: Could not unregister class {cls.__name__}: {e}")
            pass
    
    # 删除场景属性
    del bpy.types.Scene.qta_po_metadata_json
    del bpy.types.Scene.qta_po_header
    del bpy.types.Scene.qta_po_search
    del bpy.types.Scene.qta_po_filepath
    del bpy.types.Scene.qta_po_entries_index
    del bpy.types.Scene.qta_po_entries
    del bpy.types.Scene.qta_mo_compile_progress
    del bpy.types.Scene.qta_mo_compile_in_progress
    del bpy.types.Scene.qta_global_dict_replace_progress
    del bpy.types.Scene.qta_global_dict_replace_in_progress

# 添加MO编译线程类
class MOCompileThread(threading.Thread):
    def __init__(self, po_file, output_path):
        super().__init__()
        self.po_file = po_file
        self.output_path = output_path
        self.progress = 0.0
        self.completed = False
        self.error = None
        self.lock = threading.Lock()
        self.daemon = True

    def run(self):
        try:
            # 第一步：验证PO文件结构 (10%)
            with self.lock:
                self.progress = 10.0
            time.sleep(0.03)  # 模拟验证时间
            
            # 第二步：准备编译数据 (15%)
            with self.lock:
                self.progress = 15.0
            time.sleep(0.05)  # 模拟数据准备时间
            
            # 第三步：编译为MO格式 (30%)
            with self.lock:
                self.progress = 30.0
            time.sleep(0.08)  # 模拟编译时间
            
            # 第四步：写入文件 (50%)
            with self.lock:
                self.progress = 50.0
            self.po_file.save_as_mofile(self.output_path)
            time.sleep(0.02)  # 模拟写入时间
            
            # 完成 (100%)
            with self.lock:
                self.progress = 100.0
                self.completed = True
                
        except Exception as e:
            with self.lock:
                self.error = f"MO编译失败: {str(e)}"
                self.completed = True

# 添加全局词典替换线程类
class GlobalDictReplaceThread(threading.Thread):
    def __init__(self, po_path, target_dir):
        super().__init__()
        self.po_path = po_path
        self.target_dir = target_dir
        self.progress = 0.0
        self.completed = False
        self.error = None
        self.lock = threading.Lock()
        self.daemon = True

    def run(self):
        try:
            # 第一步：验证文件 (10%)
            with self.lock:
                self.progress = 10.0
            time.sleep(0.02)  # 模拟验证时间
            
            # 第二步：加载PO文件 (20%)
            with self.lock:
                self.progress = 20.0
            po = polib.pofile(self.po_path)
            time.sleep(0.03)  # 模拟加载时间
            
            # 第三步：编译MO文件 (40%)
            with self.lock:
                self.progress = 40.0
            mo_path = os.path.splitext(self.po_path)[0] + ".mo"
            po.save_as_mofile(mo_path)
            time.sleep(0.05)  # 模拟编译时间
            
            # 第四步：检查目标目录 (60%)
            with self.lock:
                self.progress = 60.0
            if not os.path.exists(self.target_dir):
                raise Exception(f"目标目录不存在: {self.target_dir}")
            time.sleep(0.02)  # 模拟检查时间
            
            # 第五步：复制文件 (80%)
            with self.lock:
                self.progress = 80.0
            target_file = os.path.join(self.target_dir, "blender.mo")
            shutil.copyfile(mo_path, target_file)
            time.sleep(0.03)  # 模拟复制时间
            
            # 完成 (100%)
            with self.lock:
                self.progress = 100.0
                self.completed = True
                
        except Exception as e:
            with self.lock:
                self.error = f"全局词典替换失败: {str(e)}"
                self.completed = True 