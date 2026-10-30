# -*- coding: utf-8 -*-
"""
文件转换模块
实现PO/MO文件的互相转换功能
"""

import bpy
import os
import subprocess
import platform
import shutil
from bpy.props import StringProperty, EnumProperty, BoolProperty
from bpy.types import Panel, Operator

# 导入polib模块
from . import polib

# 导入内置msgfmt模块
from . import builtin_msgfmt

# 新增：PY字典到PO文件的转换
import ast

# 使用内置msgfmt模块的函数
detect_platform = builtin_msgfmt.get_platform_key
find_msgfmt_tools = builtin_msgfmt.find_msgfmt_tools
is_msgfmt_available = builtin_msgfmt.is_msgfmt_available
is_msgmerge_available = builtin_msgfmt.is_msgmerge_available
convert_with_msgfmt = builtin_msgfmt.convert_with_msgfmt
merge_po_files = builtin_msgfmt.merge_po_files

def extract_dict_from_py(py_path):
    """从py文件中提取第一个字符串到字符串的字典（不限定变量名）"""
    with open(py_path, 'r', encoding='utf-8') as f:
        content = f.read()
    tree = ast.parse(content, filename=py_path)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            if isinstance(node.value, ast.Dict):
                result = {}
                all_str = True
                for k, v in zip(node.value.keys, node.value.values):
                    if not (isinstance(k, (ast.Str, ast.Constant)) and isinstance(v, (ast.Str, ast.Constant))):
                        all_str = False
                        break
                    key = k.s if hasattr(k, 's') else k.value
                    val = v.s if hasattr(v, 's') else v.value
                    result[key] = val
                if all_str and result:
                    return result
    return None

def dict_to_po(data_dict, po_path):
    """将字典写入po文件"""
    po = polib.POFile()
    for src, tgt in data_dict.items():
        entry = polib.POEntry(msgid=src, msgstr=tgt)
        po.append(entry)
    po.save(po_path)

def update_file_path(self, context):
    """当输入文件被选择时，自动设置默认的输出目录"""
    scene = context.scene
    mode = scene.conversion_mode
    
    if mode == 'PO_TO_MO' and scene.po_file_path:
        scene.output_dir = os.path.dirname(scene.po_file_path)
    elif mode == 'MO_TO_PO' and scene.mo_file_path:
        scene.output_dir = os.path.dirname(scene.mo_file_path)

class QTA_PT_FileConverter(Panel):
    """文件转换面板"""
    bl_label = "文件转换"
    bl_idname = "QTA_PT_FileConverter"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "翻译助手"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        
        # 模式切换
        layout.prop(scene, "conversion_mode", expand=True)
        
        box = layout.box()
        # 根据模式显示不同的UI
        if scene.conversion_mode == 'PO_TO_MO':
            box.prop(scene, "po_file_path", text="PO文件")
        elif scene.conversion_mode == 'MO_TO_PO':
            box.prop(scene, "mo_file_path", text="MO文件")
        elif scene.conversion_mode == 'PY_TO_PO':
            box.prop(scene, "py_dict_file_path", text="PY字典文件")
        elif scene.conversion_mode == 'PO_MERGE':
            box.prop(scene, "pot_template_path", text="PO文件A")
            box.prop(scene, "po_translation_path", text="PO文件B")
            box.prop(scene, "duplicate_handling_mode", text="重复项处理模式")
        box.prop(scene, "output_dir", text="输出目录")
        
        # 添加msgfmt选项（仅对PO/MO转换显示）
        if scene.conversion_mode in ['PO_TO_MO', 'MO_TO_PO']:
            msgfmt_info = builtin_msgfmt.get_msgfmt_info()
            row = box.row()
            
            # 根据转换模式显示不同的工具名称
            if scene.conversion_mode == 'PO_TO_MO':
                tool_name = "msgfmt"
                tool_display = "使用msgfmt（更快）"
            else:  # MO_TO_PO
                tool_name = "msgunfmt"
                tool_display = "使用msgunfmt（更快）"
            
            row.prop(scene, "use_msgfmt", text=tool_display)
            
            if not msgfmt_info['available']:
                row.label(text=f"⚠️ {tool_name}未找到", icon='ERROR')
                row.operator("qta.install_msgfmt_help", text="", icon='HELP')
            else:
                # 显示工具类型
                tool_type = msgfmt_info['type']
                if tool_type == 'builtin':
                    row.label(text="✓ 内置工具", icon='CHECKMARK')
                else:
                    row.label(text="✓ 系统工具", icon='CHECKMARK')
        

        
        row = box.row(align=True)
        row.scale_y = 1.5
        if scene.conversion_mode == 'PO_MERGE':
            row.operator("qta.convert_file", text="合并", icon='PLAY')
        else:
            row.operator("qta.convert_file", text="转换", icon='PLAY')
        row.operator("qta.show_file_info", text="", icon='INFO')

