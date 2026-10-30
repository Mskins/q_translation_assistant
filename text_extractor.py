# -*- coding: utf-8 -*-
"""
文本提取模块
从Blender插件的Python文件中提取需要翻译的文本。

设计原则：
1. 用户可见位置（bl_label、name、description、text、label、report、枚举项等）
   提取到的字符串一律视为界面文本，不再用“变量名/特殊字符”规则误杀。
2. 补全常见写法：f-string、字符串拼接、% 格式化、.format()、常量引用、
   bl_category、bl_info、gettext 系列函数、operator/label 等位置参数。
3. 仅在无法确定上下文（如普通列表、元组、注释）时使用保守的代码噪声过滤，
   避免把路径、URL、变量名等当成词条。
"""

import os
import ast
import glob
import json
import re
from dataclasses import dataclass
from typing import List


@dataclass
class ExtractedText:
    """提取的文本条目"""
    text: str
    file_path: str
    line_number: int
    context: str
    original_line: str


class TextExtractor:
    """文本提取器"""

    # 用于AST解析器查找的目标关键字（赋值语句 / 函数调用关键字参数）
    TEXT_PATTERNS = {
        "bl_label", "bl_description", "bl_category", "name", "description",
        "warning", "text", "title", "label",
    }

    def __init__(self):
        self.extracted_texts: List[ExtractedText] = []

    # ------------------------------------------------------------------
    # 公共提取入口
    # ------------------------------------------------------------------
    def extract_from_file(self, file_path: str, extract_docstring: bool = False,
                          filter_options: dict = None) -> List[ExtractedText]:
        """从单个Python文件中使用AST提取文本"""
        if not file_path.endswith('.py'):
            return []

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            print(f"无法读取文件 {file_path}: {e}")
            return []

        try:
            tree = ast.parse(content, filename=file_path)
        except SyntaxError as e:
            print(f"无法解析文件 {file_path}: {e}")
            return []

        visitor = self.TextVisitor(
            file_path,
            self.TEXT_PATTERNS,
            extract_docstring=extract_docstring,
            filter_options=filter_options,
        )
        visitor.visit(tree)

        # 同一文件内先去重，避免同一个字符串因多种语法路径被重复收集
        seen = set()
        result = []
        for item in visitor.texts:
            key = (item.text, item.context)
            if key not in seen:
                seen.add(key)
                result.append(item)
        return result

    def extract_from_blend_file(self, file_path: str, extract_options: dict = None) -> List[ExtractedText]:
        """从.blend文件中提取资产和节点组接口名称"""
        import bpy
        if not file_path or not file_path.endswith('.blend'):
            return []

        if extract_options is None:
            extract_options = {
                'extract_objects': True,
                'extract_materials': True,
                'extract_worlds': True,
                'extract_collections': True,
                'extract_textures': True,
                'extract_images': True,
                'extract_node_groups': True,
                'extract_node_sockets': True,
                'extract_node_panels': True,
            }

        texts = []

        with bpy.data.libraries.load(file_path, link=False, relative=False) as (data_from, data_to):
            data_block_mapping = {
                'objects': 'extract_objects',
                'materials': 'extract_materials',
                'worlds': 'extract_worlds',
                'collections': 'extract_collections',
                'textures': 'extract_textures',
                'images': 'extract_images',
                'node_groups': 'extract_node_groups',
            }

            for block_type, option_key in data_block_mapping.items():
                if extract_options.get(option_key, True) and hasattr(data_from, block_type):
                    for name in getattr(data_from, block_type):
                        texts.append(ExtractedText(
                            text=name,
                            file_path=file_path,
                            line_number=0,
                            context='',
                            original_line=f"Data-block Name ({block_type})"
                        ))

            if (extract_options.get('extract_node_sockets', True)
                    or extract_options.get('extract_node_panels', True)) \
                    and hasattr(data_from, 'node_groups'):
                data_to.node_groups = data_from.node_groups

        for ng in data_to.node_groups:
            if not ng:
                continue

            if hasattr(ng, 'interface'):
                for item in ng.interface.items_tree:
                    if not hasattr(item, 'name') or not item.name:
                        continue

                    if item.item_type == 'SOCKET' and extract_options.get('extract_node_sockets', True):
                        if item.name in ['Geometry', 'Shader', 'Image', 'Vector']:
                            continue

                        item_io_type = "Input" if item.in_out == 'INPUT' else "Output"
                        texts.append(ExtractedText(
                            text=item.name,
                            file_path=file_path,
                            line_number=0,
                            context='',
                            original_line=f"Node Group '{ng.name}' Socket {item_io_type}"
                        ))

                    elif item.item_type == 'PANEL' and extract_options.get('extract_node_panels', True):
                        texts.append(ExtractedText(
                            text=item.name,
                            file_path=file_path,
                            line_number=0,
                            context='',
                            original_line=f"Node Group '{ng.name}' Panel"
                        ))

        return texts

    def extract_from_json_file(self, file_path: str, json_keys=None) -> List[ExtractedText]:
        """从JSON文件递归提取所有字符串value，支持指定key过滤"""
        texts = []
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            print(f"无法读取或解析JSON文件 {file_path}: {e}")
            return []

        def recursive_extract(obj, parent_key=None):
            if isinstance(obj, str):
                if json_keys is None or (isinstance(parent_key, str) and parent_key in json_keys):
                    texts.append(ExtractedText(
                        text=obj,
                        file_path=file_path,
                        line_number=0,
                        context="",
                        original_line=""
                    ))
            elif isinstance(obj, dict):
                for k, v in obj.items():
                    recursive_extract(v, parent_key=k)
            elif isinstance(obj, list):
                for item in obj:
                    recursive_extract(item, parent_key=parent_key)

        recursive_extract(data)
        return texts

    def extract_from_directory(self, directory_path: str, recursive: bool = True,
                               extract_docstring: bool = False, extract_json: bool = False,
                               json_keys=None, filter_options: dict = None) -> List[ExtractedText]:
        """从目录中提取所有Python和（可选）JSON文件的文本，支持JSON key过滤"""
        all_texts = []
        py_pattern = os.path.join(directory_path, "**", "*.py") if recursive else os.path.join(directory_path, "*.py")
        python_files = glob.glob(py_pattern, recursive=recursive)
        for file_path in python_files:
            all_texts.extend(self.extract_from_file(
                file_path,
                extract_docstring=extract_docstring,
                filter_options=filter_options,
            ))

        if extract_json:
            json_pattern = os.path.join(directory_path, "**", "*.json") if recursive else os.path.join(directory_path, "*.json")
            json_files = glob.glob(json_pattern, recursive=recursive)
            for file_path in json_files:
                all_texts.extend(self.extract_from_json_file(file_path, json_keys=json_keys))

        return all_texts

    # ------------------------------------------------------------------
    # 文本清理 / 过滤
    # ------------------------------------------------------------------
    @staticmethod
    def _has_cjk(text: str) -> bool:
        return any('\u3400' <= ch <= '\u9fff' or '\uf900' <= ch <= '\ufaff' for ch in text)

    @staticmethod
    def _is_only_symbols(text: str) -> bool:
        """是否完全没有字母/数字/汉字（如 "---"、"..."、"✓"）。"""
        return not any(ch.isalnum() or TextExtractor._has_cjk(ch) for ch in text)

    @staticmethod
    def _is_pure_placeholder(text: str) -> bool:
        """判断文本是否只剩占位符/标点（例如 "{}"、"%s"、"---"）。"""
        stripped = re.sub(r'%[sdifoxXeEgGcrs]', '', text)
        stripped = re.sub(r'\{[^{}]*\}', '', stripped)
        return TextExtractor._is_only_symbols(stripped)

    @staticmethod
    def _is_path_or_url(text: str) -> bool:
        patterns = [
            r'^(https?|ftp|file)://',
            r'^([a-zA-Z]:[\\/]|/[^/]|\.{1,2}[\\/])',
            r'^-{1,2}[A-Za-z][\w-]*$',                     # --version
            r'^\.[A-Za-z0-9]{1,10}$',                       # .po / .blend
            r'\.(py|blend|json|xml|txt|md|yml|yaml|po|mo|zip|exe|dll|so|dylib)$',
        ]
        if any(re.match(p, text, re.IGNORECASE) for p in patterns):
            return True
        # 含占位符的路径模板，例如 f"{program_files}/gettext/bin/msgfmt.exe"
        if ('/' in text or '\\' in text) and re.search(
                r'\.(py|blend|json|xml|txt|md|yml|yaml|po|mo|zip|exe|dll|so|dylib)$',
                text, re.IGNORECASE):
            return True
        return False

    @staticmethod
    def _is_number_or_code_value(text: str, trusted: bool = False) -> bool:
        if text.isdigit():
            return True
        if re.fullmatch(r'\d+(\.\d+)?', text):
            return True
        if re.fullmatch(r'\d+\s*[xX]\s*\d+', text):            # 128 x 128
            return True
        if re.fullmatch(r'\d{4}-\d{2}-\d{2}', text):           # 日期
            return True
        if re.fullmatch(r'\d{2}:\d{2}(:\d{2})?', text):        # 时间
            return True
        if re.fullmatch(r'[\w.+-]+@[\w.-]+\.\w+', text):       # 邮箱
            return True
        # 颜色值只在上下文不明确时按“纯十六进制串”过滤，
        # 避免把 Add / Face / Cafe 这类正常单词误杀
        if text.startswith('#') and re.fullmatch(r'#[0-9A-Fa-f]{3,8}', text):
            return True
        if not trusted and re.fullmatch(r'[0-9A-Fa-f]{3,8}', text):
            return True
        return False

    @staticmethod
    def _looks_like_code_token(text: str) -> bool:
        """仅在上下文不明确时使用的保守判断，避免把代码标识符当词条。"""
        patterns = [
            r'^[a-zA-Z_][a-zA-Z0-9_]*$',                   # 纯标识符
            r'^bl_[a-z_]+$',                                # bl_idname 等
            r'^[A-Z_]+$',                                   # 常量
            r'^[a-z]+_[a-z_]*_[a-z]+$',                     # 技术命名
            r'^[a-z0-9]+(?:[._:-][a-z0-9]+)+$',             # utf-8 / gpt-4o-mini
            r'^[A-Z0-9]+(?:_[A-Z0-9]+)+$',                  # PO_TO_MO
            r'^[A-Za-z0-9._+-]+/[A-Za-z0-9._+-]+$',         # Qwen/Qwen2.5...
            r'^[A-Za-z][A-Za-z0-9]*:$',                      # Language:
            r'^[A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)+:$',   # PO 头字段 xxx-yyy:
            r'^[A-Za-z]+(?:-[A-Za-z]+){2,}$',               # Project-Id-Version
            r'^[A-Z][A-Za-z]*(?:-[A-Z][A-Za-z]*)+$',        # Last-Translator / Content-Type
        ]
        return any(re.match(p, text) for p in patterns)

    @staticmethod
    def _looks_like_regex(text: str) -> bool:
        """判断字符串是否像正则表达式（只在上下文不明确时启用）。"""
        if not text or TextExtractor._has_cjk(text):
            return False
        if any(ch.isspace() for ch in text):
            return False
        return bool(re.search(r'[\^$\\|?*+\[\]{}()]', text))

    @staticmethod
    def _clean_text(text: str, context: str = "", filter_options: dict = None,
                    trusted: bool = False) -> str:
        """
        文本清理和过滤。

        trusted=True 表明确认字符串来自界面文本位置（如 text=、bl_label=、report 等），
        此时只剔除明显不是自然语言的取值，不再使用变量名/特殊字符规则误杀。
        """
        if not text:
            return ""

        text = text.strip()
        if not text:
            return ""

        if text in ['True', 'False', 'None']:
            return ""
        if TextExtractor._is_number_or_code_value(text, trusted=trusted):
            return ""
        if TextExtractor._is_path_or_url(text):
            return ""
        if TextExtractor._is_only_symbols(text):
            return ""

        # 单字符（纯 ASCII）通常不是可翻译文本；单个汉字仍保留
        if len(text) < 2 and not TextExtractor._has_cjk(text):
            return ""

        if trusted:
            if TextExtractor._is_pure_placeholder(text):
                return ""
            # 界面文本上限放宽，避免长工具提示被丢弃
            if len(text) > 4000:
                return ""
            return text

        # ---------------- 以下只针对上下文不明确的普通容器/注释 ----------------
        if filter_options is None:
            filter_options = {
                'filter_variables': True,
                'filter_keywords': True,
                'filter_tech_ids': True,
                'filter_format_placeholders': True,
                'filter_paths_urls': True,
                'filter_data_keys': True,
                'filter_special_chars': True,
                'filter_repetitive': True,
            }

        code_keywords = {
            'if', 'else', 'elif', 'for', 'while', 'def', 'class', 'import', 'from',
            'return', 'yield', 'break', 'continue', 'pass', 'try', 'except', 'finally',
            'with', 'as', 'lambda', 'and', 'or', 'not', 'in', 'is', 'True', 'False',
            'None', 'self', 'cls', 'super', 'property', 'staticmethod', 'classmethod',
            'async', 'await', 'global', 'nonlocal', 'assert', 'del', 'raise'
        }
        if filter_options.get('filter_keywords', True) and text in code_keywords:
            return ""

        if filter_options.get('filter_variables', True) or filter_options.get('filter_tech_ids', True):
            if TextExtractor._looks_like_code_token(text):
                return ""

        if filter_options.get('filter_paths_urls', True) and TextExtractor._is_path_or_url(text):
            return ""

        if filter_options.get('filter_format_placeholders', True) and TextExtractor._is_pure_placeholder(text):
            return ""

        if filter_options.get('filter_tech_ids', True) and TextExtractor._looks_like_regex(text):
            return ""

        if filter_options.get('filter_special_chars', True):
            meaningful = sum(1 for ch in text if ch.isalnum() or TextExtractor._has_cjk(ch))
            if meaningful < max(1, len(text) * 0.3):
                return ""

        if len(text) > 500:
            return ""

        if filter_options.get('filter_repetitive', True) and len(text) >= 4:
            char_counts = {}
            for char in text:
                char_counts[char] = char_counts.get(char, 0) + 1
            if max(char_counts.values()) > len(text) * 0.6:
                return ""

        return text

    # ------------------------------------------------------------------
    # 去重
    # ------------------------------------------------------------------
    def get_unique_texts(self, texts: List[ExtractedText]) -> List[ExtractedText]:
        """获取去重后的文本列表，保留第一次出现的位置信息"""
        unique_map = {}
        for text_obj in texts:
            key = (text_obj.text, text_obj.context)
            if text_obj.text and key not in unique_map:
                unique_map[key] = text_obj
        return list(unique_map.values())

    def extract_from_current_blend(self, extract_options: dict = None) -> List[ExtractedText]:
        """直接从当前打开的Blend文件中提取资产和节点组接口名称"""
        import bpy

        if extract_options is None:
            extract_options = {
                'extract_objects': True,
                'extract_materials': True,
                'extract_worlds': True,
                'extract_collections': True,
                'extract_textures': True,
                'extract_images': True,
                'extract_node_groups': True,
                'extract_node_sockets': True,
                'extract_node_panels': True,
            }

        texts = []
        data_block_mapping = [
            ('objects', 'Object', 'extract_objects'),
            ('materials', 'Material', 'extract_materials'),
            ('worlds', 'World', 'extract_worlds'),
            ('collections', 'Collection', 'extract_collections'),
            ('textures', 'Texture', 'extract_textures'),
            ('images', 'Image', 'extract_images'),
            ('node_groups', 'NodeGroup', 'extract_node_groups'),
        ]

        for attr, block_type, option_key in data_block_mapping:
            if extract_options.get(option_key, True):
                for item in getattr(bpy.data, attr, []):
                    if hasattr(item, 'name') and item.name:
                        texts.append(ExtractedText(
                            text=item.name,
                            file_path=bpy.data.filepath or "<current>",
                            line_number=0,
                            context='',
                            original_line=f"Data-block Name ({block_type})"
                        ))

        if extract_options.get('extract_node_sockets', True) or extract_options.get('extract_node_panels', True):
            for ng in getattr(bpy.data, 'node_groups', []):
                if not ng:
                    continue
                if hasattr(ng, 'interface'):
                    for item in ng.interface.items_tree:
                        if not hasattr(item, 'name') or not item.name:
                            continue
                        if item.item_type == 'SOCKET' and extract_options.get('extract_node_sockets', True):
                            if item.name in ['Geometry', 'Shader', 'Image', 'Vector']:
                                continue
                            item_io_type = "Input" if getattr(item, 'in_out', '') == 'INPUT' else "Output"
                            texts.append(ExtractedText(
                                text=item.name,
                                file_path=bpy.data.filepath or "<current>",
                                line_number=0,
                                context='',
                                original_line=f"Node Group '{ng.name}' Socket {item_io_type}"
                            ))
                        elif item.item_type == 'PANEL' and extract_options.get('extract_node_panels', True):
                            texts.append(ExtractedText(
                                text=item.name,
                                file_path=bpy.data.filepath or "<current>",
                                line_number=0,
                                context='',
                                original_line=f"Node Group '{ng.name}' Panel"
                            ))
        return texts

    # ------------------------------------------------------------------
    # AST 访问器
    # ------------------------------------------------------------------
    class TextVisitor(ast.NodeVisitor):
        """AST节点访问器，用于遍历语法树并提取文本。"""

        # 自定义 UI 辅助函数：所有字符串参数都按界面文本处理
        UI_FUNC_NAMES = {"draw_prop"}

        # 标准 Blender UI 函数中“文本”所在的位置参数索引
        UI_POSITIONAL_TEXT_ARGS = {
            'label': (0,),
            'operator': (1,),
            'prop': (2,),
            'prop_enum': (3,),
            'prop_search': (4,),
            'menu': (1,),
            'menu_contents': (1,),
            'popover': (1,),
            'operator_menu_enum': (2,),
        }

        # gettext / pgettext 系列函数中 msgid 所在的位置
        GETTEXT_ARG_INDEXES = {
            'gettext': (0,),
            '_': (0,),
            'pgettext': (1,),
            'pgettext_iface': (1,),
            'pgettext_tip': (1,),
            'pgettext_rtl': (1,),
            'pgettext_data': (1,),
            'dgettext': (1,),
            'ngettext': (0, 1),
            'dngettext': (1, 2),
        }

        # 这些 key 一出现就说明字符串是界面文本，跳过代码噪声过滤
        # 注意：name 不在此集合中——name= 在非 bpy.props 调用里可能只是技术名称，
        # 由调用方显式传入 trusted=True 决定。
        TRUSTED_CONTEXT_KEYS = {
            'bl_label', 'bl_description', 'bl_category', 'description',
            'warning', 'text', 'title', 'label', 'report', 'enum_label',
            'enum_desc', 'docstring', 'gettext',
        }

        DICT_TEXT_KEYS = {
            'Description', 'description', 'desc', 'label', 'text', 'title',
            'name', 'tooltip', 'warning', 'message', 'msg', 'error',
            'error_msg', 'info',
        }

        # 赋值目标名包含这些词时，认为右侧字符串是界面文本
        # （例如 tool_display = "..."、filter_title = "..."、self.error = f"..."）
        # 赋值目标名包含这些词时，认为右侧字符串是界面文本
        # （例如 tool_display = "..."、filter_title = "..."、self.error = f"..."）
        UI_ASSIGN_NAME_TOKENS = frozenset({
            'label', 'labels', 'text', 'texts', 'title', 'titles',
            'desc', 'description', 'descriptions', 'message', 'messages',
            'msg', 'msgs', 'tooltip', 'tooltips', 'hint',
            'info', 'display', 'caption', 'captions', 'error', 'errors',
            'warning', 'warnings', 'tip', 'tips', 'notice', 'notices',
        })

        # 赋值目标名包含这些词且右侧是列表/元组时，把其中的字符串视为界面文本
        # （例如 MENU_ITEMS = ["Apply", "Cancel"]）
        UI_CONTAINER_NAME_TOKENS = frozenset({
            'items', 'menu', 'menus', 'choice', 'choices', 'option', 'options',
            'label', 'labels', 'title', 'titles', 'desc', 'description',
            'command', 'commands', 'mode', 'modes', 'preset', 'presets',
            'category', 'categories', 'tab', 'tabs', 'button', 'buttons',
            'entry', 'entries', 'enum', 'enums', 'tooltip', 'tooltips',
            'hint', 'message', 'messages', 'error', 'errors',
            'info', 'display', 'caption', 'captions', 'tip', 'tips',
            'notice', 'notices',
        })

        def __init__(self, file_path: str, patterns: set, extract_docstring: bool = False,
                     filter_options: dict = None):
            self.file_path = file_path
            self.patterns = patterns
            self.texts: List[ExtractedText] = []
            self.class_stack: List[ast.ClassDef] = []
            self.function_stack: List[str] = []
            self.extract_docstring = extract_docstring
            self.filter_options = filter_options
            self.constants = {}
            # 常量作用域栈：模块级 + 类级，支持 text=self.LABEL / items=Class.ITEMS
            self.scopes = [self.constants]

        # ---------------- 基础工具 ----------------
        def _is_in_operator_class(self) -> bool:
            if not self.class_stack:
                return False

            current_class = self.class_stack[-1]
            for base in current_class.bases:
                if isinstance(base, ast.Name) and base.id == 'Operator':
                    return True
                if isinstance(base, ast.Attribute):
                    if isinstance(base.value, ast.Name) and base.value.id == 'types' and base.attr == 'Operator':
                        return True
                    if base.attr.endswith('Operator'):
                        return True
            return False

        def _determine_final_context(self, original_key: str, is_operator_call: bool) -> str:
            """根据代码上下文决定 msgctxt"""
            if (original_key == 'bl_label' and self._is_in_operator_class()) or is_operator_call:
                return 'Operator'
            return ""

        @staticmethod
        def _unparse(node: ast.AST) -> str:
            try:
                return ast.unparse(node)
            except Exception:
                return "value"

        def _joinedstr_to_text(self, node: ast.JoinedStr) -> str:
            """把 f-string 还原成带 {占位符} 的模板文本。"""
            parts = []
            for value in node.values:
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    parts.append(value.value)
                elif isinstance(value, ast.FormattedValue):
                    expr = self._unparse(value.value)
                    if expr.startswith('self.'):
                        expr = expr[5:]
                    elif expr.startswith('cls.'):
                        expr = expr[4:]
                    parts.append('{' + expr + '}')
            return ''.join(parts)

        def _resolve_string(self, node: ast.AST, depth: int = 0):
            """
            尽量把一个表达式还原成可翻译文本：
            - 普通字符串
            - f-string -> "{name}" 形式
            - "..." % (...)
            - "..." + "..."
            - "...".format(...)
            - 模块级/类级字符串常量引用（含 self.LABEL）
            - 常量列表/元组/字典的下标
            无法还原时返回 None。
            """
            if node is None or depth > 10:
                return None

            if isinstance(node, ast.Constant):
                return node.value if isinstance(node.value, str) else None
            if isinstance(node, ast.Str):  # Python < 3.8 兼容
                return node.s
            if isinstance(node, ast.JoinedStr):
                return self._joinedstr_to_text(node)

            if isinstance(node, ast.BinOp):
                if isinstance(node.op, ast.Mod):
                    return self._resolve_string(node.left, depth + 1)
                if isinstance(node.op, ast.Add):
                    left = self._resolve_string(node.left, depth + 1)
                    right = self._resolve_string(node.right, depth + 1)
                    if left is not None or right is not None:
                        if left is None:
                            left = '{' + self._unparse(node.left) + '}'
                        if right is None:
                            right = '{' + self._unparse(node.right) + '}'
                        return left + right

            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute) and node.func.attr == 'format':
                    return self._resolve_string(node.func.value, depth + 1)

            if isinstance(node, ast.Name):
                value = self._lookup_constant(node.id)
                if value is not None:
                    return self._resolve_string(value, depth + 1)

            if isinstance(node, ast.Attribute):
                # self.LABEL / cls.LABEL
                if isinstance(node.value, ast.Name) and node.value.id in ('self', 'cls'):
                    value = self._lookup_constant(node.attr)
                    if value is not None:
                        return self._resolve_string(value, depth + 1)

            if isinstance(node, ast.Subscript):
                resolved = self._resolve_node(node, depth + 1)
                if resolved is not node:
                    return self._resolve_string(resolved, depth + 1)

            return None

        def _lookup_constant(self, name: str):
            for scope in reversed(self.scopes):
                if name in scope:
                    return scope[name]
            return None

        def _resolve_node(self, node: ast.AST, depth: int = 0) -> ast.AST:
            """把常量名解析成其真实表达式节点（用于 items=常量 的情况）。"""
            if depth >= 10:
                return node
            if isinstance(node, ast.Name):
                value = self._lookup_constant(node.id)
                if value is not None:
                    return self._resolve_node(value, depth + 1)
            elif isinstance(node, ast.Attribute):
                if isinstance(node.value, ast.Name) and node.value.id in ('self', 'cls'):
                    value = self._lookup_constant(node.attr)
                    if value is not None:
                        return self._resolve_node(value, depth + 1)
            elif isinstance(node, ast.Subscript):
                base = self._resolve_node(node.value, depth + 1)
                index = node.slice
                if isinstance(index, ast.Index):  # Python 3.8 兼容
                    index = index.value
                if isinstance(index, ast.Constant) and isinstance(index.value, int) \
                        and isinstance(base, (ast.List, ast.Tuple)):
                    i = index.value
                    if 0 <= i < len(base.elts):
                        return self._resolve_node(base.elts[i], depth + 1)
                if isinstance(index, ast.Constant) and isinstance(index.value, str) \
                        and isinstance(base, ast.Dict):
                    for key, value in zip(base.keys, base.values):
                        if isinstance(key, ast.Constant) and key.value == index.value:
                            return self._resolve_node(value, depth + 1)
            return node

        def _add_text(self, text: str, node: ast.AST, context_key: str,
                      is_operator_call: bool = False, trusted: bool = False):
            if not text:
                return

            if context_key in self.TRUSTED_CONTEXT_KEYS or context_key.startswith('dict.'):
                trusted = True

            final_context = self._determine_final_context(context_key, is_operator_call)
            cleaned_text = TextExtractor._clean_text(
                text, final_context, self.filter_options, trusted=trusted
            )
            if cleaned_text:
                self.texts.append(ExtractedText(
                    text=cleaned_text,
                    file_path=self.file_path,
                    line_number=getattr(node, 'lineno', 0),
                    context=final_context,
                    original_line=""
                ))

        def _add_text_from_node(self, node: ast.AST, context_key: str,
                                trusted: bool = True, is_operator_call: bool = False):
            """处理三元表达式/布尔表达式，尽量把每个分支的文本都提取出来。"""
            if isinstance(node, ast.IfExp):
                self._add_text_from_node(node.body, context_key, trusted, is_operator_call)
                self._add_text_from_node(node.orelse, context_key, trusted, is_operator_call)
                return
            if isinstance(node, ast.BoolOp):
                for value in node.values:
                    self._add_text_from_node(value, context_key, trusted, is_operator_call)
                return

            text = self._resolve_string(node)
            if text is not None:
                self._add_text(
                    text, node, context_key,
                    is_operator_call=is_operator_call, trusted=trusted
                )

            # f-string 内嵌字符串分支，例如 f"{'启用' if x else '禁用'}"
            if trusted and isinstance(node, ast.JoinedStr):
                self._extract_embedded_fstring_strings(node, context_key, is_operator_call)

        def _extract_embedded_fstring_strings(self, node: ast.JoinedStr,
                                              context_key: str,
                                              is_operator_call: bool = False):
            for value in node.values:
                if not isinstance(value, ast.FormattedValue):
                    continue

                # 条件表达式分支：f"{'On' if enabled else 'Off'}"
                if isinstance(value.value, ast.IfExp):
                    self._add_text_from_node(value.value, context_key, trusted=True)

                for sub in ast.walk(value.value):
                    if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                        s = sub.value
                        # 只提取明确像自然语言的片段，避免把 dict 键等技术字符串带进来
                        if TextExtractor._has_cjk(s) or any(ch.isspace() for ch in s):
                            self._add_text(
                                s, sub, context_key,
                                is_operator_call=is_operator_call, trusted=True
                            )

        @staticmethod
        def _name_tokens(name: str):
            if not name:
                return []
            # snake_case / kebab-case / PascalCase / camelCase 统一拆词
            name = re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', name)
            return [token.lower() for token in re.split(r'[^A-Za-z0-9]+', name) if token]

        @classmethod
        def _looks_like_ui_assign_name(cls, name: str) -> bool:
            return bool(set(cls._name_tokens(name)) & cls.UI_ASSIGN_NAME_TOKENS)

        @classmethod
        def _looks_like_ui_container_name(cls, name: str) -> bool:
            return bool(set(cls._name_tokens(name)) & cls.UI_CONTAINER_NAME_TOKENS)

        def _extract_ui_container(self, node: ast.AST, context_key: str):
            """提取界面用列表/元组中的文本（MENU_ITEMS、CHOICES 等）。"""
            if not isinstance(node, (ast.List, ast.Tuple)):
                return
            for elt in node.elts:
                if isinstance(elt, (ast.Tuple, ast.List)):
                    self._extract_enum_tuple(elt, trusted=True)
                else:
                    self._add_text_from_node(elt, context_key, trusted=True)

        def _extract_enum_tuple(self, elt: ast.AST, trusted: bool = True):
            """提取单个 (value, label, description) 枚举项。"""
            if not isinstance(elt, (ast.Tuple, ast.List)) or len(elt.elts) < 2:
                return
            self._add_text_from_node(elt.elts[1], 'enum_label', trusted=trusted)
            if len(elt.elts) >= 3:
                self._add_text_from_node(elt.elts[2], 'enum_desc', trusted=trusted)

        def _collect_constants(self, node: ast.Module):
            self.constants.update(self._collect_scoped_assignments(node.body))

        @staticmethod
        def _collect_scoped_assignments(body) -> dict:
            scope = {}
            for stmt in body:
                if isinstance(stmt, ast.Assign):
                    for target in stmt.targets:
                        if isinstance(target, ast.Name):
                            scope[target.id] = stmt.value
                elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                    if stmt.value is not None:
                        scope[stmt.target.id] = stmt.value
            return scope

        def _extract_enum_items(self, node: ast.AST, trusted: bool = True):
            """提取 EnumProperty(items=...) 中的 label / description。"""
            node = self._resolve_node(node)

            if isinstance(node, (ast.List, ast.Tuple)):
                for elt in node.elts:
                    self._extract_enum_tuple(elt, trusted=trusted)

            elif isinstance(node, ast.ListComp):
                # 例如 items=[(key, label, ...) for key, label, ... in PRESETS]
                for gen in node.generators:
                    source = self._resolve_node(gen.iter)
                    if isinstance(source, (ast.List, ast.Tuple)):
                        self._extract_enum_items(source, trusted=trusted)

                elt = node.elt
                if isinstance(elt, ast.Tuple) and len(elt.elts) >= 3:
                    self._add_text_from_node(elt.elts[2], 'enum_desc', trusted=trusted)

        # ---------------- 节点访问 ----------------
        def visit_Module(self, node: ast.Module):
            self._collect_constants(node)

            if self.extract_docstring:
                docstring = ast.get_docstring(node)
                if docstring:
                    if node.body and isinstance(node.body[0], ast.Expr):
                        self._add_text(docstring, node.body[0], 'docstring', trusted=True)

            self.generic_visit(node)

        def visit_ClassDef(self, node: ast.ClassDef):
            self.class_stack.append(node)
            self.scopes.append(self._collect_scoped_assignments(node.body))
            if self.extract_docstring:
                docstring = ast.get_docstring(node)
                if docstring:
                    self._add_text(docstring, node, 'docstring', trusted=True)
            self.generic_visit(node)
            self.scopes.pop()
            self.class_stack.pop()

        def visit_FunctionDef(self, node: ast.FunctionDef):
            self.function_stack.append(node.name)
            if self.extract_docstring:
                docstring = ast.get_docstring(node)
                if docstring:
                    self._add_text(docstring, node, 'docstring', trusted=True)
            self.generic_visit(node)
            self.function_stack.pop()

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
            self.function_stack.append(node.name)
            if self.extract_docstring:
                docstring = ast.get_docstring(node)
                if docstring:
                    self._add_text(docstring, node, 'docstring', trusted=True)
            self.generic_visit(node)
            self.function_stack.pop()

        def visit_Return(self, node: ast.Return):
            # 辅助函数直接返回界面文本时也能提取
            if node.value is not None:
                func_name = self.function_stack[-1].lower() if self.function_stack else ''
                trusted = any(hint in func_name for hint in (
                    'label', 'text', 'name', 'desc', 'title',
                    'tooltip', 'message', 'msg', 'error', 'info', 'display',
                ))
                self._add_text_from_node(node.value, 'return', trusted=trusted)
            self.generic_visit(node)

        def visit_Raise(self, node: ast.Raise):
            # raise ValueError("提示信息") / raise RuntimeError(f"...")
            # 这些消息通常会被调用方 report 给用户
            if isinstance(node.exc, ast.Call):
                for arg in node.exc.args:
                    self._add_text_from_node(arg, 'raise', trusted=True)
            elif node.exc is not None:
                self._add_text_from_node(node.exc, 'raise', trusted=True)
            self.generic_visit(node)

        def visit_Assign(self, node: ast.Assign):
            for target in node.targets:
                key = None
                if isinstance(target, ast.Name):
                    key = target.id
                elif isinstance(target, ast.Attribute):
                    key = target.attr

                if isinstance(node.value, (ast.List, ast.Tuple)) \
                        and self._looks_like_ui_container_name(key):
                    self._extract_ui_container(node.value, key)
                elif key in self.patterns or self._looks_like_ui_assign_name(key):
                    self._add_text_from_node(node.value, key, trusted=True)

            self.generic_visit(node)

        def visit_AnnAssign(self, node: ast.AnnAssign):
            key = None
            if isinstance(node.target, ast.Name):
                key = node.target.id
            elif isinstance(node.target, ast.Attribute):
                key = node.target.attr
            if node.value is not None:
                if isinstance(node.value, (ast.List, ast.Tuple)) \
                        and self._looks_like_ui_container_name(key):
                    self._extract_ui_container(node.value, key)
                elif key in self.patterns or self._looks_like_ui_assign_name(key):
                    self._add_text_from_node(node.value, key, trusted=True)
            self.generic_visit(node)

        def visit_Call(self, node: ast.Call):
            func_name = ""
            if isinstance(node.func, ast.Name):
                func_name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                func_name = node.func.attr

            is_operator_call = func_name == 'operator'

            # 1) 标准关键字参数：text= / name= / description= / bl_label= ...
            for kw in node.keywords:
                if kw.arg and kw.arg in self.patterns:
                    # name= 在非 bpy.props 调用中可能只是技术名称
                    # （如 keymaps.new(name='Window')），此时按普通上下文过滤
                    kw_trusted = True
                    if kw.arg == 'name' and not func_name.endswith('Property'):
                        kw_trusted = False
                    self._add_text_from_node(
                        kw.value, kw.arg,
                        trusted=kw_trusted, is_operator_call=is_operator_call,
                    )

            # 2) EnumProperty / BoolProperty 等 items 参数
            for kw in node.keywords:
                if kw.arg == 'items':
                    self._extract_enum_items(kw.value)

            # 3) self.report({'INFO'}, "xxx")
            if func_name == 'report' and len(node.args) >= 2:
                self._add_text_from_node(node.args[1], 'report', trusted=True)

            # 4) gettext / pgettext 系列
            for index in self.GETTEXT_ARG_INDEXES.get(func_name, ()):
                if index < len(node.args):
                    self._add_text_from_node(node.args[index], 'gettext', trusted=True)

            # 5) Blender UI 函数的位置参数（如 layout.operator("id", "按钮文字")）
            for index in self.UI_POSITIONAL_TEXT_ARGS.get(func_name, ()):
                if index < len(node.args):
                    self._add_text_from_node(
                        node.args[index], func_name,
                        trusted=True, is_operator_call=is_operator_call,
                    )

            # 6) 自定义 UI 辅助函数：所有字符串参数都提取
            if func_name in self.UI_FUNC_NAMES:
                for arg in node.args:
                    self._add_text_from_node(arg, func_name, trusted=True)
                for kw in node.keywords:
                    self._add_text_from_node(kw.value, f"{func_name}.{kw.arg}", trusted=True)

            self.generic_visit(node)

        def visit_Dict(self, node: ast.Dict):
            for key, value in zip(node.keys, node.values):
                key_str = None
                if isinstance(key, ast.Str):
                    key_str = key.s
                elif hasattr(key, 'value') and isinstance(key.value, str):
                    key_str = key.value

                if key_str in self.DICT_TEXT_KEYS and value is not None:
                    self._add_text_from_node(value, f'dict.{key_str}', trusted=True)

                if value is not None:
                    self.visit(value)

        def visit_List(self, node: ast.List):
            for elt in node.elts:
                if isinstance(elt, (ast.List, ast.Tuple, ast.Dict, ast.Set,
                                    ast.ListComp, ast.DictComp)):
                    self.visit(elt)
                else:
                    self._add_text_from_node(elt, 'list_or_tuple', trusted=False)
                    if isinstance(elt, ast.Call):
                        self.visit(elt)

        def visit_Tuple(self, node: ast.Tuple):
            for elt in node.elts:
                if isinstance(elt, (ast.List, ast.Tuple, ast.Dict, ast.Set,
                                    ast.ListComp, ast.DictComp)):
                    self.visit(elt)
                else:
                    self._add_text_from_node(elt, 'list_or_tuple', trusted=False)
                    if isinstance(elt, ast.Call):
                        self.visit(elt)
