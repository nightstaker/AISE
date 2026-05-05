import { describe, it, expect, vi } from 'vitest';
import { Request, Response, NextFunction } from 'express';
import { errorHandler } from '../../src/middleware/error_handler';

describe('echo_invalid_json', () => {
  it('malformed JSON triggers SyntaxError handled as HTTP 400', () => {
    const syntaxError = new SyntaxError('Unexpected token');
    (syntaxError as any).status = 400;
    (syntaxError as any).body = {};
    syntaxError.name = 'SyntaxError';

    const req = {} as Request;
    const res = {
      status: vi.fn().mockReturnThis(),
      json: vi.fn(),
    } as unknown as Response;
    const next = {} as NextFunction;

    errorHandler(syntaxError, req, res, next);

    expect(res.status).toHaveBeenCalledWith(400);
    const callArgs = res.json.mock.calls[0][0] as { error: string };
    expect(callArgs.error).toBeDefined();
    expect(callArgs.error).toContain('Invalid JSON');
  });

  it('non-syntax errors return HTTP 500', () => {
    const genericError = new Error('Something went wrong');
    genericError.name = 'Error';

    const req = {} as Request;
    const res = {
      status: vi.fn().mockReturnThis(),
      json: vi.fn(),
    } as unknown as Response;
    const next = {} as NextFunction;

    errorHandler(genericError, req, res, next);

    expect(res.status).toHaveBeenCalledWith(500);
    const callArgs = res.json.mock.calls[0][0] as { error: string };
    expect(callArgs.error).toBe('Internal server error');
  });

  it('SyntaxError without 400 status is treated as generic error', () => {
    const syntaxError = new SyntaxError('Parse error');
    syntaxError.name = 'SyntaxError';

    const req = {} as Request;
    const res = {
      status: vi.fn().mockReturnThis(),
      json: vi.fn(),
    } as unknown as Response;
    const next = {} as NextFunction;

    errorHandler(syntaxError, req, res, next);

    expect(res.status).toHaveBeenCalledWith(500);
    const callArgs = res.json.mock.calls[0][0] as { error: string };
    expect(callArgs.error).toBe('Internal server error');
  });
});