class QTA_OT_ConvertFile(Operator):
    """根据所选模式转换或合并翻译文件"""
    bl_idname = "qta.convert_file"
    bl_label = "转换文件"
    bl_description = "根据所选模式转换或合并翻译文件"

    def execute(self, context):
        scene = context.scene
        mode = scene.conversion_mode
        output_dir = scene.output_dir

        if not output_dir:
            self.report({'ERROR'}, "请选择输出目录")
            return {'CANCELLED'}
        
        try:
            os.makedirs(output_dir, exist_ok=True)

            if mode == 'PO_TO_MO':
                input_path = scene.po_file_path
                if not input_path:
                    self.report({'ERROR'}, "请选择PO文件")
                    return {'CANCELLED'}
                base_name = os.path.splitext(os.path.basename(input_path))[0]
                output_path = os.path.join(output_dir, base_name + '.mo')
                
                # 根据用户选择使用msgfmt或polib
                if scene.use_msgfmt and is_msgfmt_available():
                    try:
                        convert_with_msgfmt(input_path, output_path, mode)
                        msgfmt_info = builtin_msgfmt.get_msgfmt_info()
                        tool_type = msgfmt_info['type']
                        self.report({'INFO'}, f"使用{tool_type}msgfmt成功转换文件到: {output_path}")
                    except Exception as e:
                        self.report({'WARNING'}, f"msgfmt转换失败，回退到polib: {str(e)}")
                        po_file = polib.pofile(input_path)
                        po_file.save_as_mofile(output_path)
                else:
                    po_file = polib.pofile(input_path)
                    po_file.save_as_mofile(output_path)

            elif mode == 'MO_TO_PO':
                input_path = scene.mo_file_path
                if not input_path:
                    self.report({'ERROR'}, "请选择MO文件")
                    return {'CANCELLED'}
                base_name = os.path.splitext(os.path.basename(input_path))[0]
                output_path = os.path.join(output_dir, base_name + '.po')
                
                # 根据用户选择使用msgfmt或polib
                if scene.use_msgfmt and is_msgfmt_available():
                    try:
                        convert_with_msgfmt(input_path, output_path, mode)
                        msgfmt_info = builtin_msgfmt.get_msgfmt_info()
                        tool_type = msgfmt_info['type']
                        self.report({'INFO'}, f"使用{tool_type}msgfmt成功转换文件到: {output_path}")
                    except Exception as e:
                        self.report({'WARNING'}, f"msgfmt转换失败，回退到polib: {str(e)}")
                        mo_file = polib.mofile(input_path)
                        mo_file.save_as_pofile(output_path)
                else:
                    mo_file = polib.mofile(input_path)
                    mo_file.save_as_pofile(output_path)
            
            elif mode == 'PY_TO_PO':
                input_path = scene.py_dict_file_path
                if not input_path:
                    self.report({'ERROR'}, "请选择PY字典文件")
                    return {'CANCELLED'}
                base_name = os.path.splitext(os.path.basename(input_path))[0]
                output_path = os.path.join(output_dir, base_name + '.po')
                data_dict = extract_dict_from_py(input_path)
                if not data_dict:
                    self.report({'ERROR'}, "未找到名为data的字典，或内容格式不正确")
                    return {'CANCELLED'}
                dict_to_po(data_dict, output_path)
                self.report({'INFO'}, f"成功转换PY字典到: {output_path}")
                return {'FINISHED'}
            
            elif mode == 'PO_MERGE':
                template_path = scene.pot_template_path
                translation_path = scene.po_translation_path
                
                if not template_path or not translation_path:
                    self.report({'ERROR'}, "请选择POT模板文件和PO翻译文件")
                    return {'CANCELLED'}
                
                if not output_dir:
                    self.report({'ERROR'}, "请选择输出目录")
                    return {'CANCELLED'}
                
                # 生成输出文件名
                base_name = os.path.splitext(os.path.basename(translation_path))[0]
                output_path = os.path.join(output_dir, f"{base_name}_merged.po")
                
                # 使用字典去重方式进行合并，根据选择的优先级模式
                try:
                    priority_mode = scene.duplicate_handling_mode
                    merge_po_files(template_path, translation_path, output_path, 'merge', priority_mode)
                    
                    priority_text = "A文件" if priority_mode == 'A_PRIORITY' else "B文件"
                    self.report({'INFO'}, f"成功合并PO文件到: {output_path}（以{priority_text}为准）")
                except Exception as e:
                    error_msg = str(e)
                    self.report({'WARNING'}, f"PO合并失败: {error_msg}")
                    return {'CANCELLED'}

            self.report({'INFO'}, f"成功转换文件到: {output_path}")

        except Exception as e:
            self.report({'ERROR'}, f"转换失败: {str(e)}")
            return {'CANCELLED'}
            
        return {'FINISHED'}

