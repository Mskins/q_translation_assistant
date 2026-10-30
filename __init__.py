# -*- coding: utf-8 -*-


bl_info = {
    "name": "快捷翻译助手",
    "author": "亮锅不服LAO",
    "version": (1, 5, 0),
    "blender": (3, 0, 0),
    "location": "View3D > Sidebar > 翻译助手",
    "description": "处理gettext翻译文件的工具集，支持PO/MO文件转换、PO编辑、文本提取与翻译等功能",
    "warning": "",
    "doc_url": "",
    "category": "亮锅出品",
}

import bpy
from bpy.props import StringProperty, BoolProperty, EnumProperty
from bpy.types import Panel, Operator

# 导入我们的模块
from . import file_converter
from . import po_editor
from . import translation_panel
from . import preferences
from . import utils
from . import translator
from . import global_translation_panel
from . import hud_translator

# 注册所有模块
def register():
    file_converter.register()
    po_editor.register()
    translation_panel.register()
    preferences.register()
    global_translation_panel.register()
    hud_translator.register()
    # utils.register() # utils模块当前不包含任何可注册的UI

def unregister():
    file_converter.unregister()
    po_editor.unregister()
    translation_panel.unregister()
    preferences.unregister()
    global_translation_panel.unregister()
    hud_translator.unregister()
    # utils.unregister() # utils模块当前不包含任何可注册的UI

if __name__ == "__main__":
    register() 