import { Routes } from '@angular/router';
import { requireAuth } from './auth.guard';

export const routes: Routes = [
  {
    path: 'login',
    loadComponent: () => import('./login-page').then((module) => module.LoginPage),
  },
  {
    path: '',
    canActivate: [requireAuth],
    loadComponent: () =>
      import('./workspace/workspace-page').then((module) => module.WorkspacePage),
  },
  { path: '**', redirectTo: '' },
];
