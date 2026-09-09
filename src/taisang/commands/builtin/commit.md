---
description: 查看 git 改动并生成 commit message 提交
allowed-tools: Bash, read_file
argument-hint: <可选:额外说明>
---

# 提交代码

按以下步骤执行:

1. `git status` + `git diff`(含 `--stat`)了解全部改动,不要只看单个文件
2. 判断改动意图,归纳成一个 commit;若改动包含多个不相关主题,向用户建议拆分
3. 写 commit message:
   - 格式:`type: 简述(中文)`;type 从 feat/fix/refactor/test/docs/chore 里选
   - 首行 ≤50 字符,正文(可省略)说明 why,不重复 diff 能看到的 what
4. 提交前把 message 给用户过目确认,再执行 `git add`(只加相关文件,不要无脑 `-A`)+ `git commit`
5. 不要 push,除非用户明确要求

用户传入参数:
$ARGUMENTS