import {
  ChangeDetectionStrategy,
  ChangeDetectorRef,
  Component,
  ComponentRef,
  computed,
  ElementRef,
  NgZone,
  OnDestroy,
  OnInit,
  signal,
  ViewChild,
  ViewContainerRef,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { ApiRequestError, ApiService } from '../api.service';
import { AuthService } from '../auth.service';
import { ChatMessage, Citation, ConversationDetails, ConversationSummary, DocumentInfo, StreamError } from '../models';
import { MessageBody } from '../message-body/message-body';
import type { PdfViewerComponent } from '../pdf-viewer/pdf-viewer';

@Component({
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, MessageBody],
  selector: 'app-workspace-page',
  templateUrl: './workspace-page.html',
})
export class WorkspacePage implements OnInit, OnDestroy {
  @ViewChild('messageList') private messageList?: ElementRef<HTMLDivElement>;
  @ViewChild('pdfPanelHost', { read: ViewContainerRef })
  private pdfPanelHost!: ViewContainerRef;

  readonly conversations = signal<ConversationSummary[]>([]);
  readonly conversation = signal<ConversationDetails | null>(null);
  readonly messages = signal<ChatMessage[]>([]);
  readonly selectedId = signal<string | null>(null);
  readonly draft = signal('');
  readonly sending = signal(false);
  readonly loadingHistory = signal(false);
  readonly loadingMoreHistory = signal(false);
  readonly historyHasMore = signal(false);
  readonly loadingConversation = signal(false);
  readonly uploading = signal(false);
  readonly checkingBackend = signal(false);
  readonly backendOnline = signal<boolean | null>(null);
  readonly statusText = signal('');
  readonly pageError = signal('');
  readonly toast = signal('');
  readonly showSettings = signal(false);
  readonly showDocumentPicker = signal(false);
  readonly documentLibrary = signal<DocumentInfo[]>([]);
  readonly documentLibraryLoading = signal(false);
  readonly documentLibraryError = signal('');
  readonly attachingDocumentId = signal<string | null>(null);
  readonly apiBaseDraft = signal('');
  readonly pdfPanelError = signal('');
  readonly canSend = computed(() => Boolean(this.draft().trim()) && !this.sending());
  readonly currentConversation = computed(
    () => this.conversations().find((item) => item.id === this.selectedId()) ?? null,
  );
  readonly attachedDocuments = computed(() => this.conversation()?.documents ?? []);

  private abortController: AbortController | null = null;
  private toastTimer: ReturnType<typeof setTimeout> | null = null;
  private pdfViewerModule: Promise<typeof import('../pdf-viewer/pdf-viewer')> | null = null;
  private pdfViewerRef: ComponentRef<PdfViewerComponent> | null = null;
  private pendingQuestion: string | null = null;

  constructor(
    readonly api: ApiService,
    private readonly auth: AuthService,
    private readonly router: Router,
    private readonly zone: NgZone,
    private readonly changeDetector: ChangeDetectorRef,
  ) {
    this.apiBaseDraft.set(api.baseUrl());
  }

  ngOnInit(): void {
    void this.loadWorkspace();
  }

  async signOut(): Promise<void> {
    try {
      await this.auth.signOut();
      await this.router.navigateByUrl('/login');
    } catch (error) {
      this.showToast(this.errorMessage(error));
    }
  }

  ngOnDestroy(): void {
    this.abortController?.abort();
    this.pdfViewerRef?.destroy();
    if (this.toastTimer) {
      clearTimeout(this.toastTimer);
    }
  }

  async loadWorkspace(): Promise<void> {
    this.loadingHistory.set(true);
    this.pageError.set('');
    const [healthResult, historyResult] = await Promise.allSettled([
      this.api.health(),
      this.api.getConversations(),
    ]);
    this.backendOnline.set(healthResult.status === 'fulfilled');
    if (historyResult.status === 'fulfilled') {
      this.conversations.set(historyResult.value.items);
      this.historyHasMore.set(historyResult.value.has_more);
      if (historyResult.value.items.length) {
        await this.openConversation(historyResult.value.items[0].id);
      }
    } else {
      this.pageError.set(this.errorMessage(historyResult.reason));
    }
    this.loadingHistory.set(false);
  }

  async checkBackend(): Promise<void> {
    this.checkingBackend.set(true);
    try {
      await this.api.health();
      this.backendOnline.set(true);
      this.showToast('Backend connection is healthy.');
    } catch (error) {
      this.backendOnline.set(false);
      this.showToast(this.errorMessage(error));
    } finally {
      this.checkingBackend.set(false);
    }
  }

