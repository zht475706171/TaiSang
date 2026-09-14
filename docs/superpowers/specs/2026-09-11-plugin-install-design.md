# Plugin 安装系统设计（Skill 管理页集成）

## 目标

让用户在 Skill 管理页直接从 github 安装 plugin（如 superpowers），自动批量导入 plugin 内所有 skills 到 user 源，统一在 UI 管理已装 plugin（查看、卸载、升级）。

## 背景

当前 TaiSang 的 skill 导入只支持单文件 SKILL.md 或单 skill zip（`src/taisang/skills/importer.py`），不认识 plugin 结构。用户想把 superpowers 整包导入要逐个 skill 打 zip 传 14 次，体验差。

参考 claude-code 的 plugin 系统：`installed_plugins.json` 记录已装 plugin（name/source/version/sha/installedAt），`marketplace.json` 描述可装 plugin。本设计不做 marketplace，只做"用户输入 github 地址直接装"的轻量形态。

## 范围

**做**：
- Skill 管理页加"安装 Plugin"按钮 + 输入 github 地址 dialog
- 后端 git clone + 扫描 plugin 结构 + 批量导入 skills 到 `~/.taisang/skills/<plugin>/<skill>/`
- `installed_plugins.json` 记录已装 plugin
- Skill 管理页加"已装 Plugin"折叠面板（查看、卸载、升级）
- skill 列表加"Plugin"列；plugin 来源 skill 禁止单删，只能整包卸载

**不做（YAGNI）**：
- `/add` `/remove` `/list` 指令系统（UI 已覆盖，指令是额外前端拦截工作）
- 别名表（必须输 `owner/repo` 或完整 URL）
- `/upgrade` 独立指令（"安装 Plugin"输同地址即升级）
- plugin 的 hooks/agents/scripts 资源（只导 skills）
- marketplace.json 解析（用户指定具体 plugin 仓库）
- 私有仓库 token 配置（依赖机器 git 配置）
- plugin 依赖关系

## 架构

### 数据流

```
用户在 Skill 管理页点"安装 Plugin" → 输入 obra/superpowers → 点"安装"
  → POST /api/skills/install-plugin {source: "obra/superpowers"}
  → installer.install_plugin(source, user_skills_dir)
    → 解析 github url（owner/repo 或完整 URL 或 .git 后缀）
    → git clone 到 tempfile.TemporaryDirectory 临时目录
    → 扫描 plugin 结构（3 种形态识别）
    → 对每个 skill: 复制到 ~/.taisang/skills/<plugin>/<skill>/
    → 读 package.json 取 version + git rev-parse HEAD 取 sha
    → 更新 installed_plugins.json（覆盖式：同名 plugin 先 rmtree 再写）
    → 清理临时目录
  → 返回 {plugin: "superpowers", version, sha, skills: [...]}
  → 前端 toast "已安装 superpowers v5.1.0（14 个 skill）"
  → skill 列表 + 已装 plugin 面板刷新
```

### Plugin 结构识别（3 种形态）

clone 下来后扫描 plugin 根目录：

1. **根有 `skills/` 子目录**（superpowers 形态）：批量导入 `skills/*/SKILL.md`，每个 skill 复制到 `~/.taisang/skills/<plugin-name>/<skill-name>/`。skill-name 取 skill 目录名（不用 frontmatter name，避免不一致）。
2. **根直接是 `SKILL.md`**（单 skill 仓库）：导入这一个，落盘到 `~/.taisang/skills/<plugin-name>/SKILL.md`（注意：这是单层，不是 `<plugin>/<skill>/`）。
3. **根有 `.claude-plugin/marketplace.json`**（marketplace 形态）：报错"这是 marketplace 不是 plugin，请指定具体 plugin 仓库地址"。

### plugin-name 取法

从 repo 名取（`obra/superpowers` → `superpowers`），不用 package.json 的 name 字段（可能不一致，且有些 plugin 没 package.json）。

### 落盘结构

```
~/.taisang/
├── installed_plugins.json          # 已装 plugin 索引
└── skills/                         # user 源 skills
    └── <plugin-name>/              # 按 plugin 分目录
        ├── brainstorming/
        │   └── SKILL.md
        ├── subagent-driven-development/
        │   ├── SKILL.md
        │   ├── implementer-prompt.md
        │   └── scripts/
        └── ...
```

