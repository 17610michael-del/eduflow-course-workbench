# 考试子系统

负责试卷考试、网页题库式机考、答题实时保存、倒计时、自动交卷和课程题库。上传文件存放在 `uploads/exams/`。

## 题库 API

- `POST /api/question-bank/generate`：接收 `topic`、`count`、`type`，或直接接收结构化 `questions` 数组，生成题库记录。
- `POST /api/question-bank/imports/<任务ID>/complete`：PDF/Word 识别服务回传 `questions` 数组，将待识别任务转换为题库题目。
- 接口当前均使用教师登录权限保护；接第三方识别服务时可在反向代理层增加服务账号或令牌认证。

结构化题目字段为 `type`、`prompt`、`options`、`answer`、`points`；题型支持 `single`、`multiple`、`true_false`、`fill`、`essay`。
