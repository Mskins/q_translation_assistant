# -*- coding: utf-8 -*-
"""
插件偏好设置。

翻译 API 采用“通用大模型接入”方案：
用户填写服务地址（Base URL）、API Key 和模型名称，即可接入任何
OpenAI Chat Completions 兼容的服务商（OpenAI、DeepSeek、通义千问、
豆包、Ollama、LM Studio、OpenRouter、硅基流动、Moonshot、智谱等）。
"""
import json
import os
import re

import bpy
from bpy.props import StringProperty, EnumProperty, BoolProperty, IntProperty
from bpy.types import Operator

from .translator import OpenAICompatibleTranslator
from . import hud_translator

# ---------------------------------------------------------------------------
# 服务商预设：仅用于一键填充地址和模型，所有字段仍可自由修改
# (key, 显示名称, Base URL, 默认模型)
# ---------------------------------------------------------------------------
LLM_PRESETS = [
    ('CUSTOM', "自定义 / 其他服务商", "", ""),
    ('OPENAI', "OpenAI", "https://api.openai.com/v1", "gpt-4o-mini"),
    ('DEEPSEEK', "DeepSeek", "https://api.deepseek.com/v1", "deepseek-chat"),
    ('QWEN', "通义千问（DashScope）",
     "https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen-turbo"),
    ('DOUBAO', "豆包（火山方舟）",
     "https://ark.cn-beijing.volces.com/api/v3", "doubao-1-5-lite-32k-250115"),
    ('OLLAMA', "Ollama（本地）", "http://localhost:11434/v1", "qwen2.5:7b"),
    ('LMSTUDIO', "LM Studio（本地）", "http://localhost:1234/v1", "local-model"),
    ('OPENROUTER', "OpenRouter", "https://openrouter.ai/api/v1", "openai/gpt-4o-mini"),
    ('SILICONFLOW', "硅基流动", "https://api.siliconflow.cn/v1", "Qwen/Qwen2.5-7B-Instruct"),
    ('MOONSHOT', "Moonshot / Kimi", "https://api.moonshot.cn/v1", "moonshot-v1-8k"),
    ('ZHIPU', "智谱 GLM", "https://open.bigmodel.cn/api/paas/v4", "glm-4-flash"),
    ('GEMINI', "Google Gemini",
     "https://generativelanguage.googleapis.com/v1beta/openai", "gemini-2.0-flash"),
    ('GROQ', "Groq", "https://api.groq.com/openai/v1", "llama-3.1-8b-instant"),
    ('MISTRAL', "Mistral", "https://api.mistral.ai/v1", "mistral-small-latest"),
]

_LLM_PROVIDER_ITEMS = [
    (
        key,
        label,
        f"自动填入 {base_url} / {model_name}" if base_url else "手动填写服务地址和模型",
    )
    for key, label, base_url, model_name in LLM_PRESETS
]

# 获取模型列表时使用的临时缓存（只在弹窗期间有效，不写入偏好设置）
_MODEL_DIALOG_CACHE = []


# ---------------------------------------------------------------------------
# 配置解析与翻译器工厂
# ---------------------------------------------------------------------------
def _parse_custom_headers(text: str) -> dict:
    """把 "Key: Value; Key2: Value2" 解析成字典。"""
    headers = {}
    for chunk in re.split(r'[\n;；]+', text or ''):
        chunk = chunk.strip()
        if not chunk or ':' not in chunk:
            continue
        name, value = chunk.split(':', 1)
        name = name.strip()
        value = value.strip()
        if name:
            headers[name] = value
    return headers


def _parse_extra_body(text: str) -> dict:
    """解析用户自定义的额外请求体参数。"""
    text = (text or '').strip()
    if not text:
        return {}
    try:
        data = json.loads(text)
    except ValueError as e:
        raise ValueError(f"额外请求参数不是有效的 JSON：{e}")
    if not isinstance(data, dict):
        raise ValueError('额外请求参数必须是 JSON 对象，例如 {"temperature": 0.2}')
    return data


def create_llm_translator(prefs, require_model: bool = True) -> OpenAICompatibleTranslator:
    base_url = (prefs.llm_base_url or '').strip()
    if not base_url:
        raise ValueError("请填写大模型服务地址（Base URL）")

    model_name = (prefs.llm_model_name or '').strip()
    if require_model and not model_name:
        raise ValueError("请填写模型名称")

    return OpenAICompatibleTranslator(
        base_url=base_url,
        api_key=prefs.llm_api_key,
        model_name=model_name,
        custom_headers=_parse_custom_headers(prefs.llm_custom_headers),
        extra_body=_parse_extra_body(prefs.llm_extra_body),
        timeout=prefs.llm_timeout,
    )