### installed_plugins.json 格式

```json
{
  "version": 1,
  "plugins": {
    "superpowers": {
      "source": "github:obra/superpowers",
      "version": "5.1.0",
      "git_commit_sha": "f2cbfbefebbf",
      "installed_at": "2026-09-11T10:00:00Z",
      "skills": ["brainstorming", "subagent-driven-development", "..."]
    }
  }
}
```

- `version`：从 plugin 根 `package.json` 的 `version` 字段取，没有则用 commit SHA 前 12 位
- `git_commit_sha`：`git rev-parse HEAD` 取前 12 位
- `source`：规范化成 `github:<owner>/<repo>` 格式
- `skills`：导入的 skill name 列表（目录名）

### load_skills 扫描兼容

当前 `loader.py:83` `d.glob("*/SKILL.md")` 只扫一层。改成同时扫两层：
- `*/SKILL.md`：旧的单 skill 形式（向后兼容）
- `*/*/SKILL.md`：plugin 形式 `<plugin>/<skill>/SKILL.md`

`Skill` dataclass 加 `plugin_name: str | None = None` 字段。两层扫描时，第二层解析出的 skill 的 `plugin_name` 取父目录名。

优先级不变（project > user > system），同名覆盖。

## 组件

### 后端新建

**`src/taisang/skills/installer.py`** — plugin 安装核心逻辑
- `parse_github_source(source: str) -> str`：解析输入成规范化 `github:owner/repo`
  - `owner/repo` → `github:owner/repo`
  - `https://github.com/owner/repo` → `github:owner/repo`
  - `https://github.com/owner/repo.git` → `github:owner/repo`
  - 其他 → 抛 `PluginInstallError`
- `install_plugin(source: str, user_skills_dir: Path, plugins_file: Path) -> InstalledPlugin`：主流程
  - 解析 source
  - git clone 到 tempfile.TemporaryDirectory
  - 扫描 plugin 结构（3 形态）
  - 复制 skills 到 `user_skills_dir/<plugin>/<skill>/`
  - 读 version + sha
  - 更新 installed_plugins.json（覆盖式）
  - 返回 InstalledPlugin dataclass
- `uninstall_plugin(name: str, user_skills_dir: Path, plugins_file: Path) -> None`：删 `user_skills_dir/<plugin>/` + plugins.json 条目
- `list_plugins(plugins_file: Path) -> list[InstalledPlugin]`：读 plugins.json
- `InstalledPlugin` dataclass：name/source/version/sha/installed_at/skills

**`src/taisang/skills/plugin_registry.py`** — installed_plugins.json 读写
- `load_plugins(plugins_file: Path) -> dict[str, InstalledPlugin]`
- `save_plugins(plugins_file: Path, plugins: dict[str, InstalledPlugin]) -> None`（原子写）
- `upsert_plugin(plugins_file: Path, plugin: InstalledPlugin) -> None`（覆盖式）

### 后端修改

**`src/taisang/skills/loader.py`**
- `load_skills` 扫描改成兼容 `*/SKILL.md` 和 `*/*/SKILL.md`
- `_parse_skill_md` 加 `plugin_name` 参数（第二层扫描时传入）
- `Skill` dataclass 加 `plugin_name: str | None = None`

**`src/taisang/web/skills_api.py`**
- 新增 `POST /api/skills/install-plugin`：body `{source: str}`，调 `installer.install_plugin`，返回 `{plugin, version, sha, skills}`
- 新增 `DELETE /api/skills/plugin/<name>`：调 `installer.uninstall_plugin`
- 新增 `GET /api/skills/plugins`：调 `installer.list_plugins`
- `GET /api/skills` 返回的 skill 对象加 `plugin_name` 字段

### 前端修改

**`src/taisang/web/frontend/src/views/SkillManage.vue`**
- header 加"安装 Plugin"按钮（和"导入 Skill"并列）
- 新增"安装 Plugin" dialog 组件：输入框 + 格式提示 + 安装按钮 + loading 态
- skill 列表上方加"已装 Plugin"折叠面板：每个 plugin 一行（name + version + skills 数 + 安装时间 + 卸载按钮）
- skill 表格加"Plugin"列（plugin_name 非空时显示，否则空）
- plugin skill 的"删除"按钮改"卸载 plugin"（调 `DELETE /api/skills/plugin/<name>`）；单文件导入的 skill 保持"删除"

