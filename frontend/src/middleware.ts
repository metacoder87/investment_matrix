import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

// Protected routes that require authentication
const protectedRoutes = [
    '/market',
    '/portfolio',
    '/paper',
    '/backtests',
    '/settings',
    '/pipeline'
];

// Public routes that don't require authentication
const publicRoutes = ['/login', '/register', '/'];

export function middleware(request: NextRequest) {
    const { pathname } = request.nextUrl;

    // Check if the current path is protected
    const isProtectedRoute = protectedRoutes.some(route =>
        pathname.startsWith(route)
    );

    // Check if the current path is public
    const isPublicRoute = publicRoutes.some(route =>
        pathname === route || pathname.startsWith(route)
    );

    // Get token from cookie or localStorage (we'll check both)
    // Note: Middleware runs on server, so we check cookies
    const token = request.cookies.get('auth_token')?.value;

    // If trying to access protected route without token, redirect to login
    if (isProtectedRoute && !token) {
        const loginUrl = new URL('/login', request.url);
        loginUrl.searchParams.set('redirect', pathname);
        return NextResponse.redirect(loginUrl);
    }

    // If already logged in and trying to access login/register, redirect to market
    if ((pathname === '/login' || pathname === '/register') && token) {
        return NextResponse.redirect(new URL('/market', request.url));
    }

    return NextResponse.next();
}

// Configure which routes this middleware runs on
export const config = {
    matcher: [
        /*
         * Match all request paths except for the ones starting with:
         * - api (API routes)
         * - _next/static (static files)
         * - _next/image (image optimization files)
         * - favicon.ico (favicon file)
         */
        '/((?!api|_next/static|_next/image|favicon.ico).*)',
    ],
};
