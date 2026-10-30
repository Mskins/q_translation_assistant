# 快捷翻译助手（Quick Translation Assistant）

Blender 翻译工作流插件：**PO/MO 文件转换、PO 编辑、源码与 Blend 词条提取、通用大模型翻译、全局翻译、HUD 翻译**。

- 当前版本：**v1.5.0**
- 适用版本：**Blender 3.0+**（已在 4.4 / 4.5 / 5.2 测试）
- 插件位置：`3D 视图 > 侧边栏 > 翻译助手`
- 仓库地址：<https://github.com/Mskins/q_translation_assistant>

## 功能特性

| 模块 | 功能 |
| --- | --- |
| 文件转换 | PO → MO、MO → PO、PY 字典 → PO、PO 合并、重复条目清理、文件信息查看 |
| PO 编辑器 | 加载/保存/编辑/添加/移除/合并词条，文本替换，全局词典替换 |
| 文本提取 | 从插件源码目录或 `.blend` 文件提取可翻译词条 |
| 一键翻译 | 通过通用大模型批量翻译，支持单条翻译、编辑与导出 |
| 全局翻译 | 将内置中文词典解压到 Blender 用户 `datafiles/locale`，实现全局界面翻译 |
| HUD 翻译 | 运行时重写 `blf_draw`，实现视口/界面文字的实时翻译 |

## 环境要求

- Blender 3.0 或更高版本
- 任意 **OpenAI Chat Completions 兼容**的大模型服务（OpenAI、DeepSeek、通义千问、豆包、Ollama、LM Studio、OpenRouter、硅基流动、Moonshot、智谱、Gemini、Groq、Mistral 等）
- 文件转换功能需要 `msgfmt` / `msgunfmt` / `msgmerge`
  - Windows：插件内置这些工具，无需额外安装
  - macOS / Linux：可使用系统 `gettext`，或按插件内提示安装

## 安装

### 方式一：Release 安装（推荐）

