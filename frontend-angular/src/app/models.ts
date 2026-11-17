export type MessageRole = 'user' | 'assistant';

export interface Citation {
  chunk_id: number | string | null;
  document_id: string;
  page: number;
  bboxes: BoundingBox[];
  snippet: string;
}

export type BoundingBox =
  | readonly [number, number, number, number]
  | { x0: number; y0: number; x1: number; y1: number };

export interface ChatMessage {
  id: string;
  role: MessageRole;
  content: string;
  citations: Citation[];
  created_at?: string;
  streaming?: boolean;
  status?: string;
  error?: string;
}

export interface DocumentInfo {
  id: string;
  filename: string | null;
  status: string;
  pages?: number;
}

export interface DocumentUploadResponse {
  document_id: string;
  filename: string;
  status: string;
  pages: number;
}

export interface ConversationSummary {
  id: string;
  title: string;
  created_at?: string;
  updated_at?: string;
}

export interface ConversationDetails extends ConversationSummary {
  documents: DocumentInfo[];
}

export interface ConversationPage {
  items: ConversationSummary[];
  limit: number;
  offset: number;
  has_more: boolean;
}

export interface StreamError {
  code: string;
  message: string;
  retryable: boolean;
}