def create_translator_from_prefs(prefs, require_model: bool = True):
    """根据偏好设置创建翻译器；配置不完整时抛出 ValueError。"""
    return create_llm_translator(prefs, require_model=require_model)


def is_translation_configured(prefs) -> bool:
    """供操作符 poll 使用：是否为当前服务填写了必要配置。"""
    return bool((prefs.llm_base_url or '').strip()
                and (prefs.llm_model_name or '').strip())


# ---------------------------------------------------------------------------
# 设置更新回调
# ---------------------------------------------------------------------------
def _apply_llm_preset(self, context):
    """选择服务商预设时自动填充地址与模型（用户仍可手动修改）。"""
    preset = self.llm_provider
    if preset == 'CUSTOM':
        return
    for key, _label, base_url, model_name in LLM_PRESETS:
        if key == preset:
            if base_url:
                self.llm_base_url = base_url
            if model_name:
                self.llm_model_name = model_name
            return


def _model_dialog_items(self, context):
    if not _MODEL_DIALOG_CACHE:
        return [('NONE', "（无可用模型）", "")]
    return [(model, model, "") for model in _MODEL_DIALOG_CACHE]


# ---------------------------------------------------------------------------
# 旧版配置迁移
# 说明：translation_service 及旧字段仍然保留定义（不显示在界面上），
# 这样从旧版本升级时可以直接读取并迁移，不需要用户重新填写。
# ---------------------------------------------------------------------------
def _migrate_legacy_preferences(prefs):
    if prefs.qta_v2_migrated:
        return

    legacy = prefs.translation_service

    # 旧版百度翻译已移除，升级后统一使用通用大模型；
    # 其余旧版大模型服务商尽量保留原 Key 与模型配置。
    if legacy in ('QWEN', 'DEEPSEEK', 'DOUBAO', 'OLLAMA'):
        prefs.llm_provider = legacy

        if legacy == 'QWEN':
            prefs.llm_base_url = 'https://dashscope.aliyuncs.com/compatible-mode/v1'
            prefs.llm_model_name = 'qwen-turbo'
            prefs.llm_api_key = prefs.qwen_api_key
        elif legacy == 'DEEPSEEK':
            prefs.llm_base_url = 'https://api.deepseek.com/v1'
            prefs.llm_model_name = 'deepseek-chat'
            prefs.llm_api_key = prefs.deepseek_api_key
        elif legacy == 'DOUBAO':
            prefs.llm_base_url = 'https://ark.cn-beijing.volces.com/api/v3'
            prefs.llm_model_name = prefs.doubao_model_name or 'doubao-1-5-lite-32k-250115'
            prefs.llm_api_key = prefs.doubao_api_key
        elif legacy == 'OLLAMA':
            base_url = (prefs.ollama_base_url or 'http://localhost:11434').rstrip('/')
            if not base_url.endswith('/v1'):
                base_url += '/v1'
            prefs.llm_base_url = base_url
            prefs.llm_model_name = prefs.ollama_model_name or 'qwen2.5:7b'
            prefs.llm_api_key = ''

    prefs.qta_v2_migrated = True


# ---------------------------------------------------------------------------
# 界面绘制（偏好设置与翻译面板共用，避免两处逻辑不一致）
# ---------------------------------------------------------------------------
def draw_translation_settings(layout, prefs):
    box = layout.box()
    box.label(text="通用大模型设置（OpenAI 兼容接口）:", icon='WORLD')
    box.prop(prefs, "llm_provider")

    col = box.column(align=True)
    col.prop(prefs, "llm_base_url")
    col.prop(prefs, "llm_api_key")

    row = box.row(align=True)
    row.prop(prefs, "llm_model_name")
    row.operator("qta.select_llm_model", text="获取模型", icon='VIEWZOOM')

    box.label(text="任何支持 /chat/completions 的服务商均可接入", icon='INFO')
    box.label(text="本地服务（Ollama / LM Studio）可留空 API Key", icon='INFO')

    box.prop(
        prefs,
        "llm_show_advanced",
        text="高级选项（超时 / 请求头 / 额外参数）",
        emboss=False,
        icon='TRIA_DOWN' if prefs.llm_show_advanced else 'TRIA_RIGHT',
    )
    if prefs.llm_show_advanced:
        advanced = box.column(align=True)
        advanced.prop(prefs, "llm_timeout")
        advanced.prop(prefs, "llm_custom_headers")
        advanced.prop(prefs, "llm_extra_body")

    layout.operator("qta.validate_api", icon='CHECKMARK')


