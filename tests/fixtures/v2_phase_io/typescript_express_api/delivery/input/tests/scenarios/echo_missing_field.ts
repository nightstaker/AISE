import { describe, it, expect, vi } from 'vitest';
import { Request, Response } from 'express';
import { echoHandler } from '../../src/routes/echo_handler';

describe('echo_missing_field', () => {
  it('POST /api/echo without message field returns HTTP 400', () => {
    const req = {
      method: 'POST',
      url: '/api/echo',
      body: { name: 'test' },
      headers: { 'content-type': 'application/json' },
    } as Request;
    const res = {
      status: vi.fn().mockReturnThis(),
      json: vi.fn(),
    } as unknown as Response;

    echoHandler(req, res);

    expect(res.status).toHaveBeenCalledWith(400);
    const callArgs = res.json.mock.calls[0][0] as { error: string };
    expect(callArgs.error).toBeDefined();
    expect(typeof callArgs.error).toBe('string');
  });

  it('POST /api/echo with empty body returns HTTP 400', () => {
    const req = {
      method: 'POST',
      url: '/api/echo',
      body: {},
      headers: { 'content-type': 'application/json' },
    } as Request;
    const res = {
      status: vi.fn().mockReturnThis(),
      json: vi.fn(),
    } as unknown as Response;

    echoHandler(req, res);

    expect(res.status).toHaveBeenCalledWith(400);
    const callArgs = res.json.mock.calls[0][0] as { error: string };
    expect(callArgs.error).toBeDefined();
  });

  it('POST /api/echo with null body returns HTTP 400', () => {
    const req = {
      method: 'POST',
      url: '/api/echo',
      body: null,
      headers: { 'content-type': 'application/json' },
    } as Request;
    const res = {
      status: vi.fn().mockReturnThis(),
      json: vi.fn(),
    } as unknown as Response;

    echoHandler(req, res);

    expect(res.status).toHaveBeenCalledWith(400);
  });
});
