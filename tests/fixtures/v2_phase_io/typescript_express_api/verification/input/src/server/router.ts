// Router — 定义并注册所有路由处理器

import { Express, Router } from 'express';
import { registerHealthRoute } from '../routes/health_handler';
import { registerEchoRoute } from '../routes/echo_handler';

/**
 * Registers all routes on the given Express application.
 * Mounts the health check and echo routes under their respective paths.
 * @param app - Express application instance
 */
export function registerRoutes(app: Express): void {
  const router = Router();

  registerHealthRoute(router);
  registerEchoRoute(router);

  app.use('/', router);
}