# ---------------------------------------------------------------------------
# 操作符
# ---------------------------------------------------------------------------
class QTA_OT_ValidateAPI(Operator):
    """验证API设置的有效性"""
    bl_idname = "qta.validate_api"
    bl_label = "验证API设置"
    bl_description = "测试当前翻译服务的配置是否有效"

    def execute(self, context):
        prefs = context.preferences.addons[__package__].preferences

        try:
            translator = create_translator_from_prefs(prefs)
        except ValueError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}

        self.report({'INFO'}, "正在验证，请稍候...")
        is_valid, message = translator.validate()

        if is_valid:
            self.report({'INFO'}, message)
        else:
            self.report({'ERROR'}, message)

        return {'FINISHED'}


class QTA_OT_SelectLLMModel(Operator):
    """从当前服务商获取可用模型列表并选择"""
    bl_idname = "qta.select_llm_model"
    bl_label = "获取模型列表"
    bl_description = "请求服务商的 /models 接口，选择后自动填入模型名称"
    bl_options = {'INTERNAL'}

    model: EnumProperty(name="模型", items=_model_dialog_items)

    @classmethod
    def poll(cls, context):
        prefs = context.preferences.addons[__package__].preferences
        return bool((prefs.llm_base_url or '').strip())

    def invoke(self, context, event):
        prefs = context.preferences.addons[__package__].preferences

        try:
            translator = create_llm_translator(prefs, require_model=False)
            models = translator.fetch_models()
        except ValueError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}

        if not models:
            self.report({'ERROR'}, "服务商未返回任何模型")
            return {'CANCELLED'}

        _MODEL_DIALOG_CACHE[:] = models
        preferred = prefs.llm_model_name if prefs.llm_model_name in models else models[0]
        try:
            self.model = preferred
        except (TypeError, ValueError):
            pass

        self.report({'INFO'}, f"获取到 {len(models)} 个模型")
        return context.window_manager.invoke_props_dialog(self, width=560)

    def draw(self, context):
        col = self.layout.column()
        col.label(text=f"共 {len(_MODEL_DIALOG_CACHE)} 个模型，选择后会填入模型名称：")
        col.prop(self, "model", text="")

    def execute(self, context):
        prefs = context.preferences.addons[__package__].preferences
        if self.model and self.model != 'NONE':
            prefs.llm_model_name = self.model
            self.report({'INFO'}, f"已选择模型: {self.model}")
        return {'FINISHED'}


def update_global_translation(self, context):
    import bpy
    if self.global_translation_enabled:
        from .global_translation_panel import extract_locale_zip
        extract_locale_zip()
    else:
        from .global_translation_panel import remove_locale_dir
        remove_locale_dir()
    bpy.ops.qta.global_translation_popup('INVOKE_DEFAULT', enable=self.global_translation_enabled)


