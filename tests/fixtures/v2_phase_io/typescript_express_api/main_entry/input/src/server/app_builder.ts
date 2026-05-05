// App Builder — 构建 Express 应用实例，配置中间件

import express from 'express';
import type { Express } from 'express';
import { registerRoutes } from './router';
import { errorHandler } from '../middleware/error_handler';

/**
 * Creates and configures the Express application instance.
 * Sets up JSON parsing middleware and mounts the error handler.
 * @returns Configured Express application
 */
export function createApp(): Express {
  const app = express();

  // JSON body parsing middleware
  app.use(express.json());

  // Mount error handler
  app.use(errorHandler);

  // Register all routes
  registerRoutes(app);

  return app;
}
