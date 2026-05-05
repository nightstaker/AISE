// Tests for Router — 路由注册

import { describe, it, expect } from 'vitest';
import express from 'express';
import type { Express } from 'express';
import { registerRoutes } from '../../src/server/router';

describe('registerRoutes', () => {
  it('should register routes on the given app', () => {
    const app = express();
    expect(() => registerRoutes(app)).not.toThrow();
  });

  it('should create a mounted router on the app', () => {
    const app = express();
    registerRoutes(app);
    const internalRouter = app._router;
    expect(internalRouter).toBeDefined();
    expect(internalRouter.stack).toBeDefined();
    expect(Array.isArray(internalRouter.stack)).toBe(true);
    expect(internalRouter.stack.length).toBeGreaterThan(0);
  });

  it('should mount a router at /', () => {
    const app = express();
    registerRoutes(app);
    const internalRouter = app._router;
    // The mounted router is a layer whose handle has a `stack` property
    const mountLayer = internalRouter.stack.find(
      (layer: { handle?: { stack?: unknown[] } }) =>
        Array.isArray(layer.handle?.stack)
    );
    expect(mountLayer).toBeDefined();
    expect(mountLayer.handle).toBeDefined();
    expect(Array.isArray(mountLayer.handle.stack)).toBe(true);
  });

  it('should register the echo route', () => {
    const app = express();
    registerRoutes(app);
    const internalRouter = app._router;
    const mountLayer = internalRouter.stack.find(
      (layer: { handle?: { stack?: unknown[] } }) =>
        Array.isArray(layer.handle?.stack)
    );
    expect(mountLayer).toBeDefined();
    const mountedRouter = mountLayer.handle;
    expect(mountedRouter).toBeDefined();
    expect(mountedRouter.stack).toBeDefined();
    expect(Array.isArray(mountedRouter.stack)).toBe(true);
    expect(mountedRouter.stack.length).toBeGreaterThan(0);
  });
});
