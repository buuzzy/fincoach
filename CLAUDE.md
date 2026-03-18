# TraderCoach — 交易复盘分析工具

## 项目概览
面向券商个人投资者的交易复盘分析 H5 应用，帮助用户分析交易行为、识别模式、诊断问题并生成周期性复盘报告。

## 技术栈
- **前端**: React + TypeScript + Ant Design Mobile + ECharts
- **后端**: Python + FastAPI + pandas + numpy
- **数据库**: SQLite (MVP)
- **AI**: OpenAI 兼容 API (用户自配)
- **构建**: Vite (前端) + uvicorn (后端)

## 开发命令

### 后端
```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
pytest  # 运行测试
```

### 前端
```bash
cd frontend
npm install
npm run dev   # 启动开发服务器 (port 5173)
npm run build # 构建生产版本
```

## 项目结构
- `frontend/` — React H5 前端
- `backend/` — FastAPI 后端 + 分析引擎
- `docs/` — PRD 及设计文档

## 环境变量 (backend/.env)
```
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=sk-xxx
DATABASE_URL=sqlite:///./coach.db
```

## API 端点
- `POST /api/reports/generate` — 触发报告生成
- `GET /api/reports/{report_id}` — 获取报告详情
- `GET /api/reports/` — 报告列表
- `GET /api/users/{user_id}/profile` — 用户画像
