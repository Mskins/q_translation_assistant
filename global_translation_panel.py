# -*- coding: utf-8 -*-
"""
Blender全局翻译面板及相关操作符
"""
import bpy
import os
import zipfile
import shutil
from bpy.props import BoolProperty, EnumProperty
from bpy.types import Panel, Operator, AddonPreferences
import bpy.utils.previews

# 图标路径
ICON_CN = os.path.join(os.path.dirname(__file__), "icons", "CN.png")
ICON_EN = os.path.join(os.path.dirname(__file__), "icons", "EN.png")

# 获取Blender用户datafiles目录

def get_blender_datafiles_dir():
    datafiles_dir = bpy.utils.user_resource('DATAFILES')
    if not os.path.exists(datafiles_dir):
        os.makedirs(datafiles_dir, exist_ok=True)
    return datafiles_dir

# 获取插件内locale.zip路径
def get_plugin_locale_zip():
    return os.path.join(os.path.dirname(__file__), "mo", "locale.zip")

# 解压locale.zip到Blender datafiles
def extract_locale_zip():
    datafiles_dir = get_blender_datafiles_dir()
    zip_path = get_plugin_locale_zip()
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        zip_ref.extractall(datafiles_dir)

# 删除Blender datafiles/locale目录
def remove_locale_dir():
    locale_dir = os.path.join(get_blender_datafiles_dir(), "locale")
    if os.path.exists(locale_dir):
        shutil.rmtree(locale_dir)

# 弹窗操作符
class QTA_OT_GlobalTranslationPopup(Operator):
    bl_idname = "qta.global_translation_popup"
    bl_label = "全局翻译生效提示"
    bl_options = {'INTERNAL'}

    enable: BoolProperty()

    def execute(self, context):
        return {'FINISHED'}

    def invoke(self, context, event):
        wm = context.window_manager
        return wm.invoke_popup(self, width=350)

    def draw(self, context):
        layout = self.layout
        if self.enable:
            layout.label(text="全局翻译已启用！请重启Blender或新建Blender实例以生效。", icon='INFO')
        else:
            layout.label(text="全局翻译已关闭！请重启Blender或新建Blender实例以还原。", icon='INFO')
        row = layout.row(align=True)
        row.operator("qta.restart_blender", text="重启Blender", icon='LOOP_BACK')
        row.operator("qta.new_blender_window", text="新建Blender实例", icon='BLENDER')

# 重启Blender操作符
class QTA_OT_RestartBlender(Operator):
    bl_idname = "qta.restart_blender"
    bl_label = "重启Blender"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        import sys
        import subprocess
        blender_path = sys.argv[0]
        subprocess.Popen([blender_path] + sys.argv[1:])
        bpy.ops.wm.quit_blender()
        return {'FINISHED'}

# 新建Blender实例操作符
class QTA_OT_NewBlenderWindow(Operator):
    bl_idname = "qta.new_blender_window"
    bl_label = "新建Blender实例"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        import sys
        import subprocess
        blender_path = sys.argv[0]
        subprocess.Popen([blender_path] + sys.argv[1:])
        return {'FINISHED'}