**`src/taisang/web/frontend/src/types/index.ts`**（或 SkillManage.vue 内联）
- `SkillRow` 加 `plugin_name?: string`
- 新增 `InstalledPlugin` interface

## 错误处理

| 场景 | 行为 |
|------|------|
| git 未安装 | `PluginInstallError("系统未安装 git，请先安装 git")` |
| clone 失败（仓库不存在/无权限） | `PluginInstallError("git clone 失败：<stderr 内容>")` |
| plugin 根无 SKILL.md 也无 skills/ | `PluginInstallError("未找到可导入的 skill")` |
| plugin 根有 .claude-plugin/marketplace.json | `PluginInstallError("这是 marketplace 不是 plugin，请指定具体 plugin 仓库地址")` |
| skill name 不符合安全字符集 | 跳过并 warning（不致命） |
| /remove 不存在的 plugin | `PluginInstallError("未安装：<name>")` |
| installed_plugins.json 损坏 | log warning + 当成空 dict 重新写 |

## 测试策略

### 后端单元测试

**`tests/unit/test_skills_installer.py`**（新建）
- `parse_github_source`：4 种输入格式（owner/repo、完整 URL、.git 后缀、非法格式）
- `install_plugin`：用本地 fixture 目录当"已 clone"的 plugin（mock subprocess git clone）
  - superpowers 形态（skills/ 子目录）→ 批量导入
  - 单 skill 仓库形态（根 SKILL.md）→ 单导入
  - marketplace 形态 → 报错
  - 无 skill → 报错
  - 覆盖升级（已存在同名 plugin）
- `uninstall_plugin`：删目录 + 删 json 条目 + 不存在的 plugin 报错
- `list_plugins`：读 json + 空文件返回空

**`tests/unit/test_skills_loader.py`**（修改现有）
- `load_skills` 扫描两层：`*/SKILL.md` + `*/*/SKILL.md`
- plugin_name 字段正确填充
- 向后兼容：旧的单层 skill 仍能扫到

### 后端 API 集成测试

**`tests/unit/test_web_skills_api.py`**（修改或新建）
- `POST /api/skills/install-plugin` 成功 + 失败路径
- `DELETE /api/skills/plugin/<name>` 成功 + 不存在
- `GET /api/skills/plugins` 返回格式
- `GET /api/skills` 返回的 skill 含 plugin_name

### 前端验证

playwright 文本方式（不截图）：
1. 打开 Skill 管理页
2. 点"安装 Plugin" → 输入 `obra/superpowers` → 点安装
3. 等待 loading 结束
4. 验证 toast "已安装 superpowers v..."
5. 验证"已装 Plugin"面板出现 superpowers
6. 验证 skill 列表出现 brainstorming 等 skill，Plugin 列显示 superpowers
7. 点"卸载" → 验证 plugin 消失 + skill 消失

## 关键文件

- Create: `src/taisang/skills/installer.py`
- Create: `src/taisang/skills/plugin_registry.py`
- Modify: `src/taisang/skills/loader.py`
- Modify: `src/taisang/skills/types.py`
- Modify: `src/taisang/web/skills_api.py`
- Modify: `src/taisang/web/frontend/src/views/SkillManage.vue`
- Create: `tests/unit/test_skills_installer.py`
- Modify: `tests/unit/test_skills_loader.py`

## 安全考虑

- git clone 用 `subprocess.run(["git", "clone", url, tmpdir], capture_output=True)`，url 经 `parse_github_source` 规范化（只接受 github.com 域名 + owner/repo 格式），杜绝命令注入
- 临时目录用 `tempfile.TemporaryDirectory` 自动清理
- 落盘目录名用 plugin-name（从 repo 名取，符合 `_SAFE_NAME_RE` 字符集）
- installed_plugins.json 原子写（tmp + os.replace）
- 不执行 plugin 的任何脚本（hooks/scripts/agents 只复制不执行）