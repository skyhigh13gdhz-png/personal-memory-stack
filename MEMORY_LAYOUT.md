# 长期记忆目录与 Subject Registry

## 1. 目标

日常调整目录不改代码。稳定身份、页面模板、导航目录和对象关系分别管理：

```text
subject_id         永久身份，移动文件时不变
subject_type       模板类型
template           具体模板版本，必须与 Subject 类型兼容
collection         导航集合
parent_subject_id  父对象
path               当前投影路径，只存在于 manifest
```

配置文件：

- `config/subjects.example.json`：Subject Registry 示例；
- `config/memory-layout.example.json`：集合、类型路由和嵌套规则示例；
- `config/subjects.json`：当前经过确认的最小 Subject Registry；
- `config/memory-layout.json`：当前正式布局配置；
- `config/memory-layout-manifest.example.json`：生成清单格式示例；
- `memory-layout-manifest-v1`：系统生成文件当前路径和内容哈希，由投影器维护。

Layout 中的 `templates` 是模板目录。Registry 引用不存在的模板，或把不兼容模板套到 Subject 类型上，校验会直接失败。

## 2. 调整分类

把“宠物”移动到“人物与关系”下，只修改 layout：

```json
{
  "collections": {
    "people": "20-长期记忆/人物与关系"
  },
  "routing": {
    "person": "people",
    "pet": "people"
  }
}
```

把单个 Subject 放到其他集合，修改 Registry 中的显式 `collection`，其优先级高于类型默认路由。

Memory Gateway 从属于 AI 外置记忆时：

```json
{
  "subject_id": "component:memory-gateway",
  "subject_type": "component",
  "template": "component-v1",
  "collection": "projects",
  "parent_subject_id": "project:personal-memory"
}
```

## 3. 安全迁移工作流

```bash
# 只校验配置并显示目标路径
python3 scripts/memory_layout.py validate \
  --layout config/memory-layout.example.json \
  --subjects config/subjects.example.json

# 根据已有 manifest 生成迁移计划，不移动文件
python3 scripts/memory_layout.py plan \
  --layout config/memory-layout.json \
  --subjects config/subjects.json \
  --manifest 90-系统/生成清单/memory-layout-manifest.json \
  --vault /path/to/vault \
  --output /tmp/memory-layout-plan.json

# 投影器写完页面后登记或刷新文件哈希
python3 scripts/memory_layout.py register \
  --manifest 90-系统/生成清单/memory-layout-manifest.json \
  --vault /path/to/vault \
  --subject-id project:personal-memory \
  --path '20-长期记忆/项目/AI 外置记忆.md'

# 人工检查计划后执行，并生成回滚日志
python3 scripts/memory_layout.py apply \
  --plan /tmp/memory-layout-plan.json \
  --vault /path/to/vault \
  --journal /tmp/memory-layout-journal.json

# 需要时回滚
python3 scripts/memory_layout.py rollback \
  --journal /tmp/memory-layout-journal.json \
  --vault /path/to/vault
```

## 4. 安全边界

- 只移动 manifest 中 `managed=true` 的系统生成文件；
- 文件内容哈希变化时拒绝移动，避免覆盖人工编辑；
- 目标存在时拒绝，不静默覆盖；
- 所有移动执行前先整体预检，避免迁移一半才失败；
- 拒绝 `..`、绝对路径和通过符号链接逃逸 Vault；
- Apply 生成 journal，Rollback 再次校验哈希；
- 未纳入 manifest 的人工文件不处理；
- 文件名保持不变时，普通 Obsidian Wiki Link 通常不受目录移动影响；显式路径链接需单独检查。

## 5. 何时仍需改代码

以下调整只改配置：

- 重命名导航目录；
- 把一种 Subject 路由到其他集合；
- 调整某个对象的 collection；
- 设置或取消父子关系；
- 为已有模板类型选择不同目录。

以下调整需要代码与测试：

- 新增一种页面模板行为；
- 新增 State/Claim 语义；
- 改变自动更新或人工评审策略；
- 新增附件、索引、链接重写等投影能力。