# 语言切换操作符
class QTA_OT_LanguageSwitch(Operator):
    bl_idname = "qta.language_switch"
    bl_label = "切换中英文"
    bl_description = "一键切换中英文界面语言"
    
    @property
    def language_id(self):
        """获取当前可用的中文语言ID"""
        return "zh_CN" if "zh_CN" in bpy.app.translations.locales else "zh_HANS"
    
    def execute(self, context):
        view = context.preferences.view
        pref = context.preferences.addons.get("q_translation_assistant")
        
        # 获取当前语言状态
        current_locale = bpy.app.translations.locale
        is_chinese = current_locale in ['zh_CN', 'zh_HANS']
        
        # 根据当前语言状态决定切换目标
        if is_chinese:
            # 当前是中文，切换到英文
            view.language = "en_US"
            view.use_translate_interface = False
            view.use_translate_tooltips = False
            if hasattr(view, "use_translate_reports"):
                view.use_translate_reports = False
        else:
            # 当前是英文或其他语言，切换到中文
            view.language = self.language_id
            view.use_translate_interface = True
            view.use_translate_tooltips = True
            view.use_translate_reports = True
        
        # 通知HUD翻译系统更新
        try:
            if pref and pref.preferences.hud_enabled:
                import q_translation_assistant.hud_translator as hud_translator
                # 清理HUD翻译缓存
                hud_translator.clear_hud_cache()
                # 更新HUD翻译函数
                hud_translator.update_hud_translation()
                # 强制刷新HUD翻译
                hud_translator.force_refresh_hud()
            else:
                # 如果HUD翻译未启用，确保HUD翻译系统完全清理
                import q_translation_assistant.hud_translator as hud_translator
                hud_translator.unregister_hud_translation()
                
            # 强制重绘所有区域
            for area in bpy.context.screen.areas:
                area.tag_redraw()
        except Exception as e:
            print(f"HUD翻译更新失败: {e}")
        
        return {'FINISHED'}

# 打开全局词典目录操作符
class QTA_OT_OpenGlobalDictDir(Operator):
    bl_idname = "qta.open_global_dict_dir"
    bl_label = "打开全局词典目录"
    bl_description = "打开Blender用户配置datafiles/locale/zh_HANS/LC_MESSAGES目录"

    def execute(self, context):
        import os
        import platform
        import subprocess
        base_dir = get_blender_datafiles_dir()
        target_dir = os.path.join(base_dir, "locale", "zh_HANS", "LC_MESSAGES")
        if not os.path.exists(target_dir):
            self.report({'WARNING'}, f"目录不存在: {target_dir}")
            return {'CANCELLED'}
        if platform.system() == "Windows":
            os.startfile(target_dir)
        elif platform.system() == "Darwin":
            subprocess.Popen(["open", target_dir])
        else:
            subprocess.Popen(["xdg-open", target_dir])
        return {'FINISHED'}

# 面板
class QTA_PT_GlobalTranslation(Panel):
    bl_label = "Blender全局翻译"
    bl_idname = "QTA_PT_GlobalTranslation"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "翻译助手"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        prefs = context.preferences.addons[__package__].preferences
        box = layout.box()
        row = box.row(align=True)
        row.prop(prefs, "global_translation_enabled", text="全局翻译", toggle=True)
        row.operator("qta.language_switch", text="中/英切换")
        box.label(text="语言切换按钮位置")
        box.prop(prefs, "lang_button_location", text="")
        # 新增打开全局词典目录按钮
        box.operator("qta.open_global_dict_dir", icon='FILE_FOLDER')

        # --- HUD翻译快捷操作 ---
        hud_box = layout.box()
        hud_box.label(text="HUD翻译设置:", icon='FONTPREVIEW')
        hud_prefs = prefs
        row = hud_box.row(align=True)
        row.prop(hud_prefs, "hud_enabled", text="启用HUD翻译", toggle=True)
        if hud_prefs.hud_enabled:
            row = hud_box.row()
            row.prop(hud_prefs, "hud_mo_file_path", text="翻译文件")
            row = hud_box.row(align=True)
            row.operator("hud_translation.reload", text="重新加载", icon='FILE_REFRESH')
            row.operator("hud_translation.clear_cache", text="清除缓存", icon='X')

# 状态栏/工具栏按钮

preview_collections = {}

def draw_lang_switch_statusbar(self, context):
    prefs = context.preferences.addons[__package__].preferences
    if prefs.lang_button_location == 'STATUSBAR':
        layout = self.layout
        # 根据当前语言状态显示图标
        current_locale = bpy.app.translations.locale
        is_chinese = current_locale in ['zh_CN', 'zh_HANS']
        icon = 'CN' if is_chinese else 'EN'
        icon_id = preview_collections["main"][icon].icon_id
        layout.operator(QTA_OT_LanguageSwitch.bl_idname, text="", icon_value=icon_id)

