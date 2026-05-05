// Health Handler — 处理 GET /healthz 端点逻辑

import { Request, Response, Router } from 'express';

/**
 * Handles the GET /healthz endpoint.
 * Returns a simple health check response with HTTP 200.
 */
export function healthHandler(_req: Request, res: Response): void {
  res.status(200).json({ status: 'ok' });
}

/**
 * Registers the health check route on the given router.
 * @param router - Express Router instance
 */
export function registerHealthRoute(router: Router): void {
  router.get('/healthz', healthHandler);
}
