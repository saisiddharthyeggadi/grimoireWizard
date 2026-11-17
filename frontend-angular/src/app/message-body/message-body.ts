import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import DOMPurify from 'dompurify';
import { marked } from 'marked';

@Component({
  changeDetection: ChangeDetectionStrategy.OnPush,
  selector: 'app-message-body',
  template: '<div class="markdown-body" [innerHTML]="html()"></div>',
  styleUrl: './message-body.scss',
})
export class MessageBody {
  readonly content = input.required<string>();
  protected readonly html = computed(() => {
    const parsed = marked.parse(this.content(), { async: false });
    return DOMPurify.sanitize(parsed);
  });
}
