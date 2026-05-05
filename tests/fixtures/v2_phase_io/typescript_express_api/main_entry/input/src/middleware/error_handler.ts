// Error Middleware — 处理 JSON 解析错误和全局错误处理

import { Request, Response, NextFunction } from 'express';

/**
 * Global error handler middleware.
 * Catches JSON parse errors and other unhandled errors, returning descriptive HTTP 400 responses.
 */
export function errorHandler(err: Error, _req: Request, res: Response, _next: NextFunction): void {
  if (err instanceof SyntaxError && 'status' in err && err.status === 400 && 'body' in err) {
    // JSON parse error
    res.status(400).json({
      error: 'Invalid JSON in request body. Please send a valid JSON object.',
    });
    return;
  }

  // Generic unhandled error
  res.status(500).json({
    error: 'Internal server error',
  });
}
