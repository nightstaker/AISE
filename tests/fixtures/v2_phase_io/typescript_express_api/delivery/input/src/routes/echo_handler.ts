// Echo Handler — 处理 POST /api/echo 端点业务逻辑

import { Request, Response, Router } from 'express';

/**
 * Echo response body structure.
 */
export interface EchoResponse {
  echo: string;
  length: number;
}

/**
 * Echo request body structure.
 */
export interface EchoRequest {
  message: string;
}

/**
 * Processes an echo request and returns the message with its character length.
 * @param message - The message string to echo back
 * @returns EchoResponse with echo field and length field
 */
export function processEcho(message: string): EchoResponse {
  return {
    echo: message,
    length: message.length,
  };
}

/**
 * Handles the POST /api/echo endpoint.
 * Validates the request body and returns the echoed message with its length.
 * Returns HTTP 400 if the request body is malformed.
 */
export function echoHandler(req: Request, res: Response): void {
  const body = req.body as EchoRequest;

  if (!body || typeof body.message !== 'string') {
    res.status(400).json({
      error: 'Invalid request body. Expected JSON with a "message" string field.',
    });
    return;
  }

  const result = processEcho(body.message);
  res.status(200).json(result);
}

/**
 * Registers the echo route on the given router.
 * @param router - Express Router instance
 */
export function registerEchoRoute(router: Router): void {
  router.post('/api/echo', echoHandler);
}
