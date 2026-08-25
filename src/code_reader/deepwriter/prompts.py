"""deepwriter 的 LLM prompt 模板。

三套 system/user 对:机制 / 流程 / 模块。均要求跟用户问题同语言、带 [file:line] 引用。
"""

MECHANISM_SYSTEM = """你正在为一个完全没见过这个项目的开发者写讲解文档。

写一篇 1500-3000 字的讲解,包含:
1. 这个机制解决什么问题
2. 怎么实现的(带 [file:line] 引用)
3. 为什么这么设计(取舍点)
4. 典型用法示例

语言:跟用户问题同语言(中文或英文)。
格式:markdown,带 [file:line] 引用。"""

MECHANISM_USER = """【机制名】: {name}
【一句话定位】: {one_liner}
【相关符号】:
{symbols_with_file_line}
【代码片段】:
{code_snippets}

请写一篇 1500-3000 字的讲解。"""

FLOW_SYSTEM = """你正在为一个完全没见过这个项目的开发者写端到端流程讲解。

写一篇 1500-3000 字的讲解,包含:
1. 这个流程从哪个入口开始
2. 端到端每一步在哪、做什么
3. 数据怎么流动
4. 关键决策点

语言:跟用户问题同语言。格式:markdown,带 [file:line] 引用。"""

FLOW_USER = """【流程名】: {name}
【端到端调用链】:
{rendered_chain}
【每一步的代码片段】:
{code_snippets}

请写一篇 1500-3000 字的讲解。"""

MODULE_SYSTEM = """你正在为一个完全没见过这个项目的开发者写核心模块讲解。

写一篇 1000-2000 字的讲解,包含:
1. 这个模块的职责
2. 对外接口
3. 内部结构
4. 和谁耦合

语言:跟用户问题同语言。格式:markdown。"""

MODULE_USER = """【模块路径】: {module_path}
【包含文件数】: {file_count}
【一句话定位】: {one_liner}
【相关符号】:
{symbols}"""
