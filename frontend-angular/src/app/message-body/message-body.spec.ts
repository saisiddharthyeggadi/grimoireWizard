import { TestBed } from '@angular/core/testing';
import { describe, expect, it } from 'vitest';
import { MessageBody } from './message-body';

describe('MessageBody', () => {
  it('sanitizes raw HTML before it reaches the view', async () => {
    await TestBed.configureTestingModule({
      imports: [MessageBody],
    }).compileComponents();

    const fixture = TestBed.createComponent(MessageBody);
    fixture.componentRef.setInput(
      'content',
      '<img src="x" onerror="alert(1)"><script>alert(2)</script>',
    );
    fixture.detectChanges();

    const output = fixture.nativeElement.querySelector('.markdown-body') as HTMLElement;
    expect(output.querySelector('script')).toBeNull();
    expect(output.querySelector('img')?.hasAttribute('onerror')).toBe(false);
  });
});
