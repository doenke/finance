// Privacy mode: blurs all amounts (e.g. when showing the app on the phone). Stored per device.
const KEY = 'finanzen:private';

function stored(): boolean {
  try {
    return localStorage.getItem(KEY) === '1';
  } catch {
    return false;
  }
}

export const privacy = $state({ on: false });

export function initPrivacy(): void {
  privacy.on = stored();
  document.documentElement.classList.toggle('private', privacy.on);
}

export function setPrivate(on: boolean): void {
  privacy.on = on;
  document.documentElement.classList.toggle('private', on);
  try {
    if (on) localStorage.setItem(KEY, '1');
    else localStorage.removeItem(KEY);
  } catch {
    // storage may be unavailable
  }
}
