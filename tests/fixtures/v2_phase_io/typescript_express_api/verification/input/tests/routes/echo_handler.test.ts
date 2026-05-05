import { describe, it, expect, vi } from 'vitest';
import { Request, Response } from 'express';
import { echoHandler, EchoResponse } from '../../src/routes/echo_handler';

describe('echoHandler', () => {
  it('should echo back the message with correct length', () => {
    const req = { body: { message: 'hello' } } as Request;
    const res = {
      status: vi.fn().mockReturnThis(),
      json: vi.fn(),
    } as unknown as Response;

    echoHandler(req, res);

    expect(res.status).toHaveBeenCalledWith(200);
    expect(res.json).toHaveBeenCalledWith({ echo: 'hello', length: 5 });
  });

  it('should return 400 when message is missing', () => {
    const req = { body: {} } as Request;
    const res = {
      status: vi.fn().mockReturnThis(),
      json: vi.fn(),
    } as unknown as Response;

    echoHandler(req, res);

    expect(res.status).toHaveBeenCalledWith(400);
    expect(res.json).toHaveBeenCalledWith({
      error: 'Invalid request body. Expected JSON with a "message" string field.',
    });
  });

  it('should return 400 when message is not a string', () => {
    const req = { body: { message: 123 } } as Request;
    const res = {
      status: vi.fn().mockReturnThis(),
      json: vi.fn(),
    } as unknown as Response;

    echoHandler(req, res);

    expect(res.status).toHaveBeenCalledWith(400);
  });

  it('should handle empty string message', () => {
    const req = { body: { message: '' } } as Request;
    const res = {
      status: vi.fn().mockReturnThis(),
      json: vi.fn(),
    } as unknown as Response;

    echoHandler(req, res);

    expect(res.status).toHaveBeenCalledWith(200);
    expect(res.json).toHaveBeenCalledWith({ echo: '', length: 0 });
  });

  it('should handle unicode characters', () => {
    const req = { body: { message: '你好' } } as Request;
    const res = {
      status: vi.fn().mockReturnThis(),
      json: vi.fn(),
    } as unknown as Response;

    echoHandler(req, res);

    expect(res.status).toHaveBeenCalledWith(200);
    const result: EchoResponse = { echo: '你好', length: 2 };
    expect(res.json).toHaveBeenCalledWith(result);
  });
});