class QTA_OT_InstallMsgfmtHelp(Operator):
    """显示如何安装msgfmt的帮助信息"""
    bl_idname = "qta.install_msgfmt_help"
    bl_label = "安装msgfmt帮助"
    bl_description = "显示如何安装msgfmt工具"
    
    def execute(self, context):
        platform = detect_platform()
        
        if platform == 'windows':
            help_text = (
                "在Windows上安装msgfmt:\n\n"
                "1. 下载gettext工具包:\n"
                "   - 访问: https://mlocati.github.io/articles/gettext-icon-windows.html\n"
                "   - 或使用Chocolatey: choco install gettext\n"
                "   - 或使用Scoop: scoop install gettext\n\n"
                "2. 安装后确保gettext/bin目录在系统PATH中\n\n"
                "3. 重启Blender后即可使用msgfmt功能"
            )
        elif platform == 'darwin':  # macOS
            help_text = (
                "在macOS上安装msgfmt:\n\n"
                "1. 使用Homebrew安装:\n"
                "   brew install gettext\n\n"
                "2. 或使用MacPorts:\n"
                "   sudo port install gettext\n\n"
                "3. 安装后重启Blender即可使用"
            )
        else:  # Linux
            help_text = (
                "在Linux上安装msgfmt:\n\n"
                "Ubuntu/Debian:\n"
                "   sudo apt-get install gettext\n\n"
                "CentOS/RHEL/Fedora:\n"
                "   sudo yum install gettext\n"
                "   或 sudo dnf install gettext\n\n"
                "Arch Linux:\n"
                "   sudo pacman -S gettext\n\n"
                "安装后重启Blender即可使用"
            )
        
        self.report({'INFO'}, help_text)
        return {'FINISHED'}

class QTA_OT_CleanPOFile(Operator):
    """清理PO文件中的重复条目"""
    bl_idname = "qta.clean_po_file"
    bl_label = "清理重复条目"
    bl_description = "清理PO文件中的重复msgid条目"
    
    filepath: StringProperty(
        name="PO文件路径",
        subtype="FILE_PATH",
        description="选择要清理的PO文件"
    )
    
    def execute(self, context):
        if not self.filepath:
            self.report({'ERROR'}, "请选择PO文件")
            return {'CANCELLED'}
        
        try:
            from .builtin_msgfmt import clean_duplicate_entries
            duplicate_count = clean_duplicate_entries(self.filepath)
            
            if duplicate_count > 0:
                self.report({'INFO'}, f"成功清理了 {duplicate_count} 个重复条目，原文件已备份为 .backup")
            else:
                self.report({'INFO'}, "未发现重复条目")
                
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"清理失败: {str(e)}")
            return {'CANCELLED'}
    
    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

class QTA_OT_ShowFileInfo(Operator):
    """显示所选翻译文件的信息"""
    bl_idname = "qta.show_file_info"
    bl_label = "文件信息"
    bl_description = "显示当前选择的翻译文件信息"
    
    @classmethod
    def poll(cls, context):
        scene = context.scene
        if scene.conversion_mode == 'PO_TO_MO':
            return scene.po_file_path != ""
        else:
            return scene.mo_file_path != ""

    def execute(self, context):
        scene = context.scene
        mode = scene.conversion_mode
        
        try:
            if mode == 'PO_TO_MO':
                file_path = scene.po_file_path
                po_file = polib.pofile(file_path)
                total = len([e for e in po_file if not e.obsolete])
                info = (f"PO文件信息:\n"
                        f"  路径: {os.path.basename(file_path)}\n"
                        f"  总条目: {total}\n"
                        f"  已翻译: {len(po_file.translated_entries())}\n"
                        f"  未翻译: {len(po_file.untranslated_entries())}\n"
                        f"  模糊条目: {len(po_file.fuzzy_entries())}\n"
                        f"  完成度: {po_file.percent_translated()}%")
            else:
                file_path = scene.mo_file_path
                mo_file = polib.mofile(file_path)
                info = (f"MO文件信息:\n"
                        f"  路径: {os.path.basename(file_path)}\n"
                        f"  总条目: {len(mo_file)}\n"
                        f"  类型: 编译后的二进制文件")

            # 在新窗口中显示信息
            def draw_info(self, context):
                for line in info.split('\n'):
                    self.layout.label(text=line)
            
            bpy.context.window_manager.popup_menu(draw_info, title="文件信息", icon='INFO')

        except Exception as e:
            self.report({'ERROR'}, f"读取文件信息失败: {str(e)}")
            return {'CANCELLED'}
            
        return {'FINISHED'}