  async createConversation(): Promise<void> {
    this.stopStreaming();
    this.pageError.set('');
    try {
      const created = await this.api.createConversation();
      this.conversations.update((items) => [created, ...items]);
      this.selectedId.set(created.id);
      this.conversation.set({ ...created, documents: [] });
      this.messages.set([]);
      this.statusText.set('');
      this.scrollToLatest();
    } catch (error) {
      this.showToast(this.errorMessage(error));
    }
  }

  async openConversation(id: string): Promise<void> {
    if (this.selectedId() === id && this.conversation()) {
      return;
    }
    this.stopStreaming();
    this.selectedId.set(id);
    this.loadingConversation.set(true);
    this.pageError.set('');
    this.messages.set([]);
    try {
      const [details, messages] = await Promise.all([
        this.api.getConversation(id),
        this.api.getMessages(id),
      ]);
      if (this.selectedId() !== id) {
        return;
      }
      this.conversation.set(details);
      this.messages.set(messages);
      if (messages.some((message) => message.citations?.length)) {
        this.prefetchPdfViewer();
      }
      this.scrollToLatest();
    } catch (error) {
      if (this.selectedId() === id) {
        this.pageError.set(this.errorMessage(error));
      }
    } finally {
      if (this.selectedId() === id) {
        this.loadingConversation.set(false);
      }
    }
  }

  async loadMoreConversations(): Promise<void> {
    if (this.loadingMoreHistory() || !this.historyHasMore()) {
      return;
    }
    this.loadingMoreHistory.set(true);
    try {
      const currentItems = this.conversations();
      const result = await this.api.getConversations(30, currentItems.length);
      this.conversations.update((items) => [...items, ...result.items]);
      this.historyHasMore.set(result.has_more);
    } catch (error) {
      this.showToast(this.errorMessage(error));
    } finally {
      this.loadingMoreHistory.set(false);
    }
  }

  async sendMessage(): Promise<void> {
    const question = this.draft().trim();
    if (!question || !this.selectedId() || this.sending()) {
      return;
    }
    this.draft.set('');
    await this.streamAnswer(question, true);
  }

  cancelAnswer(): void {
    this.abortController?.abort();
  }

  retryMessage(message: ChatMessage): void {
    if (!message.error || !this.pendingQuestion || this.sending()) {
      return;
    }
    const question = this.pendingQuestion;
    this.updateMessage(message.id, {
      error: undefined,
      content: '',
      status: '',
      streaming: true,
    });
    void this.streamAnswer(question, false, message.id);
  }

  async onPdfSelected(event: Event): Promise<void> {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    input.value = '';
    if (!file) {
      return;
    }
    if (!file.name.toLowerCase().endsWith('.pdf')) {
      this.showToast('Choose a PDF file.');
      return;
    }
    if (file.size > 100 * 1024 * 1024) {
      this.showToast('PDFs must be 100 MB or smaller.');
      return;
    }
    this.uploading.set(true);
    this.pageError.set('');
    try {
      const document = await this.api.uploadPdf(file);
      let conversationId = this.selectedId();
      if (!conversationId) {
        const created = await this.api.createConversation(file.name);
        conversationId = created.id;
        this.conversations.update((items) => [created, ...items]);
        this.selectedId.set(conversationId);
      }
      await this.api.attachDocument(conversationId, document.id);
      await this.refreshSelectedConversation(conversationId);
      this.showToast(`Added ${document.filename ?? file.name} to this conversation.`);
    } catch (error) {
      this.showToast(this.errorMessage(error));
    } finally {
      this.uploading.set(false);
    }
  }

  async openDocumentPicker(): Promise<void> {
    this.showDocumentPicker.set(true);
    this.documentLibraryLoading.set(true);
    this.documentLibraryError.set('');
    try {
      this.documentLibrary.set(await this.api.getDocuments());
    } catch (error) {
      this.documentLibraryError.set(this.errorMessage(error));
    } finally {
      this.documentLibraryLoading.set(false);
    }
  }

  closeDocumentPicker(): void {
    this.showDocumentPicker.set(false);
  }

  async attachFromLibrary(document: DocumentInfo): Promise<void> {
    if (this.attachingDocumentId()) {
      return;
    }
    this.attachingDocumentId.set(document.id);
    try {
      let conversationId = this.selectedId();
      if (!conversationId) {
        const created = await this.api.createConversation(
          document.filename ?? undefined,
        );
        conversationId = created.id;
        this.conversations.update((items) => [created, ...items]);
        this.selectedId.set(conversationId);
        this.conversation.set({ ...created, documents: [] });
      }
      await this.api.attachDocument(conversationId, document.id);
      await this.refreshSelectedConversation(conversationId);
      this.closeDocumentPicker();
      this.showToast(`Attached ${document.filename ?? 'document'}.`);
    } catch (error) {
      this.documentLibraryError.set(this.errorMessage(error));
    } finally {
      this.attachingDocumentId.set(null);
    }
  }

