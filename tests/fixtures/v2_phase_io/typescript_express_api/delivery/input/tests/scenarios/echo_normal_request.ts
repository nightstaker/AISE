import { describe, it, expect, vi } from 'vitest';
import { Request, Response } from 'express';
import { echoHandler } from '../../src/routes/echo_handler';

describe('echo_normal_request', () => {
  it('POST /api/echo with valid message returns correct echo and length', () => {
    const req = {
      method: 'POST',
      url: '/api/echo',
      body: { message: 'hello' },
      headers: { 'content-type': 'application/json' },
    } as Request;
    const res = {
      status: vi.fn().mockReturnThis(),
      json: vi.fn(),
    } as unknown as Response;

    echoHandler(req, res);

    expect(res.status).toHaveBeenCalledWith(200);
    expect(res.json).toHaveBeenCalledWith({ echo: 'hello', length: 5 });
  });

  it('POST /api/echo with empty string returns length 0', () => {
    const req = {
      method: 'POST',
      url: '/api/echo',
      body: { message: '' },
      headers: { 'content-type': 'application/json' },
    } as Request;
    const res = {
      status: vi.fn().mockReturnThis(),
      json: vi.fn(),
    } as unknown as Response;

    echoHandler(req, res);

    expect(res.status).toHaveBeenCalledWith(200);
    expect(res.json).toHaveBeenCalledWith({ echo: '', length: 0 });
  });

  it('POST /api/echo with unicode characters returns correct length', () => {
    const req = {
      method: 'POST',
      url: '/api/echo',
      body: { message: '你好世界' },
      headers: { 'content-type': 'application/json' },
    } as Request;
    const res = {
      status: vi.fn().mockReturnThis(),
      json: vi.fn(),
    } as unknown as Response;

    echoHandler(req, res);

    expect(res.status).toHaveBeenCalledWith(200);
    expect(res.json).toHaveBeenCalledWith({ echo: '你好世界', length: 4 });
  });
});
