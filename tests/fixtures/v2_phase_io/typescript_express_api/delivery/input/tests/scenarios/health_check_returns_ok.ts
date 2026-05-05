import { describe, it, expect, vi } from 'vitest';
import { Request, Response } from 'express';
import { healthHandler } from '../../src/routes/health_handler';

describe('health_check_returns_ok', () => {
  it('GET /healthz returns HTTP 200 with JSON body {"status":"ok"}', () => {
    const req = {} as Request;
    const res = {
      status: vi.fn().mockReturnThis(),
      json: vi.fn(),
    } as unknown as Response;

    healthHandler(req, res);

    expect(res.status).toHaveBeenCalledWith(200);
    expect(res.json).toHaveBeenCalledWith({ status: 'ok' });
  });
});
