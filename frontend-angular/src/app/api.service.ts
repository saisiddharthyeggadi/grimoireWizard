import { Injectable, signal } from '@angular/core';
import { environment } from '../environments/environment';
import { AuthService } from './auth.service';
import {
  ChatMessage,
  ConversationDetails,
  ConversationPage,
  ConversationSummary,
  DocumentUploadResponse,
  DocumentInfo,
  StreamError,
  Citation,
} from './models';

export class ApiRequestError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = 'ApiRequestError';
  }
}

@Injectable({ providedIn: 'root' })
export class ApiService {
  private readonly storageKey = 'grimoire.apiBaseUrl';
  readonly baseUrl = signal(this.loadBaseUrl());

  constructor(private readonly auth: AuthService) {}

  setBaseUrl(value: string): void {
    const url = value.trim().replace(/\/+$/, '');
    let parsed: URL;
    try {
      parsed = new URL(url);
    } catch {
      throw new Error('Enter a complete API URL, including http:// or https://.');
    }
    if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
      throw new Error('The API URL must use HTTP or HTTPS.');
    }
    this.baseUrl.set(url);
    localStorage.setItem(this.storageKey, url);
  }

  async health(): Promise<void> {
    const response = await this.request('/health');
    const body = (await response.json()) as { status?: string };
    if (body.status !== 'ok') {
      throw new Error('The backend health check returned an unexpected response.');
    }
  }

  async getConversations(
    limit = 30,
    offset = 0,
    signal?: AbortSignal,
  ): Promise<ConversationPage> {
    return this.getJson<ConversationPage>(
      `/conversations?limit=${limit}&offset=${offset}`,
      signal,
    );
  }

  getConversation(id: string, signal?: AbortSignal): Promise<ConversationDetails> {
    return this.getJson<ConversationDetails>(
      `/conversations/${encodeURIComponent(id)}`,
      signal,
    );
  }

  getMessages(id: string, signal?: AbortSignal): Promise<ChatMessage[]> {
    return this.getJson<ChatMessage[]>(
      `/conversations/${encodeURIComponent(id)}/messages`,
      signal,
    );
  }

  createConversation(title?: string): Promise<ConversationSummary> {
    return this.getJson<ConversationSummary>('/conversations', undefined, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(title ? { title } : {}),
    });
  }

  async getDocuments(signal?: AbortSignal): Promise<DocumentInfo[]> {
    const response = await this.request('/documents', { signal });
    const body: unknown = await response.json();
    if (Array.isArray(body)) {
      return body.map((item: unknown) => this.normalizeDocument(item));
    }
    if (
      typeof body === 'object' &&
      body !== null &&
      'items' in body &&
      Array.isArray(body.items)
    ) {
      return body.items.map((item: unknown) => this.normalizeDocument(item));
    }
    throw new Error('The document library returned an unsupported response.');
  }

  async uploadPdf(file: File): Promise<DocumentInfo> {
    const body = new FormData();
    body.append('file', file);
    const result = await this.getJson<DocumentUploadResponse>('/documents', undefined, {
      method: 'POST',
      body,
    });
    return {
      id: result.document_id,
      filename: result.filename,
      status: result.status,
      pages: result.pages,
    };
  }

  attachDocument(conversationId: string, documentId: string): Promise<DocumentInfo> {
    return this.getJson<DocumentInfo>(
      `/conversations/${encodeURIComponent(conversationId)}/documents`,
      undefined,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ document_id: documentId }),
      },
    );
  }

  async getDocumentFile(id: string, signal?: AbortSignal): Promise<string> {
    const result = await this.getJson<{ url?: string; signed_url?: string }>(
      `/documents/${encodeURIComponent(id)}/file`,
      signal,
    );
    const url = result.url ?? result.signed_url;
    if (!url) {
      throw new Error('The backend did not return a signed PDF URL.');
    }
    return url;
  }

  async streamMessage(
    conversationId: string,
    content: string,
    signal: AbortSignal,
    handlers: {
      onStatus: (status: string) => void;
      onToken: (text: string) => void;
      onCitations: (citations: Citation[]) => void;
      onError: (error: StreamError) => void;
    },
  ): Promise<void> {
    const response = await this.request(
      `/conversations/${encodeURIComponent(conversationId)}/messages`,
      {
        method: 'POST',
        headers: {
          Accept: 'text/event-stream',
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ content }),
        signal,
      },
    );
    if (!response.body) {
      throw new Error('The backend returned an empty event stream.');
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let pending = '';
    let eventName = 'message';
    let dataLines: string[] = [];

    const dispatch = (block: string): void => {
      for (const line of block.split(/\r?\n/)) {
        if (line.startsWith('event:')) {
          eventName = line.slice(6).trim();
        } else if (line.startsWith('data:')) {
          dataLines.push(line.slice(5).trimStart());
        }
      }
      if (dataLines.length) {
        const data = JSON.parse(dataLines.join('\n')) as Record<string, unknown>;
        if (eventName === 'status' && typeof data['status'] === 'string') {
          handlers.onStatus(data['status']);
        } else if (eventName === 'token' && typeof data['text'] === 'string') {
          handlers.onToken(data['text']);
        } else if (
          eventName === 'citations' &&
          Array.isArray(data['citations'])
        ) {
          handlers.onCitations(data['citations'] as Citation[]);
        } else if (eventName === 'error') {
          handlers.onError({
            code: typeof data['code'] === 'string' ? data['code'] : 'unknown',
            message:
              typeof data['message'] === 'string'
                ? data['message']
                : 'The answer stream failed.',
            retryable: data['retryable'] === true,
          });
        }
      }
      eventName = 'message';
      dataLines = [];
    };

    try {
      while (true) {
        const { done, value } = await reader.read();
        pending += decoder.decode(value, { stream: !done });
        const blocks = pending.split(/\r?\n\r?\n/);
        pending = blocks.pop() ?? '';
        for (const block of blocks) {
          dispatch(block);
        }
        if (done) {
          if (pending.trim()) {
            dispatch(pending);
          }
          break;
        }
      }
    } finally {
      reader.releaseLock();
    }
  }

  private loadBaseUrl(): string {
    try {
      return localStorage.getItem(this.storageKey) ?? environment.apiBaseUrl;
    } catch {
      return environment.apiBaseUrl;
    }
  }

  private async getJson<T>(
    path: string,
    signal?: AbortSignal,
    init: RequestInit = {},
  ): Promise<T> {
    const response = await this.request(path, { ...init, signal });
    return (await response.json()) as T;
  }

  private async request(path: string, init: RequestInit = {}): Promise<Response> {
    let response: Response;
    const headers = new Headers(init.headers);
    if (path !== '/health') {
      const token = await this.auth.getAccessToken();
      if (!token) {
        throw new Error('Sign in to continue.');
      }
      headers.set('Authorization', `Bearer ${token}`);
    }
    try {
      response = await fetch(`${this.baseUrl()}${path}`, {
        ...init,
        headers,
        credentials: 'omit',
      });
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') {
        throw error;
      }
      throw new Error(
        `Could not reach ${this.baseUrl()}. Check that the backend is running and allows this frontend origin.`,
      );
    }
    if (!response.ok) {
      let message = `Backend request failed (${response.status}).`;
      try {
        const body: unknown = await response.json();
        if (typeof body === 'object' && body !== null) {
          if ('detail' in body && typeof body.detail === 'string') {
            message = body.detail;
          } else if (
            'error' in body &&
            typeof body.error === 'object' &&
            body.error !== null &&
            'message' in body.error &&
            typeof body.error.message === 'string'
          ) {
            message = body.error.message;
          }
        }
      } catch {
        message = `Backend request failed (${response.status}).`;
      }
      throw new ApiRequestError(message, response.status);
    }
    return response;
  }

  private normalizeDocument(item: unknown): DocumentInfo {
    if (typeof item !== 'object' || item === null) {
      throw new Error('The document library returned an invalid document.');
    }
    const record = item as Record<string, unknown>;
    const id = record['id'] ?? record['document_id'];
    if (typeof id !== 'string') {
      throw new Error('The document library returned an item without an ID.');
    }
    return {
      id,
      filename: typeof record['filename'] === 'string' ? record['filename'] : null,
      status: typeof record['status'] === 'string' ? record['status'] : 'ready',
      pages: typeof record['pages'] === 'number' ? record['pages'] : undefined,
    };
  }
}
