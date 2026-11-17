import { afterEach, describe, expect, it, vi } from 'vitest';
import { TestBed } from '@angular/core/testing';
import { ApiService } from './api.service';
import { AuthService } from './auth.service';

describe('ApiService SSE stream', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('parses status, token, citations, and error events from streamed chunks', async () => {
    const payload = [
      'event: status\ndata: {"status":"retrieving"}\n\n',
      'event: token\ndata: {"text":"Grounded "}\n\n',
      'event: citations\ndata: {"citations":[{"chunk_id":4,"document_id":"doc-1","page":6,"bboxes":[],"snippet":"Source"}]}\n\n',
      'event: error\ndata: {"code":"document_not_ready","message":"Not ready","retryable":false}\n\n',
    ];
    vi.stubGlobal(
      'fetch',
      vi.fn(
        async () =>
          new Response(
            new ReadableStream<Uint8Array>({
              start(controller) {
                for (const part of payload) {
                  controller.enqueue(new TextEncoder().encode(part));
                }
                controller.close();
              },
            }),
            { headers: { 'Content-Type': 'text/event-stream' } },
          ),
      ),
    );
    TestBed.configureTestingModule({
      providers: [
        ApiService,
        { provide: AuthService, useValue: { getAccessToken: async () => 'test-token' } },
      ],
    });
    const service = TestBed.inject(ApiService);
    service.setBaseUrl('http://127.0.0.1:8000');
    const statuses: string[] = [];
    const tokens: string[] = [];
    const citations: unknown[] = [];
    const errors: unknown[] = [];

    await service.streamMessage('conversation-1', 'Question', new AbortController().signal, {
      onStatus: (status) => statuses.push(status),
      onToken: (text) => tokens.push(text),
      onCitations: (items) => citations.push(...items),
      onError: (error) => errors.push(error),
    });

    expect(statuses).toEqual(['retrieving']);
    expect(tokens).toEqual(['Grounded ']);
    expect(citations).toHaveLength(1);
    expect(errors).toEqual([
      { code: 'document_not_ready', message: 'Not ready', retryable: false },
    ]);
    const requestHeaders = vi.mocked(fetch).mock.calls[0][1]?.headers as Headers;
    expect(requestHeaders.get('Authorization')).toBe('Bearer test-token');
  });
});
