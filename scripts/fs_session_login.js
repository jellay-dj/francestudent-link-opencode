/**
 * fs_session_login.js — exporte la session du navigateur France Student.
 *
 * Le bridge échange le cookie de session contre un jeton d'accès via
 * l'endpoint documenté /api/auth/api-token. Ce jeton expire en quelques
 * minutes, mais le cookie de session dure plus longtemps : il suffit donc
 * d'exporter le cookie une fois.
 *
 * Le script ouvre Chrome avec un profil dédié. C'est l'UTILISATEUR qui se
 * connecte : aucun mot de passe n'est lu, saisi ni automatisé.
 *
 * Usage :  node scripts\fs_session_login.js
 * Sortie : .fs-session.json à la racine du dépôt (ignoré par Git).
 */
const fs = require('fs');
const path = require('path');
const puppeteer = require('puppeteer-core');

const ROOT = path.resolve(__dirname, '..');
const OUTPUT = path.join(ROOT, '.fs-session.json');
const PROFILE = path.join(ROOT, '.chrome-profile');
const LOGIN_URL = 'https://ia.francestudent.org/login';
const APP_URL = 'https://ia.francestudent.org/';

const sleep = ms => new Promise(r => setTimeout(r, ms));

function findChrome() {
    if (process.env.CHROME_PATH && fs.existsSync(process.env.CHROME_PATH)) {
        return process.env.CHROME_PATH;
    }
    const candidates = [];
    if (process.env.ProgramFiles) {
        candidates.push(path.join(process.env.ProgramFiles, 'Google', 'Chrome', 'Application', 'chrome.exe'));
    }
    if (process.env['ProgramFiles(x86)']) {
        candidates.push(path.join(process.env['ProgramFiles(x86)'], 'Google', 'Chrome', 'Application', 'chrome.exe'));
    }
    if (process.env.LOCALAPPDATA) {
        candidates.push(path.join(process.env.LOCALAPPDATA, 'Google', 'Chrome', 'Application', 'chrome.exe'));
    }
    if (process.platform === 'linux') {
        candidates.push('/usr/bin/google-chrome', '/usr/bin/chromium', '/usr/bin/chromium-browser');
    }
    if (process.platform === 'darwin') {
        candidates.push('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome');
    }
    return candidates.find(p => fs.existsSync(p)) || undefined;
}

async function main() {
    const executablePath = findChrome();
    if (!executablePath) {
        console.error('[fs_session_login] Chrome est introuvable. Renseignez CHROME_PATH.');
        process.exit(1);
    }

    const browser = await puppeteer.launch({
        headless: false,
        executablePath,
        userDataDir: PROFILE,
        args: ['--disable-gpu', '--no-first-run', '--no-default-browser-check'],
    });

    try {
        const page = await browser.newPage();
        console.log('[fs_session_login] Connectez-vous a France Student dans la fenetre qui vient de s\'ouvrir.');
        console.log('[fs_session_login] Repondez "ok" dans ce terminal une fois connecte.');

        // Wait for the user to confirm on the terminal.
        await new Promise(resolve => {
            process.stdin.resume();
            process.stdin.once('data', resolve);
        });

        await page.goto(APP_URL, { waitUntil: 'networkidle2', timeout: 60000 }).catch(() => {});
        await sleep(2000);

        const cookies = await browser.cookies([
            'https://ia.francestudent.org',
            'https://francestudent.org',
        ]);
        const session = cookies.filter(c => c.name === 'next-auth.session-token');
        if (!session.length) {
            console.error('[fs_session_login] Aucun cookie de session trouve. La connexion a-t-elle reussi ?');
            process.exit(2);
        }

        const device = cookies.find(c => c.name === 'francestudent-device-id');
        const payload = {
            exported_at: new Date().toISOString(),
            source: 'chrome-profile',
            device_id: device ? device.value : null,
            cookies: cookies.map(c => ({
                name: c.name,
                value: c.value,
                domain: c.domain,
                path: c.path,
                expires: c.expires,
                httpOnly: c.httpOnly,
                secure: c.secure,
                sameSite: c.sameSite,
            })),
        };
        fs.writeFileSync(OUTPUT, JSON.stringify(payload, null, 2), 'utf8');
        console.log(`[fs_session_login] Session exportee vers ${OUTPUT} (${cookies.length} cookies).`);
    } finally {
        await browser.close();
    }
}

main().catch(err => {
    console.error(`[fs_session_login] ERREUR: ${err.message}`);
    process.exit(1);
});
