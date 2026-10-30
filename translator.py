# -*- coding: utf-8 -*-
"""
翻译服务模块。

提供通用大模型翻译器 OpenAICompatibleTranslator，兼容任何
OpenAI Chat Completions 接口。只需要三个核心参数：
服务地址(Base URL)、API Key、模型名称，即可接入 OpenAI、DeepSeek、
通义千问、豆包、Ollama、LM Studio、OpenRouter、硅基流动、Moonshot、
智谱、Gemini、Groq 等任意兼容服务商。
"""
import json
import random
import re
import urllib.error
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod

# 批量翻译时用于分隔多条词条的唯一标记。
# 单独定义成模块级常量，避免 UI 层为了拿分隔符而实例化翻译器。
SEPARATOR = "|||~|||"


class BaseTranslator(ABC):
    """翻译器接口基类"""
    def __init__(self, **kwargs):
        pass

    @abstractmethod
    def translate(self, query: str, from_lang: str = 'en', to_lang: str = 'zh') -> dict:
        """
        执行翻译

        :param query: 要翻译的文本
        :param from_lang: 源语言代码 (例如 'en')
        :param to_lang: 目标语言代码 (例如 'zh')
        :return: 一个包含翻译结果或错误的字典
        """
        pass

    @abstractmethod
    def validate(self) -> (bool, str):
        """
        验证API凭证的有效性。

        :return: 一个元组 (is_valid, message)
        """
        pass


def _extract_api_error(raw: str) -> str:
    """从服务商返回的错误响应中尽量提取可读的错误信息。"""
    raw = (raw or '').strip()
    if not raw:
        return '未知错误'
    try:
        data = json.loads(raw)
    except Exception:
        return raw[:500]

    if isinstance(data, dict):
        error = data.get('error')
        if isinstance(error, dict):
            message = error.get('message') or error.get('msg') or error.get('type')
            if message:
                return str(message)
            return json.dumps(error, ensure_ascii=False)[:500]
        if isinstance(error, str) and error:
            return error
        for key in ('message', 'msg', 'detail', 'error_msg'):
            value = data.get(key)
            if value:
                if isinstance(value, (dict, list)):
                    return json.dumps(value, ensure_ascii=False)[:500]
                return str(value)
    return json.dumps(data, ensure_ascii=False)[:500]


class LLMTranslator(BaseTranslator):
    """大语言模型翻译器的通用逻辑：提示词构造、返回解析、结果校验。"""

    SEPARATOR = SEPARATOR

    # 语言代码 -> 提示词中使用的自然语言名称
    LANG_NAMES = {
        'en': 'English',
        'zh': 'Simplified Chinese',
        'zh_hans': 'Simplified Chinese',
        'zh_hant': 'Traditional Chinese',
        'zh_tw': 'Traditional Chinese',
        'ja': 'Japanese',
        'ko': 'Korean',
        'fr': 'French',
        'de': 'German',
        'es': 'Spanish',
        'ru': 'Russian',
        'pt': 'Portuguese',
        'it': 'Italian',
    }

    def __init__(self, api_key: str = ""):
        super().__init__()
        self.api_key = (api_key or "").strip()

    def _build_prompts(self, text: str, from_lang: str, to_lang: str):
        """返回 (system_prompt, user_prompt)。"""
        from_name = self.LANG_NAMES.get((from_lang or '').lower(), from_lang)
        to_name = self.LANG_NAMES.get((to_lang or '').lower(), to_lang)

        system_prompt = (
            "You are a professional translation engine for Blender (3D software) "
            "UI strings and documentation. Always use the official Blender glossary "
            "and community-standard terminology when a term has an established "
            "Blender translation. Never add explanations, notes, quotes, markdown "
            "or any extra content."
        )
        user_prompt = (
            f"Translate the following text from {from_name} to {to_name}. "
            f"The text may contain multiple segments separated by '{self.SEPARATOR}'. "
            "Keep every separator exactly as-is, in the same order, and translate "
            "only the content between separators. "
            "Preserve placeholders and formatting exactly (for example %s, %d, {}, "
            "{name}, \\n, escaped quotes and leading/trailing spaces). "
            "Return only the translated text.\n"
            "---\n"
            f"{text}\n"
            "---"
        )
        return system_prompt, user_prompt

    def _parse_translation(self, query: str, content: str) -> dict:
        """把大模型返回的内容按分隔符还原成逐条结果。"""
        cleaned_content = (content or '').strip()

        # 去掉提示词要求的外层 --- 分隔线（只处理成对出现的分隔线，
        # 避免误删译文本身以 "-" 开头/结尾的内容）
        if cleaned_content.startswith('---') and cleaned_content.endswith('---') \
                and len(cleaned_content) > 6:
            cleaned_content = cleaned_content[3:-3].strip()

        # 去掉部分模型额外包裹的 markdown 代码块
        if cleaned_content.startswith('```') and cleaned_content.endswith('```'):
            cleaned_content = re.sub(r'^```[^\n]*\n?', '', cleaned_content)
            cleaned_content = re.sub(r'\n?```$', '', cleaned_content).strip()

        original_lines = query.split(self.SEPARATOR)
        translated_lines = cleaned_content.split(self.SEPARATOR)

        if len(original_lines) != len(translated_lines):
            # 行数不一致时无法可靠对齐，返回整块结果交给用户处理
            return {
                'trans_result': [{
                    'src': query.replace(self.SEPARATOR, '\n'),
                    'dst': cleaned_content,
                }]
            }

        return {
            'trans_result': [
                {'src': src, 'dst': dst.strip()}
                for src, dst in zip(original_lines, translated_lines)
            ]
        }

    def validate(self) -> (bool, str):
        """通过一次真实翻译请求验证服务是否可用。"""
        test_query = f"Test. Random number: {random.randint(0, 1000)}"
        result = self.translate(test_query, from_lang='en', to_lang='zh')

        if 'trans_result' in result and result['trans_result']:
            translated_text = result['trans_result'][0].get('dst', '')
            if translated_text and translated_text.strip():
                return True, "API验证成功！"
            return False, "验证失败：API返回了空的翻译结果。"

        return False, f"验证失败: {result.get('error_msg', '未知错误')}"