  async openCitation(citation: Citation): Promise<void> {
    this.prefetchPdfViewer();
    this.pdfPanelError.set('');
    const importTask = this.pdfViewerModule;
    if (!importTask) {
      this.showToast('The PDF viewer could not be loaded.');
      return;
    }
    let sourceUrl: string | null = null;
    try {
      sourceUrl = await this.api.getDocumentFile(citation.document_id);
    } catch (error) {
      this.pdfPanelError.set(
        `PDF preview is unavailable: ${this.errorMessage(error)} Older documents may need to be uploaded again to store their PDF.`,
      );
    }
    try {
      const module = await importTask;
      if (!this.pdfViewerRef) {
        this.pdfViewerRef = this.pdfPanelHost.createComponent(module.PdfViewerComponent);
        this.pdfViewerRef.instance.closed.subscribe(() => this.closePdfViewer());
      }
      this.pdfViewerRef.setInput('sourceUrl', sourceUrl);
      this.pdfViewerRef.setInput('citation', citation);
      this.pdfViewerRef.setInput(
        'documentName',
        this.documentNameFor(citation.document_id) ?? 'Source document',
      );
      this.pdfViewerRef.setInput('loadError', this.pdfPanelError());
      this.pdfViewerRef.changeDetectorRef.detectChanges();
    } catch (error) {
      this.showToast(`Could not open PDF preview: ${this.errorMessage(error)}`);
    }
  }

  closePdfViewer(): void {
    this.pdfViewerRef?.destroy();
    this.pdfViewerRef = null;
  }

  onEnterKey(event: Event): void {
    const keyboardEvent = event as KeyboardEvent;
    if (!keyboardEvent.shiftKey && !keyboardEvent.isComposing) {
      keyboardEvent.preventDefault();
      void this.sendMessage();
    }
  }

  openSettings(): void {
    this.apiBaseDraft.set(this.api.baseUrl());
    this.showSettings.set(true);
  }

  closeSettings(): void {
    this.showSettings.set(false);
  }

  onApiBaseInput(event: Event): void {
    this.apiBaseDraft.set((event.target as HTMLInputElement).value);
  }

  saveApiBase(): void {
    try {
      this.api.setBaseUrl(this.apiBaseDraft());
      this.showSettings.set(false);
      this.backendOnline.set(null);
      void this.loadWorkspace();
    } catch (error) {
      this.showToast(this.errorMessage(error));
    }
  }

  documentNameFor(documentId: string): string | null {
    return (
      this.conversation()?.documents.find((document) => document.id === documentId)
        ?.filename ?? null
    );
  }

  private async streamAnswer(
    question: string,
    addUserMessage: boolean,
    existingAssistantId?: string,
  ): Promise<void> {
    const conversationId = this.selectedId();
    if (!conversationId) {
      return;
    }
    this.pendingQuestion = question;
    const userMessage: ChatMessage = {
      id: crypto.randomUUID(),
      role: 'user',
      content: question,
      citations: [],
    };
    const assistantId = existingAssistantId ?? crypto.randomUUID();
    const assistantMessage: ChatMessage = {
      id: assistantId,
      role: 'assistant',
      content: '',
      citations: [],
      streaming: true,
    };
    if (addUserMessage) {
      this.messages.update((items) => [...items, userMessage, assistantMessage]);
    } else {
      this.messages.update((items) =>
        items.map((item) => (item.id === assistantId ? assistantMessage : item)),
      );
    }
    this.sending.set(true);
    this.statusText.set('Starting response…');
    this.pageError.set('');
    this.scrollToLatest();
    const controller = new AbortController();
    this.abortController = controller;
    let tokenBuffer = '';
    let frameId: number | null = null;
    let streamError: StreamError | null = null;
    const flushTokens = (): void => {
      if (frameId !== null) {
        cancelAnimationFrame(frameId);
        frameId = null;
      }
      if (!tokenBuffer) {
        return;
      }
      const batch = tokenBuffer;
      tokenBuffer = '';
      this.zone.run(() => {
        this.messages.update((items) =>
          items.map((item) =>
            item.id === assistantId
              ? { ...item, content: item.content + batch }
              : item,
          ),
        );
        this.changeDetector.markForCheck();
        this.scrollToLatest();
      });
    };
    try {
      await this.zone.runOutsideAngular(() =>
        this.api.streamMessage(conversationId, question, controller.signal, {
          onStatus: (status) => {
            this.zone.run(() => {
              this.statusText.set(this.statusLabel(status));
              this.updateMessage(assistantId, { status: this.statusLabel(status) });
            });
          },
          onToken: (text) => {
            tokenBuffer += text;
            if (frameId === null) {
              frameId = requestAnimationFrame(flushTokens);
            }
          },
          onCitations: (citations) => {
            this.prefetchPdfViewer();
            this.zone.run(() => this.updateMessage(assistantId, { citations }));
          },
          onError: (error) => {
            streamError = error;
          },
        }),
      );
      flushTokens();
      const finalStreamError = streamError;
      if (finalStreamError) {
        this.zone.run(() => {
          this.updateMessage(assistantId, {
            streaming: false,
            status: '',
            error: this.streamErrorMessage(finalStreamError),
          });
        });
      } else {
        this.zone.run(() => {
          this.updateMessage(assistantId, {
            streaming: false,
            status: '',
          });
          void this.refreshConversationList();
        });
      }
    } catch (error) {
      flushTokens();
      if (error instanceof DOMException && error.name === 'AbortError') {
        this.zone.run(() =>
          this.updateMessage(assistantId, {
            streaming: false,
            status: '',
            error: 'Response stopped.',
          }),
        );
      } else {
        this.zone.run(() =>
          this.updateMessage(assistantId, {
            streaming: false,
            status: '',
            error: this.errorMessage(error),
          }),
        );
      }
    } finally {
      this.zone.run(() => {
        if (this.abortController === controller) {
          this.abortController = null;
          this.sending.set(false);
          this.statusText.set('');
        }
      });
    }
  }

