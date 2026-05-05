import { describe, it, expect, vi } from 'vitest';
import { Request, Response } from 'express';
import { healthHandler } from '../../src/routes/health_handler';

describe('healthHandler', () => {
  it('should return status ok with HTTP 200', () => {
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
