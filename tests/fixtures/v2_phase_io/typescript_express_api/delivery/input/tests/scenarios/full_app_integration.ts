import { describe, it, expect, beforeAll } from 'vitest';
import request from 'supertest';
import { createApp } from '../../src/server/app_builder';

describe('full_app_integration', () => {
  let app: ReturnType<typeof createApp>;

  beforeAll(() => {
    app = createApp();
  });

  it('GET /healthz returns HTTP 200 with correct body', async () => {
    const res = await request(app).get('/healthz');
    expect(res.statusCode).toBe(200);
    expect(res.body).toEqual({ status: 'ok' });
  });

  it('POST /api/echo returns correct echo and length', async () => {
    const res = await request(app)
      .post('/api/echo')
      .send({ message: 'hello' })
      .set('Content-Type', 'application/json');
    expect(res.statusCode).toBe(200);
    expect(res.body.echo).toBe('hello');
    expect(res.body.length).toBe(5);
  });

  it('POST /api/echo without message field returns HTTP 400', async () => {
    const res = await request(app)
      .post('/api/echo')
      .send({ name: 'test' })
      .set('Content-Type', 'application/json');
    expect(res.statusCode).toBe(400);
    expect(res.body.error).toBeDefined();
  });

  it('POST /api/echo with malformed JSON returns HTTP 400', async () => {
    const res = await request(app)
      .post('/api/echo')
      .send('not valid json{')
      .set('Content-Type', 'application/json');
    expect(res.statusCode).toBe(400);
    expect(res.body.error).toBeDefined();
  });

  it('POST /api/echo with empty message returns length 0', async () => {
    const res = await request(app)
      .post('/api/echo')
      .send({ message: '' })
      .set('Content-Type', 'application/json');
    expect(res.statusCode).toBe(200);
    expect(res.body.echo).toBe('');
    expect(res.body.length).toBe(0);
  });

  it('POST /api/echo with unicode characters returns correct length', async () => {
    const res = await request(app)
      .post('/api/echo')
      .send({ message: '你好世界' })
      .set('Content-Type', 'application/json');
    expect(res.statusCode).toBe(200);
    expect(res.body.echo).toBe('你好世界');
    expect(res.body.length).toBe(4);
  });

  it('GET /healthz response has correct content-type', async () => {
    const res = await request(app).get('/healthz');
    expect(res.statusCode).toBe(200);
    expect(res.headers['content-type']).toMatch(/application\/json/);
  });
});