# 注册列表
classes = (
    QTA_PT_FileConverter,
    QTA_OT_ConvertFile,
    QTA_OT_InstallMsgfmtHelp,
    QTA_OT_CleanPOFile,
    QTA_OT_ShowFileInfo,
)

# 注册函数
def register():
    # 注册属性
    bpy.types.Scene.conversion_mode = EnumProperty(
        name="转换模式",
        description="选择要执行的转换类型",
        items=[
            ('PO_TO_MO', "PO → MO", "将PO文件转换为MO文件"),
            ('MO_TO_PO', "MO → PO", "将MO文件转换为PO文件"),
            ('PY_TO_PO', "PY → PO", "将PY字典文件转换为PO文件"),
            ('PO_MERGE', "PO合并", "合并PO文件（使用msgmerge）"),
        ],
        default='PO_TO_MO',
    )
    
    bpy.types.Scene.po_file_path = StringProperty(
        name="PO文件路径",
        description="要转换的PO文件路径",
        default="",
        maxlen=1024,
        subtype='FILE_PATH',
        update=update_file_path
    )
    
    bpy.types.Scene.mo_file_path = StringProperty(
        name="MO文件路径",
        description="要转换的MO文件路径",
        default="",
        maxlen=1024,
        subtype='FILE_PATH',
        update=update_file_path
    )
    
    bpy.types.Scene.py_dict_file_path = StringProperty(
        name="PY字典文件路径",
        description="要转换的PY字典文件路径（需包含data字典）",
        default="",
        maxlen=1024,
        subtype='FILE_PATH',
    )
    
    bpy.types.Scene.pot_template_path = StringProperty(
        name="PO文件A",
        description="PO文件A路径（用于PO合并）",
        default="",
        maxlen=1024,
        subtype='FILE_PATH',
    )
    
    bpy.types.Scene.po_translation_path = StringProperty(
        name="PO文件B",
        description="PO文件B路径（用于PO合并）",
        default="",
        maxlen=1024,
        subtype='FILE_PATH',
    )
    
    bpy.types.Scene.duplicate_handling_mode = EnumProperty(
        name="重复项处理模式",
        description="选择重复项的处理方式",
        items=[
            ('A_PRIORITY', "以A文件为准", "当有重复项时，优先使用PO文件A中的条目"),
            ('B_PRIORITY', "以B文件为准", "当有重复项时，优先使用PO文件B中的条目"),
        ],
        default='A_PRIORITY',
    )
    

    
    bpy.types.Scene.output_dir = StringProperty(
        name="输出目录",
        description="转换后文件的输出目录",
        default="",
        maxlen=1024,
        subtype='DIR_PATH'
    )
    
    bpy.types.Scene.use_msgfmt = BoolProperty(
        name="使用msgfmt",
        description="使用msgfmt工具进行转换（速度更快，需要系统安装gettext）",
        default=False
    )
    

    
    # 注册类
    for cls in classes:
        bpy.utils.register_class(cls)

def unregister():
    # 注销类
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except (ValueError, RuntimeError) as e:
            # 如果类未注册或已经取消注册，忽略错误
            print(f"Warning: Could not unregister class {cls.__name__}: {e}")
            pass
    
    # 删除属性
    del bpy.types.Scene.output_dir
    del bpy.types.Scene.mo_file_path
    del bpy.types.Scene.po_file_path
    del bpy.types.Scene.py_dict_file_path
    del bpy.types.Scene.conversion_mode
    del bpy.types.Scene.use_msgfmt
    del bpy.types.Scene.pot_template_path
    del bpy.types.Scene.po_translation_path
    del bpy.types.Scene.duplicate_handling_mode 