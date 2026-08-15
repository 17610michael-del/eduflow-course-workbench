# EduFlow 师生课程工作台

EduFlow 是面向内网 Linux 教学服务器的 Flask 课程管理系统。系统使用服务器 Linux 账号通过 PAM 登录，不提供网页注册，也不在应用数据库中保存 Linux 密码。

## 主要功能

- 学生、教师、助教三类角色与差异化权限
- 课程任务发布、草稿、提交、删除记录、审阅与评分
- PDF、DOCX、本地文件和服务器暂存区作业提交
- 随堂测试、期中与期末考试、题库组卷、限时机考和自动交卷
- 学生分组、组长标识、小组交流与真实姓名资料
- 作业和考试完成比例、学生信息及学情分析
- DeepSeek 题库生成、PDF/DOCX 题目识别、任务助教和学情分析

## 本地运行

需要 Linux 环境及 PAM 开发库。Windows 可用于代码检查，但不能完成真实 PAM 登录。

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# 编辑 .env，并设置 SECRET_KEY；可用下面的命令生成：
python -c 'import secrets; print(secrets.token_hex(32))'
set -a
source .env
set +a
flask --app app init-db
python app.py
```

浏览器访问 `http://127.0.0.1:5000/`。

## 服务器部署

示例部署目录为 `/opt/eduflow/app`，持久数据目录为 `/opt/eduflow/data`。实际路径可以在部署脚本和 `.env` 中调整。

```bash
cd /opt/eduflow/app
chmod +x deploy.sh deploy/*.sh
./deploy.sh
```

首次主机初始化需由管理员运行：

```bash
sudo bash deploy/bootstrap-root.sh
```

## 用户角色

- 普通 Linux 用户默认为学生。
- `teacher` 用户组成员识别为教师。
- `assistant` 用户组成员识别为助教。
- `TEACHERS` 环境变量可额外指定教师账号。

账号密码由 Linux PAM 管理。测试账号密码、数据库和上传文件均不进入 Git 仓库。

## DeepSeek 配置

复制 `.env.example` 为 `.env`，仅在服务器上设置：

```text
DEEPSEEK_API_KEY=你的服务器端密钥
```

`.env` 已被 Git 忽略。API Key 只由后端读取，不会下发到浏览器。PDF 自动识别需要可提取文本；扫描版 PDF 应先执行 OCR，旧版 DOC 应另存为 DOCX。

请将生成的随机值写入 `.env` 的 `SECRET_KEY`。未设置该变量时应用会拒绝启动。只有在可信内网使用纯 HTTP 时才把 `SESSION_COOKIE_SECURE` 设为 `0`；通过 HTTPS 部署时保持为 `1`。

## 安全说明

- 不要提交 `.env`、测试账号密码、SQLite 数据库或用户上传文件。
- 内网演示可以使用 HTTP；面向非可信网络时必须启用 HTTPS，因为登录表单会传输 Linux 账号密码。
- 教师应用角色不需要 Linux root 或 sudo 权限。
