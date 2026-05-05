// Entry point — 构建 Express 应用、注册路由、启动监听

import { createApp } from './server/app_builder';

const app = createApp();
const port = Number(process.env.PORT) || 3000;

app.listen(port, () => {
  console.log(`Server listening on port ${port}`);
});
