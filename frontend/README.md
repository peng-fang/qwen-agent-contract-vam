# 签之前 · React 前端

基于 **React + TypeScript + Vite + Tailwind + shadcn/ui 风格组件 + React Flow + ECharts**。

## 页面

- **合同核验**：上传宣传材料/合同、提问、双栏 PDF 证据高亮。
- **对赌协议推演**：输入对赌条款，React Flow 渲染决策树，支持继续推演、回溯、导出报告。
- **资金流**：ECharts 累计成本对比图（当前为示例数据）。

## 开发

```powershell
npm install
npm run dev
```

打开：<http://localhost:5173>

Vite 将 `/api` 代理到 FastAPI 后端：

```text
/api -> http://127.0.0.1:8001
```

## 构建

```powershell
npm run build
```

产物在 `dist/`；FastAPI 会自动托管该目录，因此也可以直接访问：

```text
http://127.0.0.1:8001
```

## 后端

后端启动方式见 `../backend/README.md`。Gradio 旧前端仍保留在：

- http://127.0.0.1:7860
- http://127.0.0.1:7861
