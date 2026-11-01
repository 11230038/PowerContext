# WebGPU 与 WASM 降级

应用启动时先在浏览器 Worker 中尝试创建 WebGPU 推理会话。仅检查 navigator.gpu 并不充分，因为显卡驱动、adapter 或模型算子也可能导致初始化失败。任何 WebGPU 初始化错误都会被捕获，应用随后使用相同 INT8 模型建立 WASM 会话。界面必须显示实际使用的后端以及降级原因，WASM 环境仍能完成导入和检索。
