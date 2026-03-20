# TradeMind AI — 交易复盘分析工具

## 项目概览
面向券商个人投资者的交易复盘分析 H5 应用，帮助用户分析交易行为、识别模式、诊断问题并生成周期性复盘报告与单笔交易情景还原。

## 技术栈
- **前端**: React 18 + TypeScript + Ant Design Mobile + ECharts
- **后端**: Python 3.11 + FastAPI + pandas + numpy
- **数据库**: Supabase PostgreSQL 17
- **AI**: DeepSeek API（deepseek-chat），OpenAI 兼容接口
- **行情数据**: QVeris API（实时 + 历史 K 线）
- **资讯数据**: Finloop News API
- **构建**: Vite (前端) + uvicorn (后端)
- **部署**: Cloudflare Pages (前端) + Render (后端)

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

### 数据补种
```bash
cd backend
python scripts/seed_supabase.py            # 全量补种
python scripts/seed_supabase.py --news-only # 仅补种资讯
```

## 项目结构
- `frontend/` — React H5 前端
- `backend/` — FastAPI 后端 + 分析引擎
- `backend/app/api/trades.py` — 单笔复盘 + 情景还原（含 LLM prompt）
- `backend/app/services/ai_agent.py` — 复盘报告生成（含 LLM Agent 流程）
- `backend/scripts/seed_supabase.py` — Supabase 数据补种脚本
- `docs/PRD.md` — 产品需求文档（v1.5）

## 环境变量 (backend/.env)
```
LLM_BASE_URL=https://api.deepseek.com
LLM_API_KEY=sk-xxx
LLM_MODEL=deepseek-chat
DATABASE_URL=postgresql+asyncpg://...
SUPABASE_DATABASE_URL=postgresql+asyncpg://...
QVERIS_API_KEY=sk-xxx
```

## API 端点
- `POST /api/reports/generate` — 触发报告生成（异步）
- `GET /api/reports/{report_id}` — 获取报告详情（轮询）
- `GET /api/reports/` — 报告列表
- `GET /api/users/{user_id}/profile` — 用户画像
- `GET /api/trades/{account_id}/closed` — 已平仓交易列表
- `GET /api/trades/review/{buy_id}/{sell_id}` — 单笔交易情景还原

## 线上地址
- 前端：https://fincoach-aee.pages.dev
- 后端：https://fincoach-backend.onrender.com
- API 文档：https://fincoach-backend.onrender.com/docs
