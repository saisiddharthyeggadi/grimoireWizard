import { Injectable } from '@angular/core';
import type { SupabaseClient } from '@supabase/supabase-js';
import { environment } from '../environments/environment';

@Injectable({ providedIn: 'root' })
export class AuthService {
  readonly isConfigured = Boolean(environment.supabaseUrl && environment.supabaseAnonKey);

  private clientPromise: Promise<SupabaseClient> | null = null;

  async getAccessToken(): Promise<string | null> {
    const client = await this.getClient();
    if (!client) {
      return null;
    }
    const { data, error } = await client.auth.getSession();
    if (error) {
      throw new Error(`Could not read the sign-in session: ${error.message}`);
    }
    return data.session?.access_token ?? null;
  }

  async signInWithGoogle(): Promise<void> {
    const client = await this.getClient();
    if (!client) {
      throw new Error(
        'Set supabaseUrl and supabaseAnonKey in the Angular environment configuration.',
      );
    }
    const { error } = await client.auth.signInWithOAuth({
      provider: 'google',
      options: {
        redirectTo: window.location.origin,
        scopes: 'openid email profile',
      },
    });
    if (error) {
      throw new Error(`Google sign-in failed: ${error.message}`);
    }
  }

  async signOut(): Promise<void> {
    const client = await this.getClient();
    if (!client) {
      throw new Error('Authentication is not configured.');
    }
    const { error } = await client.auth.signOut();
    if (error) {
      throw new Error(`Could not sign out: ${error.message}`);
    }
  }

  private async getClient(): Promise<SupabaseClient | null> {
    if (!this.isConfigured) {
      return null;
    }
    this.clientPromise ??= import('@supabase/supabase-js').then(({ createClient }) =>
      createClient(environment.supabaseUrl, environment.supabaseAnonKey),
    );
    return this.clientPromise;
  }
}
