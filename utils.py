# -*- coding: utf-8 -*-
"""
工具模块
此模块当前为空，为未来可能的通用功能预留。
"""

import bpy

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
def find_po_entry(entries, msgid, msgctxt):
    """在集合中查找词条，返回其索引，如果未找到则返回-1"""
    # PO标准：msgctxt为None或空字符串应被视为相同
    lookup_msgctxt = msgctxt or ""
    for i, entry in enumerate(entries):
        entry_msgctxt = entry.msgctxt or ""
        if entry.msgid == msgid and entry_msgctxt == lookup_msgctxt:
            return i
    return -1

def register():
    """注册工具模块（当前无内容）"""
    pass

def unregister():
    """注销工具模块（当前无内容）"""
    pass 