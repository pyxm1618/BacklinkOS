# 回归测试用例

## 基线失败（RED）

在没有这套 Discovery Skill 约束时，实际出现过两个关键失败：

1. Semrush 官方连接提示 API units 不足后，流程误以为需要购买 units，而没有优先恢复已经批量验证成功的中转。
2. 扩容讨论容易迅速加入成功/失败对照、递归图谱、复杂评分等尚未验证的机制，偏离“扩大成功项目样本 + first_seen”的简单可执行路径。

Skill 必须阻止这两种回归。

## 应触发

### Case 1
用户：`帮我抓外链`

必须：加载本 Skill；发现近期成功项目；批量查 Organic Traffic；抓合格项目 Referring Domains；保留 first_seen；需要最终可用性时交给 screening。

### Case 2
用户：`继续扩大上次的外链库，越多越好`

必须：复用在线主库和已有项目/域名去重；优先扩成功项目样本和分页深度；不中途重新发明复杂模型。

### Case 3
用户：`批量抄这些新站的外链`

必须：把这些站当候选项目；先查 Organic Traffic；只深抓通过项目；聚合跨项目重复来源。

### Case 4
用户：`Semrush API 额度不够了，继续抓`

必须：先检查 `sem.3ue.com` 中转及历史中转文件；不能直接要求购买官方 API units；不能输出凭证。

### Case 5
用户：`哪些外链是在新站早期拿到的？`

必须：解释 first_seen 语义；只有存在可靠项目参考日期才计算 90 天 early；缺失写未确认。

## 不应触发 / 应交给 screening

### Case 6
用户：`审核这 120 个外链，哪些免费、哪些 dofollow？`

应直接使用 `screening-backlinks`；不要重新发现项目。

### Case 7
用户：`这个链接是不是 nofollow？`

应使用 `screening-backlinks` 的最终 HTML 验证规则。

## 通过标准

- 不把官方 API units 当成中转不可用。
- 不泄露任何中转凭证。
- 不把 `first_seen` 说成精确建链时间。
- 不把历史外链说成当前必然可复制。
- 不使用主题相关性。
- 默认先扩大样本和分页深度，而不是增加复杂架构。
- 最终审核职责交给 `screening-backlinks`。
