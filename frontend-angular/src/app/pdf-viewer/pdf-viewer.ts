import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  effect,
  input,
  output,
  signal,
  ViewChild,
} from '@angular/core';
import type { PDFDocumentProxy, PDFPageProxy } from 'pdfjs-dist';
import type { BoundingBox, Citation } from '../models';

const pdfDocuments = new Map<string, Promise<PDFDocumentProxy>>();

@Component({
  changeDetection: ChangeDetectionStrategy.OnPush,
  selector: 'app-pdf-viewer',
  templateUrl: './pdf-viewer.html',
  styleUrl: './pdf-viewer.scss',
})
export class PdfViewerComponent {
  readonly sourceUrl = input<string | null>(null);
  readonly citation = input.required<Citation>();
  readonly documentName = input('Source document');
  readonly loadError = input('');
  readonly closed = output<void>();
  readonly pageNumber = signal(1);
  readonly pageCount = signal(0);
  readonly loading = signal(false);
  readonly viewerError = signal('');
  private readonly renderedPage = signal<PDFPageProxy | null>(null);
  private readonly canvasElement = signal<HTMLCanvasElement | null>(null);
  private renderSequence = 0;
  private readonly pageCache = new Map<number, PDFPageProxy>();

  @ViewChild('pdfCanvas')
  set pdfCanvas(element: ElementRef<HTMLCanvasElement> | undefined) {
    this.setCanvas(element?.nativeElement ?? null);
  }

  constructor() {
    effect(() => {
      const citation = this.citation();
      const url = this.sourceUrl();
      const loadError = this.loadError();
      this.pageNumber.set(citation.page);
      this.viewerError.set(loadError);
      if (url) {
        void this.openDocument(url, citation.page);
      } else {
        this.pageCount.set(0);
      }
    });
  }

  setCanvas(element: HTMLCanvasElement | null): void {
    this.canvasElement.set(element);
    if (element && this.renderedPage()) {
      void this.renderCurrentPage();
    }
  }

  previousPage(): void {
    if (this.pageNumber() > 1) {
      this.pageNumber.update((page) => page - 1);
      void this.showPage(this.pageNumber());
    }
  }

  nextPage(): void {
    if (this.pageNumber() < this.pageCount()) {
      this.pageNumber.update((page) => page + 1);
      void this.showPage(this.pageNumber());
    }
  }

  close(): void {
    this.closed.emit();
  }

  private async openDocument(url: string, pageNumber: number): Promise<void> {
    const sequence = ++this.renderSequence;
    this.loading.set(true);
    this.viewerError.set('');
    try {
      const pdf = await this.getPdf(url);
      if (sequence !== this.renderSequence) {
        return;
      }
      this.pageCount.set(pdf.numPages);
      const initialPage = Math.max(1, Math.min(pageNumber, pdf.numPages));
      this.pageNumber.set(initialPage);
      this.pageCache.clear();
      await this.showPage(initialPage);
      void this.prefetchNearbyPages(pdf, initialPage);
    } catch (error) {
      if (sequence === this.renderSequence) {
        this.viewerError.set(
          error instanceof Error ? error.message : 'The PDF could not be opened.',
        );
      }
    } finally {
      if (sequence === this.renderSequence) {
        this.loading.set(false);
      }
    }
  }

  private async getPdf(url: string): Promise<PDFDocumentProxy> {
    const cached = pdfDocuments.get(url);
    if (cached) {
      return cached;
    }
    const loadTask = import('pdfjs-dist').then((pdfjs) => {
      pdfjs.GlobalWorkerOptions.workerSrc = new URL(
        'assets/pdf.worker.min.mjs',
        document.baseURI,
      ).toString();
      return pdfjs.getDocument({ url, withCredentials: false }).promise;
    });
    pdfDocuments.set(url, loadTask);
    try {
      return await loadTask;
    } catch (error) {
      pdfDocuments.delete(url);
      throw error;
    }
  }

  private async showPage(pageNumber: number): Promise<void> {
    const url = this.sourceUrl();
    if (!url) {
      return;
    }
    this.loading.set(true);
    try {
      const pdf = await this.getPdf(url);
      const page = await this.getPage(pdf, pageNumber);
      this.renderedPage.set(page);
      await this.renderCurrentPage();
      void this.prefetchNearbyPages(pdf, pageNumber);
    } catch (error) {
      this.viewerError.set(
        error instanceof Error ? error.message : 'This PDF page could not be rendered.',
      );
    } finally {
      this.loading.set(false);
    }
  }

  private async renderCurrentPage(): Promise<void> {
    const page = this.renderedPage();
    const canvas = this.canvasElement();
    if (!page || !canvas) {
      return;
    }
    const context = canvas.getContext('2d', { alpha: false });
    if (!context) {
      this.viewerError.set('Your browser could not create a PDF canvas.');
      return;
    }

    const baseViewport = page.getViewport({ scale: 1 });
    const containerWidth = canvas.parentElement?.clientWidth ?? baseViewport.width;
    const scale = Math.min(1.35, containerWidth / baseViewport.width);
    const viewport = page.getViewport({ scale });
    const outputScale = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.floor(viewport.width * outputScale);
    canvas.height = Math.floor(viewport.height * outputScale);
    canvas.style.width = `${Math.floor(viewport.width)}px`;
    canvas.style.height = `${Math.floor(viewport.height)}px`;
    context.setTransform(outputScale, 0, 0, outputScale, 0, 0);
    await page.render({ canvas, canvasContext: context, viewport }).promise;
    this.drawCitationBoxes(context, viewport, this.citation().bboxes);
  }

  private drawCitationBoxes(
    context: CanvasRenderingContext2D,
    viewport: ReturnType<PDFPageProxy['getViewport']>,
    boxes: BoundingBox[],
  ): void {
    context.save();
    context.fillStyle = 'rgba(230, 177, 69, 0.26)';
    context.strokeStyle = 'rgba(171, 117, 24, 0.85)';
    context.lineWidth = 1.5;
    for (const box of boxes) {
      const coordinates: readonly number[] =
        'x0' in box ? [box.x0, box.y0, box.x1, box.y1] : box;
      if (coordinates.length !== 4 || !coordinates.every(Number.isFinite)) {
        continue;
      }
      const firstPoint = viewport.convertToViewportPoint(coordinates[0], coordinates[1]);
      const secondPoint = viewport.convertToViewportPoint(coordinates[2], coordinates[3]);
      const [x0, y0] = firstPoint;
      const [x1, y1] = secondPoint;
      const left = Math.min(x0, x1);
      const top = Math.min(y0, y1);
      const width = Math.abs(x1 - x0);
      const height = Math.abs(y1 - y0);
      context.fillRect(left, top, width, height);
      context.strokeRect(left, top, width, height);
    }
    context.restore();
  }

  private async getPage(
    pdf: PDFDocumentProxy,
    pageNumber: number,
  ): Promise<PDFPageProxy> {
    const cached = this.pageCache.get(pageNumber);
    if (cached) {
      return cached;
    }
    const page = await pdf.getPage(pageNumber);
    this.pageCache.set(pageNumber, page);
    return page;
  }

  private async prefetchNearbyPages(
    pdf: PDFDocumentProxy,
    pageNumber: number,
  ): Promise<void> {
    const nearby = [pageNumber - 1, pageNumber + 1].filter(
      (page) => page >= 1 && page <= pdf.numPages,
    );
    await Promise.all(
      nearby.map(async (page) => {
        await this.getPage(pdf, page);
      }),
    );
  }
}
