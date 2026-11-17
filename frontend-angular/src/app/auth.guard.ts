import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { AuthService } from './auth.service';

export const requireAuth: CanActivateFn = async () => {
  const auth = inject(AuthService);
  const router = inject(Router);
  if (!auth.isConfigured || !(await auth.getAccessToken())) {
    return router.parseUrl('/login');
  }
  return true;
};