1. 打开 [Releases](https://github.com/Mskins/q_translation_assistant/releases) 页面
2. 下载最新的 `q_translation_assistant-1.5.0.zip`
3. Blender 中依次打开：`编辑 > 偏好设置 > 插件 > 从磁盘安装`
4. 选择下载的 zip 文件，启用「快捷翻译助手」

Release 附件已按 Blender 要求的目录结构打包，无需手动改文件夹名。

### 方式二：源码安装

将仓库克隆到 Blender 的 `scripts/addons` 目录：

```bash
cd "<Blender 用户目录>/scripts/addons"
git clone https://github.com/Mskins/q_translation_assistant.git
```

常见路径：

- Windows：`%APPDATA%\Blender Foundation\Blender\<版本>\scripts\addons`
- macOS：`~/Library/Application Support/Blender/<版本>/scripts/addons`
- Linux：`~/.config/blender/<版本>/scripts/addons`

> 注意：插件目录名必须为 `q_translation_assistant`。如果下载的是 GitHub 源码 ZIP（目录名通常是 `q_translation_assistant-main`），请先重命名后再放入 `addons` 目录，或直接使用 Release 附件。

安装后在 `偏好设置 > 插件` 中搜索「快捷翻译助手」并勾选启用。侧边栏（N 面板）会出现「翻译助手」标签页。

## 快速开始

### 1. 配置翻译 API

打开 `编辑 > 偏好设置 > 插件 > 快捷翻译助手`，在「通用大模型设置」中填写：

- **服务商预设**：选择后自动填充地址和模型，仍可手动修改
- **服务地址（Base URL）**：例如 `https://api.openai.com/v1`
- **API Key**：本地服务（Ollama / LM Studio）可留空
- **模型名称**：例如 `gpt-4o-mini`、`deepseek-chat`

点击「验证API设置」确认可用；模型名不确定时可点击「获取模型」从服务商 `/models` 接口拉取。

内置预设：

| 服务商 | Base URL | 默认模型 |
| --- | --- | --- |
| OpenAI | `https://api.openai.com/v1` | `gpt-4o-mini` |
| DeepSeek | `https://api.deepseek.com/v1` | `deepseek-chat` |
| 通义千问 | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-turbo` |
| 豆包 / 火山方舟 | `https://ark.cn-beijing.volces.com/api/v3` | `doubao-1-5-lite-32k-250115` |
| Ollama | `http://localhost:11434/v1` | `qwen2.5:7b` |
| LM Studio | `http://localhost:1234/v1` | `local-model` |
| OpenRouter | `https://openrouter.ai/api/v1` | `openai/gpt-4o-mini` |
| 硅基流动 | `https://api.siliconflow.cn/v1` | `Qwen/Qwen2.5-7B-Instruct` |
| Moonshot / Kimi | `https://api.moonshot.cn/v1` | `moonshot-v1-8k` |
| 智谱 GLM | `https://open.bigmodel.cn/api/paas/v4` | `glm-4-flash` |
| Google Gemini | `https://generativelanguage.googleapis.com/v1beta/openai` | `gemini-2.0-flash` |
| Groq | `https://api.groq.com/openai/v1` | `llama-3.1-8b-instant` |
| Mistral | `https://api.mistral.ai/v1` | `mistral-small-latest` |
| 自定义 | 手动填写 | 手动填写 |

高级选项：

- **请求超时**：本地模型或长文本可适当调大
- **自定义请求头**：多个请求头用分号分隔，例如 `api-key: xxx; X-Title: Blender`
- **额外请求参数**：合并到请求体的 JSON，例如 `{"temperature": 0.2, "enable_thinking": false}`

### 2. 提取与翻译词条

1. 打开侧边栏 `翻译助手 > 文本提取与翻译`
2. 选择提取来源：
   - **插件**：选择插件源码目录，提取 `.py` 中的界面文本
   - **Blend文件**：选择 `.blend`，提取物体、材质、世界、集合、纹理、图像、节点组接口等名称
3. 点击「提取文本」
4. 在词条列表中检查、编辑，点击「一键翻译」
5. 翻译完成后可「导出为文件」，或「追加到编辑器」继续处理

### 3. PO / MO 文件处理

- **文件转换**：支持 PO → MO、MO → PO、PY 字典 → PO、PO 合并
- **PO 文件编辑器**：加载、保存、添加、删除、合并词条，支持文本替换与全局词典替换

### 4. 全局翻译与 HUD 翻译

在插件偏好设置中：

- **全局翻译**：将插件自带词典解压到 Blender 用户 `datafiles/locale`，重启 Blender 后生效；可设置语言切换按钮显示在顶部工具栏/状态栏
- **HUD 翻译**：通过重写 `blf_draw` 实时翻译界面文字，需要指定 `.mo` 文件路径

## 词条提取说明

提取器基于 Python AST，会从以下位置收集文本：

- `bl_info` 的 `name` / `description` / `warning`
- `bl_label`、`bl_description`、`bl_category`
- `bpy.props.*(name=..., description=...)`
- `text=`、`label=`、`title=`、`description=` 等界面参数
- `self.report(...)`、`raise ValueError(...)`、`error_msg` / `message` 字典值
- `EnumProperty(items=...)` 的标签与描述（含常量引用、ListComp、2/3 元组）
- `layout.label(...)`、`layout.operator(..., "文字")`、`prop` / `menu` / `popover` 等位置参数
- `MENU_ITEMS`、`CHOICES` 等界面列表
- f-string、`%` 格式化、字符串拼接、`.format(...)`、三元表达式分支
- 模块级/类级字符串常量、`self.LABEL`、常量列表/字典下标
- `gettext` / `pgettext` / `ngettext`
- 赋给 `*_label`、`*_title`、`*_text`、`*_message`、`*_error` 等变量的文本
- 函数返回的界面文本（函数名包含 `label/text/name/desc/title/message/error` 时优先识别）
- 可选的文档字符串与 JSON 文件

**f-string 会以 `{占位符}` 模板形式收录**，例如：

```text
翻译完成，共处理 {translation_count} 个词条
```

翻译时请保留 `{...}` 占位符不变。

过滤选项只作用于普通列表、元组、注释等“上下文不明确”的位置；`text=`、`bl_label=` 等确认是界面文本的位置不会被变量名/特殊字符规则误杀。

## 目录结构

```text
q_translation_assistant/
├─ __init__.py                 插件入口与注册
├─ translator.py               通用大模型翻译器（OpenAI 兼容）
├─ preferences.py              API 设置、全局翻译、HUD 设置
├─ text_extractor.py           源码 / Blend / JSON 词条提取
├─ translation_panel.py        文本提取与自动翻译面板
├─ po_editor.py                PO 文件编辑器
├─ file_converter.py           PO/MO/PY 文件转换
├─ global_translation_panel.py 全局翻译面板
├─ hud_translator.py           HUD 实时翻译
├─ polib.py                    内置 PO 文件解析库
├─ builtin_msgfmt.py           内置 msgfmt 工具调用
├─ builtin_msgfmt_data.py      内置工具二进制数据
├─ icons/                      图标
├─ mo/locale.zip               全局翻译词典
└─ tools/                      内置 msgfmt/msgunfmt/msgmerge
```

## 常见问题

**Q：验证 API 失败？**  
检查 Base URL 是否填到 `/v1` 级别、API Key 是否正确、模型名是否可用。部分服务商的模型名是接入点 ID，需要按服务商文档填写。

**Q：本地 Ollama / LM Studio 需要 API Key 吗？**  
不需要，留空即可。Base URL 使用 `http://localhost:11434/v1` 或 `http://localhost:1234/v1`。

**Q：旧版的通义千问 / DeepSeek / 豆包 / Ollama 配置还能用吗？**  
首次启动会自动迁移到通用大模型配置。百度翻译已在 v1.4.1 移除，需要改用通用大模型。

**Q：翻译结果不生效？**  
f-string 词条是以模板形式提取的；运行时需要代码通过 gettext 查表并使用 `format` 填充，翻译才会实际应用到界面。

**Q：提取结果太多 / 太少？**  
在「智能过滤选项」中调整过滤开关；提取界面文本位置不受“过滤变量名”等选项影响。也可以设置最小文本长度。

**Q：提示找不到 msgfmt？**  
Windows 版插件内置了工具；macOS/Linux 请安装 `gettext` 并确保 `msgfmt`、`msgunfmt`、`msgmerge` 在 `PATH` 中。

## 更新日志

### v1.5.0

- 重构源码词条提取器，大幅提升提取完整度
- 支持 f-string、格式化、三元分支、枚举项常量、类常量、下标、gettext 等写法
- 新增 `bl_category`、`bl_info` 描述、异常消息、字典错误消息等提取
- 修复单词标签、含括号/占位符文本被误过滤的问题
- 修复重复上下文词条

### v1.4.1

- 移除百度翻译及相关设置
- 翻译服务统一为通用大模型

### v1.4.0

- 新增通用大模型接入（OpenAI Chat Completions 兼容）
- 支持 13 个服务商预设、模型列表获取、自定义请求头与额外请求参数
- 旧版大模型配置自动迁移

完整更新日志与安装包见 [Releases](https://github.com/Mskins/q_translation_assistant/releases)。

## 反馈

- 问题反馈：<https://github.com/Mskins/q_translation_assistant/issues>
- 作者：亮锅不服LAO
- PO 解析基于内置的 [polib](https://github.com/izimobil/polib)
