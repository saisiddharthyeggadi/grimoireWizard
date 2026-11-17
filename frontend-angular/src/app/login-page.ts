import { ChangeDetectionStrategy, Component, signal } from '@angular/core';
import { AuthService } from './auth.service';

@Component({
  changeDetection: ChangeDetectionStrategy.OnPush,
  selector: 'app-login-page',
  template: `
    <main class="login-page">
      <section class="login-card">
        <p class="login-kicker">GRIMOIRE WIZARD</p>
        <h1>Sign in to your reading room</h1>
        <p>Your documents and conversations are private to your account.</p>
        @if (!auth.isConfigured) {
          <p class="login-error" role="alert">
            Authentication needs the public Supabase URL and anon key in the
            Angular environment configuration.
          </p>
        } @else {
          <button type="button" [disabled]="busy()" (click)="signIn()">
            {{ busy() ? 'Opening Google…' : 'Continue with Google' }}
          </button>
        }
        @if (error()) {
          <p class="login-error" role="alert">{{ error() }}</p>
        }
      </section>
    </main>
  `,
  styles: `
    .login-page { min-height: 100vh; display: grid; place-items: center; padding: 24px; background: #f4f1eb; }
    .login-card { width: min(100%, 420px); padding: 40px; border: 1px solid #e4ded3; border-radius: 20px; background: #fffdfa; box-shadow: 0 20px 60px #2e261712; }
    .login-kicker { color: #806348; font-size: 12px; font-weight: 700; letter-spacing: .14em; }
    h1 { margin: 12px 0; color: #29241f; font-size: 30px; }
    .login-card > p:not(.login-kicker) { color: #686158; line-height: 1.6; }
    button { width: 100%; margin-top: 16px; padding: 13px 18px; border: 0; border-radius: 10px; background: #37302a; color: white; font: inherit; font-weight: 600; cursor: pointer; }
    button:disabled { opacity: .6; cursor: wait; }
    .login-card .login-error { color: #a12e2e; }
  `,
})
export class LoginPage {
  readonly busy = signal(false);
  readonly error = signal('');

  constructor(readonly auth: AuthService) {}

  async signIn(): Promise<void> {
    this.busy.set(true);
    this.error.set('');
    try {
      await this.auth.signInWithGoogle();
    } catch (error) {
      this.error.set(error instanceof Error ? error.message : 'Google sign-in failed.');
      this.busy.set(false);
    }
  }
}