class OpenAICompatibleTranslator(LLMTranslator):
    """
    通用大模型翻译器（OpenAI Chat Completions 兼容接口）。

    只要服务商支持 POST {base_url}/chat/completions，即可直接使用：
      - OpenAI:        https://api.openai.com/v1
      - DeepSeek:      https://api.deepseek.com/v1
      - 通义千问:      https://dashscope.aliyuncs.com/compatible-mode/v1
      - 豆包/方舟:     https://ark.cn-beijing.volces.com/api/v3
      - Ollama:        http://localhost:11434/v1
      - LM Studio:     http://localhost:1234/v1
      - OpenRouter:    https://openrouter.ai/api/v1
      - 硅基流动:      https://api.siliconflow.cn/v1
      ...
    """

    def __init__(self, base_url: str, api_key: str = "", model_name: str = "",
                 custom_headers: dict = None, extra_body: dict = None,
                 timeout: int = 60):
        super().__init__(api_key)
        self.base_url = (base_url or "").strip()
        self.model_name = (model_name or "").strip()
        self.custom_headers = dict(custom_headers or {})
        self.extra_body = dict(extra_body or {})
        try:
            timeout = int(timeout)
        except (TypeError, ValueError):
            timeout = 60
        self.timeout = max(5, min(timeout, 600))

    # ---- URL 处理 ---------------------------------------------------------
    def _normalize_base(self) -> str:
        """补全协议，并去掉末尾多余的斜杠。"""
        base = self.base_url.strip()
        if not base:
            return ""
        if not re.match(r'^https?://', base, re.IGNORECASE):
            base = 'https://' + base
        return base

    def chat_url(self) -> str:
        """推导出 /chat/completions 完整地址。"""
        base = self._normalize_base()
        if not base:
            return ""

        parts = urllib.parse.urlsplit(base)
        path = parts.path.rstrip('/')

        # 用户直接填写了完整的 chat/completions 地址（兼容 Azure 等带查询参数的地址）
        if path.endswith('/chat/completions'):
            return urllib.parse.urlunsplit(
                (parts.scheme, parts.netloc, parts.path, parts.query, '')
            )

        # 没写路径时默认补 /v1（OpenAI / DeepSeek / Ollama 等的通行约定）
        if not path:
            path = '/v1/chat/completions'
        else:
            path = path + '/chat/completions'

        return urllib.parse.urlunsplit(
            (parts.scheme, parts.netloc, path, parts.query, '')
        )

    def models_url(self) -> str:
        """推导出 /models 地址（用于获取模型列表）。"""
        chat = self.chat_url()
        if not chat:
            return ""
        parts = urllib.parse.urlsplit(chat)
        path = parts.path.rstrip('/')
        if path.endswith('/chat/completions'):
            path = path[:-len('/chat/completions')] + '/models'
        else:
            path = path + '/models'
        return urllib.parse.urlunsplit(
            (parts.scheme, parts.netloc, path, parts.query, '')
        )

    # ---- HTTP ------------------------------------------------------------
    def _build_headers(self) -> dict:
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        }
        if self.api_key:
            auth = self.api_key
            if not auth.lower().startswith('bearer '):
                auth = f'Bearer {auth}'
            headers['Authorization'] = auth

        # 自定义请求头优先级最高（可覆盖 Authorization，例如 Azure 的 api-key）
        for name, value in self.custom_headers.items():
            name = str(name).strip()
            if name:
                headers[name] = str(value)
        return headers

    def _request(self, url: str, method: str = 'GET', payload: dict = None):
        """发送请求，返回 (status_code, response_text)。网络错误抛出 ConnectionError。"""
        data = None
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode('utf-8')

        request = urllib.request.Request(
            url, data=data, headers=self._build_headers(), method=method
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode('utf-8', errors='replace')
                return response.getcode(), raw
        except urllib.error.HTTPError as e:
            raw = e.read().decode('utf-8', errors='replace') if e.fp else str(e)
            return e.code, raw
        except urllib.error.URLError as e:
            raise ConnectionError(f"无法连接到 {url}：{e.reason}")
        except Exception as e:
            raise ConnectionError(f"请求 {url} 失败：{e}")

    @staticmethod
    def _extract_content(data: dict):
        """从不同服务商的响应结构中提取正文。"""
        try:
            choices = data.get('choices') or []
            if not choices:
                return None
            choice = choices[0] or {}
            message = choice.get('message') or {}
            content = message.get('content')
            if content is None:
                # 部分兼容接口沿用 completions 的 text 字段
                content = choice.get('text')
            if isinstance(content, list):
                # 部分服务商把 content 返回成分段数组
                parts = []
                for part in content:
                    if isinstance(part, dict):
                        parts.append(part.get('text') or part.get('content') or '')
                    else:
                        parts.append(str(part))
                content = ''.join(parts)
            if content is None:
                return None
            return str(content)
        except Exception:
            return None

    # ---- 公共接口 --------------------------------------------------------
    def translate(self, query: str, from_lang: str = 'en', to_lang: str = 'zh') -> dict:
        if not self.base_url:
            return {'error_msg': '服务地址（Base URL）未配置'}
        if not self.model_name:
            return {'error_msg': '模型名称未配置'}

        url = self.chat_url()
        if not url:
            return {'error_msg': f'服务地址无效: {self.base_url}'}

        system_prompt, user_prompt = self._build_prompts(query, from_lang, to_lang)
        payload = {
            'model': self.model_name,
            'messages': [
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': user_prompt},
            ],
            'stream': False,
        }
        # 额外参数（如 enable_thinking / temperature / top_p 等）由用户自行追加；
        # 不允许覆盖核心字段，避免破坏翻译结果的解析
        for key, value in self.extra_body.items():
            if key not in ('model', 'messages', 'stream'):
                payload[key] = value

        try:
            status, raw = self._request(url, 'POST', payload)
        except ConnectionError as e:
            return {'error_msg': str(e)}

        if status != 200:
            return {'error_msg': f'API请求失败 ({status}): {_extract_api_error(raw)}'}

        try:
            data = json.loads(raw)
        except ValueError:
            return {'error_msg': f'API返回了非JSON内容: {raw[:300]}'}

        content = self._extract_content(data)
        if content is None:
            return {'error_msg': f'API返回格式无法解析: {_extract_api_error(raw)}'}

        return self._parse_translation(query, content)

    def fetch_models(self) -> list:
        """获取服务商提供的模型列表（需要服务端支持 GET /models）。"""
        url = self.models_url()
        if not url:
            raise ValueError("服务地址（Base URL）未配置")

        try:
            status, raw = self._request(url, 'GET')
        except ConnectionError as e:
            raise ValueError(str(e))

        if status != 200:
            raise ValueError(f"获取模型列表失败 ({status}): {_extract_api_error(raw)}")

        try:
            data = json.loads(raw)
        except ValueError:
            raise ValueError("模型列表返回了非JSON内容")

        items = None
        if isinstance(data, dict):
            items = data.get('data')
            if items is None:
                items = data.get('models')

        if not isinstance(items, list):
            raise ValueError("模型列表格式无法识别")

        models = []
        for item in items:
            if isinstance(item, dict):
                model_id = item.get('id') or item.get('name') or item.get('model')
            else:
                model_id = str(item)
            if model_id:
                models.append(str(model_id))

        return sorted(set(models), key=str.lower)
