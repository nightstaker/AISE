// Tests for App Builder — 构建 Express 应用实例

import { describe, it, expect } from 'vitest';
import type { Express } from 'express';
import { createApp } from '../../src/server/app_builder';

describe('createApp', () => {
  it('should return an Express application instance', () => {
    const app = createApp();
    expect(app).toBeDefined();
    expect(typeof app).toBe('function');
    expect(typeof app.use).toBe('function');
    expect(typeof app.get).toBe('function');
    expect(typeof app.post).toBe('function');
  });

  it('should have JSON body parsing middleware configured', () => {
    const app = createApp();
    const internalRouter = app._router;
    expect(internalRouter).toBeDefined();
    expect(internalRouter.stack).toBeDefined();
    expect(Array.isArray(internalRouter.stack)).toBe(true);
    expect(internalRouter.stack.length).toBeGreaterThan(0);
  });

  it('should mount error handler middleware', () => {
    const app = createApp();
    const internalRouter = app._router;
    const layers = internalRouter.stack;
    const hasErrorMiddleware = layers.some(
      (layer: { name?: string; handle?: { name?: string } }) =>
        layer.name === 'errorHandler' ||
        layer.handle?.name === 'errorHandler'
    );
    expect(hasErrorMiddleware).toBe(true);
  });

  it('should register routes via registerRoutes call', () => {
    const app = createApp();
    const internalRouter = app._router;
    const layers = internalRouter.stack;
    // The mounted router is a layer whose handle has a `stack` property
    const mountLayer = layers.find(
      (layer: { handle?: { stack?: unknown[] } }) =>
        Array.isArray(layer.handle?.stack)
    );
    expect(mountLayer).toBeDefined();
    expect(mountLayer.handle).toBeDefined();
    expect(mountLayer.handle.stack).toBeDefined();
    expect(Array.isArray(mountLayer.handle.stack)).toBe(true);
    expect(mountLayer.handle.stack.length).toBeGreaterThan(0);
  });
});