class QTA_Preferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    # --- 通用大模型设置 ---
    llm_provider: EnumProperty(
        name="服务商预设",
        description="选择后自动填入常用的服务地址和模型，所有字段仍可手动修改",
        items=_LLM_PROVIDER_ITEMS,
        default='OPENAI',
        update=_apply_llm_preset,
    )

    llm_base_url: StringProperty(
        name="服务地址 (Base URL)",
        description=(
            "OpenAI 兼容接口根地址，填到 /v1 为止，例如 https://api.openai.com/v1；"
            "也可以直接填写完整的 /chat/completions 地址"
        ),
        default="https://api.openai.com/v1",
    )

    llm_api_key: StringProperty(
        name="API Key",
        description="服务商提供的 API Key；本地服务（Ollama / LM Studio）可留空",
        default="",
        subtype='PASSWORD',
    )

    llm_model_name: StringProperty(
        name="模型名称",
        description="模型 ID，例如 gpt-4o-mini、deepseek-chat、qwen-turbo、llama3.1:8b",
        default="gpt-4o-mini",
    )

    llm_timeout: IntProperty(
        name="请求超时（秒）",
        description="单次请求的超时时间，本地模型或长文本可适当调大",
        default=60,
        min=5,
        max=600,
    )

    llm_custom_headers: StringProperty(
        name="自定义请求头",
        description=(
            "可选。多个请求头用分号分隔，例如：X-Api-Key: xxx; X-Title: Blender。"
            "可用于 Azure（api-key）等特殊认证方式"
        ),
        default="",
    )

    llm_extra_body: StringProperty(
        name="额外请求参数 (JSON)",
        description=(
            '可选。合并到请求体中的 JSON 对象，例如：'
            '{"temperature": 0.2, "enable_thinking": false}'
        ),
        default="",
    )

    llm_show_advanced: BoolProperty(
        name="显示高级选项",
        description="展开超时、自定义请求头和额外请求参数",
        default=False,
    )

    # --- 旧版配置字段（仅用于升级迁移，不在界面显示） ---
    # 注意：旧版枚举项的先后顺序必须保持不变（Blender 可能按序号保存枚举值），
    # 新增项只能追加到末尾；BAIDU 仅用于安全读取旧配置，已不再支持。
    translation_service: EnumProperty(
        name="旧版翻译服务",
        items=[
            ('BAIDU', "百度翻译", ""),
            ('QWEN', "通义千问", ""),
            ('DEEPSEEK', "Deepseek", ""),
            ('DOUBAO', "豆包大模型", ""),
            ('OLLAMA', "Ollama本地模型", ""),
            ('LLM', "通用大模型", ""),
        ],
        default='LLM',
    )
    qwen_api_key: StringProperty(default="", subtype='PASSWORD')
    deepseek_api_key: StringProperty(default="", subtype='PASSWORD')
    doubao_api_key: StringProperty(default="", subtype='PASSWORD')
    doubao_model_name: StringProperty(default="doubao-1-5-lite-32k-250115")
    ollama_base_url: StringProperty(default="http://localhost:11434")
    ollama_model_name: StringProperty(default="qwen2.5:7b")

    qta_v2_migrated: BoolProperty(default=False)

    # --- 全局翻译设置 ---
    global_translation_enabled: BoolProperty(
        name="全局翻译",
        description="启用会将插件自带全局词典解压到Blender用户datafiles目录，实现全局翻译\n禁用会删除全局词典",
        default=False,
        update=update_global_translation,
    )

    lang_button_location: EnumProperty(
        name="语言切换按钮位置",
        items=[
            ('TOOLBAR', "顶部工具栏", "显示在顶部工具栏"),
            ('STATUSBAR', "状态栏", "显示在状态栏"),
            ('NONE', "不显示", "不显示语言切换按钮"),
        ],
        default='STATUSBAR',
    )

    tooltips_included: BoolProperty(
        name="包含工具提示翻译",
        description="语言切换时同时切换工具提示的翻译状态",
        default=True,
    )

    use_translate_reports: BoolProperty(
        name="翻译报告信息",
        description="语言切换时同时切换报告信息的翻译状态",
        default=False,
    )

    # --- HUD翻译设置 ---
    hud_enabled: BoolProperty(
        name="启用HUD翻译",
        description="启用HUD翻译功能，通过重写blf_draw函数实现实时界面翻译",
        default=False,
        update=lambda self, context: hud_translator.update_hud_enabled(self, context),
    )

    hud_mo_file_path: StringProperty(
        name="HUD翻译文件",
        description="选择用于HUD翻译的.mo文件路径",
        default=os.path.join(bpy.utils.user_resource('DATAFILES'), "locale", "zh_HANS", "LC_MESSAGES", "blender.mo"),
        subtype='FILE_PATH',
        update=lambda self, context: hud_translator.update_hud_settings(self, context),
    )

    def draw(self, context):
        layout = self.layout
        draw_translation_settings(layout, self)

        box = layout.box()
        box.label(text="全局翻译设置:")
        box.prop(self, "global_translation_enabled", text="全局翻译", toggle=True)
        box.prop(self, "lang_button_location", text="语言切换按钮位置")

        # 语言切换选项
        lang_box = box.box()
        lang_box.label(text="语言切换选项:")
        lang_box.prop(self, "tooltips_included", text="包含工具提示翻译")
        lang_box.prop(self, "use_translate_reports", text="翻译报告信息")

        # HUD翻译设置
        box = layout.box()
        box.label(text="HUD翻译设置:")
        box.prop(self, "hud_enabled", text="启用HUD翻译", toggle=True)

        if self.hud_enabled:
            box.prop(self, "hud_mo_file_path", text="翻译文件")


def register():
    bpy.utils.register_class(QTA_OT_ValidateAPI)
    bpy.utils.register_class(QTA_OT_SelectLLMModel)
    bpy.utils.register_class(QTA_Preferences)

    # 初始化偏好设置（迁移旧版配置 + HUD翻译）
    prefs_holder = bpy.context.preferences.addons.get(__package__)
    if prefs_holder:
        p = prefs_holder.preferences
        _migrate_legacy_preferences(p)

        # 自动填充默认路径
        default_mo = os.path.join(bpy.utils.user_resource('DATAFILES'), "locale", "zh_HANS", "LC_MESSAGES", "blender.mo")
        if not p.hud_mo_file_path:
            p.hud_mo_file_path = default_mo
        # 启动时如已启用HUD翻译则自动注册
        if p.hud_enabled:
            import q_translation_assistant.hud_translator as hud_translator_module
            hud_translator_module.register_hud_translation()


def unregister():
    bpy.utils.unregister_class(QTA_Preferences)
    bpy.utils.unregister_class(QTA_OT_SelectLLMModel)
    bpy.utils.unregister_class(QTA_OT_ValidateAPI)