def draw_lang_switch_toolbar(self, context):
    prefs = context.preferences.addons[__package__].preferences
    if prefs.lang_button_location == 'TOOLBAR':
        layout = self.layout
        layout.separator()
        # 根据当前语言状态显示图标
        current_locale = bpy.app.translations.locale
        is_chinese = current_locale in ['zh_CN', 'zh_HANS']
        icon = 'CN' if is_chinese else 'EN'
        icon_id = preview_collections["main"][icon].icon_id
        layout.operator(QTA_OT_LanguageSwitch.bl_idname, text="", icon_value=icon_id)

# 当选择"不显示"时，这些函数不会绘制任何内容

# 全局翻译开关操作符（偏好设置同步）
class QTA_OT_ToggleGlobalTranslation(Operator):
    bl_idname = "qta.toggle_global_translation"
    bl_label = "切换全局翻译"
    enable: BoolProperty()

    def execute(self, context):
        prefs = context.preferences.addons[__package__].preferences
        if self.enable:
            extract_locale_zip()
        else:
            remove_locale_dir()
        prefs.global_translation_enabled = self.enable
        bpy.ops.qta.global_translation_popup('INVOKE_DEFAULT', enable=self.enable)
        # 强制刷新所有区域
        for window in context.window_manager.windows:
            for area in window.screen.areas:
                area.tag_redraw()
        return {'FINISHED'}

# 注册
classes = [
    QTA_PT_GlobalTranslation,
    QTA_OT_ToggleGlobalTranslation,
    QTA_OT_GlobalTranslationPopup,
    QTA_OT_RestartBlender,
    QTA_OT_NewBlenderWindow,
    QTA_OT_LanguageSwitch,
    QTA_OT_OpenGlobalDictDir,
]

addon_keymaps = []

def register():
    global preview_collections
    pcoll = bpy.utils.previews.new()
    pcoll.load("CN", ICON_CN, 'IMAGE')
    pcoll.load("EN", ICON_EN, 'IMAGE')
    preview_collections["main"] = pcoll
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.STATUSBAR_HT_header.append(draw_lang_switch_statusbar)
    bpy.types.TOPBAR_MT_editor_menus.append(draw_lang_switch_toolbar)

    # 注册F8快捷键
    wm = bpy.context.window_manager
    kc = wm.keyconfigs.addon
    if kc:
        km = kc.keymaps.new(name='Window', space_type='EMPTY')
        kmi = km.keymap_items.new(QTA_OT_LanguageSwitch.bl_idname, type='F8', value='PRESS')
        addon_keymaps.append((km, kmi))

    # 监听偏好设置变化，自动触发全局翻译操作
    def update_global_translation(self, context):
        bpy.ops.qta.toggle_global_translation('INVOKE_DEFAULT', enable=self.global_translation_enabled)
    QTA_Preferences = bpy.types.AddonPreferences
    if not hasattr(QTA_Preferences, '_qta_global_translation_update_patch'):
        setattr(QTA_Preferences, 'global_translation_enabled', bpy.props.BoolProperty(
            name="全局翻译",
            description="启用后将locale.zip解压到Blender用户datafiles，实现全局翻译",
            default=False,
            update=update_global_translation
        ))
        setattr(QTA_Preferences, '_qta_global_translation_update_patch', True)

def unregister():
    global preview_collections
    for pcoll in preview_collections.values():
        bpy.utils.previews.remove(pcoll)
    preview_collections.clear()
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except (ValueError, RuntimeError) as e:
            # 如果类未注册或已经取消注册，忽略错误
            print(f"Warning: Could not unregister class {cls.__name__}: {e}")
            pass
    bpy.types.STATUSBAR_HT_header.remove(draw_lang_switch_statusbar)
    bpy.types.TOPBAR_MT_editor_menus.remove(draw_lang_switch_toolbar)
    # 注销F8快捷键
    for km, kmi in addon_keymaps:
        km.keymap_items.remove(kmi)
    addon_keymaps.clear() 