/**
 * Password utilities — Teacher Progress App
 */

const CHARSET = 'abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789!@#$';

export function generateStrongPassword(length = 12) {
    return Array.from({ length }, () => CHARSET[Math.floor(Math.random() * CHARSET.length)]).join('');
}

export function buildTeacherInviteText(email, password) {
    const origin = window.location.origin;
    const lines = [
        '=== Teacher App Invitation ===',
        `Login URL: ${origin}`,
        `Email:     ${email}`,
        password ? `Password:  ${password}` : '(password will be provided separately)',
        '',
        'Please change your password after first login.',
    ];
    return lines.join('\n');
}

export async function copyText(text) {
    try {
        await navigator.clipboard.writeText(text);
    } catch {
        // Fallback for older browsers
        const el = document.createElement('textarea');
        el.value = text;
        el.style.position = 'fixed';
        el.style.opacity = '0';
        document.body.appendChild(el);
        el.select();
        document.execCommand('copy');
        el.remove();
    }
}