  private async refreshSelectedConversation(id: string): Promise<void> {
    const details = await this.api.getConversation(id);
    if (this.selectedId() === id) {
      this.conversation.set(details);
    }
  }

  private async refreshConversationList(): Promise<void> {
    try {
      const result = await this.api.getConversations();
      this.conversations.set(result.items);
      this.historyHasMore.set(result.has_more);
    } catch (error) {
      this.showToast(this.errorMessage(error));
    }
  }

  private updateMessage(id: string, patch: Partial<ChatMessage>): void {
    this.messages.update((items) =>
      items.map((item) => (item.id === id ? { ...item, ...patch } : item)),
    );
    this.changeDetector.markForCheck();
  }

  private stopStreaming(): void {
    this.abortController?.abort();
    this.abortController = null;
    this.sending.set(false);
    this.statusText.set('');
  }

  private statusLabel(status: string): string {
    switch (status) {
      case 'rewriting':
        return 'Understanding your question';
      case 'retrieving':
        return 'Searching attached documents';
      case 'reranking':
        return 'Selecting the best passages';
      case 'generating':
        return 'Writing an answer';
      default:
        return 'Working';
    }
  }

  private streamErrorMessage(error: StreamError): string {
    if (error.code === 'document_not_ready') {
      return 'This document is still processing or has no indexed text. Try again when ingestion is complete.';
    }
    if (error.code === 'llm_unavailable') {
      return 'The answer service is temporarily unavailable.';
    }
    if (error.code === 'rate_limited') {
      return 'The answer service is rate limited. Wait a moment and retry.';
    }
    return error.message;
  }

  private errorMessage(error: unknown): string {
    if (error instanceof ApiRequestError) {
      if (error.status === 404) {
        return 'This backend endpoint is not available yet.';
      }
      if (error.status === 409) {
        return 'Attach a ready document before asking a question.';
      }
    }
    if (error instanceof Error) {
      return error.message;
    }
    return 'An unexpected error occurred.';
  }

  private showToast(message: string): void {
    this.toast.set(message);
    if (this.toastTimer) {
      clearTimeout(this.toastTimer);
    }
    this.toastTimer = setTimeout(() => this.toast.set(''), 5000);
  }

  private scrollToLatest(): void {
    requestAnimationFrame(() => {
      const element = this.messageList?.nativeElement;
      if (element) {
        element.scrollTop = element.scrollHeight;
      }
    });
  }

  private prefetchPdfViewer(): void {
    if (!this.pdfViewerModule) {
      this.pdfViewerModule = import('../pdf-viewer/pdf-viewer');
    }
    const idleWindow = window as Window & {
      requestIdleCallback?: (callback: () => void) => number;
    };
    const prefetch = (): void => {
      void import('pdfjs-dist');
    };
    if (idleWindow.requestIdleCallback) {
      idleWindow.requestIdleCallback(prefetch);
    } else {
      window.setTimeout(prefetch, 500);
    }
  }
}
